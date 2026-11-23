"""Candidate four-byte storage spans for source-checked type5c descriptors.

The existing hash32 contexts supply a four-byte inspection unit. This separate
exploratory profile does not establish type5c element/count/empty semantics,
change legacy refusals, bind asset names or emit record/graph associations.
"""
from __future__ import annotations

from copy import deepcopy

from . import psin_schema, psin_type5c_headers

PROFILE = 'local_type5c_candidate_hash32_storage_spans_v1'
MAX_WORDS = 4096


def inspect(data, schema, instances, *, consume, max_depth=16):
    """Frame only complete candidate pools; zero headers remain unresolved.

    All evidence is regenerated from the source. A complete bounded local owner
    inventory, an exact local descriptor, matching untyped pool and whole-pool
    distinct-span coverage are mandatory. Raw four-byte words are observations,
    never typed elements or application values. Limits return no report prefix.
    """
    used = 0
    def charge(amount=1):
        nonlocal used
        consume(amount)
        used += amount
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('type5c scalar candidates require a local native schema')
    charge(1 + len(schema.structures) + sum(len(owner.fields) for owner in schema.structures))
    # Callbacks may mutate caller-owned objects. Every schema fact below comes
    # from this charged private snapshot, rechecked by the header reader.
    schema = deepcopy(schema)
    inventory = psin_type5c_headers.inspect(data, schema, instances,
        consume=charge, max_depth=max_depth)
    charge(2 + len(inventory['fields']) + len(inventory['source_blocks']) + len(schema.structures))
    blocks = inventory['source_blocks']
    definitions = psin_schema._index(schema.structures)
    complete = inventory['scan_complete'] and all(
        f['status'] == 'bounded_observation' and f['descriptor'] is not None
        for f in inventory['fields'])
    scan_reasons = list(inventory['scan_reasons'])
    if not complete and not scan_reasons:
        scan_reasons.append('one or more type5c header/descriptor observations are unavailable')
    fields, groups = [], {}
    def exact_descriptor(field):
        d = field.get('descriptor')
        return (isinstance(d, dict) and d['hash'] == '0x00000100'
            and d['data_offset'] == 0 and d['type_word'] == '0x0000004a'
            and d['auxiliary'] == '0x00000000' and field['field_auxiliary'] == '0x00000000')
    for source in inventory['fields']:
        descriptor = source.get('descriptor')
        if not isinstance(descriptor, dict) or descriptor['type_word'] != '0x0000004a':
            continue
        charge()
        item = dict(index=len(fields), source_header_index=source['index'], status='unresolved',
            block_index=source['block_index'], record_index=source['record_index'],
            field_path=list(source['field_path']), owner_hash=source['owner_hash'],
            field_hash=source['field_hash'], descriptor=dict(descriptor),
            declaration_section_offset=source['declaration_section_offset'],
            header_data_offset=source.get('header_data_offset'),
            parent_type_meaning='unknown', logical_element_meaning='unknown',
            count_capacity_meaning='unknown', empty_state_meaning='unknown', semantic_owner='unknown')
        fields.append(item)
        if source['status'] != 'bounded_observation':
            item['reason'] = 'no complete source-checked sixteen-byte observation'; continue
        a, b, bits = source['first_word'], source['second_word'], source['third_word_bits']
        item.update(first_word=a, second_word=b, third_word_bits=bits, header_bits=source['header_bits'])
        if int(source['header_bits'], 16) == 0:
            item['reason'] = 'raw zero header; empty-state grammar remains unconfirmed'
            item['raw_zero_header'] = True
            if not exact_descriptor(source):
                complete = False
                reason = 'raw zero header has unsupported local descriptor attributes'
                item['reason'] = reason
                if reason not in scan_reasons:
                    charge(); scan_reasons.append(reason)
            continue
        location = source['packed_location_hypothesis']
        if not exact_descriptor(source):
            reason = 'candidate requires an exact local synthetic hash32-context descriptor'
        elif a <= 0 or a != b or bits == '0x0000000000000000':
            reason = 'candidate requires equal positive raw words and a nonzero location word'
        elif location['status'] != 'bounded_byte_location' or location['type_hash'] != '0x0000004a':
            reason = 'candidate location does not select bytes of a raw hash32-context pool'
        else:
            bi, offset = location['block_index'], location['byte_offset']
            block = blocks[bi]
            if definitions.get(0x4a):
                reason = 'a local structure definition collides with the raw pool type'
            elif (block['byte_length'] % 4 or offset % 4
                    or a > (block['byte_length'] - offset) // 4):
                reason = 'candidate four-byte span is unaligned or outside the complete pool'
            else:
                item['candidate_span'] = dict(block_index=bi, byte_offset=offset,
                    data_offset=block['data_offset']+offset, byte_length=a*4,
                    inspection_unit_bytes=4, inspection_word_count=a)
                groups.setdefault(bi, []).append(item)
                continue
        item['reason'] = reason
        complete = False
        if reason not in scan_reasons:
            charge(); scan_reasons.append(reason)
    targets, words_total = [], 0
    for bi, members in sorted(groups.items()):
        charge(1 + len(members) + len(inventory['fields']))
        block = blocks[bi]
        spans = sorted({(m['candidate_span']['byte_offset'], m['candidate_span']['byte_length']) for m in members})
        other = [f['index'] for f in inventory['fields']
            if f.get('packed_location_hypothesis', {}).get('block_index') == bi and not exact_descriptor(f)]
        target = dict(block_index=bi, raw_type_hash=block['type_hash'], data_offset=block['data_offset'],
            byte_length=block['byte_length'], inspection_unit_bytes=4, status='unresolved',
            header_count=len(members), distinct_spans=len(spans), exact_alias_headers=len(members)-len(spans),
            candidate_spans=[dict(byte_offset=o, byte_length=n) for o, n in spans],
            competing_header_indices=other, storage_words=[], application_meaning='unknown',
            record_links=[], associations_admitted=0)
        targets.append(target)
        reason = None
        if not complete:
            reason = 'eligible source header inventory is incomplete or contains malformed candidates'
        elif other:
            reason = 'a differently described header also addresses this raw pool'
        else:
            cursor = 0
            for offset, length in spans:
                charge()
                if offset != cursor:
                    reason = 'distinct candidate spans have a gap or partial overlap'; break
                cursor = offset + length
            if reason is None and cursor != block['byte_length']:
                reason = 'distinct candidate spans do not cover the complete raw pool'
        if reason is not None:
            target['reason'] = reason
            for item in members:
                item['reason'] = reason
            continue
        count = block['byte_length'] // 4
        if count > MAX_WORDS - words_total:
            raise ValueError('type5c scalar candidates exceed the 4096-word observation limit')
        charge(count)
        for index in range(count):
            start = block['data_offset'] + index*4
            target['storage_words'].append(dict(index=index, data_offset=start, byte_length=4,
                bits='0x'+data[start:start+4][::-1].hex(), logical_element_meaning='unknown'))
        words_total += count
        target.update(status='candidate_framed', inspection_word_count=count,
            evidence='independent four-byte other-context storage and exact distinct whole-pool coverage')
        for item in members:
            item['status'] = 'candidate_framed'
    return dict(format='gta6x-psin-type5c-scalar-candidates-v1', profile=PROFILE,
        profile_status='exploratory_candidate_only', source_sha256=inventory['source_sha256'],
        schema_id=inventory['schema_id'], max_depth=max_depth,
        status='partial' if fields or not complete else 'complete',
        scan_complete=complete, scan_reasons=scan_reasons, fields=fields, targets=targets,
        summary=dict(nodes=used, headers=len(fields),
            candidate_framed=sum(f['status']=='candidate_framed' for f in fields),
            unresolved=sum(f['status']=='unresolved' for f in fields),
            raw_zero_headers=sum(f.get('raw_zero_header', False) for f in fields),
            targets=len(targets), targets_candidate_framed=sum(t['status']=='candidate_framed' for t in targets),
            storage_words=words_total, record_links=0, associations_admitted=0, semantic_types_promoted=0),
        interpretation='Exploratory four-byte storage observations only, using existing hash32-context width. Type5c elements, raw word/count/capacity/empty semantics and ownership remain unknown. No legacy profile, refusal or record association changes.')
