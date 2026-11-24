"""Exact offline AWC indexing from explicit immutable container-file bytes.

Existing native metadata and optional radio grammars are reused. A complete
index is not encoded-audio validation, original game provenance, a song title
or station membership. No archive search, inner-magic scan or joining occurs.
"""
from __future__ import annotations

import hashlib
import os
import stat
import struct

from . import awc_radio, media

MAX_FILES = 256
DEFAULT_INPUT_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES = 512 * 1024 * 1024
MAX_RECORDS = awc_radio.MAX_RECORDS


class AWCInputLimitError(ValueError):
    """A complete offline query cannot fit its shared processing limits."""


def _limit(value, maximum, label):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{label} must be an integer from 1 to {maximum}')


def _path(value):
    try:
        path = os.fspath(value)
    except TypeError as exc:
        raise ValueError('AWC inputs/outputs require text paths') from exc
    if not isinstance(path, str) or not path or '\0' in path:
        raise ValueError('AWC inputs/outputs require nonempty text paths')
    return path


def _preflight(data, charge, with_radio):
    """Bound index/format/radio allocation work before existing parsers run."""
    header = media.awc_header_length(data[:16])
    if header is None or header > len(data):
        raise ValueError('raw AWC input requires a complete supported container header')
    flags, streams = struct.unpack_from('<II', data, 4)
    charge(1 + 2 * streams)
    position = 16 + (4 if flags & media.AWC_FEATURE_PREFIX else 0)
    if flags & media.AWC_FEATURE_INDEX:
        position += streams * 2
    if flags & media.AWC_FEATURE_EXTRA:
        position += (streams + 1) * 4
    info = position
    position += streams * 4
    if position > header:
        raise ValueError('raw AWC stream directory exceeds its declared header')
    tags = sum(struct.unpack_from('<I', data, info + 4 * i)[0] >> 29
               for i in range(streams))
    charge(2 * tags)
    if position + tags * 8 != header:
        raise ValueError('raw AWC tags do not tile the declared header')
    extent, channels, radio_records = header, 0, 0
    for ordinal in range(tags):
        word, = struct.unpack_from('<Q', data, position + 8 * ordinal)
        kind, size, at = word >> 56, (word >> 28) & 0x0fffffff, word & 0x0fffffff
        if at > len(data) - size or size and at < header:
            raise ValueError('raw AWC chunk exceeds its container or overlaps the header')
        extent = max(extent, at + size)
        if kind == media.AWC_TAG_SAMPLE_FORMAT and size < 32:
            raise ValueError('unsupported AWC sample-format chunk shorter than its known metadata profile')
        if kind == media.AWC_TAG_STREAM_FORMAT and size >= 12:
            count, = struct.unpack_from('<I', data, at + 8)
            if 0 < count <= 32:
                if 12 + 16 * count > size:
                    raise ValueError('AWC music descriptor channels exceed their declared chunk')
                channels += count
                charge(2 * count)
        if with_radio and kind in (0xa3, 0xbd):
            # A marker may produce both one marker row and one chapter row.
            # Reserve the complete possible product, not a prefix from a parser
            # that retains table-level refusals instead of raising on its cap.
            radio_records += 1 + (2 * (size // 16) if kind == 0xbd else size // 4)
    if extent != len(data):
        raise ValueError('raw AWC input has trailing bytes outside its exact tag-derived extent')
    if with_radio:
        # inspect_bank repeats native metadata parsing and walks all stream/tag
        # rows. Reserve that work as well as all potential table output.
        charge(1 + 2 * streams + 2 * tags + 2 * channels + radio_records)
    return radio_records


def inspect_files(paths, *, with_radio=False, expected_sha256=None,
                  protected_outputs=(), max_records=100000,
                  max_input_bytes=DEFAULT_INPUT_BYTES):
    """Reparse complete selected AWC files or refuse the whole batch.

    Path/regular-file/alias/aggregate-size checks precede payload reads. Source
    identity and size are checked again on open; optional SHA-256 pins identify
    the exact bytes. All files share verification, index and radio work. Radio
    unsupported/refused tables stay explicit, while malformed containers, hash
    mismatches and budget exhaustion raise without a successful file prefix.
    The API writes no files and accepts no saved parse results.
    """
    _limit(max_records, MAX_RECORDS, 'AWC record limit')
    _limit(max_input_bytes, MAX_INPUT_BYTES, 'AWC input byte limit')
    if type(with_radio) is not bool:
        raise ValueError('AWC with_radio must be boolean')
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_FILES:
        raise ValueError('select 1..256 raw AWC files')
    if not isinstance(protected_outputs, (list, tuple)) or len(protected_outputs) > 1024:
        raise ValueError('protected AWC outputs require a bounded path list')
    paths = tuple(_path(p) for p in paths)
    outputs = tuple(_path(p) for p in protected_outputs)
    if expected_sha256 is None:
        hashes = (None,) * len(paths)
    else:
        if (not isinstance(expected_sha256, (list, tuple)) or len(expected_sha256) != len(paths)
                or any(not isinstance(h, str) or len(h) != 64
                       or any(c not in '0123456789abcdef' for c in h) for h in expected_sha256)):
            raise ValueError('expected AWC hashes require one lowercase SHA-256 per input')
        hashes = tuple(expected_sha256)
    output_paths = {os.path.realpath(p) for p in outputs}
    output_ids = set()
    for path in outputs:
        try:
            info = os.stat(path)
        except FileNotFoundError:
            continue
        output_ids.add((info.st_dev, info.st_ino))
    plan, identities, total_bytes = [], set(), 0
    for path, expected in zip(paths, hashes):
        info = os.stat(path)
        identity = info.st_dev, info.st_ino
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('raw AWC inputs must be regular files')
        if identity in identities:
            raise ValueError('duplicate or aliased raw AWC input')
        if identity in output_ids or os.path.realpath(path) in output_paths:
            raise ValueError('AWC output would overwrite an input')
        if info.st_size > media.MAX_AWC_SIZE:
            raise AWCInputLimitError('raw AWC file exceeds its source byte limit')
        total_bytes += info.st_size
        if total_bytes > max_input_bytes:
            raise AWCInputLimitError('raw AWC inputs exceed aggregate byte limit')
        identities.add(identity)
        plan.append((path, info, expected))
    used = 0

    def charge(amount=1):
        nonlocal used
        if amount > max_records - used:
            raise AWCInputLimitError('raw AWC query exceeds its shared record budget')
        used += amount

    charge(1 + len(plan) + sum(max(1, (info.st_size + 4095) // 4096)
                               for _, info, _ in plan))
    rows = []
    summary = dict(files=len(plan), input_bytes=total_bytes, streams=0, tags=0,
                   radio_tables=0, radio_markers=0, radio_chapters=0,
                   radio_seek_entries=0, radio_incomplete=0)
    for path, info, expected in plan:
        with open(path, 'rb') as handle:
            now = os.fstat(handle.fileno())
            if (not stat.S_ISREG(now.st_mode) or now.st_size != info.st_size
                    or (now.st_dev, now.st_ino) != (info.st_dev, info.st_ino)):
                raise ValueError('AWC input identity or size changed after preflight')
            data = handle.read(info.st_size + 1)
        if len(data) != info.st_size:
            raise ValueError('AWC input size changed during read')
        digest = hashlib.sha256(data).hexdigest()
        if expected is not None and digest != expected:
            raise ValueError('AWC input differs from its expected SHA-256')
        radio_records = _preflight(data, charge, with_radio)
        metadata = media.validate_awc(data)
        if metadata is None or not metadata['exact_length'] or metadata['size'] != len(data):
            raise ValueError('raw AWC input has malformed or unsupported native metadata')
        row = dict(file=path, bytes=len(data), sha256=digest,
                   expected_sha256_verified=expected is not None, metadata=metadata)
        summary['streams'] += metadata['streams']
        summary['tags'] += metadata['tags']
        if with_radio:
            try:
                radio = awc_radio.inspect_bank(data, max_records=max(1, radio_records))
            except ValueError as exc:
                radio = dict(status='unsupported', reason=str(exc), tables=[],
                             summary=dict(nodes=0, markers=0, chapters=0, seek_entries=0))
            row['radio'] = radio
            summary['radio_tables'] += len(radio['tables'])
            summary['radio_markers'] += radio['summary']['markers']
            summary['radio_chapters'] += radio['summary']['chapters']
            summary['radio_seek_entries'] += radio['summary']['seek_entries']
            summary['radio_incomplete'] += radio['status'] != 'parsed'
        rows.append(row)
    summary['work_records'] = used
    return dict(format='gta6x-raw-awc-inspection-v1',
                status='partial' if summary['radio_incomplete'] else 'complete',
                files=rows, summary=summary, archive_search_performed=False,
                sources_joined=False, saved_metadata_trusted=False,
                encoded_audio_validated=False,
                interpretation='Exact supplied AWC container index and optional raw radio evidence only; '
                'no original game provenance, decoded audio, song title or station membership claim.')
