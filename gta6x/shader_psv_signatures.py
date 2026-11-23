"""Bounded public PSV0 name/index/signature tables; dependency masks stay opaque."""
from __future__ import annotations

import hashlib
import struct

MAX_NAME_BYTES = 1024


def inspect(body: bytes, origin: int, prefix: dict, spend) -> dict:
    """Decode additive signature records using only their declared local tables.

    All work shares the enclosing metadata budget. Callers discard this entire
    view on malformed tables; independent runtime/resource prefixes survive.
    """
    info = prefix['runtime_info']
    cursor = prefix['parsed_prefix_bytes']
    if info['known_prefix_version'] == 0:
        return dict(status='complete', scope='version-zero PSV0 has no signature tables',
                    signatures=[], entry_name=None)
    spend()

    def word():
        nonlocal cursor
        if cursor > len(body)-4:
            raise ValueError('PSV0 signature table header is truncated')
        value = struct.unpack_from('<I', body, cursor)[0]
        cursor += 4
        return value

    string_size = word()
    if string_size % 4 or string_size > len(body)-cursor:
        raise ValueError('PSV0 string table is unaligned or exceeds its chunk')
    strings_at = cursor
    strings = body[cursor:cursor+string_size]
    cursor += string_size
    if strings and strings[0] != 0:
        raise ValueError('PSV0 string table is missing its null entry')
    names = {}

    def name(offset):
        if offset == 0:
            return None
        if offset >= len(strings):
            raise ValueError('PSV0 string offset exceeds its declared string table')
        if offset not in names:
            end = strings.find(b'\0', offset, min(len(strings), offset+MAX_NAME_BYTES+1))
            if end < 0:
                raise ValueError('PSV0 name is unterminated or exceeds its byte limit')
            raw = strings[offset:end]
            if any(c < 32 or c > 126 for c in raw):
                raise ValueError('PSV0 name contains unsupported non-ASCII bytes')
            spend()
            names[offset] = raw.decode('ascii')
        return names[offset]

    index_count = word()
    if index_count > (len(body)-cursor)//4:
        raise ValueError('PSV0 index count exceeds its declared chunk')
    spend(index_count)
    indices_at = cursor
    indices = list(struct.unpack_from('<'+'I'*index_count, body, cursor))
    cursor += index_count*4
    counts = [info['input_signature_elements'], info['output_signature_elements'],
              info['patch_or_primitive_signature_elements']]
    stride = word() if sum(counts) else None
    if stride is not None and (stride < 16 or stride % 4 or sum(counts) > (len(body)-cursor)//stride):
        raise ValueError('PSV0 signature count/stride exceeds its declared table')
    spend(sum(counts))
    signatures = []
    for direction, count in zip(('input', 'output', 'patch_constant_or_primitive'), counts):
        elements = []
        for ordinal in range(count):
            at = cursor
            name_at, index_at, rows, start, packed, kind, component, mode, dynamic, reserved = (
                struct.unpack_from('<IIBBBBBBBB', body, at))
            if index_at > index_count or rows > index_count-index_at:
                raise ValueError('PSV0 semantic index range exceeds its index table')
            cols, col, allocated = packed & 15, (packed >> 4) & 3, bool(packed & 64)
            if not 1 <= cols <= 4 or col+cols > 4:
                raise ValueError('PSV0 signature columns exceed a four-component row')
            if packed & 128 or dynamic & 192 or reserved:
                raise ValueError('PSV0 signature has unsupported reserved bits')
            # Index sequences can be shared by distinct elements; preserve aliases.
            spend(rows)
            row = dict(ordinal=ordinal, data_offset=origin+at, byte_length=stride,
                name_offset=name_at, semantic_name=name(name_at), index_offset=index_at,
                indices=indices[index_at:index_at+rows], rows=rows, start_row=start,
                columns=cols, start_column=col, allocated=allocated,
                semantic_kind_code=kind, component_type_code=component,
                interpolation_mode_code=mode, dynamic_mask=dynamic & 15,
                stream=(dynamic >> 4) & 3, reserved_bits=reserved)
            if stride > 16:
                row['unknown_extension'] = dict(data_offset=origin+at+16,
                    byte_length=stride-16,
                    sha256=hashlib.sha256(body[at+16:at+stride]).hexdigest())
            elements.append(row)
            cursor += stride
        signatures.append(dict(direction=direction, element_count=count, elements=elements))
    entry_at = info.get('entry_name_offset')
    entry = name(entry_at) if entry_at is not None else None
    return dict(status='complete', data_offset=origin+prefix['parsed_prefix_bytes'],
        scope='public PSV0 string/index/signature tables only; dependency masks and game identities unresolved',
        string_table=dict(data_offset=origin+strings_at, byte_length=string_size,
            sha256=hashlib.sha256(strings).hexdigest()),
        index_table=dict(data_offset=origin+indices_at, count=index_count, values=indices),
        signature_stride=stride, signatures=signatures, entry_name=entry,
        parsed_table_bytes=cursor-prefix['parsed_prefix_bytes'],
        opaque_mask_suffix=dict(data_offset=origin+cursor, byte_length=len(body)-cursor,
            sha256=hashlib.sha256(body[cursor:]).hexdigest()))
