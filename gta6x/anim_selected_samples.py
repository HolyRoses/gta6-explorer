"""Selected raw packed-animation codes, without channel or numeric decoding.

The complete existing source-order lookup profile is checked before emitting a
requested source/row subset. Selection reduces output, not the validation scope;
source order and temporal/channel associations remain explicitly unconfirmed.
"""
from __future__ import annotations

import hashlib
import struct

from . import anim_channels, anim_lookups, anim_resources as resources
from .anim_samples import _bits

PROFILE = 'selected_source_order_raw_sample_code_candidates_v1'
MAX_SOURCES = 64


def _selection(source_ordinals, row_start, row_count):
    if (not isinstance(source_ordinals, (list, tuple))
            or not 1 <= len(source_ordinals) <= MAX_SOURCES
            or any(type(value) is not int or value < 0 for value in source_ordinals)
            or len(set(source_ordinals)) != len(source_ordinals)):
        raise ValueError('select 1..64 distinct nonnegative source ordinals')
    if type(row_start) is not int or row_start < 0:
        raise ValueError('selected row start must be a nonnegative integer')
    if type(row_count) is not int or row_count < 1:
        raise ValueError('selected row count must be a positive integer')
    return tuple(source_ordinals)


def inspect_buffer(data, offset, length, binding_count, *, source_ordinals,
                   row_start=0, row_count=1, consume):
    """Inspect an exact selected product with complete parent-profile validation.

    Malformed/unsupported inputs produce an atomic unresolved view. Shared work
    exhaustion propagates. Mutable input bytes and selection lists are copied
    before a caller callback can change them. No caller-supplied parse cache or
    metadata is accepted. Bounds are exact: selected rows are never clipped.
    """
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, selected_sequences=[])
    try:
        sources = _selection(source_ordinals, row_start, row_count)
        if not isinstance(data, (bytes, bytearray)) or len(data) > resources.MAX_RESOURCE:
            raise ValueError('selected sample input requires bounded bytes')
        if (type(offset) is not int or type(length) is not int
                or offset < 0 or length < 32 or offset > len(data) - length):
            raise ValueError('selected sample buffer exceeds input bounds')
        if type(binding_count) is not int or not 1 <= binding_count <= 16383:
            raise ValueError('selected samples require 1..16383 caller-supplied binding rows')
        data = bytes(data)
        consume()
        directory = anim_channels.inspect_buffer(data, offset, length, binding_count,
                                                  consume=consume)
        if directory['status'] != 'complete':
            raise ValueError('selected samples require a checked directory: ' + directory['reason'])
        source_count = directory['groups'][5]['count']
        stored_rows = struct.unpack_from('<H', data, offset + 22)[0]
        if not source_count:
            raise ValueError('no variable indexed-payload candidate in this buffer')
        if max(sources) >= source_count:
            raise ValueError('selected source ordinal exceeds the variable-record count')
        if row_start >= stored_rows or row_count > stored_rows - row_start:
            raise ValueError('selected row range exceeds stored rows; ranges are not clipped')
        # The inherited lookup checker examines all row/record combinations.
        # Reserve that work before it creates row/code lists, plus the selected
        # output product before allocating any returned observation or span.
        validation_units = stored_rows * (source_count + 1) + source_count
        observation_count = row_count * len(sources)
        consume(validation_units + 3 + len(sources) + 3 * observation_count)
        lookups = anim_lookups.inspect_buffer(data, offset, length, binding_count,
                                              consume=consume)
        if lookups['status'] != 'complete':
            raise ValueError('selected samples require checked lookup candidates: ' + lookups['reason'])
        layout = lookups['row_layout']
        if (lookups['record_count'] != source_count
                or layout['stored_rows_emitted'] != stored_rows):
            raise ValueError('selected sample preflight disagrees with checked source dimensions')
        sequences = []
        for ordinal in sources:
            record = lookups['lookup_candidates'][ordinal]
            if record['source_ordinal'] != ordinal:
                raise ValueError('checked lookup source ordinal disagrees with source position')
            payload = record['packed_entries']
            payload_start = payload['data_offset']
            payload_end = payload_start + payload['byte_length']
            observations = []
            selected_hash = hashlib.sha256()
            for row in range(row_start, row_start + row_count):
                at = layout['data_offset'] + row * layout['row_stride']
                code, index_source = _bits(data, at, record['row_bit_offset'],
                                           record['index_width_bits'], at + layout['row_stride'])
                if code >= record['observed_index_count']:
                    raise ValueError('selected raw row code exceeds the checked index domain')
                raw, entry_source = _bits(data, payload_start, code * record['packed_entry_width_bits'],
                                           record['packed_entry_width_bits'], payload_end)
                bits = f'0x{raw:x}'
                if bits != record['entries'][code]['raw_bits']:
                    raise ValueError('selected entry bits disagree with original checked lookup')
                selected_hash.update(struct.pack('<I', code))
                observations.append(dict(source_row_ordinal=row, index_code=code,
                    raw_entry_bits=bits, index_source=index_source, entry_source=entry_source))
            sequences.append(dict(source_ordinal=ordinal,
                variable_record_index=record['variable_record_index'],
                row_bit_offset=record['row_bit_offset'], index_width_bits=record['index_width_bits'],
                packed_entry_width_bits=record['packed_entry_width_bits'],
                observed_index_count=record['observed_index_count'],
                full_index_sequence_sha256=record['index_sequence_sha256'],
                selected_index_sequence_sha256=selected_hash.hexdigest(), observations=observations))
        result.update(status='complete', profile=result.pop('candidate_profile'),
            interpretation='selected raw source-order codes and packed entry bits only',
            association_status='unconfirmed; source order is conditional and no channel or bone is assigned',
            semantic_status='unconfirmed; raw entry bits are not numeric samples, poses or times',
            source_order='stored row order; temporal ordering is unconfirmed',
            validation_scope='complete existing lookup profile; output selection does not narrow validation',
            source_row_count=stored_rows, source_record_count=source_count,
            selection=dict(source_ordinals=list(sources), row_start=row_start, row_count=row_count),
            sequence_count=len(sources), observation_count=observation_count,
            validation_work_reserved=validation_units, selected_sequences=sequences)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result


def inspect_file(path, *, binding_count, source_ordinals, row_start=0, row_count=1,
                 max_nodes=100000):
    """Read one bounded raw buffer and return its exact byte identity and view.

    This performs no archive search, extraction, joining or file writes. The
    supplied binding count is structural context, not an authenticated table.
    """
    sources = _selection(source_ordinals, row_start, row_count)
    if type(binding_count) is not int or not 1 <= binding_count <= 16383:
        raise ValueError('selected samples require 1..16383 caller-supplied binding rows')
    if type(max_nodes) is not int or max_nodes < 1:
        raise resources.ResourceLimitError('selected sample work limit must be positive')
    with open(path, 'rb') as stream:
        data = stream.read(resources.MAX_RESOURCE + 1)
    if len(data) > resources.MAX_RESOURCE:
        raise resources.ResourceLimitError('raw packed buffer exceeds resource size limit')
    used = 0
    def consume(amount=1):
        nonlocal used
        if amount > max_nodes - used:
            raise resources.ResourceLimitError('selected sample work exceeds --max-nodes')
        used += amount
    report = inspect_buffer(data, 0, len(data), binding_count, source_ordinals=sources,
                            row_start=row_start, row_count=row_count, consume=consume)
    report['source'] = dict(byte_length=len(data), sha256=hashlib.sha256(data).hexdigest(),
        binding_count=binding_count, binding_context='caller-supplied count; table identity is not authenticated')
    report['work_units'] = used
    return report
