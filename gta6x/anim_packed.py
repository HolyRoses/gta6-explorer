"""Observed packed-animation header regions and raw channel-binding candidates.

Version/type meanings, channel identifiers, auxiliary row semantics, sample
values and timing remain unconfirmed. Bounds and redundant sample-count/length
relationships authorize metadata views only. No external implementation,
channel table or game fixture is used; packed samples are not decoded.
"""
from __future__ import annotations

import struct

from . import anim_resources as resources

BASE = resources.VIRTUAL_BASE


def inspect_animation(data, animation_start, buffers, *, consume, with_channels=False, with_storage=False, with_payloads=False, with_bitrows=False, with_lookups=False, with_prefix=False):
    """Inspect one bounded animation's header/channel metadata atomically.

    Invalid or unsupported layouts return no prefix binding/buffer rows. Parent
    opaque-buffer associations remain independently valid. Budget exhaustion
    propagates to discard dictionary output. All offsets refer to the original
    joined dictionary; region offsets are also retained relative to each buffer.
    """
    if with_lookups or with_prefix:
        with_bitrows = True
    if with_payloads or with_bitrows:
        with_storage = True
    if with_storage:
        with_channels = True
    consume()
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile='packed_animation_layout_v1', bindings=[], buffers=[])
    context = {}

    def span(at, length, label):
        if at < 112 or length < 0 or at > len(data) - length:
            raise ValueError(f'packed {label} exceeds dictionary bounds or overlaps header')
        return at

    def bits(at, length):
        return '0x' + data[at:at + length][::-1].hex()

    def array(at, stride, label):
        word, count, other, tail = struct.unpack_from('<QHHI', data, at)
        if count != other or tail:
            raise ValueError(f'unsupported packed {label} array header')
        if count == 0:
            if word:
                raise ValueError(f'unsupported packed empty {label} with nonzero reference')
            offset = None
        else:
            offset = span(word - BASE, count * stride, label)
        consume(1 + count)
        return dict(header_data_offset=at, header_bits=bits(at, 16), reference_bits=f'0x{word:016x}',
                    count=count, stride=stride, data_offset=offset, byte_length=count * stride)

    try:
        span(animation_start, 112, 'animation prefix')
        total, step = struct.unpack_from('<HH', data, animation_start + 36)
        if not total or not step:
            raise ValueError('unsupported packed zero sample-count or step candidate')
        refs = array(animation_start + 80, 8, 'buffer references')
        if refs['count'] != len(buffers) or not buffers:
            raise ValueError('packed buffer descriptors differ from the referenced array')
        binding_header = array(animation_start + 96, 12, 'channel-binding candidates')
        bindings = []
        for i in range(binding_header['count']):
            at = binding_header['data_offset'] + 12 * i
            bindings.append(dict(index=i, data_offset=at, byte_length=12, value_bits=bits(at, 12),
                raw_words=[f'0x{word:08x}' for word in struct.unpack_from('<III', data, at)],
                interpretation='candidate channel binding; identifiers and type meanings unknown'))
        layouts, samples, auxiliary_count = [], [], 0
        for i, buffer in enumerate(buffers):
            context = dict(failed_buffer_index=i)
            at, length = buffer['data_offset'], buffer['byte_length']
            reference_at = refs['data_offset'] + 8 * i
            word = struct.unpack_from('<Q', data, reference_at)[0]
            if word != BASE + at:
                raise ValueError('packed buffer descriptor differs from its original reference')
            span(at, length, 'buffer')
            if length < 32:
                raise ValueError('packed buffer header is truncated')
            w = struct.unpack_from('<5I5H2B', data, at)
            if length != 32 + w[1] or w[2]:
                raise ValueError('packed buffer length/reserved word differs from its header')
            if w[5] != 2 or w[10] != 11:
                raise ValueError('unsupported packed header markers; requires u16_14=2 and u8_1e=11')
            first, second, count, flag = w[3], w[4], w[6], w[11]
            if not 32 <= first <= second <= length:
                raise ValueError('packed section offsets are unordered or exceed the buffer')
            aux_rows = (flag >> 4) + (flag & 15)
            if length - second != aux_rows * 6:
                raise ValueError('packed auxiliary span disagrees with the header nibble counts')
            if not count or (i < len(buffers) - 1 and count != step + 1) or count > step + 1:
                raise ValueError('packed buffer sample-count candidate disagrees with animation step')
            consume(6 + aux_rows)  # Header, four regions, sample window and every auxiliary row.
            regions = [dict(name=name, relative_offset=start, data_offset=at + start, byte_length=end - start)
                       for name, start, end in (('header', 0, 32), ('section_0', 32, first),
                                               ('section_1', first, second), ('auxiliary', second, length))]
            rows = []
            for j in range(aux_rows):
                pos = at + second + j * 6
                a, b, c, d = struct.unpack_from('<BBHH', data, pos)
                rows.append(dict(index=j, data_offset=pos, byte_length=6, value_bits=bits(pos, 6),
                                 u8_00=a, u8_01=b, u16_02=c, u16_04=d,
                                 interpretation='raw auxiliary row; channel association and codec unknown'))
            start = i * step
            sample = dict(buffer_index=i, first_index=start, count=count, last_index=start + count - 1)
            layouts.append(dict(index=i, data_offset=at, byte_length=length, header_bits=bits(at, 32),
                header=dict(unknown_00=f'0x{w[0]:08x}', body_byte_length=w[1], unknown_08=f'0x{w[2]:08x}',
                    section_1_relative_offset=first, auxiliary_relative_offset=second,
                    u16_14=w[5], u16_16=w[6], u16_18=w[7], u16_1a=w[8], u16_1c=w[9],
                    u8_1e=w[10], u8_1f=flag),
                regions=regions, auxiliary_high_nibble=flag >> 4, auxiliary_low_nibble=flag & 15,
                auxiliary_rows=rows, sample_index_span=sample))
            if with_channels:
                from . import anim_channels
                layouts[-1]['channel_layout'] = anim_channels.inspect_buffer(
                    data, at, length, len(bindings), consume=consume)
            if with_storage:
                from . import anim_storage
                layouts[-1]['storage_layout'] = anim_storage.inspect_buffer(
                    data, at, length, len(bindings), consume=consume)
            if with_payloads:
                from . import anim_payloads
                layouts[-1]['payload_layout'] = anim_payloads.inspect_buffer(
                    data, at, length, len(bindings), consume=consume)
            if with_bitrows:
                from . import anim_bitrows
                layouts[-1]['bitrow_layout'] = anim_bitrows.inspect_buffer(
                    data, at, length, len(bindings), consume=consume)
            if with_lookups:
                from . import anim_lookups
                layouts[-1]['lookup_layout'] = anim_lookups.inspect_buffer(
                    data, at, length, len(bindings), consume=consume)
            if with_prefix:
                from . import anim_prefix
                layouts[-1]['prefix_layout'] = anim_prefix.inspect_buffer(
                    data, at, length, len(bindings), consume=consume)
            samples.append(sample)
            auxiliary_count += aux_rows
        context = {}
        if 1 + sum(s['count'] - 1 for s in samples) != total or samples[-1]['last_index'] != total - 1:
            raise ValueError('packed sample counts do not reconcile with one-sample overlaps and animation total')
        result.update(status='complete', interpretation='inferred structural metadata; samples/timing/codec meanings unconfirmed',
                      profile=result.pop('candidate_profile'), binding_header=binding_header,
                      bindings=bindings, buffers=layouts, binding_count=len(bindings), buffer_count=len(layouts),
                      auxiliary_row_count=auxiliary_count,
                      sample_index_layout=dict(interpretation='inferred overlapping sample indices; no decoded sample values or rate',
                                               total_count_candidate=total, step_candidate=step, spans=samples))
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result.update(reason=str(exc), **context)
    return result
