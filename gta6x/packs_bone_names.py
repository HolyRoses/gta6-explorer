"""Checked compact fragment-tree names and source-local bone ordinals.

Every terminal is reconciled with the independently checked native named table.
Original compact/named spellings and stored alternate keys are retained. This
does not infer zero-key semantics, a key exception, provider or animation owner.
"""
from __future__ import annotations

from collections import Counter
import struct

from . import names, packs_bones as bones, packs_skeleton_bounds as bounds

PROFILE = 'packs_compact_fragment_names_terminal_ordinals_v1'


def inspect(data, *, max_work=1000000):
    """Return the complete checked compact name/index map or an atomic refusal.

    Work includes the complete underlying table reader. Tree references address
    whole nodes, terminal slots cover an ordinal permutation, and every decoded
    spelling must match its target's exact/lower-ASCII literal and stored hash.
    Case variants and duplicate/colliding alternatives never select an owner.
    """
    base = bones.inspect(data, max_work=max_work)
    used = base['work_units']
    result = dict(status='unsupported', candidate_profile=PROFILE, nodes=[], records=[],
        allocation_end=None, complete_format=False, zero_key_meaning='unknown',
        inferred_animation_links=[], inferred_skeleton_providers=[])

    def charge(n=1):
        nonlocal used
        if n > max_work - used:
            raise bounds.BoundsLimitError('compact bone name work limit exceeded')
        used += n

    try:
        charge()
        if base['status'] != 'complete':
            raise ValueError('compact names require checked named table: ' + base['reason'])
        header = base['skeleton_header_data_offset']
        word, = struct.unpack_from('<Q', data, header + 72)
        start = word - bounds.BASE
        charge(3)
        if start < 64 or start > len(data) - 4:
            raise ValueError('compact name header exceeds source bounds')
        count, fragment_bytes = struct.unpack_from('<HH', data, start)
        if count != base['bone_count'] or fragment_bytes < 11:
            raise ValueError('compact name count/fragment extent disagrees with named table')
        length = fragment_bytes + 2 * count
        if start > len(data) - length:
            raise ValueError('compact name fragment/index extent exceeds source bounds')
        known = [(p['data_offset'], p['data_offset'] + p['byte_length'])
                 for p in base['header_path']['prefixes']]
        for key in ('record_array', 'parent_array', 'lookup'):
            row = base[key]
            known.append((row['data_offset'], row['data_offset'] + row['byte_length']))
        known.append((base['record_array']['count_prefix_data_offset'],
                      base['record_array']['data_offset']))
        known.extend((r['name_data_offset'], r['name_data_offset'] + r['name_byte_length'] + 1)
                     for r in base['records'])
        charge(len(known) + count)
        if any(start < end and at < start + length for at, end in known):
            raise ValueError('compact name extent overlaps a checked named-table region')
        values = list(struct.unpack_from(f'<{count}H', data, start + fragment_bytes))
        if sorted(values) != list(range(count)):
            raise ValueError('compact name terminal values are not a complete ordinal permutation')
        node_map, position = {}, 4
        while position < fragment_bytes:
            charge(3)
            if position > fragment_bytes - 7:
                raise ValueError('truncated compact name node header/terminator')
            sibling, child, value = struct.unpack_from('<HHh', data, start + position)
            end = data.find(b'\0', start + position + 6, start + fragment_bytes)
            if end < 0 or end - (start + position + 6) > bones.MAX_NAME_BYTES:
                raise ValueError('compact name fragment requires a bounded final NUL')
            raw = data[start + position + 6:end]
            if any(c < 32 or c > 126 for c in raw):
                raise ValueError('compact name fragment is not printable ASCII')
            charge(1 + (len(raw) + 15) // 16)
            node_map[position] = dict(data_offset=start + position,
                byte_length=end - (start + position) + 1,
                sibling_delta_u16=sibling, child_delta_u16=child,
                value_delta_i16=value, fragment=raw.decode('ascii'))
            position = end - start + 1
        stack, seen, cursor = [(4, '')], set(), 0
        records, counts = [], Counter()
        while stack:
            relative, prefix = stack.pop()
            charge(3)
            if relative not in node_map or relative in seen:
                raise ValueError('compact name tree references a partial, aliased or absent node')
            seen.add(relative)
            node = node_map[relative]
            literal = prefix + node['fragment']
            if len(literal) > bones.MAX_NAME_BYTES:
                raise ValueError('compact reconstructed name exceeds literal bound')
            charge(1 + (len(literal) + 15) // 16)
            delta = node['value_delta_i16']
            terminal = delta >= 0
            target = relative + delta if terminal else relative - delta
            if target != fragment_bytes + 2 * cursor or cursor >= count:
                raise ValueError('compact name value cursor disagrees with terminal traversal')
            node.update(terminal=terminal, value_cursor_data_offset=start + target,
                sibling_data_offset=(start + relative + node['sibling_delta_u16']
                                     if node['sibling_delta_u16'] else None),
                child_data_offset=(start + relative + node['child_delta_u16']
                                   if node['child_delta_u16'] else None))
            if terminal:
                charge(5)
                index = values[cursor]
                row = base['records'][index]
                stored_hash = int(row['stored_name_hash_u32'], 16)
                families = [label for label, function in
                    (('joaat_lower_ascii', names.joaat), ('joaat_exact_ascii', names.joaat_exact))
                    if function(literal) == stored_hash]
                exact = literal == row['name']
                lower_match = (literal.lower() == row['name'].lower()
                    and names.joaat(literal) == stored_hash)
                if not literal or not families or not (exact or lower_match):
                    raise ValueError('compact terminal spelling/hash disagrees with named ordinal')
                comparison = 'exact_literal' if exact else 'ascii_case_variant'
                counts[comparison] += 1
                counts['zero_alternate_key_terminals'] += row['alternate_key_u16'] == 0
                records.append(dict(index=index, terminal_order=cursor,
                    node_data_offset=start + relative,
                    value_slot_data_offset=start + fragment_bytes + 2 * cursor,
                    compact_name=literal, named_name=row['name'], comparison=comparison,
                    matching_name_hash_algorithms=families,
                    named_record_data_offset=row['data_offset'],
                    stored_name_hash_u32=row['stored_name_hash_u32'],
                    alternate_key_u16=row['alternate_key_u16'],
                    alternate_key_data_offset=row['alternate_key_data_offset']))
                cursor += 1
            elif not node['child_delta_u16']:
                raise ValueError('compact nonterminal has no child names')
            if node['sibling_delta_u16']:
                stack.append((relative + node['sibling_delta_u16'], prefix))
            if node['child_delta_u16']:
                stack.append((relative + node['child_delta_u16'], literal))
        if cursor != count or seen != node_map.keys():
            raise ValueError('compact tree does not cover every terminal/node')
        charge(len(node_map) + count)
        result.pop('candidate_profile')
        result.update(status='complete', profile=PROFILE,
            source_sha256=base['source_sha256'], byte_length=len(data),
            bone_count=count, skeleton_header_data_offset=header,
            compact_block=dict(reference_data_offset=header + 72,
                reference_bits=f'0x{word:016x}', data_offset=start, byte_length=length,
                fragment_byte_length=fragment_bytes, stored_name_count=count,
                ordinal_array_data_offset=start + fragment_bytes, ordinal_width=2,
                terminal_ordinals=values),
            nodes=list(node_map.values()), records=sorted(records, key=lambda row: row['index']),
            counts=dict(named_records=count, fragment_nodes=len(node_map), terminal_names=cursor,
                exact_literal_names=counts['exact_literal'],
                ascii_case_variant_names=counts['ascii_case_variant'],
                zero_alternate_key_terminals=counts['zero_alternate_key_terminals']),
            interpretation='checked compact-name to stored-ordinal relation; alternate zero meaning and ownership remain unknown')
    except bounds.BoundsLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    result['work_units'] = used
    return result
