"""Checked parallel keyed records and explicit numeric candidates in pack data.

The source's redundant bone count and per-row full name hashes bound a parallel
64-byte array. Its numeric word views do not establish pose, matrix, coordinate,
rest/bind, local/global or animation-ownership semantics. Raw bits are retained.
"""
from __future__ import annotations

import math
import struct

from . import packs_bones as bones, packs_skeleton_bounds as bounds

PROFILE = 'packs_parallel_keyed64_numeric_candidates_v1'
ROW_NUMERIC_OFFSETS = (0, 4, 8, 12, 16, 20, 24, 32, 36, 40, 44)
PARALLEL_NUMERIC_OFFSETS = tuple(range(0, 60, 4))


class PoseLimitError(bounds.BoundsLimitError):
    """An explicit work/input limit refused the complete numeric view."""


def inspect(data, *, max_work=1000000):
    """Reparse one source and inspect only a redundantly keyed parallel array.

    Unsupported layouts are atomic. Non-finite f32 interpretations preserve the
    word bits, classification and a null value, never nonstandard JSON numbers.
    The stable table reader remains authoritative for names/keys/forest fields.
    """
    if type(max_work) is not int or max_work < 1:
        raise ValueError('pack numeric work limit must be a positive integer')
    base = bones.inspect(data, max_work=max_work)
    used = base['work_units']
    result = dict(status='unsupported', candidate_profile=PROFILE, records=[],
                  allocation_end=None, complete_format=False,
                  pose_interpretation='unknown', inferred_animation_links=[])

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise PoseLimitError('pack numeric work limit exceeded')
        used += n

    def numeric(at, offsets):
        values = []
        for relative in offsets:
            charge()
            bits, = struct.unpack_from('<I', data, at + relative)
            value, = struct.unpack_from('<f', data, at + relative)
            classification = ('finite' if math.isfinite(value) else
                              'nan' if math.isnan(value) else 'infinity')
            values.append(dict(relative_offset=relative, data_offset=at + relative,
                raw_u32=f'0x{bits:08x}', ieee754_le_f32=value if math.isfinite(value) else None,
                classification=classification))
        return values

    try:
        if base['status'] != 'complete':
            raise ValueError('numeric view requires checked named table: ' + base['reason'])
        count = base['bone_count']
        header = base['skeleton_header_data_offset']
        pointer, = struct.unpack_from('<Q', data, header + 56)
        at = pointer - bounds.BASE
        length = count * 64
        charge(3)
        if at < 64 or at % 16 or at > len(data) - length:
            raise ValueError('parallel keyed array reference is unaligned or exceeds source bounds')
        checked = [(p['data_offset'], p['data_offset'] + p['byte_length'])
                   for p in base['header_path']['prefixes']]
        for key in ('record_array', 'parent_array', 'lookup'):
            row = base[key]
            checked.append((row['data_offset'], row['data_offset'] + row['byte_length']))
        checked.append((base['record_array']['count_prefix_data_offset'],
                        base['record_array']['data_offset']))
        checked.extend((r['name_data_offset'], r['name_data_offset'] + r['name_byte_length'] + 1)
                       for r in base['records'])
        charge(len(checked))
        if any(at < end and start < at + length for start, end in checked):
            raise ValueError('parallel keyed array overlaps a checked named-table region')
        records = []
        nonfinite = 0
        for row in base['records']:
            charge(4)
            position = at + 64 * row['index']
            key, = struct.unpack_from('<I', data, position + 60)
            if key != int(row['stored_name_hash_u32'], 16):
                raise ValueError('parallel keyed record hash disagrees with named-table ordinal')
            original_numeric = numeric(row['data_offset'], ROW_NUMERIC_OFFSETS)
            parallel_numeric = numeric(position, PARALLEL_NUMERIC_OFFSETS)
            nonfinite += sum(v['classification'] != 'finite' for v in original_numeric + parallel_numeric)
            records.append(dict(index=row['index'], named_record_data_offset=row['data_offset'],
                stored_name_hash_u32=row['stored_name_hash_u32'], parallel_data_offset=position,
                parallel_byte_length=64, parallel_raw_hex=data[position:position + 64].hex(),
                parallel_key_data_offset=position + 60, named_numeric_candidates=original_numeric,
                parallel_numeric_candidates=parallel_numeric))
        result.update(status='complete', profile=result.pop('candidate_profile'),
            source_sha256=base['source_sha256'], byte_length=len(data), bone_count=count,
            parallel_array=dict(reference_data_offset=header + 56, reference_bits=f'0x{pointer:016x}',
                data_offset=at, byte_length=length, stride=64, count=count,
                count_authority='checked bone count plus full stored name hash at +60 in every parallel row'),
            records=records, nonfinite_numeric_candidate_count=nonfinite,
            numeric_interpretation='explicit little-endian IEEE754 word candidates; pose and matrix meanings unknown',
            untraversed_header_references=dict(base['header']['opaque_reference_words']),
            interpretation='checked source-local ordinal/key equality, not a pose decoder')
        # +56 was checked here; no other opaque reference becomes traversable.
        result['untraversed_header_references'].pop('0x38', None)
    except bounds.BoundsLimitError:
        raise
    except ValueError as exc:
        result.update(reason=str(exc))
    result['work_units'] = used
    return result
