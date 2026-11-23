"""Bounded entry-row links for an observed local map with opaque keys.

Exact descriptor equality and declared local record extents authorize these
associations. The key code 0x054f remains unknown: its bytes, width and lookup
semantics are never interpreted. Values remain in their existing typed rows.
"""
from __future__ import annotations

import struct

from . import psin_references, psin_schema

PROFILE = 'local_opaque_key_map_entry_links_v1'


def resolve_entries(data, start, field, owner, block_end, blocks, *,
                    local_owner, local_structures, consume, slot_cache=None,
                    local_enums=None):
    """Link a whole nonempty span after exact local schema/layout checks.

    Only the three observed value/entry layouts are enabled. The key's offset
    is compared as metadata, without reading it or deriving a scalar width
    from the next field. No key value or copied target value is emitted.
    """
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, mode='entry_record_links',
                  header_data_offset=start, header_byte_length=24, entries=[])

    def refuse(reason):
        return dict(result, reason=reason)

    if not local_owner:
        return refuse('opaque-key map requires a local owning schema')
    if field.name_hash == 0x100 or field.type_word != 0x71:
        return refuse('unsupported opaque-key map field attributes')
    if (field.data_offset < 0 or field.data_offset + 24 > owner.byte_size
            or start < 0 or start + 24 > min(block_end, len(data))):
        return refuse('opaque-key map header exceeds its owning record or block')
    if not psin_references.field_slot_clear(owner, field, 24, slot_cache):
        return refuse('opaque-key map header overlaps another named field start')
    ki, vi = field.auxiliary & 0xffff, field.auxiliary >> 16
    if ki == vi or max(ki, vi) >= len(owner.fields):
        return refuse('opaque-key map requires distinct bounded descriptor indices')
    key, value = owner.fields[ki], owner.fields[vi]
    if any(d.name_hash != 0x100 or d.data_offset != 0 for d in (key, value)):
        return refuse('opaque-key map requires local synthetic descriptors at zero')
    if key.type_word != 0x054f or key.auxiliary != 0:
        return refuse('unsupported opaque-key map key descriptor')

    if value.type_word == 5:
        values = local_structures.get(value.auxiliary, [])
        if len(values) != 1 or values[0].byte_size != 12:
            return refuse('opaque-key map requires a unique local 12-byte value structure')
        width, stride, value_type = 12, 24, 'structure'
        result['value_structure_hash'] = f'0x{value.auxiliary:08x}'
    elif value.type_word == 0x62:
        definitions = (local_enums or {}).get(value.auxiliary, [])
        info = psin_schema._type_info(value, owner, local_structures, local_enums)
        if len(definitions) != 1 or info['name'] != 'enum32':
            return refuse('opaque-key map requires a unique representable local enum32 value definition')
        width, stride, value_type = 4, 16, 'enum32'
        result['value_enum_hash'] = f'0x{value.auxiliary:08x}'
    elif value.type_word == 0x21 and value.auxiliary == 0:
        width, stride, value_type = 4, 16, 'float32'
    else:
        return refuse('unsupported opaque-key map value descriptor')

    prefix, word, count, other_count, tail = struct.unpack_from('<QQHHI', data, start)
    result.update(header_bits='0x' + data[start:start+24][::-1].hex(),
                  unknown_00=f'0x{prefix:016x}', reference_bits=f'0x{word:016x}',
                  u16_10=count, u16_12=other_count, unknown_14=f'0x{tail:08x}',
                  key_descriptor_index=ki, value_descriptor_index=vi)
    if prefix != 1 or count != other_count or tail:
        return refuse('unvalidated opaque-key map header: requires leading one, equal u16 words and zero tail')
    if count == 0:
        return refuse('empty opaque-key map profile is not validated')
    number, offset = word & 0xfffff, word >> 20
    if not 1 <= number <= len(blocks):
        return refuse('opaque-key map entry reference has an invalid one-based block ID')
    target = blocks[number-1]
    definitions = local_structures.get(target.type_hash, [])
    if len(definitions) != 1 or definitions[0].byte_size <= 0:
        return refuse('opaque-key map requires a unique positive-sized local entry schema')
    entry = definitions[0]
    fields = entry.fields
    if (entry.byte_size != stride or len(fields) != 2
            or any(f.name_hash == 0x100 for f in fields)
            or fields[0].data_offset != 0 or fields[0].type_word != key.type_word
            or fields[0].auxiliary != key.auxiliary or fields[1].data_offset != 8
            or fields[1].type_word != value.type_word or fields[1].auxiliary != value.auxiliary
            or fields[1].data_offset + width > entry.byte_size):
        return refuse('opaque-key map entry differs from the measured local two-field layout')
    if target.byte_length % stride or offset % stride:
        return refuse('opaque-key map entry block or offset is not a whole local record stride')
    if offset > target.byte_length or count > (target.byte_length-offset)//stride:
        return refuse('opaque-key map entry span exceeds its logical target block')
    at, length = target.data_offset+offset, count*stride
    if at < 0 or at+length > len(data):
        raise ValueError('PSIN opaque-key map entry span exceeds container bounds')
    for i in range(count):
        consume()
        result['entries'].append(dict(index=i, status='record_reference',
            block_index=target.index, record_index=offset//stride+i,
            data_offset=at+i*stride, byte_length=stride,
            structure_hash=f'0x{entry.name_hash:08x}'))
    result.update(status='complete', interpretation='inferred', profile=result.pop('candidate_profile'),
                  key_type='opaque', key_descriptor_type_bits=f'0x{key.type_word:08x}',
                  value_type=value_type,
                  value_meaning='local descriptor only; target fields retain their own status',
                  count=count, stride=stride, entry_structure_hash=f'0x{entry.name_hash:08x}',
                  key_field_index=0, value_field_index=1,
                  target=dict(block_id=number, block_index=target.index,
                              block_type=f'0x{target.type_hash:08x}', byte_offset=offset,
                              data_offset=at, byte_length=length))
    return result
