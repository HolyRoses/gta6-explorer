"""Bounded public PSV0 component dependency masks; game identities stay unknown."""
from __future__ import annotations

import struct


def inspect(body: bytes, origin: int, prefix: dict, signatures: dict, spend) -> dict:
    """Read supported stage masks using declared packed-vector dimensions.

    Only generic vertex/pixel/geometry masks and empty mesh masks are supported.
    Unsupported stage profiles and surplus bytes are refused by this view; valid
    independent signature/runtime metadata is retained by the caller.
    """
    spend()
    info = prefix['runtime_info']
    if info['known_prefix_version'] == 0:
        return dict(status='complete', tables=[], word_count=0,
                    scope='version-zero PSV0 has no dependency masks')
    stage = info['stage_code']
    inputs = info['input_vectors']
    outputs = info['output_vectors']
    uses_view = info['uses_view_id_raw']
    primitive = int(info['extra_stage_bits'], 16) & 255
    if uses_view not in (0, 1):
        raise ValueError('PSV0 mask profile requires a Boolean UsesViewID value')
    if stage == 13:
        if uses_view or inputs or primitive:
            raise ValueError('PSV0 mesh masks require independent stage-specific layout evidence')
    elif stage not in (0, 1, 2):
        raise ValueError('PSV0 dependency mask stage profile is unsupported')
    if stage != 2 and any(outputs[1:]):
        raise ValueError('PSV0 non-geometry mask profile has unsupported extra output streams')
    tail = signatures['opaque_mask_suffix']
    cursor = tail['data_offset'] - origin
    end = cursor + tail['byte_length']
    if cursor < 0 or end != len(body):
        raise ValueError('PSV0 dependency mask suffix exceeds its bounded chunk')
    start = cursor
    streams = range(4) if stage == 2 else range(1)
    plans = []
    if stage != 13:
        if uses_view:
            plans.extend(('view_id_output', stream, 1, outputs[stream]) for stream in streams if outputs[stream])
        if inputs:
            plans.extend(('input_output', stream, 4 * inputs, outputs[stream]) for stream in streams if outputs[stream])
    expected = sum(rows * ((vectors + 7) // 8) for _, _, rows, vectors in plans)
    if expected * 4 != end - start:
        raise ValueError('PSV0 dependency mask dimensions do not exhaust the declared suffix')
    tables = []
    total_edges = 0
    for kind, stream, rows, vectors in plans:
        words_per_row = (vectors + 7) // 8
        output_components = vectors * 4
        spend(1 + rows + rows * words_per_row)
        table_start = cursor
        records = []
        for index in range(rows):
            at = cursor
            words = list(struct.unpack_from('<' + 'I' * words_per_row, body, at))
            cursor += 4 * words_per_row
            spend(sum(word.bit_count() for word in words))
            bits = [32 * wi + bi for wi, word in enumerate(words) for bi in range(32) if word & (1 << bi)]
            assigned = [bit for bit in bits if bit < output_components]
            padding = [bit for bit in bits if bit >= output_components]
            row = dict(index=index, data_offset=origin + at,
                       words=[f'0x{word:08x}' for word in words],
                       dependent_output_components=assigned, unassigned_padding_bits=padding)
            if kind == 'input_output':
                row['input_component_index'] = index
            records.append(row)
            total_edges += len(assigned)
        tables.append(dict(kind=kind, output_stream=stream, data_offset=origin + table_start,
            byte_length=cursor - table_start, row_count=rows, words_per_row=words_per_row,
            output_vectors=vectors, output_component_count=output_components, rows=records))
    return dict(status='complete', data_offset=origin + start, byte_length=end - start,
                tables=tables, word_count=expected, dependency_bits=total_edges,
                scope='public packed component-grid dependencies only; signature allocation, instructions and game identities unverified')
