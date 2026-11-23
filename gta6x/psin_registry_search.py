"""Offline exact search of structurally checked PSIN registry metadata.

Recorded source labels and hashes are provenance, not reverified game payloads.
Low-ID declarations remain file-local metadata and never become global bindings.
The declaration/layout matcher is shared with native source inspection.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat

from . import psin_registry, psin_schema_search

PROFILE = 'offline_psin_registry_declaration_search_v1'
VERIFICATION = 'sections_validated; source_payloads_not_reverified'


def inspect(registry, *, consume, **selectors):
    """Search a native Registry object without opening its recorded sources.

    All exact selectors, conflict rules and output limits come from the shared
    declaration matcher. The caller supplies a fresh parsed Registry, not an
    authenticated serialized-report cache. No input object is modified.
    """
    psin_schema_search.validate_query(**selectors)
    if not isinstance(registry, psin_registry.Registry):
        raise ValueError('offline schema search requires a native PSIN registry')
    if (len(registry.schemas) > psin_registry.MAX_SCHEMAS
            or registry.section_bytes > psin_registry.MAX_REGISTRY_BYTES
            or registry.source_count > psin_registry.MAX_SOURCES):
        raise ValueError('offline schema search registry exceeds metadata limits')
    used = 0
    def charge(count=1):
        nonlocal used
        consume(count)
        used += count
    charge(1 + len(registry.schemas))
    sources = []
    for ident in registry.schemas:
        labels = registry.sources.get(ident)
        if not isinstance(labels, list):
            raise ValueError('offline schema search registry source labels are unavailable')
        charge(len(labels))
        for source in labels:
            registry._validate_source(source)
            sources.append(dict(source, schema_id=ident, status='ok'))
    result = psin_schema_search.inspect(registry.schemas, sources, consume=charge, **selectors)
    # These additions qualify metadata availability, not the search's exact
    # declaration/layout equality or its local source-index associations.
    charge(len(result['sources']) + len(result['matches']) + len(result['seed_layouts']))
    for source in result['sources']:
        source.update(source_payload_reverified=False, provenance='recorded_registry_label_only')
    for match in result['matches']:
        owner = int(match['structure_hash'], 16)
        match.update(registry_binding_status='reserved' if owner < 0x10000 else 'not_established',
                     namespace_scope='file_local_reserved' if owner < 0x10000 else 'registry_metadata',
                     source_payloads_reverified=False)
    for seed in result['seed_layouts']:
        seed['source_payloads_reverified'] = False
    result.update(format='gta6x-psin-registry-search-v1', profile=PROFILE,
                  verification=VERIFICATION, source_payloads_reverified=False,
                  input_scope='saved registry declarations and recorded source labels only',
                  interpretation=('Exact registry metadata matches only; source payloads are not opened or '
                    'reverified, low-ID definitions remain file-local and no instance, asset or transform '
                    'binding is established.'))
    result['summary']['nodes'] = used
    return result


def _metadata_work(obj):
    """Bound and count section/source work before the native registry parser."""
    if (not isinstance(obj, dict) or set(obj) != {'format', 'schemas'}
            or obj.get('format') != 'gta6x-psin-registry-v1'
            or not isinstance(obj['schemas'], list)
            or len(obj['schemas']) > psin_registry.MAX_SCHEMAS):
        raise ValueError('invalid offline PSIN registry structure')
    total_hex = sources = work = 0
    for entry in obj['schemas']:
        if not isinstance(entry, dict) or set(entry) != {'id', 'lsch_hex', 'lenm_hex', 'sources'}:
            raise ValueError('invalid offline PSIN registry schema entry')
        ls, en, labels = entry['lsch_hex'], entry['lenm_hex'], entry['sources']
        if (not isinstance(ls, str) or not isinstance(en, str)
                or len(ls) + len(en) > psin_registry.MAX_SECTION_BYTES * 2
                or not isinstance(labels, list) or not labels):
            raise ValueError('invalid offline PSIN registry section/source limits')
        total_hex += len(ls) + len(en)
        sources += len(labels)
        if total_hex > psin_registry.MAX_REGISTRY_BYTES * 2 or sources > psin_registry.MAX_SOURCES:
            raise ValueError('offline PSIN registry exceeds aggregate metadata limits')
        # A descriptor-sized allowance includes headers, fields, enum members
        # and hexadecimal decoding. Source metadata validation is charged too.
        # Registry.from_dict retains a list and checks source membership twice
        # for each insertion. Account for its worst-case comparison fanout
        # before calling it, rather than hiding quadratic work behind loading.
        work += 1 + len(labels) + len(labels) * (len(labels)-1)
        work += (len(ls) + len(en) + 31) // 32
    return 1 + len(obj['schemas']) + work


def inspect_file(path, *, consume, **selectors):
    """Load one bounded registry file and search under the same work budget.

    Selector validation precedes even file stat. File scan/JSON work is charged
    before reading; descriptor/source work is charged before section parsing.
    No paths recorded inside the registry are opened.
    """
    psin_schema_search.validate_query(**selectors)
    used = 0
    def charge(count=1):
        nonlocal used
        consume(count)
        used += count
    metadata_stat = os.stat(path)
    if not stat.S_ISREG(metadata_stat.st_mode):
        raise ValueError('offline PSIN registry input must be a regular file')
    size = metadata_stat.st_size
    if size > psin_registry.MAX_FILE_BYTES:
        raise ValueError('offline PSIN registry file size limit exceeded')
    scan_units = 1 + 3 * ((size + 4095) // 4096)
    charge(scan_units)
    with open(path, 'rb') as handle:
        raw = handle.read(size + 1)
    if len(raw) != size:
        raise ValueError('offline PSIN registry file size changed during reading')
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError('invalid offline PSIN registry JSON') from exc
    charge(_metadata_work(obj))
    registry = psin_registry.Registry.from_dict(obj)
    result = inspect(registry, consume=charge, **selectors)
    result['registry_input'] = dict(bytes=size, sha256=hashlib.sha256(raw).hexdigest(),
                                    file_scan_work_units=scan_units,
                                    verification=VERIFICATION)
    result['summary']['nodes'] = used
    return result
