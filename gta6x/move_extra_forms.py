"""Measured kind-11 MoVE header prefixes with opaque remainders.

Packed selector fields constrain observed storage widths and zero-bit slots.
No selector, scalar, channel, pose, time or remainder meaning is inferred.
"""
from __future__ import annotations

import hashlib
import struct

PROFILE = 'observed_move_kind11_selector_header_v1'
SELECTOR_WORDS = frozenset((0x5556, 0x5559, 0x5566, 0x5569, 0x556a,
                            0x596a, 0x4556a, 0x4596a, 0x45a6a))


def inspect_kind11(data, at, size, consume):
    """Describe an exact measured prefix or raise before publishing metadata.

    The caller already bounds the parent candidate and verifies its header.
    Only discovery-observed selector words are accepted. A nonempty remainder
    requires the independently observed next ordinal, and stays wholly opaque.
    """
    stop = at + size

    def span(pos, count):
        if (type(at) is not int or type(size) is not int or at < 0 or size < 0
                or stop > len(data) or count < 0 or pos < at or pos > stop-count):
            raise ValueError('MoVE kind-11 header exceeds its bounded candidate')

    span(at, 12)
    kind, ordinal, name, word = struct.unpack_from('<HHII', data, at)
    if kind != 11 or ordinal or word not in SELECTOR_WORDS:
        raise ValueError('unsupported MoVE kind-11 selector/header profile')
    codes = [(word >> (2*i)) & 3 for i in range(10)]
    width = 44 + 8 * (codes[0] == 1) + 4 * bool(word & 0x40000)
    span(at, width)
    if codes[0] == 1:
        zero = (12, 32, 36, 44, 48)
        sparse = 40
    else:
        zero = (24, 36, 40)
        if codes[1] == 1:
            zero += (16,)
        if codes[4] == 1:
            zero += (28,)
        sparse = 32 if codes[5] == 1 else None
    if any(struct.unpack_from('<I', data, at+p)[0] for p in zero):
        raise ValueError('unsupported MoVE kind-11 zero-slot profile')
    if sparse is not None and struct.unpack_from('<I', data, at+sparse)[0] not in (0, 0x01000000):
        raise ValueError('unsupported MoVE kind-11 sparse-bit slot profile')
    tail = at + width
    remaining = stop-tail
    if remaining:
        span(tail, 8)
        if struct.unpack_from('<H', data, tail+2)[0] != 1:
            raise ValueError('unsupported MoVE kind-11 opaque-remainder ordinal')
    consume(16 + bool(remaining))
    result = dict(status='complete', profile=PROFILE,
        form='kind11_measured_selector_header',
        header=dict(data_offset=at, byte_length=width, raw_kind_u16=kind,
            raw_ordinal_u16=ordinal, name_hash_bits=f'0x{name:08x}',
            selector_word_bits=f'0x{word:08x}', value_bits='0x'+data[at:tail][::-1].hex(),
            selectors=[dict(index=i, bit_offset=2*i, raw_code=code) for i, code in enumerate(codes)]),
        references=[], records=[],
        regions=[dict(name='selector_header', data_offset=at, byte_length=width),
                 dict(name='opaque_remainder', data_offset=tail, byte_length=remaining)],
        opaque_regions=[dict(data_offset=tail, byte_length=remaining,
            sha256=hashlib.sha256(data[tail:stop]).hexdigest(), interpretation='opaque')],
        summary=dict(header_prefixes=1, header_selector_fields=10, header_prefix_bytes=width),
        interpretation='measured header storage only; selector, scalar and motion meanings unknown')
    if remaining:
        result['remainder_header'] = dict(data_offset=tail, byte_length=8,
            raw_ordinal_u16=1, value_bits='0x'+data[tail:tail+8][::-1].hex(), interpretation='opaque boundary witness only')
    return result
