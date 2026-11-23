"""Observed local reference incidence and ancestry, without semantic ownership.

Only existing source rows and counted structure ranges are used. A unique
incoming reference or an unreferenced row does not establish transform owners,
application roots, object lifetimes, placements or a complete world graph.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter, deque
import struct

from . import world_links

PROFILE = 'world_0drp_observed_reference_context_v1'


def inspect(data, structures, blocks, *, consume, links=None, queries=()):
    """Describe exact local incidence without expanding target record ranges.

    Normalized declarations and optional links must be fresh, same-source output
    of this project's readers. Supplied links are source-revalidated but their
    completeness is a caller provenance requirement; persisted arbitrary JSON
    is not authenticated. Without supplied links, the own reader is invoked.
    All work and output use the enclosing catalog's shared node budget.
    """
    if (not isinstance(data, bytes) or not 80 <= len(data) <= world_links.MAX_BYTES
            or data[16:20] != b'0DRP' or struct.unpack_from('<I', data, 20)[0] != 122):
        raise ValueError('reference context requires bounded version-122 0DRP bytes')
    if not isinstance(queries, (list, tuple)) or len(queries) > 32:
        raise ValueError('reference context accepts at most 32 record queries')
    for query in queries:
        if (not isinstance(query, (list, tuple)) or len(query) != 2
                or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in query)):
            raise ValueError('reference-context queries require unsigned block and record indices')
    if not isinstance(structures, list) or not isinstance(blocks, list):
        raise ValueError('reference context requires local normalized declarations')
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    charge()
    def uint(value, maximum, label):
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError('invalid reference-context ' + label)
        return value
    index = {}
    for definition in structures:
        charge()
        if (not isinstance(definition, dict) or not isinstance(definition.get('hash'), str)
                or not isinstance(definition.get('fields'), list)):
            raise ValueError('invalid reference-context structure')
        uint(definition.get('byte_size'), world_links.MAX_BYTES, 'structure extent')
        for field in definition['fields']:
            charge()
            if not isinstance(field, list) or len(field) != 4:
                raise ValueError('invalid reference-context field')
            for value in field: uint(value, 0xffffffff, 'field word')
        index.setdefault(definition['hash'], []).append(definition)
    typed = {}; unrepresented = 0
    for bi, block in enumerate(blocks):
        charge()
        if not isinstance(block, dict) or block.get('index') != bi or type(block.get('index')) is not int:
            raise ValueError('invalid reference-context block index')
        length = uint(block.get('byte_length'), world_links.MAX_BYTES, 'block length')
        at = block.get('data_offset')
        if at is not None:
            uint(at, len(data), 'block offset')
            if at < 80 or at > len(data)-length: raise ValueError('reference-context block exceeds source')
        elif length: raise ValueError('nonnull reference-context block has no source span')
        definitions = index.get(block.get('type_hash'), [])
        if len(definitions) != 1 or not length or not definitions[0]['byte_size'] or length % definitions[0]['byte_size']:
            unrepresented += 1; continue
        owner = definitions[0]
        typed[bi] = dict(definition=owner, stride=owner['byte_size'], records=length//owner['byte_size'])
    normalized_queries = []
    for query in queries:
        charge()
        bi,ri = query
        reason = ('block outside observed source' if bi >= len(blocks) else
                  'block has no unique tiled local structure' if bi not in typed else
                  'record outside observed source block' if ri >= typed[bi]['records'] else None)
        normalized_queries.append((bi, ri, reason))
    if links is None:
        links = world_links.inspect(data, structures, blocks, consume=charge)
    if (not isinstance(links, dict) or links.get('profile') != world_links.PROFILE
            or not isinstance(links.get('links'), list) or not isinstance(links.get('source_paths'), list)
            or not isinstance(links.get('summary'), dict)
            or links['summary'].get('reference_ranges') != len(links['links'])):
        raise ValueError('reference context requires same-source checked local links')
    paths = links['source_paths']; rows = links['links']
    events = {}; intervals = {}; pairs = Counter(); source_headers = set()
    for i, row in enumerate(rows):
        charge()
        if not isinstance(row, dict): raise ValueError('invalid reference-context link')
        source = uint(row.get('source_block_index'), len(blocks)-1, 'source block')
        target = uint(row.get('target_block_index'), len(blocks)-1, 'target block')
        if source not in typed or target not in typed: raise ValueError('reference-context link lacks local typed rows')
        source_record = uint(row.get('source_record_index'), typed[source]['records']-1, 'source record')
        target_record = uint(row.get('target_record_index'), typed[target]['records']-1, 'target record')
        count = uint(row.get('count'), typed[target]['records']-target_record, 'reference count')
        if not count: raise ValueError('reference-context link count is empty')
        path_index = uint(row.get('source_path_index'), len(paths)-1, 'source path')
        path = paths[path_index]; owner = typed[source]['definition']
        if (not isinstance(path, dict) or path.get('index') != path_index
                or path.get('source_structure_hash') != owner['hash']
                or not isinstance(path.get('field_path'), list) or not 1 <= len(path['field_path']) <= 65):
            raise ValueError('reference-context source path does not match local row')
        position = blocks[source]['data_offset']+source_record*owner['byte_size']
        for depth, step in enumerate(path['field_path']):
            charge()
            if not isinstance(step, dict): raise ValueError('invalid reference-context path step')
            fi = uint(step.get('field_index'), len(owner['fields'])-1, 'field index')
            field = owner['fields'][fi]; name, offset, word, auxiliary = field
            di = word >> 16
            if name == 0x100 or di >= len(owner['fields']) or di == fi:
                raise ValueError('reference-context path has no supported field descriptor')
            descriptor = owner['fields'][di]; candidates = index.get(f'0x{descriptor[3]:08x}', [])
            if descriptor[:3] != [0x100, 0, 5] or len(candidates) != 1 or not candidates[0]['byte_size']:
                raise ValueError('reference-context path descriptor differs from local structure')
            others = [f[1] for j,f in enumerate(owner['fields']) if j != fi and f[0] != 0x100]
            if offset >= owner['byte_size'] or offset in others:
                raise ValueError('reference-context source field slot is ambiguous')
            end = min([v for v in others if v > offset]+[owner['byte_size']])
            child = candidates[0]; position += offset
            terminal = depth == len(path['field_path'])-1
            if not terminal:
                if word & 0xffff != 0x50 or not auxiliary or auxiliary*child['byte_size'] != end-offset:
                    raise ValueError('reference-context inline path does not exhaust its field slot')
                element = uint(step.get('element_index'), auxiliary-1, 'inline element')
                position += element*child['byte_size']; owner = child
            else:
                if word & 0xffff != 0x5c or auxiliary or end-offset != 16 or 'element_index' in step:
                    raise ValueError('reference-context terminal path is not a counted field')
                if (path.get('field_structure_hash') != owner['hash']
                        or path.get('field_hash') != f'0x{name:08x}'
                        or path.get('target_structure_hash') != child['hash']
                        or path.get('target_stride') != child['byte_size']
                        or blocks[target]['type_hash'] != child['hash']):
                    raise ValueError('reference-context terminal descriptor differs from link')
        if row.get('source_data_offset') != position or not 80 <= position <= len(data)-16:
            raise ValueError('reference-context source header location differs')
        source_identity = source,source_record,position
        if source_identity in source_headers: raise ValueError('reference-context link repeats a source field')
        source_headers.add(source_identity)
        a,b,word = struct.unpack_from('<IIQ',data,position)
        if (a,b) != (count,count) or row.get('reference_bits') != f'0x{word:016x}' or (
                word & 0xfffff != target+1 or word >> 20 != target_record*typed[target]['stride']):
            raise ValueError('reference-context link does not reproduce source header and target')
        charge(3)
        events.setdefault(target, []).extend(((target_record,1),(target_record+count,-1)))
        intervals.setdefault(target, []).append((target_record,target_record+count,i))
        pairs[source,target] += 1
    result = []; unreferenced = []; totals = Counter()
    lookup = {}
    for bi, info in typed.items():
        charge(); histogram = Counter(); coverage = []; last = incoming = 0
        def span(stop):
            nonlocal last
            if stop > last:
                count = stop-last; histogram[incoming] += count
                if coverage and coverage[-1]['incoming_references'] == incoming:
                    coverage[-1]['record_count'] += count
                else:
                    charge(); coverage.append(dict(record_start=last,record_count=count,incoming_references=incoming))
                last = stop
        combined = Counter()
        for pos, delta in events.get(bi, []):
            charge(); combined[pos] += delta
        for position, delta in sorted(combined.items()):
            span(position); incoming += delta
            if incoming < 0: raise ValueError('reference-context incidence became negative')
        span(info['records'])
        if incoming: raise ValueError('reference-context incidence does not terminate')
        for item in coverage:
            if item['incoming_references'] == 0:
                charge(); unreferenced.append(dict(block_index=bi,**item))
        totals['typed_records'] += info['records']; totals['unreferenced_records'] += histogram[0]
        totals['singly_referenced_records'] += histogram[1]
        totals['multiply_referenced_records'] += sum(n for k,n in histogram.items() if k > 1)
        result.append(dict(block_index=bi,type_hash=blocks[bi]['type_hash'],stride=info['stride'],
            record_count=info['records'],coverage_intervals=coverage,
            histogram=[dict(incoming_references=k,record_count=v) for k,v in sorted(histogram.items()) if v]))
        ordered = sorted(intervals.get(bi, [])); starts = []; prefix = []; maximum = 0
        for start,end,link_index in ordered:
            charge()
            maximum = max(maximum,end); starts.append(start); prefix.append(maximum)
        lookup[bi] = ordered,starts,prefix
    adjacency = {bi:set() for bi in typed}; indegree = Counter()
    edges = []
    for (source,target),count in sorted(pairs.items()):
        charge(); adjacency[source].add(target); indegree[target] += 1
        edges.append(dict(source_block_index=source,target_block_index=target,reference_ranges=count))
    queue = deque(bi for bi in typed if not indegree[bi]); visited = 0
    while queue:
        bi = queue.popleft(); visited += 1
        for target in adjacency[bi]:
            indegree[target] -= 1
            if not indegree[target]: queue.append(target)
    contexts = []
    def evidence(li):
        row = rows[li]; path = paths[row['source_path_index']]
        charge(1+len(path['field_path']))
        return dict(row, reference_index=li, source_structure_hash=path['source_structure_hash'],
            field_structure_hash=path['field_structure_hash'],field_hash=path['field_hash'],
            field_path=[dict(step) for step in path['field_path']],
            target_structure_hash=path['target_structure_hash'],target_stride=path['target_stride'])
    for bi,ri,reason in normalized_queries:
        if reason is not None:
            charge(); contexts.append(dict(block_index=bi,record_index=ri,status='unresolved',reason=reason,ancestry=[]))
            continue
        charge(); chain = []; seen = set(); current = bi,ri
        while True:
            charge()
            if current in seen: status='cycle_in_observed_record_references'; break
            if len(chain) >= 64: status='depth_limited'; break
            seen.add(current); block,record = current; ordered,starts,prefix = lookup[block]
            offset = bisect_right(starts,record)-1; matches = []
            while offset >= 0 and prefix[offset] > record:
                charge(); first,end,li = ordered[offset]
                if first <= record < end: matches.append(li)
                offset -= 1
            if not matches: status='unreferenced_in_observed_profile'; break
            if len(matches) != 1:
                charge(len(matches)); chain.append(dict(target_block_index=block,target_record_index=record,
                    incoming_reference_indices=sorted(matches),incoming_references=[evidence(li)for li in sorted(matches)]))
                status='ambiguous_incoming_references'; break
            li = matches[0]; row = rows[li]; charge()
            chain.append(dict(evidence(li),queried_target_block_index=block,queried_target_record_index=record))
            current = row['source_block_index'],row['source_record_index']
        contexts.append(dict(block_index=bi,record_index=ri,status=status,ancestry=chain,
            terminal_block_index=current[0],terminal_record_index=current[1]))
    totals.update(nodes=used,typed_blocks=len(typed),reference_ranges=len(rows),unrepresented_blocks=unrepresented,
        block_pairs=len(edges),queries=len(contexts))
    return dict(status='partial',profile=PROFILE,blocks=result,unreferenced_ranges=unreferenced,
        block_graph=dict(acyclic=visited==len(typed),edges=edges,
            interpretation='block aggregation only; a block cycle need not be a record cycle'),
        queries=contexts,summary=dict(totals),
        offset_space='decompressed same-source 0DRP bytes; record indices belong to local declared blocks',
        node_accounting='includes link-reader work only when links are not supplied; all invoked work uses caller budget',
        interpretation='Observed local reference incidence/ancestry only; semantic roots, ownership, transform meanings and graph completeness unknown.')
