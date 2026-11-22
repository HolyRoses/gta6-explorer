"""Conservative views of low-ID PSIN pools from direct byte observations.

Hash32 reuses the existing inferred scalar meaning. Printable NUL-terminated
ASCII is a measured storage profile. Packed references are candidates only;
integer signedness, vector semantics and pointer targets are not decoded.
No external implementation, mapping table or game fixture is used.
"""
from __future__ import annotations

from . import psin_schema


def reference_candidate(word, blocks):
    """Describe a measured bit partition without dereferencing its target."""
    result = dict(interpretation='candidate', block_id_bits=20)
    if word == 0:
        return dict(result, status='zero_word')
    number, offset = word & 0xfffff, word >> 20
    result.update(block_id=number, byte_offset=offset)
    if not 1 <= number <= len(blocks):
        return dict(result, status='invalid_block_id')
    target = blocks[number - 1]
    result.update(block_index=target.index, block_type=f'0x{target.type_hash:08x}')
    return dict(result, status='in_bounds' if offset < target.byte_length else 'offset_out_of_bounds')


def inspect_pool(data, block, blocks, *, consume, dictionary=None):
    """View one pool in an already verified container; None for unknown IDs.

    Caller must prefer local structure definitions (including ambiguity).
    Every emitted element consumes the instance reader's shared node budget.
    Candidate/opaque elements keep their bits but never become decoded values.
    """
    key = block.type_hash
    if key not in (7, 0x10, 0x14, 0x16, 0x33, 0x4a):
        return None
    start, end = block.data_offset, block.data_offset + block.byte_length
    if start < 0 or block.byte_length <= 0 or end > len(data):
        raise ValueError('PSIN pool exceeds container bounds')
    raw = data[start:end]
    kind = {7: 'reference64_candidate', 0x10: 'nul_ascii', 0x14: 'opaque32',
            0x16: 'opaque64', 0x33: 'opaque128', 0x4a: 'hash32'}[key]
    result = dict(kind=kind, interpretation='inferred' if key in (0x10, 0x4a) else
                  'candidate' if key == 7 else 'unknown', elements=[])
    if key == 0x10:
        if raw[-1] != 0 or any(c != 0 and not 32 <= c < 127 for c in raw):
            return dict(result, status='unresolved',
                        reason='unvalidated text profile: requires printable ASCII and final NUL')
        # No split/list allocation before output-budget checks.
        width = None
    else:
        width = {7: 8, 0x14: 4, 0x16: 8, 0x33: 16, 0x4a: 4}[key]
        if len(raw) % width:
            return dict(result, status='unresolved',
                        reason=f'pool length is not a supported {width}-byte storage multiple')
        result['view_bytes' if key in (0x14, 0x16, 0x33) else 'storage_bytes'] = width
    position = 0
    while position < len(raw):
        consume()
        stop = position + width if width is not None else raw.index(0, position) + 1
        item = dict(index=len(result['elements']), data_offset=start + position,
                    byte_length=stop - position,
                    value_bits='0x' + raw[position:stop][::-1].hex())
        if key == 0x4a:
            value = int.from_bytes(raw[position:stop], 'little')
            item.update(status='decoded', value=f'0x{value:08x}',
                        value_name_matches=psin_schema._matches(dictionary, value))
        elif key == 0x10:
            item.update(status='decoded', value=raw[position:stop - 1].decode('ascii'))
        elif key == 7:
            item.update(status='unresolved', reason='candidate reference; target is not followed',
                        reference=reference_candidate(int.from_bytes(raw[position:stop], 'little'), blocks))
        else:
            item.update(status='unresolved', reason='storage view only; type meaning is unknown')
        result['elements'].append(item)
        position = stop
    result['status'] = 'complete' if key in (0x10, 0x4a) else 'partial'
    return result
