"""Bounded offline remux of one checked standalone AWC Opus stream.

Stored packets are retained unchanged under the existing declared-duration Ogg
policy. Encoder alignment and compressed frame contents remain unconfirmed.
"""
from __future__ import annotations

import hashlib
import os
import stat
import struct

from . import audio, audio_ogg, audio_pcm, awc_inputs, media


def _options(stream_index, pre_skip, expected_sha256, max_records,
             max_input_bytes, max_output_bytes):
    if type(stream_index) is not int or stream_index < 0:
        raise ValueError('AWC stream index must be a nonnegative integer')
    if type(pre_skip) is not int or not 0 <= pre_skip <= audio_pcm.MAX_PACKET_FRAMES:
        raise ValueError('AWC Ogg pre-skip must be between 0 and 5760 frames')
    awc_inputs._limit(max_records, awc_inputs.MAX_RECORDS, 'AWC Ogg record limit')
    awc_inputs._limit(max_input_bytes, media.MAX_AWC_SIZE, 'AWC Ogg input byte limit')
    awc_inputs._limit(max_output_bytes, audio_ogg.MAX_OUTPUT_BYTES, 'AWC Ogg output byte limit')
    if expected_sha256 is not None and (
            not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_sha256)):
        raise ValueError('expected AWC hash must be one lowercase SHA-256')


def export_ogg(data, *, stream_index, pre_skip=audio.PRE_SKIP,
               expected_sha256=None, max_records=100000,
               max_input_bytes=awc_inputs.DEFAULT_INPUT_BYTES,
               max_output_bytes=audio_ogg.MAX_OUTPUT_BYTES):
    """Return (source-backed report, Ogg bytes), or refuse the entire operation.

    Input selection uses directory ordinals, never stream-ID uniqueness or saved
    metadata. The entire exact container and all selected packet framing are
    checked, including omitted tail packets. No codec library or writes are used.
    """
    _options(stream_index, pre_skip, expected_sha256, max_records,
             max_input_bytes, max_output_bytes)
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('AWC Ogg export requires source bytes')
    if len(data) > max_input_bytes:
        raise awc_inputs.AWCInputLimitError('AWC Ogg input exceeds byte limit')
    data = bytes(data)
    used = 0

    def charge(amount=1):
        nonlocal used
        if amount > max_records - used:
            raise awc_inputs.AWCInputLimitError('AWC Ogg export exceeds shared record limit')
        used += amount

    charge(1 + max(1, (len(data) + 4095) // 4096))
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('AWC Ogg input differs from expected SHA-256')
    awc_inputs._preflight(data, charge, False)
    metadata = media.validate_awc(data)
    if metadata is None or not metadata['exact_length'] or metadata['size'] != len(data):
        raise ValueError('AWC Ogg requires an exact complete supported container')
    if stream_index >= metadata['streams']:
        raise ValueError('AWC stream index exceeds stored directory')
    stream = metadata['stream_list'][stream_index]
    kinds = [chunk['type'] for chunk in stream['chunks']]
    charge(1 + len(kinds))
    if (kinds.count('0x76') != 1 or kinds.count('0x55') != 1 or '0x48' in kinds):
        raise ValueError('AWC Ogg requires unique sample-format/data tags and no music descriptor')
    if (stream.get('music') or stream.get('codec') != 11 or stream.get('codec_name') != 'opus'
            or stream.get('sample_rate') != audio.RATE or stream.get('channels') != 1):
        raise ValueError('AWC Ogg supports standalone mono 48 kHz Opus streams only')
    at, length, frames = stream['data_offset'], stream['data_bytes'], stream['samples']
    if (type(at) is not int or type(length) is not int or at < 0 or length <= 0
            or length > audio_pcm.MAX_INPUT_BYTES or at > len(data) - length
            or length % audio.BLOCK):
        raise ValueError('AWC Ogg data requires complete bounded 2 KiB blocks')
    if type(frames) is not int or not 1 <= frames <= audio_pcm.MAX_PCM_BYTES // 2:
        raise ValueError('AWC Ogg declared duration exceeds processing limit')
    # Meter every serialized packet before the existing list-producing reader.
    # Its record/padding grammar remains the authority for the actual packets.
    count = 0
    for block_at in range(at, at + length, audio.BLOCK):
        charge()
        cursor, end = block_at, block_at + audio.BLOCK
        while cursor + 2 <= end:
            size, = struct.unpack_from('<H', data, cursor)
            if not size:
                break
            if size > end - cursor - 2:
                raise ValueError('truncated AWC Ogg packet crosses its block')
            charge(3)
            count += 1
            if count > audio_pcm.MAX_PACKETS:
                raise ValueError('AWC Ogg packet count exceeds processing limit')
            cursor += 2 + size
        if any(data[cursor:end]):
            raise ValueError('nonzero AWC Ogg block padding')
    packets = audio_pcm.strict_packets(data[at:at + length])
    total, retained = 0, None
    output_size = 47 + 64  # Fixed OpusHead and gta6x TITLE/vendor pages.
    for i, packet in enumerate(packets):
        duration = audio_ogg.packet_frames(packet)
        total += duration
        if total > audio_pcm.MAX_PCM_BYTES // 2:
            raise ValueError('AWC Ogg source duration exceeds processing limit')
        if retained is None:
            output_size += 27 + len(packet) // 255 + 1 + len(packet)
            if total >= pre_skip + frames:
                retained = i + 1
    if retained is None:
        raise ValueError('AWC Ogg packets do not cover pre-skip plus declared duration')
    charge(3 + retained + (output_size + 4095) // 4096)
    if output_size > max_output_bytes:
        raise awc_inputs.AWCInputLimitError('AWC Ogg output exceeds byte limit')
    result, timing = audio_ogg.ogg_opus(packets, frames, channels=1, pre_skip=pre_skip)
    if len(result) != output_size:
        raise ValueError('AWC Ogg output does not match its preflighted layout')
    timing.update(declared_samples=frames, source_data_bytes=length,
                  pre_skip_assumption='312 inherited from existing Ogg policy' if pre_skip == 312
                                      else 'explicit caller value')
    report = dict(format='gta6x-awc-ogg-export-v1', status='complete',
        source_sha256=digest, byte_length=len(data),
        expected_sha256_verified=expected_sha256 is not None, metadata=metadata,
        selection=dict(stream_index=stream_index, stream_id_u29=stream['id'],
                       data_offset=at, byte_length=length),
        ogg=dict(byte_length=len(result), sha256=hashlib.sha256(result).hexdigest(), **timing),
        work_records=used, retained_packets_preserved=True, encoded_audio_decoded=False,
        archive_search_performed=False, sources_joined=False, saved_metadata_trusted=False,
        interpretation='Declared-duration standalone Opus remux only; original sample alignment, '
                       'compressed frame contents, song titles and station membership unconfirmed')
    return report, result


def export_ogg_file(path, *, stream_index, pre_skip=audio.PRE_SKIP,
                    expected_sha256=None, protected_outputs=(), max_records=100000,
                    max_input_bytes=awc_inputs.DEFAULT_INPUT_BYTES,
                    max_output_bytes=audio_ogg.MAX_OUTPUT_BYTES):
    """Read one bounded regular immutable snapshot; return report/Ogg in memory."""
    _options(stream_index, pre_skip, expected_sha256, max_records,
             max_input_bytes, max_output_bytes)
    path = awc_inputs._path(path)
    if not isinstance(protected_outputs, (list, tuple)) or len(protected_outputs) > 1024:
        raise ValueError('protected AWC Ogg outputs require a bounded path list')
    outputs = tuple(awc_inputs._path(p) for p in protected_outputs)
    source = os.stat(path)
    if not stat.S_ISREG(source.st_mode):
        raise ValueError('AWC Ogg input must be a regular file')
    if source.st_size > max_input_bytes:
        raise awc_inputs.AWCInputLimitError('AWC Ogg file exceeds input byte limit')
    for output in outputs:
        if os.path.realpath(output) == os.path.realpath(path):
            raise ValueError('AWC Ogg output aliases its input')
        try:
            info = os.stat(output)
        except FileNotFoundError:
            continue
        if (info.st_dev, info.st_ino) == (source.st_dev, source.st_ino):
            raise ValueError('AWC Ogg output aliases its input')

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    with open(path, 'rb') as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or identity(before) != identity(source):
            raise ValueError('AWC Ogg input changed after preflight')
        data = handle.read(source.st_size + 1)
        after = os.fstat(handle.fileno())
    if (len(data) != source.st_size or identity(after) != identity(before)
            or identity(os.stat(path)) != identity(source)):
        raise ValueError('AWC Ogg input changed during read')
    return export_ogg(data, stream_index=stream_index, pre_skip=pre_skip,
        expected_sha256=expected_sha256, max_records=max_records,
        max_input_bytes=max_input_bytes, max_output_bytes=max_output_bytes)
