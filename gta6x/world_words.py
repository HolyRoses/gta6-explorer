"""Opt-in raw primitive bits, full key slots and verified name preimages.

No raw primitive tag or key namespace is given a semantic type. Declarations
and links must be fresh same-source reader output; persisted JSON is not an
authenticated source. The default storage readers do not call this inspector.
"""
from __future__ import annotations

import struct

from . import names, world_values

PROFILE = 'world_0drp_raw_value_words_and_opaque_keys_v1'


def verified_preimages(dictionary, word, *, consume):
    """Mathematical preimages only; retain every spelling/family/source."""
    if type(word) is not int or not 0 <= word <= 0xffffffff:
        raise ValueError('name preimage word must be an unsigned32bit pattern')
    if dictionary is None or not word:
        return []
    if not isinstance(dictionary, dict):
        raise ValueError('word names require a dictionary object')
    result = []
    for family, algorithm in (('hashes', names.joaat), ('exact', names.joaat_exact)):
        table = dictionary.get(family, {})
        if not isinstance(table, dict):raise ValueError('invalid name dictionary family')
        bucket = table.get(f'{word:08x}', [])
        if not isinstance(bucket, list):raise ValueError('invalid name preimage bucket')
        for entry in bucket:
            consume(1)
            if (not isinstance(entry, (list, tuple)) or len(entry) != 2
                    or any(not isinstance(v, str) or '\0' in v or len(v) > 4096 for v in entry)):
                raise ValueError('invalid name preimage candidate')
            text, source = entry
            if text and text.isascii() and algorithm(text) == word:
                result.append(dict(name=text, source=source, hash_family=family,
                    status='verified_hash_preimage; native name/type/namespace unconfirmed'))
    return result


def inspect(data, structures, blocks, *, links, consume, dictionary=None):
    """Read only qualified raw storage; never infer a primitive or asset type."""
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n);used += n
    charge()
    values = world_values.inspect(data, structures, blocks, links=links, consume=charge)
    preimages, cache, words, keys, skipped = [], {}, [], [], []
    counts = dict(primitive_words=0, key_slots=0, words_with_preimages=0,
                  keys_with_preimages=0, nonzero_key_high_words=0)

    def candidates(word):
        if dictionary is None or not word:return None
        if word not in cache:
            found = verified_preimages(dictionary, word, consume=charge)
            cache[word] = len(preimages) if found else None
            if found:
                charge(1 + len(found))
                preimages.append(dict(word_bits=f'0x{word:08x}', candidates=found))
        return cache[word]

    for pool in values['pools']:
        charge()
        if pool['status'] != 'complete_disjoint' or pool['element_bytes'] != 4:
            skipped.append(dict(block_index=pool['block_index'], reason='primitive pool coverage or grouping unresolved'))
            continue
        for index in range(pool['group_count']):
            charge()
            at = pool['data_offset'] + index * 4;bits, = struct.unpack_from('<I', data, at)
            pi = candidates(bits)
            words.append(dict(block_index=pool['block_index'], group_index=index,
                data_offset=at, raw_type=pool['raw_type'], bits=f'0x{bits:08x}', preimage_index=pi))
            counts['primitive_words'] += 1;counts['words_with_preimages'] += pi is not None
    for row in values['sequences']:
        if row['source_kind'] != 'container_entry':continue
        charge()
        at = row['source_data_offset'] - 8;bits, = struct.unpack_from('<Q', data, at)
        high = bits >> 32;pi = candidates(bits & 0xffffffff) if high == 0 else None
        keys.append(dict(block_index=row['source_block_index'], record_index=row['source_record_index'],
            data_offset=at, byte_length=8, bits=f'0x{bits:016x}', low32_bits=f'0x{bits & 0xffffffff:08x}',
            high32_bits=f'0x{high:08x}', preimage_index=pi,
            container_incidence=row['incidences']))
        counts['key_slots'] += 1;counts['keys_with_preimages'] += pi is not None
        counts['nonzero_key_high_words'] += high != 0
    counts.update(nodes=used, preimage_words=len(preimages),
                  preimage_candidates=sum(len(r['candidates']) for r in preimages), skipped_pools=len(skipped))
    return dict(status='partial' if words or keys else 'unsupported', profile=PROFILE,
                summary=counts, primitive_words=words, key_slots=keys, preimages=preimages,
                skipped_pools=skipped, offset_space='decompressed same-source 0DRP bytes',
                interpretation='Raw bit patterns and mathematical name preimages only; primitive types, '
                               'signedness, padding, key namespaces, model IDs and semantic ownership remain unknown.')
