"""Observed kind-12 MoVE storage: five counted groups of opaque cells.

Selector and cell bits are retained without numeric, hash, pose or timing
meanings. The optional remainder stays opaque and is never traversed.
"""
from __future__ import annotations

import hashlib
import struct

PROFILE = 'observed_move_kind12_five_groups_v1'
HEADER_WORDS = frozenset((0x1156, 0x1166, 0x116a))


def inspect_kind12(data, at, size, consume):
    """Return one complete observed prefix or raise before publishing rows.

    Parent framing must already authorize this exact candidate and its header.
    Only zero-ordinal, 52-byte headers and at most one selector word per group
    are supported. A nonempty remainder must carry the observed next ordinal.
    These bounds describe storage, not a general motion object grammar.
    """
    stop = at + size

    def span(pos, n):
        if (type(at) is not int or type(size) is not int or at < 0 or size < 0
                or stop > len(data) or n < 0 or pos < at or pos > stop - n):
            raise ValueError('MoVE kind-12 storage exceeds its bounded candidate')

    def opaque(pos, n):
        span(pos, n)
        return dict(data_offset=pos, byte_length=n,
                    sha256=hashlib.sha256(data[pos:pos+n]).hexdigest(), interpretation='opaque')

    span(at, 52)
    kind, ordinal, name = struct.unpack_from('<HHI', data, at)
    flags = struct.unpack_from('<I', data, at + 12)[0]
    if kind != 12 or ordinal != 0 or flags not in HEADER_WORDS:
        raise ValueError('unsupported MoVE kind-12 header-word profile')
    if any(struct.unpack_from('<I', data, at + p)[0]
           for p in (8, 16, 20, 24, 40, 44, 48)):
        raise ValueError('unsupported MoVE kind-12 reserved header words')
    pos = at + 52
    groups = []
    regions = [dict(name='header', data_offset=at, byte_length=52)]
    consume(3)
    for group in range(5):
        start = pos
        span(pos, 4)
        count = struct.unpack_from('<I', data, pos)[0]
        pos += 4
        if count > 16:
            raise ValueError('MoVE kind-12 group exceeds observed one-word selector profile')
        selector = None
        selector_at = pos
        if count:
            span(pos, 4)
            selector = struct.unpack_from('<I', data, pos)[0]
            # Every used two-bit field is exactly 2; all unused bits are zero.
            if selector != 2 * ((1 << (2 * count)) - 1) // 3:
                raise ValueError('unsupported MoVE kind-12 selector or nonzero unused bits')
            pos += 4
        span(pos, 8 * count)
        consume(2 + count)
        cells = []
        for i in range(count):
            cell = dict(index=i, group_index=group, data_offset=pos + i * 8,
                        byte_length=8,
                        value_bits='0x' + data[pos+i*8:pos+(i+1)*8][::-1].hex(),
                        interpretation='opaque cell bits; numeric and application meanings unknown')
            cells.append(cell)
        pos += 8 * count
        groups.append(dict(index=group, data_offset=start, byte_length=pos-start,
            count_data_offset=start, count=count, selector_data_offset=selector_at,
            selector_byte_length=4 if count else 0,
            selector_bits=f'0x{selector:08x}' if selector is not None else None,
            cell_stride=8, cells=cells))
        regions.append(dict(name='counted_group', data_offset=start, byte_length=pos-start))
    remaining = stop - pos
    if remaining:
        span(pos, 8)
        if struct.unpack_from('<H', data, pos + 2)[0] != 1:
            raise ValueError('unsupported MoVE kind-12 opaque-tail ordinal')
    consume(2)
    regions.append(dict(name='opaque_tail', data_offset=pos, byte_length=remaining))
    return dict(status='complete', profile=PROFILE, form='kind12_five_counted_opaque_groups',
        header=dict(raw_kind_u16=kind, raw_ordinal_u16=ordinal,
                    name_hash_bits=f'0x{name:08x}', header_word_bits=f'0x{flags:08x}',
                    value_bits='0x' + data[at:at+52][::-1].hex()),
        groups=groups, references=[], records=[], regions=regions,
        summary=dict(counted_groups=5, selector_words=sum(g['count'] > 0 for g in groups),
                     opaque_cells=sum(g['count'] for g in groups)),
        opaque_regions=[opaque(pos, remaining)],
        interpretation='bounded counted storage only; selector, cell and motion meanings unknown')
