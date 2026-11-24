"""Narrow declaration-qualified parents of raw animation key-holder records.

The generic raw-type7 field has no declared target type. Only complete local
body references into independently checked40-byte holders are associated.
No parent becomes a bone, skeleton, rig provider or semantic animation owner.
"""
from __future__ import annotations

import struct

from . import anim_bone_keys, anim_resources as resources

PROFILE = 'animation_1024_raw7_at144_to_checked40_holder_v1'
FIELD_SHAPE = ((8, 7), (16, 7), (24, 0x60065), (28, 0x10065),
               (32, 5), (64, 5), (144, 7), (152, 7), (160, 5))


def inspect(data, *, max_work=1000000):
    """Reparse the whole source and retain all checked local parent links.

    Zero/unmatched generic words stay explicit and untraversed. A word selecting
    a qualified holder block must identify a complete aligned40-byte record.
    Malformed recognized references raise atomically; unsupported sources retain
    an explicit reason. Work includes the independent holder/metadata readers.
    """
    if type(max_work) is not int or max_work < 1:
        raise ValueError('key-parent work limit must be a positive integer')
    holders = anim_bone_keys.inspect(data, max_work=max_work)
    used = holders['work_units']
    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise resources.ResourceLimitError('key-parent work limit exceeded')
        used += n

    def result(links, words, missing, counts):
        supported = bool(links)
        view = dict(status='complete' if supported else 'unsupported', profile=PROFILE,
            source_sha256=holders['source_sha256'], links=links, source_words=words,
            holders_without_parent=missing, summary=counts, work_units=used,
            inferred_bone_links=[],
            interpretation='declaration-qualified local generic references only; typed target, root, rig and bone ownership unknown')
        if not supported:
            view['reason'] = 'No supported1024-byte parent links to checked40-byte key holders in this source'
        return view

    counts = dict(source_records=0, zero_source_words=0, matched_parent_links=0,
                  unmatched_source_words=0, checked_holder_records=len(holders['references']),
                  reached_holder_records=0, holders_without_parent=0)
    if not holders['references']:
        return result([], [], [], counts)
    parsed = resources.parse_resource(data, max_nodes=max_work - used)
    charge(parsed['summary']['nodes'])
    definitions = {}
    for row in parsed['structures']:
        charge()
        definitions.setdefault(row['hash'], []).append(row)
    plans = {}
    for declaration in parsed['structures']:
        charge()
        fields = declaration['fields']
        if (declaration['byte_size'] != 1024 or len(fields) != len(FIELD_SHAPE)
                or tuple((f['field_offset'], int(f['type_word'], 16)) for f in fields) != FIELD_SHAPE):
            continue
        if any(fields[i]['unknown_0c'] != '0x00000000' for i in (0, 1, 6, 7)):
            raise ValueError('unsupported generic key-parent field auxiliary word')
        if len(definitions[declaration['hash']]) != 1:
            raise ValueError('ambiguous1024-byte key-parent declaration')
        for ordinal, expected_size in ((4, 24), (5, 80), (8, 864)):
            charge()
            local = definitions.get(fields[ordinal]['unknown_0c'], [])
            if len(local) != 1 or local[0]['byte_size'] != expected_size:
                raise ValueError('unsupported key-parent local declaration extent')
        plans[declaration['hash']] = declaration
    by_holder = {(r['source_block_index'], r['source_record_index']): r
                 for r in holders['references']}
    holder_blocks = {key[0] for key in by_holder}
    charge(len(by_holder))
    links, words, reached = [], [], set()
    for block in parsed['blocks']:
        charge()
        if block['type_hash'] not in plans:
            continue
        declaration = plans[block['type_hash']]
        if block['byte_length'] % 1024:
            raise ValueError('key-parent source block has incomplete1024-byte records')
        for record in range(block['byte_length'] // 1024):
            charge(5)
            source = block['data_offset'] + record * 1024
            at = source + 144
            word, = struct.unpack_from('<Q', data, at)
            selector, offset = word & 0xfffff, word >> 20
            metadata = dict(source_block_index=block['index'], source_record_index=record,
                source_record_data_offset=source, source_field_data_offset=at,
                source_structure_index=declaration['index'], source_structure_hash=declaration['hash'],
                field_descriptor_data_offset=declaration['fields'][6]['data_offset'],
                raw_field_type='0x00000007', raw_field_auxiliary='0x00000000',
                raw_u64=f'0x{word:016x}',
                unassigned_38_bits='0x' + data[source + 56:source + 64][::-1].hex(),
                other_raw_fields=[dict(field_offset=relative, data_offset=source + relative,
                    raw_u64=f'0x{struct.unpack_from("<Q", data, source + relative)[0]:016x}',
                    interpretation='unknown raw field; not traversed') for relative in (8, 16, 152)])
            counts['source_records'] += 1
            if not word:
                counts['zero_source_words'] += 1
                words.append(dict(**metadata, status='zero_word', traversed=False))
                continue
            if selector - 1 not in holder_blocks:
                counts['unmatched_source_words'] += 1
                words.append(dict(**metadata, status='unmatched_word', traversed=False,
                    reason='generic word does not select a checked key-holder block'))
                continue
            target = parsed['blocks'][selector - 1]
            if offset % 40 or offset > target['byte_length'] - 40:
                raise ValueError('key-parent reference does not select a whole bounded40-byte holder')
            identity = selector - 1, offset // 40
            if identity not in by_holder:
                raise ValueError('key-parent reference lacks an independently checked holder record')
            holder = by_holder[identity]
            charge()
            links.append(dict(**metadata, target_holder_block_index=identity[0],
                target_holder_record_index=identity[1],
                target_holder_data_offset=holder['source_header_data_offset'] - 8,
                holder_reference_header_data_offset=holder['source_header_data_offset'],
                holder_reference_bits=holder['reference_bits'],
                key_target_block_index=holder['target_block_index'],
                key_target_record_index=holder['target_record_index'],
                key_slot_data_offset=holder['target_slot_data_offset'],
                raw_key_slot_u64=holder['raw_slot_u64'], nested_raw_slot_u64=holder['nested_raw_slot_u64'],
                target_type_authority='actual checked holder block; generic field has no target descriptor'))
            reached.add(identity)
    missing = []
    for identity in sorted(by_holder.keys() - reached):
        charge()
        missing.append(dict(holder_block_index=identity[0], holder_record_index=identity[1]))
    counts.update(matched_parent_links=len(links), reached_holder_records=len(reached),
                  holders_without_parent=len(missing))
    return result(links, words, missing, counts)
