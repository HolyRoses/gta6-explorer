"""Source-local 0DRP container entry spans in guarded reachable records.

The raw key/value descriptors qualify storage only. Primitive types, keys,
lookup behavior, application ownership and model/asset meanings remain unknown.
Supplied declarations/links must be fresh same-source output of our readers.
"""
from __future__ import annotations

from collections import defaultdict
import struct

from . import world_links, world_owners

PROFILE = 'world_0drp_reachable_raw71_counted_value_entries_v1'


class _UnsupportedLayout(ValueError):
    """A declaration outside this profile, separate from caller budget errors."""


def _tree(owner, index, consume, active=()):
    consume(1)
    fields = owner['fields']
    if type(index) is not int or not 0 <= index < len(fields) or index in active or len(active) >= 8:
        raise _UnsupportedLayout('container descriptor index is outside its owner, cyclic or too deep')
    name, offset, word, auxiliary = fields[index]
    if name != 0x100 or offset:
        raise _UnsupportedLayout('container requires local synthetic descriptors at zero')
    if word in (0x4a, 0x14) and auxiliary == 0:
        return (word, 0)
    if word & 0xffff == 0x5c and auxiliary == 0:
        return (0x5c, 0, _tree(owner, word >> 16, consume, active + (index,)))
    raise _UnsupportedLayout('unsupported raw container descriptor')


def _layout(owner, fi, consume):
    name, offset, word, auxiliary = owner['fields'][fi]
    if name == 0x100 or word != 0x71:
        raise _UnsupportedLayout('unsupported named raw0x71 container attributes')
    others = [f[1] for i, f in enumerate(owner['fields']) if i != fi and f[0] != 0x100]
    end = min([v for v in others if v > offset] + [owner['byte_size']])
    if offset >= owner['byte_size'] or offset in others or end - offset != 24:
        raise _UnsupportedLayout('container requires a distinct exact 24-byte field slot')
    ki, vi = auxiliary & 0xffff, auxiliary >> 16
    if ki == vi or fi in (ki, vi):
        raise _UnsupportedLayout('container requires distinct local key/value descriptors')
    key, value = _tree(owner, ki, consume), _tree(owner, vi, consume)
    if key != (0x4a, 0) or value not in ((0x5c, 0, (0x4a, 0)), (0x5c, 0, (0x14, 0))):
        raise _UnsupportedLayout('unsupported container key/counted-value descriptor pair')
    return dict(field_index=fi, field_hash=f'0x{name:08x}', record_offset=offset,
                key_descriptor_index=ki, value_descriptor_index=vi,
                key_descriptor_tree=key, value_descriptor_tree=value)


def _entry_layout(entry, specification, consume):
    named = [(i, f) for i, f in enumerate(entry['fields']) if f[0] != 0x100]
    if entry['byte_size'] != 24 or len(named) != 2:
        raise ValueError('container requires a unique 24-byte two-member entry declaration')
    (ki, key), (vi, value) = sorted(named, key=lambda item: item[1][1])
    if key[1:] != [0, 0x4a, 0] or value[1] != 8 or value[2] & 0xffff != 0x5c or value[3]:
        raise ValueError('container entry member offsets/raw types differ')
    di = value[2] >> 16
    if di in (ki, vi) or (0x5c, 0, _tree(entry, di, consume)) != specification['value_descriptor_tree']:
        raise ValueError('container entry counted-value descriptor tree differs')
    return dict(key_field_index=ki, value_field_index=vi, key_offset=0, key_slot_bytes=8,
                value_offset=8, value_slot_bytes=16, stride=24,
                key_meaning='opaque storage; primitive width/type unconfirmed',
                value_meaning='declared counted slot; payload not decoded')


def inspect(data, structures, blocks, *, links, consume, with_descendants=False):
    """Return compact container-entry ranges, without expanding keys or values.

    Guarded incoming headers are source-revalidated. Their temporary subset is
    used only for validation, never exposed as a complete reference graph.
    Unsupported declarations are explicit. A malformed supported header refuses
    this whole view; its successful prefix is never returned.
    """
    if type(with_descendants) is not bool:
        raise ValueError('container descendant selection must be boolean')
    if (not isinstance(data, bytes) or not 80 <= len(data) <= world_links.MAX_BYTES
            or data[16:20] != b'0DRP' or struct.unpack_from('<I', data, 20)[0] != 122):
        raise ValueError('container links require bounded version-122 0DRP bytes')
    if (not isinstance(links, dict) or links.get('profile') != world_links.PROFILE
            or not isinstance(links.get('links'), list) or not isinstance(links.get('source_paths'), list)):
        raise ValueError('container links require fresh same-source counted links')
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    charge()
    candidates = []
    paths = links['source_paths']
    for row in links['links']:
        charge()
        pi = row.get('source_path_index')
        if type(pi) is not int or not 0 <= pi < len(paths):
            raise ValueError('container source path is outside its local table')
        path = paths[pi]
        if path.get('field_layout_profile') == world_links.GUARDED_40_PROFILE and path.get('target_stride') in (88, 80):
            candidates.append(row)
    if not candidates:
        return dict(status='unsupported', profile=PROFILE, owner_ranges=[], layouts=[], entry_layouts=[], containers=[],
                    unsupported_fields=[], summary=dict(nodes=used, containers=0, entry_ranges=0,
                                                       entry_record_observations=0),
                    reason='no guarded incoming range to an observed 88/80-byte declaration')
    # This validates declarations, paths, full guarded bytes and exact headers.
    world_owners.inspect(data, structures, blocks, consume=charge,
        links=dict(profile=world_links.PROFILE, links=candidates, source_paths=paths,
                   summary=dict(reference_ranges=len(candidates))))
    by_hash = defaultdict(list)
    for owner in structures:
        charge()
        by_hash[owner['hash']].append(owner)
    owners, by_block, unsupported_owners = [], {}, []
    for row in candidates:
        charge()
        block = blocks[row['target_block_index']]
        path = paths[row['source_path_index']]
        if row['target_record_index'] or row['count'] * path['target_stride'] != block['byte_length']:
            unsupported_owners.append(dict(source_data_offset=row['source_data_offset'],
                target_block_index=block['index'], reason='partial incoming owner ranges are outside the validated container profile'))
            continue
        incoming = dict(source_data_offset=row['source_data_offset'], source_path_index=row['source_path_index'])
        if block['index'] in by_block:
            charge()
            by_block[block['index']]['incoming_sources'].append(incoming)
            continue
        owner_range = dict(block_index=block['index'], stride=path['target_stride'], record_count=row['count'],
                           incoming_sources=[incoming])
        by_block[block['index']] = owner_range
        owners.append(owner_range)
    if with_descendants:
        # One independently observed hop only: whole guarded88Bowners to
        # declared184Brecords. Never scan unreferenced records to fill gaps.
        source_blocks = {r['block_index'] for r in owners if r['stride'] == 88}
        descendants = [r for r in links['links'] if r['source_block_index'] in source_blocks
                       and paths[r['source_path_index']].get('target_stride') == 184]
        charge(len(links['links']))
        if descendants:
            world_owners.inspect(data, structures, blocks, consume=charge,
                links=dict(profile=world_links.PROFILE, links=descendants, source_paths=paths,
                           summary=dict(reference_ranges=len(descendants))))
        grouped = defaultdict(list)
        for row in descendants:
            charge()
            grouped[row['target_block_index']].append(row)
        for bi, incoming_rows in sorted(grouped.items()):
            charge(1 + len(incoming_rows))
            block = blocks[bi];cursor = 0
            for row in sorted(incoming_rows, key=lambda r: r['target_record_index']):
                charge()
                if row['target_record_index'] > cursor:
                    break
                cursor = max(cursor, row['target_record_index'] + row['count'])
            else:
                if cursor * 184 == block['byte_length']:
                    owners.append(dict(block_index=bi, stride=184, record_count=cursor,
                        scope='counted_descendant', incoming_sources=[dict(source_data_offset=r['source_data_offset'],
                        source_path_index=r['source_path_index'], record_start=r['target_record_index'],
                        record_count=r['count']) for r in incoming_rows]))
                    continue
            unsupported_owners.append(dict(target_block_index=bi,
                reason='counted descendant ranges do not cover the complete184Brecord block'))
    layouts, entry_layouts, rows, unsupported = [], [], [], []
    entry_cache = {}
    counts = dict(containers=0, empty_containers=0, entry_ranges=0, entry_record_observations=0)
    for owner_range in owners:
        block = blocks[owner_range['block_index']]
        definitions = by_hash[block['type_hash']]
        if len(definitions) != 1:
            raise ValueError('container owner requires a unique local declaration')
        owner = definitions[0]
        for fi, field in enumerate(owner['fields']):
            charge()
            if field[0] == 0x100 or field[2] & 0xffff != 0x71:
                continue
            try:
                specification = _layout(owner, fi, charge)
            except _UnsupportedLayout as exc:
                unsupported.append(dict(source_block_index=block['index'], field_index=fi, reason=str(exc)))
                continue
            charge()
            li = len(layouts)
            layouts.append(dict(specification, owner_structure_hash=owner['hash'],
                                source_block_index=block['index']))
            for ri in range(owner_range['record_count']):
                charge()
                at = block['data_offset'] + ri * owner_range['stride'] + specification['record_offset']
                prefix, word, a, b, tail = struct.unpack_from('<QQHHI', data, at)
                if prefix != 1 or a != b or tail or (not a and word):
                    raise ValueError('container header requires leading one, equal u16 counts and zero tail/empty reference')
                common = dict(source_block_index=block['index'], source_record_index=ri,
                              source_data_offset=at, layout_index=li, count=a,
                              reference_bits=f'0x{word:016x}')
                counts['containers'] += 1
                if not a:
                    counts['empty_containers'] += 1
                    rows.append(dict(common, status='empty', target=None))
                    continue
                number, offset = word & 0xfffff, word >> 20
                if not 1 <= number <= len(blocks):
                    raise ValueError('container reference has an invalid local block number')
                target = blocks[number - 1]
                definitions = by_hash[target['type_hash']]
                if len(definitions) != 1:
                    raise ValueError('container entry declaration is missing or ambiguous')
                cache_key = target['type_hash'], specification['value_descriptor_tree']
                if cache_key not in entry_cache:
                    charge()
                    entry_cache[cache_key] = len(entry_layouts)
                    entry_layouts.append(dict(_entry_layout(definitions[0], specification, charge),
                                              structure_hash=target['type_hash']))
                ei = entry_cache[cache_key]
                entry = entry_layouts[ei]
                stride = entry['stride']
                if (not target['byte_length'] or target['byte_length'] % stride or offset % stride
                        or offset > target['byte_length'] or a > (target['byte_length'] - offset) // stride):
                    raise ValueError('container target is not a whole bounded declared entry range')
                charge(2)
                rows.append(dict(common, status='entry_record_range', entry_layout_index=ei,
                    target=dict(block_index=number - 1, record_index=offset // stride, record_count=a,
                                structure_hash=target['type_hash'], data_offset=target['data_offset'] + offset,
                                byte_length=a * stride)))
                counts['entry_ranges'] += 1
                counts['entry_record_observations'] += a
    counts.update(nodes=used, owner_ranges=len(owners), layouts=len(layouts), entry_layouts=len(entry_layouts),
                  unsupported_fields=len(unsupported), unsupported_owner_ranges=len(unsupported_owners))
    return dict(status='partial', profile=PROFILE, owner_ranges=owners, layouts=layouts,
                entry_layouts=entry_layouts, containers=rows, unsupported_fields=unsupported,
                unsupported_owner_ranges=unsupported_owners, summary=counts,
                offset_space='decompressed same-source 0DRP bytes and existing local typed records',
                interpretation='Container entry storage only; keys, counted value payloads, lookup semantics, '
                               'model IDs and semantic ownership unconfirmed. Counted-record ancestry is a separate view.')
