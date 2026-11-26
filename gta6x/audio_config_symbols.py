"""Same-namespace symbol uses in one already-validated config directory.

An occurrence is a listed native reference word, not a provider definition.
Index spans locate source storage without assigning runtime field ownership.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
import struct

from . import audio_config_providers


def _uses(directory, symbols, consume):
    groups = {}
    for symbol in symbols:
        identity = symbol['raw_flags'], int(symbol['reference_hash'], 16)
        if identity in groups:
            continue
        consume()
        groups[identity] = dict(raw_flags=identity[0], reference_hash=f'0x{identity[1]:08x}',
            reference_indices=[], occurrences=[], status='unresolved_namespace')

    indices = {}
    for ordinal, (key, flags) in enumerate(directory.rows):
        identity = flags, key
        if identity in groups:
            consume()
            groups[identity]['reference_indices'].append(ordinal)
            indices[ordinal] = identity

    ordered = sorted(directory.records.values(), key=lambda record: record['data_offset'])
    starts = [record['data_offset'] for record in ordered]
    spans = {}
    unplaced = count = 0
    for at in directory.locations:
        index, = struct.unpack_from('<I', directory.data, at)
        identity = indices.get(index)
        if identity is None:
            continue
        consume()
        occurrence = directory.resolve_at(at)
        ordinal = bisect_right(starts, at) - 1
        record = ordered[ordinal] if ordinal >= 0 else None
        if record is None or at + 4 > record['data_offset'] + record['byte_length']:
            occurrence['placement'] = 'not_contained_in_one_index_span'
            unplaced += 1
        else:
            key = record['name_hash']
            if key not in spans:
                consume()
                size = record['byte_length']
                spans[key] = dict(name_hash=key, data_offset=record['data_offset'],
                    indexed_span_bytes=size, matched_reference_words=0,
                    full_kind_word=(f"0x{struct.unpack_from('<I', directory.data, record['data_offset'])[0]:08x}"
                                    if size >= 4 else None))
            spans[key]['matched_reference_words'] += 1
            occurrence.update(placement='within_index_span', source_hash=key,
                relative_offset=at-record['data_offset'])
        groups[identity]['occurrences'].append(occurrence)
        count += 1

    kinds = Counter(span['full_kind_word'] for span in spans.values() if span['full_kind_word'] is not None)
    return dict(status='parsed', source_sha256=directory.summary['source_sha256'],
        symbols=[groups[identity] for identity in sorted(groups)],
        source_spans=list(spans.values()),
        summary=dict(queried_symbols=len(groups), matching_directory_rows=len(indices),
            listed_reference_words=count, source_index_spans=len(spans),
            words_not_contained_in_one_span=unplaced, full_kind_counts=dict(sorted(kinds.items()))),
        interpretation='same-resource, exact-hash and exact-flag listed uses; index-span association only, no provider definitions or recording/station roles')


def enrich(directory, targets, consume):
    """Add all same-resource uses of the selected profiles' external symbols."""
    profiles = audio_config_providers.enrich(directory, targets, consume)
    profiles['symbol_uses'] = _uses(directory, profiles['provider_symbols'], consume)
    return profiles
