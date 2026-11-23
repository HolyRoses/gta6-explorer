"""Opt-in structural view of the discovery family-581 audio index.

The two length-prefixed sections contain counted raw u32 groups. Their roles
are unknown: neither group order nor hash-like values establish playlists.
The original strict config parser remains unchanged.
"""
from __future__ import annotations

import hashlib
import os
import struct
import zlib

from . import audio_config


def _section(data, at, consume):
    if at + 8 > len(data):
        raise ValueError('incomplete audio index section')
    size, count = struct.unpack_from('<II', data, at)
    end = at + 4 + size
    if size < 4 or size % 4 or end > len(data) or count > (size - 4) // 8:
        raise ValueError('audio index section extent/count is invalid')
    values_at = at + 8 + count * 8
    value_count = (end - values_at) // 4
    consume(1 + count + value_count)
    groups = []
    cursor = 0
    for i in range(count):
        start, length = struct.unpack_from('<II', data, at + 8 + 8*i)
        if start != cursor or not length or length > value_count - cursor:
            raise ValueError('audio index groups do not partition the raw value array')
        groups.append(dict(ordinal=i, start=start, count=length))
        cursor += length
    if cursor != value_count:
        raise ValueError('audio index section has unclaimed raw values')
    return dict(data_offset=at, byte_length=4 + size, group_count=count,
        groups=groups, values_data_offset=values_at,
        raw_u32_values=[f'0x{struct.unpack_from("<I",data,values_at+4*i)[0]:08x}'
                        for i in range(value_count)],
        interpretation='counted raw u32 groups; reference targets and ordering semantics unresolved'), end


def parse_index(data: bytes, *, max_nodes=100000):
    """Parse the measured length-section layout, without assigning semantics.

    Reuse the strict parser for the unchanged data region and hash/offset
    pairs. Only the synthetic empty section headers differ; all reported
    extents and hashes are restored to the original source before return.
    """
    consume, used = audio_config._budget(max_nodes)
    if not isinstance(data, bytes) or not 40 <= len(data) <= audio_config.MAX_RESOURCE:
        raise ValueError('extended audio-config input size is unsupported')
    family, size = struct.unpack_from('<II', data)
    if family != 581:
        raise ValueError('unsupported extended audio-config family')
    data_end = 8 + size
    if size < 5 or data_end > len(data) - 28:
        raise ValueError('extended audio-config data extent is invalid')
    first, at = _section(data, data_end, consume)
    second, at = _section(data, at, consume)
    if not first['group_count'] or second['group_count']:
        raise ValueError('unsupported extended audio-config section profile')
    if max_nodes - used() < 1:
        raise audio_config.ConfigLimitError('audio-config output exceeds node limit')
    canonical = data[:data_end] + audio_config.FOOTER + data[at:]
    view = audio_config.parse_index(canonical, max_nodes=max_nodes-used())
    consume(view.pop('nodes'))
    index_end = at + 4 + 8 * view['index']['record_count']
    view.update(byte_length=len(data), sha256=hashlib.sha256(data).hexdigest(),
        index_sections=[first, second], nodes=used(),
        layout_status='structural_discovery_profile_only')
    view['index'].update(data_offset=data_end, byte_length=index_end-data_end,
        pairs_data_offset=at+4, layout='two_length_sections_then_hash_offset_pairs')
    view['opaque_tail']['data_offset'] = index_end
    return view


def _read_source(path, source):
    """Reproduce only the already-carved complete pages, checking identity."""
    data = bytearray()
    previous_end = None
    file_size = os.path.getsize(path)
    segments = source['segments']
    if (not segments or len(segments) > audio_config.MAX_RESOURCE // 65536
            or source['offset'] != segments[0][0]):
        raise ValueError('invalid extended audio-config page directory')
    with open(path, 'rb') as fh:
        for i, (offset, packed, size) in enumerate(segments):
            if (any(type(n) is not int for n in (offset, packed, size))
                    or not 0 <= offset < offset+packed <= file_size
                    or not 0 < size <= 65536 or packed > audio_config.MAX_RESOURCE):
                raise ValueError('invalid extended audio-config source page')
            if (size != 65536 if i < len(segments)-1 else size >= 65536):
                raise ValueError('extended audio-config lacks complete page framing')
            if previous_end is not None:
                aligned = (previous_end + 15) & ~15
                fh.seek(previous_end)
                if offset != aligned or any(fh.read(aligned-previous_end)):
                    raise ValueError('extended audio-config page gap is invalid')
            fh.seek(offset)
            obj = zlib.decompressobj()
            try:
                page = obj.decompress(fh.read(packed), size+1)
            except zlib.error as exc:
                raise ValueError('invalid extended audio-config page') from exc
            if not obj.eof or obj.unused_data or obj.unconsumed_tail or len(page) != size:
                raise ValueError('extended audio-config page identity/extent is invalid')
            data.extend(page)
            if len(data) > audio_config.MAX_RESOURCE:
                raise audio_config.ConfigLimitError('extended audio-config resource exceeds assembly limit')
            previous_end = offset + packed
    if hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('extended audio-config resource identity changed')
    return bytes(data)


def inspect_file(path, **kwargs):
    """Extend supported discovery indexes; retain every other refusal."""
    report = audio_config.inspect_file(path, **kwargs)
    max_nodes = kwargs.get('max_nodes', 100000)
    remaining = max_nodes - report['summary']['nodes']
    refused = []
    for source in report['refused']:
        if source['reason'] != 'unsupported audio-config index prefix':
            refused.append(source)
            continue
        try:
            data = _read_source(path, source)
            if struct.unpack_from('<I', data)[0] != 581:
                refused.append(source)
                continue
            if remaining < 1:
                raise audio_config.ConfigLimitError('audio-config output exceeds node limit')
            view = parse_index(data, max_nodes=remaining)
        except (OSError, ValueError) as exc:
            refused.append(dict(source, reason=str(exc)))
            continue
        remaining -= view['nodes']
        report['summary']['nodes'] += view.pop('nodes')
        report['summary']['records'] += len(view['records'])
        report['summary']['resources'] += 1
        view.update(source={k:v for k,v in source.items() if k != 'reason'},
            name_table_reason='no extended-family name association established',
            wave_slots=dict(status='unresolved', reason='no typed slot/playlist rule established', entries=[]),
            music_records=[])
        report['resources'].append(view)
    report['resources'].sort(key=lambda r:r['source']['offset'])
    report['refused'] = refused
    report['status'] = 'partial' if refused else 'indexed'
    report['summary']['raw_index_groups'] = sum(s['group_count']
        for r in report['resources'] for s in r.get('index_sections', []))
    report['summary']['raw_index_values'] = sum(len(s['raw_u32_values'])
        for r in report['resources'] for s in r.get('index_sections', []))
    return report
