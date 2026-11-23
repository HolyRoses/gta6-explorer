"""Contextual inline PSIN maps linked to locally declared entry records.

Opaque key and type5c value storage retain no primitive, array, element-width
or lookup meaning. Only exact local descriptor trees and whole entry spans bind.
"""
from __future__ import annotations

import struct

from . import psin_references

PROFILE = 'inline_opaque_descriptor_map_record_links_v1'


def _opaque(field):
    return field.type_word == 0x1b4d and field.auxiliary == 0


def _value_descriptor(owner, field):
    index = field.type_word >> 16
    if (field.type_word & 0xffff != 0x5c or field.auxiliary != 0
            or index >= len(owner.fields)):
        return False
    descriptor = owner.fields[index]
    return (descriptor is not field and descriptor.name_hash == 0x100
            and descriptor.data_offset == 0 and _opaque(descriptor))


def resolve_map(data, start, field, owner, end, blocks, structures, *, consume):
    """Bind one exact contextual map; malformed maps publish no entry prefix."""
    consume()
    result = dict(status='unresolved', candidate_profile=PROFILE, entries=[],
                  mode='local_entry_record_links', header_data_offset=start,
                  header_byte_length=24)
    def refuse(reason):
        return dict(result, reason=reason)
    if (field.name_hash == 0x100 or field.type_word != 0x71
            or field.data_offset < 0 or field.data_offset + 24 > owner.byte_size
            or start < 0 or start + 24 > min(end, len(data))
            or not psin_references.field_slot_clear(owner, field, 24)):
        return refuse('contextual map requires one bounded unaliased local 24-byte field slot')
    ki, vi = field.auxiliary & 0xffff, field.auxiliary >> 16
    if ki == vi or max(ki, vi) >= len(owner.fields):
        return refuse('contextual map descriptor indices are invalid')
    key, value = owner.fields[ki], owner.fields[vi]
    if (any(d.name_hash != 0x100 or d.data_offset != 0 for d in (key, value))
            or not _opaque(key) or not _value_descriptor(owner, value)):
        return refuse('contextual map requires the exact local opaque/type5c descriptor tree')
    prefix, word, a, b, tail = struct.unpack_from('<QQHHI', data, start)
    result.update(header_bits='0x' + data[start:start+24][::-1].hex(),
                  unknown_00=f'0x{prefix:016x}', reference_bits=f'0x{word:016x}',
                  u16_10=a, u16_12=b, unknown_14=f'0x{tail:08x}')
    if prefix != 1 or a != b or tail:
        return refuse('contextual map requires leading one, equal u16 words and zero tail')
    result['count'] = a
    if not a:
        if word:
            return refuse('contextual empty map requires a null entry reference')
        result['target'] = None
    else:
        number, offset = word & 0xfffff, word >> 20
        if not 1 <= number <= len(blocks):
            return refuse('contextual map reference has an invalid local block ID')
        target = blocks[number-1]; definitions = structures.get(target.type_hash, [])
        if len(definitions) != 1:
            return refuse('contextual map requires one unique local entry schema')
        entry = definitions[0]
        if (entry.byte_size != 24 or len(entry.fields) != 3
                or entry.fields[0].name_hash == 0x100 or entry.fields[0].data_offset != 0
                or not _opaque(entry.fields[0])
                or entry.fields[1].name_hash != 0x100 or entry.fields[1].data_offset != 0
                or not _opaque(entry.fields[1])
                or entry.fields[2].name_hash == 0x100 or entry.fields[2].data_offset != 8
                or not _value_descriptor(entry, entry.fields[2])):
            return refuse('contextual entry schema differs from the complete matched local descriptor layout')
        if (target.byte_length % 24 or offset % 24 or offset > target.byte_length
                or a > (target.byte_length-offset)//24):
            return refuse('contextual map allocation is not a whole bounded local entry span')
        at = target.data_offset + offset
        if at < 0 or at + a*24 > len(data):
            raise ValueError('contextual map entry span exceeds input bounds')
        result['target'] = dict(block_index=target.index, byte_offset=offset,
            data_offset=at, byte_length=a*24, structure_hash=f'0x{entry.name_hash:08x}')
        for i in range(a):
            consume()
            result['entries'].append(dict(index=i, status='record_reference',
                block_index=target.index, record_index=offset//24+i,
                data_offset=at+i*24, byte_length=24,
                structure_hash=f'0x{entry.name_hash:08x}'))
    result.update(status='complete', profile=result.pop('candidate_profile'),
        interpretation='local whole-entry associations only; opaque keys/type5c values and lookup semantics remain unknown')
    return result
