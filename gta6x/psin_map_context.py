"""Source-checked context for selected existing local PSIN maps.

This replays the native map-entry association grammar; it adds no map profile,
key decoding, application role or asset binding. Inputs are fresh same-source
reader objects, not authenticated persisted JSON reports.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import struct

from . import psin_field_context, psin_maps, psin_schema
from .psin_blocks import parse_blocks

PROFILE = 'local_psin_selected_map_context_v1'
MAX_ENTRIES = 4096


def inspect(data, schema, instances, queries, *, consume, max_depth=16):
    """Inspect <=32 embedded-only field paths with one shared source session.

    Unknown paths and unsupported map profiles remain unresolved. Source/view
    disagreements, work failures or the aggregate entry cap return no prefix.
    Entry links are copied only from the existing source-replayed map resolver;
    target values, key widths, semantic ownership and pointer graphs stay unknown.
    """
    psin_field_context._validate_queries(queries, max_depth, 0)
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('PSIN map context requires a local schema object')
    used = 0
    def charge(count=1):
        nonlocal used
        consume(count)
        used += count

    # Own the declaration snapshot before callbacks in subsequent source work.
    # The checked-source session reparses and compares it with the actual source.
    enums = schema.enum_table.definitions if schema.enum_table else []
    charge(1 + len(schema.structures) + sum(len(s.fields) for s in schema.structures)
           + len(enums) + sum(len(e.members) for e in enums))
    schema = deepcopy(schema)
    execute = psin_field_context._prepare(data, schema, instances, consume=charge,
        max_depth=max_depth, max_sample_bytes=0)
    contexts = execute(queries)
    charge(len(instances['blocks']))
    blocks = parse_blocks(data[:struct.unpack_from('>I', data, 4)[0]])
    structures = psin_schema._index(schema.structures)
    enums = psin_schema._index(schema.enum_table.definitions)
    target_hashes = {}
    output = []; entries = resolved = 0
    for context in contexts['queries']:
        charge()
        item = dict(block_index=context['block_index'],record_index=context['record_index'],
                    field_path=context['field_path'],status='unresolved',source_context=context,
                    application_semantics='unknown',semantic_owner='unknown')
        output.append(item)
        if context['status'] != 'resolved':
            item['reason'] = context['reason']; continue
        field = context['field']
        if field['type_word'] != '0x00000071' or field['type_name'] != 'map':
            item['reason'] = 'selected field is not an existing locally declared map'; continue
        owners = structures.get(int(field['owner_hash'],16), [])
        if len(owners) != 1:
            raise ValueError('PSIN map context requires a unique local owning declaration')
        owner = owners[0]
        selected = owner.fields[context['field_path'][-1]]
        start = field['source_slot']['data_offset']
        count = struct.unpack_from('<H',data,start+16)[0]
        if count > MAX_ENTRIES-entries:
            raise ValueError('PSIN map context exceeds its 4096-entry report limit')
        charge(1 + len(owner.fields))
        # The existing resolver may scan enum members for representability
        # and again to build the map-key membership set. Repeated queries
        # repeat that work even though source/schema verification is cached.
        descriptor_indices = (selected.auxiliary & 0xffff, selected.auxiliary >> 16)
        for di in descriptor_indices:
            if di < len(owner.fields):
                descriptor = owner.fields[di]
                if descriptor.type_word == 0x62:
                    charge(2 * sum(len(e.members) for e in enums.get(descriptor.auxiliary, [])))
        block = blocks[context['block_index']]
        mapping = psin_maps.resolve_entries(data,start,selected,owner,
            block.data_offset+block.byte_length,blocks,local_owner=True,
            local_structures=structures,local_enums=enums,consume=charge)
        record = instances['blocks'][context['block_index']]['records'][context['record_index']]
        for index in context['field_path'][:-1]:
            charge()
            record = record['fields'][index]['value']
        existing = record['fields'][context['field_path'][-1]].get('map')
        # Fresh replays preserve empty/unresolved profiles and their exact reason.
        # Any changed header/target/entry metadata is a source-view disagreement.
        charge(1 + len(mapping['entries']))
        if existing != mapping:
            raise ValueError('PSIN map context instance association differs from source replay')
        target = mapping.get('target')
        if mapping['status'] == 'complete' and target is not None:
            bi = target['block_index']; source_block = blocks[bi]
            if bi not in target_hashes:
                charge(1 + (source_block.byte_length+4095)//4096)
                target_hashes[bi] = hashlib.sha256(memoryview(data)[
                    source_block.data_offset:source_block.data_offset+source_block.byte_length]).hexdigest()
            block_row = instances['blocks'][bi]
            expected = dict(index=bi,table_offset=source_block.table_offset,
                type_hash=f'0x{source_block.type_hash:08x}',data_offset=source_block.data_offset,
                byte_length=source_block.byte_length,sha256=target_hashes[bi])
            if not isinstance(block_row,dict) or any(block_row.get(key) != value for key,value in expected.items()):
                raise ValueError('PSIN map context target block differs from source')
            count_rows = source_block.byte_length // mapping['stride']
            if (block_row.get('record_count') != count_rows or
                    not isinstance(block_row.get('records'),list) or len(block_row['records']) != count_rows):
                raise ValueError('PSIN map context target record stride differs from source')
            for link in mapping['entries']:
                charge()
                row = block_row['records'][link['record_index']]
                if not isinstance(row,dict) or any(row.get(key) != link[key] for key in ('data_offset','byte_length','structure_hash')):
                    raise ValueError('PSIN map context target record differs from source')
        item['mapping'] = mapping
        if mapping['status'] != 'complete':
            item['reason'] = mapping['reason']; continue
        entries += len(mapping['entries'])
        item['status'] = 'resolved'
        resolved += 1
    return dict(format='gta6x-psin-map-context-v1',profile=PROFILE,
        status='complete' if resolved == len(output) else 'partial',
        source_sha256=contexts['source_sha256'],schema_id=contexts['schema_id'],
        max_depth=max_depth,
        queries=output,
        summary=dict(nodes=used,requested=len(output),resolved=resolved,
                     unresolved=len(output)-resolved,map_entries=entries,asset_bindings=0),
        interpretation='Selected existing local map-entry associations only; key width, values, semantic owners, native map roles and asset bindings are not established.')
