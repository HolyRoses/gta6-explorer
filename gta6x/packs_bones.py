"""Stored named records, alternate keys and forest indices in native pack data.

Counts, name hashes, lookup membership and duplicate parent indices are checked
from the original bytes. Pose bytes, alternate-key algorithms, rig/animation
ownership and the complete containing allocation remain unknown.
"""
from __future__ import annotations

from collections import Counter
import struct

from . import names, packs_skeleton_bounds as bounds

PROFILE = 'packs_named_80byte_records_lookup_parent_forest_v1'
MAX_NAME_BYTES = 256
SENTINEL = 0xffff


class BoneLimitError(bounds.BoundsLimitError):
    """The complete table is refused on an explicit work/input limit."""


def inspect(data, *, max_work=1000000):
    """Return a checked named table/forest or an atomic unsupported view.

    All positions are original decompressed-source offsets. No marker search,
    cross-stream join, name dictionary, inferred allocation endpoint or external
    implementation is used. Counts are bounded before allocation or traversal.
    """
    if type(max_work) is not int or max_work < 1:
        raise ValueError('pack bone work limit must be a positive integer')
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('pack bone input must be bytes')
    if len(data) > bounds.MAX_BYTES:
        raise BoneLimitError('pack bone source exceeds input byte limit')
    path = bounds.inspect(data, max_work=max_work)
    used = path['work_units']
    result = dict(status='unsupported', candidate_profile=PROFILE, records=[], lookup_entries=[],
                  allocation_end=None, complete_format=False)

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise BoneLimitError('pack bone work limit exceeded')
        used += n

    try:
        if path['status'] != 'complete':
            raise ValueError('named table requires checked header path: ' + path['reason'])
        header = path['table_header_data_offset']
        marker, = struct.unpack_from('<Q', data, header + 16)
        counts = struct.unpack_from('<6H', data, header + 108)
        count = counts[0]
        charge(4)
        if marker != 1:
            raise ValueError('unsupported named-table header marker')
        if not count or counts[:3] != (count,) * 3:
            raise ValueError('named-table first three stored counts disagree or are zero')

        def span(pointer, length, label):
            charge()
            at = pointer - bounds.BASE
            if at < 64 or length < 0 or at > len(data) - length:
                raise ValueError(f'pack bone {label} exceeds source bounds or overlaps root prefix')
            return at

        def reference(relative, length, label):
            word, = struct.unpack_from('<Q', data, header + relative)
            return word, span(word, length, label)

        capacity, occupied = struct.unpack_from('<2I', data, header + 24)
        if not 0 < occupied == 2 * count <= capacity:
            raise ValueError('named-table lookup count/capacity does not reconcile with two keys per record')
        record_word, records_at = reference(40, count * 80, 'records')
        parent_word, parents_at = reference(64, count * 2, 'parent array')
        lookup_word, lookup_at = reference(32, capacity * 8, 'lookup')
        if records_at < 80:
            raise ValueError('named-table record count prefix overlaps root prefix')
        prefix_count, prefix_unknown = struct.unpack_from('<2Q', data, records_at - 16)
        if prefix_count != count:
            raise ValueError('named-table record prefix count differs from header')
        regions = [(p['data_offset'], p['data_offset'] + p['byte_length'], p['role']) for p in path['prefixes']]
        regions += [(records_at - 16, records_at, 'record_count_prefix'),
                    (records_at, records_at + count * 80, 'records'),
                    (parents_at, parents_at + count * 2, 'parent_array'),
                    (lookup_at, lookup_at + capacity * 8, 'lookup')]
        ordered = sorted(regions)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:])):
            raise ValueError('named-table checked regions overlap or alias')
        charge(len(regions) + count + capacity)
        parent_values = list(struct.unpack_from(f'<{count}H', data, parents_at))
        records = []
        for i in range(count):
            charge(4)
            at = records_at + 80 * i
            stored_hash, = struct.unpack_from('<I', data, at + 28)
            word, = struct.unpack_from('<Q', data, at + 48)
            name_at = span(word, 1, 'name')
            end = data.find(b'\0', name_at, min(len(data), name_at + MAX_NAME_BYTES + 1))
            if end < 0 or end == name_at or any(b < 32 or b > 126 for b in data[name_at:end]):
                raise ValueError('named-table record name requires bounded final-NUL ASCII')
            charge(1 + (end - name_at + 63) // 64)
            text = data[name_at:end].decode('ascii')
            algorithms = [label for label, algorithm in (('joaat_lower_ascii', names.joaat),
                                                          ('joaat_exact_ascii', names.joaat_exact))
                          if algorithm(text) == stored_hash]
            if not algorithms:
                raise ValueError('named-table stored name hash has no supported literal preimage')
            flags, next_sibling, parent, ordinal, alternate, unknown, subtree_end = struct.unpack_from('<I6H', data, at + 64)
            if ordinal != i:
                raise ValueError('named-table stored record index differs from array ordinal')
            if parent != parent_values[i] or (parent != SENTINEL and parent >= count):
                raise ValueError('named-table parent copy/range differs')
            records.append(dict(index=i, data_offset=at, byte_length=80,
                raw_record_hex=data[at:at + 80].hex(), name=text, name_data_offset=name_at,
                name_byte_length=end - name_at, name_reference_data_offset=at + 48,
                name_reference_bits=f'0x{word:016x}', stored_name_hash_u32=f'0x{stored_hash:08x}',
                name_hash_data_offset=at + 28, matching_name_hash_algorithms=algorithms,
                alternate_key_u16=alternate, alternate_key_data_offset=at + 74,
                parent_index=None if parent == SENTINEL else parent, raw_parent_u16=parent,
                parent_data_offset=at + 70, parent_copy_data_offset=parents_at + 2 * i,
                next_sibling_index=None if next_sibling == SENTINEL else next_sibling,
                raw_next_sibling_u16=next_sibling, subtree_end_index=subtree_end,
                flags_raw_u32=f'0x{flags:08x}', unknown_u16_4c=unknown,
                interpretation='checked named record/keys/forest indices; pose and rig ownership unknown'))

        # Stored parents are independently duplicated. Validate the forest and
        # the sibling/subtree columns iteratively, without recursive call depth
        # or unmetered per-node ancestor walks.
        charge(3 * count)
        children = [[] for _ in range(count)]
        roots = []
        for row in records:
            destination = roots if row['parent_index'] is None else children[row['parent_index']]
            destination.append(row['index'])
        for siblings in [roots] + children:
            for position, index in enumerate(siblings):
                charge()
                expected = siblings[position + 1] if position + 1 < len(siblings) else None
                if records[index]['next_sibling_index'] != expected:
                    raise ValueError('named-table next-sibling column contradicts parent forest')
        stack = [(index, False) for index in reversed(roots)]
        entered, postorder = set(), []
        while stack:
            charge()
            index, done = stack.pop()
            if done:
                postorder.append(index)
                continue
            if index in entered:
                raise ValueError('named-table parent forest cycles or aliases a record')
            entered.add(index)
            stack.append((index, True))
            stack.extend((child, False) for child in reversed(children[index]))
        if len(entered) != count:
            raise ValueError('named-table parent forest has an unreachable cycle')
        sizes, minima, ends = [1] * count, list(range(count)), list(range(1, count + 1))
        for index in postorder:
            charge()
            if minima[index] != index or ends[index] - index != sizes[index] or records[index]['subtree_end_index'] != ends[index]:
                raise ValueError('named-table subtree-end column contradicts contiguous parent forest')
            parent = records[index]['parent_index']
            if parent is not None:
                sizes[parent] += sizes[index]
                minima[parent] = min(minima[parent], minima[index])
                ends[parent] = max(ends[parent], ends[index])

        expected = Counter()
        for row in records:
            charge(2)
            expected[int(row['stored_name_hash_u32'], 16), row['index']] += 1
            expected[row['alternate_key_u16'], row['index']] += 1
        entries, empty_slots, observed = [], [], Counter()
        for slot in range(capacity):
            charge()
            at = lookup_at + 8 * slot
            key, index = struct.unpack_from('<II', data, at)
            if key == 0xffffffff:
                empty_slots.append(dict(slot_index=slot, data_offset=at, raw_index_u32=f'0x{index:08x}'))
                continue
            if index >= count:
                raise ValueError('named-table lookup index exceeds record count')
            roles = []
            if key == int(records[index]['stored_name_hash_u32'], 16):
                roles.append('stored_name_hash')
            if key == records[index]['alternate_key_u16']:
                roles.append('stored_alternate_key')
            if not roles:
                raise ValueError('named-table lookup key differs from target record keys')
            observed[key, index] += 1
            entries.append(dict(slot_index=slot, data_offset=at, key_u32=f'0x{key:08x}',
                                record_index=index, key_roles=roles))
        if len(entries) != occupied or observed != expected:
            raise ValueError('named-table lookup occupancy/key coverage differs from records')
        result.update(status='complete', profile=result.pop('candidate_profile'),
            source_sha256=path['source_sha256'], byte_length=len(data), work_units=used,
            header_path=path, skeleton_header_data_offset=header, bone_count=count,
            header=dict(marker_10_bits=f'0x{marker:016x}', stored_counts=list(counts),
                unknown_remaining_counts=list(counts[3:]),
                opaque_reference_words={f'0x{r:02x}': f'0x{struct.unpack_from("<Q", data, header + r)[0]:016x}' for r in (48, 56, 72, 80, 88)},
                unknown_signature_words=[f'0x{v:08x}' for v in struct.unpack_from('<3I', data, header + 96)],
                unknown_78_bits=f'0x{struct.unpack_from("<Q", data, header + 120)[0]:016x}'),
            record_array=dict(data_offset=records_at, byte_length=count * 80, stride=80,
                reference_bits=f'0x{record_word:016x}', count_prefix_data_offset=records_at - 16,
                count_u64=prefix_count, unknown_prefix_08_bits=f'0x{prefix_unknown:016x}'),
            records=records, parent_array=dict(data_offset=parents_at, byte_length=count * 2,
                reference_bits=f'0x{parent_word:016x}', raw_u16=parent_values),
            lookup=dict(data_offset=lookup_at, byte_length=capacity * 8,
                reference_bits=f'0x{lookup_word:016x}', capacity=capacity, entry_count=occupied,
                empty_key_u32='0xffffffff', empty_slots=empty_slots),
            lookup_entries=entries, root_indices=roots, forest_component_count=len(roots),
            alternate_key_algorithm='unknown', pose_decoding='unknown; raw record bytes only',
            inferred_animation_links=[],
            interpretation='checked named record table, stored key/index map and parent/sibling/subtree forest; animation/rig ownership unknown')
    except bounds.BoundsLimitError:
        raise
    except ValueError as exc:
        result.update(reason=str(exc), work_units=used)
    return result
