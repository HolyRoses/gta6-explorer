"""Bounded local PSIN map-entry links from direct byte observations.

Header words and duplicate stored keys are preserved without assigning hash
lookup, bucket or insertion-order semantics. Only existing locally typed entry
rows are selected; target values and nested pointers are never expanded here.
No external implementation, mapping table or game fixture is used.
"""
from __future__ import annotations

import struct

from . import psin_references


def resolve_entries(data, start, field, owner, block_end, blocks, *, local_owner,
                    local_structures, consume, slot_cache=None):
    """Bind the observed hash32-key map profile to complete local entry spans.

    Exact local descriptors authorize hash32, bool8 or embedded-structure
    values. The selected block's two-field schema supplies the value offset;
    neither field hashes nor presumed alignment select a layout. Failed checks
    return no entry links. Every output link uses the caller's node budget.
    """
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile='local_hash32_map_entries_v1', mode='entry_record_links',
                  header_data_offset=start, header_byte_length=24, entries=[])

    def refuse(reason):
        return dict(result, reason=reason)

    if not local_owner:
        return refuse('map entries require a local owning schema')
    if field.name_hash == 0x100 or field.type_word != 0x71:
        return refuse('unsupported map field attributes')
    if (field.data_offset < 0 or field.data_offset + 24 > owner.byte_size
            or start < 0 or start + 24 > min(block_end, len(data))):
        return refuse('map header exceeds its owning record or block')
    if not psin_references.field_slot_clear(owner, field, 24, slot_cache):
        return refuse('map header overlaps another named field start')
    prefix, word, a, b, tail = struct.unpack_from('<QQHHI', data, start)
    result.update(header_bits='0x' + data[start:start + 24][::-1].hex(),
                  unknown_00=f'0x{prefix:016x}', reference_bits=f'0x{word:016x}',
                  u16_10=a, u16_12=b, unknown_14=f'0x{tail:08x}')
    ki, vi = field.auxiliary & 0xffff, field.auxiliary >> 16
    result.update(key_descriptor_index=ki, value_descriptor_index=vi)
    if ki == vi or not all(i < len(owner.fields) for i in (ki, vi)):
        return refuse('map requires distinct bounded key/value descriptor indices')
    key, value = owner.fields[ki], owner.fields[vi]
    if any(d.name_hash != 0x100 or d.data_offset != 0 for d in (key, value)):
        return refuse('map requires local synthetic descriptors at offset zero')
    if key.type_word != 0x4a or key.auxiliary != 0:
        return refuse('unsupported map key descriptor; requires exact hash32 profile')
    if value.type_word in (1, 0x4a) and value.auxiliary == 0:
        width = 1 if value.type_word == 1 else 4
        result['value_type'] = 'bool8' if value.type_word == 1 else 'hash32'
    elif value.type_word == 5:
        values = local_structures.get(value.auxiliary, [])
        if len(values) != 1 or values[0].byte_size <= 0:
            return refuse('map requires a unique positive-sized local value structure')
        width = values[0].byte_size
        result.update(value_type='structure', value_structure_hash=f'0x{value.auxiliary:08x}')
    else:
        return refuse('unsupported map value descriptor')
    result['key_type'] = 'hash32'
    if prefix != 1 or a != b or tail != 0:
        return refuse('unvalidated map header: requires leading word one, equal u16 words and zero tail')
    result['count'] = a  # Equal observed words, without count/capacity role claims.
    if a == 0:
        if word != 0:
            return refuse('empty map with nonzero entry reference is not validated')
        result['target'] = None
    else:
        number, offset = word & 0xfffff, word >> 20
        if not 1 <= number <= len(blocks):
            return refuse('map entry reference has an invalid one-based block ID')
        target = blocks[number - 1]
        definitions = local_structures.get(target.type_hash, [])
        if len(definitions) != 1 or definitions[0].byte_size <= 0:
            return refuse('map requires a unique positive-sized local entry schema')
        entry = definitions[0]
        stride, fields = entry.byte_size, entry.fields
        if (len(fields) != 2 or any(f.name_hash == 0x100 for f in fields)
                or fields[0].data_offset != 0 or fields[0].type_word != key.type_word
                or fields[0].auxiliary != key.auxiliary or fields[1].data_offset < 4
                or fields[1].type_word != value.type_word or fields[1].auxiliary != value.auxiliary
                or fields[1].data_offset + width > stride):
            return refuse('map entry fields do not match the local key/value descriptors and bounded layout')
        if target.byte_length % stride or offset % stride:
            return refuse('map entry block or offset is not a whole local record stride')
        if offset > target.byte_length or a > (target.byte_length - offset) // stride:
            return refuse('map entry span exceeds its target block')
        at, length = target.data_offset + offset, a * stride
        if at < 0 or at + length > len(data):
            raise ValueError('PSIN map entry span exceeds container bounds')
        result.update(stride=stride, entry_structure_hash=f'0x{entry.name_hash:08x}',
                      key_field_index=0, value_field_index=1,
                      target=dict(block_id=number, block_index=target.index,
                                  block_type=f'0x{target.type_hash:08x}', byte_offset=offset,
                                  data_offset=at, byte_length=length))
        for i in range(a):
            consume()
            result['entries'].append(dict(index=i, status='record_reference',
                block_index=target.index, record_index=offset // stride + i,
                data_offset=at + i * stride, byte_length=stride,
                structure_hash=f'0x{entry.name_hash:08x}'))
    result.update(status='complete', interpretation='inferred', profile=result.pop('candidate_profile'))
    return result
