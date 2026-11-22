"""Bounded clip-group/segment/animation-buffer associations from local bytes.

Only independently observed layouts are followed. Full-width references, names,
array extents and redundant buffer length fields must agree. Timing fields,
header roles, channel formats and packed contents remain unknown. No external
implementation, game-specific table or fixture is used.
"""
from __future__ import annotations

import hashlib
import struct

from . import anim_resources as resources, names

BASE = resources.VIRTUAL_BASE
MAX_NAME = 512


def resolve(data, record_start, *, consume, hash_cache=None, with_packed_layout=False):
    """Bind a named clip's component graph, or return one explicit refusal.

    A failed graph returns no prefix of groups/segments/buffers. It does not
    invalidate an independently verified clip-name binding. Budget exhaustion
    propagates to discard dictionary output. Repeated aliases remain separate
    observations; there is no recursive pointer or packed-data interpretation.
    """
    if with_packed_layout:
        from . import anim_packed
    consume()
    result = dict(status='unresolved', interpretation='candidate',
                  candidate_profile='local_clip_animation_buffers_v1', groups=[])
    context = {}
    cache = hash_cache if hash_cache is not None else {}

    def span(word, length, label):
        at = word - BASE
        if at < 112 or length < 0 or at > len(data) - length:
            raise ValueError(f'component {label} span exceeds dictionary bounds or overlaps header')
        return at

    def bits(at, size):
        return '0x' + data[at:at + size][::-1].hex()

    def array(at, stride, label):
        word, a, b, tail = struct.unpack_from('<QHHI', data, at)
        header = dict(header_data_offset=at, header_bits=bits(at, 16),
                      reference_bits=f'0x{word:016x}', u16_08=a, u16_0a=b,
                      unknown_0c=f'0x{tail:08x}')
        if a != b or tail:
            raise ValueError(f'unsupported component {label} header: unequal u16 words or nonzero tail')
        if a == 0:
            if word:
                raise ValueError(f'unsupported component empty {label} with nonzero reference')
            pos = None
        else:
            pos = span(word, a * stride, label)
        header.update(count=a, stride=stride, data_offset=pos, byte_length=a * stride)
        return header

    def animation_name(word, key):
        at = span(word, 1, 'animation name')
        end = data.find(b'\0', at, min(len(data), at + MAX_NAME + 1))
        if end < 0:
            raise ValueError('component animation name lacks a bounded NUL terminator')
        raw = data[at:end]
        if not raw or any(b < 32 or b > 126 for b in raw):
            raise ValueError('component animation name is not supported printable ASCII')
        consume(1 + (len(raw) + 63) // 64)
        text = raw.decode('ascii')
        stem = text.rsplit('/', 1)[-1][:-5]
        if not text.startswith('pack:/') or not text.endswith('.anim') or not stem:
            raise ValueError('component name is not a supported pack animation path')
        if names.joaat(stem) != key:
            raise ValueError('component animation name stem hash differs from its segment key')
        return dict(value=text, data_offset=at, byte_length=len(raw),
                    reference_bits=f'0x{word:016x}')

    try:
        span(BASE + record_start, 144, 'owning clip prefix')
        head = array(record_start + 104, 24, 'groups')
        result['header'] = head
        groups, animation_links, payload_spans = [], 0, 0
        consume(head['count'])
        for i in range(head['count']):
            context = dict(failed_group_index=i)
            at = head['data_offset'] + i * 24
            if struct.unpack_from('<I', data, at + 20)[0]:
                raise ValueError('unsupported component group reserved word')
            segments = array(at, 56, 'segments')
            consume(segments['count'])
            group = dict(index=i, data_offset=at, byte_length=24, value_bits=bits(at, 24),
                         duration_candidate_bits=bits(at + 16, 4), header=segments, segments=[])
            for j in range(segments['count']):
                context = dict(failed_group_index=i, failed_segment_index=j)
                pos = segments['data_offset'] + j * 56
                word, key, zero = struct.unpack_from('<QII', data, pos)
                if zero:
                    raise ValueError('unsupported component segment reserved word')
                anim_at = span(word, 112, 'animation prefix')
                if data[anim_at:anim_at + 16] != bytes(16) or data[anim_at + 56:anim_at + 72] != bytes(16):
                    raise ValueError('unsupported component animation-prefix attributes')
                consume()
                name = animation_name(struct.unpack_from('<Q', data, anim_at + 48)[0], key)
                maximum = struct.unpack_from('<Q', data, anim_at + 72)[0]
                refs = array(anim_at + 80, 8, 'buffer references')
                if refs['count'] == 0:
                    raise ValueError('component animation has no validated packed-buffer references')
                consume(refs['count'])
                buffers = []
                for k in range(refs['count']):
                    context = dict(failed_group_index=i, failed_segment_index=j, failed_payload_index=k)
                    reference_at = refs['data_offset'] + k * 8
                    buffer_word = struct.unpack_from('<Q', data, reference_at)[0]
                    buffer_at = span(buffer_word, 32, 'packed-buffer header')
                    body, zero = struct.unpack_from('<II', data, buffer_at + 4)
                    if zero:
                        raise ValueError('unsupported component packed-buffer reserved word')
                    length = 32 + body
                    span(buffer_word, length, 'packed buffer')
                    consume(1 + (length + 65535) // 65536)
                    identity = buffer_at, length
                    if identity not in cache:
                        cache[identity] = hashlib.sha256(memoryview(data)[buffer_at:buffer_at + length]).hexdigest()
                    buffers.append(dict(index=k, reference_data_offset=reference_at,
                        reference_bits=f'0x{buffer_word:016x}', data_offset=buffer_at,
                        byte_length=length, body_byte_length=body,
                        header_bits=bits(buffer_at, 32), sha256=cache[identity],
                        interpretation='inferred bounded packed buffer; contents undecoded'))
                context = dict(failed_group_index=i, failed_segment_index=j)
                if max(b['byte_length'] for b in buffers) != maximum:
                    raise ValueError('component maximum-buffer word differs from referenced buffer lengths')
                group['segments'].append(dict(index=j, data_offset=pos, byte_length=56,
                    value_bits=bits(pos, 56), animation_key=f'0x{key:08x}',
                    animation=dict(reference_bits=f'0x{word:016x}', data_offset=anim_at,
                        prefix_byte_length=112, header_bits=bits(anim_at, 112), name=name,
                        maximum_buffer_bytes=maximum, buffer_reference_header=refs, buffers=buffers)))
                if with_packed_layout:
                    group['segments'][-1]['animation']['packed_layout'] = anim_packed.inspect_animation(
                        data, anim_at, buffers, consume=consume)
                animation_links += 1
                payload_spans += len(buffers)
            groups.append(group)
        result.update(status='complete', interpretation='inferred',
                      profile=result.pop('candidate_profile'), groups=groups,
                      group_count=len(groups), animation_links=animation_links, payload_spans=payload_spans)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result.update(reason=str(exc), **context)
    return result
