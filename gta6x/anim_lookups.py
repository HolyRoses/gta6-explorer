"""Checked source-order indexed-payload candidates in packed animation.

Candidate code spans address dense packed lookup entries and exhaust their
word extents with zero high bits. Ordering, channel/slot associations, numeric
sample representations and codec meanings remain unconfirmed.
"""
from __future__ import annotations

import hashlib
import struct

from . import anim_bitrows, anim_resources as resources

PROFILE = 'source_order_indexed_payload_candidates_v1'


def inspect_buffer(data, offset, length, binding_count, *, consume):
    """Validate one candidate partition atomically without assigning channels.

    Fixed-width row bits remain an opaque prefix. Each variable source record
    supplies a candidate index width and packed-entry width. Every observed
    index must occur densely from zero; its highest index must explain the
    exact payload allocation and zero high padding. These checks do not prove
    a unique ordering, so there is no directory-slot or binding assignment.
    """
    consume()
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, lookup_candidates=[])
    try:
        view = anim_bitrows.inspect_buffer(data, offset, length, binding_count,
                                           consume=lambda n=1: None)
        if view['status'] != 'complete':
            raise ValueError('lookup candidates require supported bit rows: ' + view['reason'])
        records = view['variable_width_records']
        if not records:
            raise ValueError('no variable indexed-payload candidate in this buffer')
        rows = [int(row['raw_bits'], 16) for row in view['rows']]
        if not rows:
            raise ValueError('indexed-payload candidates require nonempty stored rows')
        bit = view['fixed_table']['width_sum_bits']
        candidates = []
        for index, record in enumerate(records):
            width = record['width_bits']
            entry_width = int(record['unknown_u32_04'], 16)
            if not 1 <= entry_width <= 32:
                raise ValueError('unsupported packed lookup-entry width; requires 1..32 bits')
            codes = [(row >> bit) & ((1 << width) - 1) for row in rows]
            count = max(codes) + 1
            if min(codes) != 0 or len(set(codes)) != count:
                raise ValueError('candidate indices do not densely cover zero through the observed maximum')
            payload = record['opaque_payload']
            active_bits = count * entry_width
            if payload['byte_length'] != 4 * ((active_bits + 31) // 32):
                raise ValueError('candidate indices and entry width disagree with packed lookup word extent')
            start, size = payload['data_offset'], payload['byte_length']
            raw = int.from_bytes(data[start:start+size], 'little')
            if raw >> active_bits:
                raise ValueError('nonzero high padding above observed packed lookup entries')
            consume(2 + count)
            entries = []
            for code in range(count):
                entry_bit = code * entry_width
                local_bit = entry_bit % 8
                entries.append(dict(index=code, data_offset=start+entry_bit//8,
                    source_bit_offset=local_bit, bit_length=entry_width,
                    byte_length=(local_bit+entry_width+7)//8,
                    raw_bits=f'0x{(raw >> entry_bit) & ((1 << entry_width)-1):x}'))
            candidates.append(dict(source_ordinal=index, variable_record_index=index,
                row_bit_offset=bit, index_width_bits=width, row_count=len(codes),
                observed_index_count=count, packed_entry_width_bits=entry_width,
                packed_entries=dict(data_offset=start, byte_length=size,
                    active_bits=active_bits, high_zero_padding_bits=size*8-active_bits),
                index_sequence_sha256=hashlib.sha256(b''.join(struct.pack('<I', c) for c in codes)).hexdigest(),
                entries=entries))
            bit += width
        if bit != view['row_layout']['active_bits_per_row']:
            raise ValueError('candidate partitions do not exhaust the checked row bit width')
        consume(2)
        result.update(status='complete', profile=result.pop('candidate_profile'),
            interpretation='checked source-order indexed-payload candidates; raw bits only',
            association_status='unconfirmed; order may be ambiguous and no slot or channel is assigned',
            fixed_prefix_bits=view['fixed_table']['width_sum_bits'],
            row_layout=dict(view['row_layout']), lookup_candidates=candidates,
            record_count=len(candidates), entry_count=sum(len(c['entries']) for c in candidates),
            index_observation_count=len(rows)*len(candidates))
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
