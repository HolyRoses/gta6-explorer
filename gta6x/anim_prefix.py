"""Measured packed-animation prefix spans and counted opaque storage.

Leading words retain a source-order grouping only. Trailing record lengths
exhaust an independently bounded span; their bodies remain opaque. No slot,
individual group, scalar, transform, quantizer or codec meaning is inferred.
"""
from __future__ import annotations

import hashlib
import struct

from . import anim_bitrows, anim_channels, anim_resources as resources

PROFILE = 'mixed_prefix_words_and_counted_opaque_records_v1'
MIN_RECORD_WORDS = 13


def inspect_buffer(data, offset, length, binding_count, *, consume):
    """Partition the observed prefix atomically without interpreting values."""
    consume()
    result = dict(status='unresolved', interpretation='candidate', candidate_profile=PROFILE,
                  triplet_records=[], word_records=[], opaque_records=[], regions=[])
    try:
        bits = anim_bitrows.inspect_buffer(data, offset, length, binding_count,
                                           consume=lambda n=1: None)
        if bits['status'] != 'complete':
            raise ValueError('prefix requires supported counted bit tables: ' + bits['reason'])
        directory = anim_channels.inspect_buffer(data, offset, length, binding_count,
                                                  consume=lambda n=1: None)
        if directory['status'] != 'complete':
            raise ValueError('prefix requires a supported directory: ' + directory['reason'])
        counts = [group['count'] for group in directory['groups']]
        start = offset + 32
        triplet_count, word_count = counts[0]+counts[1], counts[2]
        word_start = start + 12*triplet_count
        fixed = bits['fixed_table']; variable = bits['variable_table']
        if word_start + 4*word_count != fixed['data_offset']:
            raise ValueError('leading prefix counts disagree with independently checked width-table origin')
        trailing = bits['remaining_prefix']
        at, end = trailing['data_offset'], trailing['data_offset']+trailing['byte_length']
        opaque_records = []
        for index in range(counts[10]):
            if at > end-4:
                raise ValueError('counted prefix record length exceeds its bounded span')
            words = struct.unpack_from('<I', data, at)[0]
            if words < MIN_RECORD_WORDS:
                raise ValueError('prefix record is below the observed thirteen-word profile')
            if words > (end-at)//4:
                raise ValueError('counted prefix record exceeds the logical pre-row boundary')
            size = 4*words
            consume(2)
            opaque_records.append(dict(source_ordinal=index, data_offset=at, byte_length=size,
                length_data_offset=at, length_word_bits=f'0x{words:08x}', word_count=words,
                body=dict(data_offset=at+4, byte_length=size-4,
                    sha256=hashlib.sha256(data[at+4:at+size]).hexdigest(), interpretation='opaque')))
            at += size
        if at != end:
            raise ValueError('counted prefix records do not exhaust the independently bounded remainder')
        consume(7+triplet_count+word_count)
        triplets = [dict(source_ordinal=i, data_offset=start+12*i, byte_length=12,
                         raw_words=[f'0x{v:08x}' for v in struct.unpack_from('<3I', data, start+12*i)])
                    for i in range(triplet_count)]
        words = [dict(source_ordinal=i, data_offset=word_start+4*i, byte_length=4,
                      raw_bits=f'0x{struct.unpack_from("<I", data, word_start+4*i)[0]:08x}')
                 for i in range(word_count)]
        spans = [('leading_triplet_grouping',start,word_start),
                 ('leading_word_grouping',word_start,fixed['data_offset']),
                 ('fixed_width_table',fixed['data_offset'],variable['data_offset']),
                 ('variable_width_table',variable['data_offset'],trailing['data_offset']),
                 ('counted_opaque_records',trailing['data_offset'],end)]
        result.update(status='complete', profile=result.pop('candidate_profile'),
            interpretation='inferred bounded prefix storage; raw leading words and opaque counted bodies only',
            association_status='unconfirmed; no individual group, slot, binding or numeric meaning assigned',
            prefix=dict(data_offset=start, byte_length=end-start),
            count_context=dict(combined_group0_group1_count=triplet_count, group2_count=word_count,
                               group10_count=counts[10], unassigned_group7_count=counts[7],
                               unassigned_group8_count=counts[8]),
            triplet_records=triplets, word_records=words, opaque_records=opaque_records,
            regions=[dict(name=name, data_offset=a, byte_length=b-a) for name,a,b in spans],
            triplet_count=triplet_count, word_count=3*triplet_count+word_count,
            opaque_record_count=len(opaque_records))
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
