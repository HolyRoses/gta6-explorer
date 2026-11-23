"""Declared-duration Ogg Opus export using public packet/container facts.

Retained packets are unchanged. Granules count packet samples from zero;
pre-skip and final trimming express an explicit output interval. The inherited
312-frame default is an assumption, not a recovered AWC encoder-delay field.
Legacy exports in audio.py are independent and unchanged. Packet framing is
checked here; compressed codec contents are not decoded or semantically proved.
"""
from __future__ import annotations

import struct

from . import audio, audio_pcm

MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_TITLE_BYTES = 4096


def packet_frames(packet: bytes) -> int:
    """Validate RFC 6716 frame packing and return its 48 kHz duration.

    This checks lengths/counts/padding extents, not the compressed frame bits.
    Zero-byte source frames are permitted by Opus framing; none are inserted.
    """
    if not isinstance(packet, bytes) or not 1 <= len(packet) <= audio.BLOCK - 2:
        raise ValueError('invalid or oversized Opus packet')
    end, pos, code = len(packet), 1, packet[0] & 3

    def size_word():
        nonlocal pos
        if pos >= end:
            raise ValueError('truncated Opus frame-length header')
        value = packet[pos]
        pos += 1
        if value >= 252:
            if pos >= end:
                raise ValueError('truncated two-byte Opus frame length')
            value += 4 * packet[pos]
            pos += 1
        return value

    if code == 0:
        sizes = [end - pos]
    elif code == 1:
        if (end - pos) % 2:
            raise ValueError('Opus equal-frame payload has an odd byte count')
        sizes = [(end - pos) // 2] * 2
    elif code == 2:
        first = size_word()
        sizes = [first, end - pos - first]
    else:
        if pos >= end:
            raise ValueError('truncated Opus frame-count header')
        flags = packet[pos]
        pos += 1
        count = flags & 63
        if not 1 <= count <= 48:
            raise ValueError('Opus packet frame count is outside 1..48')
        if flags & 64:
            padding = 0
            while True:
                if pos >= end:
                    raise ValueError('truncated Opus padding length')
                value = packet[pos]
                pos += 1
                padding += 254 if value == 255 else value
                if value != 255:
                    break
            end -= padding
            if end < pos:
                raise ValueError('Opus padding exceeds packet bounds')
        if flags & 128:
            sizes = [size_word() for _ in range(count - 1)]
            sizes.append(end - pos - sum(sizes))
        else:
            if (end - pos) % count:
                raise ValueError('Opus CBR payload does not divide into its frame count')
            sizes = [(end - pos) // count] * count
    if any(size < 0 or size > 1275 for size in sizes):
        raise ValueError('Opus frame size exceeds its packet or public size limit')
    frames = audio.packet_samples(packet)
    if not 1 <= frames <= audio_pcm.MAX_PACKET_FRAMES:
        raise ValueError('Opus packet duration exceeds 120 ms')
    return frames


def ogg_opus(packets, frames: int, *, channels: int = 1, pre_skip: int = audio.PRE_SKIP,
             title: str = 'gta6x', max_frames=None, max_input_bytes=None):
    """Return (Ogg, metadata) for an explicitly selected decoded interval.

    All supplied packet framing is checked, including later omitted packets.
    Only the unchanged packet prefix needed to cover pre_skip+frames is kept;
    EOS trims its last packet and granules never run backwards. No codec is
    invoked, packet rewritten, missing audio synthesized, or original alignment
    inferred. Compressed contents require a decoder for stronger validation.
    """
    if type(channels) is not int or channels not in (1, 2):
        raise ValueError('declared Ogg supports one or two channels')
    if max_frames is None:
        max_frames = audio_pcm.MAX_PCM_BYTES // (2 * channels)
    elif type(max_frames) is not int or not 1 <= max_frames <= 0xffffffff:
        raise ValueError('invalid explicit Ogg frame bound')
    if max_input_bytes is None:
        max_input_bytes = audio_pcm.MAX_INPUT_BYTES
    elif type(max_input_bytes) is not int or not 1 <= max_input_bytes <= 256*1024*1024:
        raise ValueError('invalid explicit Ogg input bound')
    if type(frames) is not int or frames < 1 or frames > max_frames:
        raise ValueError('declared Ogg duration exceeds the supported PCM-equivalent bound')
    if type(pre_skip) is not int or not 0 <= pre_skip <= audio_pcm.MAX_PACKET_FRAMES:
        raise ValueError('Ogg pre-skip must be between 0 and 5760 frames')
    if not isinstance(title, str):
        raise ValueError('Ogg title must be text')
    try:
        comment = ('TITLE=' + title).encode('utf-8')
    except UnicodeEncodeError as exc:
        raise ValueError('Ogg title must be valid UTF-8 text') from exc
    if len(comment) > MAX_TITLE_BYTES:
        raise ValueError('Ogg title exceeds byte limit')
    if not isinstance(packets, (list, tuple)) or not 1 <= len(packets) <= audio_pcm.MAX_PACKETS:
        raise ValueError('Opus packets must be a nonempty bounded sequence')
    if any(not isinstance(packet, bytes) for packet in packets):
        raise ValueError('Opus packet entries must be bytes')
    if sum(map(len, packets)) > max_input_bytes:
        raise ValueError('Opus packet bytes exceed input limit')
    durations = [packet_frames(packet) for packet in packets]
    if audio.packet_channels(packets) != channels:
        raise ValueError('Opus packet channel profile differs from Ogg header')
    total, selected, retained_frames = 0, None, None
    end = pre_skip + frames
    for i, duration in enumerate(durations):
        total += duration
        if total > max_frames:
            raise ValueError('source Opus duration exceeds PCM-equivalent processing limit')
        if selected is None and total >= end:
            selected, retained_frames = i + 1, total
    if selected is None:
        raise ValueError('Opus packets do not cover pre-skip plus declared duration')
    head = b'OpusHead' + struct.pack('<BBHIhB', 1, channels, pre_skip, audio.RATE, 0, 0)
    vendor = b'gta6x'
    tags = (b'OpusTags' + struct.pack('<I', len(vendor)) + vendor
            + struct.pack('<I', 1) + struct.pack('<I', len(comment)) + comment)
    out = bytearray()
    audio._page(out, 0, 0, 2, head)
    audio._page(out, 1, 0, 0, tags)
    granule = 0
    for i in range(selected):
        granule += durations[i]
        last = i + 1 == selected
        audio._page(out, i + 2, end if last else granule, 4 if last else 0, packets[i])
        if len(out) > MAX_OUTPUT_BYTES:
            raise ValueError('declared Ogg output exceeds size limit')
    return bytes(out), dict(profile='declared_duration_ogg_opus_v1', channels=channels,
        sample_rate=audio.RATE, output_frames=frames, pre_skip=pre_skip,
        source_packet_count=len(packets), retained_packet_count=selected,
        dropped_tail_packets=len(packets) - selected, source_decoded_frames=total,
        retained_decoded_frames=retained_frames, final_granule=end,
        final_packet_trim_frames=retained_frames - end,
        timing_policy='explicit pre-skip plus declared output duration; original alignment unconfirmed',
        validation_scope='packet framing/duration and container metadata; codec frame bits remain undecoded')


def extract_ogg(bank: bytes, stream: dict, *, pre_skip: int = audio.PRE_SKIP,
                title: str = 'gta6x'):
    """Declared-duration remux for the observed standalone mono AWC profile."""
    if stream.get('music') or stream.get('codec') != 0x0b or stream.get('codec_name') != 'opus':
        raise ValueError('declared Ogg supports standalone AWC Opus streams only')
    if stream.get('sample_rate') != audio.RATE or type(stream.get('channels')) is not int or stream.get('channels') != 1:
        raise ValueError('declared Ogg requires the observed mono 48 kHz AWC profile')
    at, size = stream.get('data_offset'), stream.get('data_bytes')
    if (type(at) is not int or type(size) is not int or at < 0 or size <= 0
            or size > audio_pcm.MAX_INPUT_BYTES or at > len(bank) - size):
        raise ValueError('AWC Opus data span exceeds complete container bounds')
    packets = audio_pcm.strict_packets(bank[at:at + size])
    result, info = ogg_opus(packets, stream.get('samples'), channels=1,
                            pre_skip=pre_skip, title=title)
    info.update(declared_samples=stream['samples'], source_data_bytes=size,
        pre_skip_assumption='312 inherited from existing Ogg policy' if pre_skip == 312 else 'explicit caller value')
    return result, info
