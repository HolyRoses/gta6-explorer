"""Narrow raw-word inventory for a group-zero-only animation storage profile.

Source-ordered twelve-byte records and directory slot candidates are reported
separately. Their same-ordinal association is unconfirmed. No numeric samples,
constant values, scalar types, transforms, channel meanings or codecs decode.
"""
from __future__ import annotations

import struct

from . import anim_channels, anim_storage, anim_resources as resources

PROFILE = 'group_zero_only_raw_word_records_v1'


def inspect_buffer(data, offset, length, binding_count, *, consume):
    """Inventory a supported raw prefix atomically, or retain one refusal.

    The narrow profile requires only group zero, one sub-index-zero slot per
    binding, no stored sample rows/auxiliary bytes and twelve prefix bytes per
    slot. These guards identify an observed storage shape, not its semantics.
    All records and separate slot candidates charge the shared output budget.
    """
    consume()
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, records=[], slot_candidates=[])
    try:
        storage = anim_storage.inspect_buffer(data, offset, length, binding_count,
                                              consume=lambda n=1: None)
        if storage['status'] != 'complete':
            raise ValueError('payload inventory requires supported storage: ' + storage['reason'])
        directory = anim_channels.inspect_buffer(data, offset, length, binding_count,
                                                  consume=lambda n=1: None)
        groups = directory['groups']
        if not groups[0]['count'] or any(group['count'] for group in groups[1:]):
            raise ValueError('raw payload profile requires only directory group zero')
        slots = [slot['slot_index'] for slot in groups[0]['slots']]
        if slots != list(range(0, binding_count * 4, 4)):
            raise ValueError('raw payload profile requires one sub-index-zero slot per binding')
        rows = storage['sample_rows']
        if rows['byte_length'] or rows['row_stride']:
            raise ValueError('raw payload profile requires empty stored sample rows')
        if storage['sample_bit_layout']['status'] != 'complete':
            raise ValueError('raw payload profile requires the supported empty bit-row grammar')
        prefix = storage['regions'][1]
        auxiliary = storage['regions'][4]
        if auxiliary['byte_length']:
            raise ValueError('raw payload profile with auxiliary bytes is not established')
        count = groups[0]['count']
        if prefix['byte_length'] != 12 * count:
            raise ValueError('raw payload prefix is not twelve bytes per group-zero slot')
        consume(2 + 2 * count)  # Prefix/association views, records and slot candidates.
        records, candidates = [], []
        for ordinal, slot in enumerate(groups[0]['slots']):
            at = prefix['data_offset'] + 12 * ordinal
            records.append(dict(source_ordinal=ordinal, data_offset=at, byte_length=12,
                raw_words=[f'0x{word:08x}' for word in struct.unpack_from('<3I', data, at)],
                interpretation='raw little-endian words; numeric and temporal meaning unknown'))
            candidates.append(dict(source_ordinal=ordinal, group_index=0,
                slot_index=slot['slot_index'], binding_index=slot['binding_index'],
                sub_index=slot['sub_index'],
                interpretation='same-ordinal directory candidate; record association unconfirmed'))
        result.update(status='complete', profile=result.pop('candidate_profile'),
            interpretation='bounded source-order raw words only; slot association and sample meanings unconfirmed',
            prefix=dict(data_offset=prefix['data_offset'], byte_length=prefix['byte_length']),
            record_count=count, word_count=3 * count, slot_candidate_count=count,
            association_status='unconfirmed', records=records, slot_candidates=candidates)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
