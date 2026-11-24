"""Checked local pointer context beside a named pack table.

The header, paired counts, complete pointer slots and minimum target prefixes
are source-backed. Target words remain untyped: no provider namespace, resource
ID, animation owner, full record size or allocation endpoint is inferred.
"""
from __future__ import annotations

import struct

from . import packs_bones as bones, packs_skeleton_bounds as bounds

PROFILE = 'packs_child16_paired_count_pointer_context_v1'


def inspect(data, *, max_work=1000000):
    """Inspect a narrow local counted-pointer hypothesis, retaining all slots.

    Equal stored counts bound complete eight-byte pointer slots. An eight-byte
    target prefix is a minimum checked extent, not a typed provider record.
    Empty arrays leave their stored pointer uninterpreted. Exact aliases retain
    every source slot; partial overlaps or malformed late references refuse the
    entire context. The unchanged bone reader supplies the table/path authority.
    """
    base = bones.inspect(data, max_work=max_work)
    used = base['work_units']
    result = dict(status='unsupported', candidate_profile=PROFILE, entries=[],
        allocation_end=None, complete_format=False, provider_namespace='unknown',
        inferred_animation_owners=[], inferred_skeleton_providers=[])

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise bounds.BoundsLimitError('skeleton provider context work limit exceeded')
        used += n

    def target(word, length, label):
        charge()
        at = word - bounds.BASE
        if at < 64 or at > len(data) - length:
            raise ValueError(f'provider context {label} exceeds source bounds or overlaps root prefix')
        return at

    try:
        if base['status'] != 'complete':
            raise ValueError('provider context requires checked named table: ' + base['reason'])
        path = base['header_path']
        reference_at = path['child_data_offset'] + 16
        word, = struct.unpack_from('<Q', data, reference_at)
        header_at = target(word, 32, 'count header')
        charge(2)
        if data[header_at:header_at + 16] != bytes(16):
            raise ValueError('unsupported provider context count-header prefix')
        array_word, = struct.unpack_from('<Q', data, header_at + 16)
        count, duplicate, opaque0, opaque1 = struct.unpack_from('<4H', data, header_at + 24)
        if count != duplicate:
            raise ValueError('provider context paired stored counts disagree')
        spans = [(p['data_offset'], p['data_offset'] + p['byte_length'])
                 for p in path['prefixes']]
        for label in ('record_array', 'parent_array', 'lookup'):
            row = base[label]
            spans.append((row['data_offset'], row['data_offset'] + row['byte_length']))
        spans.append((base['record_array']['count_prefix_data_offset'],
                      base['record_array']['data_offset']))
        spans.extend((r['name_data_offset'], r['name_data_offset'] + r['name_byte_length'] + 1)
                     for r in base['records'])
        charge(len(spans))
        # Known names may alias; their mutual overlap is already the unchanged
        # reader's concern. New spans must be disjoint from their whole union.
        known = spans
        new = [(header_at, header_at + 32)]
        array_at = target(array_word, count * 8, 'pointer slots') if count else None
        if count:
            new.append((array_at, array_at + count * 8))
        entries, prefixes = [], {}
        charge(count)
        for i in range(count):
            charge(2)
            slot = array_at + i * 8
            target_word, = struct.unpack_from('<Q', data, slot)
            at = target(target_word, 8, 'target prefix')
            if at not in prefixes:
                prefixes[at] = len(prefixes)
                new.append((at, at + 8))
            words = struct.unpack_from('<2I', data, at)
            entries.append(dict(index=i, slot_data_offset=slot,
                reference_bits=f'0x{target_word:016x}', target_data_offset=at,
                target_prefix_bytes=8, target_prefix_raw_hex=data[at:at + 8].hex(),
                target_raw_u32=[f'0x{v:08x}' for v in words],
                target_prefix_index=prefixes[at], target_type='unknown'))
        charge(len(new) * (len(known) + 1))
        if any(a < d and c < b for a, b in new for c, d in known):
            raise ValueError('provider context overlaps a checked named-table region')
        ordered = sorted(new)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('provider context minimum regions partially overlap or alias headers/slots')
        result.update(status='complete', profile=result.pop('candidate_profile'),
            source_sha256=base['source_sha256'], byte_length=len(data),
            bone_count=base['bone_count'], skeleton_header_data_offset=base['skeleton_header_data_offset'],
            count_header=dict(reference_data_offset=reference_at,
                reference_bits=f'0x{word:016x}', data_offset=header_at,
                minimum_prefix_bytes=32, paired_count_u16=[count, duplicate],
                opaque_trailing_u16=[opaque0, opaque1]),
            pointer_array=dict(reference_data_offset=header_at + 16,
                reference_bits=f'0x{array_word:016x}', data_offset=array_at,
                checked_byte_length=count * 8, slot_width=8, count=count,
                empty_pointer_untraversed=not count),
            entries=entries, distinct_target_prefixes=len(prefixes),
            interpretation='source-local paired-count pointer context only; raw target words do not establish typed providers or animation ownership')
    except bounds.BoundsLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    result['work_units'] = used
    return result
