"""Relocation-listed family-581 reference indices and conservative local bindings.

Only words explicitly listed by the auxiliary directory are treated as indices.
Flags retain their native bits; the measured flag-1/local-hash binding profile
does not establish sound types, station membership or external namespaces.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter
import struct

from . import audio_config, audio_config_maps, audio_config_sections

MAX_AUX_ENTRIES = 1000000


class Directory:
    def __init__(self, data, view, rows, locations, aliases, summary, nodes):
        self.data = data
        self.records = {int(r['name_hash'], 16): r for r in view['records']}
        self.rows = rows
        self.locations = locations
        self.aliases = aliases
        self.summary = summary
        self.nodes = nodes
        self.data_start = view['data_region']['data_offset']
        self.data_end = self.data_start + view['data_region']['byte_length']

    def resolve_at(self, offset):
        """Re-read a native word; an in-range integer alone is never sufficient."""
        if type(offset) is not int or not self.data_start <= offset <= self.data_end-4:
            raise ValueError('reference word escapes config data region')
        value, = struct.unpack_from('<I', self.data, offset)
        where = bisect_left(self.locations, offset)
        if where == len(self.locations) or self.locations[where] != offset:
            return dict(status='not_listed', word_offset=offset,
                        raw_value_u32=value, raw_value_bits=f'0x{value:08x}')
        key, flags = self.rows[value]
        result = dict(status='listed_reference', word_offset=offset,
            reference_index=value, reference_hash=f'0x{key:08x}', raw_flags=flags)
        if flags != 1:
            result['binding_status'] = 'unsupported_flags'
        elif key not in self.records:
            result['binding_status'] = 'missing_local_key'
        else:
            record = self.records[key]
            result['binding_status'] = 'local_hash_match'
            result['local_target'] = dict(name_hash=record['name_hash'],
                data_offset=record['data_offset'], indexed_span_bytes=record['byte_length'],
                raw_kind_u8=record['raw_kind_u8'],
                alternate_key_u64=f"0x{self.aliases[record['data_offset']-8]:016x}")
        return result

    def within_span(self, target, *, _consume=None):
        """Listed words inside an index upper-bound span; object ownership is unproven."""
        start = target['data_offset']; end = start + target['indexed_span_bytes']
        a, b = bisect_left(self.locations, start), bisect_left(self.locations, end)
        while b > a and self.locations[b-1]+4 > end:b -= 1
        if _consume is not None:_consume(1+b-a)
        return [self.resolve_at(self.locations[i]) for i in range(a,b)]


def parse(data: bytes, *, max_nodes=100000, max_aux_entries=MAX_AUX_ENTRIES, _aux_budget=None):
    """Validate the complete measured auxiliary suffix, including every listed word.

    Dense table validation has a separate aggregate entry limit. The node
    budget covers the index view and returned trace nodes, not serialized
    expansion of the dense arrays (which are kept private).
    """
    consume, used = audio_config._budget(max_nodes)
    own_aux = audio_config._budget(max_aux_entries)
    consume_aux, aux_used = own_aux if _aux_budget is None else _aux_budget
    aux_before = aux_used()
    view = audio_config_sections.parse_index(data, max_nodes=max_nodes)
    consume(view['nodes'])
    at = view['opaque_tail']['data_offset']; descriptors = []
    data_start = view['data_region']['data_offset']
    data_end = data_start + view['data_region']['byte_length']

    def table(width, label):
        nonlocal at
        if at+4 > len(data):raise ValueError('truncated config auxiliary '+label)
        count, = struct.unpack_from('<I', data, at)
        if count > (len(data)-at-4)//width:
            raise ValueError('config auxiliary '+label+' count escapes source')
        consume_aux(count)
        begin = at+4; end = begin+count*width
        descriptors.append(dict(role=label, data_offset=at, count=count,
                                entry_bytes=width, byte_length=end-at))
        at = end
        return begin, count

    begin, count = table(12, 'alternate_index')
    if count != len(view['records']):raise ValueError('alternate index count differs from primary index')
    relative = {r['data_offset']-8 for r in view['records']}
    aliases = {}; keys64 = set()
    for i in range(count):
        key, offset = struct.unpack_from('<QI', data, begin+12*i)
        if offset not in relative or offset in aliases or key in keys64:
            raise ValueError('alternate index is not a bijection of primary storage starts')
        aliases[offset] = key; keys64.add(key)
    if at+8 > len(data) or data[at:at+8] != bytes(8):
        raise ValueError('unsupported auxiliary zero-word profile')
    zero_at = at; at += 8
    begin, count = table(4, 'opaque_offset_array')
    previous = -1
    for i in range(count):
        value, = struct.unpack_from('<I', data, begin+4*i)
        if not previous < value <= data_end-4 or value < data_start:
            raise ValueError('opaque auxiliary offsets are unordered or out of bounds')
        previous = value
    begin, count = table(8, 'reference_entries')
    rows = [struct.unpack_from('<II', data, begin+8*i) for i in range(count)]
    begin, count = table(4, 'reference_word_locations')
    locations = []; previous = -1
    for i in range(count):
        location, = struct.unpack_from('<I', data, begin+4*i)
        if not previous < location <= data_end-4 or location < data_start:
            raise ValueError('reference locations are unordered or outside data')
        index, = struct.unpack_from('<I', data, location)
        if index >= len(rows):raise ValueError('listed reference index escapes entry directory')
        previous = location; locations.append(location)
    if at != len(data):raise ValueError('unclaimed bytes after config reference directories')
    local_keys = {int(r['name_hash'], 16) for r in view['records']}
    flags = Counter(flag for key, flag in rows)
    summary = dict(status='parsed', source_sha256=view['sha256'], tables=descriptors,
        opaque_zero_words_offset=zero_at, validated_aux_entries=aux_used()-aux_before,
        reference_entries=len(rows), listed_reference_words=len(locations),
        flag_counts={f'0x{k:08x}':v for k,v in sorted(flags.items())},
        flag1_local_key_entries=sum(flag==1 and key in local_keys for key,flag in rows),
        flag1_missing_key_entries=sum(flag==1 and key not in local_keys for key,flag in rows),
        interpretation='listed words index the reference entry table; flags and external namespaces remain raw')
    return Directory(data, view, rows, locations, aliases, summary, used())


def trace_maps(data: bytes, *, key_hash=None, max_nodes=100000, max_aux_entries=MAX_AUX_ENTRIES,
               _aux_budget=None, _profile_hook=None):
    """Trace validated map value locations, keeping unsupported flags/keys unresolved."""
    consume, used = audio_config._budget(max_nodes)
    directory = parse(data, max_nodes=max_nodes, max_aux_entries=max_aux_entries, _aux_budget=_aux_budget)
    consume(directory.nodes)
    if max_nodes-used() < 1:
        raise audio_config.ConfigLimitError('reference trace has no map-validation node budget')
    maps = audio_config_maps.parse(data, key_hash=key_hash, max_nodes=max_nodes-used())
    consume(maps['nodes'])
    wanted = maps['selected_key_hash']; results = []; targets = {}
    for row in maps['records']:
        for pair in row['entries']:
            if wanted is not None and pair['key_hash'] != wanted:continue
            consume()
            result = directory.resolve_at(pair['value_offset'])
            result.update(map_hash=row['name_hash'], map_offset=row['data_offset'], key_hash=pair['key_hash'])
            target = result.get('local_target')
            if target and target['name_hash'] not in targets:
                occurrences = directory.within_span(target, _consume=consume)
                targets[target['name_hash']] = dict(target,
                    span_reference_occurrences=occurrences,
                    ownership='listed words within an index upper-bound span; exact object extent unconfirmed')
            results.append(result)
    result = dict(status='parsed', directory=directory.summary, selected_key_hash=wanted,
        map_value_traces=results, local_targets=list(targets.values()), nodes=used(),
        summary=dict(traced_map_words=len(results),
            listed_map_words=sum(r['status']=='listed_reference' for r in results),
            local_map_bindings=sum(r.get('binding_status')=='local_hash_match' for r in results),
            distinct_local_targets=len(targets)),
        interpretation='relocation-backed indices and measured flag-1 local hash matches; no recording/station roles assigned')
    if _profile_hook is not None:
        result['target_profiles'] = _profile_hook(directory,list(targets.values()),consume)
        result['nodes'] = used()
    return result


def inspect_file(path, *, key_hash=None, slot_hierarchy=False, parameters=False,
                 max_aux_entries=MAX_AUX_ENTRIES, _profile_hook=None, **kwargs):
    # Validate the separate dense-scan limit before source reads.
    aux_budget = audio_config._budget(max_aux_entries)
    report = audio_config_maps.inspect_file(path, key_hash=key_hash,
        slot_hierarchy=slot_hierarchy, parameters=parameters, **kwargs)
    remaining = kwargs.get('max_nodes',100000)-report['summary']['nodes']
    total = listed = bindings = aux_total = 0
    exhausted = False
    for resource in report['resources']:
        if resource['raw_family'] != 581:continue
        try:
            if remaining < 1:raise audio_config.ConfigLimitError('reference trace exceeds node budget')
            if aux_budget[1]() >= max_aux_entries:raise audio_config.ConfigLimitError('reference auxiliary entry budget exhausted')
            data = audio_config_sections._read_source(path, resource['source'])
            trace = trace_maps(data, key_hash=key_hash, max_nodes=remaining,
                max_aux_entries=max_aux_entries, _aux_budget=aux_budget, _profile_hook=_profile_hook)
        except (OSError, ValueError) as exc:
            resource['reference_trace'] = dict(status='refused', map_value_traces=[], reason=str(exc))
            report['status'] = 'partial'
            if isinstance(exc,audio_config.ConfigLimitError):
                remaining = 0; exhausted = True
            continue
        cost = trace.pop('nodes'); remaining -= cost; report['summary']['nodes'] += cost
        resource['reference_trace'] = trace
        if trace.get('target_profiles',{}).get('status','parsed') != 'parsed':report['status'] = 'partial'
        aux_count = trace['directory']['validated_aux_entries']
        aux_total += aux_count
        total += trace['summary']['traced_map_words']; listed += trace['summary']['listed_map_words']
        bindings += trace['summary']['local_map_bindings']
    report['summary'].update(traced_map_words=total, listed_map_reference_words=listed,
        local_map_hash_bindings=bindings, auxiliary_entries_validated=aux_total,
        auxiliary_entries_charged=aux_budget[1](), reference_budget_exhausted=exhausted)
    return report
