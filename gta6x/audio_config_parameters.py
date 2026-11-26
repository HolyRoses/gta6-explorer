"""Checked named binary32 config scalars, separate from radio graph semantics.

The observed family-26 kind-2 layout is name/kind word, AAAAAAAA sentinel,
then one finite little-endian float. Names require the complete offset/hash
association from the original reader. A name does not establish runtime use,
units, station membership, category rules or an intro-to-song reference.
"""
from __future__ import annotations

import hashlib
import math
import struct

from . import audio_config, audio_config_sections


def parse(data: bytes, name_table: bytes, *, max_nodes=100000):
    """Decode the exact named scalar profile atomically; keep other kinds opaque."""
    consume, used = audio_config._budget(max_nodes)
    if not isinstance(name_table, bytes) or not 0 < len(name_table) <= audio_config.MAX_RESOURCE:
        raise ValueError('invalid named scalar name table')
    view = audio_config.parse_index(data, max_nodes=max_nodes)
    consume(view['nodes'])
    if view['raw_family'] != 26:
        raise ValueError('named scalar parameters require config family 26')
    consume(len(view['records']))
    named = audio_config.attach_names(view, data, name_table)
    if named is None:
        raise ValueError('named scalar parameters require a complete checked name table')
    records = []
    for record in named:
        if record['raw_kind_u8'] != 2:
            continue
        at = record['data_offset']
        if record['byte_length'] != 12 or data[at+4:at+8] != b'\xaa'*4:
            raise ValueError('unsupported named kind-2 scalar layout')
        bits, = struct.unpack_from('<I', data, at+8)
        value, = struct.unpack_from('<f', data, at+8)
        if not math.isfinite(value):
            raise ValueError('nonfinite named scalar parameter')
        consume()
        records.append(dict(ordinal=record['ordinal'], name_hash=record['name_hash'],
            name=record['name'], name_table_offset=record['name_table_offset'],
            data_offset=at, byte_length=12, raw_kind_u8=2,
            value_bits=f'0x{bits:08x}', value=value, encoding='float32_le'))
    return dict(status='parsed', records=records, nodes=used(),
        source_sha256=view['sha256'], name_table_sha256=hashlib.sha256(name_table).hexdigest(),
        interpretation='stored named scalars only; runtime use and units unconfirmed')


def inspect_file(path, *, index_sections=False, **kwargs):
    """Add source-rechecked scalar views without changing the original parser."""
    reader = audio_config_sections if index_sections else audio_config
    report = reader.inspect_file(path, **kwargs)
    remaining = kwargs.get('max_nodes', 100000) - report['summary']['nodes']
    total = 0
    for resource in report['resources']:
        if resource['raw_family'] != 26 or 'name_table_source' not in resource:
            resource['scalar_parameters'] = dict(status='unavailable', records=[],
                reason='no complete checked family-26 name association')
            continue
        try:
            if remaining < 1:
                raise audio_config.ConfigLimitError('named scalar report exceeds node budget')
            data = audio_config_sections._read_source(path, resource['source'])
            table = audio_config_sections._read_source(path, resource['name_table_source'])
            scalars = parse(data, table, max_nodes=remaining)
        except (OSError, ValueError) as exc:
            resource['scalar_parameters'] = dict(status='refused', records=[], reason=str(exc))
            report['status'] = 'partial'
            if isinstance(exc, audio_config.ConfigLimitError):
                remaining = 0
            continue
        nodes = scalars.pop('nodes')
        remaining -= nodes
        report['summary']['nodes'] += nodes
        total += len(scalars['records'])
        resource['scalar_parameters'] = scalars
    report['summary']['named_scalars'] = total
    return report
