"""Exact stored AWC tag bytes selected by source-local directory ordinals.

The complete supplied container is revalidated before any payload is returned.
No packet decoding, file carving, joins, song naming or station inference occurs.
"""
from __future__ import annotations

import hashlib
import os
import stat
import struct

from . import awc_inputs, media


def _options(stream_index, tag_index, expected_sha256, max_records,
             max_input_bytes, max_output_bytes):
    if any(type(v) is not int or v < 0 for v in (stream_index, tag_index)):
        raise ValueError('AWC stream and tag indices must be nonnegative integers')
    awc_inputs._limit(max_records, awc_inputs.MAX_RECORDS, 'AWC export record limit')
    awc_inputs._limit(max_input_bytes, media.MAX_AWC_SIZE, 'AWC export input byte limit')
    if type(max_output_bytes) is not int or not 0 <= max_output_bytes <= media.MAX_AWC_SIZE:
        raise ValueError('AWC export output byte limit is outside its supported range')
    if expected_sha256 is not None and (
            not isinstance(expected_sha256, str) or len(expected_sha256) != 64
            or any(c not in '0123456789abcdef' for c in expected_sha256)):
        raise ValueError('expected AWC hash must be one lowercase SHA-256')


def export_tag(data, *, stream_index, tag_index, expected_sha256=None,
               max_records=100000, max_input_bytes=awc_inputs.DEFAULT_INPUT_BYTES,
               max_output_bytes=media.MAX_AWC_SIZE):
    """Return (source-backed report, exact tag bytes), or raise atomically.

    Selection is by directory ordinal, so repeated IDs and tag kinds remain
    distinct. Input verification, metadata allocation and exported payload work
    share max_records. No saved index is accepted and no files are written.
    """
    _options(stream_index, tag_index, expected_sha256, max_records,
             max_input_bytes, max_output_bytes)
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('AWC tag export requires source bytes')
    if len(data) > max_input_bytes:
        raise awc_inputs.AWCInputLimitError('AWC export source exceeds input byte limit')
    data = bytes(data)
    used = 0

    def charge(amount=1):
        nonlocal used
        if amount > max_records - used:
            raise awc_inputs.AWCInputLimitError('AWC export exceeds its shared record budget')
        used += amount

    charge(1 + max(1, (len(data) + 4095) // 4096))
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError('AWC input differs from its expected SHA-256')
    awc_inputs._preflight(data, charge, False)
    metadata = media.validate_awc(data)
    if metadata is None or not metadata['exact_length'] or metadata['size'] != len(data):
        raise ValueError('AWC export requires complete supported native metadata')
    if stream_index >= metadata['streams']:
        raise ValueError('AWC stream index exceeds the stored directory')
    stream = metadata['stream_list'][stream_index]
    if tag_index >= stream['tags']:
        raise ValueError('AWC tag index exceeds the selected stored stream')
    chunk = stream['chunks'][tag_index]
    length, at = chunk['byte_length'], chunk['data_offset']
    if length > max_output_bytes:
        raise awc_inputs.AWCInputLimitError('AWC selected tag exceeds output byte limit')
    charge(1 + stream_index + max(1, (length + 4095) // 4096))
    # Re-read only the selected descriptor's serialized location; the complete
    # table and every payload span have already passed the existing index grammar.
    earlier = sum(s['tags'] for s in metadata['stream_list'][:stream_index])
    descriptor_at = metadata['header_size'] - metadata['tags'] * 8 + 8 * (earlier + tag_index)
    word, = struct.unpack_from('<Q', data, descriptor_at)
    payload = data[at:at + length]
    report = dict(format='gta6x-awc-tag-export-v1', status='complete',
        source_sha256=digest, byte_length=len(data),
        expected_sha256_verified=expected_sha256 is not None,
        metadata=metadata, work_records=used,
        selection=dict(stream_index=stream_index, tag_index=tag_index,
            stream_id_u29=stream['id'], kind=chunk['type'],
            descriptor_data_offset=descriptor_at, descriptor_bits=f'0x{word:016x}',
            data_offset=at, byte_length=length,
            payload_sha256=hashlib.sha256(payload).hexdigest()),
        payload_preserved=True, encoded_audio_validated=False,
        archive_search_performed=False, sources_joined=False, saved_metadata_trusted=False,
        interpretation='Exact stored tag bytes only; no decoded audio, original game provenance, '
                       'song title, station membership or tag-name interpretation')
    return report, payload


def export_tag_file(path, *, stream_index, tag_index, expected_sha256=None,
                    protected_outputs=(), max_records=100000,
                    max_input_bytes=awc_inputs.DEFAULT_INPUT_BYTES,
                    max_output_bytes=media.MAX_AWC_SIZE):
    """Read one checked immutable snapshot and export a selected tag in memory.

    Options, regular-file status, source/output aliases and file size are checked
    before reads. Opened identity, size and timestamps must remain unchanged.
    """
    _options(stream_index, tag_index, expected_sha256, max_records,
             max_input_bytes, max_output_bytes)
    path = awc_inputs._path(path)
    if not isinstance(protected_outputs, (list, tuple)) or len(protected_outputs) > 1024:
        raise ValueError('protected AWC outputs require a bounded path list')
    outputs = tuple(awc_inputs._path(p) for p in protected_outputs)
    source = os.stat(path)
    if not stat.S_ISREG(source.st_mode):
        raise ValueError('AWC export input must be a regular file')
    if source.st_size > max_input_bytes:
        raise awc_inputs.AWCInputLimitError('AWC export source exceeds input byte limit')
    for output in outputs:
        if os.path.realpath(output) == os.path.realpath(path):
            raise ValueError('AWC export would overwrite an input')
        try:
            target = os.stat(output)
        except FileNotFoundError:
            continue
        if (target.st_dev, target.st_ino) == (source.st_dev, source.st_ino):
            raise ValueError('AWC export would overwrite an input')

    def identity(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    with open(path, 'rb') as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode) or identity(before) != identity(source):
            raise ValueError('AWC export input changed after preflight')
        data = handle.read(source.st_size + 1)
        after = os.fstat(handle.fileno())
    if len(data) != source.st_size or identity(after) != identity(before):
        raise ValueError('AWC export input changed during read')
    return export_tag(data, stream_index=stream_index, tag_index=tag_index,
        expected_sha256=expected_sha256, max_records=max_records,
        max_input_bytes=max_input_bytes, max_output_bytes=max_output_bytes)
