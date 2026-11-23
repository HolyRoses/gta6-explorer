"""Source-checked users of intrinsic PSIN hash32 pool storage.

Already supported ordinary hash32-array storage is distinguished from
explicitly hypothetical type5c word groupings. Neither creates a new record link.
"""
from __future__ import annotations

from copy import deepcopy

from . import psin_arrays, psin_field_context, psin_references, psin_schema, psin_type5c_headers
from .psin_blocks import parse_blocks

PROFILE = 'local_hash32_pool_user_context_v1'
MAX_FIELDS = 4096
MAX_OWNERS = 65536
MAX_WORDS = 4096
MAX_MEMBERSHIPS = 65536


def inspect(data, schema, instances, *, consume, max_depth=16):
    """Explain storage coverage without interpreting uncovered bytes as values.

    Live source/schema/instance identities are checked. Ordinary array extents
    are recomputed using the existing hash32-array resolver, never imported
    from saved instance JSON. Type5c count-times-four remains a hypothesis;
    complete geometric coverage grants no new field or element interpretation.
    """
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    if not isinstance(schema, psin_schema.Schema):
        raise ValueError('hash pool users require a local native schema')
    charge(1+len(schema.structures)+sum(len(s.fields) for s in schema.structures))
    local = deepcopy(schema)
    observed = psin_type5c_headers.inspect(data, local, instances, consume=charge, max_depth=max_depth)
    execute = psin_field_context._prepare(data, local, instances, consume=charge,
        max_depth=min(64, max_depth+1), max_sample_bytes=0)
    blocks = parse_blocks(data[:int.from_bytes(data[4:8], 'big')])
    structures = psin_schema._index(local.structures)
    charge(len(blocks))
    pools = {b.index: b for b in blocks if b.type_hash == 0x4a and not structures.get(0x4a)}
    reasons = list(observed['scan_reasons'])
    pending, excluded_descriptors, visited = [], [], set()
    def refuse(reason):
        if reason not in reasons:
            charge(); reasons.append(reason)
    def walk(owner, at, root, path, depth, active):
        charge(); identity = owner.name_hash, at
        if identity in active:
            refuse('embedded cycle prevents complete ordinary-array inventory'); return
        if identity in visited:
            return
        if len(visited) >= MAX_OWNERS:
            raise ValueError('hash pool users exceed owner limit')
        visited.add(identity)
        if depth > max_depth:
            refuse('embedded depth prevents complete ordinary-array inventory'); return
        for fi, field in enumerate(owner.fields):
            charge()
            if field.name_hash == 0x100:
                continue
            if field.type_word & 0xffff == 0x52:
                di = field.type_word >> 16
                descriptor = owner.fields[di] if di < len(owner.fields) else None
                invalid = ('descriptor index is unavailable or selects its own field' if descriptor is None or di == fi else
                    'descriptor is not an exact local synthetic declaration' if descriptor.name_hash != 0x100 or descriptor.data_offset != 0 else
                    'hash32 descriptor has unsupported auxiliary attributes' if descriptor.type_word == 0x4a and (descriptor.auxiliary or field.auxiliary) else None)
                if invalid or descriptor.type_word == 0x4a:
                    if len(pending)+len(excluded_descriptors) >= MAX_FIELDS:
                        raise ValueError('hash pool users exceed array-field limit')
                    charge(1+len(path))
                    if invalid:
                        refuse('ordinary-array '+invalid)
                        excluded_descriptors.append(dict(block_index=root[0], record_index=root[1],
                            field_path=path+[fi], field_hash=f'0x{field.name_hash:08x}',
                            field_type_word=f'0x{field.type_word:08x}', descriptor_index=di, reason=invalid))
                    else:
                        pending.append((owner, field, fi, at, root, path+[fi]))
            elif field.type_word == 5:
                defs = structures.get(field.auxiliary, [])
                if (len(defs) != 1 or defs[0].byte_size <= 0 or field.data_offset < 0
                        or field.data_offset+defs[0].byte_size > owner.byte_size
                        or not psin_references.field_slot_clear(owner, field, defs[0].byte_size)):
                    refuse('ordinary-array embedded owner is missing, ambiguous or unbounded'); continue
                walk(defs[0], at+field.data_offset, root, path+[fi], depth+1, active | {identity})
            elif field.type_word == 0x75:
                refuse('inline bucket ordinary-array users are outside this instance-path inventory')
    for block in blocks:
        charge(); defs = structures.get(block.type_hash, [])
        if not defs:
            continue
        if len(defs) != 1 or defs[0].byte_size <= 0 or block.byte_length % defs[0].byte_size:
            refuse('ordinary-array root is ambiguous or does not tile its block'); continue
        for ri in range(block.byte_length//defs[0].byte_size):
            walk(defs[0], block.data_offset+ri*defs[0].byte_size, (block.index, ri), [], 0, frozenset())
    users = []
    for begin in range(0, len(pending), 32):
        batch = pending[begin:begin+32]
        proofs = iter(execute([(r[0], r[1], p) for _, _, _, _, r, p in batch if len(p) <= 64])['queries'])
        for owner, field, fi, at, root, path in batch:
            charge()
            item = dict(index=len(users), status='unresolved', block_index=root[0], record_index=root[1],
                field_path=path, owner_hash=f'0x{owner.name_hash:08x}', field_hash=f'0x{field.name_hash:08x}',
                field_type_word=f'0x{field.type_word:08x}', header_data_offset=at+field.data_offset,
                declaration_section_offset=field.section_offset, storage_span=None)
            users.append(item)
            if len(path) > 64:
                item['reason'] = 'ordinary-array field path exceeds instance limit'; continue
            proof = next(proofs)
            if proof['status'] != 'resolved':
                item['reason'] = proof['reason']; continue
            item['source_field'] = proof['field']
            if (field.auxiliary or field.data_offset < 0 or field.data_offset+16 > owner.byte_size
                    or not psin_references.field_slot_clear(owner, field, 16)):
                item['reason'] = 'ordinary hash32-array header is not a clear complete local slot'; continue
            array = psin_arrays.resolve_hash32(data, at+field.data_offset, owner,
                field.type_word >> 16, blocks, local_owner=True, local_structures=structures, consume=charge)
            item['array_profile_status'] = array['status']
            item['header_bits'] = array['header_bits']
            if array['status'] != 'complete':
                item['reason'] = array['reason']; continue
            item.update(status='supported_storage', profile=array['profile'], count=array['count'],
                storage_span=deepcopy(array['target']), existing_decoded_value_count=len(array['elements']),
                associations_admitted=0,
                interpretation='existing ordinary hash32-array storage only; no new association')
    hypotheses = []
    for field in observed['fields']:
        charge(); descriptor = field.get('descriptor')
        if not isinstance(descriptor, dict) or descriptor.get('type_word') != '0x0000004a':
            continue
        item = dict(index=len(hypotheses), status='unresolved', block_index=field['block_index'],
            record_index=field['record_index'], field_path=field['field_path'],
            owner_hash=field['owner_hash'], field_hash=field['field_hash'],
            header_data_offset=field.get('header_data_offset'), storage_span=None,
            interpretation='type5c equal-word-times-four storage hypothesis only; element/count/ownership meaning unknown')
        hypotheses.append(item)
        if (field['status'] != 'bounded_observation' or field['field_auxiliary'] != '0x00000000'
                or descriptor['hash'] != '0x00000100' or descriptor['data_offset'] != 0
                or descriptor['auxiliary'] != '0x00000000'):
            item['reason'] = 'no clear exact local hash32-descriptor observation'; continue
        item.update(first_word=field['first_word'], second_word=field['second_word'], third_word_bits=field['third_word_bits'])
        location = field['packed_location_hypothesis']; count = field['first_word']
        if (not count or count != field['second_word'] or location['status'] != 'bounded_byte_location'):
            item['reason'] = 'hypothesis requires positive equal words and bounded nonzero packed location'; continue
        target = pools.get(location['block_index']); offset = location['byte_offset']
        if (target is None or target.byte_length % 4 or offset % 4
                or count > (target.byte_length-offset)//4):
            item['reason'] = 'hypothesis does not fit an unambiguous aligned intrinsic hash32-word pool'; continue
        item.update(status='candidate_storage', storage_span=dict(block_index=target.index,
            byte_offset=offset, data_offset=target.data_offset+offset, byte_length=count*4),
            hypothetical_word_count=count, candidate_word_bytes=4, associations_admitted=0)
    results, total_words, memberships = [], 0, 0
    for bi, block in sorted(pools.items()):
        charge()
        if block.byte_length % 4:
            results.append(dict(block_index=bi, status='unresolved', reason='intrinsic pool is not four-byte aligned')); continue
        count = block.byte_length//4
        if count > MAX_WORDS-total_words:
            raise ValueError('hash pool users exceed word report limit')
        total_words += count
        supported = [u for u in users if u['status'] == 'supported_storage' and u['storage_span'] is not None
                     and u['storage_span']['block_index'] == bi]
        candidate = [h for h in hypotheses if h['status'] == 'candidate_storage' and h['storage_span']['block_index'] == bi]
        charge(len(users)+len(hypotheses)+count)
        words = [dict(word_index=i, data_offset=block.data_offset+i*4, byte_length=4,
            supported_user_indices=[], candidate_header_indices=[], content_interpretation='unknown') for i in range(count)]
        for collection, key in ((supported, 'supported_user_indices'), (candidate, 'candidate_header_indices')):
            for item in collection:
                span = item['storage_span']; start = span['byte_offset']//4
                entries = span['byte_length']//4
                if entries > MAX_MEMBERSHIPS-memberships:
                    raise ValueError('hash pool users exceed word-membership report limit')
                memberships += entries
                charge(1+entries)
                for i in range(start, start+span['byte_length']//4):
                    words[i][key].append(item['index'])
        gaps = []
        for word in words:
            charge()
            if word['supported_user_indices'] or word['candidate_header_indices']:
                continue
            if gaps and gaps[-1]['first_word_index']+gaps[-1]['word_count'] == word['word_index']:
                gaps[-1]['word_count'] += 1; gaps[-1]['byte_length'] += 4
            else:
                charge(); gaps.append(dict(first_word_index=word['word_index'], word_count=1,
                    byte_offset=word['word_index']*4, data_offset=word['data_offset'], byte_length=4))
        results.append(dict(block_index=bi, status='observed', type_hash='0x0000004a',
            data_offset=block.data_offset, byte_length=block.byte_length, word_bytes_basis='existing independently inferred hash32 pool storage',
            word_bytes=4, word_count=count, supported_array_indices=[u['index'] for u in supported],
            candidate_type5c_indices=[h['index'] for h in candidate], words=words, gaps=gaps,
            supported_words=sum(bool(w['supported_user_indices']) for w in words),
            candidate_words=sum(bool(w['candidate_header_indices']) for w in words),
            multiply_observed_words=sum(len(w['supported_user_indices'])+len(w['candidate_header_indices'])>1 for w in words),
            union_words=sum(bool(w['supported_user_indices'] or w['candidate_header_indices']) for w in words),
            unexplained_words=sum(g['word_count'] for g in gaps), semantic_owner='unknown', associations_admitted=0))
    unresolved = sum(u['status'] == 'unresolved' for u in users)+sum(h['status'] == 'unresolved' for h in hypotheses)
    return dict(format='gta6x-psin-hash-pool-users-v1', profile=PROFILE,
        source_sha256=observed['source_sha256'], schema_id=observed['schema_id'], max_depth=max_depth,
        status='partial' if reasons or unresolved or any(p.get('unexplained_words', 1) for p in results) else 'complete',
        scan_scope='local tiled roots and bounded embedded paths; exact descriptor4a ordinary arrays and type5c observations only',
        scan_complete=not reasons, scan_reasons=reasons, excluded_array_descriptors=excluded_descriptors, ordinary_arrays=users,
        type5c_hypotheses=hypotheses, pools=results,
        summary=dict(nodes=used, pools=len(results), ordinary_arrays=len(users),
            ordinary_arrays_supported=sum(u['status'] == 'supported_storage' for u in users),
            excluded_array_descriptors=len(excluded_descriptors),
            type5c_hypotheses=len(hypotheses), hypotheses_bounded=sum(h['status'] == 'candidate_storage' for h in hypotheses),
            words=total_words, supported_words=sum(p.get('supported_words', 0) for p in results),
            candidate_words=sum(p.get('candidate_words', 0) for p in results),
            union_words=sum(p.get('union_words', 0) for p in results),
            unexplained_words=sum(p.get('unexplained_words', 0) for p in results),
            multiply_observed_words=sum(p.get('multiply_observed_words', 0) for p in results),
            associations_admitted=0, record_links=0, semantic_types_promoted=0),
        interpretation='Storage-user accounting only. Supported ordinary arrays and hypothetical type5c grouping stay distinct; union coverage never validates a type5c layout or interprets remaining bytes, values, ownership or graph associations.')
