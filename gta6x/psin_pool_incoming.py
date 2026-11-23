"""Source-checked reverse lookup of conditional PSIN pool-word evidence.

Target rows are declared locally; incoming occurrences keep candidate type5c
and already supported ordinary-array authority separate. No new links result.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import struct

from . import psin_arrays, psin_field_context, psin_references, psin_schema, psin_type5c_reference_words
from .psin_blocks import parse_blocks

PROFILE = 'local_psin_conditional_pool_incoming_v1'
MAX_WORDS = 4096
MAX_OCCURRENCES = 65536
MAX_SNAPSHOT_ITEMS = 2_000_000
MAX_SNAPSHOT_DEPTH = 256
MAX_REPORT_ITEMS = 131072


def _require(condition, reason):
    if not condition:
        raise ValueError('PSIN pool incoming ' + reason)


def inspect(data, schema, instances, queries, *, consume, max_depth=16):
    """Resolve selected typed rows to bounded, separately labelled evidence.

    Source schema/instances are private snapshots. Evidence is regenerated, raw
    words rebound and source paths replayed; saved report values cannot provide
    target or source authority. Exhaustion raises without a prefix report.
    """
    psin_field_context._validate_queries([], max_depth, 0)
    if (not isinstance(queries, (list, tuple)) or len(queries) > 32 or
            any(not isinstance(q, (list, tuple)) or len(q) != 2 or
                any(type(v) is not int or not 0 <= v <= 0xffffffff for v in q) for q in queries)):
        raise ValueError('pool incoming requires at most 32 unsigned block/record pairs')
    _require(isinstance(data, bytes) and len(data) <= 16*1024*1024, 'requires bounded source bytes')
    _require(isinstance(schema, psin_schema.Schema), 'requires a local native schema')
    queries = [tuple(q) for q in queries]
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    enums = schema.enum_table.definitions if schema.enum_table else []
    charge(1+len(schema.structures)+sum(len(s.fields) for s in schema.structures)
           +len(enums)+sum(len(e.members) for e in enums))
    local = deepcopy(schema)
    copied, active, memo = 0, set(), {}
    def snapshot(value, depth=0):
        nonlocal copied
        copied += 1
        _require(copied <= MAX_SNAPSHOT_ITEMS and depth <= MAX_SNAPSHOT_DEPTH, 'exceeds snapshot bounds')
        if type(value) in (str, int, float, bool, type(None)):
            _require(not isinstance(value, str) or len(value) <= 16*1024*1024, 'exceeds snapshot string bound')
            return value
        _require(type(value) in (dict, list, tuple), 'requires native JSON-compatible instances')
        identity = id(value)
        _require(identity not in active, 'instance metadata contains a cycle')
        if identity in memo:
            return memo[identity]
        _require(len(value) <= MAX_SNAPSHOT_ITEMS-copied, 'exceeds snapshot bounds')
        charge(1+(len(value)+63)//64)
        _require(len(value) <= MAX_SNAPSHOT_ITEMS-copied, 'exceeds snapshot bounds')
        active.add(identity)
        if isinstance(value, dict):
            entries = tuple(value.items())
            _require(all(type(k) is str for k, _ in entries), 'instance keys must be strings')
            result = {k: snapshot(v, depth+1) for k, v in entries}
        else:
            result = [snapshot(v, depth+1) for v in tuple(value)]
            if isinstance(value, tuple):
                result = tuple(result)
        active.remove(identity); memo[identity] = result
        return result
    private = snapshot(instances)
    report = psin_type5c_reference_words.inspect(data, local, private, consume=charge, max_depth=max_depth)
    charge(1+(len(data)+4095)//4096)
    digest = hashlib.sha256(data).hexdigest()
    _require(isinstance(report, dict) and report.get('format') == 'gta6x-psin-type5c-reference-word-evidence-v1'
        and report.get('profile') == psin_type5c_reference_words.PROFILE
        and report.get('source_sha256') == digest and report.get('schema_id') == local.schema_id
        and report.get('status') in ('complete', 'partial'), 'child evidence differs from checked source')
    blocks = parse_blocks(data[:struct.unpack_from('>I', data, 4)[0]])
    structures = psin_schema._index(local.structures)
    charge(1+len(blocks)+len(local.structures))
    source_lists = {key: report.get(key) for key in ('candidate_sources', 'ordinary_sources')}
    words = report.get('words')
    _require(isinstance(words, list) and len(words) <= MAX_WORDS and all(
        isinstance(rows, list) and len(rows) <= 4096 for rows in source_lists.values()), 'has invalid evidence tables')
    by_target, physical = {}, set()
    for wi, word in enumerate(words):
        charge()
        _require(isinstance(word, dict) and type(word.get('index')) is int and word['index'] == wi,
                 'has invalid word index')
        bi, index = word.get('pool_block_index'), word.get('word_index')
        _require(type(bi) is int and 0 <= bi < len(blocks) and type(index) is int and index >= 0,
                 'has invalid pool position')
        pool = blocks[bi]; start = pool.data_offset+index*8
        _require(pool.type_hash == 7 and not structures.get(7) and pool.byte_length % 8 == 0
            and index < pool.byte_length//8 and (bi, index) not in physical
            and word.get('data_offset') == start and word.get('byte_length') == 8,
            'word position differs from intrinsic pool')
        physical.add((bi, index))
        raw = struct.unpack_from('<Q', data, start)[0]
        _require(word.get('raw_bits') == f'0x{raw:016x}', 'word bits differ from source')
        rebound = psin_references.bind_record(raw, blocks, structures, data_size=len(data))
        target = None
        if rebound['status'] == 'record_reference':
            target_block = blocks[rebound['block_index']]
            defs = structures.get(target_block.type_hash, [])
            if len(defs) == 1 and defs[0].byte_size > 0 and target_block.byte_length % defs[0].byte_size == 0:
                target = {k: rebound[k] for k in ('block_index', 'record_index', 'structure_hash', 'data_offset', 'byte_length')}
        _require(word.get('conditional_target') == target and (target is None or all(
            type(word['conditional_target'].get(k)) is type(v) for k, v in target.items())),
            'conditional target differs from source grammar')
        _require(word.get('record_span_authorized') is False and type(word.get('associations_admitted')) is int
            and word['associations_admitted'] == 0 and word.get('logical_element_meaning') == 'unknown'
            and word.get('semantic_owner') == 'unknown', 'word evidence changes conditional authority')
        memberships = []
        for key, member_key, status in (('candidate_sources', 'candidate_header_indices', 'candidate_storage'),
                                        ('ordinary_sources', 'ordinary_array_indices', 'supported_storage')):
            indices = word.get(member_key)
            _require(isinstance(indices, list) and len(indices) <= 4096
                and all(type(i) is int for i in indices) and len(set(indices)) == len(indices),
                     'has invalid source memberships')
            for si in indices:
                charge()
                _require(type(si) is int and 0 <= si < len(source_lists[key]), 'selects no source witness')
                source = source_lists[key][si]
                _require(isinstance(source, dict) and type(source.get('index')) is int and source['index'] == si and source.get('status') == status,
                         'source witness identity/status differs')
                span = source.get('storage_span')
                _require(isinstance(span, dict) and type(span.get('block_index')) is int and span['block_index'] == bi
                    and type(span.get('byte_offset')) is int and span['byte_offset'] >= 0
                    and type(span.get('byte_length')) is int and span['byte_length'] >= 0
                    and span['byte_offset'] % 8 == span['byte_length'] % 8 == 0
                    and span.get('data_offset') == pool.data_offset+span['byte_offset']
                    and span['byte_offset']+span['byte_length'] <= pool.byte_length
                    and span['data_offset'] <= start < start+8 <= span['data_offset']+span['byte_length'],
                    'word lies outside its source storage witness')
                memberships.append((key, si))
        if target is not None:
            by_target.setdefault((target['block_index'], target['record_index']), []).append((wi, memberships))
    tables = dict(words=[], candidate_sources=[], ordinary_sources=[], occurrences=[])
    selected_words, selected_sources, selected_occurrences = {}, {}, {}
    copied_report = 0
    def emit_copy(value):
        nonlocal copied_report
        copied_report += 1
        _require(copied_report <= MAX_REPORT_ITEMS, 'exceeds report item bound')
        if isinstance(value, dict):
            charge(1+(len(value)+63)//64)
            return {k: emit_copy(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            charge(1+(len(value)+63)//64)
            return [emit_copy(v) for v in value]
        return value
    execute = None
    def source_evidence(key, index):
        nonlocal execute
        identity = key, index
        if identity not in selected_sources:
            if execute is None:
                execute = psin_field_context._prepare(data, local, private, consume=charge,
                    max_depth=min(64, max_depth+1), max_sample_bytes=0)
            source = source_lists[key][index]
            path, bi, ri = source.get('field_path'), source.get('block_index'), source.get('record_index')
            _require(isinstance(path, list) and 1 <= len(path) <= 64, 'source path is unavailable')
            proof = execute([(bi, ri, path)])['queries'][0]
            _require(proof['status'] == 'resolved', 'source path cannot be replayed')
            field = proof['field']; start = field['source_slot']['data_offset']
            expected_type = 0x5c if key == 'candidate_sources' else 0x52
            _require(field['owner_hash'] == source.get('owner_hash') and field['hash'] == source.get('field_hash')
                and start == source.get('header_data_offset') and int(field['type_word'], 16) & 0xffff == expected_type,
                'source field differs from its replayed path')
            owners = structures.get(int(field['owner_hash'], 16), [])
            _require(len(owners) == 1 and field['source_slot']['byte_length'] >= 16, 'source owner/header is not bounded')
            owner = owners[0]; definition = owner.fields[path[-1]]; di = definition.type_word >> 16
            _require(di < len(owner.fields) and di != path[-1] and definition.auxiliary == 0
                and psin_references.field_slot_clear(owner, definition, 16), 'source descriptor/header is invalid')
            descriptor = owner.fields[di]
            _require(descriptor.name_hash == 0x100 and descriptor.data_offset == 0
                and descriptor.type_word == 7 and descriptor.auxiliary == 0, 'source reference descriptor differs')
            if key == 'candidate_sources':
                a, b, raw = struct.unpack_from('<IIQ', data, start)
                _require(a > 0 and a == b and 1 <= (raw & 0xfffff) <= len(blocks), 'source candidate header differs')
                pool = blocks[(raw & 0xfffff)-1]; offset = raw >> 20
                expected_span = dict(block_index=pool.index, byte_offset=offset,
                    data_offset=pool.data_offset+offset, byte_length=a*8)
                _require(source['storage_span'] == expected_span, 'candidate span differs from raw header')
            else:
                array = psin_arrays.resolve_reference_links(data, start, owner, di, blocks,
                    local_owner=True, local_structures=structures, consume=charge)
                _require(array['status'] == 'complete' and source['storage_span'] == array['target'],
                         'ordinary storage differs from existing source resolver')
            selected_sources[identity] = len(tables[key])
            tables[key].append(emit_copy(dict(source, source_path_context=proof['field'])))
        return selected_sources[identity]
    output = []
    for bi, ri in queries:
        charge()
        row = dict(block_index=bi, record_index=ri, status='unresolved',
            conditional_incoming=[], ordinary_incoming=[], semantic_owner='unknown', associations_admitted=0)
        output.append(row)
        if bi >= len(blocks):
            row['reason'] = 'selected block does not exist'; continue
        block = blocks[bi]; defs = structures.get(block.type_hash, [])
        if len(defs) != 1 or defs[0].byte_size <= 0 or block.byte_length % defs[0].byte_size:
            row['reason'] = 'selected block lacks a unique positive local typed-row layout'; continue
        stride = defs[0].byte_size; count = block.byte_length//stride
        if ri >= count:
            row['reason'] = 'selected record does not exist in the local typed block'; continue
        target = dict(block_index=bi, record_index=ri, structure_hash=f'0x{block.type_hash:08x}',
            data_offset=block.data_offset+ri*stride, byte_length=stride)
        existing = private['blocks'][bi]
        _require(existing.get('record_count') == count and isinstance(existing.get('records'), list)
            and len(existing['records']) == count and isinstance(existing['records'][ri], dict)
            and all(type(existing['records'][ri].get(k)) is type(v) and existing['records'][ri][k] == v for k, v in target.items()
                if k in ('structure_hash', 'data_offset', 'byte_length')), 'queried row differs from existing source instances')
        row.update(status='resolved', target=target, resolution_scope='typed row and incoming evidence lookup only')
        for wi, memberships in by_target.get((bi, ri), []):
            if wi not in selected_words:
                selected_words[wi] = len(tables['words']); tables['words'].append(emit_copy(words[wi]))
            for key, si in memberships:
                identity = wi, key, si
                if identity not in selected_occurrences:
                    _require(len(tables['occurrences']) < MAX_OCCURRENCES, 'exceeds incoming occurrence bound')
                    source_index = source_evidence(key, si)
                    span = source_lists[key][si]['storage_span']
                    occurrence = dict(index=len(tables['occurrences']), word_evidence_index=selected_words[wi],
                        source_evidence_table=key, source_evidence_index=source_index,
                        source_word_index=(words[wi]['data_offset']-span['data_offset'])//8,
                        authority='conditional_type5c_candidate' if key == 'candidate_sources' else 'existing_supported_ordinary_array_control',
                        associations_admitted=0, new_record_span_authorized=False)
                    selected_occurrences[identity] = occurrence['index']; tables['occurrences'].append(emit_copy(occurrence))
                name = 'conditional_incoming' if key == 'candidate_sources' else 'ordinary_incoming'
                charge(); emit_copy(selected_occurrences[identity]); row[name].append(selected_occurrences[identity])
        row['conditional_word_count'] = len({tables['occurrences'][i]['word_evidence_index'] for i in row['conditional_incoming']})
        row['ordinary_word_count'] = len({tables['occurrences'][i]['word_evidence_index'] for i in row['ordinary_incoming']})
    resolved = sum(row['status'] == 'resolved' for row in output)
    return dict(format='gta6x-psin-pool-incoming-v1', profile=PROFILE, source_sha256=digest,
        schema_id=local.schema_id, max_depth=max_depth, status='complete' if resolved == len(output) else 'partial',
        queries=output, evidence=tables, scan_complete=report['scan_complete'], scan_reasons=list(report['scan_reasons']),
        summary=dict(nodes=used, requested=len(output), resolved=resolved, unresolved=len(output)-resolved,
            words=len(tables['words']), conditional_occurrences=sum(o['source_evidence_table']=='candidate_sources' for o in tables['occurrences']),
            ordinary_occurrences=sum(o['source_evidence_table']=='ordinary_sources' for o in tables['occurrences']),
            associations_admitted=0, record_links=0, semantic_types_promoted=0),
        interpretation='Reverse navigation over source-checked conditional pool words and separately pre-existing ordinary-array controls. Lookup success and grammar matches create no type5c meaning, count/empty rule, application owner or new record/graph association.')
