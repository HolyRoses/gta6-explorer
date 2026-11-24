"""Raw, source-backed PSIN schema comparison without compatibility claims.

Unique high-ID names provide candidate alignment only. Duplicate names and low
IDs remain unaligned. Complete header/member words are retained, including
unknowns; no registry provider, type meaning or instance layout is inferred.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import os
import stat
import struct

from . import psin, psin_schema

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_INPUT_BYTES = 2 * MAX_SOURCE_BYTES
MAX_NODES = 2_000_000


class SchemaDiffLimitError(ValueError):
    pass


class _Budget:
    def __init__(self, maximum):
        if type(maximum) is not int or not 1 <= maximum <= MAX_NODES:
            raise ValueError(f'max_nodes must be an integer from 1 to {MAX_NODES}')
        self.maximum, self.used = maximum, 0

    def charge(self, count=1):
        if count > self.maximum - self.used:
            raise SchemaDiffLimitError('PSIN schema comparison exceeds shared node budget')
        self.used += count


def _uint(value, maximum, name):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{name} must be an integer from 1 to {maximum}')


def _hex_words(words, widths):
    return [f'0x{word:0{width//4}x}' for word, width in zip(words, widths)]


def _precharge_section(data, header_size, count_offset, budget):
    """Bound descriptor work before the existing parser allocates any table."""
    position = expected = 8
    while expected < len(data):
        budget.charge(3)
        if position > len(data) - header_size:
            raise ValueError('schema comparison requires a complete declaration header')
        code = '<H' if header_size == 32 else '<I'
        count = struct.unpack_from(code, data, position + count_offset)[0]
        budget.charge(3 * count)
        expected += header_size + 16 * count
        if expected > len(data):
            raise ValueError('schema comparison declaration count exceeds section')
        position += header_size
    if expected != len(data):
        raise ValueError('schema comparison declarations do not tile their section')


def _inventory(data, budget):
    budget.charge(1 + 2 * ((len(data) + 4095) // 4096))
    container = psin.parse_container(data)
    if container is None or not container.checksum_verified:
        raise ValueError('schema comparison requires a complete checksum-verified PSIN container')
    result = []
    hashes = {}
    for kind, tag, header_size, count_at in (('structure', 'LSCH', 32, 30), ('enum', 'LENM', 24, 16)):
        section = container.section(tag)
        raw = data[section.offset:section.offset + section.length]
        _precharge_section(raw, header_size, count_at, budget)
        table = psin_schema.parse_lsch(raw) if kind == 'structure' else psin_schema.parse_lenm(raw)
        declarations = table.structures if kind == 'structure' else table.definitions
        hashes[tag] = hashlib.sha256(raw).hexdigest()
        for declaration in declarations:
            budget.charge(3)
            at = declaration.section_offset
            if kind == 'structure':
                words = struct.unpack_from('<4IQIHH', raw, at)
                widths = [32, 32, 32, 32, 64, 32, 16, 16]
                parsed_entries = declaration.fields
                expected_header = (declaration.name_hash, declaration.unknown_04, declaration.unknown_08,
                    declaration.unknown_0c, int.from_bytes(b'\xaa' * 8, 'little'),
                    declaration.byte_size, declaration.unknown_1c, len(parsed_entries))
            else:
                words = struct.unpack_from('<IIQII', raw, at)
                widths = [32, 32, 64, 32, 32]
                parsed_entries = declaration.members
                expected_header = (declaration.name_hash, declaration.unknown_04,
                    int.from_bytes(b'\xee' * 8, 'little'), len(parsed_entries), declaration.unknown_14)
            if words != expected_header:
                raise ValueError('schema comparison header differs from original parser words')
            entries, raw_entries = [], []
            content = bytearray(raw[at:at + header_size])
            for ordinal, entry in enumerate(parsed_entries):
                budget.charge(2)
                entry_at = entry.section_offset
                if kind == 'structure':
                    value = struct.unpack_from('<4I', raw, entry_at)
                    expected = entry.name_hash, entry.data_offset, entry.type_word, entry.auxiliary
                    entry_widths = [32, 32, 32, 32]
                else:
                    value = struct.unpack_from('<QII', raw, entry_at)
                    expected = entry.value_bits, entry.name_hash, entry.unknown_0c
                    entry_widths = [64, 32, 32]
                if value != expected:
                    raise ValueError('schema comparison entry differs from original source words')
                raw_entries.append(value)
                content.extend(raw[entry_at:entry_at + 16])
                entries.append(dict(index=ordinal, hash=f'0x{entry.name_hash:08x}',
                    data_offset=section.offset + entry_at, section_offset=entry_at,
                    byte_length=16, raw_words=_hex_words(value, entry_widths), word_widths=entry_widths))
            result.append(dict(index=len(result), kind=kind, hash=f'0x{declaration.name_hash:08x}',
                data_offset=section.offset + at, section_offset=at, byte_length=header_size,
                raw_header_words=_hex_words(words, widths), header_word_widths=widths,
                header_sha256=hashlib.sha256(raw[at:at + header_size]).hexdigest(),
                content_sha256=hashlib.sha256(b'gta6x-raw-schema-declaration-v1\0' + kind.encode() + bytes(content)).hexdigest(),
                entries=entries, _header=words, _entries=raw_entries))
    return result, dict(byte_length=len(data), sha256=hashlib.sha256(data).hexdigest(),
        checksum_verified=True, lsch_sha256=hashes['LSCH'], lenm_sha256=hashes['LENM'])


def _entry_changes(left, right, budget):
    groups = defaultdict(lambda: [[], []])
    for side, entries in enumerate((left['entries'], right['entries'])):
        for entry in entries:
            budget.charge()
            groups[entry['hash']][side].append(entry)
    changes = []
    for name, (a, b) in sorted(groups.items()):
        budget.charge(1 + len(a) + len(b))
        row = dict(hash=name, left_indices=[v['index'] for v in a], right_indices=[v['index'] for v in b])
        if not a or not b:
            row['status'] = 'only_right' if b else 'only_left'
        elif int(name, 16) < 0x10000:
            row['status'] = 'file_local_unaligned'
        elif len(a) != 1 or len(b) != 1:
            row['status'] = 'ambiguous_unaligned'
        else:
            av, bv = a[0], b[0]
            budget.charge(1 + len(av['raw_words']))
            row.update(status='equal_content' if av['raw_words'] == bv['raw_words'] else 'changed_content',
                alignment='unique same-hash candidate only; entry identity is unconfirmed',
                ordinal_changed=av['index'] != bv['index'],
                changed_word_indices=[i for i, (x, y) in enumerate(zip(av['raw_words'], bv['raw_words'])) if x != y])
        changes.append(row)
    return changes


def compare(left, right, *, max_nodes=100000, max_input_bytes=MAX_INPUT_BYTES,
            max_source_bytes=MAX_SOURCE_BYTES):
    """Compare two immutable complete containers, or raise without a prefix.

    Only unique high-ID same-kind/name declarations are candidate-aligned.
    Missing names mean absence from the selected counterpart, not a semantic
    addition/deletion, ABI compatibility result or schema-version relationship.
    """
    budget = _Budget(max_nodes)
    _uint(max_input_bytes, MAX_INPUT_BYTES, 'aggregate input byte limit')
    _uint(max_source_bytes, MAX_SOURCE_BYTES, 'source byte limit')
    if not isinstance(left, (bytes, bytearray)) or not isinstance(right, (bytes, bytearray)):
        raise ValueError('schema comparison requires bytes')
    if len(left) > max_source_bytes or len(right) > max_source_bytes or len(left) + len(right) > max_input_bytes:
        raise SchemaDiffLimitError('PSIN schema comparison exceeds input byte limits')
    left, right = bytes(left), bytes(right)
    inventories, sources = [], []
    for data in (left, right):
        inventory, source = _inventory(data, budget)
        inventories.append(inventory)
        sources.append(source)
    groups = defaultdict(lambda: [[], []])
    for side, inventory in enumerate(inventories):
        for declaration in inventory:
            budget.charge()
            groups[(declaration['kind'], declaration['hash'])][side].append(declaration)
    comparisons, counts = [], Counter()
    for (kind, name), (a, b) in sorted(groups.items()):
        budget.charge(1 + len(a) + len(b))
        row = dict(kind=kind, hash=name, left_indices=[d['index'] for d in a], right_indices=[d['index'] for d in b])
        if not a or not b:
            row['status'] = 'only_right' if b else 'only_left'
        elif int(name, 16) < 0x10000:
            row['status'] = 'file_local_unaligned'
        elif len(a) != 1 or len(b) != 1:
            row['status'] = 'ambiguous_unaligned'
        else:
            av, bv = a[0], b[0]
            row.update(status='equal_content' if av['content_sha256'] == bv['content_sha256'] else 'changed_content',
                alignment='unique same-kind/hash candidate only; no semantic or ABI identity',
                changed_header_word_indices=[i for i, (x, y) in enumerate(zip(av['_header'], bv['_header'])) if x != y],
                entry_order_or_content_changed=av['_entries'] != bv['_entries'],
                entry_changes=_entry_changes(av, bv, budget))
        counts[kind + '/' + row['status']] += 1
        comparisons.append(row)
    for inventory in inventories:
        for row in inventory:
            del row['_header'], row['_entries']
    return dict(format='gta6x-psin-schema-diff-v1', status='complete',
        sources=dict(left=sources[0], right=sources[1]),
        source_bytes_equal=left == right,
        schema_sections_equal=all(sources[0][key] == sources[1][key] for key in ('lsch_sha256', 'lenm_sha256')),
        definitions=dict(left=inventories[0], right=inventories[1]), comparisons=comparisons,
        summary=dict(counts= dict(counts), left_declarations=len(inventories[0]),
                     right_declarations=len(inventories[1]), comparison_groups=len(comparisons)),
        work_units=budget.used, semantic_compatibility='unconfirmed',
        scope='Raw declaration observations only; no schema evolution, ABI, instance, asset or provider authority.')


def compare_files(left_path, right_path, *, max_nodes=100000, max_input_bytes=MAX_INPUT_BYTES,
                  max_source_bytes=MAX_SOURCE_BYTES, protected_outputs=()):
    """Read each bounded file once; never scan/carve or reopen source metadata."""
    _Budget(max_nodes)
    _uint(max_input_bytes, MAX_INPUT_BYTES, 'aggregate input byte limit')
    _uint(max_source_bytes, MAX_SOURCE_BYTES, 'source byte limit')
    paths = [os.fspath(left_path), os.fspath(right_path)]
    resolved = {os.path.realpath(path) for path in paths}
    if any(os.path.realpath(output) in resolved for output in protected_outputs):
        raise ValueError('schema comparison output aliases an input')
    for output in protected_outputs:
        if os.path.exists(output) and any(os.path.samefile(output, path) for path in paths):
            raise ValueError('schema comparison output aliases an input')
    information = [os.stat(path) for path in paths]
    if any(not stat.S_ISREG(row.st_mode) for row in information):
        raise ValueError('schema comparison inputs must be regular files')
    sizes = [row.st_size for row in information]
    if any(size > max_source_bytes for size in sizes) or sum(sizes) > max_input_bytes:
        raise SchemaDiffLimitError('PSIN schema comparison files exceed input byte limits')
    inputs = []
    for path, size in zip(paths, sizes):
        with open(path, 'rb') as handle:
            raw = handle.read(size + 1)
        if len(raw) != size:
            raise ValueError('schema comparison file size changed while reading')
        inputs.append(raw)
    return compare(*inputs, max_nodes=max_nodes, max_input_bytes=max_input_bytes,
                   max_source_bytes=max_source_bytes)
