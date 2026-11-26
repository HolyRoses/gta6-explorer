"""Measured family-61 directories and kind-0x27 cross-file key candidates.

Listed references establish addressing. Flag/family and full-key matches expose
candidates, not recording identities, station membership or playback semantics.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import deque
import struct

from . import audio_config, audio_config_providers, audio_config_references, audio_config_sections

MAX_DEPTH = 5
_FAMILIES = {1: 581, 32: 26, 64: 61, 256: 25}


class Directory:
    """Raw references only: flag 1 is not local in the family-61 profile."""

    def __init__(self, data, view, rows, locations, summary, nodes):
        self.data, self.view, self.rows, self.locations = data, view, rows, locations
        self.summary, self.nodes = summary, nodes
        self.records = {int(r['name_hash'], 16): r for r in view['records']}


def parse(data, *, max_nodes=100000, max_aux_entries=1000000, _aux_budget=None):
    """Validate the full family-61 suffix before exposing any native links."""
    consume, used = audio_config._budget(max_nodes)
    own_aux = audio_config._budget(max_aux_entries)
    consume_aux, aux_used = own_aux if _aux_budget is None else _aux_budget
    before = aux_used()
    view = audio_config.parse_index(data, max_nodes=max_nodes)
    consume(view['nodes'])
    if view['raw_family'] != 61:
        raise ValueError('kind27 directory requires family 61')
    at = view['opaque_tail']['data_offset']
    end = 8 + view['data_region']['byte_length']
    tables = []

    def table(width, label):
        nonlocal at
        if at+4 > len(data):
            raise ValueError('truncated family61 auxiliary '+label)
        count, = struct.unpack_from('<I', data, at)
        if count > (len(data)-at-4)//width:
            raise ValueError('family61 auxiliary count escapes source')
        consume_aux(count)
        begin = at+4
        tables.append(dict(role=label, data_offset=at, count=count, entry_bytes=width))
        at = begin+width*count
        return begin, count

    begin, count = table(12, 'alternate_index')
    if count != len(view['records']):
        raise ValueError('family61 alternate index count differs from primary')
    expected = {r['data_offset']-8 for r in view['records']}
    aliases, offsets = set(), set()
    for i in range(count):
        key, offset = struct.unpack_from('<QI', data, begin+12*i)
        if key in aliases or offset in offsets or offset not in expected:
            raise ValueError('family61 alternate index is not a primary-start bijection')
        aliases.add(key)
        offsets.add(offset)
    for slot in range(3):
        begin, count = table(4, f'opaque_offset_array_{slot}')
        previous = -1
        for i in range(count):
            value, = struct.unpack_from('<I', data, begin+4*i)
            if not 8 <= value <= end-4 or value <= previous:
                raise ValueError('family61 opaque offsets are unordered or out of bounds')
            previous = value
    begin, count = table(8, 'reference_entries')
    rows = [struct.unpack_from('<II', data, begin+8*i) for i in range(count)]
    begin, count = table(4, 'reference_word_locations')
    locations = []
    previous = -1
    for i in range(count):
        location, = struct.unpack_from('<I', data, begin+4*i)
        if not 8 <= location <= end-4 or location <= previous:
            raise ValueError('family61 reference locations are unordered or out of bounds')
        index, = struct.unpack_from('<I', data, location)
        if index >= len(rows):
            raise ValueError('family61 listed reference index escapes directory')
        locations.append(location)
        previous = location
    if at != len(data):
        raise ValueError('unclaimed bytes after family61 auxiliary suffix')
    summary = dict(status='parsed', source_sha256=view['sha256'], tables=tables,
        validated_aux_entries=aux_used()-before, reference_entries=len(rows),
        listed_reference_words=len(locations), interpretation='native listed reference indices; flag/family roles remain measured candidates')
    return Directory(data, view, rows, locations, summary, used())


def _references(directory, record, consume):
    start = record['data_offset']
    end = start+record['byte_length']
    a, b = bisect_left(directory.locations, start), bisect_left(directory.locations, end)
    consume(b-a)
    result = []
    for at in directory.locations[a:b]:
        if at+4 > end:
            raise ValueError('listed word crosses the source index span')
        index, = struct.unpack_from('<I', directory.data, at)
        key, flags = directory.rows[index]
        result.append(dict(word_offset=at, relative_offset=at-start,
            reference_index=index, reference_hash=f'0x{key:08x}', raw_flags=flags))
    return result


def profile27(directory, record, consume):
    """Only the measured exact header and count-exhausted span are supported."""
    start, size = record['data_offset'], record['byte_length']
    data = directory.data
    if size < 69 or data[start:start+5] != b'\x27\xa1\xaa\xaa\xaa':
        raise ValueError('unsupported kind27 header or prefix extent')
    count = data[start+68]
    if size != 69+4*count:
        raise ValueError('kind27 counted references do not exhaust index span')
    refs = _references(directory, record, consume)
    actual = {r['relative_offset']: r for r in refs}
    expected = {21: 256}
    expected.update((69+4*i, 1) for i in range(count))
    unlisted = []
    for offset, flags in ((46, 4), (52, 1)):
        if offset in actual:
            expected[offset] = flags
        elif struct.unpack_from('<I', data, start+offset)[0] != 0xffffffff:
            raise ValueError('unlisted kind27 optional field is not measured sentinel bits')
        else:
            consume()
            unlisted.append(dict(relative_offset=offset, raw_value_bits='0xffffffff'))
    if set(actual) != set(expected) or any(actual[o]['raw_flags'] != f for o, f in expected.items()):
        raise ValueError('kind27 reference positions or exact flags differ from measured profile')
    consume(5)
    return dict(status='parsed', name_hash=record['name_hash'], data_offset=start,
        indexed_span_bytes=size, raw_kind_u8=0x27, tail_count_u8=count, references=refs,
        unlisted_fields=unlisted,
        opaque_regions=[dict(relative_offset=o, raw_hex=data[start+o:start+o+n].hex())
            for o, n in ((1, 4), (5, 16), (25, 21), (50, 2), (56, 12))],
        interpretation='measured index-span profile; optional sentinel bits and numeric fields have no assigned runtime roles')


def _trace(directory, roots, contexts, resources, own, consume):
    # Every candidate keeps its source identity. Duplicate definitions never
    # collapse to a preferred provider, even when their contents are identical.
    candidates = {}
    for resource in resources:
        family = resource['raw_family']
        for record in resource['records']:
            candidates.setdefault((family, int(record['name_hash'], 16)), []).append((resource, record))
    pending = deque()
    seen = set()
    nodes, edges = [], []

    def queue(resource, record, depth):
        identity = resource['sha256'], resource['source']['offset'], record['name_hash']
        if identity in seen:
            return False
        consume()
        seen.add(identity)
        pending.append((resource, record, depth))
        return True

    for key in sorted(roots):
        queue(own, directory.records[key], 0)
    ordered = sorted(directory.records.values(), key=lambda r: r['data_offset'])
    starts = [r['data_offset'] for r in ordered]
    incoming = []
    for at in directory.locations:
        index, = struct.unpack_from('<I', directory.data, at)
        key, flags = directory.rows[index]
        if flags != 64 or key not in roots:
            continue
        consume()
        ordinal = bisect_right(starts, at)-1
        record = ordered[ordinal] if ordinal >= 0 else None
        ref = dict(word_offset=at, reference_index=index, reference_hash=f'0x{key:08x}', raw_flags=flags)
        if record is not None and at+4 <= record['data_offset']+record['byte_length']:
            ref.update(source_hash=record['name_hash'], relative_offset=at-record['data_offset'])
            queue(own, record, 0)
        else:
            ref['placement'] = 'not_contained_in_one_index_span'
        incoming.append(ref)
    while pending:
        resource, record, depth = pending.popleft()
        source = dict(family=resource['raw_family'], source_sha256=resource['sha256'],
            source_offset=resource['source']['offset'], name_hash=record['name_hash'],
            data_offset=record['data_offset'], indexed_span_bytes=record['byte_length'],
            raw_kind_u8=record['raw_kind_u8'], name=record['name'], name_status=record['name_status'])
        node = dict(source, depth=depth)
        context = contexts.get(resource['sha256'])
        if context is None:
            node.update(reference_status='not_inspected', reason='no supported relocation directory for this resource')
            nodes.append(node)
            continue
        try:
            links = _references(context, record, consume)
        except audio_config.ConfigLimitError:
            raise
        except ValueError as exc:
            node.update(reference_status='refused', reason=str(exc))
            nodes.append(node)
            continue
        node['reference_status'] = 'listed_words_inspected'
        nodes.append(node)
        for ref in links:
            family = _FAMILIES.get(ref['raw_flags'])
            matches = candidates.get((family, int(ref['reference_hash'], 16)), []) if family is not None else []
            consume(1+len(matches))
            edge = dict(source=source, **ref, target_candidates=[])
            edge['status'] = ('unsupported_flags' if family is None else 'missing_family_key' if not matches
                              else 'unique_hash_candidate' if len(matches) == 1 else 'ambiguous_hash_candidates')
            for target_resource, target in matches:
                follow = 'depth_limit' if depth >= MAX_DEPTH else ('queued_candidate' if queue(target_resource, target, depth+1) else 'already_seen')
                edge['target_candidates'].append(dict(family=family, source_sha256=target_resource['sha256'],
                    source_offset=target_resource['source']['offset'], name_hash=target['name_hash'],
                    data_offset=target['data_offset'], indexed_span_bytes=target['byte_length'],
                    raw_kind_u8=target['raw_kind_u8'], name=target['name'], name_status=target['name_status'], follow_status=follow))
            edges.append(edge)
    return dict(records=nodes, edges=edges, incoming_root_references=incoming,
        max_follow_depth=MAX_DEPTH, interpretation='namespace-qualified full32 key candidates only; no provider priority, recording identity or station membership assigned')


def inspect_file(path, *, _profile_hook=None, _graph_hook=None, max_aux_entries=1000000, **kwargs):
    """Add family61 roots selected by the current target graph's flag-4 symbols."""
    contexts, symbols = {}, set()

    def capture(directory, targets, consume):
        profiles = (_profile_hook or audio_config_providers.enrich)(directory, targets, consume)
        contexts[directory.summary['source_sha256']] = directory
        symbols.update(int(s['reference_hash'], 16) for s in profiles['provider_symbols'] if s['raw_flags'] == 4)
        return profiles

    report = audio_config_references.inspect_file(path, _profile_hook=capture, max_aux_entries=max_aux_entries, **kwargs)
    remaining = kwargs.get('max_nodes', 100000)-report['summary']['nodes']
    consume_aux, aux_used = audio_config._budget(max_aux_entries)
    consume_aux(report['summary']['auxiliary_entries_charged'])
    extra_nodes = extra_aux = roots_count = edges_count = 0
    for resource in report['resources']:
        if resource['raw_family'] != 61:
            continue
        consume, used = audio_config._budget(max(1, remaining))
        try:
            if remaining < 1:
                raise audio_config.ConfigLimitError('kind27 links exceed shared node budget')
            data = audio_config_sections._read_source(path, resource['source'])
            directory = parse(data, max_nodes=remaining, max_aux_entries=max_aux_entries, _aux_budget=(consume_aux, aux_used))
            consume(directory.nodes)
            contexts[resource['sha256']] = directory
            keys = set()
            for at in directory.locations:
                index, = struct.unpack_from('<I', data, at)
                key, flags = directory.rows[index]
                if flags == 4 and key in symbols:
                    keys.add(at)
            ordered = sorted(directory.records.values(), key=lambda r: r['data_offset'])
            starts = [r['data_offset'] for r in ordered]
            selected = {}
            for at in sorted(keys):
                ordinal = bisect_right(starts, at)-1
                if ordinal >= 0:
                    record = ordered[ordinal]
                    if record['raw_kind_u8'] == 0x27 and at+4 <= record['data_offset']+record['byte_length']:
                        selected[int(record['name_hash'], 16)] = record
            roots, valid = [], set()
            for key, record in selected.items():
                consume()
                try:
                    roots.append(profile27(directory, record, consume))
                    valid.add(key)
                except audio_config.ConfigLimitError:
                    raise
                except ValueError as exc:
                    roots.append(dict(status='refused', name_hash=record['name_hash'], reason=str(exc)))
            graph = _trace(directory, valid, contexts, report['resources'], resource, consume)
            view = dict(status='partial' if len(valid) != len(selected) or any(n.get('reference_status') == 'refused' for n in graph['records']) else 'parsed',
                directory=directory.summary, roots=roots, graph=graph,
                summary=dict(selected_kind27_records=len(selected), profiled_kind27_records=len(valid),
                    graph_records=len(graph['records']), graph_reference_words=len(graph['edges']),
                    incoming_root_references=len(graph['incoming_root_references'])))
            if _graph_hook is not None:
                view['downstream_symbols'] = _graph_hook(graph, contexts, report['resources'], consume)
                if view['downstream_symbols']['status'] != 'parsed':
                    view['status'] = 'partial'
        except (OSError, ValueError) as exc:
            resource['kind27_links'] = dict(status='refused', roots=[], reason=str(exc))
            report['status'] = 'partial'
            if isinstance(exc, audio_config.ConfigLimitError):
                remaining = 0
                report['summary']['reference_budget_exhausted'] = True
            continue
        resource['kind27_links'] = view
        cost = used()
        remaining -= cost
        extra_nodes += cost
        extra_aux += directory.summary['validated_aux_entries']
        roots_count += len(valid)
        edges_count += len(graph['edges'])
        if view['status'] != 'parsed':
            report['status'] = 'partial'
    report['summary']['nodes'] += extra_nodes
    report['summary']['auxiliary_entries_validated'] += extra_aux
    report['summary']['auxiliary_entries_charged'] = aux_used()
    report['summary'].update(profiled_kind27_records=roots_count, kind27_graph_reference_words=edges_count)
    return report
