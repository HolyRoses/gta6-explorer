"""Bounded local PSIN record-reference bindings from direct byte observations.

Only existing typed record rows are selected, never recursively expanded.
Standalone field profiles preserve raw schema types and explicit unknowns.
No external implementation, mapping table or game fixture is used.
"""
from __future__ import annotations

from bisect import bisect_left
import struct


def bind_record(word, blocks, local_structures, *, data_size):
    """Bind one full word using its block's declared local type, without reading targets."""
    if word == 0:
        return dict(status='null_reference', target=None)
    number, offset = word & 0xfffff, word >> 20
    if not 1 <= number <= len(blocks):
        return dict(status='unresolved', failure='invalid_id', reason='record reference has an invalid block ID')
    target = blocks[number - 1]
    definitions = local_structures.get(target.type_hash, [])
    if len(definitions) != 1 or definitions[0].byte_size <= 0:
        return dict(status='unresolved', failure='schema',
                    reason='record reference has no unique positive-sized local target schema')
    stride = definitions[0].byte_size
    if target.byte_length % stride or offset % stride or offset > target.byte_length - stride:
        return dict(status='unresolved', failure='span', reason='record reference does not select a whole bounded local record')
    at = target.data_offset + offset
    if at < 0 or at + stride > data_size:
        raise ValueError('PSIN record reference exceeds container bounds')
    return dict(status='record_reference', block_index=target.index, record_index=offset // stride,
                data_offset=at, byte_length=stride, structure_hash=f'0x{target.type_hash:08x}')


def named_field_starts(owner):
    """Sorted declared starts; duplicate starts deliberately remain ambiguous."""
    return tuple(sorted(f.data_offset for f in owner.fields if f.name_hash != 0x100))


def field_slot_clear(owner, field, width, slot_cache=None):
    """Index named starts once per owner; reject aliases inside a bounded slot."""
    starts = slot_cache.get(id(owner)) if slot_cache is not None else None
    if starts is None:
        starts = named_field_starts(owner)
        if slot_cache is not None:
            slot_cache[id(owner)] = starts
    lower = bisect_left(starts, field.data_offset)
    upper = bisect_left(starts, field.data_offset + width)
    return upper - lower == 1 and starts[lower] == field.data_offset


def resolve_field(data, start, field, owner, block_end, blocks, *, local_owner, local_structures,
                  slot_cache=None):
    """Recognize a local exact-0x07/zero-aux eight-byte named-field slot.

    The caller provides start = record start + field offset and bounds its
    owning record. Another named field start may not overlap the word. This
    context-specific binding does not assign a global LSCH primitive meaning.
    """
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile='local_record_reference_v1', reference_data_offset=start,
                  reference_byte_length=8)
    if not local_owner:
        return dict(result, reason='standalone reference requires a local owning schema')
    if field.name_hash == 0x100 or field.type_word != 7 or field.auxiliary != 0:
        return dict(result, reason='unsupported standalone reference field attributes')
    if field.data_offset < 0 or field.data_offset + 8 > owner.byte_size or start < 0 or start + 8 > min(block_end, len(data)):
        return dict(result, reason='standalone reference word exceeds its owning record or block')
    if not field_slot_clear(owner, field, 8, slot_cache):
        return dict(result, reason='standalone reference word overlaps another named field start')
    word = struct.unpack_from('<Q', data, start)[0]
    result['reference_bits'] = f'0x{word:016x}'
    bound = bind_record(word, blocks, local_structures, data_size=len(data))
    if bound['status'] == 'unresolved':
        return dict(result, reason=bound['reason'])
    result.update(bound, interpretation='inferred', profile=result.pop('candidate_profile'))
    return result
