"""Bounded DOT rendering of existing checked local PSIN record associations.

Fresh graph/instance/header reports are replayed; serialized JSON is not source
checksum authentication. No new edges, semantic owners or global identities are
inferred. Source clusters never merge records and omit filenames by default.
"""
from __future__ import annotations

import re

from . import psin_graph_context

PROFILE = 'checked_local_psin_graph_dot_v1'
MAX_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 4096
MAX_RECORDS = 65536
MAX_EDGES = 131072
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_TYPE = re.compile(r'0x[0-9a-f]{8}\Z')


def _quote(text):
    """Produce one quoted DOT string, retaining controls as visible escapes."""
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError('invalid bounded PSIN DOT label')
    parts = []
    for char in text:
        if char == '\\': parts.append('\\\\')
        elif char == '"': parts.append('\\"')
        elif char == '\n': parts.append('\\n')
        elif ord(char) < 32 or ord(char) == 127:
            # Double the slash so DOT shows the escape rather than treating a
            # control or unknown Graphviz escape as syntax or a label command.
            parts.append('\\\\x' + f'{ord(char):02x}')
        else: parts.append(char)
    try:
        value = '"' + ''.join(parts) + '"'
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError('invalid PSIN DOT label encoding') from exc
    return value


def inspect(resources, *, consume, max_bytes=MAX_BYTES):
    """Render all source-local record nodes and edges, with no prefix truncation.

    ``resources`` must be fresh same-invocation native resource reports. The
    existing graph-context reader replays their graph against instance/header
    (and bucket-map, if used) metadata. This does not reverify raw source bytes.
    Unsupported/refused sources remain labeled empty clusters with incomplete
    coverage. Work, record, edge and byte caps reject the entire DOT result.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
        raise ValueError('PSIN DOT byte limit must be 1..8388608')
    if not isinstance(resources, (list, tuple)) or len(resources) > MAX_SOURCES:
        raise ValueError('PSIN DOT requires at most 4096 native source reports')
    used = output_bytes = records = edge_count = refused = partial = unknown = missing = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    charge(1 + len(resources))
    lines = []; sources = []
    def emit(line):
        nonlocal output_bytes
        encoded = (line+'\n').encode('utf-8')
        if len(encoded) > max_bytes-output_bytes:
            raise ValueError('PSIN DOT output exceeds byte limit')
        charge(1 + (len(encoded)+63)//64)
        output_bytes += len(encoded); lines.append(line)
    emit('digraph psin_records {')
    emit('  graph [label="Checked local PSIN associations; missing links and semantic owners remain unknown", labelloc=t];')
    emit('  node [shape=box];')
    for si, resource in enumerate(resources):
        charge()
        if not isinstance(resource, dict):
            raise ValueError('invalid PSIN DOT source report')
        source = dict(index=si, status='unavailable')
        for key in ('sha256', 'schema_id'):
            if key in resource:
                value = resource[key]
                if not isinstance(value, str) or not _DIGEST.fullmatch(value):
                    raise ValueError('invalid PSIN DOT source identity')
                source[key] = value
        sources.append(source)
        emit(f'  subgraph cluster_{si} {{')
        graph = resource.get('record_graph')
        if (resource.get('status') != 'ok' or not isinstance(graph, dict)
                or graph.get('status') == 'refused'):
            refused += 1
            source['reason'] = 'checked source graph unavailable or refused'
            emit(f'    label={_quote(f"Source {si}: checked graph unavailable; coverage incomplete")};')
            emit('  }'); continue
        if 'sha256' not in source or 'schema_id' not in source:
            raise ValueError('PSIN DOT checked graph requires source/schema identities')
        if (not isinstance(resource.get('instances'), dict) or
                resource['instances'].get('schema_id') != source['schema_id']):
            raise ValueError('PSIN DOT instance schema differs from its source identity')
        if (not isinstance(graph.get('nodes'), list) or not isinstance(graph.get('edges'), list)
                or len(graph['nodes']) > MAX_RECORDS-records
                or len(graph['edges']) > MAX_EDGES-edge_count):
            raise ValueError('PSIN DOT exceeds aggregate record/edge limit')
        if graph.get('type5c_profile') and graph.get('type5c_source_sha256') != source['sha256']:
            raise ValueError('PSIN DOT type5c source checksum differs from source identity')
        psin_graph_context.inspect(resource.get('instances'), graph, [], consume=charge,
            resource_header=resource.get('resource_header'),
            bucket_maps=resource.get('bucket_maps') if graph.get('bucket_profile') else None,
            type5c_spans=resource.get('type5c_spans') if graph.get('type5c_profile') else None)
        summary = graph['summary']; nodes = graph['nodes']; edges = graph['edges']
        source.update(status=graph['status'],record_nodes=len(nodes),record_edges=len(edges),
            unresolved_fields=summary['unresolved_fields'],unrepresented_blocks=summary['unrepresented_blocks'],
            unsupported_associations=summary['unsupported_associations'],
            depth_limited=bool(graph['reachability']['depth_limited']),candidate_role='unknown')
        partial += graph['status'] == 'partial'
        unknown += summary['unresolved_fields']; missing += summary['unrepresented_blocks']
        records += len(nodes); edge_count += len(edges)
        title = (f"Source {si} | schema {source['schema_id'][:16]} | {graph['status']} associations\n"
                 f"{source['unresolved_fields']} unresolved fields; {source['unrepresented_blocks']} unrepresented blocks\n"
                 'Candidate/root role and graph completeness unconfirmed')
        charge(1 + (len(title)+63)//64)
        emit(f'    label={_quote(title)};')
        candidate = graph['reachability'].get('candidate_node_index')
        for node in nodes:
            charge()
            if not isinstance(node.get('structure_hash'), str) or not _TYPE.fullmatch(node['structure_hash']):
                raise ValueError('invalid PSIN DOT record declaration hash')
            label = (f"{node['block_index']}:{node['record_index']} | {node['structure_hash']}\n"
                     f"@{node['data_offset']} +{node['byte_length']} bytes | {node['record_status']}")
            if node['index'] == candidate: label += '\nLRSC candidate (role unknown)'
            charge(1 + (len(label)+63)//64)
            emit(f"    s{si}_n{node['index']} [label={_quote(label)}];")
        for edge in edges:
            charge(1 + len(edge['field_path']))
            path = '.'.join(map(str,edge['field_path']))
            label = f"e{edge['index']} {edge['kind']} | field {path}"
            if 'element_index' in edge: label += f" | element {edge['element_index']}"
            if edge['kind'] == 'bucket_reference':
                label += f" | bucket {edge['bucket_index']} slot {edge['slot_index']}"
            charge(1 + (len(label)+63)//64)
            emit(f"    s{si}_n{edge['source_node_index']} -> s{si}_n{edge['target_node_index']} "
                 f"[id=\"s{si}_e{edge['index']}\", label={_quote(label)}];")
        emit('  }')
    emit('}')
    return dict(format='gta6x-psin-graph-dot-v1',profile=PROFILE,
        status='partial' if refused or partial or not resources else 'complete',
        dot='\n'.join(lines)+'\n',sources=sources,
        source_payloads_reverified=False,
        summary=dict(nodes=used,sources=len(sources),source_graphs=len(sources)-refused,
            source_graphs_refused=refused,source_graphs_partial=partial,
            record_nodes=records,record_edges=edge_count,unresolved_fields=unknown,
            unrepresented_blocks=missing,output_bytes=output_bytes,asset_bindings=0),
        interpretation='Replayed existing local record associations only; no new links, complete-world coverage, semantic owner, transform or asset binding. Filenames are omitted; source payloads are not reverified by DOT rendering.')
