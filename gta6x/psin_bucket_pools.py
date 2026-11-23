"""Optional opaque four-byte PSIN pool spans with complete-coverage witnesses.

Exact local descriptors and every eligible header jointly bound storage. No
primitive, element, integer, hash, key, lookup or application meaning is assigned.
"""
from __future__ import annotations

import struct

from . import psin_references

PROFILE = 'opaque_descriptor_pool_span_coverage_v1'


def eligible(owner, field):
    if field.name_hash == 0x100 or field.type_word & 0xffff != 0x5c or field.auxiliary:
        return False
    index = field.type_word >> 16
    if index >= len(owner.fields):
        return False
    descriptor = owner.fields[index]
    return (descriptor is not field and descriptor.name_hash == 0x100
            and descriptor.data_offset == 0 and descriptor.type_word == 0x1b4d
            and descriptor.auxiliary == 0)


def collect(data, blocks, structures, *, read_bucket, consume, max_depth):
    """Collect all independently bounded eligible local headers before output.

    The callback reuses the exact bucket framing rules and shares this budget.
    Unknown blocks are not guessed into structures; depth-truncated typed scans
    cannot authorize pool coverage. Exact source aliases retain one physical row.
    """
    consume()
    headers = {}; visited = set(); complete = True

    def visit(owner, at, end, depth):
        nonlocal complete
        consume()
        identity = owner.name_hash, at
        if identity in visited:
            return
        visited.add(identity)
        if depth > max_depth:
            complete = False
            return
        if at < 0 or at + owner.byte_size > min(end, len(data)):
            complete = False
            return
        for field in owner.fields:
            consume()
            if field.name_hash == 0x100:
                continue
            start = at + field.data_offset
            if eligible(owner, field):
                valid = (field.data_offset >= 0 and field.data_offset + 16 <= owner.byte_size
                         and psin_references.field_slot_clear(owner, field, 16))
                if not valid:
                    complete = False
                    continue
                a, b, word = struct.unpack_from('<IIQ', data, start)
                headers[start] = dict(data_offset=start, first_word=a, second_word=b,
                    reference_word=word, block_id=word & 0xfffff, byte_offset=word >> 20)
            elif field.type_word == 5:
                defs = structures.get(field.auxiliary, [])
                if (len(defs) != 1 or defs[0].byte_size <= 0
                        or field.data_offset < 0
                        or not psin_references.field_slot_clear(owner, field, defs[0].byte_size)):
                    complete = False
                else:
                    visit(defs[0], start, at + owner.byte_size, depth + 1)
            elif field.type_word == 0x75:
                mapping = read_bucket(start, field, owner, at + owner.byte_size)
                if mapping.get('mode') == 'embedded_structure_spans':
                    for entry in mapping['entries']:
                        span = entry['value_span']; defs = structures.get(int(span['structure_hash'], 16), [])
                        if len(defs) != 1:
                            complete = False
                        else:
                            visit(defs[0], span['data_offset'], span['data_offset'] + span['byte_length'], depth + 1)
                elif mapping['status'] != 'complete':
                    # An unresolved potential owner cannot be used as coverage
                    # evidence. Refuse authorization rather than omit its rows.
                    complete = False

    for block in blocks:
        consume()
        defs = structures.get(block.type_hash, [])
        if not defs:
            continue
        if len(defs) != 1 or defs[0].byte_size <= 0 or block.byte_length % defs[0].byte_size:
            complete = False
            continue
        owner = defs[0]
        for at in range(block.data_offset, block.data_offset + block.byte_length, owner.byte_size):
            visit(owner, at, at + owner.byte_size, 0)
    grouped = {}
    for row in headers.values():
        consume()
        word = row['reference_word']
        if not word:
            if row['first_word'] or row['second_word']:
                complete = False
        elif (not 1 <= row['block_id'] <= len(blocks)
              or blocks[row['block_id'] - 1].type_hash != 0x4d
              or structures.get(0x4d)):
            complete = False
        if word:
            grouped.setdefault(row['block_id'], []).append(row)
    pools = {}
    for number, rows in grouped.items():
        consume()
        if not 1 <= number <= len(blocks):
            continue
        target = blocks[number - 1]
        reason = None
        if target.type_hash != 0x4d or structures.get(target.type_hash):
            reason = 'target is not an untyped local opaque pool0x4d'
        elif not complete:
            reason = 'eligible header scan is incomplete or ambiguous'
        elif target.byte_length <= 0 or target.byte_length % 4:
            reason = 'opaque pool does not have a positive whole four-byte extent'
        elif any(r['first_word'] != r['second_word'] or r['first_word'] <= 0 for r in rows):
            reason = 'eligible pool header has unequal or nonpositive stored words'
        intervals = sorted({(r['byte_offset'], r['first_word']) for r in rows})
        cursor = 0
        if reason is None:
            for offset, count in intervals:
                consume()
                if offset != cursor or offset % 4 or count > (target.byte_length - offset) // 4:
                    reason = 'eligible spans have a gap, partial overlap or out-of-bounds extent'
                    break
                cursor = offset + count * 4
            if reason is None and cursor != target.byte_length:
                reason = 'eligible spans do not exhaust the complete opaque pool'
        pools[number] = dict(status='unresolved' if reason else 'complete',
            reason=reason, block_index=target.index, data_offset=target.data_offset,
            byte_length=target.byte_length, header_count=len(rows), distinct_spans=len(intervals))
    return dict(headers=headers, pools=pools, scan_complete=complete)


def resolve(data, start, owner, field, index, *, consume):
    """Emit raw four-byte groups only after the complete-pool guard succeeds."""
    consume()
    result = dict(status='unresolved', candidate_profile=PROFILE, words=[])
    if not eligible(owner, field):
        return dict(result, reason='unsupported local opaque pool descriptor profile')
    row = index['headers'].get(start)
    if row is None:
        return dict(result, reason='field has no independently collected bounded header')
    result.update(header_data_offset=start, header_byte_length=16,
        header_bits='0x' + data[start:start + 16][::-1].hex(),
        first_word=row['first_word'], second_word=row['second_word'],
        reference_bits=f"0x{row['reference_word']:016x}")
    if row['first_word'] == row['second_word'] == row['reference_word'] == 0:
        return dict(result, status='complete', profile=result.pop('candidate_profile'), target=None,
            interpretation='exact null-empty storage header only; no primitive or element meaning')
    pool = index['pools'].get(row['block_id'])
    if pool is None or pool['status'] != 'complete':
        return dict(result, reason=pool['reason'] if pool else 'pool has no complete coverage witness')
    count = row['first_word']; at = pool['data_offset'] + row['byte_offset']
    # Consume all requested output nodes before constructing the list.
    for _ in range(count):
        consume()
    words = [dict(index=i, data_offset=at + 4 * i, byte_length=4,
                  raw_bits='0x' + data[at + 4 * i:at + 4 * i + 4][::-1].hex())
             for i in range(count)]
    result.update(status='complete', profile=result.pop('candidate_profile'), words=words,
        storage_group_bytes=4, stored_word_count=count,
        target=dict(block_index=pool['block_index'], block_type='0x0000004d',
            data_offset=at, byte_offset=row['byte_offset'], byte_length=4 * count),
        coverage=dict(pool_data_offset=pool['data_offset'], pool_byte_length=pool['byte_length'],
            physical_headers=pool['header_count'], distinct_spans=pool['distinct_spans']),
        interpretation='opaque four-byte storage groups only; primitive, element and lookup meanings unresolved')
    return result
