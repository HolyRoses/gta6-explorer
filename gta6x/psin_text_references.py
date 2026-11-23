"""Bounded contextual links to already decoded local PSIN ASCII pool entries.

These measured named-field profiles do not give global LSCH type meanings.
Targets remain existing pool elements; no text value or pointer graph is copied.
"""
from __future__ import annotations

import struct

from .psin_references import field_slot_clear


WORD_PROFILE = 'local_ascii_pool_word_v1'
HEADER_PROFILE = 'local_ascii_pool_header24_v1'


def resolve_field(data, start, field, owner, block_end, blocks, *, local_owner,
                  local_structures, pool_for_block, slot_cache=None, entry_cache=None):
    """Select an exact existing entry after local owner/header/pool validation.

    ``pool_for_block`` supplies the instance reader's budgeted pool view. It
    must suppress any block with an authoritative schema; the returned view is
    also reused in the block output, rather than decoding scalar values twice.
    """
    width = 8 if field.type_word == 0x42 else 24
    profile = WORD_PROFILE if field.type_word == 0x42 else HEADER_PROFILE
    result = dict(status='unresolved', interpretation='candidate', candidate_profile=profile,
                  reference_data_offset=start, reference_byte_length=8, field_byte_length=width)
    if not local_owner:
        return dict(result, reason='text reference requires a local owning schema')
    if field.name_hash == 0x100 or field.type_word not in (0x42, 0x44) or field.auxiliary:
        return dict(result, reason='unsupported contextual text-reference field attributes')
    if (field.data_offset < 0 or field.data_offset + width > owner.byte_size
            or start < 0 or start + width > min(block_end, len(data))):
        return dict(result, reason='text reference exceeds its owning record or block')
    if not field_slot_clear(owner, field, width, slot_cache):
        return dict(result, reason='text reference overlaps another named field start')
    word = struct.unpack_from('<Q', data, start)[0]
    result['reference_bits'] = f'0x{word:016x}'
    if width == 24:
        result['header_bits'] = '0x' + data[start:start + width][::-1].hex()
    if word == 0:
        return dict(result, reason='null contextual text references are not validated')
    number, offset = word & 0xfffff, word >> 20
    if not 1 <= number <= len(blocks):
        return dict(result, reason='text reference has an invalid block ID')
    block = blocks[number - 1]
    if block.type_hash != 0x10:
        return dict(result, reason='text reference does not select the measured ASCII pool profile')
    if local_structures.get(block.type_hash):
        return dict(result, reason='text pool has a local schema; intrinsic fallback is forbidden')
    if offset >= block.byte_length:
        return dict(result, reason='text reference is outside the logical pool span')
    pool = pool_for_block(block)
    if pool is None or pool.get('kind') != 'nul_ascii' or pool.get('status') != 'complete':
        return dict(result, reason='text reference requires an existing complete ASCII pool view')
    entries = entry_cache.get(block.index) if entry_cache is not None else None
    if entries is None:
        entries = {e['data_offset'] - block.data_offset: e for e in pool['elements']}
        if entry_cache is not None:
            entry_cache[block.index] = entries
    entry = entries.get(offset)
    if entry is None:
        return dict(result, reason='text reference is not at an exact pool entry boundary')
    if entry['byte_length'] <= 1:
        return dict(result, reason='empty contextual text entries are not validated')
    if width == 24:
        first, second, marker, reserved = struct.unpack_from('<HHIQ', data, start + 8)
        if (first != entry['byte_length'] - 1 or second != entry['byte_length']
                or marker != 1 or reserved != 0):
            return dict(result, reason='text reference header differs from the measured length/marker profile')
    result.update(status='pool_element_reference', interpretation='inferred', profile=profile,
                  block_index=block.index, pool_element_index=entry['index'],
                  data_offset=entry['data_offset'], byte_length=entry['byte_length'])
    result.pop('candidate_profile')
    return result
