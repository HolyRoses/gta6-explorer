"""Bounded paths through existing checked PSIN record associations.

Paths start at the existing LRSC candidate, whose application role is unknown.
No source word, value, pool or hash is reinterpreted as a pointer or transform.
Inputs must be fresh same-source reports, not arbitrary persisted JSON.
"""
from __future__ import annotations

from collections import deque

from . import psin_record_graph

PROFILE = 'checked_psin_record_context_v1'
MAX_NODES = 2_000_000


def inspect(instances, graph, queries, *, consume, resource_header=None,
            bucket_maps=None, type5c_spans=None, max_depth=None):
    """Revalidate a live graph and return self-contained bounded query paths.

    The existing graph reader rechecks instances, source paths and targets using
    its established profiles. This is not authentication of reader JSON or raw
    source checksums. Header-candidate graphs require the fresh header report.
    The graph's recorded work is charged before replay and all further work uses
    the caller's shared callback. Failure returns no prefix result.
    """
    if not isinstance(queries, (list, tuple)) or len(queries) > 32:
        raise ValueError('PSIN record context accepts at most 32 queries')
    for query in queries:
        if (not isinstance(query, (list, tuple)) or len(query) != 2
                or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in query)):
            raise ValueError('PSIN context queries require unsigned block/record pairs')
    if (not isinstance(graph, dict) or graph.get('format') != 'gta6x-psin-record-graph-v1'
            or graph.get('profile') != psin_record_graph.PROFILE
            or graph.get('status') not in ('complete', 'partial')
            or not isinstance(graph.get('summary'), dict)
            or not isinstance(graph.get('reachability'), dict)):
        raise ValueError('PSIN context requires a checked record graph')
    work = graph['summary'].get('nodes')
    graph_depth = graph['reachability'].get('max_depth')
    if type(work) is not int or not 3 <= work <= MAX_NODES:
        raise ValueError('invalid PSIN context graph work count')
    if type(graph_depth) is not int or not 1 <= graph_depth <= 64:
        raise ValueError('invalid PSIN context graph depth')
    depth = graph_depth if max_depth is None else max_depth
    if type(depth) is not int or not 1 <= depth <= graph_depth:
        raise ValueError('PSIN context depth must be within the graph depth limit')
    if graph['reachability'].get('status') == 'candidate_reachability' and resource_header is None:
        raise ValueError('PSIN context candidate requires its same-source resource header')
    from . import psin_type5c_graph
    if ((graph.get('type5c_profile') is not None and graph.get('type5c_profile') != psin_type5c_graph.PROFILE)
            or (graph.get('type5c_profile') is not None) != (type5c_spans is not None)):
        raise ValueError('PSIN context type5c graph requires matching same-source span evidence')
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    charge(work)
    replay = psin_record_graph.inspect(instances, resource_header, max_nodes=work,
        max_depth=graph_depth, bucket_maps=bucket_maps, type5c_spans=type5c_spans)
    if replay != graph:
        raise ValueError('PSIN context graph differs from its source instance/header reports')
    nodes, edges = replay['nodes'], replay['edges']
    charge(2 + len(nodes) + len(edges))
    identities = {(n['block_index'], n['record_index']): n['index'] for n in nodes}
    incoming = [[] for _ in nodes]; outgoing = [[] for _ in nodes]
    indegree = [0] * len(nodes)
    for edge in edges:
        source, target = edge['source_node_index'], edge['target_node_index']
        outgoing[source].append(edge['index']); incoming[target].append(edge['index'])
        indegree[target] += 1
    queue = deque(i for i, degree in enumerate(indegree) if not degree)
    visited = 0
    while queue:
        charge(); current = queue.popleft(); visited += 1
        for ei in outgoing[current]:
            charge(); target = edges[ei]['target_node_index']; indegree[target] -= 1
            if not indegree[target]: queue.append(target)
    candidate = replay['reachability'].get('candidate_node_index')
    distances = {}; previous = {}; ways = {}; frontier = 0
    if candidate is not None:
        distances[candidate] = 0; previous[candidate] = None; ways[candidate] = 1
        queue = deque([candidate])
        while queue:
            charge(); current = queue.popleft()
            for ei in outgoing[current]:
                charge(); target = edges[ei]['target_node_index']
                if distances[current] == depth:
                    frontier += target not in distances
                    continue
                proposed = distances[current] + 1
                if target not in distances:
                    distances[target] = proposed; previous[target] = ei
                    ways[target] = ways[current]; queue.append(target)
                elif distances[target] == proposed:
                    # Two is sufficient to distinguish one from multiple paths;
                    # exact combinatorial path counts are neither needed nor safe.
                    ways[target] = min(2, ways[target] + ways[current])

    def node_view(index):
        charge()
        return {k: v for k, v in nodes[index].items() if k != 'candidate_distance'}

    def evidence(ei):
        edge = edges[ei]; source = nodes[edge['source_node_index']]
        record = instances['blocks'][source['block_index']]['records'][source['record_index']]
        owner = record; path = []
        for ordinal, fi in enumerate(edge['field_path']):
            charge(); field = owner['fields'][fi]
            at = owner['data_offset'] + field['data_offset']
            path.append(dict(field_index=fi, structure_hash=owner['structure_hash'],
                field_hash=field['hash'], type_word=field['type_word'], data_offset=at))
            if ordinal + 1 < len(edge['field_path']): owner = field['value']
        charge(3)
        proof = dict(edge_index=ei, kind=edge['kind'], field_path=path,
            source=node_view(edge['source_node_index']), target=node_view(edge['target_node_index']))
        kind = edge['kind']
        if kind == 'field_reference':
            reference = field['reference']
            proof['source_evidence'] = dict(reference_data_offset=reference['reference_data_offset'],
                reference_byte_length=reference['reference_byte_length'], reference_bits=reference['reference_bits'])
        elif kind in ('structure_array', 'reference_array', 'enum_array', 'map_entry'):
            collection = field['map'] if kind == 'map_entry' else field['array']
            key = 'entries' if kind == 'map_entry' else 'elements'
            element = collection[key][edge['element_index']]
            proof['element_index'] = edge['element_index']
            proof['source_evidence'] = dict(profile=collection['profile'], header_data_offset=at,
                header_byte_length=24 if kind == 'map_entry' else 16,
                header_bits=collection['header_bits'], count=collection['count'],
                selected_element={k:v for k,v in element.items() if not isinstance(v,(dict,list))})
        elif kind == 'type5c_record_span':
            span = type5c_spans['fields'][edge['type5c_field_index']]
            proof['element_index'] = edge['element_index']
            proof['source_evidence'] = dict(profile=span['profile'],
                header_data_offset=span['header_data_offset'], header_byte_length=16,
                header_bits=span['header_bits'], reference_bits=span['reference_bits'],
                declared_record_stride=span['declared_record_stride'],
                target_coverage=span['target_coverage'], parent_type_meaning='unknown',
                logical_element_meaning='unknown', semantic_owner='unknown')
        elif kind == 'bucket_reference':
            # Replay above requires the complete same-source bucket-map view.
            mapping = bucket_maps['maps'][edge['bucket_map_index']]
            entry = mapping['entries'][edge['element_index']]
            proof['source_evidence'] = dict(bucket_map_index=edge['bucket_map_index'],
                bucket_index=edge['bucket_index'], slot_index=edge['slot_index'],
                entry_data_offset=edge['entry_data_offset'],
                reference_data_offset=edge['reference_data_offset'], reference_bits=entry['reference_bits'])
        else:
            raise ValueError('unsupported checked graph context edge kind')
        return proof

    contexts = []; resolved = 0
    for bi, ri in queries:
        charge(); target = identities.get((bi, ri))
        if target is None:
            contexts.append(dict(block_index=bi, record_index=ri, status='unresolved',
                reason='query selects no existing typed graph record', path=[], incoming=[]))
            continue
        charge(len(incoming[target]))
        row = dict(block_index=bi, record_index=ri, record=node_view(target),
            incoming=[evidence(ei) for ei in incoming[target]], path=[],
            shortest_path_ambiguous=False, incoming_reference_count=len(incoming[target]))
        if candidate is None:
            row.update(status='unanchored', reason='no supported LRSC record candidate supplied')
        elif target not in distances:
            row.update(status='not_reached_within_depth', depth_limited=bool(frontier),
                reason='absent from bounded checked-link reachability; unknown associations may exist')
        else:
            selected = []; current = target
            while previous[current] is not None:
                charge(); ei = previous[current]; selected.append(ei)
                current = edges[ei]['source_node_index']
            selected.reverse(); row['path'] = [evidence(ei) for ei in selected]
            row.update(status='candidate_path' if selected else 'candidate_anchor',
                candidate_distance=distances[target], shortest_path_ambiguous=ways[target] > 1)
            resolved += 1
        contexts.append(row)
    return dict(format='gta6x-psin-record-context-v1', profile=PROFILE, status='partial',
        candidate=node_view(candidate) if candidate is not None else None,
        candidate_role='unknown', queries=contexts, max_depth=depth,
        observed_graph_has_cycle=visited != len(nodes),
        scope='existing checked local associations only; missing edges, semantic ownership and transforms unknown',
        offset_space='decompressed same-source checksum-verified PSIN resource bytes',
        node_accounting='includes precharged own graph-reader replay and bounded query/source-evidence work',
        summary=dict(nodes=used, queries=len(queries), resolved=resolved,
            unresolved=len(queries)-resolved, graph_nodes=len(nodes), graph_edges=len(edges)))
