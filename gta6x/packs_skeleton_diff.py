"""Literal checked skeleton tables compared without rig or pose identity claims.

Unique literal names and their stored full hashes supply candidate alignment.
Original records, lookup alternatives and unknown words remain source-local.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import os
import stat
import struct

from . import packs_bones, packs_skeleton_bounds as bounds

MAX_INPUT_BYTES = 2 * bounds.MAX_BYTES
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_NODES = 2_000_000


class SkeletonDiffLimitError(ValueError):
    """The complete comparison cannot fit its processing or output limits."""


def _limit(value, maximum, label):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{label} must be an integer from 1 to {maximum}')


def compare(left, right, *, max_nodes=100000, max_input_bytes=MAX_INPUT_BYTES,
            max_output_bytes=MAX_OUTPUT_BYTES):
    """Compare original byte snapshots, or refuse without a successful prefix.

    Both entire named tables must satisfy the unchanged native reader. All raw
    record words and lookup entries are retained, including pointers and unknown
    values. Differences are literal, not transform/animation compatibility.
    Output bytes are bounded using compact sorted-key UTF-8 JSON serialization.
    """
    _limit(max_nodes, MAX_NODES, 'skeleton comparison node limit')
    _limit(max_input_bytes, MAX_INPUT_BYTES, 'skeleton comparison input byte limit')
    _limit(max_output_bytes, MAX_OUTPUT_BYTES, 'skeleton comparison output byte limit')
    if not isinstance(left, (bytes, bytearray)) or not isinstance(right, (bytes, bytearray)):
        raise ValueError('skeleton comparison requires source bytes')
    if max(len(left), len(right)) > bounds.MAX_BYTES or len(left) + len(right) > max_input_bytes:
        raise SkeletonDiffLimitError('skeleton comparison exceeds input byte limit')
    left, right = bytes(left), bytes(right)
    used = 0

    def charge(amount=1):
        nonlocal used
        if amount > max_nodes - used:
            raise SkeletonDiffLimitError('skeleton comparison exceeds shared node limit')
        used += amount

    charge(1 + sum(1 + (len(data) + 4095) // 4096 for data in (left, right)))
    tables = []
    for label, data in (('left', left), ('right', right)):
        if used >= max_nodes:
            raise SkeletonDiffLimitError('skeleton comparison exceeds shared node limit')
        table = packs_bones.inspect(data, max_work=max_nodes - used)
        charge(table['work_units'])
        if table['status'] != 'complete':
            raise ValueError(f'{label} skeleton table unsupported: {table["reason"]}')
        header_at = table['skeleton_header_data_offset']
        table['raw_table_header_hex'] = data[header_at:header_at + 128].hex()
        tables.append(table)

    groups = defaultdict(lambda: [[], []])
    name_counts, hash_counts, key_counts = [], [], []
    for side, table in enumerate(tables):
        nc, hc, kc = Counter(), Counter(), Counter()
        for row in table['records']:
            charge(4)
            groups[row['name'], row['stored_name_hash_u32']][side].append(row)
            nc[row['name']] += 1
            hc[row['stored_name_hash_u32']] += 1
            kc[row['alternate_key_u16']] += 1
        name_counts.append(nc); hash_counts.append(hc); key_counts.append(kc)

    def unique(row, side):
        return name_counts[side][row['name']] == hash_counts[side][row['stored_name_hash_u32']] == 1

    candidate_pairs = {}
    for (name, hashed), (a, b) in groups.items():
        charge()
        if len(a) == len(b) == 1 and unique(a[0], 0) and unique(b[0], 1):
            candidate_pairs[a[0]['index']] = b[0]['index']
    right_candidates = set(candidate_pairs.values())

    comparisons, counts = [], Counter()
    for (name, hashed), (a, b) in sorted(groups.items()):
        charge(1 + len(a) + len(b))
        item = dict(name=name, stored_name_hash_u32=hashed,
                    left_indices=[r['index'] for r in a], right_indices=[r['index'] for r in b])
        ambiguous = any(not unique(row, side) for side, rows in enumerate((a, b)) for row in rows)
        if ambiguous:
            item['status'] = 'ambiguous_unaligned'
        elif not a or not b:
            item['status'] = 'only_right' if b else 'only_left'
        else:
            av, bv = a[0], b[0]
            charge(23)
            aw, bw = (struct.unpack('<20I', bytes.fromhex(row['raw_record_hex'])) for row in (av, bv))
            ap, bp = av['parent_index'], bv['parent_index']
            if ap is None or bp is None:
                parent_relation = 'both_roots' if ap is bp else 'root_vs_record'
            elif ap in candidate_pairs and bp in right_candidates:
                parent_relation = ('same_unique_name_hash_candidate' if candidate_pairs[ap] == bp
                                   else 'different_unique_name_hash_candidates')
            else:
                parent_relation = 'unresolved_parent_candidates'
            item.update(status='equal_raw_record' if aw == bw else 'changed_raw_record',
                        alignment='unique literal name and full stored hash candidate; native identity unconfirmed',
                        changed_u32_word_indices=[i for i, (x, y) in enumerate(zip(aw, bw)) if x != y],
                        ordinal_changed=av['index'] != bv['index'],
                        alternate_key_changed=av['alternate_key_u16'] != bv['alternate_key_u16'],
                        left_parent_index=ap, right_parent_index=bp,
                        stored_parent_index_changed=ap != bp, parent_candidate_relation=parent_relation)
        comparisons.append(item)
        counts[item['status']] += 1

    alternatives = {}
    for side, label in enumerate(('left', 'right')):
        duplicates = []
        for kind, counter in (('literal_name', name_counts[side]), ('stored_name_hash', hash_counts[side]),
                              ('alternate_key_u16', key_counts[side])):
            for value, count in sorted(counter.items()):
                charge()
                if count > 1:
                    duplicates.append(dict(kind=kind, value=value, record_count=count))
        alternatives[label] = dict(duplicate_values=duplicates,
                                  zero_alternate_keys=key_counts[side][0])
    report = dict(format='gta6x-skeleton-diff-v1', status='complete',
                  sources=dict(left=tables[0], right=tables[1]),
                  source_bytes_equal=left == right,
                  raw_named_records_equal=[r['raw_record_hex'] for r in tables[0]['records']]
                                          == [r['raw_record_hex'] for r in tables[1]['records']],
                  comparisons=comparisons, alternatives=alternatives,
                  summary=dict(left_records=tables[0]['bone_count'], right_records=tables[1]['bone_count'],
                               candidate_pairs=len(candidate_pairs), comparison_groups=len(comparisons),
                               counts=dict(counts)),
                  work_units=used, semantic_compatibility='unconfirmed', allocation_end=None,
                  complete_format=False,
                  scope='Checked literal records, lookup and stored forest only; pointers and unknown '
                        'words remain raw. No pose, rig, provider or animation identity is inferred.')
    size = 0
    for chunk in json.JSONEncoder(sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                  allow_nan=False).iterencode(report):
        size += len(chunk.encode('utf-8'))
        if size > max_output_bytes:
            raise SkeletonDiffLimitError('skeleton comparison exceeds output byte limit')
    return report


def _path(value):
    try:
        value = os.fspath(value)
    except TypeError as exc:
        raise ValueError('skeleton comparison requires text file paths') from exc
    if not isinstance(value, str) or not value or '\0' in value:
        raise ValueError('skeleton comparison requires nonempty text file paths')
    return value


def _identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def compare_files(left_path, right_path, *, max_nodes=100000, max_input_bytes=MAX_INPUT_BYTES,
                  max_output_bytes=MAX_OUTPUT_BYTES, expected_sha256=None, protected_outputs=()):
    """Read two bounded regular snapshots with optional ordered SHA-256 pins.

    Same-file comparison is allowed. Output aliases, sizes and processing options
    are checked before payload reads; identities, sizes and change timestamps
    are rechecked on open and after reading.
    This function never writes, scans archives or trusts persisted metadata.
    """
    _limit(max_nodes, MAX_NODES, 'skeleton comparison node limit')
    _limit(max_input_bytes, MAX_INPUT_BYTES, 'skeleton comparison input byte limit')
    _limit(max_output_bytes, MAX_OUTPUT_BYTES, 'skeleton comparison output byte limit')
    paths = [_path(left_path), _path(right_path)]
    if expected_sha256 is None:
        expected_sha256 = (None, None)
    elif (not isinstance(expected_sha256, (list, tuple)) or len(expected_sha256) != 2
          or any(not isinstance(h, str) or len(h) != 64
                 or any(c not in '0123456789abcdef' for c in h) for h in expected_sha256)):
        raise ValueError('skeleton comparison expects two lowercase SHA-256 pins')
    if not isinstance(protected_outputs, (list, tuple)) or len(protected_outputs) > 1024:
        raise ValueError('skeleton comparison outputs require a bounded path list')
    outputs = [_path(p) for p in protected_outputs]
    info = [os.stat(p) for p in paths]
    if any(not stat.S_ISREG(row.st_mode) for row in info):
        raise ValueError('skeleton comparison inputs must be regular files')
    ids = {(r.st_dev, r.st_ino) for r in info}
    resolved = {os.path.realpath(p) for p in paths}
    for output in outputs:
        if os.path.realpath(output) in resolved:
            raise ValueError('skeleton comparison output aliases an input')
        try:
            row = os.stat(output)
        except FileNotFoundError:
            continue
        if (row.st_dev, row.st_ino) in ids:
            raise ValueError('skeleton comparison output aliases an input')
    sizes = [r.st_size for r in info]
    if max(sizes) > bounds.MAX_BYTES or sum(sizes) > max_input_bytes:
        raise SkeletonDiffLimitError('skeleton comparison files exceed input byte limit')
    if max_nodes < 1 + sum(1 + (size + 4095) // 4096 for size in sizes):
        raise SkeletonDiffLimitError('skeleton comparison verification exceeds node limit')
    snapshots = []
    for path, before, expected in zip(paths, info, expected_sha256):
        with open(path, 'rb') as handle:
            now = os.fstat(handle.fileno())
            if not stat.S_ISREG(now.st_mode) or _identity(now) != _identity(before):
                raise ValueError('skeleton comparison input changed after preflight')
            data = handle.read(before.st_size + 1)
            if _identity(os.fstat(handle.fileno())) != _identity(before):
                raise ValueError('skeleton comparison input changed during read')
        if _identity(os.stat(path)) != _identity(before):
            raise ValueError('skeleton comparison input path changed during read')
        if len(data) != before.st_size:
            raise ValueError('skeleton comparison input size changed during read')
        if expected is not None and hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('skeleton comparison input SHA-256 mismatch')
        snapshots.append(data)
    return compare(*snapshots, max_nodes=max_nodes, max_input_bytes=max_input_bytes,
                   max_output_bytes=max_output_bytes)
