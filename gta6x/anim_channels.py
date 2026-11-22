"""Bounded packed-animation slot-directory candidates; no sample decoding.

The eleven groups have unknown meanings. An index associates a candidate
binding row with a sub-index arithmetically, without identifying bones,
properties, codecs, scalar types, or timing.
"""
from __future__ import annotations

import struct

from . import anim_resources as resources

PROFILE = 'packed_channel_slot_directory_v1'
GROUP_COUNT = 11
DEFAULT_MAX_SCAN_BYTES = 65536


def inspect_buffer(data, offset, length, binding_count, *, consume,
                   max_scan_bytes=DEFAULT_MAX_SCAN_BYTES):
    """Return a unique bounded suffix directory, or a separate unresolved view.

    Search is capped independently of output nodes. Every emitted group, index,
    and region consumes the caller's node budget. No partial groups escape on
    refusal; ResourceLimitError propagates to the dictionary caller.
    """
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, groups=[])
    try:
        if not isinstance(binding_count, int) or isinstance(binding_count, bool) or not 0 < binding_count <= 16383:
            raise ValueError('channel directory requires 1..16383 binding rows for its u16 sentinel')
        if not isinstance(max_scan_bytes, int) or isinstance(max_scan_bytes, bool) or max_scan_bytes < 22:
            raise ValueError('channel directory scan limit must be at least 22 bytes')
        if offset < 0 or length < 32 or offset > len(data) - length:
            raise ValueError('channel directory buffer exceeds input bounds')
        w = struct.unpack_from('<5I5H2B', data, offset)
        if w[1] + 32 != length or w[2] or w[5] != 2 or w[10] != GROUP_COUNT:
            raise ValueError('unsupported channel directory packed-header profile')
        first, end = w[3:5]
        if not 32 <= first <= end <= length or length - end != 6 * ((w[11] >> 4) + (w[11] & 15)):
            raise ValueError('channel directory section bounds disagree with packed header')
        slots = 4 * binding_count
        maximum_size = 22 + GROUP_COUNT * 2 * slots
        search_size = min(end - first, maximum_size)
        if search_size > max_scan_bytes:
            raise ValueError('channel directory candidate search exceeds scan-byte limit')
        if search_size < 22:
            raise ValueError('channel directory count table is truncated')
        matches = []
        for start in range(end - 22, end - search_size - 1, -2):
            counts = struct.unpack_from('<11H', data, offset + start)
            if max(counts) > slots:
                continue
            padded = tuple((count + 3) // 4 * 4 for count in counts)
            if start + 22 + 2 * sum(padded) != end:
                continue
            pos, valid = offset + start + 22, True
            for count, size in zip(counts, padded):
                values = struct.unpack_from('<' + 'H' * size, data, pos)
                active = values[:count]
                if (any(value >= slots for value in active)
                        or any(a >= b for a, b in zip(active, active[1:]))
                        or any(value != slots for value in values[count:])):
                    valid = False
                    break
                pos += size * 2
            if valid:
                matches.append((start, counts, padded))
                if len(matches) > 1:
                    raise ValueError('ambiguous channel directory: multiple suffix candidates')
        if not matches:
            raise ValueError('no supported bounded channel directory suffix')
        start, counts, padded = matches[0]
        consume(4 + GROUP_COUNT + sum(counts))
        groups, pos = [], offset + start + 22
        for group, (count, size) in enumerate(zip(counts, padded)):
            values = struct.unpack_from('<' + 'H' * count, data, pos)
            groups.append(dict(group_index=group, meaning='unknown', count=count,
                data_offset=pos, byte_length=2 * size, padding_count=size - count,
                slots=[dict(slot_index=value, binding_index=value // 4, sub_index=value % 4)
                       for value in values]))
            pos += size * 2
        result.update(status='complete', interpretation='inferred structural slot associations; group meanings unknown',
            profile=result.pop('candidate_profile'), group_count=GROUP_COUNT,
            binding_count=binding_count, slot_limit=slots, padding_sentinel=slots,
            directory=dict(relative_offset=start, data_offset=offset + start, byte_length=end - start),
            count_table=dict(data_offset=offset + start, byte_length=22),
            preceding_section_1=dict(data_offset=offset + first, byte_length=start - first,
                                     interpretation='opaque; no sample values decoded'),
            active_slot_count=sum(counts), padded_slot_count=sum(padded), groups=groups)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
