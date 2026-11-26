"""Bounded family-581 kind-A8 maps with opaque u32 values.

Integer values are not interpreted as record ordinals, offsets or audio IDs.
The optional key selection uses complete words and does not assign semantics
to a key spelling. Original index spans and unclaimed suffixes remain visible.
"""
from __future__ import annotations

import struct

from . import audio_config, audio_config_hierarchy, audio_config_parameters, audio_config_sections


def _key(value):
    if value is not None and (type(value) is not int or not 0 <= value <= 0xffffffff):
        raise ValueError('map key must be a complete unsigned 32-bit word')


def parse(data: bytes, *, key_hash=None, max_nodes=100000):
    """Validate every A8 map before selecting records; no prefix results on failure."""
    _key(key_hash)
    consume, used = audio_config._budget(max_nodes)
    view = audio_config_sections.parse_index(data, max_nodes=max_nodes)
    consume(view['nodes'])
    rows = []; total = 0; entries = 0; selected_entries = 0; suffixes = 0
    wanted = None if key_hash is None else f'0x{key_hash:08x}'
    for record in view['records']:
        if record['raw_kind_u8'] != 0xa8:
            continue
        at, span = record['data_offset'], record['byte_length']
        if span < 8:
            raise ValueError('truncated A8 map header')
        kind, count = struct.unpack_from('<II', data, at)
        if kind != 0xa8:
            raise ValueError('unsupported A8 map kind/flags word')
        if count > (span-8)//8:
            raise ValueError('A8 map count escapes its index-bounded span')
        length = 8+8*count
        suffix = data[at+length:at+span]
        # Six discovery spans contain a zero word after the complete pairs.
        # Preserve it as unclaimed bytes; never assume padding or another object.
        if suffix not in (b'', bytes(4)):
            raise ValueError('unsupported A8 map unclaimed suffix')
        consume(1+count)
        pairs = []; previous = -1
        for i in range(count):
            pos = at+8+8*i
            key, value = struct.unpack_from('<II', data, pos)
            if key <= previous:
                raise ValueError('A8 map keys must be strictly increasing and unique')
            previous = key
            pairs.append(dict(key_hash=f'0x{key:08x}', value_u32=value,
                value_bits=f'0x{value:08x}', key_offset=pos, value_offset=pos+4))
        total += 1; entries += count; suffixes += bool(suffix)
        if wanted is not None and not any(p['key_hash'] == wanted for p in pairs):
            continue
        selected_entries += count
        rows.append(dict(ordinal=record['ordinal'], name_hash=record['name_hash'],
            data_offset=at, indexed_span_bytes=span, counted_payload_bytes=length,
            entry_count=count, entries=pairs, opaque_suffix_hex=suffix.hex(),
            extent_status='counted_prefix_with_opaque_suffix' if suffix else 'counted_prefix_exhausts_index_span'))
    return dict(status='parsed', source_sha256=view['sha256'], records=rows,
        total_maps=total, total_entries=entries, selected_maps=len(rows),
        selected_entries=selected_entries, spans_with_unclaimed_suffix=suffixes,
        selected_key_hash=wanted, nodes=used(),
        interpretation='stored sorted key/u32 pairs only; value addressing, object extents and station/recording links unconfirmed')


def inspect_file(path, *, slot_hierarchy=False, parameters=False, key_hash=None, **kwargs):
    """Opt into the measured length-section index and source-rechecked map views."""
    _key(key_hash)
    if slot_hierarchy:
        report = audio_config_hierarchy.inspect_file(path, index_sections=True, parameters=parameters, **kwargs)
    elif parameters:
        report = audio_config_parameters.inspect_file(path, index_sections=True, **kwargs)
    else:
        report = audio_config_sections.inspect_file(path, **kwargs)
    remaining = kwargs.get('max_nodes', 100000)-report['summary']['nodes']
    counts = dict(keyed_maps=0, keyed_map_entries=0, selected_keyed_maps=0, selected_map_entries=0)
    for resource in report['resources']:
        if resource['raw_family'] != 581:
            continue
        try:
            if remaining < 1:
                raise audio_config.ConfigLimitError('config map view exceeds node budget')
            data = audio_config_sections._read_source(path, resource['source'])
            maps = parse(data, key_hash=key_hash, max_nodes=remaining)
        except (OSError, ValueError) as exc:
            resource['keyed_maps'] = dict(status='refused', records=[], reason=str(exc))
            report['status'] = 'partial'
            if isinstance(exc, audio_config.ConfigLimitError):remaining = 0
            continue
        cost = maps.pop('nodes'); remaining -= cost; report['summary']['nodes'] += cost
        resource['keyed_maps'] = maps
        for key, field in (('keyed_maps','total_maps'), ('keyed_map_entries','total_entries'),
                           ('selected_keyed_maps','selected_maps'), ('selected_map_entries','selected_entries')):
            counts[key] += maps[field]
    report['summary'].update(counts)
    return report
