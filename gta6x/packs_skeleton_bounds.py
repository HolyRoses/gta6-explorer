"""Bounded local header-prefix path in skeleton-name-bearing pack streams.

The path identifies candidate native table headers, not complete allocations or
semantic bone/animation owners. No cross-stream join, magic search, external
decoder or game-specific fixture is used. Other raw words remain opaque.
"""
from __future__ import annotations

import hashlib
import struct

BASE = 0x50000000
MAX_BYTES = 16 * 1024 * 1024
PROFILE = 'packs_local_root24_child24_header_prefixes_v1'


class BoundsLimitError(ValueError):
    """An explicit header-prefix input/work bound was exceeded."""


def inspect(data, *, max_work=100000):
    """Check a disjoint minimum-prefix path from original source bytes.

    Complete describes this narrow prefix check only. The serialized record,
    containing resource and allocation endpoints remain unknown. No field after
    the returned minimum prefixes is claimed merely from physical adjacency.
    """
    if type(max_work) is not int or max_work < 1:
        raise ValueError('pack prefix work limit must be a positive integer')
    if len(data) > MAX_BYTES:
        raise BoundsLimitError('pack prefix source exceeds input byte limit')
    used = 0
    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise BoundsLimitError('pack prefix work limit exceeded')
        used += n
    result = dict(status='unresolved', candidate_profile=PROFILE, prefixes=[], references=[],
                  allocation_end=None, complete_format=False)
    try:
        charge()
        if len(data) < 64 or data[:8] != bytes(8):
            raise ValueError('unsupported pack root prefix')

        def target(at, length, label):
            charge()
            value, = struct.unpack_from('<Q', data, at)
            pos = value - BASE
            if pos < 64 or pos > len(data) - length:
                raise ValueError(f'pack {label} exceeds source bounds or overlaps root prefix')
            return value, pos

        child_word, child = target(24, 32, 'child prefix')
        if data[child:child + 16] != bytes(16):
            raise ValueError('unsupported pack child prefix')
        table_word, table = target(child + 24, 128, 'table-header prefix')
        if data[table:table + 16] != bytes(16):
            raise ValueError('unsupported pack table-header prefix')
        spans = [(0, 64, 'root_prefix'), (child, child + 32, 'child_prefix'),
                 (table, table + 128, 'table_header_prefix')]
        ordered = sorted(spans)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('pack header prefixes overlap or alias')
        charge(5)
        prefixes = [dict(role=role, data_offset=start, byte_length=end - start,
                         extent_kind='minimum_checked_prefix', sha256=hashlib.sha256(data[start:end]).hexdigest())
                    for start, end, role in spans]
        references = [dict(data_offset=24, raw_u64=f'0x{child_word:016x}', target_data_offset=child,
                           target_prefix_bytes=32),
                      dict(data_offset=child + 24, raw_u64=f'0x{table_word:016x}', target_data_offset=table,
                           target_prefix_bytes=128)]
        charge(9)
        result.update(status='complete', profile=result.pop('candidate_profile'),
            prefixes=prefixes, references=references, child_data_offset=child,
            table_header_data_offset=table,
            root_raw_words=[f'0x{struct.unpack_from("<Q", data, at)[0]:016x}' for at in (8, 16, 32, 40)],
            root_raw_u16_30=list(struct.unpack_from('<4H', data, 48)),
            source_sha256=hashlib.sha256(data).hexdigest(), work_units=used,
            interpretation='inferred local header-prefix path only; record/resource endpoints, table and owner meanings unknown')
    except BoundsLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
        result['work_units'] = used
    return result
