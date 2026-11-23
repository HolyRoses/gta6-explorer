"""Observed native 0DRP field slots and fully covered opaque primitive pools.

The eight-byte grouping is authorized only by complete disjoint counted ranges,
not by value plausibility. Numeric type, signedness, hash and transform meanings
remain unknown. Declarations must be the own reader's same-source output.
"""
from __future__ import annotations

import struct

PROFILE = 'world_0drp_opaque_primitive_pool_layout_v1'
MAX_BYTES = 16 * 1024 * 1024
GROUP_BYTES = 8


def _uint(value, label, maximum=0xffffffff):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('invalid world primitive ' + label)
    return value


def inspect(data, structures, blocks, *, consume, sample_groups=0):
    """Return compact checked layouts; samples are explicit opaque byte groups.

    Every inspected header and nonempty range uses the enclosing node budget.
    A referenced primitive pool must be covered exactly once with no gaps; a
    malformed supported observation refuses the whole view without a prefix.
    Unsupported fields and unreferenced pools remain explicit. No semantic
    primitive width is transferred from PSIN or any external implementation.
    """
    if (not isinstance(data, bytes) or not 80 <= len(data) <= MAX_BYTES
            or data[16:20] != b'0DRP' or struct.unpack_from('<I', data, 20)[0] != 122):
        raise ValueError('world primitive layouts require bounded version-122 0DRP bytes')
    _uint(sample_groups, 'sample count', 32)
    if not isinstance(structures, list) or not isinstance(blocks, list):
        raise ValueError('world primitive layouts require normalized local declarations')
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    charge()
    definitions = {}
    for definition in structures:
        charge()
        if (not isinstance(definition, dict) or not isinstance(definition.get('hash'), str)
                or not isinstance(definition.get('fields'), list)):
            raise ValueError('invalid world primitive structure declaration')
        _uint(definition.get('byte_size'), 'structure size', MAX_BYTES)
        for field in definition['fields']:
            charge()
            if not isinstance(field, list) or len(field) != 4:
                raise ValueError('invalid world primitive field declaration')
            for word in field: _uint(word, 'field word')
        definitions.setdefault(definition['hash'], []).append(definition)
    for index, block in enumerate(blocks):
        charge()
        if (not isinstance(block, dict) or block.get('index') != index
                or type(block.get('index')) is not int or not isinstance(block.get('type_hash'), str)):
            raise ValueError('invalid world primitive block declaration')
        length = _uint(block.get('byte_length'), 'block length', MAX_BYTES)
        at = block.get('data_offset')
        if length == 0 and at is None: continue
        _uint(at, 'block offset', MAX_BYTES)
        if at < 80 or at > len(data) - length:
            raise ValueError('world primitive block exceeds source bytes')
    layouts = {}; unsupported = []
    for name, candidates in definitions.items():
        if len(candidates) != 1: continue
        owner = candidates[0]; fields = owner['fields']; width = owner['byte_size']
        named = [(i, f) for i, f in enumerate(fields) if f[0] != 0x100]
        operations = []
        for index, field in named:
            charge()
            _, offset, word, auxiliary = field
            others = [f[1] for i, f in named if i != index]
            di = word >> 16
            primitive_header = (word & 0xffff == 0x5c and di < len(fields)
                and di != index and fields[di] == [0x100, 0, 0x17, 0])
            if offset >= width or offset in others:
                if (word == 0x15 and auxiliary == 0) or primitive_header:
                    raise ValueError('world primitive named field overlaps or exceeds its owning slot')
                charge(); unsupported.append(dict(structure_hash=name, field_index=index,
                    type_word=f'0x{word:08x}', slot_bytes=None,
                    reason='unknown field has no unique bounded local slot'))
                continue
            end = min([v for v in others if v > offset] + [width])
            operation = None
            if word == 0x15 and auxiliary == 0:
                if end - offset != GROUP_BYTES:
                    raise ValueError('unsupported world type15 field-slot extent')
                operation = dict(kind='inline_slot', field_index=index, offset=offset,
                    field_hash=f'0x{field[0]:08x}', type_word=f'0x{word:08x}', byte_length=GROUP_BYTES)
            elif word & 0xffff == 0x5c and word >> 16 < len(fields):
                di = word >> 16
                if di != index and fields[di] == [0x100, 0, 0x17, 0]:
                    if auxiliary or end - offset != 16:
                        raise ValueError('unsupported world primitive counted-header slot')
                    operation = dict(kind='counted_pool', field_index=index, offset=offset,
                        field_hash=f'0x{field[0]:08x}', type_word=f'0x{word:08x}', descriptor_index=di)
            if operation is None:
                charge(); unsupported.append(dict(structure_hash=name, field_index=index,
                    type_word=f'0x{word:08x}', slot_bytes=end-offset,
                    reason='no independently supported primitive layout'))
            else:
                operations.append(operation)
        layouts[name] = operations
    inline_slots = []; sources = []; ranges = {}
    counts = dict(counted_headers=0, null_headers=0, reference_ranges=0,
        primitive_groups=0, primitive_pool_bytes=0, inline_slot_observations=0,
        blocks_without_tiled_structure=0, unreferenced_primitive_blocks=0)
    for block in blocks:
        charge()
        candidates = definitions.get(block['type_hash'], [])
        if (len(candidates) != 1 or candidates[0]['byte_size'] <= 0
                or block['byte_length'] <= 0 or block['byte_length'] % candidates[0]['byte_size']):
            counts['blocks_without_tiled_structure'] += 1; continue
        owner = candidates[0]; stride = owner['byte_size']; records = block['byte_length'] // stride
        for operation in layouts[owner['hash']]:
            charge()
            common = dict(source_block_index=block['index'], source_structure_hash=owner['hash'],
                field_index=operation['field_index'], field_hash=operation['field_hash'],
                type_word=operation['type_word'], record_offset=operation['offset'],
                source_data_offset=block['data_offset']+operation['offset'],
                record_stride=stride, record_count=records)
            if operation['kind'] == 'inline_slot':
                inline_slots.append(dict(common, slot_bytes=GROUP_BYTES,
                    interpretation='eight-byte declared field slot only; value width and meaning unknown'))
                counts['inline_slot_observations'] += records
                continue
            nulls = nonnull = 0; targets = set()
            for record in range(records):
                charge(); position = common['source_data_offset'] + record * stride
                count, other, reference = struct.unpack_from('<IIQ', data, position)
                counts['counted_headers'] += 1
                if (count, other, reference) == (0, 0, 0):
                    nulls += 1; counts['null_headers'] += 1; continue
                if not count or count != other or not reference:
                    raise ValueError('world primitive header requires equal positive counts and a nonnull reference')
                number, offset = reference & 0xfffff, reference >> 20
                if not 1 <= number <= len(blocks):
                    raise ValueError('world primitive reference has an invalid local block ID')
                target = blocks[number-1]; length = target['byte_length']
                if (target['type_hash'] != '0x00000017' or not length or length % GROUP_BYTES
                        or offset % GROUP_BYTES or offset > length or count > (length-offset)//GROUP_BYTES):
                    raise ValueError('world primitive range does not select bounded opaque eight-byte groups')
                charge(); ranges.setdefault(number-1, []).append((offset, count))
                targets.add(number-1); nonnull += 1; counts['reference_ranges'] += 1
            charge(len(targets))
            sources.append(dict(common, descriptor_index=operation['descriptor_index'],
                null_headers=nulls, reference_ranges=nonnull, target_block_indices=sorted(targets)))
    pools = []
    for index, spans in sorted(ranges.items()):
        charge(1+len(spans)); block = blocks[index]; cursor = 0
        for offset, count in sorted(spans):
            if offset != cursor:
                raise ValueError('world primitive pool coverage overlaps or has a gap')
            cursor += count * GROUP_BYTES
        if cursor != block['byte_length']:
            raise ValueError('world primitive ranges do not cover the complete target pool')
        group_count = cursor // GROUP_BYTES
        row = dict(block_index=index, type_hash='0x00000017', data_offset=block['data_offset'],
            byte_length=cursor, group_width=GROUP_BYTES, group_count=group_count,
            source_ranges=len(spans), coverage='complete_disjoint',
            interpretation='opaque byte groups; numeric type, signedness, hash and transform meanings unknown')
        if sample_groups:
            count = min(sample_groups, group_count); charge(count)
            row['raw_group_samples'] = [dict(group_index=i, data_offset=block['data_offset']+i*GROUP_BYTES,
                bytes_hex=data[block['data_offset']+i*GROUP_BYTES:block['data_offset']+(i+1)*GROUP_BYTES].hex())
                for i in range(count)]
            row['sample_scope'] = 'explicit prefix samples only; all source ranges validated independently'
        pools.append(row); counts['primitive_groups'] += group_count; counts['primitive_pool_bytes'] += cursor
    for block in blocks:
        if block['type_hash'] == '0x00000017' and block['index'] not in ranges:
            counts['unreferenced_primitive_blocks'] += 1
    counts.update(nodes=used, primitive_pools=len(pools), primitive_sources=len(sources),
        inline_slot_layouts=len(inline_slots), unsupported_fields=len(unsupported))
    return dict(status='partial', profile=PROFILE, inline_slots=inline_slots,
        primitive_sources=sources, pools=pools, unsupported_fields=unsupported,
        summary=counts, offset_space='decompressed same-source 0DRP bytes',
        interpretation='observed primitive storage layout only; world meanings and graph completeness remain unknown')
