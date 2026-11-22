"""Observed RBF rig-set rows and exact-string associations.

Field labels come from the supported tree itself. They do not establish rig
execution, animation/bone relationships, numeric types or priority ordering.
The generic RBF tree remains the source of raw tokens and bytes.
"""
from __future__ import annotations

from collections import Counter

from . import rbf

PROFILE = 'observed_rbf_rig_sets_v1'


def inspect_tree(tree, *, max_nodes=100000, name=None, rig=None):
    """Return a complete candidate inventory or an explicit unsupported view.

    The whole source tree is checked before filtering. ``name`` is a literal,
    case-sensitive substring of a key; ``rig`` is an exact literal Rig value.
    Duplicate keys and repeated rows retain source identity. The output budget
    counts the view, set/entry rows, reverse-index rows and occurrence rows.
    Exhaustion raises RbfLimitError; no prefix is returned.
    """
    if type(max_nodes) is not int or max_nodes < 1:
        raise ValueError('rig-set max_nodes must be a positive integer')
    if any(value is not None and not isinstance(value, str) for value in (name, rig)):
        raise ValueError('rig-set filters must be text')
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, rig_sets=[], rig_index=[])
    try:
        if (not isinstance(tree, dict) or tree.get('format') != 'gta6x-rbf0-tree-v1'
                or tree.get('status') != 'complete'):
            raise ValueError('rig sets require a complete native RBF tree')
        nodes = tree.get('nodes')
        length = tree.get('byte_length')
        if (not isinstance(nodes, list) or not nodes or type(length) is not int
                or not 8 <= length <= rbf.MAX_BYTES or tree.get('consumed_bytes') != length):
            raise ValueError('unsupported rig-set source tree bounds')
        descriptors = tree.get('descriptors')
        if not isinstance(descriptors, list):
            raise ValueError('unsupported rig-set descriptor table')
        seen, seen_descriptors = set(), set()

        def take(index, parent, role, kind, label=None):
            if type(index) is not int or not 0 <= index < len(nodes) or index in seen:
                raise ValueError('duplicate, cyclic or invalid rig-set node reference')
            node = nodes[index]
            if (not isinstance(node, dict) or type(node.get('index')) is not int or node.get('index') != index
                    or node.get('parent_index') != parent
                    or (parent is not None and type(node.get('parent_index')) is not int)
                    or node.get('role') != role
                    or node.get('kind') != kind or (label is not None and node.get('name') != label)):
                raise ValueError(f'unsupported rig-set {label or kind} node profile')
            at, size = node.get('data_offset'), node.get('byte_length')
            if (type(at) is not int or type(size) is not int or at < 8 or size < 2
                    or at > length - size):
                raise ValueError('rig-set source node span exceeds tree bounds')
            if parent is not None:
                p = nodes[parent]
                if at <= p['data_offset'] or at + size >= p['data_offset'] + p['byte_length']:
                    raise ValueError('rig-set child span exceeds parent bounds')
            if kind != 'object' and ('attributes' in node or 'children' in node):
                raise ValueError('unexpected member references on rig-set leaf')
            if kind == 'bytes':
                if node.get('token_bits') != '0xfffd':
                    raise ValueError('rig-set byte leaf token differs from its kind')
            else:
                di = node.get('descriptor_index')
                code = {'object': '0x0', 'text': '0x6', 'raw64': '0x1'}[kind]
                if (type(di) is not int or not 0 <= di < len(descriptors)
                        or not isinstance(descriptors[di], dict)
                        or type(descriptors[di].get('index')) is not int or descriptors[di].get('index') != di
                        or descriptors[di].get('type_code') != code
                        or descriptors[di].get('name') != node.get('name')
                        or node.get('type_code') != code
                        or node.get('token_bits') != f'0x{(int(code, 16) << 12) | di:04x}'):
                    raise ValueError('rig-set name descriptor differs from its node')
                seen_descriptors.add(di)
            seen.add(index)
            return node

        def obj(index, parent, role, label, attribute_names, child_names=None):
            node = take(index, parent, role, 'object', label)
            attrs, children = node.get('attributes'), node.get('children')
            if (node.get('reserved_bits') != '0x00000000'
                    or not isinstance(attrs, list) or not isinstance(children, list)):
                raise ValueError('unsupported rig-set object framing')
            def labels(indices):
                out = []
                last = node['data_offset']
                for i in indices:
                    if type(i) is not int or not 0 <= i < len(nodes) or not isinstance(nodes[i], dict):
                        raise ValueError('invalid rig-set object member')
                    child = nodes[i]
                    at = child.get('data_offset')
                    if type(at) is not int or at <= last:
                        raise ValueError('rig-set members differ from source order')
                    last = at
                    out.append(child.get('name'))
                return out
            if labels(attrs) != list(attribute_names):
                raise ValueError(f'unsupported rig-set {label} attributes')
            names = labels(children)
            last_end = node['data_offset']
            for i in attrs + children:
                member = nodes[i]
                if member['data_offset'] < last_end:
                    raise ValueError('overlapping rig-set object members')
                size = member.get('byte_length')
                if type(size) is not int or size < 2:
                    raise ValueError('invalid rig-set member byte length')
                last_end = member['data_offset'] + size
            if child_names is not None and names != list(child_names):
                raise ValueError(f'unsupported rig-set {label} children or field order')
            return node

        def text_field(index, parent, label):
            wrapper = obj(index, parent, 'child', label, [], [None])
            leaf = take(wrapper['children'][0], index, 'child', 'bytes')
            value, raw, count = leaf.get('text_candidate'), leaf.get('value_hex'), leaf.get('value_byte_length')
            if (not isinstance(value, str) or '\0' in value or not isinstance(raw, str)
                    or type(count) is not int or not 1 <= count <= rbf.MAX_BYTES
                    or len(raw) != count * 2 or leaf['byte_length'] != count + 6
                    or leaf.get('value_data_offset') != leaf['data_offset'] + 6):
                raise ValueError(f'unsupported rig-set {label} text leaf')
            try:
                exact = bytes.fromhex(raw) == value.encode('utf-8') + b'\0'
            except (ValueError, UnicodeEncodeError):
                exact = False
            if not exact:
                raise ValueError(f'rig-set {label} text candidate does not match raw bytes')
            return value, leaf['index']

        root = obj(tree.get('root_index'), None, 'root', 'rage__crRigSetManager', [], ['RigSet'])
        sets = obj(root['children'][0], root['index'], 'child', 'RigSet', [])
        source_sets, total_entries = [], 0
        for set_index in sets['children']:
            row = obj(set_index, sets['index'], 'child', 'Item', ['key'], ['Entries'])
            key = take(row['attributes'][0], set_index, 'attribute', 'text', 'key')
            if not isinstance(key.get('text'), str) or '\0' in key['text']:
                raise ValueError('unsupported rig-set key text')
            entries = obj(row['children'][0], set_index, 'child', 'Entries', [])
            source_entries = []
            for entry_index in entries['children']:
                entry = obj(entry_index, entries['index'], 'child', 'Item', [],
                            ['Dictionary', 'Rig', 'Group', 'Priority'])
                fields, sources = {}, {}
                for field, field_index in zip(('Dictionary', 'Rig', 'Group'), entry['children'][:3]):
                    fields[field], sources[field] = text_field(field_index, entry_index, field)
                priority = take(entry['children'][3], entry_index, 'child', 'raw64', 'Priority')
                bits = priority.get('value_bits')
                try:
                    valid = isinstance(bits, str) and len(bits) == 18 and bits[:2] == '0x' and all(c in '0123456789abcdefABCDEF' for c in bits[2:])
                except ValueError:
                    valid = False
                if not valid:
                    raise ValueError('unsupported rig-set Priority raw bits')
                fields['Priority_bits'] = bits
                sources['Priority'] = priority['index']
                source_entries.append((entry_index, fields, sources))
            source_sets.append((set_index, key['text'], key['index'], entries['index'], source_entries))
            total_entries += len(source_entries)
        if len(seen_descriptors) != len(descriptors):
            raise ValueError('unaccounted rig-set name descriptors')
        if len(seen) != len(nodes):
            raise ValueError('unaccounted nodes outside supported rig-set profile')
        selected, selected_rigs = [], set()
        for set_index, key, key_index, entries_index, entries in source_sets:
            if name is not None and name not in key:
                continue
            entries = [entry for entry in entries if rig is None or entry[1]['Rig'] == rig]
            if rig is not None and not entries:
                continue
            selected.append((set_index, key, key_index, entries_index, entries))
            selected_rigs.update(entry[1]['Rig'] for entry in entries)
        count = sum(len(row[4]) for row in selected)
        needed = 1 + len(selected) + count * 2 + len(selected_rigs)
        if needed > max_nodes:
            raise rbf.RbfLimitError('rig-set output exceeds node limit')
        normalized, reverse = [], {}
        key_counts = Counter(row[1] for row in source_sets)
        for set_index, key, key_index, entries_index, entries in selected:
            output = dict(node_index=set_index, key=key, key_node_index=key_index,
                          entries_node_index=entries_index, entries=[])
            for entry_index, fields, sources in entries:
                output['entries'].append(dict(node_index=entry_index, fields=fields, source_nodes=sources))
                reverse.setdefault(fields['Rig'], []).append(dict(rig_set_node_index=set_index,
                    entry_node_index=entry_index, rig_node_index=sources['Rig']))
            normalized.append(output)
        index = [dict(rig=value, occurrences=occurrences) for value, occurrences in sorted(reverse.items())]
        result.update(status='complete', interpretation='literal tree-field associations; runtime meanings unknown',
            profile=result.pop('candidate_profile'), source_sha256=tree.get('sha256'),
            filters=dict(name_contains=name, rig_equals=rig), rig_sets=normalized, rig_index=index,
            summary=dict(nodes=needed, source_tree_nodes=len(nodes), source_rig_sets=len(source_sets),
                source_entries=total_entries, duplicate_source_keys=sum(n - 1 for n in key_counts.values()),
                selected_rig_sets=len(selected), selected_entries=count, distinct_selected_rigs=len(reverse)))
    except rbf.RbfLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
