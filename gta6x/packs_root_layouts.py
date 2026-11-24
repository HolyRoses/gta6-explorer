"""Checked minimum reference graph for a separate two-reference pack root.

Source-local references and disjoint minimum prefixes are checked without
identifying a resource type, allocation, bone table or provider. Other words,
including graphics-domain-looking values, remain raw and are never rebased.
"""
from __future__ import annotations

import hashlib
import struct

from . import packs_skeleton_bounds as bounds

PROFILE = 'packs_root8_root16_member40_minimum_graph_v1'


def inspect(data, *, max_work=1000000):
    """Inspect one explicitly supplied source under the narrow new profile.

    Complete means only that this minimum graph was checked. Unsupported shapes,
    overlaps and malformed late references yield no partial prefixes/references.
    A shared/cyclic prefix is outside this disjoint profile, not a general claim
    that native aliases cannot exist. No continuation or external target is read.
    """
    if type(max_work) is not int or max_work < 1:
        raise ValueError('root layout work limit must be positive')
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('root layout input must be bytes')
    if len(data) > bounds.MAX_BYTES:
        raise bounds.BoundsLimitError('root layout input exceeds byte limit')
    used = 0

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise bounds.BoundsLimitError('root layout work limit exceeded')
        used += n

    result = dict(status='unsupported', candidate_profile=PROFILE, prefixes=[], references=[],
        allocation_end=None, complete_format=False, resource_type='unknown',
        inferred_bone_links=[], inferred_skeleton_providers=[], inferred_animation_owners=[])
    try:
        charge()
        if len(data) < 32 or data[:8] != bytes(8):
            raise ValueError('unsupported two-reference root prefix')
        word24, = struct.unpack_from('<Q', data, 24)
        charge()
        if word24 != 0:
            raise ValueError('two-reference root requires raw word24 zero')

        def target(slot, size, label):
            charge(2)
            word, = struct.unpack_from('<Q', data, slot)
            at = word - bounds.BASE
            if at < 32 or at > len(data) - size:
                raise ValueError(f'root layout {label} exceeds source bounds or overlaps root prefix')
            return word, at

        first_word, first = target(8, 32, 'first minimum prefix')
        second_word, second = target(16, 64, 'second minimum prefix')
        charge(2)
        if data[first:first + 8] != bytes(8) or data[second:second + 8] != bytes(8):
            raise ValueError('unsupported member minimum-prefix guard')
        leaf_word, leaf = target(second + 40, 8, 'member40 minimum context')
        spans = [(0, 32, 'root_prefix'), (first, first + 32, 'first_member_prefix'),
                 (second, second + 64, 'second_member_prefix'), (leaf, leaf + 8, 'member40_context')]
        ordered = sorted(spans)
        charge(4)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('root layout minimum prefixes overlap or alias outside supported profile')
        charge(4 + 3 + 16)
        prefixes = [dict(role=role, data_offset=start, byte_length=end-start,
            extent_kind='minimum_checked_prefix', raw_hex=data[start:end].hex())
            for start, end, role in spans]
        references = [dict(data_offset=slot, raw_u64=f'0x{word:016x}', target_data_offset=at,
            target_prefix_bytes=size) for slot, word, at, size in
            ((8, first_word, first, 32), (16, second_word, second, 64),
             (second + 40, leaf_word, leaf, 8))]
        result.pop('candidate_profile')
        result.update(status='complete', profile=PROFILE,
            source_sha256=hashlib.sha256(data).hexdigest(), byte_length=len(data),
            prefixes=prefixes, references=references,
            first_member_data_offset=first, second_member_data_offset=second,
            member40_data_offset=leaf,
            first_member_raw_u64=[f'0x{w:016x}' for w in struct.unpack_from('<4Q', data, first)],
            second_member_raw_u64=[f'0x{w:016x}' for w in struct.unpack_from('<8Q', data, second)],
            counts=dict(minimum_prefixes=4, source_local_references=3, minimum_prefix_bytes=136),
            untraversed_second_member_word24=dict(data_offset=second+24,
                raw_u64=f'0x{struct.unpack_from("<Q", data, second+24)[0]:016x}', meaning='unknown'),
            interpretation='checked minimum source-local graph only; type, count, full extents and ownership unknown')
    except bounds.BoundsLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    result['work_units'] = used
    return result
