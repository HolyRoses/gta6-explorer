"""Contextual links for two observed schema-local nested-map storage profiles.

Only existing typed entry rows are linked. Descriptor indices are interpreted
within their own owner, then compared as bounded trees. Raw code 0x15 remains
opaque: no scalar width, signedness, key value or lookup semantics are inferred.
No nested target graph is traversed and no application values are copied.
"""
from __future__ import annotations

import struct

from .psin_references import field_slot_clear

PROFILE = 'local_nested_map_entry_links_v1'
_HASH = (0x4a,)
_OPAQUE = (0x15,)
_LEAF_MAP = (0x71, _HASH, _HASH)
_INNER_MAP = (0x71, _OPAQUE, _LEAF_MAP)
_OBSERVED = frozenset(((0x71, _HASH, _INNER_MAP), _INNER_MAP))


def _tree(owner, field, active=()):
    """Normalize only measured bounded descriptor trees, not pointer graphs."""
    identity = field.section_offset
    if identity in active or len(active) > 3:
        raise ValueError('nested-map descriptor graph is cyclic or exceeds the measured depth')
    if field.type_word in (0x4a, 0x15) and field.auxiliary == 0:
        return (field.type_word,)
    if field.type_word != 0x71:
        raise ValueError('unsupported nested-map descriptor leaf')
    ki, vi = field.auxiliary & 0xffff, field.auxiliary >> 16
    if ki == vi or max(ki, vi) >= len(owner.fields):
        raise ValueError('nested map requires distinct bounded descriptor indices')
    key, value = owner.fields[ki], owner.fields[vi]
    if any(f.name_hash != 0x100 or f.data_offset != 0 for f in (key, value)):
        raise ValueError('nested map requires local synthetic descriptors at zero')
    active = active + (identity,)
    return (0x71, _tree(owner, key, active), _tree(owner, value, active))


def resolve_entries(data, start, field, owner, block_end, blocks, *,
                    local_owner, local_structures, consume, slot_cache=None):
    """Link a whole nonempty local span after schema-tree/layout equality.

    The opaque-key profile validates an association to already present records;
    it does not decode their key fields. Empty maps and other header, entry or
    descriptor-tree shapes remain unfitted and return no prefix entries.
    """
    result = dict(status='unresolved', interpretation='candidate', candidate_profile=PROFILE,
                  mode='entry_record_links', header_data_offset=start,
                  header_byte_length=24, entries=[])
    def refuse(reason):
        return dict(result, reason=reason)
    if not local_owner:
        return refuse('nested map requires a local owning schema')
    if field.name_hash == 0x100 or field.type_word != 0x71:
        return refuse('unsupported nested-map field attributes')
    if (field.data_offset < 0 or field.data_offset + 24 > owner.byte_size
            or start < 0 or start + 24 > min(block_end, len(data))):
        return refuse('nested-map header exceeds its owning record or block')
    if not field_slot_clear(owner, field, 24, slot_cache):
        return refuse('nested-map header overlaps another named field start')
    try:
        tree = _tree(owner, field)
    except ValueError as exc:
        return refuse(str(exc))
    if tree not in _OBSERVED:
        return refuse('nested-map descriptor tree is outside the measured profiles')
    prefix, word, count, capacity, tail = struct.unpack_from('<QQHHI', data, start)
    result.update(header_bits='0x' + data[start:start+24][::-1].hex(),
                  unknown_00=f'0x{prefix:016x}', reference_bits=f'0x{word:016x}',
                  u16_10=count, u16_12=capacity, unknown_14=f'0x{tail:08x}',
                  key_descriptor_index=field.auxiliary & 0xffff,
                  value_descriptor_index=field.auxiliary >> 16)
    if prefix != 1 or count != capacity or tail:
        return refuse('unvalidated nested-map header: requires leading one, equal u16 words and zero tail')
    if count == 0:
        return refuse('empty nested-map profile is not validated')
    number, offset = word & 0xfffff, word >> 20
    if not 1 <= number <= len(blocks):
        return refuse('nested-map entry reference has an invalid one-based block ID')
    target = blocks[number-1]
    definitions = local_structures.get(target.type_hash, [])
    if len(definitions) != 1 or definitions[0].byte_size <= 0:
        return refuse('nested map requires a unique positive-sized local entry schema')
    entry = definitions[0]
    named = [(i, f) for i, f in enumerate(entry.fields) if f.name_hash != 0x100]
    # These are observed record extents and offsets, not an inferred key width.
    if entry.byte_size != 32 or len(named) != 2 or [f.data_offset for _, f in named] != [0, 8]:
        return refuse('nested-map entry differs from the measured 32-byte two-named-field layout')
    try:
        actual = (0x71, _tree(entry, named[0][1]), _tree(entry, named[1][1]))
    except ValueError as exc:
        return refuse(str(exc))
    if actual != tree:
        return refuse('nested-map local descriptor trees do not match')
    stride = entry.byte_size
    if target.byte_length % stride or offset % stride:
        return refuse('nested-map entry block or offset is not a whole local record stride')
    if offset > target.byte_length or count > (target.byte_length-offset)//stride:
        return refuse('nested-map entry span exceeds its logical target block')
    at, length = target.data_offset+offset, count*stride
    if at < 0 or at+length > len(data):
        raise ValueError('PSIN nested-map entry span exceeds container bounds')
    for i in range(count):
        consume()
        result['entries'].append(dict(index=i, status='record_reference',
            block_index=target.index, record_index=offset//stride+i,
            data_offset=at+i*stride, byte_length=stride,
            structure_hash=f'0x{entry.name_hash:08x}'))
    result.update(status='complete', interpretation='inferred', profile=result.pop('candidate_profile'),
                  key_type='hash32' if tree[1] == _HASH else 'opaque',
                  key_descriptor_type_bits=f'0x{tree[1][0]:08x}', value_type='map',
                  value_meaning='nested map descriptor shape only; target fields retain their own status',
                  count=count, stride=stride, entry_structure_hash=f'0x{entry.name_hash:08x}',
                  key_field_index=named[0][0], value_field_index=named[1][0],
                  target=dict(block_id=number, block_index=target.index,
                              block_type=f'0x{target.type_hash:08x}', byte_offset=offset,
                              data_offset=at, byte_length=length))
    return result
