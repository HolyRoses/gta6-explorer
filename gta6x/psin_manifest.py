"""Full native PSIN inspection of confined manifest-pinned immutable inputs.

The manifest selects files, not trusted parsed reports. Selected bytes are read
once, bounded and hashed, then verified with the existing raw PSIN grammar.
Those same immutable bytes feed normal schema/instance/context inspection, so
source changes cannot route a later filename read into archive carving.
"""
from __future__ import annotations

import hashlib

from . import psin_registry, psin_schema, world_manifest, world_resources

MAX_BYTES = world_manifest.MAX_BYTES
MAX_RESOURCE_BYTES = world_resources.MAX_RESOURCE_BYTES
MAX_NODES = 2_000_000


def inspect(manifest_path, *, max_nodes=100000, max_resources=0,
            max_input_bytes=MAX_BYTES, max_source_bytes=MAX_RESOURCE_BYTES,
            protected_outputs=(), **psin_options):
    """Inspect complete selected PSIN exports without opening archive metadata.

    Normal PSIN view/query options are validated before manifest access. Each
    selected file is read once into immutable bytes and verified before the
    source orchestration receives it. All verification and reader work share
    ``max_nodes``. Explicit resource limits retain uninspected file coverage;
    empty selections and malformed/budget inputs produce no report prefix.
    """
    world_manifest._uint(max_nodes, MAX_NODES, 'PSIN node limit', 1)
    world_manifest._uint(max_resources, 1_000_000, 'PSIN resource limit')
    world_manifest._uint(max_input_bytes, MAX_BYTES, 'PSIN aggregate input limit', 1)
    world_manifest._uint(max_source_bytes, MAX_RESOURCE_BYTES, 'PSIN source byte limit', 1)
    forbidden = {'paths', 'limit', 'max_nodes', '_source_items'}
    if forbidden.intersection(psin_options):
        raise ValueError('unsupported PSIN manifest source option')
    registry = psin_options.get('registry')
    if registry is not None and not isinstance(registry, psin_registry.Registry):
        raise ValueError('PSIN manifest registry must be a native metadata registry')
    depth = psin_options.get('max_depth', 16)
    if type(depth) is not int or not 1 <= depth <= 64:
        raise ValueError('PSIN manifest max_depth must be an integer from 1 to 64')
    used = 0
    def charge(amount=1):
        nonlocal used
        if type(amount) is not int or amount < 0 or amount > max_nodes-used:
            raise world_resources.WorldResourceLimitError('PSIN manifest inspection exceeds shared node budget')
        used += amount
    # Reuse the normal source/view/query preflight. The empty iterator opens no
    # file. Any aggregate empty-index work is accounted rather than hidden.
    try:
        empty = psin_schema.inspect_sources([], limit=None, max_nodes=max_nodes,
                                            _source_items=(), **psin_options)
    except TypeError as exc:
        raise ValueError('unsupported PSIN manifest inspection option') from exc
    charge(empty['summary'].get('metadata_nodes', 0))
    if (empty['summary'].get('hash_uses_refused') or
            empty['summary'].get('schema_search_refused') or
            empty['summary'].get('graph_dot_refused')):
        raise world_resources.WorldResourceLimitError('PSIN manifest option validation exhausted its work budget')
    plan = world_manifest.preflight(manifest_path, protected_outputs=protected_outputs, consume=charge)
    selected = plan['files'][:max_resources] if max_resources else plan['files']
    uninspected = plan['files'][len(selected):]
    if not selected:
        raise ValueError(f"manifest contains no complete PSIN exports ({len(plan['skipped'])} skipped entries)")
    total = sum(row['bytes'] for row in selected)
    if total > max_input_bytes or any(row['bytes'] > max_source_bytes for row in selected):
        raise world_resources.WorldResourceLimitError('PSIN manifest selected files exceed input byte limits')
    # Read, hash and schema/metadata serialization allowances. Descriptor/table
    # work below is separately precharged for both native parsing passes.
    charge(sum(1 + 4*((row['bytes']+4095)//4096) for row in selected))
    items = []
    for row in selected:
        with open(row['file'], 'rb') as handle:
            data = handle.read(row['bytes']+1)
        if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('PSIN manifest selected source differs from its pinned size or hash')
        # No archive fallback: unsupported bytes fail this exact existing grammar.
        # Charge twice to include the normal orchestration's subsequent reparse.
        structures, enums, _, _ = world_resources._psin_metadata(
            data, lambda amount=1: charge(2*amount))
        # Normal schema serialization may recheck representability of an enum
        # for each referencing field. Charge that repeated member fanout before
        # invoking it; one source-level enum inventory is not the same work.
        charge(1 + len(structures) + len(enums)
               + sum(len(owner['fields']) for owner in structures))
        enum_work = {}
        for enum in enums:
            key = int(enum['hash'], 16)
            enum_work[key] = enum_work.get(key, 0) + 1 + len(enum['members'])
        fanout = sum(enum_work.get(field[3], 0)
            for owner in structures for field in owner['fields']
            if field[2] & 0xffff in (0x62, 0x63, 0x65, 0x68))
        charge(fanout)
        source = dict(file=row['relative_file'], offset=0, blocks=1)
        items.append((source, data, None))
    overhead = used
    if used >= max_nodes:
        raise world_resources.WorldResourceLimitError('PSIN manifest has no remaining PSIN inspection work budget')
    report = psin_schema.inspect_sources([], limit=None, max_nodes=max_nodes-used,
                                        _source_items=items, **psin_options)
    used += report['summary'].get('metadata_nodes', 0)
    if len(report['resources']) != len(selected):
        raise ValueError('PSIN manifest source inspection changed the selected resource count')
    for row, resource in zip(selected, report['resources']):
        if (resource.get('status') != 'ok' or resource.get('sha256') != row['sha256']
                or resource.get('bytes') != row['bytes'] or not resource.get('checksum_verified')):
            raise ValueError('PSIN manifest source inspection differs from its verified immutable input')
    report['manifest_input'] = dict(format='gta6x-psin-manifest-input-v1',
        file=plan['file'], sha256=plan['sha256'], status='partial' if uninspected else 'complete',
        coverage_complete=not uninspected, selected=selected, skipped=plan['skipped'],
        uninspected=uninspected, source_archive_metadata_reopened=False,
        immutable_verified_inputs=True,
        summary=dict(exported_rows=len(plan['files']), selected_files=len(selected),
            skipped_rows=len(plan['skipped']), uninspected_files=len(uninspected),
            verified_bytes=total, verification_nodes=overhead),
        interpretation='Pinned complete PSIN file bytes only; no archive allocation, asset or semantic ownership claim.')
    report['summary'].update(metadata_nodes=used, manifest_verification_nodes=overhead,
                             manifest_verification_bytes=total)
    return report
