"""Observed MoVE payload spans, without motion or recursive object decoding.

Two root storage forms are supported. Kind one has immediate field-relative
references whose target headers repeat the ordinal and hash. Kind 22 has
length-prefixed descriptor records, fixed-width cells and length-prefixed
subblocks. Child bodies and remaining tails stay opaque. No external parser,
game-specific hash table, numeric sample or motion semantics is used.
"""
from __future__ import annotations

import hashlib
import struct

from .move import MAX_BYTES, MoveLimitError

PROFILE = 'observed_move_payload_spans_v1'


def inspect_payload(data, offset, length, *, max_nodes=100000):
    """Inspect one bounded payload atomically; unsupported forms keep a reason.

    References are followed one level only, using full-width checked addition.
    Their bounded child bodies are not recursively interpreted. A complete
    storage view does not establish complete object or motion semantics.
    """
    if type(max_nodes) is not int or max_nodes < 1:
        raise MoveLimitError('MoVE object metadata output exceeds node limit')
    used = 0
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, references=[], descriptors=[], regions=[])

    def consume(count=1):
        nonlocal used
        if count > max_nodes - used:
            raise MoveLimitError('MoVE object metadata output exceeds node limit')
        used += count

    def span(at, size, end=None):
        stop = offset + length if end is None else end
        if size < 0 or at < offset or at > stop - size:
            raise ValueError('MoVE payload structure exceeds its bounded span')
        return at

    def bits(at, size):
        return '0x' + data[at:at + size][::-1].hex()

    def opaque(at, size):
        span(at, size)
        return dict(data_offset=at, byte_length=size,
                    sha256=hashlib.sha256(data[at:at + size]).hexdigest(),
                    interpretation='opaque; object and motion meanings unknown')

    def region(name, start, stop):
        return dict(name=name, data_offset=start, byte_length=stop-start)

    consume()
    try:
        if (type(offset) is not int or type(length) is not int or offset < 0
                or length < 20 or length > MAX_BYTES or offset > len(data) - length):
            raise ValueError('unsupported MoVE payload bounds')
        end = offset + length
        kind, ordinal, name = struct.unpack_from('<HHI', data, offset)
        if ordinal != 0 or kind not in (1, 22):
            raise ValueError('unsupported MoVE root kind or ordinal profile')
        limit = struct.unpack_from('<H', data, offset + 18)[0]
        header = dict(raw_kind_u16=kind, raw_ordinal_u16=ordinal,
                      name_hash_bits=f'0x{name:08x}',
                      raw_word_08=f'0x{struct.unpack_from("<I", data, offset+8)[0]:08x}',
                      raw_word_0c=f'0x{struct.unpack_from("<I", data, offset+12)[0]:08x}',
                      raw_u16_10=struct.unpack_from('<H', data, offset+16)[0],
                      raw_u16_12=limit)
        if kind == 1:
            span(offset, 88)
            table_size = struct.unpack_from('<I', data, offset + 84)[0]
            table_end = offset + 84 + table_size
            if (not limit or table_size != 4 + 8 * limit
                    or offset + 36 + struct.unpack_from('<I', data, offset+36)[0] != table_end):
                raise ValueError('MoVE root reference count or redundant table extent differs')
            span(offset + 84, table_size)
            consume(6 + 4 * limit)
            refs = []
            for i in range(limit):
                at = offset + 88 + 8*i
                hashed, relative = struct.unpack_from('<II', data, at)
                target = at + 4 + relative
                span(target, 8)
                if target < table_end or (refs and target <= refs[-1][2]):
                    raise ValueError('MoVE immediate object targets overlap table or differ from source order')
                child_kind, child_ordinal, child_hash = struct.unpack_from('<HHI', data, target)
                if child_ordinal != i or child_hash != hashed:
                    raise ValueError('MoVE object target ordinal or hash differs from its reference')
                refs.append((at, relative, target, child_kind, child_hash))
            if any(b[2] - a[2] < 8 for a, b in zip(refs, refs[1:])):
                raise ValueError('MoVE object target headers overlap')
            records, opaque_parts = [], [opaque(table_end, refs[0][2]-table_end)]
            regions = [region('root_header', offset, offset+84),
                       region('reference_table', offset+84, table_end),
                       region('opaque_before_objects', table_end, refs[0][2])]
            for i, (at, relative, target, child_kind, child_hash) in enumerate(refs):
                stop = refs[i+1][2] if i+1 < len(refs) else end
                records.append(dict(index=i, data_offset=at, byte_length=8,
                    hash_bits=f'0x{child_hash:08x}', offset_field_data_offset=at+4,
                    relative_offset_bits=f'0x{relative:08x}', target_data_offset=target,
                    target_byte_length=stop-target,
                    child_header=dict(raw_kind_u16=child_kind, raw_ordinal_u16=i,
                                      name_hash_bits=f'0x{child_hash:08x}', value_bits=bits(target, 8)),
                    interpretation='bounded immediate field-relative target; child body remains opaque'))
                opaque_parts.append(opaque(target+8, stop-target-8))
                regions.append(region(f'referenced_object_{i}', target, stop))
            header['header_bits'] = bits(offset, 84)
            result.update(form='immediate_relative_references', references=records,
                reference_table=dict(count_data_offset=offset+84, data_offset=offset+84,
                                     records_data_offset=offset+88, byte_length=table_size, count=limit),
                opaque_regions=opaque_parts, regions=regions)
            counts = dict(references=limit, descriptor_records=0, fixed_cells=0, nested_blocks=0)
        else:
            span(offset, 56)
            if not limit or struct.unpack_from('<III', data, offset+32) != (0, 12, 8):
                raise ValueError('unsupported MoVE descriptor-root header profile')
            count = struct.unpack_from('<I', data, offset+44)[0]
            if count > limit:
                raise ValueError('MoVE descriptor count exceeds its raw index bound')
            consume(6)
            records, pos, previous, cells, nested = [], offset+48, -1, 0, 0
            for i in range(count):
                span(pos, 12)
                size, index, a, b, c, d, e, reserved = struct.unpack_from('<IH6B', data, pos)
                if size < 12 or size % 4 or reserved:
                    raise ValueError('unsupported MoVE descriptor size or reserved count byte')
                span(pos, size)
                if not previous < index < limit:
                    raise ValueError('MoVE descriptor indices are unordered, duplicate or outside raw bound')
                previous = index
                cursor = pos + 12
                fixed_size = 16*(a+b+c) + 8*d
                span(cursor, fixed_size, pos+size)
                consume(5 + a+b+c+d + 2*e)
                groups = []
                for group, (number, stride) in enumerate(zip((a,b,c,d),(16,16,16,8))):
                    groups.append(dict(group_index=group, count=number, record_stride=stride,
                        data_offset=cursor, byte_length=number*stride,
                        interpretation='raw fixed-width cells; group and numeric meanings unknown',
                        cells=[dict(index=j, data_offset=cursor+j*stride, byte_length=stride,
                                    value_bits=bits(cursor+j*stride, stride)) for j in range(number)]))
                    cursor += number*stride
                subblocks = []
                for j in range(e):
                    span(cursor, 8, pos+size)
                    w = struct.unpack_from('<4H', data, cursor)
                    if w[2] < 8 or w[2] % 4:
                        raise ValueError('unsupported MoVE descriptor subblock length')
                    span(cursor, w[2], pos+size)
                    subblocks.append(dict(index=j, data_offset=cursor, byte_length=w[2],
                        raw_u16_00=w[0], raw_u16_02=w[1], raw_u16_06=w[3],
                        header_bits=bits(cursor, 8), body=opaque(cursor+8, w[2]-8)))
                    cursor += w[2]
                if cursor != pos+size:
                    raise ValueError('unaccounted MoVE descriptor bytes')
                records.append(dict(index=i, data_offset=pos, byte_length=size,
                    raw_index_u16=index, header_bits=bits(pos, 12), raw_count_bytes=[a,b,c,d,e,reserved],
                    fixed_groups=groups, nested_blocks=subblocks,
                    interpretation='bounded descriptor storage; index association and field meanings unknown'))
                cells += a+b+c+d
                nested += e
                pos += size
            span(pos, 8)
            if struct.unpack_from('<H', data, pos+2)[0] != 0:
                raise ValueError('unsupported first opaque-tail ordinal profile')
            header['header_bits'] = bits(offset, 48)
            result.update(form='length_prefixed_descriptors', descriptors=records,
                descriptor_table=dict(count_data_offset=offset+44, data_offset=offset+48,
                                      byte_length=pos-offset-48, count=count),
                opaque_regions=[opaque(pos, end-pos)],
                regions=[region('root_header',offset,offset+48),
                         region('descriptor_records',offset+48,pos), region('opaque_object_tail',pos,end)])
            counts = dict(references=0, descriptor_records=count, fixed_cells=cells, nested_blocks=nested)
        result.update(status='complete', interpretation='bounded root storage only; nested object and motion semantics remain unknown',
                      profile=result.pop('candidate_profile'), header=header,
                      summary=dict(nodes=used, **counts))
    except MoveLimitError:
        raise
    except (ValueError, struct.error) as exc:
        # Reset all lists: no apparently successful prefix escapes a refusal.
        result = dict(status='unresolved', interpretation='candidate', candidate_profile=PROFILE,
                      reason=str(exc), references=[], descriptors=[], regions=[], summary=dict(nodes=1))
    return result
