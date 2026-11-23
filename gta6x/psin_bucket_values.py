"""Opt-in local fields inside independently bounded PSIN bucket value spans.

Uses existing inferred scalar/enum and local record-link profiles. Unknown fields
remain explicit; target records, strings and application meanings are not expanded.
"""
from __future__ import annotations

import math
import struct

from . import psin_schema, psin_arrays, psin_references


def inspect_value(data, owner, start, *, structures, enums, blocks, consume,
                  read_bucket, depth, max_depth, active=frozenset(), pool_index=None):
    """Read one complete local schema extent under the caller's shared budget."""
    consume()
    result = dict(status='unresolved', data_offset=start, byte_length=owner.byte_size,
                  structure_hash=f'0x{owner.name_hash:08x}', fields=[])
    if (len(structures.get(owner.name_hash, [])) != 1
            or structures[owner.name_hash][0] is not owner or owner.byte_size <= 0):
        return dict(result, reason='inline value requires one positive-sized local schema')
    end = start + owner.byte_size
    if start < 0 or end > len(data):
        raise ValueError('inline bucket value exceeds container bounds')
    if depth > max_depth or (owner.name_hash, start) in active:
        return dict(result, reason='inline value depth or cycle boundary reached')
    active = active | {(owner.name_hash, start)}
    fields = []
    for index, field in enumerate(owner.fields):
        consume()
        row = dict(index=index, field_hash=f'0x{field.name_hash:08x}',
                   type_word=f'0x{field.type_word:08x}', data_offset=start + field.data_offset,
                   status='unresolved')
        fields.append(row)
        if field.name_hash == 0x100:
            row.update(status='descriptor', reason='schema descriptor, not an instance member')
            continue
        info = psin_schema._type_info(field, owner, structures, enums)
        kind, width = info['name'], info['storage_bytes']
        row.update(type_name=kind, type_confidence=info['status'])
        if pool_index is not None:
            from . import psin_bucket_pools
            if psin_bucket_pools.eligible(owner, field):
                row['pool_span']=psin_bucket_pools.resolve(data,row['data_offset'],owner,field,pool_index,consume=consume)
                row['reason']='opaque storage association only; primitive and element meanings remain unresolved'
                continue
        if field.type_word == 0x75:
            width = 16
        elif field.type_word == 7 and field.auxiliary == 0:
            width = 8
        if width is None or width <= 0:
            row['reason'] = 'unsupported inline value field type or unresolved local definition'
            continue
        at = row['data_offset']
        if (field.data_offset < 0 or field.data_offset + width > owner.byte_size
                or not psin_references.field_slot_clear(owner, field, width)):
            row['reason'] = 'inline field extent exceeds or overlaps its local owning slot'
            continue
        row['byte_length'] = width
        if field.type_word == 0x75:
            if depth >= max_depth:
                row['reason'] = 'inline bucket depth limit reached'
                continue
            nested = read_bucket(at, field, owner, end, depth + 1, active)
            row.update(status=nested.get('values_status', nested['status']), bucket_map=nested)
            if row['status'] != 'complete':
                row['reason'] = nested.get('reason', 'nested bucket values remain unresolved')
        elif field.type_word == 7 and field.auxiliary == 0:
            consume()
            reference = psin_references.resolve_field(data, at, field, owner, end, blocks,
                local_owner=True, local_structures=structures)
            row.update(reference=reference,
                       status='complete' if reference['status'] != 'unresolved' else 'unresolved')
            if row['status'] == 'unresolved':
                row['reason'] = reference['reason']
        elif kind == 'embedded_structure':
            child = structures[field.auxiliary][0]
            nested = inspect_value(data, child, at, structures=structures, enums=enums,
                blocks=blocks, consume=consume, read_bucket=read_bucket, depth=depth + 1,
                max_depth=max_depth, active=active, pool_index=pool_index)
            row.update(status=nested['status'], value=nested)
            if row['status'] != 'complete':
                row['reason'] = nested.get('reason', 'embedded value has unresolved fields')
        elif kind == 'map':
            from .psin_bucket_storage import resolve_map
            mapping = resolve_map(data, at, field, owner, end, blocks, structures,
                                  consume=consume)
            row.update(status=mapping['status'], entry_map=mapping)
            if row['status'] != 'complete':
                row['reason'] = mapping['reason']
        elif kind == 'dynamic_array':
            di = info['element_descriptor_index']
            descriptor = owner.fields[di]
            if descriptor.type_word != 5:
                row['reason'] = 'only existing local structure-array links enabled in inline values'
                continue
            array = psin_arrays.resolve_structure_links(data, at, owner, di, blocks,
                local_owner=True, local_structures=structures, consume=consume,
                field=field, block_end=end)
            row.update(status=array['status'], array=array)
            if row['status'] != 'complete':
                row['reason'] = array['reason']
        elif kind in ('bool8', 'float32', 'hash32', 'enum32'):
            raw = data[at:at + width]
            row['value_bits'] = '0x' + raw[::-1].hex()
            if kind == 'bool8':
                if raw[0] not in (0, 1):
                    row['reason'] = 'stored byte is not a supported Boolean value'
                    continue
                row['value'] = bool(raw[0])
            elif kind == 'float32':
                value = struct.unpack('<f', raw)[0]
                if not math.isfinite(value):
                    row['reason'] = 'nonfinite float preserved as bits'
                    continue
                row['value'] = value
            elif kind == 'hash32':
                row['value'] = row['value_bits']
            else:
                value = int.from_bytes(raw, 'little')
                matches = []
                for member in enums[field.auxiliary][0].members:
                    consume()
                    if member.value_bits & 0xffffffff == value:
                        matches.append(member.as_dict(None))
                row.update(value_unsigned=value, enum_hash=f'0x{field.auxiliary:08x}', enum_matches=matches)
                if not matches:
                    row['reason'] = 'enum value absent from the local LENM definition'
                    continue
            row['status'] = 'complete'
        else:
            row['reason'] = 'inline field profile is unsupported'
    result.update(fields=fields, status='complete' if all(
        f['status'] in ('complete', 'descriptor') for f in fields) else 'partial')
    if result['status'] != 'complete':
        result['reason'] = 'inline value has unsupported or unresolved fields'
    return result
