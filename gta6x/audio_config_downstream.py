"""Downstream config reference profiles and unresolved symbol consumers.

Full kind words, source-key echoes, count closure and listed reference locations
are checked. Raw tags and numeric regions retain bits without audio meanings.
"""
from __future__ import annotations

import struct

from . import audio_config, audio_config_kind27, audio_config_symbols


def profile(directory, record, consume):
    data = directory.data
    start, size = record['data_offset'], record['byte_length']
    if size < 4:
        raise ValueError('downstream kind word escapes index span')
    kind, = struct.unpack_from('<I', data, start)
    count = None
    if kind == 0x121:
        if size != 164 or data[start+4:start+8] != b'\x55\xaa\xaa\xaa':
            raise ValueError('unsupported kind121 header or exact extent')
        if struct.unpack_from('<I', data, start+8)[0] != int(record['name_hash'], 16):
            raise ValueError('kind121 stored key echo differs from primary index key')
        expected = {12: 2, 28: 2}
        optional = {20: 32}
    elif kind == 0x2c:
        if size < 200 or struct.unpack_from('<I', data, start+4)[0] not in (0x40102450, 0x40102460):
            raise ValueError('unsupported kind2C header or prefix extent')
        count = data[start+193]
        if size != 200+8*count:
            raise ValueError('kind2C counted tail does not exhaust index span')
        expected = {44: 3}
        expected.update((196+8*i, 1) for i in range(count))
        optional = {128: 4, 136: 2, 156: 1}
    else:
        raise ValueError('unsupported downstream full kind word')
    references = audio_config_kind27._references(directory, record, consume)
    actual = {ref['relative_offset']: ref for ref in references}
    unlisted = []
    for offset, flags in optional.items():
        if offset in actual:
            expected[offset] = flags
        elif struct.unpack_from('<I', data, start+offset)[0] == 0xffffffff:
            consume()
            unlisted.append(dict(relative_offset=offset, raw_value_bits='0xffffffff'))
        else:
            raise ValueError('unlisted downstream optional field differs from measured raw bits')
    if set(actual) != set(expected) or any(actual[o]['raw_flags'] != flags for o, flags in expected.items()):
        raise ValueError('downstream reference positions or exact flags differ from measured profile')
    # Preserve every byte outside the full kind and reference words. This also
    # retains raw tag words, count-word neighbours and trailing opaque bits.
    opaque = []
    cursor = 4
    for offset in sorted(actual):
        if offset > cursor:
            consume()
            opaque.append(dict(relative_offset=cursor, raw_hex=data[start+cursor:start+offset].hex()))
        cursor = offset+4
    if cursor < size:
        consume()
        opaque.append(dict(relative_offset=cursor, raw_hex=data[start+cursor:start+size].hex()))
    result = dict(status='parsed', name_hash=record['name_hash'], data_offset=start,
        indexed_span_bytes=size, full_kind_word=f'0x{kind:08x}', references=references,
        unlisted_fields=unlisted, opaque_regions=opaque,
        interpretation='measured storage/reference profile; tags, numeric fields and symbol meanings unconfirmed')
    if count is not None:
        consume(count)
        result.update(tail_count_u8=count, tail_count_offset=193,
            tail_reference_offsets=[196+8*i for i in range(count)])
    else:
        result['stored_key_echo'] = record['name_hash']
    return result


def enrich(graph, contexts, resources, consume):
    profiles, queries = [], {}
    selected = {}
    for node in graph['records']:
        if node['family'] == 581 and node['raw_kind_u8'] in (0x21, 0x2c):
            identity = node['source_sha256'], node['source_offset'], node['name_hash']
            selected[identity] = node
    for identity, node in selected.items():
        consume()
        directory = contexts.get(node['source_sha256'])
        try:
            if directory is None:
                raise ValueError('no validated directory for downstream record')
            record = directory.records[int(node['name_hash'], 16)]
            result = profile(directory, record, consume)
        except audio_config.ConfigLimitError:
            raise
        except ValueError as exc:
            profiles.append(dict(status='refused', name_hash=node['name_hash'],
                source_sha256=node['source_sha256'], source_offset=node['source_offset'], reason=str(exc)))
            continue
        result.update(source_sha256=node['source_sha256'], source_offset=node['source_offset'])
        profiles.append(result)
        for ref in result['references']:
            if ref['raw_flags'] not in (2, 3, 4):
                continue
            key = ref['raw_flags'], ref['reference_hash']
            if key not in queries:
                consume()
                queries[key] = dict(raw_flags=key[0], reference_hash=key[1], seed_occurrences=[])
            consume()
            queries[key]['seed_occurrences'].append(dict(source_sha256=node['source_sha256'],
                source_offset=node['source_offset'], source_hash=node['name_hash'], **ref))
    uses = []
    for sha, source_offset in sorted({(node['source_sha256'], node['source_offset']) for node in selected.values()}):
        if sha in contexts:
            consume()
            result = audio_config_symbols._uses(contexts[sha], list(queries.values()), consume)
            result['source_offset'] = source_offset
            uses.append(result)
    # Full-key coincidences are observable, but no provider namespace is known
    # for these flags. Never convert one into a resolved candidate/graph edge.
    lookup = {}
    for flag, key in queries:
        lookup.setdefault(key, []).append(flag)
    coincidences = []
    for resource in resources:
        for record in resource['records']:
            for flag in lookup.get(record['name_hash'], []):
                consume()
                coincidences.append(dict(reference_hash=record['name_hash'], raw_flags=flag,
                    family=resource['raw_family'], source_sha256=resource['sha256'],
                    source_offset=resource['source']['offset'], data_offset=record['data_offset'],
                    indexed_span_bytes=record['byte_length'], status='hash_coincidence_namespace_unconfirmed'))
    return dict(status='partial' if any(p['status'] == 'refused' for p in profiles) else 'parsed',
        profiles=profiles, symbols=[queries[key] for key in sorted(queries)],
        same_resource_uses=uses, indexed_hash_coincidences=coincidences,
        summary=dict(profiled_records=sum(p['status'] == 'parsed' for p in profiles),
            refused_records=sum(p['status'] == 'refused' for p in profiles),
            seed_reference_words=sum(len(q['seed_occurrences']) for q in queries.values()),
            distinct_symbols=len(queries), listed_symbol_uses=sum(u['summary']['listed_reference_words'] for u in uses),
            source_index_spans=sum(u['summary']['source_index_spans'] for u in uses),
            indexed_hash_coincidences=len(coincidences)),
        interpretation='profiled reference slots and exact flag/hash consumers only; no provider definitions, recording identities or station membership established')


def inspect_file(path, **kwargs):
    return audio_config_kind27.inspect_file(path, _graph_hook=enrich, **kwargs)
