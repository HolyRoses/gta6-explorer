"""Bounded DOT views of freshly checked native world counted references.

Nodes denote declared local blocks, and edges retain compact record ranges.
Reports must come from this invocation's own native reader; rendering persisted
JSON cannot authenticate bytes. No object, transform or semantic owner is inferred.
"""
from __future__ import annotations

import re

from . import world_links

PROFILE = 'native_world_checked_counted_ranges_dot_v1'
MAX_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 4096
MAX_BLOCKS = 65536
MAX_EDGES = 131072
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_TYPE = re.compile(r'0x[0-9a-f]{8}\Z')
_WORD = re.compile(r'0x[0-9a-f]{16}\Z')


def _quote(text):
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError('invalid bounded world DOT label')
    pieces = []
    for char in text:
        if char == '\\': pieces.append('\\\\')
        elif char == '"': pieces.append('\\"')
        elif char == '\n': pieces.append('\\n')
        elif ord(char) < 32 or ord(char) == 127:
            pieces.append('\\\\x' + f'{ord(char):02x}')
        else: pieces.append(char)
    try:
        value = '"' + ''.join(pieces) + '"'
        value.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError('invalid world DOT label encoding') from exc
    return value


def inspect(report, *, consume, max_bytes=MAX_BYTES):
    """Render a complete bounded view or raise, never emit a partial DOT string.

    ``report`` must be freshly produced by ``world_resources.inspect_sources``
    or the manifest delegate with links enabled. Exact local range/reference
    relationships are replayed against the report's own block declarations.
    This does not reread source payloads or authenticate caller-supplied JSON.
    Each block is one node; counted ranges are never expanded to record nodes.
    """
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_BYTES:
        raise ValueError('world DOT byte limit must be 1..8388608')
    if (not isinstance(report, dict) or report.get('format') != 'gta6x-native-world-resources-v1'
            or report.get('status') not in ('complete', 'partial')):
        raise ValueError('world DOT requires a fresh native-world report')
    resources = report.get('resources')
    refused = report.get('refused_streams')
    unknown = report.get('unclassified_streams')
    groups = report.get('schema_groups')
    if (not all(isinstance(rows, list) for rows in (resources, refused, unknown, groups))
            or len(resources) + len(refused) > MAX_SOURCES or len(groups) > MAX_SOURCES):
        raise ValueError('world DOT exceeds source/schema limits')
    used = output_bytes = block_count = edge_count = unavailable = partial = 0
    lines = []; source_rows = []

    def charge(n=1):
        nonlocal used
        consume(n); used += n

    def uint(value, maximum, label):
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError('invalid world DOT ' + label)
        return value

    def digest(value, label):
        if not isinstance(value, str) or not _DIGEST.fullmatch(value):
            raise ValueError('invalid world DOT ' + label)
        return value

    def typename(value):
        if not isinstance(value, str) or not _TYPE.fullmatch(value):
            raise ValueError('invalid world DOT declaration hash')
        return value

    def emit(line):
        nonlocal output_bytes
        encoded = (line + '\n').encode('utf-8')
        if len(encoded) > max_bytes - output_bytes:
            raise ValueError('world DOT output exceeds byte limit')
        charge(1 + (len(encoded) + 63) // 64)
        output_bytes += len(encoded); lines.append(line)

    charge(1 + len(resources) + len(refused) + len(unknown) + len(groups))
    group_index = {}
    for group in groups:
        charge()
        if not isinstance(group, dict) or group.get('format') not in ('0drp', 'psin'):
            raise ValueError('invalid world DOT schema group')
        key = digest(group.get('id'), 'schema identity')
        if key in group_index or not isinstance(group.get('structures'), list):
            raise ValueError('invalid world DOT duplicate/schema structures')
        definitions = []
        for di, definition in enumerate(group['structures']):
            charge()
            if not isinstance(definition, dict) or type(definition.get('index')) is not int or definition['index'] != di:
                raise ValueError('invalid world DOT structure index')
            typename(definition.get('hash'))
            uint(definition.get('byte_size'), world_links.MAX_BYTES, 'structure extent')
            uint(definition.get('field_count'), 0xffff, 'field count')
            definitions.append(definition)
        group_index[key] = group, definitions

    emit('digraph world_references {')
    title = ('Checked local world counted-reference ranges; semantic owners and graph completeness unknown\n'
             f'{len(unknown)} unclassified streams; {len(refused)} refused metadata sources')
    emit(f'  graph [label={_quote(title)}, labelloc=t];')
    emit('  node [shape=box];')
    for si, resource in enumerate(resources):
        charge()
        if (not isinstance(resource, dict) or type(resource.get('index')) is not int
                or resource['index'] != si or resource.get('format') not in ('0drp', 'psin')):
            raise ValueError('invalid world DOT source resource')
        source_digest = digest(resource.get('sha256'), 'source identity')
        group_id = digest(resource.get('schema_group_id'), 'source schema identity')
        if group_id not in group_index:
            raise ValueError('world DOT source has no matching schema group')
        group, definitions = group_index[group_id]
        if group['format'] != resource['format']:
            raise ValueError('world DOT source/schema formats differ')
        source_bytes = uint(resource.get('inflated_bytes'), world_links.MAX_BYTES, 'source byte length')
        uint(resource.get('offset'), (1 << 64) - 1, 'source offset')
        blocks = resource.get('blocks')
        if not isinstance(blocks, list) or len(blocks) > MAX_BLOCKS - block_count:
            raise ValueError('world DOT exceeds aggregate block limit')
        block_count += len(blocks)
        typed = {}
        prefix = f's{si}_{source_digest[:16]}'
        emit(f'  subgraph cluster_{prefix} {{')
        source = dict(index=si, sha256=source_digest, schema_group_id=group_id,
                      block_nodes=len(blocks), reference_edges=0, status='unavailable')
        source_rows.append(source)
        links = resource.get('local_links')
        supported = (resource['format'] == '0drp' and isinstance(links, dict)
                     and links.get('status') in ('complete', 'partial'))
        label = (f'Source {si} | {resource["format"]} | {source_digest}\n'
                 'Local declared blocks; object and ownership meanings unknown')
        if not supported:
            unavailable += 1
            label += '\nChecked counted-reference profile unavailable; coverage incomplete'
        emit(f'    label={_quote(label)};')
        for bi, block in enumerate(blocks):
            charge()
            if (not isinstance(block, dict) or type(block.get('block_index')) is not int
                    or block['block_index'] != bi):
                raise ValueError('invalid world DOT block identity')
            typename(block.get('type_hash'))
            length = uint(block.get('byte_length'), world_links.MAX_BYTES, 'block byte length')
            at = block.get('data_offset')
            if at is None:
                if length: raise ValueError('world DOT nonempty block has no source span')
            else:
                uint(at, source_bytes, 'block offset')
                if at < (80 if resource['format'] == '0drp' else 8) or at > source_bytes - length:
                    raise ValueError('world DOT block exceeds source bounds')
            if block.get('status') == 'schema_tiled_storage':
                di = uint(block.get('structure_index'), len(definitions) - 1, 'block structure index')
                definition = definitions[di]
                stride = uint(block.get('stride'), world_links.MAX_BYTES, 'block stride')
                count = uint(block.get('record_count'), world_links.MAX_BYTES, 'block record count')
                if (not stride or not count or stride != definition['byte_size']
                        or stride * count != length or block['type_hash'] != definition['hash']
                        or block.get('schema_group_id') != group_id):
                    raise ValueError('world DOT block does not reproduce its declaration')
                typed[bi] = block, definition
                block_label = (f'block {bi} | {block["type_hash"]}\n'
                               f'{count} local records × {stride} bytes | @{at}')
                style = ''
            elif block.get('status') == 'unresolved':
                block_label = f'block {bi} | {block["type_hash"]}\n@{at} +{length} bytes | unresolved storage'
                style = ', style=dashed'
            else:
                raise ValueError('invalid world DOT block status')
            emit(f'    {prefix}_b{bi} [label={_quote(block_label)}{style}];')
        if supported:
            if (links.get('profile') != world_links.PROFILE or not isinstance(links.get('links'), list)
                    or not isinstance(links.get('source_paths'), list) or not isinstance(links.get('summary'), dict)):
                raise ValueError('world DOT requires checked counted-reference profile')
            rows, paths, summary = links['links'], links['source_paths'], links['summary']
            if len(rows) > MAX_EDGES - edge_count:
                raise ValueError('world DOT exceeds aggregate edge limit')
            if (type(summary.get('reference_ranges')) is not int or summary['reference_ranges'] != len(rows)
                    or type(summary.get('source_paths')) is not int or summary['source_paths'] != len(paths)):
                raise ValueError('world DOT reference/path totals differ')
            for pi, path in enumerate(paths):
                charge()
                if (not isinstance(path, dict) or type(path.get('index')) is not int or path['index'] != pi
                        or not isinstance(path.get('field_path'), list) or not 1 <= len(path['field_path']) <= 65):
                    raise ValueError('invalid world DOT source path')
                for key in ('source_structure_hash', 'field_structure_hash', 'field_hash', 'target_structure_hash'):
                    typename(path.get(key))
                uint(path.get('target_stride'), world_links.MAX_BYTES, 'path target stride')
                for step in path['field_path']:
                    charge()
                    if not isinstance(step, dict): raise ValueError('invalid world DOT field path step')
                    uint(step.get('field_index'), 0xffff, 'field path index')
                    if 'element_index' in step: uint(step['element_index'], world_links.MAX_BYTES, 'inline element index')
            headers = set()
            for ei, edge in enumerate(rows):
                charge()
                if not isinstance(edge, dict): raise ValueError('invalid world DOT reference')
                sb = uint(edge.get('source_block_index'), len(blocks) - 1, 'reference source block')
                tb = uint(edge.get('target_block_index'), len(blocks) - 1, 'reference target block')
                if sb not in typed or tb not in typed:
                    raise ValueError('world DOT reference has no uniquely typed local block')
                source_block, source_definition = typed[sb]
                target_block, target_definition = typed[tb]
                sr = uint(edge.get('source_record_index'), source_block['record_count'] - 1, 'source record')
                tr = uint(edge.get('target_record_index'), target_block['record_count'] - 1, 'target record')
                count = uint(edge.get('count'), target_block['record_count'] - tr, 'target range count')
                pi = uint(edge.get('source_path_index'), len(paths) - 1, 'source path index')
                path = paths[pi]
                position = uint(edge.get('source_data_offset'), source_bytes, 'reference header offset')
                start = source_block['data_offset'] + sr * source_block['stride']
                word = edge.get('reference_bits')
                if (not count or not isinstance(word, str) or not _WORD.fullmatch(word)
                        or not start <= position <= start + source_block['stride'] - 16
                        or path['source_structure_hash'] != source_definition['hash']
                        or path['target_structure_hash'] != target_definition['hash']
                        or path['target_stride'] != target_block['stride']
                        or int(word, 16) & 0xfffff != tb + 1
                        or int(word, 16) >> 20 != tr * target_block['stride']):
                    raise ValueError('world DOT reference range/path disagrees with local storage')
                identity = sb, sr, position
                if identity in headers: raise ValueError('world DOT repeats a source field reference')
                headers.add(identity)
                field_path = '.'.join(str(step['field_index']) +
                    (f'[{step["element_index"]}]' if 'element_index' in step else '')
                    for step in path['field_path'])
                edge_label = (f'e{ei} | source record {sr}, field {field_path} | {path["field_hash"]}\n'
                              f'header @{position} -> target records [{tr}, {tr + count}) ({count})')
                emit(f'    {prefix}_b{sb} -> {prefix}_b{tb} [id="{prefix}_e{ei}", label={_quote(edge_label)}];')
            edge_count += len(rows)
            source.update(status=links['status'], reference_edges=len(rows))
            partial += links['status'] == 'partial'
        emit('  }')
    for ri, resource in enumerate(refused):
        charge()
        if not isinstance(resource, dict): raise ValueError('invalid world DOT refused source')
        emit(f'  subgraph cluster_refused_{ri} {{')
        emit(f'    label={_quote(f"Refused metadata source {ri}; checked references unavailable")};')
        emit('  }')
    emit('}')
    return dict(format='gta6x-world-graph-dot-v1', profile=PROFILE,
                status='partial' if unavailable or partial or refused or unknown or not resources else 'complete',
                dot='\n'.join(lines) + '\n', sources=source_rows,
                source_payloads_reverified=False, complete_world_graph=False,
                summary=dict(nodes=used, sources=len(resources), source_graphs=len(resources)-unavailable,
                             source_graphs_unavailable=unavailable, source_graphs_partial=partial,
                             metadata_sources_refused=len(refused), unclassified_streams=len(unknown),
                             block_nodes=block_count, reference_edges=edge_count, output_bytes=output_bytes,
                             asset_bindings=0),
                interpretation='Fresh report replay only; each edge is one checked counted record range, '
                'not per-record expansion or semantic ownership. No new links, resource extents, '
                'placements, transforms, assets or complete-world coverage. Filenames omitted.')
