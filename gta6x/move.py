"""Bounded MoVE envelope tables from direct local format observations.

The supported observed profile carries two counted u32-word tables and one
counted five-byte table. Words, tags, control fields and the remaining payload
have unknown motion/application meanings. No external implementation or table
is used. Successful parsing covers storage spans, not decoded motion values.
"""
from __future__ import annotations

import hashlib
import struct

MAX_BYTES = 16 * 1024 * 1024
PROFILE = 'observed_move_envelope_v1'


class MoveLimitError(ValueError):
    """An explicit input or metadata output limit was exceeded."""


def parse(data: bytes, *, max_nodes=100000, with_objects=False) -> dict:
    """Inspect the supported exact envelope, or raise ValueError atomically.

    Regions partition the input, with an opaque payload rather than guessed
    object/pointer interpretation. All counts and the redundant total-length
    relationship are checked before any table rows are emitted.
    """
    if type(max_nodes) is not int or max_nodes < 1:
        raise ValueError('MoVE max_nodes must be a positive integer')
    if len(data) > MAX_BYTES:
        raise MoveLimitError('MoVE input exceeds size limit')
    if len(data) < 62 or data[:4] != b'MoVE':
        raise ValueError('truncated or unsupported MoVE envelope')
    version = struct.unpack_from('<I', data, 4)[0]
    if version != 19 or any(data[8:20]) or any(data[28:32]):
        raise ValueError('unsupported MoVE header profile')
    position, specs = 32, []
    for label in ('word_table_0', 'word_table_1'):
        if position > len(data) - 4:
            raise ValueError('truncated MoVE table count')
        count = struct.unpack_from('<I', data, position)[0]
        size = 4 + count * 4
        if position > len(data) - size:
            raise ValueError('MoVE word-table span exceeds input')
        specs.append((label, position, count, 4))
        position += size
    if position > len(data) - 8:
        raise ValueError('truncated MoVE control or tagged-table count')
    control_at = position
    position += 4
    tagged_count = struct.unpack_from('<I', data, position)[0]
    size = 4 + tagged_count * 5
    if position > len(data) - size:
        raise ValueError('MoVE tagged-word table exceeds input')
    specs.append(('tagged_word_table', position, tagged_count, 5))
    position += size
    prelude_at, payload_at = position, position + 10
    if payload_at > len(data) - 4:
        raise ValueError('truncated MoVE payload prelude or raw payload code')
    length_word = struct.unpack_from('<I', data, 24)[0]
    if len(data) != length_word + 46 + tagged_count * 5:
        raise ValueError('MoVE redundant length relationship differs from exact input size')
    needed = 15 + sum(spec[2] for spec in specs)  # View fields and seven region descriptors.
    if needed > max_nodes:
        raise MoveLimitError('MoVE metadata output exceeds node limit')
    tables = []
    for label, at, count, stride in specs:
        records = []
        for i in range(count):
            pos = at + 4 + stride * i
            row = dict(index=i, data_offset=pos, word_bits=f'0x{struct.unpack_from("<I", data, pos)[0]:08x}')
            if stride == 5:
                row['raw_tag'] = data[pos + 4]
            records.append(row)
        tables.append(dict(name=label, data_offset=at, byte_length=4 + count * stride,
            count=count, record_stride=stride, records=records,
            interpretation='raw storage words; names, references and type meanings unknown'))
    spans = [('header', 0, 32)]
    spans += [(s[0], s[1], 4 + s[2] * s[3]) for s in specs[:2]]
    spans += [('control', control_at, 4), ('tagged_word_table', specs[2][1], 4 + tagged_count * 5),
              ('payload_prelude', prelude_at, 10), ('opaque_payload', payload_at, len(data) - payload_at)]
    result = dict(format='gta6x-move-metadata-v1', status='partial', profile=PROFILE,
        interpretation='Exact bounded envelope spans; table words, tags, control, object grammar, '
                       'motion, pose and timing semantics remain unknown.',
        byte_length=len(data), sha256=hashlib.sha256(data).hexdigest(),
        header=dict(version_word=version, raw_word_14=f'0x{struct.unpack_from("<I", data, 20)[0]:08x}',
                    raw_length_word_18=length_word, header_bits='0x' + data[:32][::-1].hex()),
        tables=tables, control=dict(data_offset=control_at, raw_bits='0x' + data[control_at:control_at+4][::-1].hex()),
        payload_prelude=dict(data_offset=prelude_at, byte_length=10,
                            value_bits='0x' + data[prelude_at:payload_at][::-1].hex()),
        opaque_payload=dict(data_offset=payload_at, byte_length=len(data)-payload_at,
                            first_word_bits=f'0x{struct.unpack_from("<I", data, payload_at)[0]:08x}',
                            sha256=hashlib.sha256(data[payload_at:]).hexdigest()),
        regions=[dict(name=label, data_offset=at, byte_length=size) for label, at, size in spans],
        summary=dict(nodes=needed, tables=3, word_rows=specs[0][2]+specs[1][2], tagged_rows=tagged_count))
    if with_objects:
        from . import move_objects
        view = move_objects.inspect_payload(data, payload_at, len(data)-payload_at,
                                            max_nodes=max_nodes-needed)
        result['object_layout'] = view
        detail = view['summary']
        result['summary'].update(nodes=needed+detail['nodes'], object_nodes=detail['nodes'],
            object_profiles_resolved=int(view['status']=='complete'),
            object_profiles_unresolved=int(view['status']=='unresolved'),
            immediate_references=detail.get('references',0),
            descriptor_records=detail.get('descriptor_records',0), fixed_cells=detail.get('fixed_cells',0),
            nested_subblocks=detail.get('nested_blocks',0))
    return result


def scan(path, *, start=None, limit=None, max_nodes=100000, with_objects=False):
    """Yield checked adjacent-page candidates and explicit envelope refusals."""
    from . import anim_resources, anim_clips
    if type(max_nodes) is not int or max_nodes < 1:
        raise ValueError('MoVE max_nodes must be a positive integer')
    remaining = max_nodes
    for row, data, error in anim_resources._scan_chains(path, start=start, limit=limit,
            is_start=lambda d: d[:4] == b'MoVE',
            independent_start=lambda d: anim_resources._independent_start(d) or anim_clips.is_dictionary(d),
            label='MoVE'):
        if error is None:
            try:
                parsed = parse(data, max_nodes=remaining, with_objects=with_objects)
                remaining -= parsed['summary']['nodes']
                row.update(parsed)
            except ValueError as exc:
                error = str(exc)
        row['framing'] = 'unresolved' if error is not None else 'short_terminal_page'
        if error is not None:
            row.update(status='refused', reason=error)
        yield row
