"""Fixed algebraic diagnostics for keyed native bone-record numeric views.

Every ordering/layout hypothesis is reported. Numeric agreement does not select
a pose convention, coordinate system, provider, rest/bind or local/global role.
No new reference is traversed; source authority comes from packs_bone_poses.
"""
from __future__ import annotations

from collections import Counter
import math
import struct

from . import packs_bone_poses as poses, packs_skeleton_bounds as bounds

PROFILE = 'packs_keyed_numeric_fixed_algebraic_relations_v1'
ABS_TOLERANCE = 1e-4
REL_TOLERANCE = 1e-4
LAYOUTS = {
    'rows_3x4': ((0, 1, 2, 4, 5, 6, 8, 9, 10), (3, 7, 11)),
    'columns_3x4': ((0, 3, 6, 1, 4, 7, 2, 5, 8), (9, 10, 11)),
    'padded_rows_translation_last': ((0, 1, 2, 4, 5, 6, 8, 9, 10), (12, 13, 14)),
    'padded_columns_translation_last': ((0, 4, 8, 1, 5, 9, 2, 6, 10), (12, 13, 14)),
}


class RelationLimitError(bounds.BoundsLimitError):
    """A complete algebraic view exceeded its explicit work limit."""


def inspect(data, *, max_work=1000000):
    """Check fixed numeric equalities without fitting or selecting a formula.

    Complete describes diagnostic evaluation, including failed/unavailable
    relations. Original nonfinite bits remain available and no NaN JSON number
    is emitted. All layouts/tolerances are fixed; no data-dependent best case is
    promoted to a pose decoder. Input and work bounds include the source reader.
    """
    numeric = poses.inspect(data, max_work=max_work)
    used = numeric['work_units']

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise RelationLimitError('bone relation work limit exceeded')
        used += n

    result = dict(status='unsupported', profile=PROFILE, records=[],
        pose_interpretation='unknown', selected_hypotheses=[], inferred_animation_links=[],
        allocation_end=None, complete_format=False)
    charge()
    if numeric['status'] != 'complete':
        return dict(result, reason=numeric['reason'], work_units=used)

    counts = Counter()
    relation_counts = {}

    def compare(label, expected, observed, reason='nonfinite numeric candidate'):
        charge(1 + max(len(expected or ()), len(observed or ())))
        if (expected is None or observed is None
                or any(v is None or not math.isfinite(v) for v in expected + observed)):
            out = dict(status='unavailable', reason=reason, max_absolute_error=None,
                       max_tolerance_ratio=None)
        else:
            differences = [abs(a - b) for a, b in zip(expected, observed)]
            ratios = [difference / (ABS_TOLERANCE + REL_TOLERANCE * max(abs(a), abs(b)))
                      for difference, a, b in zip(differences, expected, observed)]
            maximum = max(ratios, default=0.0)
            out = dict(status='agrees' if maximum <= 1 else 'contradicts',
                       max_absolute_error=max(differences, default=0.0),
                       max_tolerance_ratio=maximum)
        counts[out['status']] += 1
        relation_counts.setdefault(label, Counter())[out['status']] += 1
        return out

    def rotation(q, ordering, conjugate):
        charge(16)
        if any(v is None for v in q):
            return None
        x, y, z, w = q if ordering == 'xyzw' else (q[1], q[2], q[3], q[0])
        norm = math.sqrt(x*x + y*y + z*z + w*w)
        if not norm:
            return None
        x, y, z, w = x/norm, y/norm, z/norm, w/norm
        if conjugate:
            x, y, z = -x, -y, -z
        return [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w),
                2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w),
                2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]

    def affine(linear, translation):
        if (linear is None or any(v is None for v in linear + translation)):
            return None
        return [linear[0], linear[1], linear[2], translation[0],
                linear[3], linear[4], linear[5], translation[1],
                linear[6], linear[7], linear[8], translation[2], 0., 0., 0., 1.]

    def multiply(a, b):
        charge(16)  # Each output cell has four fixed scalar products.
        if a is None or b is None:
            return None
        return [sum(a[r*4+k]*b[k*4+c] for k in range(4)) for r in range(4) for c in range(4)]

    # The stable source reader has already checked every ordinal, complete
    # named record, duplicate parent and per-ordinal parallel key. Reading the
    # positioned parent word here introduces no unqualified reference traversal.
    prepared = []
    for row in numeric['records']:
        charge(4)
        named = [v['ieee754_le_f32'] for v in row['named_numeric_candidates']]
        parallel = [v['ieee754_le_f32'] for v in row['parallel_numeric_candidates']]
        parent, = struct.unpack_from('<H', data, row['named_record_data_offset'] + 70)
        prepared.append(dict(source=row, q=named[:4], translation=named[4:7],
            scale=named[7:10], parallel=parallel, parent=None if parent == 0xffff else parent,
            layouts={label: affine([parallel[i] for i in linear], [parallel[i] for i in t])
                     for label, (linear, t) in LAYOUTS.items()}))
    records = []
    identity3 = [1., 0., 0., 0., 1., 0., 0., 0., 1.]
    for i, entry in enumerate(prepared):
        charge()
        q, t, scale, p = entry['q'], entry['translation'], entry['scale'], entry['parallel']
        evidence = {}
        norm2 = None if any(v is None for v in q) else sum(v*v for v in q)
        evidence['named_quaternion_squared_norm'] = compare('named_quaternion_squared_norm', [1.], [norm2])
        evidence['named_translation_equals_parallel_tail'] = compare('named_translation_equals_parallel_tail', t, p[12:15])
        candidates = {}
        for ordering in ('xyzw', 'wxyz'):
            for conjugate in (False, True):
                r = rotation(q, ordering, conjugate)
                for side in ('rows', 'columns'):
                    label = ordering + ('_conjugate' if conjugate else '_direct') + '_scale_' + side
                    charge(9)
                    candidates[label] = (None if r is None or any(v is None for v in scale) else
                        [r[j] * scale[j // 3 if side == 'rows' else j % 3] for j in range(9)])
        canonical = affine(candidates['xyzw_direct_scale_columns'], t)
        for layout, (indices, translation_indices) in LAYOUTS.items():
            linear = [p[j] for j in indices]
            translation = [p[j] for j in translation_indices]
            evidence[layout + '_translation_equals_named'] = compare(layout + '_translation_equals_named', t, translation)
            gram, determinant = None, None
            charge(36)
            if all(v is not None for v in linear):
                gram = [sum(linear[k*3+r]*linear[k*3+c] for k in range(3)) for r in range(3) for c in range(3)]
                a,b,c,d,e,f,g,h,j = linear
                determinant = a*(e*j-f*h)-b*(d*j-f*g)+c*(d*h-e*g)
            evidence[layout + '_orthogonal_columns'] = compare(layout + '_orthogonal_columns', identity3, gram)
            evidence[layout + '_determinant_one'] = compare(layout + '_determinant_one', [1.], [determinant])
            for candidate, expected in candidates.items():
                label = layout + '_linear_equals_' + candidate
                evidence[label] = compare(label, expected, linear,
                    reason='nonfinite numeric candidate or zero-length quaternion')
            if entry['parent'] is not None:
                parent_matrix = prepared[entry['parent']]['layouts'][layout]
                child_matrix = entry['layouts'][layout]
                for label, a, b in (('parent_times_named', parent_matrix, canonical),
                                    ('named_times_parent', canonical, parent_matrix)):
                    key = layout + '_' + label
                    evidence[key] = compare(key, multiply(a, b), child_matrix,
                        reason='nonfinite numeric candidate or zero-length quaternion')
        source = entry['source']
        records.append(dict(index=i, named_record_data_offset=source['named_record_data_offset'],
            parallel_data_offset=source['parallel_data_offset'], parent_index=entry['parent'],
            named_numeric_raw_u32=[v['raw_u32'] for v in source['named_numeric_candidates']],
            parallel_numeric_raw_u32=[v['raw_u32'] for v in source['parallel_numeric_candidates']],
            relations=evidence))
    result.update(status='complete', source_sha256=numeric['source_sha256'], byte_length=len(data),
        bone_count=numeric['bone_count'], records=records, counts=dict(counts),
        relation_counts={label: dict(value) for label, value in sorted(relation_counts.items())},
        tolerances=dict(absolute=ABS_TOLERANCE, relative=REL_TOLERANCE,
            comparison='abs(a-b) <= absolute + relative * max(abs(a),abs(b))'),
        canonical_parent_hypothesis='normalized xyzw quaternion, direct rotation, named scale on columns, named translation; both multiplication orders retained',
        quaternion_policy='normalize only the explicit candidate; retain raw squared-norm evidence and source bits',
        interpretation='fixed algebraic consistency only; no selected numeric codec, pose convention or ownership')
    result['work_units'] = used
    return result
