"""One bounded PSIN hash32-array profile from direct local observations.

The equal u16 header words are retained without assigning count/capacity roles.
Only a local hash32 descriptor and a complete span in an intrinsic hash pool
authorize reading values. Other arrays, reference chains and maps stay unknown.
No external implementation, mapping table or game fixture is used.
"""
from __future__ import annotations

import struct

from . import psin_schema


def resolve_hash32(data, start, owner, descriptor_index, blocks, *, local_owner,
                   local_structures, consume, dictionary=None):
    """Resolve an already bounded 16-byte header; never follow another pointer.

    Caller verifies the header fits its owning record and instance block.
    Unsupported profiles return explicit diagnostics and no prefix of values.
    The shared consume callback raises on budget exhaustion, discarding output.
    """
    if start < 0 or start + 16 > len(data):
        raise ValueError('PSIN array header exceeds container bounds')
    word, a, b, tail = struct.unpack_from('<QHHI', data, start)
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile='hash32_equal_u16_v1',
                  header_bits='0x' + data[start:start + 16][::-1].hex(),
                  reference_bits=f'0x{word:016x}', u16_08=a, u16_0a=b,
                  unknown_0c=f'0x{tail:08x}', element_descriptor_index=descriptor_index,
                  elements=[])

    def refuse(reason):
        return dict(result, reason=reason)

    if not local_owner:
        return refuse('hash32 array resolution requires a local owning schema')
    if not 0 <= descriptor_index < len(owner.fields):
        return refuse('array element descriptor index is out of bounds')
    descriptor = owner.fields[descriptor_index]
    if (descriptor.name_hash != 0x100 or descriptor.data_offset != 0
            or descriptor.type_word != 0x4a or descriptor.auxiliary != 0):
        return refuse('array element descriptor is not the supported local hash32 profile')
    result['element_type'] = 'hash32'
    if a != b or tail != 0:
        return refuse('unvalidated array header: requires equal u16 words and zero tail')
    result['count'] = a  # Common observed value, not a count/capacity role assignment.
    if a == 0:
        if word != 0:
            return refuse('empty hash32 array with nonzero reference is not validated')
        result['target'] = None
    else:
        number, offset = word & 0xfffff, word >> 20
        if not 1 <= number <= len(blocks):
            return refuse('hash32 array reference has an invalid one-based block ID')
        target = blocks[number - 1]
        if target.type_hash != 0x4a:
            return refuse('hash32 array target is not a hash32 pool')
        if local_structures.get(0x4a):
            return refuse('hash32 target ID has local structure definitions; intrinsic pool is ambiguous')
        if target.byte_length % 4 or offset % 4:
            return refuse('hash32 array target pool or offset is not four-byte aligned')
        if offset > target.byte_length or a > (target.byte_length - offset) // 4:
            return refuse('hash32 array span exceeds the target block')
        at, length = target.data_offset + offset, a * 4
        if at < 0 or at + length > len(data):
            raise ValueError('PSIN array target exceeds container bounds')
        result['target'] = dict(block_id=number, block_index=target.index,
                                block_type='0x0000004a', byte_offset=offset,
                                data_offset=at, byte_length=length)
        for i in range(a):
            consume()
            position = at + i * 4
            value = int.from_bytes(data[position:position + 4], 'little')
            result['elements'].append(dict(index=i, status='decoded', data_offset=position,
                byte_length=4, value_bits=f'0x{value:08x}', value=f'0x{value:08x}',
                value_name_matches=psin_schema._matches(dictionary, value)))
    result.update(status='complete', interpretation='inferred', profile=result.pop('candidate_profile'))
    return result
