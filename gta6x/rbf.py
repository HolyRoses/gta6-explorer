"""Bounded RBF0 token trees from direct local format observations.

Only the observed FBFF/0100 framing and token kinds 0, 1, 6 and FFFD are
supported. Kind 1 values retain raw bits; names and text do not establish
application semantics. No external implementation or game-specific table is
used. Parsing covers the entire input or raises ValueError.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import struct

MAX_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 128


class RbfLimitError(ValueError):
    """An explicit RBF input or output budget was exceeded."""


def parse(data: bytes, *, max_nodes=100000, max_depth=32, max_string_bytes=4096,
          max_value_bytes=1024 * 1024) -> dict:
    """Parse the supported RBF0 profile into an indexed structural tree.

    Nodes and descriptor rows share max_nodes. Depth counts root as zero,
    with an absolute safe recursion cap of 128.
    Unsupported kinds, malformed text, unknown descriptors, unbalanced closes,
    nonzero object words and trailing bytes refuse the whole result. Byte-leaf
    text is merely a candidate when its bytes are NUL-terminated UTF-8.
    """
    for name, value in (('max_nodes', max_nodes), ('max_depth', max_depth),
                        ('max_string_bytes', max_string_bytes), ('max_value_bytes', max_value_bytes)):
        if type(value) is not int or value < 1:
            raise ValueError(f'{name} must be a positive integer')
    if max_depth > MAX_DEPTH:
        raise ValueError(f'max_depth must not exceed {MAX_DEPTH}')
    if len(data) > MAX_BYTES:
        raise RbfLimitError('RBF input exceeds size limit')
    if data[:8] != b'RBF0\xfb\xff\x01\x00':
        raise ValueError('unsupported RBF0 framing profile')
    position = 8
    nodes, descriptors = [], []
    max_seen_depth = 0

    def read(length):
        nonlocal position
        if length < 0 or position > len(data) - length:
            raise ValueError('truncated RBF token or value')
        at = position
        position += length
        return data[at:position]

    def number(fmt):
        return struct.unpack(fmt, read(struct.calcsize(fmt)))[0]

    def consume():
        if len(nodes) + len(descriptors) >= max_nodes:
            raise RbfLimitError('RBF output exceeds node limit')

    def text(length):
        if length > max_string_bytes:
            raise RbfLimitError('RBF text exceeds string-byte limit')
        raw = read(length)
        if b'\0' in raw:
            raise ValueError('unsupported embedded NUL in RBF text')
        try:
            return raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError('invalid UTF-8 RBF text') from exc

    def token(parent, role, depth):
        nonlocal max_seen_depth
        at = position
        word = number('<H')
        if word == 0xffff:
            if role != 'child':
                raise ValueError('unexpected RBF close token')
            return None
        if depth > max_depth:
            raise RbfLimitError('RBF nesting exceeds depth limit')
        max_seen_depth = max(max_seen_depth, depth)
        consume()
        index = len(nodes)
        node = dict(index=index, parent_index=parent, role=role, data_offset=at,
                    token_bits=f'0x{word:04x}')
        nodes.append(node)
        if word == 0xfffd:
            if role != 'child':
                raise ValueError('RBF byte leaf cannot be a root or attribute')
            length = number('<I')
            if length > max_value_bytes:
                raise RbfLimitError('RBF byte leaf exceeds value-byte limit')
            value_at = position
            raw = read(length)
            node.update(kind='bytes', value_data_offset=value_at, value_byte_length=length,
                        value_hex=raw.hex(), interpretation='opaque byte leaf')
            if raw.endswith(b'\0') and b'\0' not in raw[:-1]:
                if len(raw) - 1 > max_string_bytes:
                    raise RbfLimitError('RBF text candidate exceeds string-byte limit')
                try:
                    node['text_candidate'] = raw[:-1].decode('utf-8')
                except UnicodeDecodeError:
                    pass
        else:
            descriptor, kind = word & 0xfff, word >> 12
            if kind not in (0, 1, 6):
                raise ValueError(f'unsupported RBF token kind 0x{kind:x}')
            if descriptor == len(descriptors):
                name_at = position
                name = text(number('<H'))
                if not name:
                    raise ValueError('empty RBF descriptor name')
                consume()
                descriptors.append(dict(index=descriptor, type_code=f'0x{kind:x}', name=name,
                                        data_offset=name_at, byte_length=position - name_at))
            elif descriptor >= len(descriptors):
                raise ValueError('unknown or out-of-order RBF name descriptor')
            entry = descriptors[descriptor]
            if entry['type_code'] != f'0x{kind:x}':
                raise ValueError('RBF descriptor reused with a different token kind')
            node.update(descriptor_index=descriptor, name=entry['name'], type_code=f'0x{kind:x}')
            if kind == 0:
                if role == 'attribute':
                    raise ValueError('object-valued RBF attributes are not validated')
                reserved, count = number('<I'), number('<H')
                if reserved:
                    raise ValueError('unsupported nonzero RBF object header word')
                node.update(kind='object', reserved_bits='0x00000000', attributes=[], children=[])
                if count > max_nodes - len(nodes) - len(descriptors):
                    raise RbfLimitError('RBF attributes exceed node limit')
                for _ in range(count):
                    node['attributes'].append(token(index, 'attribute', depth + 1))
                while True:
                    child = token(index, 'child', depth + 1)
                    if child is None:
                        break
                    node['children'].append(child)
            elif kind == 1:
                raw = read(8)
                node.update(kind='raw64', value_bits='0x' + raw[::-1].hex(),
                            interpretation='opaque eight-byte value; signedness and semantics unknown')
            else:
                node.update(kind='text', text=text(number('<H')),
                            interpretation='length-prefixed UTF-8 text; application semantics unknown')
        node['byte_length'] = position - at
        return index

    root = token(None, 'root', 0)
    if nodes[root]['kind'] != 'object':
        raise ValueError('RBF root must be an object in the supported profile')
    if position != len(data):
        raise ValueError('unaccounted trailing RBF bytes')
    return dict(format='gta6x-rbf0-tree-v1', status='complete', profile='observed_rbf0_tokens_v1',
        interpretation='Exact structural token coverage only; type and application semantics remain unknown.',
        byte_length=len(data), consumed_bytes=position, sha256=hashlib.sha256(data).hexdigest(),
        header_bits='0x' + data[:8][::-1].hex(), root_index=root, descriptors=descriptors, nodes=nodes,
        summary=dict(nodes=len(nodes) + len(descriptors), tree_nodes=len(nodes), descriptors=len(descriptors),
                     maximum_depth=max_seen_depth, kinds=dict(Counter(n['kind'] for n in nodes)),
                     names=dict(Counter(n['name'] for n in nodes if 'name' in n))))


def scan(path, *, start=None, limit=None, max_nodes=100000, max_depth=32,
         max_string_bytes=4096):
    """Yield checked contiguous-page candidates and explicit parse refusals.

    A short terminal page establishes framing for this profile. Exact token
    consumption is also required. A full final page without a bounded end is
    refused by the shared page assembler.
    """
    from . import anim_resources
    remaining = max_nodes
    if type(remaining) is not int or remaining < 1:
        raise ValueError('max_nodes must be a positive integer')
    if type(max_depth) is not int or not 1 <= max_depth <= MAX_DEPTH:
        raise ValueError(f'max_depth must be between 1 and {MAX_DEPTH}')
    if type(max_string_bytes) is not int or max_string_bytes < 1:
        raise ValueError('max_string_bytes must be a positive integer')
    for row, data, error in anim_resources._scan_chains(path, start=start, limit=limit,
            is_start=lambda d: d[:4] == b'RBF0', independent_start=anim_resources._independent_start,
            label='RBF0'):
        if error is None:
            try:
                report = parse(data, max_nodes=remaining, max_depth=max_depth,
                               max_string_bytes=max_string_bytes)
                remaining -= report['summary']['nodes']
                row.update(report)
            except ValueError as exc:
                error = str(exc)
        row['framing'] = 'unresolved' if error is not None else 'short_terminal_page'
        if error is not None:
            row.update(status='refused', reason=error)
        yield row
