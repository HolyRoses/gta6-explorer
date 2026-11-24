"""Counted value storage and complete opaque four-byte primitive-pool coverage.

Only checked container entries and directly reached declarations participate.
Payloads and keys are never decoded; numeric/hash meanings remain unknown.
Declarations and links must be fresh same-source reader output; persisted
arbitrary JSON is not authenticated by this helper.
"""
from __future__ import annotations

from collections import defaultdict
import struct

from . import world_containers

PROFILE = 'world_0drp_counted_values_complete_four_byte_pools_v1'


def inspect(data, structures, blocks, *, links, consume):
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    charge()
    containers = world_containers.inspect(data, structures, blocks, links=links,
                                          consume=charge, with_descendants=True)
    definitions = defaultdict(list)
    for s in structures:
        charge()
        definitions[s['hash']].append(s)
    rows, entry_sources, physical, ranges = [], [], {}, defaultdict(list)
    counts = dict(value_headers=0, entry_value_headers=0, direct_value_headers=0,
                  null_headers=0, primitive_pool_ranges=0, primitive_pool_groups=0)

    def sequence(at, leaf, source):
        charge()
        if at in physical:
            row = rows[physical[at]]
            if row['raw_type'] != f'0x{leaf:08x}':
                raise ValueError('value slot has conflicting local primitive descriptors')
            row['incidences'] += 1
            if 'entry_source_index' in source:
                charge();row.setdefault('entry_source_indices', []).append(source['entry_source_index'])
            return
        if not 80 <= at <= len(data) - 16:
            raise ValueError('counted value header escapes its source')
        a, b, word = struct.unpack_from('<IIQ', data, at)
        index = len(rows)
        row = dict(source, source_data_offset=at, raw_type=f'0x{leaf:08x}',
                   count=a, reference_bits=f'0x{word:016x}', incidences=1,
                   element_bytes=None, byte_length=None)
        if 'entry_source_index' in row:
            row['entry_source_indices'] = [row.pop('entry_source_index')]
        if (a, b, word) == (0, 0, 0):
            row.update(status='null', target=None);counts['null_headers'] += 1
        else:
            if not a or a != b or not word:
                raise ValueError('counted value requires equal positive counts and a nonnull reference')
            number, offset = word & 0xfffff, word >> 20
            if not 1 <= number <= len(blocks):
                raise ValueError('counted value has an invalid local primitive block number')
            target = blocks[number - 1]
            if target['type_hash'] != f'0x{leaf:08x}' or definitions.get(target['type_hash']):
                raise ValueError('counted value target is not an unambiguous matching intrinsic pool')
            if (not target['byte_length'] or target['byte_length'] % 4 or offset % 4
                    or offset > target['byte_length'] or a > (target['byte_length'] - offset) // 4):
                raise ValueError('counted value does not select a bounded four-byte-aligned pool candidate')
            charge()
            row.update(status='coverage_unresolved', target=dict(block_index=number - 1,
                byte_offset=offset, data_offset=target['data_offset'] + offset))
            ranges[number - 1].append((offset, offset + a * 4, index))
        physical[at] = index;rows.append(row)
        counts['value_headers'] += 1
        counts['entry_value_headers' if source['source_kind'] == 'container_entry' else 'direct_value_headers'] += 1

    for container in containers['containers']:
        if container['target'] is None:
            continue
        target = container['target'];entry = containers['entry_layouts'][container['entry_layout_index']]
        specification = containers['layouts'][container['layout_index']]
        leaf = specification['value_descriptor_tree'][2][0]
        charge()
        si = len(entry_sources)
        entry_sources.append(dict(source_block_index=container['source_block_index'],
            source_record_index=container['source_record_index'], source_data_offset=container['source_data_offset'],
            field_index=specification['field_index'], target=dict(target)))
        for ri in range(target['record_count']):
            sequence(target['data_offset'] + ri * entry['stride'] + entry['value_offset'], leaf,
                dict(source_kind='container_entry', source_block_index=target['block_index'],
                     source_record_index=target['record_index'] + ri, field_index=entry['value_field_index'],
                     entry_source_index=si))
    for owner_range in containers['owner_ranges']:
        if owner_range.get('scope') != 'counted_descendant':
            continue
        block = blocks[owner_range['block_index']];owner = definitions[block['type_hash']][0]
        for fi, field in enumerate(owner['fields']):
            charge()
            name, offset, word, auxiliary = field;di = word >> 16
            if name == 0x100 or word & 0xffff != 0x5c or di == fi or di >= len(owner['fields']):
                continue
            descriptor = owner['fields'][di]
            if descriptor[:3] not in ([0x100, 0, 0x4a], [0x100, 0, 0x14]):
                continue
            others = [f[1] for i, f in enumerate(owner['fields']) if i != fi and f[0] != 0x100]
            end = min([v for v in others if v > offset] + [owner['byte_size']])
            if auxiliary or descriptor[3] or offset >= owner['byte_size'] or offset in others or end - offset != 16:
                raise ValueError('direct primitive sequence lacks a unique exact16Bslot')
            for ri in range(owner_range['record_count']):
                sequence(block['data_offset'] + ri * owner_range['stride'] + offset, descriptor[2],
                    dict(source_kind='direct_counted', source_block_index=block['index'],
                         source_record_index=ri, field_index=fi))
    pools = []
    for bi, spans in sorted(ranges.items()):
        charge(1 + len(spans));block = blocks[bi];cursor = covered = 0;gaps = [];overlaps = 0
        for start, end, _ in sorted(spans):
            charge()
            if start > cursor:
                charge();gaps.append(dict(byte_offset=cursor, byte_length=start - cursor))
            elif start < cursor:
                overlaps += 1
            covered += max(0, end - max(cursor, start));cursor = max(cursor, end)
        if cursor < block['byte_length']:
            charge();gaps.append(dict(byte_offset=cursor, byte_length=block['byte_length'] - cursor))
        complete = not gaps and not overlaps
        pi = len(pools)
        pools.append(dict(block_index=bi, raw_type=block['type_hash'], data_offset=block['data_offset'],
            byte_length=block['byte_length'], source_ranges=len(spans), covered_bytes=covered,
            status='complete_disjoint' if complete else 'coverage_unresolved',
            element_bytes=4 if complete else None, group_count=block['byte_length'] // 4 if complete else None,
            gaps=gaps, overlapping_ranges=overlaps,
            interpretation='Opaque storage groups only; numeric type, signedness and hash meanings unknown'))
        if complete:
            counts['primitive_pool_groups'] += block['byte_length'] // 4
        for _, _, index in spans:
            charge()
            row = rows[index];row['pool_index'] = pi
            if complete:
                row.update(status='primitive_pool_range', element_bytes=4, byte_length=row['count'] * 4)
                counts['primitive_pool_ranges'] += 1
    counts.update(nodes=used, pools=len(pools), unresolved_pools=sum(p['status'] != 'complete_disjoint' for p in pools),
                  unresolved_value_headers=sum(r['status'] == 'coverage_unresolved' for r in rows),
                  entry_range_sources=len(entry_sources))
    result = dict(status='partial' if counts['value_headers'] else 'unsupported', profile=PROFILE,
                summary=counts, entry_sources=entry_sources,
                owner_ranges=containers['owner_ranges'], container_scope_summary=containers['summary'],
                sequences=rows, pools=pools,
                unsupported_fields=containers['unsupported_fields'],
                unsupported_owner_ranges=containers.get('unsupported_owner_ranges', []),
                offset_space='decompressed same-source 0DRP bytes and existing local records',
                interpretation='Checked counted-value storage only; full disjoint pool coverage is required for '
                               'four-byte grouping. Keys, primitive payload values, model IDs and semantic ownership remain unknown.')
    if not counts['value_headers']:
        result['reason'] = containers.get('reason', 'no supported counted value or direct primitive slot is reached')
    return result
