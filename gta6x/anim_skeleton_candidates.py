"""Source-scoped key-set compatibility, without animation skeleton ownership.

This compares complete metadata from the native table and channel readers. The
caller must qualify and pin those producers and reports. No payload is scanned,
no cross-file reference is invented, and no compatible table is selected as owner.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import struct

from . import names

PROFILE = 'source_scoped_animation_table_key_compatibility_v1'


def inspect(queries, tables, *, max_work=4000000):
    """Compare positioned discovery rows with all supplied native table views.

    Missing keys contradict only the explicit same-key-namespace hypothesis for
    the supplied table cohort. Per-kind scopes and optional whole-dictionary
    unions are separate hypotheses. A zero-only scope is uninformative rather
    than compatible with every table. Unknown tables contribute no guessed keys.
    """
    if type(max_work) is not int or max_work < 1:
        raise ValueError('skeleton compatibility work limit must be positive')
    used = 0

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise ValueError('skeleton compatibility work limit exceeded')
        used += n

    def uint(value, bits=64):
        if type(value) is not int or not 0 <= value < 1 << bits:
            raise ValueError('invalid full-width unsigned skeleton comparison word')
        return value

    def hash_value(value):
        if not isinstance(value, str) or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            raise ValueError('complete source SHA-256 required')
        return value

    def rows(value):
        if not isinstance(value, list):
            raise ValueError('complete source row list required')
        charge(len(value))
        return value

    charge()
    if any(not isinstance(v, dict) or v.get('role') != 'discovery' for v in (queries, tables)):
        raise ValueError('only explicitly qualified discovery metadata accepted')
    native, unsupported, seen_sources, source_hashes = [], [], set(), {}
    for view in rows(tables.get('sources')):
        if not isinstance(view, dict):
            raise ValueError('invalid native table view')
        source = view.get('source')
        if not isinstance(source, dict) or source.get('role') != 'discovery' or source.get('archive') != 'packs.rpf':
            raise ValueError('native table requires original packs discovery source')
        offset, h, size = uint(source.get('offset')), hash_value(source.get('sha256')), uint(source.get('size'))
        identity = offset, h
        if offset in source_hashes and source_hashes[offset] != h:
            raise ValueError('one physical packs source has conflicting payload hashes')
        source_hashes[offset] = h
        if identity in seen_sources or not size:
            raise ValueError('duplicate or empty native table source')
        seen_sources.add(identity)
        if view.get('status') == 'unsupported':
            if not isinstance(view.get('reason'), str) or not view['reason'] or view.get('records'):
                raise ValueError('unsupported source requires an atomic empty view and reason')
            unsupported.append(dict(source_offset=offset, source_sha256=h, reason=view['reason']))
            continue
        if (view.get('status') != 'complete' or view.get('source_sha256') != h
                or view.get('byte_length') != size or view.get('complete_format') is not False
                or view.get('allocation_end') is not None):
            raise ValueError('changed or unsupported native bounded-table view')
        header = uint(view.get('skeleton_header_data_offset'))
        start = uint(view.get('record_array', {}).get('data_offset'))
        records, count = rows(view.get('records')), uint(view.get('bone_count'), 16)
        if (not count or len(records) != count or start < 80 or header < 64
                or start > size - count * 80 or header > size - 128):
            raise ValueError('native bounded table count or extent differs')
        keys, forest, key_records = set(), [], defaultdict(list)
        for i, row in enumerate(records):
            if not isinstance(row, dict):
                raise ValueError('invalid native named record')
            at = uint(row.get('data_offset'))
            raw_hex, literal = row.get('raw_record_hex'), row.get('name')
            if (type(row.get('index')) is not int or row['index'] != i or at != start + 80 * i
                    or row.get('byte_length') != 80 or not isinstance(raw_hex, str) or len(raw_hex) != 160):
                raise ValueError('native complete record position or ordinal differs')
            try:
                raw = bytes.fromhex(raw_hex)
            except ValueError as exc:
                raise ValueError('invalid native complete record bits') from exc
            if len(raw) != 80:
                raise ValueError('native complete record bits differ')
            if (not isinstance(literal, str) or not literal or len(literal) > 256
                    or not literal.isascii() or any(ord(c) < 32 or ord(c) > 126 for c in literal)):
                raise ValueError('bounded complete literal name required')
            name_at = uint(row.get('name_data_offset'))
            stored, = struct.unpack_from('<I', raw, 28)
            name_word, = struct.unpack_from('<Q', raw, 48)
            sibling, parent, ordinal, alternate, _, end = struct.unpack_from('<6H', raw, 68)
            if (row.get('stored_name_hash_u32') != f'0x{stored:08x}'
                    or row.get('name_hash_data_offset') != at + 28
                    or row.get('alternate_key_data_offset') != at + 74
                    or row.get('alternate_key_u16') != alternate
                    or row.get('raw_parent_u16') != parent or row.get('raw_next_sibling_u16') != sibling
                    or row.get('subtree_end_index') != end or ordinal != i
                    or row.get('name_reference_data_offset') != at + 48
                    or row.get('name_reference_bits') != f'0x{name_word:016x}'
                    or row.get('name_byte_length') != len(literal)
                    or name_word != 0x50000000 + name_at or name_at < 64 or name_at > size - len(literal) - 1
                    or (parent != 0xffff and parent >= count)
                    or (sibling != 0xffff and sibling >= count) or end > count):
                raise ValueError('native record metadata differs from complete stored fields')
            if stored not in (names.joaat(literal), names.joaat_exact(literal)):
                raise ValueError('native stored name key has no supported literal preimage')
            charge(3 + (len(literal) + 63) // 64)
            keys.add(stored)
            key_records[stored].append(i)
            forest.append((stored, parent, sibling, end))
        native.append(dict(source_offset=offset, source_sha256=h, table_header_offset=header,
            bone_count=count, record_array_offset=start, keys=tuple(sorted(keys)), forest=tuple(forest),
            key_record_indices=[dict(key_u32=k, record_indices=v) for k, v in sorted(key_records.items())]))
    native.sort(key=lambda t: (t['source_offset'], t['source_sha256'], t['table_header_offset']))
    unsupported.sort(key=lambda s: (s['source_offset'], s['source_sha256']))
    charge(4 * len(native))
    key_profiles = sorted({t['keys'] for t in native})
    forest_profiles = sorted({t['forest'] for t in native})
    key_profile_ids = {key: i for i, key in enumerate(key_profiles)}
    forest_profile_ids = {key: i for i, key in enumerate(forest_profiles)}
    index = defaultdict(set)
    for i, table in enumerate(native):
        charge(len(table['keys']) + 1)
        table['index'] = i
        table['key_profile_index'] = key_profile_ids[table['keys']]
        table['forest_profile_index'] = forest_profile_ids[table['forest']]
        del table['forest']
        for key in table.pop('keys'):
            index[key].add(i)

    def compatibility(raw_rows):
        charge(len(raw_rows))
        keys = sorted({w[0] for w in raw_rows} - {0})
        absent = [key for key in keys if key not in index]
        candidates = set()
        if keys and not absent:
            candidates = set(index[keys[0]])
            charge(len(candidates))
            for key in keys[1:]:
                charge(1 + min(len(candidates), len(index[key])))
                candidates.intersection_update(index[key])
        selected = sorted(candidates)
        charge(len(keys) + len(selected))
        return dict(nonzero_word0_keys=keys, zero_word0_rows=sum(w[0] == 0 for w in raw_rows),
            row_count=len(raw_rows), unmatched_cohort_keys=absent, compatible_table_indices=selected,
            compatible_key_profile_indices=sorted({native[i]['key_profile_index'] for i in selected}),
            compatible_forest_profile_indices=sorted({native[i]['forest_profile_index'] for i in selected}),
            status=('uninformative_zero_only' if not keys else 'compatible_key_sets_only' if selected
                    else 'cohort_key_absence' if absent else 'cohort_cooccurrence_contradiction'),
            ownership='unresolved; compatibility and contradiction apply only to the tested key-set hypothesis')

    def scopes(raw_rows):
        grouped = defaultdict(list)
        for row in raw_rows:
            grouped[row[1]].append(row)
        return dict(all_raw_kinds=compatibility(raw_rows), by_raw_kind=[dict(raw_word1_u32=k,
            **compatibility(grouped[k])) for k in sorted(grouped)])

    animations, dictionaries, seen_animations, animation_source_hashes = [], {}, set(), {}
    for query in rows(queries.get('animations')):
        if not isinstance(query, dict) or query.get('role', 'discovery') != 'discovery':
            raise ValueError('invalid discovery animation query')
        offset, h = uint(query.get('source_offset')), hash_value(query.get('source_sha256'))
        if offset in animation_source_hashes and animation_source_hashes[offset] != h:
            raise ValueError('one physical animation source has conflicting payload hashes')
        animation_source_hashes[offset] = h
        at, owner = uint(query.get('animation_offset')), uint(query.get('dictionary_offset'))
        identity = offset, h, at
        if identity in seen_animations or min(at, owner) < 112:
            raise ValueError('duplicate or invalid positioned animation')
        seen_animations.add(identity)
        raw_rows, previous, first = [], None, None
        for i, row in enumerate(rows(query.get('binding_rows'))):
            if not isinstance(row, dict) or type(row.get('index')) is not int or row['index'] != i:
                raise ValueError('animation counted row order differs')
            pos = uint(row.get('data_offset'))
            words = row.get('words')
            if not isinstance(words, list) or len(words) != 3:
                raise ValueError('complete raw animation triple required')
            raw = tuple(uint(w, 32) for w in words)
            if first is None:
                first = pos
            if pos < 112 or pos != first + 12 * i or (previous is not None and previous >= (raw[1], raw[0])):
                raise ValueError('animation counted row extent or raw-key ordering differs')
            previous = raw[1], raw[0]
            raw_rows.append(raw)
        dictionary = offset, h, owner
        identifier = query.get('dictionary_identifier')
        if (not isinstance(identifier, str) or not 0 < len(identifier) <= 512
                or not identifier.isascii() or any(ord(c) < 32 or ord(c) > 126 for c in identifier)):
            raise ValueError('positioned dictionary identifier required')
        if dictionary in dictionaries and dictionaries[dictionary]['identifier'] != identifier:
            raise ValueError('one positioned dictionary has conflicting identifiers')
        dictionary_row = dictionaries.setdefault(dictionary, dict(identifier=identifier, rows=[], members=[]))
        dictionary_row['rows'].extend(raw_rows)
        dictionary_row['members'].append(at)
        view = scopes(raw_rows)
        swapped = [(int.from_bytes(w[0].to_bytes(4, 'little'), 'big'), w[1], w[2]) for w in raw_rows]
        wrong = [(w[1], w[0], w[2]) for w in raw_rows]
        animations.append(dict(source_offset=offset, source_sha256=h, animation_offset=at,
            dictionary_offset=owner, dictionary_identifier=identifier, scopes=view,
            controls=dict(byte_swapped_word0=compatibility(swapped), wrong_word1_as_key=compatibility(wrong))))
    animations.sort(key=lambda a: (a['source_offset'], a['source_sha256'], a['animation_offset']))
    dictionary_views = []
    for (offset, h, at), group in sorted(dictionaries.items()):
        charge(len(group['members']))
        dictionary_views.append(dict(source_offset=offset, source_sha256=h, dictionary_offset=at,
            dictionary_identifier=group['identifier'], member_animation_offsets=sorted(group['members']),
            optional_hypothesis='all supplied member keys share one key namespace and one table; not an ownership invariant',
            scopes=scopes(group['rows'])))
    def summary(views):
        outcomes, kinds = Counter(), defaultdict(Counter)
        for view in views:
            charge(1 + len(view['scopes']['by_raw_kind']))
            outcomes[view['scopes']['all_raw_kinds']['status']] += 1
            for scope in view['scopes']['by_raw_kind']:
                kinds[scope['raw_word1_u32']][scope['status']] += 1
        return dict(views=len(views), all_raw_kind_outcomes=dict(sorted(outcomes.items())),
            by_raw_kind_outcomes={str(k): dict(sorted(c.items())) for k, c in sorted(kinds.items())})
    animation_summary, dictionary_summary = summary(animations), summary(dictionary_views)
    return dict(format=PROFILE, role='discovery', counts=dict(native_tables=len(native),
        unsupported_sources=len(unsupported), named_records=sum(t['bone_count'] for t in native),
        distinct_key_profiles=len(key_profiles), distinct_forest_profiles=len(forest_profiles)),
        animation_summary=animation_summary, dictionary_summary=dictionary_summary,
        tables=native, unsupported_sources=unsupported, animations=animations, dictionaries=dictionary_views,
        work_units=used, inferred_animation_owners=[], inferred_rig_providers=[],
        evidence='Positioned stored-key compatibility only. Cohort gaps, unknown namespaces and mixed dictionaries cannot establish or exclude native ownership.')
