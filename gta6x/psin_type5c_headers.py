"""Source-checked opaque type5c header and local descriptor observations.

A clear declared-start slot bounds a sixteen-byte observation, not its value
width, reference meaning, element count or ownership. No record links are emitted.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import struct

from . import psin_field_context, psin_references, psin_schema
from .psin_blocks import parse_blocks

PROFILE = 'local_type5c_opaque_header_observations_v1'
MAX_HEADERS = 4096
MAX_OWNERS = 65536


def inspect(data, schema, instances, *, consume, max_depth=16):
    """Inspect named headers in locally tiled roots and bounded embedded owners.

    Native schema/instance objects must come from this source. Paths are replayed
    against source declarations; inline bucket owners are explicitly outside this
    inventory. Work/output exhaustion raises without returning a report prefix.
    """
    psin_field_context._validate_queries([], max_depth, 0)
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n)
        used += n
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('type5c headers require a local schema')
    charge(1+len(schema.structures)+sum(len(o.fields) for o in schema.structures))
    schema = deepcopy(schema)
    execute = psin_field_context._prepare(data, schema, instances, consume=charge,
        max_depth=min(64, max_depth+1), max_sample_bytes=0)
    source = execute([])
    # The preparation reparses and compares the schema before this local scan.
    charge(1+len(schema.structures)+sum(len(o.fields) for o in schema.structures))
    structures = psin_schema._index(schema.structures)
    blocks = parse_blocks(data[:struct.unpack_from('>I', data, 4)[0]])
    charge(len(blocks))
    expected_keys = ('index', 'table_offset', 'type_hash', 'data_offset', 'byte_length', 'sha256')
    source_blocks = []
    for block in blocks:
        charge(1+(block.byte_length+4095)//4096)
        expected = dict(index=block.index, table_offset=block.table_offset,
            type_hash=f'0x{block.type_hash:08x}', data_offset=block.data_offset,
            byte_length=block.byte_length,
            sha256=hashlib.sha256(memoryview(data)[block.data_offset:block.data_offset+block.byte_length]).hexdigest())
        row = instances['blocks'][block.index]
        if not isinstance(row, dict) or any(row.get(k) != expected[k] for k in expected_keys):
            raise ValueError('type5c header source block differs from instances')
        source_blocks.append(expected)
    pending, visited, refusals = [], set(), []
    alias_count = 0
    def refuse(reason):
        if reason not in refusals:
            charge(); refusals.append(reason)
    def walk(owner, at, root, path, depth, active):
        nonlocal alias_count
        charge()
        identity = owner.name_hash, at
        if identity in active:
            refuse('embedded cycle prevents complete owner inventory'); return
        if identity in visited:
            charge(); alias_count += 1; return
        if len(visited) >= MAX_OWNERS:
            raise ValueError('type5c header inventory exceeds owner limit')
        visited.add(identity)
        if depth > max_depth:
            refuse('embedded depth prevents complete owner inventory'); return
        active = active | {identity}
        for fi, field in enumerate(owner.fields):
            charge()
            if field.name_hash == 0x100:
                continue
            if field.type_word & 0xffff == 0x5c:
                if len(pending) >= MAX_HEADERS:
                    raise ValueError('type5c header inventory exceeds header limit')
                charge(1+len(path))
                pending.append((root, path+[fi], owner, field, fi, at))
            elif field.type_word == 5:
                defs = structures.get(field.auxiliary, [])
                if (len(defs) != 1 or defs[0].byte_size <= 0 or field.data_offset < 0
                        or field.data_offset+defs[0].byte_size > owner.byte_size
                        or not psin_references.field_slot_clear(owner, field, defs[0].byte_size)):
                    refuse('embedded declaration is missing, ambiguous or not independently bounded'); continue
                walk(defs[0], at+field.data_offset, root, path+[fi], depth+1, active)
            elif field.type_word == 0x75:
                refuse('inline bucket owners are outside the instance-path inventory')
    for block in blocks:
        charge()
        defs = structures.get(block.type_hash, [])
        if not defs:
            continue
        if len(defs) != 1 or defs[0].byte_size <= 0 or block.byte_length % defs[0].byte_size:
            refuse('local root declaration is ambiguous or does not tile its block'); continue
        owner = defs[0]
        for ri in range(block.byte_length//owner.byte_size):
            walk(owner, block.data_offset+ri*owner.byte_size, (block.index, ri), [], 0, frozenset())
    output = []
    for begin in range(0, len(pending), 32):
        batch = pending[begin:begin+32]
        queries = [(root[0], root[1], path) for root, path, *_ in batch if len(path) <= 64]
        results = iter(execute(queries)['queries'])
        for root, path, owner, field, fi, at in batch:
            charge()
            item = dict(index=len(output), status='unresolved', block_index=root[0], record_index=root[1],
                field_path=path, owner_hash=f'0x{owner.name_hash:08x}', owner_data_offset=at,
                owner_byte_length=owner.byte_size, owner_declaration_section_offset=owner.section_offset,
                field_index=fi, field_hash=f'0x{field.name_hash:08x}', field_type_word=f'0x{field.type_word:08x}',
                field_auxiliary=f'0x{field.auxiliary:08x}', declaration_section_offset=field.section_offset,
                parent_type_meaning='unknown', logical_element_meaning='unknown', semantic_owner='unknown')
            output.append(item)
            descriptor_index = field.type_word >> 16
            item['descriptor_index'] = descriptor_index
            if descriptor_index >= len(owner.fields) or descriptor_index == fi:
                item['descriptor_status'] = 'unavailable_or_self'; item['descriptor'] = None
            else:
                d = owner.fields[descriptor_index]
                charge()
                item['descriptor'] = dict(field_index=descriptor_index, hash=f'0x{d.name_hash:08x}',
                    data_offset=d.data_offset, type_word=f'0x{d.type_word:08x}', auxiliary=f'0x{d.auxiliary:08x}',
                    declaration_section_offset=d.section_offset)
                synthetic = d.name_hash == 0x100 and d.data_offset == 0 and field.auxiliary == 0
                item['descriptor_status'] = ('structured_descriptor' if synthetic and d.type_word == 5 else
                    'opaque_pool_descriptor' if synthetic and d.type_word == 0x1b4d and d.auxiliary == 0 else
                    'unsupported_alternate_descriptor')
            if len(path) > 64:
                item['reason'] = 'field path exceeds supported replay depth'; continue
            proof = next(results)
            if proof['status'] != 'resolved':
                item['reason'] = proof['reason']; continue
            slot = proof['field']['source_slot']; start = at+field.data_offset
            item['source_slot'] = slot
            if (slot['data_offset'] != start or slot['byte_length'] < 16
                    or field.data_offset+16 > owner.byte_size
                    or not psin_references.field_slot_clear(owner, field, 16)):
                item['reason'] = 'a clear complete sixteen-byte declared-start slot is unavailable'; continue
            raw = data[start:start+16]
            if len(raw) != 16:
                raise ValueError('type5c header slot exceeds source')
            a, b, word = struct.unpack('<IIQ', raw)
            item.update(status='bounded_observation', header_data_offset=start,
                observed_byte_length=16, header_bits='0x'+raw[::-1].hex(),
                first_word=a, second_word=b, third_word_bits=f'0x{word:016x}',
                first_two_words_equal=a == b, is_value_width=False,
                exclusive_ownership_established=False)
            # This is an explicitly labelled arithmetic hypothesis only. It does
            # not bind records or infer target length/count from the other words.
            number, offset = word & 0xfffff, word >> 20
            location = dict(interpretation='packed block/byte-offset hypothesis; no reference or value meaning established')
            if word == 0:
                location.update(status='zero_word')
            elif not 1 <= number <= len(blocks):
                location.update(status='invalid_block_id')
            else:
                target = blocks[number-1]
                location.update(status='bounded_byte_location' if offset < target.byte_length else 'outside_block',
                    block_index=target.index, type_hash=f'0x{target.type_hash:08x}', byte_offset=offset,
                    block_byte_length=target.byte_length)
            item['packed_location_hypothesis'] = location
    return dict(format='gta6x-psin-type5c-header-observations-v1', profile=PROFILE,
        status='complete' if not refusals and all(f['status']=='bounded_observation' for f in output) else 'partial',
        source_sha256=source['source_sha256'], schema_id=source['schema_id'], max_depth=max_depth,
        source_blocks=source_blocks, scan_scope='locally tiled roots and bounded embedded instance paths only',
        scan_complete=not refusals, scan_reasons=refusals, fields=output,
        summary=dict(nodes=used, headers=len(output), headers_bounded=sum(f['status']=='bounded_observation' for f in output),
            headers_unresolved=sum(f['status']=='unresolved' for f in output),
            alternate_descriptors=sum(f['descriptor_status']=='unsupported_alternate_descriptor' for f in output),
            physical_owners=len(visited), physical_owner_aliases=alias_count, record_links=0, semantic_types_promoted=0),
        interpretation='Opaque sixteen-byte header observations and raw local descriptors only; type, element, count/capacity, values, references and ownership remain unknown. Existing typed-span refusals are unchanged.')
