"""Bounded selected-field context for source-checked PSIN pool evidence.

Queries navigate physical field paths. Candidate storage, ordinary array storage
and conditional word grammar retain their separate authority and never create
record/graph associations or assign logical element or ownership meanings.
"""
from __future__ import annotations

from copy import deepcopy

from . import psin_field_context, psin_schema, psin_type5c_headers, psin_type5c_scalars

PROFILE = 'local_psin_selected_pool_evidence_v1'
MAX_SNAPSHOT_ITEMS = 2_000_000
MAX_SNAPSHOT_DEPTH = 256
MAX_REPORT_ITEMS = 131072


def inspect(data, schema, instances, queries, *, consume, max_depth=16):
    """Resolve at most32 exact source paths; unsupported evidence stays explicit.

    All child evidence is freshly regenerated in this invocation. Repeated
    queries share evidence tables, not saved report inputs. Source disagreement,
    callback mutation of private source facts, or work/report exhaustion raises
    without returning a prefix. Resolver status describes navigation only.
    """
    psin_field_context._validate_queries(queries, max_depth, 0)
    if not isinstance(data, bytes) or len(data) > 16*1024*1024:
        raise ValueError('PSIN pool context requires bounded source bytes')
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('PSIN pool context requires a local native schema')
    queries = [(bi, ri, list(path)) for bi, ri, path in queries]
    used = 0
    def charge(amount=1):
        nonlocal used
        consume(amount); used += amount
    enums = schema.enum_table.definitions if schema.enum_table else []
    charge(1+len(schema.structures)+sum(len(s.fields) for s in schema.structures)
           +len(enums)+sum(len(e.members) for e in enums))
    local = deepcopy(schema)
    # Snapshot report metadata before source callbacks can mutate caller state.
    # Count containers and bounded scans; immutable scalar objects need no copy.
    copied = 0
    active, memo = set(), {}
    def clone(value, depth=0):
        nonlocal copied
        copied += 1
        if copied > MAX_SNAPSHOT_ITEMS or depth > MAX_SNAPSHOT_DEPTH:
            raise ValueError('PSIN pool context exceeds snapshot bounds')
        if type(value) in (str, int, float, bool, type(None)):
            if isinstance(value, str) and len(value) > 16*1024*1024:
                raise ValueError('PSIN pool context snapshot string exceeds bounds')
            return value
        if type(value) not in (dict, list, tuple):
            raise ValueError('PSIN pool context requires native JSON-compatible instances')
        identity = id(value)
        if identity in active:
            raise ValueError('PSIN pool context instance metadata contains a cycle')
        if identity in memo:
            return memo[identity]
        if len(value) > MAX_SNAPSHOT_ITEMS-copied:
            raise ValueError('PSIN pool context exceeds snapshot bounds')
        charge(1+(len(value)+63)//64)
        if len(value) > MAX_SNAPSHOT_ITEMS-copied:
            raise ValueError('PSIN pool context exceeds snapshot bounds')
        active.add(identity)
        if isinstance(value, dict):
            entries = tuple(value.items())
            if any(type(k) is not str for k, _ in entries):
                raise ValueError('PSIN pool context instance metadata keys must be strings')
            result = {key: clone(child, depth+1) for key, child in entries}
        else:
            result = [clone(child, depth+1) for child in tuple(value)]
            if isinstance(value, tuple):
                result = tuple(result)
        active.remove(identity); memo[identity] = result
        return result
    private = clone(instances)
    contexts = psin_field_context.inspect(data, local, private, queries,
        consume=charge, max_depth=max_depth, max_sample_bytes=0)
    digest, schema_id = contexts['source_sha256'], contexts['schema_id']
    headers = None
    scalar = hash_users = reference = None
    tables = dict(headers=[], scalar_candidates=[], hash_pool_users=None, reference_words=None)
    chosen_headers, chosen_scalars = {}, {}
    hash_blocks, reference_blocks = set(), set()
    report_items = 0
    def copy_report(value):
        nonlocal report_items
        if isinstance(value, dict):
            report_items += 1
            if report_items > MAX_REPORT_ITEMS:
                raise ValueError('PSIN pool context exceeds evidence report limit')
            charge()
            return {k: copy_report(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            report_items += 1
            if report_items > MAX_REPORT_ITEMS:
                raise ValueError('PSIN pool context exceeds evidence report limit')
            charge()
            return [copy_report(v) for v in value]
        return value
    def checked(view):
        if (view.get('source_sha256') != digest or view.get('schema_id') != schema_id
                or view.get('status') not in ('complete', 'partial')):
            raise ValueError('PSIN pool context child evidence differs from checked source')
        return view
    def identity(row, query, start):
        return (row.get('block_index') == query['block_index']
            and row.get('record_index') == query['record_index']
            and row.get('field_path') == query['field_path']
            and row.get('header_data_offset') == start)
    def unique(rows, query, start):
        matches = [row for row in rows if identity(row, query, start)]
        charge(1+len(rows))
        if len(matches) > 1:
            raise ValueError('PSIN pool context has ambiguous exact source evidence')
        return matches[0] if matches else None
    def header_for(query, start):
        nonlocal headers
        if headers is None:
            headers = checked(psin_type5c_headers.inspect(data, local, private,
                consume=charge, max_depth=max_depth))
        return unique(headers['fields'], query, start)
    output = []
    for source in contexts['queries']:
        charge()
        query = dict(block_index=source['block_index'], record_index=source['record_index'],
            field_path=list(source['field_path']), status='unresolved', source_context=source,
            logical_element_meaning='unknown', semantic_owner='unknown', associations_admitted=0)
        output.append(query)
        if source['status'] != 'resolved':
            query['reason'] = source['reason']; continue
        field = source['field']; start = field['source_slot']['data_offset']
        raw_type = int(field['type_word'], 16) & 0xffff
        if raw_type not in (0x5c, 0x52):
            query['reason'] = 'selected field is outside supported pool header/ordinary-array scope'; continue
        descriptor = None
        if raw_type == 0x5c:
            header = header_for(query, start)
            if header is None:
                query['reason'] = 'selected type5c header is outside the checked instance-path inventory'; continue
            key = header['index']
            if key not in chosen_headers:
                chosen_headers[key] = len(tables['headers'])
                tables['headers'].append(copy_report(header))
            query['header_evidence_index'] = chosen_headers[key]
            descriptor = header.get('descriptor')
            if header['status'] != 'bounded_observation' or descriptor is None:
                query['reason'] = header.get('reason', 'no complete local descriptor/header observation'); continue
        else:
            # Resolve the exact owner's descriptor without trusting saved arrays.
            owner_hash = int(field['owner_hash'], 16)
            owners = [owner for owner in local.structures if owner.name_hash == owner_hash]
            charge(1+len(local.structures))
            if len(owners) != 1:
                query['reason'] = 'ordinary-array owner has no unique local declaration'; continue
            di = int(field['type_word'], 16) >> 16
            if di >= len(owners[0].fields) or di == query['field_path'][-1]:
                query['reason'] = 'ordinary-array descriptor is unavailable or self-referential'; continue
            descriptor = dict(type_word=f'0x{owners[0].fields[di].type_word:08x}')
        kind = descriptor['type_word']
        if kind == '0x0000004a':
            from . import psin_hash_pool_users
            if raw_type == 0x5c and scalar is None:
                scalar = checked(psin_type5c_scalars.inspect(data, local, private, consume=charge, max_depth=max_depth))
            if hash_users is None:
                hash_users = checked(psin_hash_pool_users.inspect(data, local, private, consume=charge, max_depth=max_depth))
            candidate = unique(scalar['fields'], query, start) if raw_type == 0x5c else None
            if candidate is not None:
                key = candidate['index']
                if key not in chosen_scalars:
                    chosen_scalars[key] = len(tables['scalar_candidates'])
                    tables['scalar_candidates'].append(copy_report(candidate))
                query['scalar_candidate_index'] = chosen_scalars[key]
            rows = hash_users['type5c_hypotheses'] if raw_type == 0x5c else hash_users['ordinary_arrays']
            observed = unique(rows, query, start)
            expected = 'candidate_storage' if raw_type == 0x5c else 'supported_storage'
            if observed is None or observed['status'] != expected or observed.get('storage_span') is None:
                query['reason'] = (observed or {}).get('reason',
                    'existing supported ordinary array has no allocated pool span' if observed and raw_type == 0x52
                    and observed['status'] == 'supported_storage' and observed.get('storage_span') is None else
                    'selected field has no supported or bounded candidate pool span'); continue
            span = observed['storage_span']; hash_blocks.add(span['block_index'])
            query.update(status='resolved', pool_block_index=span['block_index'], storage_span=copy_report(span),
                evidence_authority='candidate_type5c_storage' if raw_type == 0x5c else 'existing_supported_ordinary_array',
                evidence_source_index=observed['index'], evidence_table='hash_pool_users')
        elif kind == '0x00000007':
            from . import psin_type5c_reference_words
            if reference is None:
                reference = checked(psin_type5c_reference_words.inspect(data, local, private,
                    consume=charge, max_depth=max_depth))
            rows = reference['candidate_sources'] if raw_type == 0x5c else reference['ordinary_sources']
            observed = unique(rows, query, start)
            expected = 'candidate_storage' if raw_type == 0x5c else 'supported_storage'
            if observed is None or observed['status'] != expected or observed.get('storage_span') is None:
                query['reason'] = (observed or {}).get('reason',
                    'existing supported ordinary array has no allocated pool span' if observed and raw_type == 0x52
                    and observed['status'] == 'supported_storage' and observed.get('storage_span') is None else
                    'selected field has no supported or bounded candidate pool span'); continue
            span = observed['storage_span']; reference_blocks.add(span['block_index'])
            query.update(status='resolved', pool_block_index=span['block_index'], storage_span=copy_report(span),
                evidence_authority='candidate_type5c_storage_and_conditional_word_grammar' if raw_type == 0x5c else 'existing_supported_ordinary_array',
                evidence_source_index=observed['index'], evidence_table='reference_words')
        else:
            query['reason'] = 'descriptor has no independently supported pool element authority in this view'; continue
        query['resolution_scope'] = 'source path and bounded storage evidence only; not a decoded type5c value or new association'
    if hash_blocks:
        pools = [p for p in hash_users['pools'] if p['block_index'] in hash_blocks]
        ordinary_ids = {i for p in pools for i in p.get('supported_array_indices', [])}
        candidate_ids = {i for p in pools for i in p.get('candidate_type5c_indices', [])}
        tables['hash_pool_users'] = copy_report(dict(profile=hash_users['profile'], scan_complete=hash_users['scan_complete'],
            scan_reasons=hash_users['scan_reasons'], pools=pools,
            ordinary_arrays=[a for a in hash_users['ordinary_arrays'] if a['index'] in ordinary_ids],
            type5c_hypotheses=[a for a in hash_users['type5c_hypotheses'] if a['index'] in candidate_ids]))
    if reference_blocks:
        words = [w for w in reference['words'] if w['pool_block_index'] in reference_blocks]
        ordinary_ids = {i for w in words for i in w['ordinary_array_indices']}
        candidate_ids = {i for w in words for i in w['candidate_header_indices']}
        tables['reference_words'] = copy_report(dict(profile=reference['profile'], scan_complete=reference['scan_complete'],
            scan_reasons=reference['scan_reasons'], words=words,
            ordinary_sources=[a for a in reference['ordinary_sources'] if a['index'] in ordinary_ids],
            candidate_sources=[a for a in reference['candidate_sources'] if a['index'] in candidate_ids]))
    resolved = sum(q['status'] == 'resolved' for q in output)
    return dict(format='gta6x-psin-pool-context-v1', profile=PROFILE, source_sha256=digest,
        schema_id=schema_id, max_depth=max_depth, status='complete' if resolved == len(output) else 'partial',
        queries=output, evidence=tables,
        summary=dict(nodes=used, requested=len(output), resolved=resolved, unresolved=len(output)-resolved,
            header_observations=len(tables['headers']), scalar_candidate_observations=len(tables['scalar_candidates']),
            hash_pools=len(hash_blocks), reference_pools=len(reference_blocks),
            associations_admitted=0, semantic_types_promoted=0),
        interpretation='Selected source paths and independently bounded storage evidence only. Candidate spans and conditional grammar stay distinct from supported ordinary arrays; no new record links, type5c elements, count/empty meanings, names, ownership or graph associations are admitted.')
