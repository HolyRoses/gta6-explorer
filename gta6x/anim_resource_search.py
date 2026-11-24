"""Literal native declaration queries over freshly inspected 0DRP files.

Full-width words, duplicate declarations and source-local positions remain
separate. A match does not identify a provider, schema, bone or field meaning.
"""
from __future__ import annotations

from . import anim_resource_inputs as inputs


def validate_selectors(*, structure_hash=None, field_hash=None, type_word=None,
                       auxiliary=None, byte_size=None, enum_hash=None):
    """Check literal query syntax before any input path or payload is opened."""
    query = dict(structure_hash=structure_hash, field_hash=field_hash,
                 type_word=type_word, auxiliary=auxiliary,
                 byte_size=byte_size, enum_hash=enum_hash)
    for name, value in query.items():
        if value is not None and (type(value) is not int or not 0 <= value <= 0xffffffff):
            raise ValueError(f'invalid native declaration query {name}')
    if not any(value is not None for value in query.values()):
        raise ValueError('native declaration search requires at least one selector')
    if enum_hash is not None and any(value is not None for name, value in query.items()
                                     if name != 'enum_hash'):
        raise ValueError('enum hash cannot combine with structure or field selectors')
    return {name: value for name, value in query.items() if value is not None}


def inspect_files(paths, *, structure_hash=None, field_hash=None, type_word=None,
                  auxiliary=None, byte_size=None, enum_hash=None,
                  max_nodes=100000, max_input_bytes=inputs.DEFAULT_INPUT_BYTES,
                  expected_sha256=None, protected_outputs=(), with_key_holders=False):
    """Inspect every selected file, then query declarations under one budget.

    Owner filters are conjunctive. Field filters must all match the same field;
    selected owners with no such field are absent from matches. Enum selection
    is a separate mode. No match result clips source validation or selects among
    equal hashes. All source metadata remains available in the base file rows.
    Query exhaustion refuses the whole result, never returning a match prefix.
    """
    query = validate_selectors(structure_hash=structure_hash, field_hash=field_hash,
        type_word=type_word, auxiliary=auxiliary, byte_size=byte_size, enum_hash=enum_hash)
    report = inputs.inspect_files(paths, max_nodes=max_nodes,
        max_input_bytes=max_input_bytes, expected_sha256=expected_sha256,
        protected_outputs=protected_outputs, with_key_holders=with_key_holders)
    used = report['summary']['work_nodes']
    query_start = used

    def charge(amount=1):
        nonlocal used
        if amount > max_nodes - used:
            raise inputs.AnimationInputLimitError('native declaration search exceeds shared node limit')
        used += amount

    counts = dict(structures_scanned=0, fields_scanned=0, enums_scanned=0,
                  structure_matches=0, field_matches=0, enum_matches=0)
    structures, enums = [], []
    field_filters = any(value is not None for value in (field_hash, type_word, auxiliary))
    charge()
    for source_index, source in enumerate(report['files']):
        charge()
        metadata = source['metadata']
        if enum_hash is not None:
            for declaration in metadata['enums']:
                charge()
                counts['enums_scanned'] += 1
                if int(declaration['hash'], 16) != enum_hash:
                    continue
                charge()
                enums.append(dict(source_index=source_index, source_sha256=source['sha256'],
                    declaration_index=declaration['index'], data_offset=declaration['data_offset'],
                    hash=declaration['hash'], byte_length=24,
                    member_count=declaration['member_count'],
                    members_data_offset=declaration['members_data_offset'],
                    members_reference_bits=declaration['members_reference_bits']))
                counts['enum_matches'] += 1
            continue
        for declaration in metadata['structures']:
            charge()
            counts['structures_scanned'] += 1
            owner_matches = (structure_hash is None or int(declaration['hash'], 16) == structure_hash)
            owner_matches = owner_matches and (byte_size is None or declaration['byte_size'] == byte_size)
            fields = []
            # Visit every structure field even when an owner filter misses. This
            # keeps query-work accounting explicit for the complete field mode.
            if field_filters:
                for field_index, field in enumerate(declaration['fields']):
                    charge()
                    counts['fields_scanned'] += 1
                    words = (int(field['hash'], 16), field['field_offset'],
                             int(field['type_word'], 16), int(field['unknown_0c'], 16))
                    if (not owner_matches or field_hash is not None and words[0] != field_hash
                            or type_word is not None and words[2] != type_word
                            or auxiliary is not None and words[3] != auxiliary):
                        continue
                    charge()
                    fields.append(dict(field_index=field_index, data_offset=field['data_offset'],
                        byte_length=16, field_offset=field['field_offset'],
                        raw_words=[f'0x{word:08x}' for word in words]))
            if not owner_matches or field_filters and not fields:
                continue
            charge()
            structures.append(dict(source_index=source_index, source_sha256=source['sha256'],
                declaration_index=declaration['index'], data_offset=declaration['data_offset'],
                hash=declaration['hash'], byte_length=32, byte_size=declaration['byte_size'],
                field_count=declaration['field_count'],
                fields_data_offset=declaration['fields_data_offset'],
                fields_reference_bits=declaration['fields_reference_bits'], matched_fields=fields))
            counts['structure_matches'] += 1
            counts['field_matches'] += len(fields)
    counts['query_nodes'] = used - query_start
    report['summary']['work_nodes'] = used
    report['summary']['declaration_query_nodes'] = counts['query_nodes']
    report['declaration_search'] = dict(status='complete', query=query,
        structures=structures, enums=enums, summary=counts,
        validation_scope='all selected files and their complete bounded metadata',
        interpretation='Exact stored-word matches only; all duplicate and low-ID alternatives retained. '
        'No declaration identity, provider, namespace, field type or bone association inferred.')
    return report
