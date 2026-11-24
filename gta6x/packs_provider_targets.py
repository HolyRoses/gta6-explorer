"""Second local reference hop from checked pack provider-context prefixes.

Only paired singleton counts, complete u64 slots and minimum raw prefixes are
checked. Target words, entry stride, provider type, allocation and animation
ownership remain unknown. No literal or name chooses an owner.
"""
from __future__ import annotations

import struct

from . import packs_bones as bones, packs_skeleton_providers as providers
from . import packs_skeleton_bounds as bounds

PROFILE = 'packs_provider_target_singleton72_minimum_prefixes_v1'


def inspect(data, *, max_work=1000000):
    """Follow a bounded singleton-only reference hypothesis, without types.

    A count above one is unsupported: native singleton observations do not
    establish the entry stride. Empty counts keep the stored pointer raw.
    Every source slot and exact same-role alias is retained. Unsupported storage
    refuses atomically; work limits include both unchanged source inspectors.
    """
    parent = providers.inspect(data, max_work=max_work)
    used = parent['work_units']
    result = dict(status='unsupported', candidate_profile=PROFILE, entries=[],
        allocation_end=None, complete_format=False, provider_namespace='unknown',
        entry_stride=None, inferred_animation_owners=[], inferred_skeleton_providers=[])

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise bounds.BoundsLimitError('provider target work limit exceeded')
        used += n

    def target(word, length, label):
        charge()
        position = word - bounds.BASE
        if position < 64 or position > len(data) - length:
            raise ValueError(f'provider target {label} exceeds source bounds or overlaps root prefix')
        return position

    try:
        if parent['status'] != 'complete':
            raise ValueError('provider target requires checked pointer context: ' + parent['reason'])
        if used >= max_work:
            raise bounds.BoundsLimitError('provider target work limit exceeded')
        base = bones.inspect(data, max_work=max_work - used)
        used += base['work_units']
        if base['status'] != 'complete':
            raise ValueError('provider target requires checked named table')
        known = [(row['data_offset'], row['data_offset'] + row['byte_length'])
                 for row in base['header_path']['prefixes']]
        for key in ('record_array', 'parent_array', 'lookup'):
            row = base[key]
            known.append((row['data_offset'], row['data_offset'] + row['byte_length']))
        known.append((base['record_array']['count_prefix_data_offset'],
                      base['record_array']['data_offset']))
        known.extend((row['name_data_offset'], row['name_data_offset'] + row['name_byte_length'] + 1)
                     for row in base['records'])
        header = parent['count_header']['data_offset']
        known.append((header, header + parent['count_header']['minimum_prefix_bytes']))
        array = parent['pointer_array']
        if array['count']:
            known.append((array['data_offset'], array['data_offset'] + array['checked_byte_length']))
        charge(len(known))
        regions = {}

        def region(at, length, role):
            charge()
            key = at, at + length
            if key in regions and regions[key] != role:
                raise ValueError('provider target spans alias different structural roles')
            regions[key] = role

        entries, counts = [], dict(target_observations=0, empty_targets=0,
                                    singleton_targets=0, payload_prefix_observations=0)
        for entry in parent['entries']:
            charge(3)
            at = target(bounds.BASE + entry['target_data_offset'], 88, 'minimum 88-byte prefix')
            region(at, 88, 'target_prefix')
            pointer, = struct.unpack_from('<Q', data, at + 72)
            count, copy, unknown0, unknown1 = struct.unpack_from('<4H', data, at + 80)
            if count != copy:
                raise ValueError('provider target paired counts disagree')
            if count > 1:
                raise ValueError('provider target count above one has no established entry stride')
            row = dict(source_slot_index=entry['index'], source_slot_data_offset=entry['slot_data_offset'],
                parent_target_prefix_index=entry['target_prefix_index'], data_offset=at,
                minimum_prefix_bytes=88, raw_prefix_hex=data[at:at + 88].hex(),
                reference_data_offset=at + 72, reference_bits=f'0x{pointer:016x}',
                paired_count_data_offset=at + 80, paired_count_u16=[count, copy],
                opaque_trailing_u16=[unknown0, unknown1], empty_pointer_untraversed=not count,
                entry_prefix=None, payload_prefix=None, target_type='unknown')
            counts['target_observations'] += 1
            if count:
                slot = target(pointer, 8, 'singleton pointer slot')
                region(slot, 8, 'singleton_slot')
                word, = struct.unpack_from('<Q', data, slot)
                destination = target(word, 8, 'minimum payload prefix')
                region(destination, 8, 'payload_prefix')
                row['entry_prefix'] = dict(data_offset=slot, minimum_prefix_bytes=8,
                    raw_prefix_hex=data[slot:slot + 8].hex(), reference_bits=f'0x{word:016x}')
                row['payload_prefix'] = dict(data_offset=destination, minimum_prefix_bytes=8,
                    raw_prefix_hex=data[destination:destination + 8].hex(), target_type='unknown')
                counts['singleton_targets'] += 1
                counts['payload_prefix_observations'] += 1
            else:
                counts['empty_targets'] += 1
            entries.append(row)
        charge(len(regions) * (len(known) + 1))
        if any(a < d and c < b for a, b in regions for c, d in known):
            raise ValueError('provider target overlaps a checked source region')
        ordered = sorted(regions)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('provider target minimum regions overlap or cycle')
        result.pop('candidate_profile')
        result.update(status='complete', profile=PROFILE, source_sha256=base['source_sha256'],
            byte_length=len(data), bone_count=base['bone_count'], entries=entries, counts=counts,
            distinct_target_prefixes=sum(role == 'target_prefix' for role in regions.values()),
            distinct_payload_prefixes=sum(role == 'payload_prefix' for role in regions.values()),
            interpretation='checked second local singleton reference hop only; complete entry stride/type/provider identity unknown')
    except bounds.BoundsLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    result['work_units'] = used
    return result
