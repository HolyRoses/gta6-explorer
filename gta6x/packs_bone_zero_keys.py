"""Stored zero-key positions, lookup witnesses and forest context in pack data.

These are name-independent observations, not a zero-specific key algorithm or a
null/root interpretation. Any valid zero placement or multiplicity is retained.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import packs_bones, packs_skeleton_bounds as bounds

PROFILE = 'packs_zero_alternate_key_structural_context_v1'


def inspect(data, *, max_work=1000000):
    """Recheck the table and return structural evidence without repairing keys.

    The complete base inspection is included in the work bound. Unsupported
    native storage is atomic; zero counts, child rows, collisions and nonzero
    parentless rows are all valid observations. Names and candidate formulas do
    not participate in this view.
    """
    base = packs_bones.inspect(data, max_work=max_work)
    used = base['work_units']

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise bounds.BoundsLimitError('zero bone key work limit exceeded')
        used += n

    result = dict(status='unsupported', candidate_profile=PROFILE, zero_records=[],
        nonzero_parentless_records=[], zero_key_meaning='unknown',
        zero_is_null=None, zero_exception_algorithm='unknown; no exception fitted',
        inferred_animation_links=[], allocation_end=None, complete_format=False)
    charge()
    if base['status'] != 'complete':
        return dict(result, reason=base['reason'], work_units=used)

    by_index = defaultdict(list)
    for entry in base['lookup_entries']:
        charge()
        if 'stored_alternate_key' in entry['key_roles']:
            by_index[entry['record_index']].append(entry)

    zeros, nonzero_roots, counts = [], [], Counter()
    zero_flags, other_root_flags = Counter(), Counter()
    for row in base['records']:
        charge(2)
        zero = row['alternate_key_u16'] == 0
        parentless = row['parent_index'] is None
        counts['named_records'] += 1
        counts['zero_records' if zero else 'nonzero_records'] += 1
        if parentless:
            counts['parentless_records'] += 1
            counts['zero_parentless_records' if zero else 'nonzero_parentless_records'] += 1
        if not zero and not parentless:
            continue
        charge(4 + len(by_index[row['index']]))
        view = dict(index=row['index'], data_offset=row['data_offset'],
            alternate_key_u16=row['alternate_key_u16'],
            alternate_key_data_offset=row['alternate_key_data_offset'],
            stored_name_hash_u32=row['stored_name_hash_u32'],
            parent_index=row['parent_index'], raw_parent_u16=row['raw_parent_u16'],
            parent_data_offset=row['parent_data_offset'],
            parent_copy_data_offset=row['parent_copy_data_offset'],
            is_parentless=parentless, is_ordinal_zero=row['index'] == 0,
            next_sibling_index=row['next_sibling_index'],
            subtree_end_index=row['subtree_end_index'],
            flags_raw_u32=row['flags_raw_u32'], unknown_u16_4c=row['unknown_u16_4c'],
            alternate_lookup_witnesses=[dict(entry, key_roles=list(entry['key_roles']))
                                        for entry in by_index[row['index']]])
        if zero:
            zeros.append(view)
            zero_flags[row['flags_raw_u32']] += 1
            counts['zero_parented_records'] += not parentless
            counts['zero_ordinal_zero_records'] += row['index'] == 0
            counts['zero_lookup_witnesses'] += len(by_index[row['index']])
        else:
            nonzero_roots.append(view)
            other_root_flags[row['flags_raw_u32']] += 1

    count_names = ('named_records', 'zero_records', 'nonzero_records',
        'parentless_records', 'zero_parentless_records', 'nonzero_parentless_records',
        'zero_parented_records', 'zero_ordinal_zero_records', 'zero_lookup_witnesses')
    counts = {name: counts[name] for name in count_names}
    charge(len(count_names) + len(zero_flags) + len(other_root_flags))
    result.pop('candidate_profile')
    result.update(status='complete', profile=PROFILE, source_sha256=base['source_sha256'],
        byte_length=len(data), bone_count=base['bone_count'],
        skeleton_header_data_offset=base['skeleton_header_data_offset'],
        zero_records=zeros, nonzero_parentless_records=nonzero_roots, counts=counts,
        zero_presence='present' if zeros else 'absent',
        forest_component_count=base['forest_component_count'],
        empty_lookup_key_u32=base['lookup']['empty_key_u32'],
        empty_lookup_slot_count=len(base['lookup']['empty_slots']),
        zero_flag_counts=[dict(flags_raw_u32=k, record_count=v) for k, v in sorted(zero_flags.items())],
        nonzero_parentless_flag_counts=[dict(flags_raw_u32=k, record_count=v)
                                      for k, v in sorted(other_root_flags.items())],
        interpretation='stored zero values have active lookup witnesses and checked forest context; meaning and algorithmic exceptions remain unknown',
        work_units=used)
    return result
