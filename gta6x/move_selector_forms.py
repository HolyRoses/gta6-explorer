"""Measured kind-28 selector headers with opaque bounded remainders.

Only complete discovery-observed selector words select a checked prefix.
Individual selector widths and all numeric/application meanings remain unknown.
No pointer or recursive interpretation of the remainder is enabled.
"""
from __future__ import annotations

import hashlib
import struct

PROFILE = 'observed_move_kind28_selector_header_v1'
PREFIX_BYTES = {0x2: 32, 0xa: 36, 0x2a: 40, 0x6a: 44, 0xaa: 44,
                0x296: 64, 0xaa9: 56}


def inspect_kind28(data, at, size, consume):
    """Describe one measured prefix after caller-authorized parent framing.

    Table entries are whole-word observed storage profiles, not a general
    selector alphabet or inferred per-field width formula. The full candidate
    must end at the prefix or retain a checked opaque next-ordinal witness.
    """
    stop = at + size

    def span(pos, count):
        if (type(at) is not int or type(size) is not int or at < 0 or size < 0
                or stop > len(data) or count < 0 or pos < at or pos > stop-count):
            raise ValueError('MoVE kind-28 header exceeds its bounded candidate')

    span(at, 28)
    kind, ordinal, name, raw_tag, word = struct.unpack_from('<HHIII', data, at)
    if kind != 28 or ordinal or word not in PREFIX_BYTES:
        raise ValueError('unsupported MoVE kind-28 selector/header profile')
    width = PREFIX_BYTES[word]
    span(at, width)
    if any(struct.unpack_from('<I', data, at+p)[0] for p in (16, 20, 24)):
        raise ValueError('unsupported MoVE kind-28 zero-slot profile')
    if word == 0x6a and struct.unpack_from('<I', data, at+40)[0]:
        raise ValueError('unsupported MoVE kind-28 final zero-slot profile')
    if word == 0x296 and any(data[at+32:at+56]):
        raise ValueError('unsupported MoVE kind-28 combined zero-slot profile')
    if word == 0xaa9 and struct.unpack_from('<I', data, at+32)[0] != name:
        raise ValueError('MoVE kind-28 repeated header word differs')
    tail = at + width
    remaining = stop-tail
    if remaining:
        span(tail, 8)
        if struct.unpack_from('<H', data, tail+2)[0] != 1:
            raise ValueError('unsupported MoVE kind-28 opaque-remainder ordinal')
    consume(22 + bool(remaining))
    result = dict(status='complete', profile=PROFILE,
        form='kind28_measured_selector_header',
        header=dict(data_offset=at, byte_length=width, raw_kind_u16=kind,
            raw_ordinal_u16=ordinal, name_hash_bits=f'0x{name:08x}',
            raw_tag_bits=f'0x{raw_tag:08x}', selector_word_bits=f'0x{word:08x}',
            value_bits='0x'+data[at:tail][::-1].hex(),
            selectors=[dict(index=i, bit_offset=2*i, raw_code=(word >> (2*i)) & 3)
                       for i in range(16)]),
        references=[], records=[],
        regions=[dict(name='selector_header', data_offset=at, byte_length=width),
                 dict(name='opaque_remainder', data_offset=tail, byte_length=remaining)],
        opaque_regions=[dict(data_offset=tail, byte_length=remaining,
            sha256=hashlib.sha256(data[tail:stop]).hexdigest(), interpretation='opaque')],
        summary=dict(header_prefixes=1, header_selector_fields=16, header_prefix_bytes=width),
        interpretation='measured whole-selector storage profile only; field widths, selector and motion meanings unknown')
    if remaining:
        result['remainder_header'] = dict(data_offset=tail, byte_length=8,
            raw_ordinal_u16=1, value_bits='0x'+data[tail:tail+8][::-1].hex(),
            interpretation='opaque boundary witness only')
    return result
