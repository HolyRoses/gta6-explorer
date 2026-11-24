"""Source-scoped alternate bone keys and a discovery-derived name candidate.

The arithmetic candidate is compared to stored keys, never substituted for
one. Zero values and mismatches stay unexplained; collisions retain every row.
No key namespace, animation owner, or special literal-name rule is inferred.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib

from . import packs_bones, packs_skeleton_bounds as bounds

PROFILE = 'packs_alternate_key_candidate_nibble_upper_mod_v1'
CANDIDATE = 'upper_ascii_nibble_add_fold24_mod65167_plus368'


def candidate_key(name):
    """Return the independently fitted arithmetic candidate, not a bone ID.

    There are deliberately no literal exceptions or observations embedded here.
    This candidate does not explain every stored key, including stored zeros.
    """
    if (not isinstance(name, str) or not 1 <= len(name) <= packs_bones.MAX_NAME_BYTES
            or any(not 32 <= ord(c) <= 126 for c in name)):
        raise ValueError('alternate key candidate requires bounded printable ASCII')
    value = 0
    for byte in name.upper().encode('ascii'):
        value = ((value << 4) + byte) & 0xffffffff
        high = value & 0xf0000000
        value = (value ^ (high >> 24)) & (~high & 0xffffffff)
    return value % 65167 + 368


def inspect(data, *, max_work=1000000):
    """Recheck the native table, preserving stored keys and candidate evidence.

    Complete means the source table and comparisons were checked. Candidate
    mismatches are complete evidence, not malformed native tables. The work
    limit includes the complete underlying named-table inspection.
    """
    base = packs_bones.inspect(data, max_work=max_work)
    used = base['work_units']

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise bounds.BoundsLimitError('alternate bone key work limit exceeded')
        used += n

    charge()
    result = dict(status='unsupported', profile=PROFILE,
        source_sha256=base.get('source_sha256') or hashlib.sha256(data).hexdigest(),
        byte_length=len(data), records=[], collision_groups=[], candidate=CANDIDATE,
        alternate_key_namespace='unknown', animation_ownership='unknown',
        allocation_end=None, complete_format=False)
    if base['status'] != 'complete':
        return dict(result, reason=base['reason'], work_units=used)
    records, groups, counts = [], defaultdict(list), Counter()
    for row in base['records']:
        charge(5 + (len(row['name']) + 15) // 16)
        stored = row['alternate_key_u16']
        predicted = candidate_key(row['name'])
        match = stored == predicted
        evidence = 'arithmetic_match' if match else 'unexplained_zero' if stored == 0 else 'arithmetic_mismatch'
        counts[evidence] += 1
        records.append(dict(index=row['index'], data_offset=row['data_offset'],
            name=row['name'], stored_name_hash_u32=row['stored_name_hash_u32'],
            alternate_key_u16=stored, alternate_key_data_offset=row['alternate_key_data_offset'],
            candidate_key_u16=predicted, candidate_matches_stored=match,
            evidence_status=evidence, key_namespace='unknown'))
        groups[stored].append(row['index'])
    collisions = []
    for key, indices in sorted(groups.items()):
        charge(1 + len(indices))
        if len(indices) > 1:
            collisions.append(dict(alternate_key_u16=key, record_indices=indices,
                                   resolution='all native rows retained; no preferred identity'))
    result.update(status='complete', work_units=used, bone_count=base['bone_count'],
        skeleton_header_data_offset=base['skeleton_header_data_offset'],
        records=records, collision_groups=collisions, counts=dict(counts),
        distinct_stored_keys=len(groups),
        interpretation='stored-key evidence and candidate arithmetic only; namespace, zero exceptions and animation ownership unknown')
    return result
