"""Bounded local declaration and source-slot context for PSIN fields.

Paths select physical LSCH field indices through existing embedded records.
Declared-start slots are not value widths or proof of exclusive ownership.
Opaque prefixes carry no numeric or application interpretation. Inputs are
fresh same-source reader objects, not authenticated persisted JSON.
"""
from __future__ import annotations

import hashlib
import math
import struct

from . import psin_schema
from .psin_blocks import parse_blocks

PROFILE = 'local_psin_field_source_context_v1'


def _validate_queries(queries, max_depth, max_sample_bytes):
    if not isinstance(queries, (list, tuple)) or len(queries) > 32:
        raise ValueError('PSIN field context accepts at most 32 queries')
    if type(max_depth) is not int or not 1 <= max_depth <= 64:
        raise ValueError('PSIN field context depth must be 1..64')
    if type(max_sample_bytes) is not int or not 0 <= max_sample_bytes <= 32:
        raise ValueError('PSIN field context sample prefix must be 0..32 bytes')
    for query in queries:
        if (not isinstance(query, (list, tuple)) or len(query) != 3
                or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in query[:2])
                or not isinstance(query[2], (list, tuple)) or not 1 <= len(query[2]) <= 64
                or any(type(v) is not int or not 0 <= v <= 0xffffffff for v in query[2])):
            raise ValueError('PSIN field queries require block, record and a nonempty field-index path')


def inspect(data, schema, instances, queries, *, consume, max_depth=16,
            max_sample_bytes=32):
    """Return <=32 source contexts; unsupported paths remain unresolved.

    Malformed queries are rejected before source work. Other malformed input
    and budget failures return no prefix result. Arrays/references are never
    traversed. Nodes include metadata units and 4-KiB source/hash work units.
    """
    _validate_queries(queries, max_depth, max_sample_bytes)
    execute = _prepare(data, schema, instances, consume=consume,
                       max_depth=max_depth, max_sample_bytes=max_sample_bytes)
    return execute(queries)


def _prepare(data, schema, instances, *, consume, max_depth=16,
             max_sample_bytes=32):
    """Prepare a private live checked-source query closure, never a JSON cache.

    The closure owns its reparsed local schema, immutable bytes and block hashes.
    Instance metadata is rechecked for each query. Reported work is per batch,
    including preparation in the first returned batch.
    """
    _validate_queries([], max_depth, max_sample_bytes)
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n)
        used += n
    if not isinstance(data, bytes) or len(data) > 16 * 1024 * 1024:
        raise ValueError('PSIN field context requires bounded source bytes')
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('PSIN field context requires a local schema object')
    enum_definitions = schema.enum_table.definitions if schema.enum_table else []
    source_units = 2 * ((len(data) + 4095) // 4096)
    # Charge metadata and two bounded input scan allowances before reparse /
    # checksum and final source hashing. A scan allowance is one unit per
    # 4 KiB of source, not one unit per byte or a CPU instruction count.
    charge(source_units + 1 + len(schema.structures)
           + sum(len(s.fields) for s in schema.structures)
           + len(enum_definitions) + sum(len(e.members) for e in enum_definitions))
    local = psin_schema.parse_schema(data)
    if schema != local:
        raise ValueError('PSIN field context schema differs from the source declarations')
    schema = local  # private copy; caller mutations cannot alter declarations
    source_digest = hashlib.sha256(memoryview(data)).hexdigest()
    if (not isinstance(instances, dict)
            or instances.get('format') != 'gta6x-psin-instances-v1'
            or instances.get('schema_id') != schema.schema_id
            or instances.get('status') not in ('complete', 'partial')
            or not isinstance(instances.get('blocks'), list)):
        raise ValueError('PSIN field context requires fresh same-source instances')
    blocks = parse_blocks(data[:struct.unpack_from('>I', data, 4)[0]])
    charge(len(blocks))
    if len(instances['blocks']) != len(blocks):
        raise ValueError('PSIN field context source block count differs')
    structures = psin_schema._index(schema.structures)
    enums = psin_schema._index(schema.enum_table.definitions)
    block_hashes = {}
    block_hash_units = 0
    reported = reported_hash_units = 0
    type_cache = {}

    def type_info(f, owner):
        key = id(owner), id(f)
        if key not in type_cache:
            # Enum type checks inspect their local members; cache per field.
            targets = enums.get(f.auxiliary, []) if f.type_word & 0xffff in (0x62, 0x63, 0x65, 0x68) else []
            charge(1 + sum(len(e.members) for e in targets))
            type_cache[key] = psin_schema._type_info(f, owner, structures, enums)
        return type_cache[key]

    def declaration(owner, field_index):
        f = owner.fields[field_index]
        info = type_info(f, owner)
        return dict(field_index=field_index, hash=f'0x{f.name_hash:08x}',
                    data_offset=f.data_offset, type_word=f'0x{f.type_word:08x}',
                    auxiliary=f'0x{f.auxiliary:08x}',
                    declaration_section_offset=f.section_offset,
                    type_name=info['name'], type_confidence=info['status'],
                    inferred_storage_bytes=info['storage_bytes'])

    def slot(owner, index):
        f = owner.fields[index]
        charge(len(owner.fields))
        real = [other for other in owner.fields if other.name_hash != 0x100]
        if f.name_hash == 0x100:
            return None, 'schema element descriptor is not a value field'
        if sum(other.name_hash == f.name_hash for other in real) != 1:
            return None, 'field name has ambiguous local declarations'
        if sum(other.data_offset == f.data_offset for other in real) != 1:
            return None, 'field shares an ambiguous declared storage origin'
        end = min([other.data_offset for other in real if other.data_offset > f.data_offset]
                  + [owner.byte_size])
        unknown = 0
        for other in real:
            if other.data_offset >= f.data_offset:
                continue
            width = type_info(other, owner)['storage_bytes']
            if width is None:
                unknown += 1
            elif other.data_offset + width > f.data_offset:
                return None, 'preceding inferred storage overlaps the selected slot'
        info = type_info(f, owner)
        width = info['storage_bytes']
        if info['name'] == 'embedded_structure' and width == 0:
            return None, 'zero-sized embedded declarations do not establish value storage'
        if width is not None and f.data_offset + width > end:
            return None, 'inferred field storage exceeds its declared-start slot'
        return dict(owner_relative_start=f.data_offset, byte_length=end-f.data_offset,
                    width_basis='next_named_declared_start_or_owner_end',
                    is_value_width=False, exclusive_ownership_established=False,
                    preceding_unknown_extent_count=unknown), None

    def execute(queries):
        nonlocal reported, reported_hash_units, block_hash_units
        _validate_queries(queries, max_depth, max_sample_bytes)
        if (instances.get('format') != 'gta6x-psin-instances-v1'
                or instances.get('schema_id') != schema.schema_id
                or not isinstance(instances.get('blocks'), list)
                or len(instances['blocks']) != len(blocks)):
            raise ValueError('PSIN field context live instance identity changed')
        output = []
        prefix_total = 0
        for bi, ri, path in queries:
            charge()
            result = dict(block_index=bi, record_index=ri, field_path=list(path), status='unresolved')
            output.append(result)
            def unresolved(reason):
                result['reason'] = reason
            if len(path) > max_depth:
                unresolved('field path exceeds the configured depth'); continue
            if bi >= len(blocks):
                unresolved('block index is absent'); continue
            block = blocks[bi]
            row = instances['blocks'][bi]
            if bi not in block_hashes:
                units = (block.byte_length + 4095) // 4096
                charge(units)
                block_hash_units += units
                block_hashes[bi] = hashlib.sha256(memoryview(data)[block.data_offset:block.data_offset+block.byte_length]).hexdigest()
            expected = dict(index=bi, table_offset=block.table_offset,
                            type_hash=f'0x{block.type_hash:08x}', data_offset=block.data_offset,
                            byte_length=block.byte_length,
                            sha256=block_hashes[bi])
            if not isinstance(row, dict) or any(row.get(k) != v for k, v in expected.items()):
                raise ValueError('PSIN field context source block identity differs')
            candidates = structures.get(block.type_hash, [])
            if len(candidates) != 1 or not candidates[0].byte_size:
                unresolved('record requires one nonempty local owner declaration'); continue
            owner = candidates[0]
            if block.byte_length % owner.byte_size:
                unresolved('source block has no exact local record stride'); continue
            count = block.byte_length // owner.byte_size
            if ri >= count:
                unresolved('record index is absent'); continue
            if (row.get('record_count') != count or not isinstance(row.get('records'), list)
                    or len(row['records']) != count):
                raise ValueError('PSIN field context record stride differs from its instance view')
            record = row['records'][ri]
            at = block.data_offset + ri * owner.byte_size
            context_path = []
            for depth, fi in enumerate(path):
                charge(1 + len(owner.fields))
                if (not isinstance(record, dict) or record.get('structure_hash') != f'0x{owner.name_hash:08x}'
                        or record.get('data_offset') != at or record.get('byte_length') != owner.byte_size
                        or not isinstance(record.get('fields'), list) or len(record['fields']) != len(owner.fields)):
                    raise ValueError('PSIN field context embedded record differs from its declaration')
                if fi >= len(owner.fields):
                    unresolved('field index is absent'); break
                f = owner.fields[fi]
                value = record['fields'][fi]
                if (not isinstance(value, dict) or value.get('hash') != f'0x{f.name_hash:08x}'
                        or value.get('data_offset') != f.data_offset
                        or value.get('type_word') != f'0x{f.type_word:08x}'):
                    raise ValueError('PSIN field context field differs from its source declaration')
                span, reason = slot(owner, fi)
                if reason:
                    unresolved(reason); break
                start = at + f.data_offset
                if not block.data_offset <= start < start + span['byte_length'] <= at + owner.byte_size <= block.data_offset + block.byte_length:
                    raise ValueError('PSIN field context slot exceeds its source owner')
                span['data_offset'] = start
                item = declaration(owner, fi)
                item.update(owner_hash=f'0x{owner.name_hash:08x}', owner_byte_length=owner.byte_size,
                            owner_data_offset=at, source_slot=span)
                context_path.append(item)
                info = type_info(f, owner)
                if depth + 1 < len(path):
                    targets = structures.get(f.auxiliary, [])
                    if info['name'] != 'embedded_structure' or len(targets) != 1:
                        unresolved('field path traverses an unsupported or nonlocal embedded declaration'); break
                    child = value.get('value')
                    if not isinstance(child, dict):
                        unresolved('embedded record is unavailable in the bounded instance view'); break
                    owner, record, at = targets[0], child, start
                    continue
                result.update(status='resolved', declaration_path=context_path, field=item,
                              value_status=value.get('status'),
                              application_semantics='unknown')
                length = min(max_sample_bytes, span['byte_length'])
                prefix = data[start:start+length]
                prefix_total += length
                result['opaque_prefix'] = dict(data_offset=start, byte_length=length, hex=prefix.hex(),
                    truncated=length < span['byte_length'], interpretation='opaque declared-start slot prefix; not a decoded value')
                kind = info['name']
                if kind in ('bool8', 'float32', 'hash32', 'enum32'):
                    width = info['storage_bytes']
                    raw = data[start:start+width]
                    bits = '0x' + raw[::-1].hex()
                    if value.get('value_bits') != bits:
                        raise ValueError('PSIN field context scalar bits differ from source')
                    scalar = dict(type_name=kind, type_confidence=info['status'], value_bits=bits,
                                  status=value.get('status'))
                    if value.get('status') == 'decoded':
                        number = (bool(raw[0]) if kind == 'bool8' else struct.unpack('<f', raw)[0]
                                  if kind == 'float32' else f'0x{int.from_bytes(raw,"little"):08x}')
                        if kind != 'enum32':
                            if (value.get('value') != number
                                    or (kind == 'bool8' and raw[0] not in (0, 1))
                                    or (kind == 'float32' and not math.isfinite(number))):
                                raise ValueError('PSIN field context scalar interpretation differs from source')
                            scalar['value'] = number
                        else:
                            unsigned = int.from_bytes(raw, 'little')
                            if not any(m.value_bits & 0xffffffff == unsigned for m in enums[f.auxiliary][0].members):
                                raise ValueError('PSIN field context enum value is not locally declared')
                            scalar.update(value_unsigned=unsigned,
                                          value_signed=unsigned-(1 << 32) if unsigned >> 31 else unsigned)
                    result['known_scalar'] = scalar
                if kind == 'embedded_structure':
                    target = structures[f.auxiliary][0]
                    charge(1 + len(target.fields))
                    result['child_declaration'] = dict(hash=f'0x{target.name_hash:08x}',
                        byte_length=target.byte_size, declaration_section_offset=target.section_offset,
                        fields=[declaration(target, index) for index in range(len(target.fields))])
        resolved = sum(r['status'] == 'resolved' for r in output)
        result = dict(format='gta6x-psin-field-context-v1', profile=PROFILE,
                    status='complete' if resolved == len(output) else 'partial',
                    source_sha256=source_digest, schema_id=schema.schema_id,
                    max_depth=max_depth, max_sample_bytes=max_sample_bytes,
                    summary=dict(nodes=used-reported, source_scan_work_units=source_units if reported == 0 else 0,
                                 block_hash_work_units=block_hash_units-reported_hash_units,
                                 requested=len(output), resolved=resolved,
                                 unresolved=len(output)-resolved, opaque_prefix_bytes=prefix_total),
                    queries=output)
        reported, reported_hash_units = used, block_hash_units
        return result
    return execute
