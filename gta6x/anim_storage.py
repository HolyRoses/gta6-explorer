"""Bounded packed-animation byte rows and an observed zero-padding profile.

The body-relative split and fixed row stride are structural associations.
Sample values, codecs, group meanings, channel IDs and time units remain
unknown. Raw header words are retained without interpreting numeric samples.
"""
from __future__ import annotations

import struct

from . import anim_channels, anim_resources as resources

PROFILE = 'packed_animation_storage_rows_v1'


def inspect_buffer(data, offset, length, binding_count, *, consume):
    """Inspect exact storage spans without decoding or copying sample values.

    A separate bit-row view is supported only when the raw +0x1a word is zero.
    Its high row-padding bits must be zero. Other bit grammars remain explicit.
    Unsupported spans return no prefix regions; budget exhaustion propagates.
    """
    consume()
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile=PROFILE, regions=[])
    try:
        # Recheck the independently bounded directory. Its intermediate rows
        # are not emitted here; its byte search already has a separate cap.
        directory = anim_channels.inspect_buffer(data, offset, length, binding_count,
                                                  consume=lambda n=1: None)
        if directory['status'] != 'complete':
            raise ValueError('storage requires a supported channel directory: ' + directory['reason'])
        words = struct.unpack_from('<5I5H2B', data, offset)
        rows, stride, unknown_1a, width = words[6:10]
        if not rows:
            raise ValueError('unsupported zero storage row-count candidate')
        if stride % 4:
            raise ValueError('unsupported storage row stride; requires four-byte units')
        split = 32 + words[3]
        end = directory['directory']['relative_offset']
        if not 32 <= split <= end or end - split != rows * stride:
            raise ValueError('storage body-relative split, row count and stride disagree with directory')
        bit_view = dict(status='unresolved', interpretation='opaque; sample scalar and codec meanings unknown',
                        reason='nonzero raw u16_1a bit grammar is not established',
                        raw_u16_1a=unknown_1a, raw_u16_1c=width)
        if unknown_1a == 0:
            if stride != 4 * ((width + 31) // 32):
                raise ValueError('storage bit-width candidate disagrees with four-byte row stride')
            for index in range(rows):
                at = offset + split + index * stride
                if int.from_bytes(data[at:at + stride], 'little') >> width:
                    raise ValueError('nonzero high padding bits in storage row')
            bit_view = dict(status='complete', interpretation='inferred opaque little-endian bit row; values undecoded',
                            profile='zero_u16_1a_padded_bit_rows_v1', raw_u16_1a=0,
                            raw_u16_1c=width, active_bits_per_row=width,
                            high_zero_padding_bits=stride * 8 - width)
        consume(8)  # Five regions, split descriptor, row descriptor and bit view.
        regions = [dict(name=name, data_offset=offset + start, relative_offset=start,
                        byte_length=stop - start)
                   for name, start, stop in (('header', 0, 32), ('body_prefix', 32, split),
                                            ('sample_rows', split, end),
                                            ('slot_directory', end, words[4]),
                                            ('auxiliary', words[4], length))]
        result.update(status='complete', interpretation='inferred bounded byte storage; sample and codec meanings unknown',
            profile=result.pop('candidate_profile'), regions=regions,
            body_relative_split=dict(header_data_offset=offset + 12, raw_u32_0c=words[3],
                                     origin_data_offset=offset + 32, data_offset=offset + split),
            sample_rows=dict(data_offset=offset + split, byte_length=end - split,
                             row_count=rows, row_stride=stride,
                             interpretation='stored fixed-stride opaque rows; sample values undecoded'),
            sample_bit_layout=bit_view)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
