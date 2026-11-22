"""Bounded PSIN instance-block reader derived from local observations.

Only local, unambiguous schemas are used. Scalar/enum/embedded interpretations
remain inferred; unsupported values and references are explicit. No pointer
chasing, external schema table or GPL implementation is used.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct

from . import psin_schema

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
                     max_nodes: int = 100000, max_depth: int = 16) -> dict:
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
    counts = dict(nodes=0, records=0, decoded_values=0, unresolved_fields=0,
                  unsupported_blocks=0, descriptor_fields=0)
    type_cache = {}

    def consume():
        if counts['nodes'] >= max_nodes:
            raise InstanceLimitError('PSIN instance output exceeds node limit')
        counts['nodes'] += 1

    def unresolved(result, reason):
        result.update(status='unresolved', reason=reason)
        counts['unresolved_fields'] += 1
        return result

    def record(owner, at, block_end, depth, active):
        consume()
        if at < 0 or at + owner.byte_size > block_end:
            raise ValueError('PSIN structure exceeds its instance block')
        counts['records'] += 1
        fields = []
        result = dict(structure_hash=f'0x{owner.name_hash:08x}',
                      name_matches=psin_schema._matches(dictionary, owner.name_hash),
                      data_offset=at, byte_length=owner.byte_size, fields=fields)
        identity = owner.section_offset, at
        active = active | {identity}
        for f in owner.fields:
            consume()
            if f.section_offset not in type_cache:
                type_cache[f.section_offset] = psin_schema._type_info(f, owner, structures, enums)
            info = type_cache[f.section_offset]
            value = dict(hash=f'0x{f.name_hash:08x}',
                         name_matches=psin_schema._matches(dictionary, f.name_hash),
                         data_offset=f.data_offset, type_word=f'0x{f.type_word:08x}',
                         type_name=info['name'], type_confidence=info['status'])
            fields.append(value)
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
            if kind == 'embedded_structure':
                target = structures[f.auxiliary][0]
                if target.byte_size == 0:
                    unresolved(value, 'zero-sized embedded structure is not validated')
                elif depth >= max_depth:
                    unresolved(value, 'embedded structure depth limit reached')
                elif (target.section_offset, start) in active:
                    unresolved(value, 'cyclic embedded structure reference')
                else:
                    child = record(target, start, start + width, depth + 1, active)
                    value.update(status=child['status'], value=child)
                continue
            if kind not in ('bool8', 'float32', 'hash32', 'enum32'):
                reason = info.get('reason') or (
                    'container pointer layout is not decoded' if kind in ('dynamic_array', 'map') else
                    'bitset storage is not independently established' if kind in ('enum_bitset32', 'enum_bitset64') else
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
                target = enums[f.auxiliary][0]
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
        candidates = structures.get(block.type_hash, [])
        if len(candidates) != 1:
            row.update(status='unresolved', reason='missing or ambiguous local block structure',
                       record_count=None)
            counts['unsupported_blocks'] += 1
            continue
        owner = candidates[0]
        if owner.byte_size == 0 or block.byte_length % owner.byte_size:
            row.update(status='unresolved', reason='block length is not a validated structure stride multiple',
                       record_count=None)
            counts['unsupported_blocks'] += 1
            continue
        records = [record(owner, at, end, 1, set()) for at in
                   range(block.data_offset, end, owner.byte_size)]
        row.update(record_count=len(records), records=records,
                   status='complete' if all(r['status'] == 'complete' for r in records) else 'partial')
    return dict(format='gta6x-psin-instances-v1', schema_id=schema.schema_id,
                interpretation='Inferred local scalar/enum/embedded values; no pointer chasing or complete object-graph claim.',
                status='complete' if all(b['status'] == 'complete' for b in output) else 'partial',
                summary=dict(counts, blocks=len(blocks)), blocks=output)
