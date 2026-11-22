"""Bounded PSIN instance-block reader derived from local observations.

Local, unambiguous schemas take precedence; an optional user-built registry
supplies unambiguous cross-file definitions. Scalar/enum/embedded meanings
remain inferred; unsupported values and references are explicit. Only bounded
local hash32-array spans are followed; checked local fields and structure/reference
arrays and map entry spans link existing typed records without expanding them. No recursive pointer traversal or GPL
implementation is used. Low-ID pool views distinguish inferred
hash/text values, candidate reference words and opaque storage groups.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct

from . import psin_schema, psin_pools, psin_arrays, psin_references, psin_maps

__all__ = ['InstanceBlock', 'InstanceLimitError', 'parse_blocks', 'decode_instances']


class InstanceLimitError(ValueError):
    """The requested instance output exceeds its explicit node budget."""


@dataclass(frozen=True)
class InstanceBlock:
    index: int
    table_offset: int
    type_hash: int
    byte_length: int
    data_offset: int


def parse_blocks(body: bytes, *, max_blocks: int = 65536) -> list[InstanceBlock]:
    """Parse an exact PSIN body, refusing other layouts and nonzero padding.

    Entries start at +8, including the first type/length pair. Each is followed
    by eight AA bytes. An eight-PP terminator precedes aligned block payloads.
    """
    if max_blocks < 1:
        raise ValueError('max_blocks must be positive')
    if (len(body) < 16 or body[:4] != b'PSIN'
            or struct.unpack_from('>I', body, 4)[0] != len(body)):
        raise ValueError('instance reader requires an exact PSIN body')
    position = 8
    entries = []
    while True:
        if position + 8 > len(body):
            raise ValueError('missing PSIN block-table terminator')
        if body[position:position + 8] == b'pppppppp':
            position += 8
            break
        if position + 16 > len(body) or body[position + 8:position + 16] != b'\xaa' * 8:
            raise ValueError('unsupported PSIN instance block-table layout')
        if len(entries) >= max_blocks:
            raise InstanceLimitError('PSIN block count exceeds limit')
        key, size = struct.unpack_from('<II', body, position)
        if size == 0:
            raise ValueError('zero-sized PSIN instance block is not validated')
        entries.append((position, key, size))
        position += 16
    blocks = []
    for index, (table_offset, key, size) in enumerate(entries):
        end = position + size
        aligned = (end + 15) & ~15
        if aligned > len(body):
            raise ValueError('truncated PSIN instance block or padding')
        if any(body[end:aligned]):
            raise ValueError('nonzero PSIN instance block padding is not validated')
        blocks.append(InstanceBlock(index, table_offset, key, size, position))
        position = aligned
    if position != len(body):
        raise ValueError('unaccounted PSIN instance body bytes')
    return blocks


def decode_instances(data: bytes, dictionary: dict | None = None, *,
                     max_nodes: int = 100000, max_depth: int = 16, registry=None) -> dict:
    """Read supported values from a verified container; never guess missing data.

    Returns explicit partial/unresolved records for unknown values. Malformed
    input and node-budget exhaustion raise ValueError. Depth/cycle boundaries
    are retained as unresolved fields. The output is strict-JSON compatible.
    """
    if max_nodes < 1 or not 1 <= max_depth <= 64:
        raise ValueError('max_nodes must be positive and max_depth must be 1..64')
    if len(data) > 16 * 1024 * 1024:
        raise ValueError('PSIN instance input exceeds resource size limit')
    schema = psin_schema.parse_schema(data)
    body_end = struct.unpack_from('>I', data, 4)[0]
    blocks = parse_blocks(data[:body_end], max_blocks=min(max_nodes, 65536))
    structures = psin_schema._index(schema.structures)
    enums = psin_schema._index(schema.enum_table.definitions)
    scope = registry.scope(schema) if registry is not None else None
    counts = dict(nodes=0, records=0, decoded_values=0, unresolved_fields=0,
                  unsupported_blocks=0, descriptor_fields=0, pool_blocks=0,
                  pool_elements=0, pool_values_decoded=0, unresolved_pool_elements=0,
                  array_fields_attempted=0, array_fields_unresolved=0,
                  hash32_arrays_resolved=0, hash32_array_values_decoded=0,
                  structure_arrays_resolved=0, structure_array_records_linked=0,
                  reference_arrays_resolved=0, reference_array_records_linked=0,
                  reference_array_null_entries=0, reference_fields_attempted=0,
                  reference_fields_resolved=0, reference_fields_linked=0,
                  reference_fields_null=0, reference_fields_unresolved=0,
                  maps_attempted=0, maps_resolved=0, maps_unresolved=0, map_entries_linked=0)
    type_cache = {}
    reference_slot_cache = {}

    def consume():
        if counts['nodes'] >= max_nodes:
            raise InstanceLimitError('PSIN instance output exceeds node limit')
        counts['nodes'] += 1

    def unresolved(result, reason):
        result.update(status='unresolved', reason=reason)
        counts['unresolved_fields'] += 1
        return result

    def record(owner, at, block_end, depth, active, context):
        consume()
        if at < 0 or at + owner.byte_size > block_end:
            raise ValueError('PSIN structure exceeds its instance block')
        counts['records'] += 1
        fields = []
        result = dict(structure_hash=f'0x{owner.name_hash:08x}',
                      name_matches=psin_schema._matches(dictionary, owner.name_hash),
                      data_offset=at, byte_length=owner.byte_size, fields=fields)
        identity = id(owner), at
        active = active | {identity}
        for f in owner.fields:
            consume()
            struct_index = context.structures if context else structures
            enum_index = context.enums if context else enums
            cache_key = id(context), id(owner), f.section_offset
            if cache_key not in type_cache:
                type_cache[cache_key] = psin_schema._type_info(f, owner, struct_index, enum_index)
            info = type_cache[cache_key]
            value = dict(hash=f'0x{f.name_hash:08x}',
                         name_matches=psin_schema._matches(dictionary, f.name_hash),
                         data_offset=f.data_offset, type_word=f'0x{f.type_word:08x}',
                         type_name=info['name'], type_confidence=info['status'])
            fields.append(value)
            for key in ('reference_resolution', 'enum_resolution'):
                if key in info:
                    value[key] = info[key]
            if f.name_hash == 0x100:
                value.update(status='descriptor', reason='schema element descriptor, not an instance member')
                counts['descriptor_fields'] += 1
                continue
            kind = info['name']
            width = info['storage_bytes']
            start = at + f.data_offset
            # Type annotations alone do not authorize reading beyond either
            # the owner or the containing block, including future type widths.
            if width is not None and (f.data_offset + width > owner.byte_size
                                      or start + width > block_end):
                raise ValueError('PSIN field exceeds instance bounds')
            if f.type_word & 0xffff == 7:
                consume()  # Bindings and nulls share the existing output budget.
                counts['reference_fields_attempted'] += 1
                reference = psin_references.resolve_field(
                    data, start, f, owner, block_end, blocks,
                    local_owner=context is None or context.schema is not None,
                    local_structures=structures, slot_cache=reference_slot_cache)
                value['reference'] = reference
                if reference['status'] == 'unresolved':
                    counts['reference_fields_unresolved'] += 1
                    unresolved(value, reference['reason'])
                else:
                    value['status'] = 'complete'
                    counts['reference_fields_resolved'] += 1
                    counts['reference_fields_linked'] += reference['status'] == 'record_reference'
                    counts['reference_fields_null'] += reference['status'] == 'null_reference'
                continue
            if kind == 'embedded_structure':
                target = struct_index.get(f.auxiliary)[0]
                if target.byte_size == 0:
                    unresolved(value, 'zero-sized embedded structure is not validated')
                elif depth >= max_depth:
                    unresolved(value, 'embedded structure depth limit reached')
                elif (id(target), start) in active:
                    unresolved(value, 'cyclic embedded structure reference')
                else:
                    child_context = context.child_scope(f.auxiliary) if context else None
                    child = record(target, start, start + width, depth + 1, active, child_context)
                    value.update(status=child['status'], value=child)
                continue
            if kind == 'dynamic_array':
                counts['array_fields_attempted'] += 1
                descriptor_index = info['element_descriptor_index']
                descriptor = owner.fields[descriptor_index]
                local_owner = context is None or context.schema is not None
                if descriptor.type_word & 0xffff == 5:
                    array = psin_arrays.resolve_structure_links(
                        data, start, owner, descriptor_index, blocks, local_owner=local_owner,
                        local_structures=structures, consume=consume)
                elif descriptor.type_word & 0xffff == 7:
                    array = psin_arrays.resolve_reference_links(
                        data, start, owner, descriptor_index, blocks, local_owner=local_owner,
                        local_structures=structures, consume=consume)
                else:
                    array = psin_arrays.resolve_hash32(
                        data, start, owner, descriptor_index, blocks, local_owner=local_owner,
                        local_structures=structures, consume=consume, dictionary=dictionary)
                value['array'] = array
                if array['status'] != 'complete':
                    counts['array_fields_unresolved'] += 1
                    unresolved(value, array['reason'])
                else:
                    value['status'] = 'complete'
                    if array['element_type'] == 'structure':
                        counts['structure_arrays_resolved'] += 1
                        counts['structure_array_records_linked'] += array['count']
                    elif array['element_type'] == 'reference':
                        counts['reference_arrays_resolved'] += 1
                        counts['reference_array_records_linked'] += array['record_link_count']
                        counts['reference_array_null_entries'] += array['null_count']
                    else:
                        counts['hash32_arrays_resolved'] += 1
                        counts['hash32_array_values_decoded'] += array['count']
                        counts['decoded_values'] += array['count']
                continue
            if kind == 'map':
                consume()  # Header associations and entries share the output budget.
                counts['maps_attempted'] += 1
                mapping = psin_maps.resolve_entries(
                    data, start, f, owner, block_end, blocks,
                    local_owner=context is None or context.schema is not None,
                    local_structures=structures, consume=consume, slot_cache=reference_slot_cache)
                value['map'] = mapping
                if mapping['status'] != 'complete':
                    counts['maps_unresolved'] += 1
                    unresolved(value, mapping['reason'])
                else:
                    value['status'] = 'complete'
                    counts['maps_resolved'] += 1
                    counts['map_entries_linked'] += mapping['count']
                continue
            if kind not in ('bool8', 'float32', 'hash32', 'enum32'):
                reason = info.get('reason') or (
                    'container pointer layout is not decoded' if kind in ('dynamic_array', 'map') else
                    'bitset storage is not independently established' if kind in ('enum_bitset32', 'enum_bitset64') else
                    'unsupported type or unresolved/ambiguous schema reference' if context else
                    'unsupported type or unresolved/ambiguous local schema reference')
                unresolved(value, reason)
                continue
            raw = data[start:start + width]
            value['value_bits'] = '0x' + raw[::-1].hex()
            if kind == 'bool8':
                if raw[0] not in (0, 1):
                    unresolved(value, 'stored byte is not a supported Boolean value')
                    continue
                value['value'] = bool(raw[0])
            elif kind == 'float32':
                number = struct.unpack('<f', raw)[0]
                if not math.isfinite(number):
                    unresolved(value, 'nonfinite float preserved as bits')
                    continue
                value['value'] = number
            elif kind == 'hash32':
                number = int.from_bytes(raw, 'little')
                value.update(value=f'0x{number:08x}',
                             value_name_matches=psin_schema._matches(dictionary, number))
            else:
                number = int.from_bytes(raw, 'little')
                target = enum_index.get(f.auxiliary)[0]
                matches = []
                for member in target.members:
                    if member.value_bits & 0xffffffff == number:
                        consume()  # Enum aliases also consume output budget.
                        matches.append(member.as_dict(dictionary))
                value.update(value_unsigned=number,
                             value_signed=number - (1 << 32) if number >> 31 else number,
                             enum_hash=f'0x{f.auxiliary:08x}',
                             enum_matches=matches)
                if not matches:
                    unresolved(value, 'enum value is absent from the referenced LENM definition')
                    continue
            value['status'] = 'decoded'
            counts['decoded_values'] += 1
        result['status'] = 'complete' if all(f['status'] in ('decoded', 'complete', 'descriptor')
                                             for f in fields) else 'partial'
        return result

    output = []
    for block in blocks:
        consume()
        end = block.data_offset + block.byte_length
        row = dict(index=block.index, table_offset=block.table_offset,
                   type_hash=f'0x{block.type_hash:08x}', data_offset=block.data_offset,
                   byte_length=block.byte_length,
                   sha256=hashlib.sha256(data[block.data_offset:end]).hexdigest())
        output.append(row)
        candidates = scope.structures.get(block.type_hash, []) if scope else structures.get(block.type_hash, [])
        if scope:
            row['structure_resolution'] = scope.resolve('structure', block.type_hash).as_dict()
        if len(candidates) != 1:
            # Intrinsic-pool views never override any local definition,
            # including duplicate/ambiguous definitions or incompatible strides.
            pool = (psin_pools.inspect_pool(data, block, blocks, consume=consume,
                                          dictionary=dictionary) if not candidates else None)
            if pool is not None:
                row.update(pool=pool, status=pool['status'], record_count=None)
                counts['pool_blocks'] += 1
                counts['pool_elements'] += len(pool['elements'])
                decoded = sum(e['status'] == 'decoded' for e in pool['elements'])
                counts['pool_values_decoded'] += decoded
                counts['decoded_values'] += decoded
                counts['unresolved_pool_elements'] += len(pool['elements']) - decoded
                counts['unsupported_blocks'] += pool['status'] != 'complete'
                continue
            row.update(status='unresolved', reason=('missing or ambiguous block structure' if scope else
                                                   'missing or ambiguous local block structure'),
                       record_count=None)
            counts['unsupported_blocks'] += 1
            continue
        owner = candidates[0]
        if owner.byte_size == 0 or block.byte_length % owner.byte_size:
            row.update(status='unresolved', reason='block length is not a validated structure stride multiple',
                       record_count=None)
            counts['unsupported_blocks'] += 1
            continue
        block_context = scope.child_scope(block.type_hash) if scope else None
        records = [record(owner, at, end, 1, set(), block_context) for at in
                   range(block.data_offset, end, owner.byte_size)]
        row.update(record_count=len(records), records=records,
                   status='complete' if all(r['status'] == 'complete' for r in records) else 'partial')
    return dict(format='gta6x-psin-instances-v1', schema_id=schema.schema_id,
                interpretation=('Inferred scalar/enum/embedded values, hash/ASCII pools, bounded hash32 arrays '
                                'and bounded local field/array/map-entry record links; '
                                'bare reference candidates and opaque pools remain unresolved; '
                                + ('local-first registry resolution; ' if registry is not None else '')
                                + 'no general pointer traversal or complete object-graph claim.'),
                status='complete' if all(b['status'] == 'complete' for b in output) else 'partial',
                summary=dict(counts, blocks=len(blocks)), blocks=output)
