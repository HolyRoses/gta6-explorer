"""Group exact opaque PSIN slot words across fresh native observations.

Equality links observations, not assets. Unknown type meanings, slot value
widths and asset namespaces remain unknown. This consumes fresh native views;
it does not authenticate a serialized report or establish resource ownership.
"""
from __future__ import annotations

from . import names, world_asset_types

PROFILE = 'local_psin_opaque_054f_word_uses_v1'


def _queries(words):
    if (not isinstance(words, (list, tuple)) or len(words) > 32
            or any(type(word) is not int or not 0 <= word <= 0xffffffffffffffff for word in words)):
        raise ValueError('PSIN hash-use queries require at most 32 unsigned 64-bit words')


def _hex(value, digits, label):
    if (not isinstance(value, str) or len(value) != digits
            or any(ch not in '0123456789abcdef' for ch in value)):
        raise ValueError('invalid PSIN hash-use ' + label)
    return value


def _unsigned(value, label, maximum=0xffffffff):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('invalid PSIN hash-use ' + label)
    return value


def inspect(resources, *, consume, words=()):
    """Index fresh native resource views, retaining aliases and missing coverage.

    ``resources`` must come directly from native source inspection in this call,
    including its source/schema identities and ``typed_hash_candidates`` views.
    Cross-checks guard accidental view mixing; they do not authenticate JSON.
    Output is linear in observations, not a quadratic set of candidate edges.
    A callback failure propagates unchanged, with no returned partial index.
    """
    _queries(words)
    if not isinstance(resources, (list, tuple)):
        raise ValueError('PSIN hash uses require a native resource list')
    used = 0
    def charge(amount=1):
        nonlocal used
        consume(amount)
        used += amount
    charge()
    selected = set(words)
    sources = []
    groups = {}
    physical = {}
    locations = {}
    contents = {}
    observed = unsupported = refused = partial = unindexed = 0
    matched_observed = unmatched_observed = 0
    for resource in resources:
        charge()
        if not isinstance(resource, dict):
            raise ValueError('invalid PSIN hash-use source')
        file = resource.get('file')
        if not isinstance(file, str) or not file or len(file) > 4096 or '\0' in file:
            raise ValueError('invalid PSIN hash-use source label')
        charge(1 + (len(file) + 63)//64)
        offset = _unsigned(resource.get('offset', 0), 'source offset', 0xffffffffffffffff)
        source = dict(index=len(sources), file=file, offset=offset, status='unavailable')
        sources.append(source)
        location = file, offset
        if resource.get('status') != 'ok':
            source['reason'] = 'native source parsing was refused'
            refused += 1
            continue
        digest = _hex(resource.get('sha256'), 64, 'source digest')
        schema = _hex(resource.get('schema_id'), 64, 'schema identity')
        source.update(sha256=digest, schema_id=schema)
        identity = file, offset, digest
        if identity in physical:
            source['physical_alias_of'] = physical[identity]
        else:
            physical[identity] = source['index']
            if location in locations:
                source['physical_conflict_with'] = locations[location]
            else:
                locations[location] = source['index']
        if digest in contents:
            source['content_alias_of'] = contents[digest]
            if sources[contents[digest]]['schema_id'] != schema:
                raise ValueError('PSIN hash-use content alias has conflicting schema identity')
        else:
            contents[digest] = source['index']
        view = resource.get('typed_hash_candidates')
        if not isinstance(view, dict) or view.get('status') == 'refused':
            source['reason'] = 'typed-slot observations are unavailable or refused'
            refused += 1
            continue
        if (view.get('format') != 'gta6x-world-asset-type-candidates-v1'
                or view.get('profile') != world_asset_types.PROFILE
                or view.get('source_sha256') != digest or view.get('schema_id') != schema
                or view.get('status') not in ('complete', 'partial')
                or not isinstance(view.get('slots'), list)):
            raise ValueError('PSIN hash-use typed view differs from its source identity')
        source['status'] = view['status']
        if view['status'] == 'partial':
            source['reason'] = 'native typed-slot inventory is partial'
            partial += 1
        seen_slots = set()
        counts = dict(selected_slots=0, matched_slots=0, unmatched_slots=0, unsupported_slots=0)
        for row in view['slots']:
            charge()
            if not isinstance(row, dict) or row.get('status') not in ('candidate_preimages', 'unmatched', 'unsupported'):
                raise ValueError('invalid PSIN hash-use slot status')
            counts['selected_slots'] += 1
            if row['status'] == 'unsupported':
                unsupported += 1; counts['unsupported_slots'] += 1
                continue
            context = row.get('context')
            if not isinstance(context, dict) or context.get('status') != 'resolved':
                raise ValueError('PSIN hash-use slot requires resolved source context')
            block = _unsigned(context.get('block_index'), 'block index')
            record = _unsigned(context.get('record_index'), 'record index')
            path = context.get('field_path')
            if not isinstance(path, list) or not 1 <= len(path) <= 64:
                raise ValueError('invalid PSIN hash-use field path')
            charge(len(path))
            for index in path:
                _unsigned(index, 'field index')
            key = block, record, tuple(path)
            if key in seen_slots:
                raise ValueError('duplicate PSIN hash-use source slot')
            seen_slots.add(key)
            field = context.get('field')
            if not isinstance(field, dict):
                raise ValueError('invalid PSIN hash-use field context')
            slot = field.get('source_slot')
            prefix = context.get('opaque_prefix')
            if (field.get('type_word') != '0x0000054f' or field.get('auxiliary') != '0x00000000'
                    or field.get('type_confidence') != 'unknown'
                    or not isinstance(slot, dict) or slot.get('byte_length') != 8
                    or slot.get('preceding_unknown_extent_count') != 0
                    or slot.get('is_value_width') is not False
                    or slot.get('exclusive_ownership_established') is not False
                    or not isinstance(prefix, dict) or prefix.get('byte_length') != 8
                    or prefix.get('truncated') is not False):
                raise ValueError('PSIN hash-use slot is outside the observed opaque profile')
            at = _unsigned(slot.get('data_offset'), 'slot offset', 0xffffffffffffffff)
            if prefix.get('data_offset') != at:
                raise ValueError('PSIN hash-use prefix differs from its slot')
            raw = bytes.fromhex(_hex(prefix.get('hex'), 16, 'opaque eight-byte word'))
            bits = '0x' + raw[::-1].hex()
            if row.get('word_bits') != bits:
                raise ValueError('PSIN hash-use word differs from its source prefix')
            owner_hash = field.get('owner_hash')
            field_hash = field.get('hash')
            for value in (owner_hash, field_hash):
                if not isinstance(value, str) or not value.startswith('0x'):
                    raise ValueError('invalid PSIN hash-use declaration hash')
                _hex(value[2:], 8, 'declaration hash')
            candidates = row.get('name_candidates')
            if not isinstance(candidates, list):
                raise ValueError('invalid PSIN hash-use name candidates')
            checked = []
            for candidate in candidates:
                charge()
                if not isinstance(candidate, dict):
                    raise ValueError('invalid PSIN hash-use candidate')
                name, provenance = candidate.get('name'), candidate.get('source')
                if any(not isinstance(v, str) or '\0' in v or len(v) > 4096 for v in (name, provenance)):
                    raise ValueError('invalid PSIN hash-use candidate text')
                try:
                    encoded = name.encode('utf-8')
                except UnicodeError as exc:
                    raise ValueError('invalid PSIN hash-use candidate encoding') from exc
                charge(1 + (len(encoded) + len(provenance) + 63)//64)
                if names.hash64(name) != int(bits, 16):
                    raise ValueError('PSIN hash-use candidate is not a full-word preimage')
                checked.append(dict(name=name, source=provenance, status='hash_preimage_candidate_only'))
            if bool(checked) != (row['status'] == 'candidate_preimages'):
                raise ValueError('PSIN hash-use candidate status differs')
            observed += 1
            counts['matched_slots' if checked else 'unmatched_slots'] += 1
            matched_observed += bool(checked)
            unmatched_observed += not checked
            word = int(bits, 16)
            if selected and word not in selected:
                unindexed += 1
                continue
            charge(1 + len(checked))
            group = groups.setdefault(word, [])
            group.append(dict(source_index=source['index'], block_index=block, record_index=record,
                field_path=list(path), data_offset=at, owner_hash=owner_hash, field_hash=field_hash,
                slot_byte_length=8, name_candidates=checked,
                value_meaning='unknown', asset_binding='not_established'))
        summary = view.get('summary')
        if not isinstance(summary, dict) or any(summary.get(k) != v for k, v in counts.items()):
            raise ValueError('PSIN hash-use slot counts differ from native inventory')
        if counts['unsupported_slots'] and source['status'] == 'complete':
            raise ValueError('PSIN hash-use complete inventory contains unsupported slots')
    output = []
    group_indices = {}
    for word, occurrences in sorted(groups.items()):
        charge(1 + len(occurrences))
        indices = {row['source_index'] for row in occurrences}
        locations = {(sources[i]['file'], sources[i]['offset']) for i in indices}
        distinct_contents = {sources[i]['sha256'] for i in indices}
        group_indices[word] = len(output)
        output.append(dict(word_bits=f'0x{word:016x}', occurrences=occurrences,
            summary=dict(occurrences=len(occurrences), source_observations=len(indices),
                distinct_source_locations=len(locations), distinct_contents=len(distinct_contents)),
            relationship='exact_eight_byte_slot_equality_only', asset_namespace='unknown'))
    coverage_complete = not (refused or partial or unsupported
                             or any('physical_conflict_with' in s for s in sources))
    queries = []
    for word in words:
        charge()
        query = dict(word_bits=f'0x{word:016x}',
                     status='observed' if word in group_indices else 'not_observed',
                     coverage_complete=coverage_complete)
        if word in group_indices:
            query['group_index'] = group_indices[word]
        queries.append(query)
    return dict(format='gta6x-psin-hash-uses-v1', profile=PROFILE,
        status='complete' if coverage_complete else 'partial',
        sources=sources, groups=output, queries=queries,
        summary=dict(nodes=used, sources=len(sources), sources_refused=refused,
            sources_partial=partial, observed_slots=observed, unsupported_slots=unsupported,
            matched_slots=matched_observed, unmatched_slots=unmatched_observed,
            unselected_slots=unindexed, groups=len(output),
            occurrences=sum(len(g['occurrences']) for g in output),
            cross_content_groups=sum(g['summary']['distinct_contents'] > 1 for g in output),
            content_alias_sources=sum('content_alias_of' in s for s in sources),
            physical_alias_sources=sum('physical_alias_of' in s for s in sources),
            physical_identity_conflicts=sum('physical_conflict_with' in s for s in sources),
            asset_bindings=0),
        interpretation='Fresh native observations only; exact opaque-slot equality does not establish a hash type, asset namespace, ownership or binding. Missing queries are not observed in the supplied scope, not absent from the game.')
