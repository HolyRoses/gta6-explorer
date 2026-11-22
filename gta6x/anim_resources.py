"""Bounded 0DRP resource metadata from direct animation-archive observations.

Joins physically adjacent zlib pages at checked zero padding. Local virtual
spans supply raw structure/field, enum/member and data-block tables. Unknown
header words and type meanings remain explicit. No clip/curve decoder, external
implementation, title-specific schema table or game fixture is used.
"""
from __future__ import annotations

import hashlib
import os
import struct

from . import rpf, zlibcarve

VIRTUAL_BASE = 0x50000000
PAGE_UNIT = 65536
MAX_RESOURCE = 16 * 1024 * 1024
MAX_SEGMENTS = 256
HEADER_SIZE = 80


class ResourceLimitError(ValueError):
    """Resource metadata exceeds an explicit output or input limit."""


def parse_resource(data: bytes, *, max_nodes: int = 100000) -> dict:
    """Read the observed version-122 0DRP metadata, or raise ValueError.

    All tables and payload spans are bounded before returning any output.
    There is no checksum or declared total length in this supported profile;
    successful metadata parsing does not establish complete file semantics.
    Offsets are relative to the joined decompressed resource, never the archive.
    """
    if max_nodes < 1:
        raise ResourceLimitError('0DRP metadata output exceeds node limit')
    if len(data) > MAX_RESOURCE:
        raise ResourceLimitError('0DRP resource exceeds size limit')
    if len(data) < HEADER_SIZE or data[16:20] != b'0DRP':
        raise ValueError('not a bounded 0DRP resource header')
    if data[:8] != bytes(8) or data[24:32] != bytes(8):
        raise ValueError('unsupported nonzero 0DRP reserved header words')
    version = struct.unpack_from('<I', data, 20)[0]
    if version != 122:
        raise ValueError('unsupported 0DRP version')
    ns, ne, nb, unknown = struct.unpack_from('<4H', data, 72)
    nodes = 1

    def consume(n=1):
        nonlocal nodes
        if n > max_nodes - nodes:
            raise ResourceLimitError('0DRP metadata output exceeds node limit')
        nodes += n

    def span(pointer, length, label):
        if length == 0:
            if pointer != 0:
                raise ValueError(f'unsupported nonnull empty 0DRP {label}')
            return None
        at = pointer - VIRTUAL_BASE  # Full-width subtraction, never mask a pointer.
        if at < HEADER_SIZE or at > len(data) - length:
            raise ValueError(f'0DRP {label} span exceeds resource bounds or overlaps header')
        return at

    def pointer(at):
        return struct.unpack_from('<Q', data, at)[0]

    # These pointers have unknown roles and lengths. Report the words only;
    # neither one authorizes traversing objects or choosing a clip payload.
    header = dict(version=version, unknown_00=f'0x{pointer(0):016x}',
        unknown_08=f'0x{pointer(8):016x}', unknown_18=f'0x{pointer(24):016x}',
        unknown_20=f'0x{pointer(32):016x}', unknown_40=f'0x{pointer(64):016x}',
        unknown_4e=unknown, header_bits='0x' + data[:HEADER_SIZE][::-1].hex())
    tables = []
    consume(ns + ne + nb)  # Preflight counts before allocating rows.
    for name, at, count, stride in (('structures', 40, ns, 32),
                                   ('enums', 48, ne, 24), ('blocks', 56, nb, 16)):
        word = pointer(at)
        tables.append(dict(name=name, reference_bits=f'0x{word:016x}', count=count,
                           stride=stride, data_offset=span(word, count * stride, name),
                           byte_length=count * stride))
    structures, enums, blocks = [], [], []
    for i in range(ns):
        at = tables[0]['data_offset'] + 32 * i
        name, a, b, c, word, size, tail, count = struct.unpack_from('<IIIIQIHH', data, at)
        fields_at = span(word, count * 16, 'structure fields')
        consume(count)
        fields = []
        for j in range(count):
            pos = fields_at + j * 16
            field, offset, type_word, aux = struct.unpack_from('<4I', data, pos)
            if offset >= size:
                raise ValueError('0DRP field start exceeds declared structure size')
            fields.append(dict(data_offset=pos, hash=f'0x{field:08x}',
                field_offset=offset, type_word=f'0x{type_word:08x}',
                unknown_0c=f'0x{aux:08x}', type_name=None, type_confidence='unknown'))
        structures.append(dict(index=i, data_offset=at, hash=f'0x{name:08x}',
            unknown_04=f'0x{a:08x}', unknown_08=f'0x{b:08x}', unknown_0c=f'0x{c:08x}',
            fields_reference_bits=f'0x{word:016x}', fields_data_offset=fields_at,
            byte_size=size, unknown_1c=tail, field_count=count, fields=fields))
    for i in range(ne):
        at = tables[1]['data_offset'] + 24 * i
        name, a, word, count, tail = struct.unpack_from('<IIQII', data, at)
        members_at = span(word, count * 16, 'enum members')
        consume(count)
        members = []
        for j in range(count):
            pos = members_at + j * 16
            bits, member, raw = struct.unpack_from('<QII', data, pos)
            members.append(dict(data_offset=pos, value_bits=f'0x{bits:016x}',
                                hash=f'0x{member:08x}', unknown_0c=f'0x{raw:08x}'))
        enums.append(dict(index=i, data_offset=at, hash=f'0x{name:08x}',
            unknown_04=f'0x{a:08x}', members_reference_bits=f'0x{word:016x}',
            members_data_offset=members_at, unknown_14=f'0x{tail:08x}',
            member_count=count, members=members))
    for i in range(nb):
        at = tables[2]['data_offset'] + 16 * i
        name, length, word = struct.unpack_from('<IIQ', data, at)
        pos = span(word, length, 'data block')
        blocks.append(dict(index=i, table_offset=at, type_hash=f'0x{name:08x}',
                           reference_bits=f'0x{word:016x}', data_offset=pos,
                           byte_length=length))
    return dict(format='gta6x-0drp-metadata-v1', status='partial',
        interpretation='Inferred bounded metadata only; unknown header roles, raw field types, '
                       'fixups, clip binding and animation curves remain unresolved. '
                       'No checksum or complete byte-coverage claim.',
        byte_length=len(data), sha256=hashlib.sha256(data).hexdigest(), header=header,
        summary=dict(nodes=nodes, structures=ns, fields=sum(s['field_count'] for s in structures),
                     enums=ne, enum_members=sum(e['member_count'] for e in enums), blocks=nb),
        tables=tables, structures=structures, enums=enums, blocks=blocks)


def _independent_start(data):
    return (data[16:20] == b'0DRP' or data[:4] in (b'PSIN', b'MoVE', b'RBF0')
            or data.startswith((b'pack:/', b'SKEL_')))


def _scan_chains(path, *, is_start, independent_start, start=None, limit=None, label="0DRP",
                 stop_when=None):
    """Yield bounded resource candidates and explicit framing failures.

    Callers provide format recognizers; no name-table or clip identity is
    inferred from mere physical adjacency. An optional predicate may authorize
    a fully bounded metadata prefix without claiming a complete resource.
    Data stays local to the consumer.
    """
    if limit is not None and limit <= 0:
        raise ValueError('resource scan limit must be positive')
    path = os.fspath(path)
    if start is None:
        try:
            header = rpf.read_header(path)
            start = header.index_size if header.is_rpf9 else 0
        except (OSError, ValueError):
            start = 0
    if start < 0 or start > os.path.getsize(path):
        raise ValueError('resource scan start must be inside the archive')
    # Keep the carver's existing capped-stream policy. Resource assembly and
    # metadata output have separate, tighter limits; an oversized yielded
    # candidate is reported as a refusal and never copied into a joined buffer.
    def streams():
        consumed_end = start
        for blob in zlibcarve.carve_streams(path, start=start, length=limit, min_out=1):
            if blob.offset >= consumed_end:
                consumed_end = blob.offset + blob.compressed
                yield blob

    blobs = iter(streams())
    pending = next(blobs, None)
    with open(path, 'rb') as fh:
        while pending is not None:
            first, pending = pending, None
            if not is_start(first.data):
                pending = next(blobs, None)
                continue
            pieces = [first.data]
            segments = [dict(offset=first.offset, compressed_bytes=first.compressed,
                             inflated_bytes=len(first.data))]
            total, last = len(first.data), first
            error = f'{label} resource exceeds size limit' if total > MAX_RESOURCE else None
            prefix_ready = (error is None and stop_when is not None
                            and len(last.data) % PAGE_UNIT == 0 and stop_when(b''.join(pieces)))
            while error is None and not prefix_ready and len(last.data) % PAGE_UNIT == 0:
                following = next(blobs, None)
                end = last.offset + last.compressed
                aligned = (end + 15) & ~15
                if following is None:
                    error = f'{label} chain has no short terminal page within the scan range'
                    break
                fh.seek(end)
                padding = fh.read(aligned - end)
                if (following.offset != aligned or len(padding) != aligned - end
                        or any(padding) or independent_start(following.data)):
                    pending = following
                    error = f'{label} continuation is missing, nonadjacent, nonzero-padded or an independent resource'
                    break
                if len(segments) >= MAX_SEGMENTS or total + len(following.data) > MAX_RESOURCE:
                    pending = following
                    error = f'{label} continuation exceeds resource size or segment limit'
                    break
                pieces.append(following.data)
                total += len(following.data)
                segments.append(dict(offset=following.offset, compressed_bytes=following.compressed,
                                     inflated_bytes=len(following.data)))
                last = following
                prefix_ready = (stop_when is not None and len(last.data) % PAGE_UNIT == 0
                                and stop_when(b''.join(pieces)))
            row = dict(archive=os.path.basename(path), offset=first.offset, segments=segments)
            if stop_when is not None:
                row['framing'] = ('unresolved' if error is not None else
                                  'bounded_metadata_prefix' if prefix_ready else 'short_terminal_page')
            yield row, b''.join(pieces) if error is None else None, error
            if pending is None:
                pending = next(blobs, None)


def scan_resources(path, *, start=None, limit=None, max_nodes=100000):
    """Yield metadata/refusals for observed bounded 0DRP resource chains.

    Only adjacent streams across zero alignment padding may join. Multiples of
    64 KiB may continue; a short terminal page is required. Known independent
    starts stop joining. Metadata shares one total output node budget.
    """
    if max_nodes < 0:
        raise ValueError('resource node budget must be nonnegative')
    remaining = max_nodes
    for row, data, error in _scan_chains(path, start=start, limit=limit,
            is_start=lambda data: data[16:20] == b'0DRP', independent_start=_independent_start):
        if error is None:
            try:
                parsed = parse_resource(data, max_nodes=remaining)
                remaining -= parsed['summary']['nodes']
                row.update(parsed)
            except ValueError as exc:
                error = str(exc)
        if error is not None:
            row.update(status='refused', reason=error)
        yield row
