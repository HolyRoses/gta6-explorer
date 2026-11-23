"""Strict AWC Opus framing and optional libopus PCM/WAV conversion.

The optional system library is used through its public C API. No decoder is
bundled. Default AWC export preserves the observed mono/48 kHz declared-frame
policy. An opt-in packet-sequence policy exports mono/stereo decoder output
without interpreting the AWC sample count. Original sample alignment remains
unknown; neither policy substitutes silence for missing packets.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import io
import struct
import sys
import wave

from . import audio

RATE = 48000
MAX_INPUT_BYTES = 64 * 1024 * 1024
MAX_PCM_BYTES = 128 * 1024 * 1024
MAX_PACKETS = 1000000
MAX_PACKET_FRAMES = 5760


class OpusUnavailableError(RuntimeError):
    """An optional compatible libopus library could not be loaded."""


def _limit(value, name, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError(f'{name} must be a {"nonnegative" if zero else "positive"} integer')
    return value


def strict_packets(data: bytes) -> list[bytes]:
    """Read complete observed 2 KiB packet blocks; reject bad records/padding.

    A zero u16 length or a final single byte ends a block only when all its
    remaining bytes are zero. A truncated nonzero record never ends a block
    successfully. Full observed allocation blocks are required.
    """
    if not data or len(data) > MAX_INPUT_BYTES or len(data) % audio.BLOCK:
        raise ValueError('AWC Opus data must contain complete bounded 2 KiB blocks')
    packets = []
    for offset in range(0, len(data), audio.BLOCK):
        block = data[offset:offset + audio.BLOCK]
        at = 0
        while at + 2 <= len(block):
            size = struct.unpack_from('<H', block, at)[0]
            if size == 0:
                break
            if size > len(block) - at - 2:
                raise ValueError('truncated AWC Opus packet crosses its block')
            if len(packets) >= MAX_PACKETS:
                raise ValueError('AWC Opus packet count exceeds limit')
            packets.append(block[at + 2:at + 2 + size])
            at += 2 + size
        if any(block[at:]):
            raise ValueError('nonzero AWC Opus block padding')
    if not packets:
        raise ValueError('no Opus packets in AWC data')
    return packets


class _Decoder:
    def __init__(self, channels, library_path):
        path = library_path if library_path is not None else ctypes.util.find_library('opus')
        if not path:
            raise OpusUnavailableError('libopus is unavailable; install it or provide --opus-library')
        try:
            self.lib = ctypes.CDLL(path)
            self.lib.opus_decoder_create.argtypes = [ctypes.c_int32, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
            self.lib.opus_decoder_create.restype = ctypes.c_void_p
            self.lib.opus_decoder_destroy.argtypes = [ctypes.c_void_p]
            self.lib.opus_decoder_destroy.restype = None
            self.lib.opus_decode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int32,
                                           ctypes.POINTER(ctypes.c_int16), ctypes.c_int, ctypes.c_int]
            self.lib.opus_decode.restype = ctypes.c_int
            self.lib.opus_packet_get_nb_samples.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int32, ctypes.c_int32]
            self.lib.opus_packet_get_nb_samples.restype = ctypes.c_int
            self.lib.opus_get_version_string.argtypes = []
            self.lib.opus_get_version_string.restype = ctypes.c_char_p
        except (OSError, AttributeError, TypeError) as exc:
            raise OpusUnavailableError('could not load a compatible libopus public API') from exc
        self.channels = channels
        self.version = self.lib.opus_get_version_string().decode('utf-8', 'replace')
        error = ctypes.c_int()
        self.state = self.lib.opus_decoder_create(RATE, channels, ctypes.byref(error))
        if error.value != 0 or not self.state:
            if self.state:
                self.lib.opus_decoder_destroy(self.state)
                self.state = None
            raise ValueError(f'libopus decoder initialization failed ({error.value})')
        self.buffer = (ctypes.c_int16 * (MAX_PACKET_FRAMES * channels))()

    def close(self):
        if self.state:
            self.lib.opus_decoder_destroy(self.state)
            self.state = None

    def decode(self, packet):
        raw = (ctypes.c_ubyte * len(packet)).from_buffer_copy(packet)
        expected = self.lib.opus_packet_get_nb_samples(raw, len(packet), RATE)
        if not 1 <= expected <= MAX_PACKET_FRAMES:
            raise ValueError(f'invalid Opus packet duration ({expected})')
        frames = self.lib.opus_decode(self.state, raw, len(packet), self.buffer, MAX_PACKET_FRAMES, 0)
        if frames < 0:
            raise ValueError(f'libopus rejected an Opus packet ({frames})')
        if frames != expected:
            raise ValueError('libopus decoded frame count differs from packet duration')
        # The public API writes host-endian int16; WAV is always little-endian.
        raw_pcm = bytes(self.buffer)[:frames * self.channels * 2]
        if sys.byteorder != 'little':
            raw_pcm = b''.join(raw_pcm[i:i + 2][::-1] for i in range(0, len(raw_pcm), 2))
        return raw_pcm


def decode_packets(packets, *, channels: int, frames: int, pre_skip: int = audio.PRE_SKIP,
                   library_path=None, max_pcm_bytes: int = MAX_PCM_BYTES):
    """Decode ordered mono/stereo packets, applying an explicit bounded trim.

    Returns (little-endian interleaved PCM16, metadata). Every packet is decoded
    serially, including trimmed tails; malformed input refuses the entire result.
    No PLC/FEC or implicit missing samples are used. ``frames`` is per channel.
    """
    return _decode_packets(packets, channels=channels, frames=frames, pre_skip=pre_skip,
        library_path=library_path, max_pcm_bytes=max_pcm_bytes, packet_sequence=False)


def decode_packet_sequence(packets, *, channels: int, pre_skip: int = 0,
                           library_path=None, max_pcm_bytes: int = MAX_PCM_BYTES):
    """Decode every packet into the requested output layout, without end trim.

    Mono/stereo packet switching is legal (RFC 6716 section 2.1.2); libopus
    produces the caller's fixed output channel count. ``pre_skip`` is an
    explicit caller selection, not an AWC encoder-delay measurement. The
    resulting interval is a packet sequence, not a recovered game interval.
    """
    return _decode_packets(packets, channels=channels, frames=None, pre_skip=pre_skip,
        library_path=library_path, max_pcm_bytes=max_pcm_bytes, packet_sequence=True)


def _decode_packets(packets, *, channels, frames, pre_skip, library_path,
                    max_pcm_bytes, packet_sequence):
    if type(channels) is not int or channels not in (1, 2):
        raise ValueError('Opus PCM supports one or two channels')
    if not packet_sequence:
        _limit(frames, 'frames')
    _limit(pre_skip, 'pre_skip', zero=True)
    _limit(max_pcm_bytes, 'max_pcm_bytes')
    if max_pcm_bytes > MAX_PCM_BYTES:
        raise ValueError('Opus PCM processing limit exceeds the supported maximum')
    if pre_skip > MAX_PACKET_FRAMES or (frames is not None and frames > max_pcm_bytes // (2 * channels)):
        raise ValueError('Opus PCM requested duration exceeds output limit')
    if not isinstance(packets, (list, tuple)) or not 1 <= len(packets) <= MAX_PACKETS:
        raise ValueError('Opus packets must be a nonempty bounded sequence')
    if any(not isinstance(packet, bytes) or not 1 <= len(packet) <= audio.BLOCK - 2 for packet in packets):
        raise ValueError('invalid or oversized Opus packet')
    if sum(map(len, packets)) > MAX_INPUT_BYTES:
        raise ValueError('Opus packet bytes exceed input limit')
    if not packet_sequence and audio.packet_channels(packets) != channels:
        raise ValueError('Opus packet channel profile differs from requested channels')
    decoded_frames = 0
    output = bytearray()
    decoder = _Decoder(channels, library_path)
    try:
        for packet in packets:
            pcm = decoder.decode(packet)
            if not pcm or len(pcm) % (2 * channels):
                raise ValueError('libopus returned an invalid PCM frame span')
            count = len(pcm) // (2 * channels)
            if count > MAX_PACKET_FRAMES:
                raise ValueError('libopus returned too many PCM frames')
            end = decoded_frames + count
            if end * channels * 2 > max_pcm_bytes:
                raise ValueError('decoded Opus duration exceeds PCM processing limit')
            first = max(decoded_frames, pre_skip)
            last = end if packet_sequence else min(end, pre_skip + frames)
            if first < last:
                output.extend(pcm[(first - decoded_frames) * channels * 2:(last - decoded_frames) * channels * 2])
            decoded_frames = end
        if packet_sequence:
            frames = decoded_frames - pre_skip
            if frames <= 0:
                raise ValueError('decoded Opus packet sequence ends before selected pre-skip')
        if decoded_frames < pre_skip + frames:
            raise ValueError('decoded Opus has fewer frames than pre-skip plus declared duration')
        if len(output) != frames * channels * 2:
            raise ValueError('Opus trim did not produce the exact requested PCM frame count')
        info = dict(sample_rate=RATE, channels=channels, sample_width=2,
            output_frames=frames, decoded_frames=decoded_frames, pre_skip=pre_skip,
            tail_discarded_frames=decoded_frames - pre_skip - frames,
            packet_count=len(packets), decoder=decoder.version,
            timing_policy='explicit pre-skip then exact requested per-channel frames; original alignment unconfirmed')
        if packet_sequence:
            mono = sum(not (packet[0] & 4) for packet in packets)
            info.update(packet_mono_count=mono, packet_stereo_count=len(packets)-mono,
                timing_policy='complete decoded packet sequence after selected pre-skip; original game interval unconfirmed',
                output_channel_policy='caller-declared fixed decoder output; packet mono/stereo switching allowed')
        return bytes(output), info
    finally:
        decoder.close()


def wav_bytes(pcm: bytes, *, channels: int, sample_rate: int = RATE) -> bytes:
    """Wrap exact little-endian interleaved PCM16 without resampling."""
    if type(channels) is not int or channels not in (1, 2) or type(sample_rate) is not int or sample_rate != RATE:
        raise ValueError('WAV profile requires mono/stereo PCM16 at 48 kHz')
    if not pcm or len(pcm) % (2 * channels) or len(pcm) > MAX_PCM_BYTES:
        raise ValueError('invalid or oversized PCM16 frame span')
    output = io.BytesIO()
    with wave.open(output, 'wb') as dest:
        dest.setnchannels(channels); dest.setsampwidth(2); dest.setframerate(sample_rate)
        dest.writeframes(pcm)
    return output.getvalue()


def extract_wav(bank: bytes, stream: dict, *, library_path=None,
                pre_skip: int | None = None, max_pcm_bytes: int = MAX_PCM_BYTES,
                interval_policy: str = 'declared'):
    """Return standalone AWC Opus WAV under an explicit sample-interval policy.

    Default ``declared`` preserves the mono declared-frame policy and inherited
    312 pre-skip. Opt-in ``packet-sequence`` accepts declared mono/stereo output
    channels, defaults to zero pre-skip and keeps every decoded trailing frame.
    It never treats the AWC sample word as a stereo per-channel duration.
    """
    if interval_policy not in ('declared', 'packet-sequence'):
        raise ValueError('unsupported AWC WAV interval policy')
    if pre_skip is None:
        pre_skip = audio.PRE_SKIP if interval_policy == 'declared' else 0
    if stream.get('music') or stream.get('codec') != 0x0b or stream.get('codec_name') != 'opus':
        raise ValueError('WAV export supports standalone AWC Opus streams only')
    channels = stream.get('channels')
    if (stream.get('sample_rate') != RATE or type(channels) is not int
            or channels not in ((1,) if interval_policy == 'declared' else (1, 2))):
        if interval_policy == 'declared':
            raise ValueError('WAV export requires the observed mono 48 kHz AWC profile')
        raise ValueError('WAV export requires supported declared channels at 48 kHz for its interval policy')
    if interval_policy == 'packet-sequence' and (type(stream.get('samples')) is not int
            or not 0 <= stream['samples'] <= 0xffffffff):
        raise ValueError('packet-sequence export requires a bounded raw AWC sample word')
    frames = (_limit(stream.get('samples'), 'AWC declared samples')
              if interval_policy == 'declared' else None)
    at, length = stream.get('data_offset'), stream.get('data_bytes')
    if (type(at) is not int or type(length) is not int or at < 0 or length <= 0
            or length > MAX_INPUT_BYTES or at > len(bank) - length):
        raise ValueError('AWC Opus data span exceeds complete container bounds')
    packets = strict_packets(bank[at:at + length])
    if interval_policy == 'packet-sequence':
        pcm, info = decode_packet_sequence(packets, channels=channels, pre_skip=pre_skip,
            library_path=library_path, max_pcm_bytes=max_pcm_bytes)
        info.update(profile='awc_opus_packet_sequence_pcm_v1', interval_policy=interval_policy,
            declared_samples=stream.get('samples'), declared_samples_applied=False,
            pre_skip_assumption='explicit output selection; original encoder delay unknown',
            source_data_bytes=length)
        return wav_bytes(pcm, channels=channels), info
    pcm, info = decode_packets(packets, channels=channels, frames=frames, pre_skip=pre_skip,
        library_path=library_path, max_pcm_bytes=max_pcm_bytes)
    info.update(profile='observed_awc_mono_opus_pcm_v1', declared_samples=frames,
                pre_skip_assumption='312 inherited from existing Ogg policy' if pre_skip == 312 else 'explicit caller value',
                source_data_bytes=length)
    return wav_bytes(pcm, channels=1), info
