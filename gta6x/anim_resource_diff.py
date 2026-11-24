"""Literal native 0DRP declarations compared without schema/provider claims.

Only unique high-ID same-kind name hashes provide candidate alignment. Complete
raw headers and members remain available; content fingerprints omit only
the independently established stored member-table pointer, never unknown words.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import os
import stat
import struct

from . import anim_resources

MAX_SOURCE_BYTES = anim_resources.MAX_RESOURCE
MAX_INPUT_BYTES = 2 * MAX_SOURCE_BYTES
MAX_NODES = 2_000_000


class AnimationDiffLimitError(ValueError):
    """The complete source comparison exceeds its explicit limits."""


def _limit(value, upper, label):
    if type(value) is not int or not 1 <= value <= upper:
        raise ValueError(f'{label} must be an integer from 1 to {upper}')


class _Budget:
    def __init__(self, maximum):
        _limit(maximum, MAX_NODES, 'animation comparison node limit')
        self.maximum, self.used = maximum, 0

    def charge(self, amount=1):
        if amount > self.maximum - self.used:
            raise AnimationDiffLimitError('animation comparison exceeds shared node budget')
        self.used += amount


def _words(values, widths):
    return [f'0x{value:0{width // 4}x}' for value, width in zip(values, widths)]


def _inventory(data, budget):
    budget.charge(1 + 2 * ((len(data) + 4095) // 4096))
    try:
        metadata = anim_resources.parse_resource(data, max_nodes=budget.maximum - budget.used)
    except anim_resources.ResourceLimitError as exc:
        raise AnimationDiffLimitError(str(exc)) from exc
    budget.charge(metadata['summary']['nodes'])
    declarations = []
    for kind, rows, code, widths, pointer_index, member_name in (
            ('structure', metadata['structures'], '<IIIIQIHH', [32, 32, 32, 32, 64, 32, 16, 16], 4, 'fields'),
            ('enum', metadata['enums'], '<IIQII', [32, 32, 64, 32, 32], 2, 'members')):
        for row in rows:
            budget.charge(3)
            position = row['data_offset']
            size = struct.calcsize(code)
            header = struct.unpack_from(code, data, position)
            if f'0x{header[0]:08x}' != row['hash']:
                raise ValueError('animation declaration differs from its parsed name hash')
            entries = []
            raw_entries = []
            for i, member in enumerate(row[member_name]):
                budget.charge(3)
                at = member['data_offset']
                values = struct.unpack_from('<IIII' if kind == 'structure' else '<QII', data, at)
                member_widths = [32, 32, 32, 32] if kind == 'structure' else [64, 32, 32]
                if kind == 'structure':
                    expected = (int(member['hash'], 16), member['field_offset'],
                                int(member['type_word'], 16), int(member['unknown_0c'], 16))
                else:
                    expected = (int(member['value_bits'], 16), int(member['hash'], 16),
                                int(member['unknown_0c'], 16))
                if values != expected:
                    raise ValueError('animation declaration member differs from parsed source words')
                raw_entries.append(values)
                entries.append(dict(index=i, hash=member['hash'], data_offset=at,
                    byte_length=16, raw_words=_words(values, member_widths), word_widths=member_widths))
            retained = [v for i, v in enumerate(header) if i != pointer_index]
            content = dict(format='gta6x-native-declaration-content-v1', kind=kind,
                           header_words_without_member_pointer=retained, entries=raw_entries)
            fingerprint = hashlib.sha256(json.dumps(content, sort_keys=True,
                separators=(',', ':')).encode('ascii')).hexdigest()
            declarations.append(dict(index=len(declarations), kind=kind, hash=row['hash'],
                declaration_index=row['index'], data_offset=position, byte_length=size,
                raw_header_words=_words(header, widths), header_word_widths=widths,
                excluded_pointer_word_index=pointer_index,
                content_sha256=fingerprint, entries=entries,
                _header=retained, _entries=raw_entries))
    budget.charge(4 + len(metadata['blocks']))
    source = dict(byte_length=len(data), sha256=metadata['sha256'],
                  metadata_status=metadata['status'], native_checksum_verified=False,
                  complete_format=False, allocation_end=None,
                  resource_header=metadata['header'], tables=metadata['tables'],
                  block_directory=metadata['blocks'])
    return declarations, source


def _entry_changes(left, right, budget):
    groups = defaultdict(lambda: [[], []])
    for side, rows in enumerate((left['entries'], right['entries'])):
        for row in rows:
            budget.charge()
            groups[row['hash']][side].append(row)
    changes = []
    for name, (a, b) in sorted(groups.items()):
        budget.charge(1 + len(a) + len(b))
        item = dict(hash=name, left_indices=[r['index'] for r in a], right_indices=[r['index'] for r in b])
        if not a or not b:
            item['status'] = 'only_right' if b else 'only_left'
        elif int(name, 16) < 0x10000:
            item['status'] = 'file_local_unaligned'
        elif len(a) != 1 or len(b) != 1:
            item['status'] = 'ambiguous_unaligned'
        else:
            av, bv = a[0], b[0]
            budget.charge(1 + len(av['raw_words']))
            item.update(status='equal_content' if av['raw_words'] == bv['raw_words'] else 'changed_content',
                alignment='unique same-hash candidate; member identity unconfirmed',
                ordinal_changed=av['index'] != bv['index'],
                changed_word_indices=[i for i, (x, y) in enumerate(zip(av['raw_words'], bv['raw_words'])) if x != y])
        changes.append(item)
    return changes


def compare(left, right, *, max_nodes=100000, max_input_bytes=MAX_INPUT_BYTES,
            max_source_bytes=MAX_SOURCE_BYTES):
    """Compare complete supplied byte sequences, without requiring full resource semantics.

    All original fields/member order remain available. Content fingerprints
    exclude known table-pointer positions only. Body data is not decoded or
    compared as schema, and same-hash alignment does not establish native identity.
    """
    budget = _Budget(max_nodes)
    _limit(max_input_bytes, MAX_INPUT_BYTES, 'animation aggregate byte limit')
    _limit(max_source_bytes, MAX_SOURCE_BYTES, 'animation source byte limit')
    if not isinstance(left, (bytes, bytearray)) or not isinstance(right, (bytes, bytearray)):
        raise ValueError('animation comparison requires immutable source bytes')
    if max(len(left), len(right)) > max_source_bytes or len(left) + len(right) > max_input_bytes:
        raise AnimationDiffLimitError('animation comparison exceeds input byte limits')
    left, right = bytes(left), bytes(right)
    inventories, sources = [], []
    budget.charge()
    for data in (left, right):
        inventory, source = _inventory(data, budget)
        inventories.append(inventory); sources.append(source)
    groups = defaultdict(lambda: [[], []])
    for side, inventory in enumerate(inventories):
        for declaration in inventory:
            budget.charge()
            groups[declaration['kind'], declaration['hash']][side].append(declaration)
    comparisons, counts = [], Counter()
    for (kind, name), (a, b) in sorted(groups.items()):
        budget.charge(1 + len(a) + len(b))
        item = dict(kind=kind, hash=name, left_indices=[d['index'] for d in a],
                    right_indices=[d['index'] for d in b])
        if not a or not b:
            item['status'] = 'only_right' if b else 'only_left'
        elif int(name, 16) < 0x10000:
            item['status'] = 'file_local_unaligned'
        elif len(a) != 1 or len(b) != 1:
            item['status'] = 'ambiguous_unaligned'
        else:
            av, bv = a[0], b[0]
            item.update(status='equal_content' if av['content_sha256'] == bv['content_sha256'] else 'changed_content',
                alignment='unique same-kind/hash candidate; no semantic or ABI identity',
                changed_nonpositional_header_word_indices=[i for i, (x, y) in enumerate(zip(av['_header'], bv['_header'])) if x != y],
                entry_order_or_content_changed=av['_entries'] != bv['_entries'],
                entry_changes=_entry_changes(av, bv, budget))
        comparisons.append(item)
        counts[kind + '/' + item['status']] += 1
    content_equal = all(sorted(d['content_sha256'] for d in inventories[0] if d['kind'] == kind)
                        == sorted(d['content_sha256'] for d in inventories[1] if d['kind'] == kind)
                        for kind in ('structure', 'enum'))
    for inventory in inventories:
        for row in inventory:
            del row['_header'], row['_entries']
    return dict(format='gta6x-animation-resource-diff-v1', status='complete',
                sources=dict(left=sources[0], right=sources[1]), source_bytes_equal=left == right,
                declaration_content_equal=content_equal, definitions=dict(left=inventories[0], right=inventories[1]),
                comparisons=comparisons,
                summary=dict(counts=dict(counts), left_declarations=len(inventories[0]),
                             right_declarations=len(inventories[1]), comparison_groups=len(comparisons)),
                work_units=budget.used, semantic_compatibility='unconfirmed',
                scope='Complete literal declaration comparison only; source metadata remains partial. '
                'No schema evolution, ABI, instance, animation, key namespace or provider authority.')


def _path(value):
    try:
        path = os.fspath(value)
    except TypeError as exc:
        raise ValueError('animation comparison requires text file paths') from exc
    if not isinstance(path, str) or not path or '\0' in path:
        raise ValueError('animation comparison requires nonempty text paths')
    return path


def compare_files(left_path, right_path, *, max_nodes=100000, max_input_bytes=MAX_INPUT_BYTES,
                  max_source_bytes=MAX_SOURCE_BYTES, protected_outputs=()):
    """Preflight and read two exact regular files, never scan, carve, join or write.

    Comparing a file with itself is allowed. Output aliases, including hardlinks,
    refuse before payload reads. Opened identities and sizes must match preflight.
    """
    _Budget(max_nodes)
    _limit(max_input_bytes, MAX_INPUT_BYTES, 'animation aggregate byte limit')
    _limit(max_source_bytes, MAX_SOURCE_BYTES, 'animation source byte limit')
    paths = [_path(left_path), _path(right_path)]
    if not isinstance(protected_outputs, (list, tuple)) or len(protected_outputs) > 1024:
        raise ValueError('animation comparison outputs require a bounded path list')
    outputs = [_path(p) for p in protected_outputs]
    information = [os.stat(p) for p in paths]
    if any(not stat.S_ISREG(row.st_mode) for row in information):
        raise ValueError('animation comparison inputs must be regular files')
    identities = {(r.st_dev, r.st_ino) for r in information}
    resolved = {os.path.realpath(p) for p in paths}
    for output in outputs:
        if os.path.realpath(output) in resolved:
            raise ValueError('animation comparison output aliases an input')
        try:
            info = os.stat(output)
        except FileNotFoundError:
            continue
        if (info.st_dev, info.st_ino) in identities:
            raise ValueError('animation comparison output aliases an input')
    sizes = [row.st_size for row in information]
    if max(sizes) > max_source_bytes or sum(sizes) > max_input_bytes:
        raise AnimationDiffLimitError('animation comparison files exceed input byte limits')
    minimum = 1 + sum(2 + 2 * ((size + 4095) // 4096) for size in sizes)
    if max_nodes < minimum:
        raise AnimationDiffLimitError('animation comparison verification exceeds node budget')
    data = []
    for path, info in zip(paths, information):
        with open(path, 'rb') as handle:
            current = os.fstat(handle.fileno())
            if (not stat.S_ISREG(current.st_mode) or current.st_size != info.st_size
                    or (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino)):
                raise ValueError('animation comparison input changed after preflight')
            raw = handle.read(info.st_size + 1)
        if len(raw) != info.st_size:
            raise ValueError('animation comparison input size changed during read')
        data.append(raw)
    return compare(*data, max_nodes=max_nodes, max_input_bytes=max_input_bytes,
                   max_source_bytes=max_source_bytes)
