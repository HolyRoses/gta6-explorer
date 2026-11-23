"""Counted packed-animation width tables and complete opaque bit rows.

Widths, counts, row strides and zero padding are independently cross-checked.
Whole source-order rows retain bits; no per-channel bit partition, slot order,
scalar representation, quantizer, codec, transform or timing is inferred.
"""
from __future__ import annotations

import hashlib
import struct

from . import anim_channels, anim_storage, anim_resources as resources

PROFILE = 'counted_width_tables_and_opaque_bit_rows_v1'


def inspect_buffer(data, offset, length, binding_count, *, consume):
    """Return exact bounded tables/rows atomically, or an explicit refusal.

    Two tables explain the complete row width. The variable table's count and
    extent are independent header observations. Payload words remain opaque;
    their count does not authorize interpretation as decoded numeric samples.
    """
    consume()
    result = dict(status='unresolved', interpretation='candidate', candidate_profile=PROFILE,
                  fixed_width_records=[], variable_width_records=[], rows=[])
    try:
        if len(data) > resources.MAX_RESOURCE:
            raise ValueError('bit-row input exceeds resource size limit')
        directory = anim_channels.inspect_buffer(data, offset, length, binding_count,
                                                  consume=lambda n=1: None)
        if directory['status'] != 'complete':
            raise ValueError('bit rows require a supported directory: ' + directory['reason'])
        storage = anim_storage.inspect_buffer(data, offset, length, binding_count,
                                               consume=lambda n=1: None)
        if storage['status'] != 'complete':
            raise ValueError('bit rows require supported storage: ' + storage['reason'])
        groups = [group['count'] for group in directory['groups']]
        if any(groups[i] for i in (3, 6, 9)):
            raise ValueError('width-table profile requires empty directory groups 3, 6 and 9')
        prefix = storage['regions'][1]
        start, end = prefix['data_offset'], prefix['data_offset'] + prefix['byte_length']
        fixed_start = start + 12 * (groups[0] + groups[1]) + 4 * groups[2]
        variable_start = fixed_start + 12 * groups[4]
        raw_extent = struct.unpack_from('<H', data, offset + 26)[0]
        raw_fixed_width = struct.unpack_from('<H', data, offset + 28)[0]
        variable_end = variable_start + 4 * raw_extent
        if not start <= fixed_start <= variable_start <= variable_end <= end:
            raise ValueError('width tables exceed the independently bounded body prefix')
        fixed, variable = [], []
        for i in range(groups[4]):
            at = fixed_start + i * 12
            width = struct.unpack_from('<I', data, at)[0]
            if not 1 <= width <= 32:
                raise ValueError('unsupported fixed-table width; requires 1..32 bits')
            consume()
            fixed.append(dict(source_ordinal=i, data_offset=at, byte_length=12, width_bits=width,
                parameter_bits='0x' + data[at + 4:at + 12][::-1].hex()))
        if sum(row['width_bits'] for row in fixed) != raw_fixed_width:
            raise ValueError('fixed-table widths disagree with raw u16_1c')
        pos = variable_start
        for i in range(groups[5]):
            if pos > variable_end - 20:
                raise ValueError('variable width-table header exceeds its declared word extent')
            width, unknown, count, _, _ = struct.unpack_from('<5I', data, pos)
            if not 1 <= width <= 32 or not count:
                raise ValueError('unsupported variable width/count; requires 1..32 bits and positive count')
            size = 20 + 4 * count
            if size > variable_end - pos:
                raise ValueError('variable width-table payload exceeds its declared word extent')
            consume(2)
            payload = data[pos + 20:pos + size]
            variable.append(dict(source_ordinal=i, data_offset=pos, byte_length=size,
                width_bits=width, unknown_u32_04=f'0x{unknown:08x}', opaque_word_count=count,
                parameter_bits='0x' + data[pos + 12:pos + 20][::-1].hex(),
                opaque_payload=dict(data_offset=pos + 20, byte_length=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(), interpretation='opaque stored words')))
            pos += size
        if pos != variable_end:
            raise ValueError('variable width-table records do not exhaust raw u16_1a word extent')
        fixed_bits = sum(row['width_bits'] for row in fixed)
        variable_bits = sum(row['width_bits'] for row in variable)
        width = fixed_bits + variable_bits
        descriptor = storage['sample_rows']
        stride, count = descriptor['row_stride'], descriptor['row_count']
        if stride != 4 * ((width + 31) // 32):
            raise ValueError('summed table widths disagree with the four-byte row stride')
        rows = []
        if stride:
            for i in range(count):
                at = descriptor['data_offset'] + stride * i
                raw = data[at:at + stride]
                if int.from_bytes(raw, 'little') >> width:
                    raise ValueError('nonzero high padding above summed table widths')
                consume()
                rows.append(dict(source_ordinal=i, data_offset=at, byte_length=stride,
                                 raw_bits='0x' + raw[::-1].hex()))
        consume(6)  # Two table spans, row span, width descriptor and opaque spans.
        result.update(status='complete', interpretation='inferred storage widths; complete opaque rows only',
            profile=result.pop('candidate_profile'),
            association_status='unconfirmed; no per-channel bit offsets or numeric samples emitted',
            fixed_table=dict(data_offset=fixed_start, byte_length=variable_start-fixed_start,
                             count=len(fixed), width_sum_bits=fixed_bits),
            variable_table=dict(data_offset=variable_start, byte_length=variable_end-variable_start,
                                count=len(variable), raw_u16_1a=raw_extent, width_sum_bits=variable_bits),
            preceding_prefix=dict(data_offset=start, byte_length=fixed_start-start,
                                  interpretation='opaque; width-table origin inferred from directory counts'),
            remaining_prefix=dict(data_offset=variable_end, byte_length=end-variable_end,
                                  interpretation='opaque; not recursively interpreted'),
            row_layout=dict(data_offset=descriptor['data_offset'], byte_length=descriptor['byte_length'],
                header_row_count=count, stored_rows_emitted=len(rows), row_stride=stride,
                active_bits_per_row=width, high_zero_padding_bits=stride*8-width,
                fixed_width_bits=fixed_bits, variable_width_bits=variable_bits),
            fixed_width_records=fixed, variable_width_records=variable, rows=rows)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
