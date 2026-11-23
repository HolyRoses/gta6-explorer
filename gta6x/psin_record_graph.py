"""Finite associations between already decoded PSIN record rows.

Only existing checked record links become edges. Unknown words, scalar values
and pools are never interpreted as pointers. LRSC supplies an optional candidate
anchor, not a proven root; reachability is limited to the supplied associations.
"""
from __future__ import annotations

from collections import deque

PROFILE = 'existing_local_record_associations_v1'
MAX_BYTES = 16 * 1024 * 1024
MAX_SCAN_FIELDS = 2_000_000
ARRAY_PROFILES = {
    ('record_links', 'structure_equal_u16_v1'): 'structure_array',
    ('reference_record_links', 'reference_equal_u16_v1'): 'reference_array',
    ('enum_record_links', 'local_enum32_record_array_v1'): 'enum_array',
}
MAP_PROFILES = frozenset(('local_hash32_map_entries_v1',
    'local_enum32_structure_map_entries_v1', 'local_nested_map_entry_links_v1'))


class RecordGraphLimitError(ValueError):
    """The requested graph metadata or bounded input scan exceeds its limit."""


def _integer(value, label, maximum=MAX_BYTES):
    if type(value) is not int or value < 0 or value > maximum:
        raise ValueError('invalid record-graph ' + label)
    return value


def inspect(instances, resource_header=None, *, max_nodes=100000, max_depth=16):
    """Index trusted decoder output and bound candidate-anchor reachability.

    This checks report identities/spans, not the original container checksum.
    Every edge selects an existing top-level typed row. Embedded source fields
    retain a field-index path within their owning top-level row. No record or
    scalar is expanded/copied. Graph cycles remain finite indexed links.
    """
    if type(max_nodes) is not int or max_nodes < 1:
        raise RecordGraphLimitError('PSIN record-graph output exceeds node limit')
    if type(max_depth) is not int or not 1 <= max_depth <= 64:
        raise ValueError('record-graph max_depth must be 1..64')
    if not isinstance(instances, dict) or instances.get('format') != 'gta6x-psin-instances-v1':
        raise ValueError('record graph requires an existing PSIN instance report')
    if instances.get('status') not in ('complete', 'partial'):
        raise ValueError('record graph requires decoded instance rows')
    used = 0
    def consume(amount=1):
        nonlocal used
        if amount > max_nodes-used:
            raise RecordGraphLimitError('PSIN record-graph output exceeds node limit')
        used += amount
    consume(3)  # View, summary and reachability descriptor.
    blocks = instances.get('blocks')
    if not isinstance(blocks, list) or len(blocks) > 65536:
        raise ValueError('invalid record-graph block table')
    nodes, sources, identities = [], [], {}
    missing_blocks = 0
    previous_end = 0
    for bi, block in enumerate(blocks):
        if not isinstance(block, dict) or type(block.get('index')) is not int or block.get('index') != bi:
            raise ValueError('record-graph block indices do not match source rows')
        start = _integer(block.get('data_offset'), 'block offset')
        size = _integer(block.get('byte_length'), 'block length')
        if (not isinstance(block.get('type_hash'), str) or not block['type_hash'].startswith('0x')
                or size == 0 or start < previous_end or start+size > MAX_BYTES):
            raise ValueError('invalid record-graph block span')
        previous_end = start+size
        rows = block.get('records')
        if rows is None:
            missing_blocks += 1
            continue
        if (not isinstance(rows, list) or type(block.get('record_count')) is not int
                or block.get('record_count') != len(rows) or not rows):
            raise ValueError('invalid record-graph typed rows')
        at = start
        stride = None
        for ri, record in enumerate(rows):
            if not isinstance(record, dict) or not isinstance(record.get('fields'), list):
                raise ValueError('invalid record-graph record fields')
            size = _integer(record.get('byte_length'), 'record length')
            if (not size or record.get('data_offset') != at
                    or type(record.get('data_offset')) is not int
                    or record.get('structure_hash') != block.get('type_hash')
                    or record.get('status') not in ('complete', 'partial')):
                raise ValueError('record-graph record identity/span differs from its block')
            if stride is None: stride = size
            if size != stride or at+size > previous_end:
                raise ValueError('record-graph record stride exceeds its block')
            consume()
            ni = len(nodes)
            nodes.append(dict(index=ni, block_index=bi, record_index=ri,
                data_offset=at, byte_length=size, structure_hash=record['structure_hash'],
                record_status=record['status']))
            sources.append(record)
            identities[bi, ri] = ni
            at += size
        if at != previous_end:
            raise ValueError('record-graph typed rows do not exhaust their block')

    edges = []
    unknown_fields = excluded_text = nulls = unsupported = scanned = 0
    def target(link):
        if not isinstance(link, dict) or link.get('status') != 'record_reference':
            raise ValueError('invalid checked record-graph association')
        bi = _integer(link.get('block_index'), 'target block index', len(blocks))
        ri = _integer(link.get('record_index'), 'target record index')
        ni = identities.get((bi, ri))
        if ni is None:
            raise ValueError('record-graph association selects no existing typed row')
        node = nodes[ni]
        if any(link.get(key) != node[key] for key in ('data_offset', 'byte_length', 'structure_hash')):
            raise ValueError('record-graph association identity/span differs from its target')
        return ni

    def edge(source, link, kind, path, element=None):
        ni = target(link)
        consume(1+len(path))
        row = dict(index=len(edges), source_node_index=source, target_node_index=ni,
                   kind=kind, field_path=list(path))
        if element is not None: row['element_index'] = element
        edges.append(row)

    for source, record in enumerate(sources):
        stack = [(record, (), frozenset())]
        while stack:
            owner, prefix, active = stack.pop()
            if id(owner) in active or len(prefix) > 64:
                raise ValueError('cyclic or over-depth embedded record view')
            fields = owner.get('fields')
            if not isinstance(fields, list):
                raise ValueError('invalid embedded record fields')
            active = active | {id(owner)}
            for fi, field in enumerate(fields):
                scanned += 1
                if scanned > MAX_SCAN_FIELDS:
                    raise RecordGraphLimitError('PSIN record-graph field scan exceeds limit')
                if not isinstance(field, dict) or field.get('status') not in ('decoded', 'complete', 'partial', 'descriptor', 'unresolved'):
                    raise ValueError('invalid record-graph field')
                field_offset = _integer(field.get('data_offset'), 'field offset')
                if field_offset >= owner['byte_length']:
                    raise ValueError('record-graph field exceeds its owning record')
                field_start = owner['data_offset'] + field_offset
                path = prefix+(fi,)
                if field.get('status') == 'unresolved': unknown_fields += 1
                child = field.get('value')
                if field.get('type_name') == 'embedded_structure' and isinstance(child, dict) and 'fields' in child:
                    at = _integer(child.get('data_offset'), 'embedded offset')
                    size = _integer(child.get('byte_length'), 'embedded length')
                    if (not size or at != field_start or at+size > owner['data_offset']+owner['byte_length']
                            or child.get('status') not in ('complete', 'partial')
                            or field.get('status') != child.get('status')
                            or not isinstance(child.get('structure_hash'), str)):
                        raise ValueError('embedded record identity/span differs from its owning field')
                    stack.append((child, path, active))
                ref = field.get('reference')
                if isinstance(ref, dict):
                    if ref.get('status') == 'record_reference' and field.get('status') == 'complete':
                        if ref.get('profile') == 'local_record_reference_v1':
                            if (ref.get('reference_data_offset') != field_start or ref.get('reference_byte_length') != 8
                                    or field_offset+8 > owner['byte_length']):
                                raise ValueError('record-graph reference source exceeds its field')
                            edge(source, ref, 'field_reference', path)
                        else: unsupported += 1
                    elif ref.get('status') == 'null_reference' and field.get('status') == 'complete':
                        if (ref.get('reference_bits') != '0x0000000000000000' or ref.get('target') is not None
                                or ref.get('reference_data_offset') != field_start
                                or ref.get('reference_byte_length') != 8 or field_offset+8 > owner['byte_length']):
                            raise ValueError('invalid record-graph null-reference source')
                        nulls += 1
                text = field.get('text_reference')
                if isinstance(text, dict) and text.get('status') == 'pool_element_reference': excluded_text += 1
                array = field.get('array')
                mapping = field.get('map')
                if field.get('status') != 'complete': continue
                if isinstance(array, dict) and array.get('status') == 'complete':
                    kind = ARRAY_PROFILES.get((array.get('mode'), array.get('profile')))
                    if kind:
                        if (not isinstance(array.get('header_bits'), str) or len(array['header_bits']) != 34
                                or field_offset+16 > owner['byte_length']):
                            raise ValueError('record-graph array header exceeds its owning field')
                        elements = array.get('elements')
                        if (not isinstance(elements, list) or type(array.get('count')) is not int
                                or array.get('count') != len(elements)):
                            raise ValueError('record-graph array count differs from existing links')
                        for ei, link in enumerate(elements):
                            if not isinstance(link, dict) or type(link.get('index')) is not int or link.get('index') != ei:
                                raise ValueError('record-graph array indices differ')
                            if link.get('status') == 'null_reference' and kind == 'reference_array':
                                if link.get('reference_bits') != '0x0000000000000000' or link.get('target') is not None:
                                    raise ValueError('invalid record-graph null-array reference')
                                nulls += 1
                            else: edge(source, link, kind, path, ei)
                    elif array.get('mode') is not None: unsupported += 1
                if isinstance(mapping, dict) and mapping.get('status') == 'complete':
                    if mapping.get('mode') == 'entry_record_links' and mapping.get('profile') in MAP_PROFILES:
                        if (mapping.get('header_data_offset') != field_start or mapping.get('header_byte_length') != 24
                                or field_offset+24 > owner['byte_length']):
                            raise ValueError('record-graph map header exceeds its owning field')
                        elements = mapping.get('entries')
                        if (not isinstance(elements, list) or type(mapping.get('count')) is not int
                                or mapping.get('count') != len(elements)):
                            raise ValueError('record-graph map count differs from existing links')
                        for ei, link in enumerate(elements):
                            if not isinstance(link, dict) or type(link.get('index')) is not int or link.get('index') != ei:
                                raise ValueError('record-graph map indices differ')
                            edge(source, link, 'map_entry', path, ei)
                    else: unsupported += 1

    reach = dict(status='unanchored', reason='no supported LRSC record candidate supplied',
                 scope='checked record associations only; candidate is not a proven root',
                 max_depth=max_depth, depth_limited=False, reachable_records=0,
                 unreached_records=None, frontier_edges=0)
    anchor = None
    if resource_header is not None:
        if not isinstance(resource_header, dict): raise ValueError('invalid resource-header view')
        if resource_header.get('status') == 'complete':
            if resource_header.get('profile') != 'lrsc_header_counts_local_record_candidate_v1':
                raise ValueError('unsupported record-graph candidate profile')
            candidate = resource_header.get('record_candidate')
            if not isinstance(candidate, dict) or candidate.get('status') != 'candidate':
                raise ValueError('invalid record-graph candidate anchor')
            anchor = target(dict(candidate, status='record_reference'))
            consume()
            adjacency = [[] for _ in nodes]
            for e in edges: adjacency[e['source_node_index']].append(e['target_node_index'])
            distances = {anchor: 0}; pending = deque([anchor])
            while pending:
                current = pending.popleft()
                depth = distances[current]
                if depth == max_depth: continue
                for nxt in adjacency[current]:
                    if nxt not in distances:
                        distances[nxt] = depth+1; pending.append(nxt)
            frontier = sum(e['source_node_index'] in distances and distances[e['source_node_index']] == max_depth
                           and e['target_node_index'] not in distances for e in edges)
            for ni, node in enumerate(nodes): node['candidate_distance'] = distances.get(ni)
            reach.update(status='candidate_reachability', reason='root role and completeness unconfirmed',
                candidate_node_index=anchor, depth_limited=bool(frontier),
                reachable_records=len(distances), unreached_records=len(nodes)-len(distances), frontier_edges=frontier)
    partial = bool(unknown_fields or missing_blocks or unsupported or anchor is None or reach['depth_limited'])
    return dict(format='gta6x-psin-record-graph-v1', profile=PROFILE,
        status='partial' if partial else 'complete',
        interpretation='Existing checked record links only; unknown edges, candidate root role and application semantics remain unconfirmed.',
        nodes=nodes, edges=edges, reachability=reach,
        summary=dict(nodes=used, record_nodes=len(nodes), record_edges=len(edges),
            unresolved_fields=unknown_fields, unrepresented_blocks=missing_blocks,
            excluded_text_links=excluded_text, null_references=nulls,
            unsupported_associations=unsupported, fields_scanned=scanned,
            reachable_records=reach['reachable_records'], depth_limited=int(reach['depth_limited'])))
