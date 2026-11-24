"""Raw source-row codes and indexed entry bits under a conditional partition.

This extends the existing checked source-order lookup candidate view. It does
not establish a channel binding, scalar representation, sample timing or codec.
"""
from __future__ import annotations

import hashlib
import struct

from . import anim_lookups, anim_resources as resources

PROFILE = 'source_order_raw_sample_code_candidates_v1'


def _bits(data, offset, bit, width, end):
    """Extract at most 32 little-endian bits from a checked source interval."""
    if not 1 <= width <= 32 or bit < 0:
        raise ValueError('raw code width/bit offset exceeds the supported profile')
    at, shift = offset + bit // 8, bit % 8
    size = (shift + width + 7) // 8
    if offset < 0 or not offset <= at <= end - size or end > len(data):
        raise ValueError('raw code source crosses its independently bounded interval')
    value = (int.from_bytes(data[at:at + size], 'little') >> shift) & ((1 << width) - 1)
    return value, dict(data_offset=at, source_bit_offset=shift,
                       bit_length=width, byte_length=size)


def inspect_buffer(data, offset, length, binding_count, *, consume):
    """Materialize conditional raw sequences, with atomic refusal and budgets.

    Every index is read again from its exact row span. Each selected entry is
    read directly from the original packed payload, independently of the prior
    view's entry strings. No mutable caller-supplied metadata is accepted.
    """
    consume()
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, candidate_sequences=[])
    try:
        lookups = anim_lookups.inspect_buffer(data, offset, length, binding_count, consume=consume)
        if lookups['status'] != 'complete':
            raise ValueError('raw sample codes require checked lookup candidates: ' + lookups['reason'])
        layout = lookups['row_layout']
        count, stride = layout['stored_rows_emitted'], layout['row_stride']
        records = lookups['lookup_candidates']
        # Reserve the entire output product before allocating any observation.
        # Each observation owns an object plus two exact source-span objects.
        consume(2 + len(records) + 3 * count * len(records))
        sequences = []
        for record in records:
            rows, code_hash = [], hashlib.sha256()
            payload = record['packed_entries']
            payload_start = payload['data_offset']
            payload_end = payload_start + payload['byte_length']
            width = record['packed_entry_width_bits']
            for ordinal in range(count):
                row_at = layout['data_offset'] + ordinal * stride
                code, index_source = _bits(data, row_at, record['row_bit_offset'],
                                          record['index_width_bits'], row_at + stride)
                if code >= record['observed_index_count']:
                    raise ValueError('raw row code exceeds the checked observed index domain')
                value, entry_source = _bits(data, payload_start, code * width, width, payload_end)
                raw_bits = f'0x{value:x}'
                if raw_bits != record['entries'][code]['raw_bits']:
                    raise ValueError('direct packed entry bits disagree with the checked lookup view')
                code_hash.update(struct.pack('<I', code))
                rows.append(dict(source_row_ordinal=ordinal, index_code=code, raw_entry_bits=raw_bits,
                                 index_source=index_source, entry_source=entry_source))
            if code_hash.hexdigest() != record['index_sequence_sha256']:
                raise ValueError('direct row codes disagree with the checked sequence hash')
            sequences.append(dict(source_ordinal=record['source_ordinal'],
                variable_record_index=record['variable_record_index'],
                row_bit_offset=record['row_bit_offset'], index_width_bits=record['index_width_bits'],
                packed_entry_width_bits=width, observed_index_count=record['observed_index_count'],
                index_sequence_sha256=code_hash.hexdigest(), observations=rows))
        result.update(status='complete', profile=result.pop('candidate_profile'),
            interpretation='conditional source-order raw code and packed entry-bit sequences only',
            association_status='unconfirmed; source order is assumed and no channel or bone is assigned',
            semantic_status='unconfirmed; raw entry bits are not numeric samples, poses or times',
            source_order='stored row order; temporal ordering is unconfirmed',
            candidate_sequences=sequences, sequence_count=len(sequences),
            observation_count=count * len(sequences), source_row_count=count)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
