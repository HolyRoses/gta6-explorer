"""Bounded local PSIN array profiles from direct byte observations.

The equal u16 header words are retained without assigning count/capacity roles.
Local hash32 descriptors authorize complete spans in intrinsic hash pools.
Structure arrays link existing local typed records without expanding them.
Reference arrays use a bounded intrinsic word pool and locally typed record
targets, preserving null slots. No recursive reference chains or maps are read.
No external implementation, mapping table or game fixture is used.
"""
from __future__ import annotations

import struct

from . import psin_schema, psin_references


def _header(data, start, descriptor_index, profile):
    if start < 0 or start + 16 > len(data):
        raise ValueError('PSIN array header exceeds container bounds')
    word, a, b, tail = struct.unpack_from('<QHHI', data, start)
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=profile,
                  header_bits='0x' + data[start:start + 16][::-1].hex(),
                  reference_bits=f'0x{word:016x}', u16_08=a, u16_0a=b,
                  unknown_0c=f'0x{tail:08x}', element_descriptor_index=descriptor_index,
                  elements=[])
    return result, word, a, b, tail


def resolve_hash32(data, start, owner, descriptor_index, blocks, *, local_owner,
                   local_structures, consume, dictionary=None):
    """Resolve an already bounded 16-byte header; never follow another pointer.

    Caller verifies the header fits its owning record and instance block.
    Unsupported profiles return explicit diagnostics and no prefix of values.
    The shared consume callback raises on budget exhaustion, discarding output.
    """
    result, word, a, b, tail = _header(data, start, descriptor_index, 'hash32_equal_u16_v1')

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


def resolve_structure_links(data, start, owner, descriptor_index, blocks, *,
                            local_owner, local_structures, consume):
    """Link an exact local structure-array span to already typed record rows.

    The caller bounds the header within its record/block. Targets must have
    exactly one local definition; signatures or plausible sizes never choose
    among candidates. Links consume nodes, never decode/expand target records.
    """
    result, word, a, b, tail = _header(data, start, descriptor_index, 'structure_equal_u16_v1')
    result.update(element_type='structure', mode='record_links')

    def refuse(reason):
        return dict(result, reason=reason)

    if not local_owner:
        return refuse('structure-array resolution requires a local owning schema')
    if not 0 <= descriptor_index < len(owner.fields):
        return refuse('structure-array element descriptor index is out of bounds')
    descriptor = owner.fields[descriptor_index]
    if descriptor.name_hash != 0x100 or descriptor.data_offset != 0 or descriptor.type_word != 5:
        return refuse('array element descriptor is not the supported local structure profile')
    result['structure_hash'] = f'0x{descriptor.auxiliary:08x}'
    definitions = local_structures.get(descriptor.auxiliary, [])
    if len(definitions) != 1:
        return refuse('missing or ambiguous local structure-array target schema')
    definition = definitions[0]
    stride = definition.byte_size
    if stride == 0:
        return refuse('zero-sized structure-array elements are not validated')
    result.update(stride=stride, structure_definition_offset=definition.section_offset)
    if a != b or tail != 0:
        return refuse('unvalidated structure-array header: requires equal u16 words and zero tail')
    result['count'] = a
    if a == 0:
        if word != 0:
            return refuse('empty structure array with nonzero reference is not validated')
        result['target'] = None
    else:
        number, offset = word & 0xfffff, word >> 20
        if not 1 <= number <= len(blocks):
            return refuse('structure-array reference has an invalid one-based block ID')
        target = blocks[number - 1]
        if target.type_hash != descriptor.auxiliary:
            return refuse('structure-array target block type differs from the local element schema')
        if target.byte_length % stride or offset % stride:
            return refuse('structure-array target block or offset is not a whole local record stride')
        if offset > target.byte_length or a > (target.byte_length - offset) // stride:
            return refuse('structure-array span exceeds the target block')
        at, length = target.data_offset + offset, a * stride
        if at < 0 or at + length > len(data):
            raise ValueError('PSIN structure-array target exceeds container bounds')
        result['target'] = dict(block_id=number, block_index=target.index,
            block_type=f'0x{target.type_hash:08x}', byte_offset=offset,
            data_offset=at, byte_length=length)
        for i in range(a):
            consume()
            result['elements'].append(dict(index=i, status='record_reference',
                block_index=target.index, record_index=offset // stride + i,
                data_offset=at + i * stride, byte_length=stride,
                structure_hash=f'0x{definition.name_hash:08x}'))
    result.update(status='complete', interpretation='inferred', profile=result.pop('candidate_profile'))
    return result


def resolve_reference_links(data, start, owner, descriptor_index, blocks, *,
                            local_owner, local_structures, consume):
    """Bind an intrinsic reference-word span to local records, without expansion.

    The caller bounds the header inside its record/block. Every nonzero member
    must select a whole locally typed record. Any failure discards all member
    links; only its explicit slot/word diagnostic is returned, never a prefix.
    """
    result, word, a, b, tail = _header(data, start, descriptor_index, 'reference_equal_u16_v1')
    result.update(element_type='reference', mode='reference_record_links')

    def refuse(reason, index=None, reference=None, position=None):
        failure = dict(result, reason=reason)
        if index is not None:
            failure.update(failed_element_index=index, failed_reference_bits=f'0x{reference:016x}',
                           failed_reference_data_offset=position)
        return failure

    if not local_owner:
        return refuse('reference-array resolution requires a local owning schema')
    if not 0 <= descriptor_index < len(owner.fields):
        return refuse('reference-array element descriptor index is out of bounds')
    descriptor = owner.fields[descriptor_index]
    if (descriptor.name_hash != 0x100 or descriptor.data_offset != 0
            or descriptor.type_word != 7 or descriptor.auxiliary != 0):
        return refuse('array element descriptor is not the supported local reference profile')
    if a != b or tail != 0:
        return refuse('unvalidated reference-array header: requires equal u16 words and zero tail')
    result['count'] = a
    links = []
    nulls = 0
    if a == 0:
        if word != 0:
            return refuse('empty reference array with nonzero reference is not validated')
        result['target'] = None
    else:
        number, offset = word & 0xfffff, word >> 20
        if not 1 <= number <= len(blocks):
            return refuse('reference-array pool reference has an invalid one-based block ID')
        pool = blocks[number - 1]
        if pool.type_hash != 7 or local_structures.get(7):
            return refuse('reference-array target is not an unambiguous intrinsic reference pool')
        if pool.byte_length % 8 or offset % 8:
            return refuse('reference-array pool or offset is not eight-byte aligned')
        if offset > pool.byte_length or a > (pool.byte_length - offset) // 8:
            return refuse('reference-array span exceeds its reference pool')
        at, length = pool.data_offset + offset, a * 8
        if at < 0 or at + length > len(data):
            raise ValueError('PSIN reference-array pool exceeds container bounds')
        result['target'] = dict(block_id=number, block_index=pool.index, block_type='0x00000007',
            byte_offset=offset, data_offset=at, byte_length=length)
        for i in range(a):
            consume()
            position = at + i * 8
            reference = struct.unpack_from('<Q', data, position)[0]
            entry = dict(index=i, reference_data_offset=position, reference_byte_length=8,
                         reference_bits=f'0x{reference:016x}', pool_element_index=offset // 8 + i)
            bound = psin_references.bind_record(reference, blocks, local_structures, data_size=len(data))
            if bound['status'] == 'unresolved':
                reason = dict(invalid_id='reference-array member has an invalid record block ID',
                    schema='reference-array member has no unique positive-sized local record schema',
                    span='reference-array member does not select a whole bounded local record')[bound['failure']]
                return refuse(reason, i, reference, position)
            links.append(dict(entry, **bound))
            nulls += bound['status'] == 'null_reference'
    result.update(status='complete', interpretation='inferred', profile=result.pop('candidate_profile'),
                  elements=links, null_count=nulls, record_link_count=len(links) - nulls)
    return result
