"""Bounded exact queries over native PSIN declarations, without instance binding.

Layout equality includes owner byte size and every ordered field descriptor,
including synthetic descriptors. It excludes owner name and unknown header
words, which remain visible through full-definition identities and raw metadata.
Inputs are native schema objects with caller-supplied provenance, not authenticated
serialized reports. Unknown types and application meanings remain unknown.
"""
from __future__ import annotations

import hashlib
import struct

from . import psin_registry, psin_schema

PROFILE = 'local_psin_exact_declaration_search_v1'
MAX_MATCHES = 4096
MAX_OUTPUT_FIELDS = 65536


def validate_query(*, structure_hash=None, field_hash=None, type_word=None,
                   auxiliary=None, byte_size=None, same_layout=None):
    selectors = dict(structure_hash=structure_hash, field_hash=field_hash,
                     type_word=type_word, auxiliary=auxiliary,
                     byte_size=byte_size, same_layout=same_layout)
    if all(value is None for value in selectors.values()):
        raise ValueError('PSIN schema search requires at least one exact selector')
    if any(value is not None and (type(value) is not int or not 0 <= value <= 0xffffffff)
           for value in selectors.values()):
        raise ValueError('PSIN schema search selectors must be unsigned 32-bit words')
    return selectors


def layout_id(definition):
    """Fingerprint exact physical declaration layout, not semantic equivalence."""
    if not isinstance(definition, psin_schema.SchemaStructure):
        raise ValueError('PSIN layout identity requires a native structure declaration')
    try:
        raw = struct.pack('<II', definition.byte_size, len(definition.fields))
        raw += b''.join(struct.pack('<4I', field.name_hash, field.data_offset,
                                   field.type_word, field.auxiliary)
                        for field in definition.fields)
    except (struct.error, OverflowError, TypeError) as exc:
        raise ValueError('invalid native PSIN layout declaration') from exc
    return hashlib.sha256(b'gta6x-psin-layout-v1\0'+raw).hexdigest()


def _digest(value, label):
    if (not isinstance(value, str) or len(value) != 64
            or any(c not in '0123456789abcdef' for c in value)):
        raise ValueError('invalid PSIN schema search '+label)
    return value


def inspect(schemas, sources, *, consume, structure_hash=None, field_hash=None,
            type_word=None, auxiliary=None, byte_size=None, same_layout=None):
    """Search exact local declarations; all supplied selectors are AND filters.

    Field selectors must match the same physical descriptor. ``same_layout``
    seeds every layout variant of the selected owner hash; conflicting seeds
    are never voted or discarded. Source parse refusals remain visible and make
    coverage incomplete. This does not prove source checksums when supplied a
    registry or establish instantiated records, pointers, assets or transforms.
    Format, work and output-limit failures return no result prefix.
    """
    selectors = validate_query(structure_hash=structure_hash, field_hash=field_hash,
        type_word=type_word, auxiliary=auxiliary, byte_size=byte_size, same_layout=same_layout)
    if not isinstance(schemas, dict) or not isinstance(sources, (list, tuple)):
        raise ValueError('PSIN schema search requires native schemas and source rows')
    used = 0
    def charge(count=1):
        nonlocal used
        consume(count)
        used += count
    charge(1 + len(schemas) + len(sources))
    source_rows = []; schema_sources = {ident: [] for ident in schemas}
    refused = 0
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('invalid PSIN schema search source row')
        file = source.get('file')
        offset = source.get('offset', 0)
        if (not isinstance(file, str) or not file or len(file) > 4096 or '\0' in file
                or type(offset) is not int or not 0 <= offset < 1 << 64):
            raise ValueError('invalid PSIN schema search source location')
        charge(1 + (len(file)+63)//64)
        row = dict(index=len(source_rows), file=file, offset=offset, status='unavailable')
        source_rows.append(row)
        if source.get('status') != 'ok':
            row['reason'] = 'native source schema is unavailable or refused'
            refused += 1
            continue
        ident = _digest(source.get('schema_id'), 'source schema identity')
        digest = _digest(source.get('sha256'), 'source digest')
        if ident not in schemas:
            raise ValueError('PSIN schema search source references an unavailable schema')
        row.update(status='available', schema_id=ident, sha256=digest)
        schema_sources[ident].append(row['index'])
    definitions = []
    variants = {}
    seed_rows = []
    seed_layouts = set()
    source_free = []
    for ident, schema in schemas.items():
        _digest(ident, 'schema identity')
        if not isinstance(schema, psin_schema.Schema) or schema.schema_id != ident:
            raise ValueError('PSIN schema search schema identity differs from its native object')
        if not schema_sources[ident]:
            charge()
            source_free.append(ident)
            continue
        charge(len(schema.structures))
        for index, owner in enumerate(schema.structures):
            charge(2 + len(owner.fields))
            layout = layout_id(owner)
            full = psin_registry.definition_id('structure', owner)
            row = (ident, index, owner, layout, full)
            definitions.append(row)
            variants.setdefault(owner.name_hash, set()).add(full)
            if owner.name_hash == same_layout:
                charge(1 + len(schema_sources[ident]))
                seed_layouts.add(layout)
                seed_rows.append(dict(schema_id=ident, structure_index=index,
                    structure_hash=f'0x{owner.name_hash:08x}', definition_id=full,
                    layout_id=layout, source_indices=list(schema_sources[ident])))
    matches = []; output_fields = 0
    field_filter = any(value is not None for value in (field_hash, type_word, auxiliary))
    for ident, index, owner, layout, full in definitions:
        charge()
        if structure_hash is not None and owner.name_hash != structure_hash:
            continue
        if byte_size is not None and owner.byte_size != byte_size:
            continue
        if same_layout is not None and layout not in seed_layouts:
            continue
        selected = []
        for fi, field in enumerate(owner.fields):
            charge()
            if (field_hash is None or field.name_hash == field_hash) and (
                    type_word is None or field.type_word == type_word) and (
                    auxiliary is None or field.auxiliary == auxiliary):
                selected.append(fi)
        if field_filter and not selected:
            continue
        if len(matches) >= MAX_MATCHES or len(owner.fields) > MAX_OUTPUT_FIELDS-output_fields:
            raise ValueError('PSIN schema search exceeds its bounded match/field output limit')
        charge(1 + len(owner.fields) + len(schema_sources[ident]))
        output_fields += len(owner.fields)
        # Exact words are sufficient for matching. No type or width guess is
        # needed, including for unknown codes and synthetic array descriptors.
        matches.append(dict(schema_id=ident, structure_index=index,
            structure_hash=f'0x{owner.name_hash:08x}',
            declaration_section_offset=owner.section_offset, byte_size=owner.byte_size,
            definition_id=full, layout_id=layout,
            definition_variants_in_scope=len(variants[owner.name_hash]),
            source_indices=list(schema_sources[ident]),
            unknown_header_words=dict(unknown_04=f'0x{owner.unknown_04:08x}',
                unknown_08=f'0x{owner.unknown_08:08x}', unknown_0c=f'0x{owner.unknown_0c:08x}',
                unknown_1c=owner.unknown_1c),
            matching_field_indices=selected if field_filter else [],
            fields=[dict(index=fi, hash=f'0x{field.name_hash:08x}',
                declaration_section_offset=field.section_offset,
                data_offset=field.data_offset, type_word=f'0x{field.type_word:08x}',
                auxiliary=f'0x{field.auxiliary:08x}', synthetic_descriptor=field.name_hash == 0x100)
                for fi, field in enumerate(owner.fields)],
            application_meaning='unknown', instantiated_records_not_established=True))
    complete = not refused and not source_free
    query = {key:(value if key == 'byte_size' else f'0x{value:08x}')
             for key,value in selectors.items() if value is not None}
    return dict(format='gta6x-psin-schema-search-v1', profile=PROFILE,
        status='complete' if complete else 'partial', query=query,
        coverage_complete=complete, sources=source_rows, matches=matches,
        seed_layouts=seed_rows, schemas_without_sources=source_free,
        summary=dict(nodes=used, sources=len(source_rows), sources_refused=refused,
            schemas=len(schemas), schemas_without_sources=len(source_free),
            structures_considered=len(definitions), matches=len(matches),
            output_fields=output_fields,
            seed_definitions=len(seed_rows), seed_layouts=len(seed_layouts),
            conflicting_owner_names=sum(len(v)>1 for v in variants.values()),
            matching_field_descriptors=sum(len(m['matching_field_indices']) for m in matches),
            instance_bindings=0),
        interpretation='Exact local declaration/layout matches only; unknown header words remain separate, metadata provenance does not authenticate source payloads, and no instance, asset or transform binding is established.')
