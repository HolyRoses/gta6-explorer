"""Bounded enum32-array links to existing local typed PSIN records.

The descriptor and unique local target-row schema must name the same local
LENM definition. Selected words are checked before any links escape. No global
low-ID pool meaning, new scalar values or recursive reference graph is inferred.
No external implementation, table or game fixture is used.
"""
from __future__ import annotations

import struct

from . import psin_arrays, psin_schema

PROFILE = 'local_enum32_record_array_v1'


def resolve(data, start, owner, descriptor_index, blocks, *, local_owner,
            local_structures, local_enums, consume):
    """Link one nonempty caller-bounded enum-array header atomically.

    The caller bounds the header inside its owning record/block. One named
    four-byte enum32 field must occupy each target row. Every selected word
    must match the local LENM definition before any source-ordered links are
    emitted. Values and enum aliases stay in the existing typed rows.
    """
    result, word, a, b, tail = psin_arrays._header(data, start, descriptor_index, PROFILE)
    result.update(element_type='enum32', mode='enum_record_links')

    def refuse(reason):
        return dict(result, reason=reason)

    if not local_owner:
        return refuse('enum32 array requires a local owning schema')
    if not 0 <= descriptor_index < len(owner.fields):
        return refuse('enum32 array descriptor index is out of bounds')
    descriptor = owner.fields[descriptor_index]
    if (descriptor.name_hash != 0x100 or descriptor.data_offset != 0
            or descriptor.type_word != 0x62):
        return refuse('array descriptor is not the exact local enum32 profile')
    definitions = (local_enums or {}).get(descriptor.auxiliary, [])
    info = psin_schema._type_info(descriptor, owner, local_structures, local_enums)
    if len(definitions) != 1 or info['name'] != 'enum32':
        return refuse('enum32 array requires one representable local LENM definition')
    result.update(enum_hash=f'0x{descriptor.auxiliary:08x}', stride=4,
                  enum_definition_offset=definitions[0].section_offset)
    if a != b or tail:
        return refuse('unvalidated enum32 array header: requires equal u16 words and zero tail')
    result['count'] = a
    if not a:
        return refuse('empty enum32 array profile is not validated')
    number, offset = word & 0xfffff, word >> 20
    if not 1 <= number <= len(blocks):
        return refuse('enum32 array reference has an invalid one-based block ID')
    target = blocks[number - 1]
    rows = local_structures.get(target.type_hash, [])
    if len(rows) != 1:
        return refuse('enum32 array requires a unique local target-row schema')
    row = rows[0]
    if (row.byte_size != 4 or len(row.fields) != 1 or row.fields[0].name_hash == 0x100
            or row.fields[0].data_offset != 0 or row.fields[0].type_word != 0x62
            or row.fields[0].auxiliary != descriptor.auxiliary):
        return refuse('enum32 array target row does not match its exact local enum descriptor')
    if target.byte_length % 4 or offset % 4:
        return refuse('enum32 array target block or offset is not a whole four-byte row stride')
    if offset > target.byte_length or a > (target.byte_length - offset) // 4:
        return refuse('enum32 array span exceeds its target block')
    at, length = target.data_offset + offset, a * 4
    if at < 0 or at + length > len(data):
        raise ValueError('enum32 array target exceeds container bounds')
    members = {member.value_bits & 0xffffffff for member in definitions[0].members}
    words = struct.unpack_from('<' + 'I' * a, data, at)
    if any(value not in members for value in words):
        return refuse('enum32 array word is absent from its local LENM definition')
    result.update(target=dict(block_id=number, block_index=target.index,
        block_type=f'0x{target.type_hash:08x}', byte_offset=offset,
        data_offset=at, byte_length=length),
        target_field_index=0, structure_hash=f'0x{row.name_hash:08x}')
    for i in range(a):
        consume()
        result['elements'].append(dict(index=i, status='record_reference',
            block_index=target.index, record_index=offset // 4 + i,
            data_offset=at + i * 4, byte_length=4,
            structure_hash=f'0x{row.name_hash:08x}', field_index=0))
    result.update(status='complete', interpretation='inferred', profile=result.pop('candidate_profile'))
    return result
