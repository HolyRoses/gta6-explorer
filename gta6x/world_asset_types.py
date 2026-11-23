"""Source-owned opaque PSIN slot and dictionary-preimage diagnostics.

The observed 0x054f profile is not a universal hash or asset-reference type.
Eight-byte declared-start slots may contain padding. A complete hash preimage
is only a candidate name; no asset namespace, object or binding is established.
"""
from __future__ import annotations

from collections import Counter
import struct

from . import names, psin_field_context, psin_schema
from .psin_blocks import parse_blocks

PROFILE = 'local_psin_opaque_054f_hash_candidates_v1'


def inspect(data, schema, instances, dictionary, *, consume, max_depth=16):
    """Enumerate all local embedded-only 0x054f slots under a shared budget.

    Source declarations and each selected instance are rechecked by the field
    context reader. Every matching declaration path and record is considered;
    no query-count prefix is returned on budget exhaustion. Unknown layouts
    and unmatched words remain explicit. No input object is modified.
    """
    if not isinstance(dictionary, dict) or not isinstance(dictionary.get('hashes64', {}), dict):
        raise ValueError('typed hash candidates require a dictionary with hash64 buckets')
    if type(max_depth) is not int or not 1 <= max_depth <= 64:
        raise ValueError('typed hash candidate depth must be 1..64')
    used = 0

    def charge(n=1):
        nonlocal used
        consume(n)
        used += n

    query_source = psin_field_context._prepare(data, schema, instances, consume=charge,
                                              max_depth=max_depth, max_sample_bytes=8)
    checked = query_source([])
    blocks = parse_blocks(data[:struct.unpack_from('>I', data, 4)[0]])
    charge(len(blocks))
    structures = psin_schema._index(schema.structures)
    enums = psin_schema._index(schema.enum_table.definitions)
    issues = Counter()

    def paths(owner, path=(), active=frozenset()):
        charge()
        if owner.name_hash in active:
            issues['cyclic_embedded_declarations'] += 1
            return []
        if len(path) >= max_depth:
            issues['depth_limited_embedded_declarations'] += 1
            return []
        active = active | {owner.name_hash}
        result = []
        for fi, field in enumerate(owner.fields):
            charge()
            if field.name_hash == 0x100:
                continue
            selected = path + (fi,)
            if field.type_word == 0x054f:
                charge(len(selected)); result.append(selected)
            if psin_schema._type_info(field, owner, structures, enums)['name'] == 'embedded_structure':
                children = structures.get(field.auxiliary, [])
                if len(children) == 1:
                    result.extend(paths(children[0], selected, active))
                else:
                    issues['ambiguous_embedded_declarations'] += 1
        return result

    cache = {}
    rejected = 0

    def preimages(word):
        nonlocal rejected
        if word not in cache:
            charge()
            entries = dictionary.get('hashes64', {}).get(f'{word:016x}', [])
            if not isinstance(entries, list):
                raise ValueError('invalid typed hash candidate bucket')
            result = []
            for entry in entries:
                charge()
                if (not isinstance(entry, (tuple, list)) or len(entry) != 2
                        or any(not isinstance(v, str) or '\0' in v or len(v) > 4096 for v in entry)):
                    raise ValueError('invalid typed hash candidate entry')
                name, source = entry
                try:
                    encoded = name.encode('utf-8')
                except UnicodeError as exc:
                    raise ValueError('typed hash candidate is not valid UTF-8') from exc
                charge(1 + (len(encoded) + len(source) + 63) // 64)
                if names.hash64(name) != word:
                    rejected += 1
                    continue
                result.append(dict(name=name, source=source,
                                   hash_method='murmur3_x64_128_low64_exact_utf8_seed0',
                                   status='hash_preimage_candidate_only'))
            cache[word] = result
        charge(len(cache[word]))
        return [dict(row) for row in cache[word]]

    output = []
    pending = []

    def flush():
        if not pending:
            return
        contexts = query_source(pending)
        for context in contexts['queries']:
            charge()
            row = dict(context=context, status='unsupported', value_meaning='unknown',
                       asset_binding='not_established', name_candidates=[])
            output.append(row)
            if context['status'] != 'resolved':
                row['reason'] = context['reason']; continue
            field = context['field']; slot = field['source_slot']
            if (field['type_word'] != '0x0000054f' or field['auxiliary'] != '0x00000000'
                    or field['type_confidence'] != 'unknown'):
                row['reason'] = 'field is outside the observed opaque type/auxiliary profile'; continue
            if slot['byte_length'] != 8 or slot['preceding_unknown_extent_count']:
                row['reason'] = 'profile requires an eight-byte declared-start slot without preceding unknown extents'; continue
            word = int.from_bytes(bytes.fromhex(context['opaque_prefix']['hex']), 'little')
            candidates = preimages(word)
            row.update(status='candidate_preimages' if candidates else 'unmatched',
                       word_bits=f'0x{word:016x}', name_candidates=candidates,
                       reason='verified full-word dictionary preimages only' if candidates else
                              'no verified full-word dictionary preimage')
        pending.clear()

    templates = {}
    for block in blocks:
        charge()
        declarations = structures.get(block.type_hash, [])
        if len(declarations) != 1 or not declarations[0].byte_size:
            issues['blocks_without_unique_local_owner'] += 1; continue
        owner = declarations[0]
        if block.byte_length % owner.byte_size:
            issues['blocks_without_exact_local_stride'] += 1; continue
        if id(owner) not in templates:
            templates[id(owner)] = paths(owner)
        for ri in range(block.byte_length // owner.byte_size):
            charge()
            for path in templates[id(owner)]:
                charge(1 + len(path)); pending.append((block.index, ri, path))
                if len(pending) == 32:
                    flush()
    flush()
    counts = Counter(row['status'] for row in output)
    return dict(format='gta6x-world-asset-type-candidates-v1', profile=PROFILE,
        status='partial' if issues or counts['unsupported'] else 'complete',
        source_sha256=checked['source_sha256'], schema_id=schema.schema_id,
        max_depth=max_depth, slots=output, unsupported=dict(issues),
        summary=dict(nodes=used, selected_slots=len(output),
                     matched_slots=counts['candidate_preimages'], unmatched_slots=counts['unmatched'],
                     unsupported_slots=counts['unsupported'], rejected_dictionary_entries=rejected,
                     asset_bindings=0),
        interpretation='Source-owned opaque declared-start slots and verified dictionary preimage candidates only; type meaning, value width, asset namespace and bindings remain unknown.')
