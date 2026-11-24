"""Narrow native reference-first key-holder records; no bone or rig binding.

Only an observed40-byte owner/32-byte target declaration shape is supported.
Raw8-byte key slots and source references remain structural evidence, without
assigning bone, hash type, hierarchy, numeric or animation-owner meanings.
"""
from __future__ import annotations

import struct

from . import anim_resources as resources

PROFILE = 'animation_raw0052_singleton_40_to_32_reference_first_v1'


def inspect(data, *, target_words=None, max_work=1000000):
    """Reparse local declarations and bounds before exposing referenced slots.

    Unknown declaration shapes are unsupported. Matching shapes with malformed
    stored references raise ValueError atomically, without partial output.
    Counts other than the observed1/1 profile refuse rather than extrapolate.
    """
    if type(max_work) is not int or max_work < 1:
        raise ValueError('key-holder work limit must be positive')
    if target_words is None:
        target_words = []
    if (not isinstance(target_words, list) or len(target_words) > max_work
            or any(type(w) is not int or not 0 <= w <= 0xffffffff for w in target_words)
            or len(set(target_words)) != len(target_words)):
        raise ValueError('key-holder targets require distinct unsigned32bit words')
    targets = set(target_words) - {0}
    parsed = resources.parse_resource(data, max_nodes=max_work)
    used = parsed['summary']['nodes']
    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise resources.ResourceLimitError('key-holder work limit exceeded')
        used += n
    charge(len(target_words))
    declarations = {}
    for row in parsed['structures']:
        charge()
        declarations.setdefault(row['hash'], []).append(row)
    plans = {}
    present = {block['type_hash'] for block in parsed['blocks']}
    for row in parsed['structures']:
        if row['hash'] not in present:
            continue
        fields = row['fields']
        if row['byte_size'] != 40 or len(fields) != 4:
            continue
        raw = [(int(f['hash'], 16), f['field_offset'], int(f['type_word'], 16), int(f['unknown_0c'], 16)) for f in fields]
        if (raw[0][:3] != (0x100, 0, 5) or raw[1][1:] != (8, 0x52, 0)
                or raw[2][1:] != (24, 0x15, 0) or raw[3][1:] != (32, 0x21, 0)):
            continue
        target_hash = f'0x{raw[0][3]:08x}'
        definitions = declarations.get(target_hash, [])
        if len(definitions) != 1:
            raise ValueError('key-holder target declaration is absent or ambiguous')
        target = definitions[0]
        f = target['fields']
        if (target['byte_size'] != 32 or len(f) != 2
                or f[0]['field_offset'] != 8 or f[0]['type_word'] != '0x00000005'
                or f[1]['field_offset'] != 24 or f[1]['type_word'] != '0x00000e4d'
                or f[1]['unknown_0c'] != '0x00000000'):
            raise ValueError('unsupported key-holder32-byte target declaration')
        nested_hash = f[0]['unknown_0c']
        nested_definitions = declarations.get(nested_hash, [])
        if len(nested_definitions) != 1:
            raise ValueError('key-holder nested declaration is absent or ambiguous')
        nested = nested_definitions[0]
        nf = nested['fields']
        if (nested['byte_size'] != 16 or len(nf) != 1 or nf[0]['field_offset'] != 8
                or nf[0]['type_word'] != '0x0000004a' or nf[0]['unknown_0c'] != '0x00000000'):
            raise ValueError('unsupported key-holder16-byte nested declaration')
        if len(declarations[row['hash']]) != 1:
            raise ValueError('ambiguous key-holder owner declaration')
        plans[row['hash']] = (row, target, nested)
    references = []
    for source in parsed['blocks']:
        charge()
        if source['type_hash'] not in plans:
            continue
        owner, target, nested = plans[source['type_hash']]
        if source['byte_length'] % 40:
            raise ValueError('key-holder owner block has incomplete40-byte records')
        for index in range(source['byte_length'] // 40):
            charge()
            at = source['data_offset'] + 40 * index + 8
            word, count, other, tail = struct.unpack_from('<QHHI', data, at)
            if (count, other, tail) != (1, 1, 0) or not word:
                raise ValueError('key-holder header requires observed singleton1/1 and zero tail')
            selector, offset = word & 0xfffff, word >> 20
            if not 1 <= selector <= len(parsed['blocks']):
                raise ValueError('key-holder reference has invalid one-based block selector')
            block = parsed['blocks'][selector - 1]
            if (block['type_hash'] != target['hash'] or block['byte_length'] % 32
                    or offset % 32 or offset > block['byte_length'] - 32):
                raise ValueError('key-holder reference is not a whole matching32-byte target')
            key_at = block['data_offset'] + offset + 24
            slot, = struct.unpack_from('<Q', data, key_at)
            nested_slot, = struct.unpack_from('<Q', data, key_at - 8)
            charge()
            references.append(dict(source_block_index=source['index'], source_record_index=index,
                source_header_data_offset=at, reference_bits=f'0x{word:016x}', count=1,
                target_block_index=block['index'], target_record_index=offset // 32,
                target_slot_data_offset=key_at, raw_slot_u64=f'0x{slot:016x}',
                slot_byte_length=8, low32_bits=f'0x{slot & 0xffffffff:08x}', high32_bits=f'0x{slot >> 32:08x}',
                nonzero_u32_query_match=(0 < slot <= 0xffffffff and slot in targets),
                source_structure_index=owner['index'], target_structure_index=target['index'],
                nested_structure_index=nested['index'], nested_structure_hash=nested['hash'],
                nested_declared_byte_size=16, nested_raw_slot_u64=f'0x{nested_slot:016x}',
                interpretation='stored local singleton reference and raw slot; bone/owner meaning unknown'))
    result = dict(status='complete' if references else 'unsupported', profile=PROFILE,
        source_sha256=parsed['sha256'], reference_count=len(references), references=references,
        work_units=used, inferred_bone_links=[],
        interpretation='Native declared reference/slot structure only; no bone table, hierarchy or animation binding')
    if not references:
        result['reason'] = 'No supported nonempty key-holder references under this narrow singleton profile'
    return result
