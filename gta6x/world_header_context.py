"""A source-corroborated header block selector, without root or boundary claims.

The observed header word is tested as a full-width one-based block ordinal.
No packed header offset encoding, allocation count, semantic owner or resource
endpoint is inferred. Only selected local declaration words are rechecked here;
this helper does not authenticate a whole resource or persisted reader JSON.
"""
from __future__ import annotations

import struct

from . import anim_resources

PROFILE = 'world_0drp_header_block_context_candidate_v1'


def inspect(data, structures, blocks, *, consume):
    """Corroborate a bounded header-selected context, or explain a mismatch.

    Structures/blocks must describe this same source. Only their hashes, sizes,
    table positions and block words are consumed. An investigation may supply
    those readable rows even when unrelated fields/payloads are absent, which
    does not grant full metadata acceptance. Profile mismatches remain local
    unresolved observations. Malformed supplied declarations raise ValueError;
    the enclosing caller's shared-budget exception propagates unchanged.
    """
    if (not isinstance(data, bytes) or not 80 <= len(data) <= anim_resources.MAX_RESOURCE
            or data[16:20] != b'0DRP' or struct.unpack_from('<I', data, 20)[0] != 122):
        raise ValueError('header context requires bounded version-122 0DRP bytes')
    if not isinstance(structures, list) or not isinstance(blocks, list):
        raise ValueError('header context requires same-source declaration lists')
    ns, _, nb = struct.unpack_from('<3H', data, 72)
    if (ns, nb) != (len(structures), len(blocks)):
        raise ValueError('header-context declaration counts differ from source')
    used = 0

    def charge(n=1):
        nonlocal used
        consume(n); used += n

    charge(1 + ns + nb)

    def table(word, count, stride):
        if not count:
            if word: raise ValueError('header-context empty table has a nonnull pointer')
            return None
        at = word - anim_resources.VIRTUAL_BASE
        if at < 80 or at > len(data) - count * stride:
            raise ValueError('header-context declaration table escapes source prefix')
        return at

    structure_at = table(struct.unpack_from('<Q', data, 40)[0], ns, 32)
    block_at = table(struct.unpack_from('<Q', data, 56)[0], nb, 16)
    types = {}
    for i, definition in enumerate(structures):
        if not isinstance(definition, dict):
            raise ValueError('invalid header-context structure declaration')
        name = struct.unpack_from('<I', data, structure_at + 32 * i)[0]
        size = struct.unpack_from('<I', data, structure_at + 32 * i + 24)[0]
        if (definition.get('hash'), definition.get('byte_size')) != (f'0x{name:08x}', size):
            raise ValueError('header-context structure hash/size differs from source')
        types.setdefault(definition['hash'], []).append((i, size))
    for i, block in enumerate(blocks):
        if not isinstance(block, dict):
            raise ValueError('invalid header-context block declaration')
        at = block_at + 16 * i
        name, length, pointer = struct.unpack_from('<IIQ', data, at)
        offset = None if not length and not pointer else pointer - anim_resources.VIRTUAL_BASE
        if (block.get('index'), block.get('type_hash'), block.get('byte_length'), block.get('data_offset')) != (
                i, f'0x{name:08x}', length, offset):
            raise ValueError('header-context block words differ from source')
        if type(block.get('index')) is not int:
            raise ValueError('invalid header-context block index')
        if not length:
            if pointer: raise ValueError('header-context empty block has a nonnull pointer')
        elif offset < 80 or offset > anim_resources.MAX_RESOURCE - length:
            raise ValueError('header-context block declaration exceeds supported extent')

    word = struct.unpack_from('<Q', data, 32)[0]
    base = dict(profile=PROFILE, header_data_offset=32, reference_bits=f'0x{word:016x}',
        encoding_hypothesis='full-width one-based local block ordinal only; packed offsets unconfirmed',
        target=None, semantic_role='unknown', resource_endpoint=None, resource_joins_enabled=False,
        offset_space='decompressed same-source 0DRP prefix bytes',
        source_validation='selected structure hash/size and block-table words only; not full metadata or resource authentication')

    def unresolved(reason):
        return dict(base, status='unresolved', reason=reason, nodes=used)

    if not 1 <= word <= nb:
        return unresolved('header word does not select a full-width one-based local block ordinal')
    selected = blocks[word - 1]
    matching = types.get(selected['type_hash'], [])
    if len(matching) != 1 or matching[0][1] != 16 or selected['byte_length'] != 16:
        return unresolved('selected block is not one uniquely declared sixteen-byte record')
    start = selected['data_offset']
    if start is None or start > len(data) - 16:
        return unresolved('selected context record is absent from the bounded prefix')
    # This independent source context is not an allocation or continuation map.
    header08 = struct.unpack_from('<Q', data, 8)[0]
    prefix = header08 - anim_resources.VIRTUAL_BASE
    if block_at is None or prefix != block_at + 16 * nb or not 80 <= prefix <= len(data) - 16:
        return unresolved('header08 does not select the readable block-table end')
    charge()
    zero, count_like = struct.unpack_from('<QQ', data, prefix)
    if zero or count_like not in (1, 2):
        return unresolved('unobserved zero-prefix/count-like context shape')
    stop = prefix + 16 + 8 * count_like
    if stop > len(data):
        return unresolved('count-like zero slots escape the bounded prefix')
    charge(count_like)
    if any(memoryview(data)[prefix + 16:stop]):
        return unresolved('count-like context slots are nonzero')
    if start != stop:
        return unresolved('selected block does not immediately follow the independently bounded zero slots')
    aliases = 0
    for block in blocks:
        charge()
        at, length = block['data_offset'], block['byte_length']
        if at is not None and length and at < start + 16 and start < at + length:
            aliases += 1
    if aliases != 1:
        return unresolved('selected context source span overlaps another declared block')
    charge(2)
    target = dict(block_index=word - 1, record_index=0, type_hash=selected['type_hash'],
        structure_index=matching[0][0], data_offset=start, byte_length=16)
    return dict(base, status='candidate', target=target, nodes=used,
        corroboration=dict(header08_reference_bits=f'0x{header08:016x}', prefix_data_offset=prefix,
            count_like_value=count_like, zero_slot_bytes=count_like * 8,
            selected_block_follows_zero_slots=True, unique_declared_source_span=True),
        interpretation='Observed header-selected local context candidate; no semantic root, owner, allocation or resource-boundary authority.')
