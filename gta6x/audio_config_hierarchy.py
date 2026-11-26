"""Stored config hash trees and conservative named-slot target candidates.

The hierarchy is structurally checked. Slot words join complete 32-bit keys;
their reference semantics and category names remain unconfirmed. Neither view
establishes station membership, playback order or an intro-to-song pairing.
"""
from __future__ import annotations

import struct
from collections import defaultdict

from . import audio_config, audio_config_parameters, audio_config_sections


def parse(data: bytes, *, max_nodes=100000):
    """Read the measured family-41 counted suffix and require one closed tree."""
    consume, used = audio_config._budget(max_nodes)
    view = audio_config.parse_index(data, max_nodes=max_nodes)
    consume(view['nodes'])
    if view['raw_family'] != 41:
        raise ValueError('config hash hierarchy requires family 41')
    rows = []
    for record in view['records']:
        at, size = record['data_offset'], record['byte_length']
        if record['raw_kind_u8'] != 0 or size < 78:
            raise ValueError('unsupported config hierarchy record prefix/extent')
        count = data[at+77]
        if size != 78+4*count:
            raise ValueError('config hierarchy child count does not exhaust record')
        consume(1+count)
        children = [f'0x{struct.unpack_from("<I", data, at+78+4*i)[0]:08x}' for i in range(count)]
        rows.append(dict(name_hash=record['name_hash'], data_offset=at, byte_length=size,
            opaque_prefix_hex=data[at:at+77].hex(), child_count=count, child_hashes=children))
    by_key = {r['name_hash']: r for r in rows}
    parents = {}
    for row in rows:
        for child in row['child_hashes']:
            if child not in by_key:
                raise ValueError('config hierarchy child is outside local index')
            if child in parents:
                raise ValueError('config hierarchy child has duplicate/multiple parents')
            parents[child] = row['name_hash']
    roots = set(by_key)-set(parents)
    if len(roots) != 1:
        raise ValueError('config hierarchy requires one root')
    root, = roots
    visited = set(); pending = [root]
    while pending:
        key = pending.pop()
        if key in visited:
            raise ValueError('cycle in config hash hierarchy')
        visited.add(key); pending.extend(by_key[key]['child_hashes'])
    if len(visited) != len(rows):
        raise ValueError('config hierarchy contains unreachable records or a cycle')
    return dict(status='parsed', source_sha256=view['sha256'], root_hash=root,
        records=rows, record_count=len(rows), edge_count=len(parents), nodes=used(),
        interpretation='stored rooted hash tree; category names and runtime meaning unconfirmed')


def slot_words(data: bytes, name_table: bytes, *, max_nodes=100000):
    """Expose +32 words only from the exact checked/listed 44-byte slot profile."""
    consume, used = audio_config._budget(max_nodes)
    if not isinstance(name_table, bytes) or not 0 < len(name_table) <= audio_config.MAX_RESOURCE:
        raise ValueError('invalid slot name table')
    view = audio_config.parse_index(data, max_nodes=max_nodes); consume(view['nodes'])
    consume(len(view['records']))
    named = audio_config.attach_names(view, data, name_table)
    if named is None:
        raise ValueError('slot words require complete checked family-26 names')
    view['records'] = named
    slots = audio_config.wave_slot_list(view, data, consume=consume)
    if slots['status'] != 'complete':
        raise ValueError('slot words require the complete checked wave-slot list')
    rows = []
    for record in named:
        if record['raw_kind_u8'] != 8:
            continue
        at = record['data_offset']
        if record['byte_length'] != 44 or data[at+4:at+8] != b'\xaa'*4:
            raise ValueError('unsupported named slot record profile')
        consume()
        word, = struct.unpack_from('<I', data, at+32)
        rows.append(dict(name_hash=record['name_hash'], name=record['name'],
            data_offset=at, word_offset=at+32, target_hash=f'0x{word:08x}'))
    return dict(status='parsed', source_sha256=view['sha256'], records=rows, nodes=used())


def inspect_file(path, *, index_sections=False, parameters=False, **kwargs):
    """Add exact trees and all slot/key candidates; preserve missing/ambiguous targets."""
    if parameters:
        report = audio_config_parameters.inspect_file(path, index_sections=index_sections, **kwargs)
    else:
        reader = audio_config_sections if index_sections else audio_config
        report = reader.inspect_file(path, **kwargs)
    remaining = kwargs.get('max_nodes', 100000)-report['summary']['nodes']
    targets = defaultdict(list); total_edges = 0; total_trees = 0
    for resource in report['resources']:
        if resource['raw_family'] != 41:
            continue
        try:
            if remaining < 1:
                raise audio_config.ConfigLimitError('config hierarchy exceeds node budget')
            data = audio_config_sections._read_source(path, resource['source'])
            tree = parse(data, max_nodes=remaining)
        except (OSError, ValueError) as exc:
            resource['hash_hierarchy'] = dict(status='refused', records=[], reason=str(exc))
            report['status'] = 'partial'
            if isinstance(exc, audio_config.ConfigLimitError):remaining = 0
            continue
        cost = tree.pop('nodes'); remaining -= cost; report['summary']['nodes'] += cost
        resource['hash_hierarchy'] = tree; total_trees += 1; total_edges += tree['edge_count']
        for row in tree['records']:
            targets[row['name_hash']].append(dict(source_sha256=tree['source_sha256'],
                source_offset=resource['source']['offset'],
                data_offset=row['data_offset'], name_hash=row['name_hash']))
    total_slots = 0; matched_slots = 0; ambiguous_slots = 0
    for resource in report['resources']:
        if resource['raw_family'] != 26 or 'name_table_source' not in resource:
            continue
        try:
            if remaining < 1:
                raise audio_config.ConfigLimitError('config slot candidates exceed node budget')
            data = audio_config_sections._read_source(path, resource['source'])
            table = audio_config_sections._read_source(path, resource['name_table_source'])
            slots = slot_words(data, table, max_nodes=remaining)
            # Charge every candidate before publishing any result for this resource.
            cost = slots['nodes'] + sum(len(targets.get(r['target_hash'], [])) for r in slots['records'])
            if cost > remaining:
                raise audio_config.ConfigLimitError('config slot candidate expansion exceeds node budget')
        except (OSError, ValueError) as exc:
            resource['slot_target_candidates'] = dict(status='refused', records=[], reason=str(exc))
            report['status'] = 'partial'
            if isinstance(exc, audio_config.ConfigLimitError):remaining = 0
            continue
        slots.pop('nodes'); remaining -= cost; report['summary']['nodes'] += cost
        for row in slots['records']:
            candidates = targets.get(row['target_hash'], [])
            row.update(target_candidates=list(candidates),
                status='unresolved' if not candidates else 'hash_candidate' if len(candidates)==1 else 'ambiguous_hash_candidates')
            total_slots += 1; matched_slots += bool(candidates); ambiguous_slots += len(candidates)>1
        slots['interpretation'] = 'full32 key candidates only; no reference semantics or station/song links assigned'
        resource['slot_target_candidates'] = slots
    report['summary'].update(hash_hierarchies=total_trees, hierarchy_edges=total_edges,
        checked_slot_words=total_slots, slots_with_hierarchy_candidates=matched_slots,
        slots_with_ambiguous_hierarchy_candidates=ambiguous_slots)
    return report
