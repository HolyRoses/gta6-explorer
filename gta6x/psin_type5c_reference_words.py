"""Conditional packed-reference grammar evidence for bounded pool positions.

Only existing supported-array storage or explicitly candidate type5c positions
are inspected. Parser compatibility never establishes type5c element meaning,
activates a record link or interprets bytes outside those independently framed
positions.
"""
from __future__ import annotations

from copy import deepcopy
import struct

from . import psin_field_context, psin_references, psin_schema, psin_type5c_pool_users
from .psin_blocks import parse_blocks

PROFILE = 'local_type5c_conditional_reference_word_evidence_v1'
MAX_WORDS = 4096


def inspect(data, schema, instances, *, consume, max_depth=16):
    """Classify raw words against source-local grammar without admitting links.

    Caller schema mutations cannot alter the private validated definitions.
    Target identities are regenerated from source declarations and block extents,
    never taken from saved instance values or links. Work/output failure returns
    no prefix. Existing pool-user coverage/refusal behavior is unchanged.
    """
    psin_field_context._validate_queries([], max_depth, 0)
    if not isinstance(data, bytes) or len(data) > 16*1024*1024:
        raise ValueError('reference-word evidence requires bounded source bytes')
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('reference-word evidence requires a local schema')
    used = 0
    def charge(amount=1):
        nonlocal used
        consume(amount)
        used += amount
    enum_defs = schema.enum_table.definitions if schema.enum_table else []
    charge(1 + len(schema.structures) + sum(len(s.fields) for s in schema.structures)
           + len(enum_defs) + sum(len(e.members) for e in enum_defs))
    local = deepcopy(schema)
    storage = psin_type5c_pool_users.inspect(data, local, instances,
                                            consume=charge, max_depth=max_depth)
    # The storage reader reparses/compares this snapshot before returning proof.
    blocks = parse_blocks(data[:struct.unpack_from('>I', data, 4)[0]])
    charge(2 + len(blocks) + len(local.structures))
    structures = psin_schema._index(local.structures)
    observations = []
    candidate_counts, supported_counts = {}, {}
    for pool in storage['pools']:
        charge()
        if pool.get('status') != 'observed':
            continue
        bi = pool['block_index']; block = blocks[bi]
        if (block.type_hash != 7 or structures.get(7) or block.byte_length % 8
                or pool['data_offset'] != block.data_offset
                or pool['byte_length'] != block.byte_length):
            raise ValueError('reference-word pool differs from source block identity')
        for word in pool['words']:
            candidate = word['candidate_header_indices']; supported = word['supported_user_indices']
            if not candidate and not supported:
                continue
            if len(observations) >= MAX_WORDS:
                raise ValueError('reference-word evidence exceeds word observation limit')
            charge(1 + len(candidate) + len(supported))
            wi = word['word_index']; start = block.data_offset + wi*8
            if (word['data_offset'] != start or word['byte_length'] != 8
                    or not 0 <= wi < block.byte_length//8 or start+8 > len(data)):
                raise ValueError('reference-word position differs from bounded pool storage')
            raw = struct.unpack_from('<Q', data, start)[0]
            result = psin_references.bind_record(raw, blocks, structures, data_size=len(data))
            item = dict(index=len(observations), pool_block_index=bi, word_index=wi,
                data_offset=start, byte_length=8, raw_bits=f'0x{raw:016x}',
                candidate_header_indices=list(candidate), ordinary_array_indices=list(supported),
                evidence_scope='conditional_type5c_candidate' if candidate else 'existing_supported_array_control',
                conditional_target=None, target_block=None, record_span_authorized=False,
                logical_element_meaning='unknown', semantic_owner='unknown', associations_admitted=0)
            if raw == 0:
                classification = 'null_word'
            else:
                number, offset = raw & 0xfffff, raw >> 20
                item.update(hypothetical_block_id=number, hypothetical_byte_offset=offset)
                if not 1 <= number <= len(blocks):
                    classification = 'invalid_block_id'
                else:
                    target = blocks[number-1]
                    item['target_block'] = dict(block_index=target.index,
                        structure_hash=f'0x{target.type_hash:08x}', data_offset=target.data_offset,
                        byte_length=target.byte_length, block_table_offset=target.table_offset)
                    definitions = structures.get(target.type_hash, [])
                    if offset >= target.byte_length:
                        classification = 'outside_block'
                    elif not definitions:
                        classification = 'bounded_untyped_offset'
                    elif len(definitions) != 1:
                        classification = 'ambiguous_local_schema'
                    elif definitions[0].byte_size <= 0:
                        classification = 'nonpositive_local_schema'
                    elif target.byte_length % definitions[0].byte_size:
                        classification = 'non_tiling_local_schema'
                    elif result['status'] == 'record_reference':
                        classification = 'conditional_typed_record_match'
                        item['conditional_target'] = {key: result[key] for key in
                            ('block_index', 'record_index', 'structure_hash', 'data_offset', 'byte_length')}
                    else:
                        classification = 'misaligned_or_partial_record'
            item['classification'] = classification
            item['grammar_status'] = result['status']
            if 'reason' in result:
                item['grammar_reason'] = result['reason']
            observations.append(item)
            for present, counts in ((candidate, candidate_counts), (supported, supported_counts)):
                if present:
                    counts[classification] = counts.get(classification, 0) + 1
    candidate_words = sum(candidate_counts.values())
    return dict(format='gta6x-psin-type5c-reference-word-evidence-v1', profile=PROFILE,
        source_sha256=storage['source_sha256'], schema_id=storage['schema_id'], max_depth=max_depth,
        status='partial' if candidate_words or storage['status'] == 'partial' else 'complete',
        profile_status='conditional_grammar_evidence_only', scan_complete=storage['scan_complete'],
        scan_reasons=list(storage['scan_reasons']), words=observations,
        candidate_sources=deepcopy(storage['type5c_hypotheses']),
        ordinary_sources=deepcopy(storage['ordinary_arrays']),
        summary=dict(nodes=used, observed_words=len(observations), candidate_words=candidate_words,
            supported_control_words=sum(supported_counts.values()),
            candidate_classifications=candidate_counts, supported_classifications=supported_counts,
            uninspected_unexplained_words=storage['summary']['unexplained_words'],
            associations_admitted=0, record_links=0, semantic_types_promoted=0),
        interpretation='Existing packed-reference grammar applied conditionally to already bounded storage positions only. Matches do not establish type5c reference/element/count/empty semantics, application ownership or new record/graph links. Ordinary supported-array controls retain their separate pre-existing authority.')
