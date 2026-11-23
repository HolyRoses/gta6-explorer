"""Source-checked explanations of unresolved local type5c target definitions.

A descriptor hash is a dependency, not permission to import a definition or
infer a stride from body bytes. Raw headers and block offsets remain observations.
"""
from __future__ import annotations

from copy import deepcopy
import struct

from . import psin_field_context, psin_references, psin_schema, psin_type5c
from .psin_blocks import parse_blocks

PROFILE = 'local_type5c_target_dependency_diagnostics_v1'
MAX_OBSERVATIONS = 65536


def inspect(data, schema, instances, *, consume, max_depth=16):
    """Explain missing, ambiguous and nonpositive local dependencies.

    Inputs must be live native same-source objects. Source/header/schema work
    shares the caller's budget; failure returns no prefix. This adds no record
    links and never accepts registry definitions or assigns empty-state meaning.
    """
    psin_field_context._validate_queries([], max_depth, 0)
    if not isinstance(data, bytes) or len(data) > 16*1024*1024:
        raise ValueError('type5c target diagnostics require bounded source bytes')
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('type5c target diagnostics require a local schema')
    used = 0
    observations = 0
    def charge(amount=1):
        nonlocal used
        consume(amount)
        used += amount
    def observe():
        nonlocal observations
        if observations >= MAX_OBSERVATIONS:
            raise ValueError('type5c target diagnostics exceed observation limit')
        charge()
        observations += 1
    enum_definitions = schema.enum_table.definitions if schema.enum_table else []
    charge(1 + len(schema.structures) + sum(len(s.fields) for s in schema.structures)
        + len(enum_definitions) + sum(len(e.members) for e in enum_definitions))
    local = deepcopy(schema)
    legacy = psin_type5c.inspect(data, local, instances, consume=charge, max_depth=max_depth)
    blocks = parse_blocks(data[:struct.unpack_from('>I', data, 4)[0]])
    structures = psin_schema._index(local.structures)
    charge(len(local.structures) + len(blocks))
    owners = {owner.section_offset: owner for owner in local.structures}
    fields = []
    for header in legacy['fields']:
        charge()
        origin = header['source_lineage']
        owner = owners.get(origin['owner']['declaration_section_offset'])
        if owner is None or owner.name_hash != int(header['owner_hash'], 16):
            raise ValueError('type5c target owner differs from local declarations')
        index = header['field_index']
        field = owner.fields[index]
        descriptor_index = field.type_word >> 16
        # Malformed descriptors remain the legacy reader's explicit refusals.
        if (field.auxiliary or descriptor_index >= len(owner.fields)
                or descriptor_index == index):
            continue
        descriptor = owner.fields[descriptor_index]
        if (descriptor.name_hash != 0x100 or descriptor.data_offset != 0
                or descriptor.type_word != 5):
            continue
        definitions = structures.get(descriptor.auxiliary, [])
        if len(definitions) == 1 and definitions[0].byte_size > 0:
            continue
        status = ('missing' if not definitions else 'ambiguous' if len(definitions) > 1
                  else 'nonpositive_size')
        observe()
        item = dict(index=len(fields), legacy_field_index=header['index'], status='unresolved',
            target_definition_status=status, target_structure_hash=f'0x{descriptor.auxiliary:08x}',
            local_definition_count=len(definitions), local_definitions=[], matching_body_blocks=[],
            owner_hash=header['owner_hash'], field_hash=header['field_hash'], field_index=index,
            field_type_word=header['field_type_word'], declaration_section_offset=field.section_offset,
            descriptor=dict(index=descriptor_index, hash=f'0x{descriptor.name_hash:08x}',
                type_word=f'0x{descriptor.type_word:08x}', auxiliary=f'0x{descriptor.auxiliary:08x}',
                data_offset=descriptor.data_offset, declaration_section_offset=descriptor.section_offset),
            source_lineage=deepcopy(origin), header_data_offset=header['header_data_offset'],
            header_byte_length=16, record_links=[], declared_record_stride=None,
            logical_element_meaning='unknown', semantic_owner='unknown',
            reason='local descriptor target is '+status+'; no record stride or links authorized')
        fields.append(item)
        for definition in definitions:
            observe()
            item['local_definitions'].append(dict(structure_hash=f'0x{definition.name_hash:08x}',
                byte_size=definition.byte_size, field_count=len(definition.fields),
                declaration_section_offset=definition.section_offset))
        for block in blocks:
            charge()
            if block.type_hash == descriptor.auxiliary:
                observe()
                item['matching_body_blocks'].append(dict(block_index=block.index,
                    structure_hash=f'0x{block.type_hash:08x}', data_offset=block.data_offset,
                    byte_length=block.byte_length, block_table_offset=block.table_offset))
        start = header['header_data_offset']
        owner_start = origin['owner']['data_offset']
        if (field.data_offset < 0 or field.data_offset+16 > owner.byte_size
                or not psin_references.field_slot_clear(owner, field, 16)
                or start != owner_start+field.data_offset or not 0 <= start < start+16 <= len(data)):
            item['header_observation'] = dict(status='unresolved', reason='no clear complete local 16-byte header slot')
            continue
        observe()
        a, b, word = struct.unpack_from('<IIQ', data, start)
        raw = data[start:start+16]
        observed = dict(status='observed', first_word=a, second_word=b, equal_words=a == b,
            all_zero=not any(raw), header_bits='0x'+raw[::-1].hex(),
            reference_bits=f'0x{word:016x}', empty_state_meaning='unknown')
        item['header_observation'] = observed
        if word == 0:
            observed['reference_observation'] = dict(status='null', record_span_authorized=False)
            continue
        number, offset = word & 0xfffff, word >> 20
        reference = dict(block_id=number, byte_offset=offset, record_span_authorized=False)
        observed['reference_observation'] = reference
        if not 1 <= number <= len(blocks):
            reference.update(status='invalid_block', reason='stored reference selects no local block')
            continue
        block = blocks[number-1]
        reference.update(block_index=block.index, block_type_hash=f'0x{block.type_hash:08x}',
            block_data_offset=block.data_offset, block_byte_length=block.byte_length,
            block_table_offset=block.table_offset,
            descriptor_type_matches_block=block.type_hash == descriptor.auxiliary)
        if offset >= block.byte_length:
            reference.update(status='outside_block', reason='stored offset selects no byte inside the block')
        else:
            reference.update(status='bounded_block_offset', data_offset=block.data_offset+offset,
                remaining_block_bytes=block.byte_length-offset,
                interpretation='bounded byte offset only; no element width, count or typed record span established')
    return dict(format='gta6x-psin-type5c-targets-v1', profile=PROFILE,
        status='partial' if fields or not legacy['scan_complete'] else 'complete',
        source_sha256=legacy['source_sha256'], schema_id=legacy['schema_id'], max_depth=max_depth,
        legacy_profile=legacy['profile'], legacy_scan_complete=legacy['scan_complete'],
        fields=fields,
        summary=dict(nodes=used, target_dependencies=len(fields),
            missing=sum(f['target_definition_status'] == 'missing' for f in fields),
            ambiguous=sum(f['target_definition_status'] == 'ambiguous' for f in fields),
            nonpositive_size=sum(f['target_definition_status'] == 'nonpositive_size' for f in fields),
            headers_observed=sum(f['header_observation']['status'] == 'observed' for f in fields),
            zero_headers=sum(f['header_observation'].get('all_zero', False) for f in fields),
            record_links=0, semantic_types_promoted=0),
        interpretation='Local unresolved target dependencies and raw bounded header/block-offset observations only; no imported definitions, inferred strides, empty semantics, record links or semantic ownership.')
