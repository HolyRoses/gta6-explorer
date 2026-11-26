"""Measured radio-target profiles and unresolved external-symbol groups.

Raw kind words, flags, opaque fields and byte payloads retain their bits.
These profiles assign no enum, sound, bank, station or song meanings. Only the
already-validated relocation context supplies references and local bindings.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, deque
import struct

from . import audio_config


def _profile(directory, key, consume):
    record = directory.records[key]
    at, size = record['data_offset'], record['byte_length']
    if size < 4:raise ValueError('target indexed span cannot hold its full kind word')
    kind, = struct.unpack_from('<I', directory.data, at)
    if kind == 0x110:
        expected_size = 56; fields = [(8,1),(12,2),(20,4),(24,4)]
        opaque = [(4,4),(16,4),(28,28)]
    elif kind == 0x1a:
        expected_size = 28; fields = [(8,1),(16,4),(24,4)]
        opaque = [(4,4),(12,4),(20,4)]
    elif kind == 0:
        expected_size = 20; fields = [(8,1),(12,1)]
        opaque = [(4,4),(16,4)]
    elif kind == 0xcc:
        expected_size = 5; fields = []; opaque = []
    else:
        raise ValueError('unsupported full target kind word')
    if size != expected_size:
        raise ValueError('target indexed span differs from measured profile')
    if kind in (0x110,0x1a):
        flags, = struct.unpack_from('<I',directory.data,at+4)
        if flags & 0xffffff00 != 0xaaaaaa00:
            raise ValueError('unsupported target opaque-header profile')
    elif kind == 0 and directory.data[at+4:at+8] != b'\0\1\1\1':
        raise ValueError('unsupported kind-zero opaque-header profile')
    consume(len(fields)+len(opaque))
    refs = []; listed = set()
    for offset, flag in fields:
        ref = directory.resolve_at(at+offset)
        if ref['status'] == 'listed_reference':
            if ref['raw_flags'] != flag:
                raise ValueError('target reference namespace differs from measured profile')
            listed.add(at+offset)
        elif kind != 0 or ref['raw_value_u32'] != 0xffffffff:
            raise ValueError('target field is not a listed reference')
        refs.append(dict(ref, relative_offset=offset))
    first = bisect_left(directory.locations,at); end = bisect_left(directory.locations,at+size)
    actual = directory.locations[first:end]
    if any(p+4 > at+size for p in actual) or set(actual) != listed:
        raise ValueError('unexpected relocation in target indexed span')
    result = dict(status='parsed', name_hash=record['name_hash'], data_offset=at,
        indexed_span_bytes=size, full_kind_word=f'0x{kind:08x}', references=refs,
        opaque_regions=[dict(relative_offset=o,byte_length=n,raw_hex=directory.data[at+o:at+o+n].hex()) for o,n in opaque],
        interpretation='measured index-span profile; field roles and complete runtime object semantics unconfirmed')
    if kind == 0xcc:
        result['byte_payload_u8'] = directory.data[at+4]
        result['byte_payload_interpretation'] = 'raw byte; not assigned boolean or enum semantics'
    return result


def enrich(directory, targets, consume):
    """Follow at most two local hops using one shared directory/output budget."""
    pending = deque(); seen = set(); nodes = []; edges = []; symbols = {}

    def queue(key, depth):
        if key in seen:return False
        consume(); seen.add(key); pending.append((key,depth)); return True

    for target in targets:queue(int(target['name_hash'],16),0)
    while pending:
        key, depth = pending.popleft()
        try:
            node = _profile(directory,key,consume)
        except audio_config.ConfigLimitError:
            raise
        except ValueError as exc:
            nodes.append(dict(status='refused',name_hash=f'0x{key:08x}',depth=depth,reason=str(exc)))
            continue
        node['depth'] = depth; nodes.append(node)
        for ref in node['references']:
            if ref['status'] != 'listed_reference':continue
            consume()
            edge = dict(source_hash=node['name_hash'], source_offset=node['data_offset'], **ref)
            target = ref.get('local_target')
            if target:
                if depth >= 2:edge['follow_status'] = 'depth_limit'
                else:edge['follow_status'] = 'queued' if queue(int(target['name_hash'],16),depth+1) else 'already_seen'
            elif ref['raw_flags'] in (2,4):
                identity = ref['raw_flags'],ref['reference_hash']
                if identity not in symbols:
                    consume()
                    symbols[identity] = dict(raw_flags=identity[0],reference_hash=identity[1],
                        status='unresolved_namespace',occurrences=[])
                consume()
                symbols[identity]['occurrences'].append(dict(source_hash=node['name_hash'],
                    word_offset=ref['word_offset'],relative_offset=ref['relative_offset'],reference_index=ref['reference_index']))
            edges.append(edge)
    kinds = Counter(n['full_kind_word'] for n in nodes if n['status']=='parsed')
    return dict(status='partial' if any(n['status']!='parsed' for n in nodes) else 'parsed',
        source_sha256=directory.summary['source_sha256'],max_follow_depth=2,
        records=nodes,edges=edges,provider_symbols=[symbols[k] for k in sorted(symbols)],
        summary=dict(profiled_records=sum(n['status']=='parsed' for n in nodes),
            refused_records=sum(n['status']!='parsed' for n in nodes),
            full_kind_counts=dict(sorted(kinds.items())),reference_occurrences=len(edges),
            unresolved_provider_symbols=len(symbols),
            unresolved_provider_occurrences=sum(len(s['occurrences']) for s in symbols.values())),
        interpretation='bounded local profiles and namespace-separated symbol occurrences only; no provider, recording or station roles assigned')
