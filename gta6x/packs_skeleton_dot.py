"""Source-backed DOT for checked named records and stored parent indices.

The whole native table, lookup and forest are reparsed from immutable bytes.
Graph edges describe stored parents, not poses, transforms, rig providers or
animation ownership. A complete graph does not establish a complete resource.
"""
from __future__ import annotations

from . import packs_bones, packs_skeleton_bounds as bounds

PROFILE = 'packs_checked_named_records_stored_parent_dot_v1'
MAX_DOT_BYTES = 8 * 1024 * 1024
MAX_NODES = 65535
MAX_EDGES = MAX_NODES - 1


def _quote(text):
    """Quote one bounded DOT label; controls and Graphviz escapes stay literal."""
    if not isinstance(text, str) or len(text) > 4096:
        raise ValueError('invalid bounded skeleton DOT label')
    parts = []
    for char in text:
        if char == '\\': parts.append('\\\\')
        elif char == '"': parts.append('\\"')
        elif char == '\n': parts.append('\\n')
        elif ord(char) < 32 or ord(char) == 127:
            parts.append('\\\\x' + f'{ord(char):02x}')
        else: parts.append(char)
    result = '"' + ''.join(parts) + '"'
    try:
        result.encode('utf-8')
    except UnicodeError as exc:
        raise ValueError('invalid skeleton DOT label encoding') from exc
    return result


def inspect(data, *, max_work=1000000, max_bytes=MAX_DOT_BYTES):
    """Return one whole stored-parent graph or an atomic unsupported view.

    Only explicitly supplied source bytes are accepted. Unsupported native
    profiles return no ``dot`` key; source/work/output limits raise ValueError.
    Work includes the entire unchanged named-table inspector, all rendered
    records/edges and emitted UTF-8 bytes. No raw pointer is followed here.
    """
    if type(max_work) is not int or max_work < 1:
        raise ValueError('skeleton DOT work limit must be positive')
    if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_DOT_BYTES:
        raise ValueError('skeleton DOT byte limit must be 1..8388608')
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('skeleton DOT requires source bytes')
    if len(data) > bounds.MAX_BYTES:
        raise bounds.BoundsLimitError('skeleton DOT source exceeds byte limit')
    data = bytes(data)
    base = packs_bones.inspect(data, max_work=max_work)
    used = base['work_units']
    result = dict(status='unsupported', candidate_profile=PROFILE,
                  allocation_end=None, complete_format=False,
                  pose_decoding='unknown', inferred_animation_links=[],
                  inferred_skeleton_providers=[])
    if base['status'] != 'complete':
        result.update(reason='skeleton DOT requires checked named table: ' + base['reason'],
                      work_units=used)
        return result

    def charge(amount=1):
        nonlocal used
        if amount > max_work - used:
            raise bounds.BoundsLimitError('skeleton DOT work limit exceeded')
        used += amount

    records = base['records']
    edges = len(records) - len(base['root_indices'])
    charge()
    if len(records) > MAX_NODES or edges > MAX_EDGES:
        raise bounds.BoundsLimitError('skeleton DOT exceeds node/edge limit')
    lines, output_bytes = [], 0

    def emit(line):
        nonlocal output_bytes
        encoded = (line + '\n').encode('utf-8')
        if len(encoded) > max_bytes - output_bytes:
            raise bounds.BoundsLimitError('skeleton DOT output exceeds byte limit')
        charge(1 + (len(encoded) + 63) // 64)
        output_bytes += len(encoded)
        lines.append(line)

    emit('digraph skeleton_records {')
    title = ('Checked stored parent forest | source ' + base['source_sha256'] + '\n'
             'Pose, provider, animation ownership and resource extent unknown')
    emit(f'  graph [label={_quote(title)}, labelloc=t];')
    emit('  node [shape=box];')
    for row in records:
        charge()
        label = (f"record {row['index']} | {row['name']}\n"
                 f"name hash {row['stored_name_hash_u32']} | alternate {row['alternate_key_u16']}\n"
                 f"source @{row['data_offset']} +{row['byte_length']} bytes")
        style = ', style=bold' if row['parent_index'] is None else ''
        emit(f"  b{row['index']} [label={_quote(label)}{style}];")
    for row in records:
        charge()
        if row['parent_index'] is not None:
            label = (f"stored parent | record word @{row['parent_data_offset']}\n"
                     f"duplicate parent @{row['parent_copy_data_offset']}")
            emit(f"  b{row['parent_index']} -> b{row['index']} [label={_quote(label)}];")
    emit('}')
    result.pop('candidate_profile')
    result.update(status='complete', profile=PROFILE, dot='\n'.join(lines) + '\n',
                  source_sha256=base['source_sha256'], byte_length=len(data),
                  work_units=used,
                  counts=dict(bone_nodes=len(records), stored_parent_edges=edges,
                              roots=len(base['root_indices']), output_bytes=output_bytes),
                  interpretation='Checked stored record-parent relationships only; '
                  'no pose, transform, rig provider, animation binding or resource-endpoint claim')
    return result
