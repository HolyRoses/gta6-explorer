"""Measured kind-4 MoVE header prefixes with an opaque next-header witness.

Complete observed profile words authorize bounded raw prefixes only. Their
individual fields, selector meanings and possible references stay unknown;
no pointer targets or recursive body interpretation are emitted.
"""
from __future__ import annotations

import hashlib
import struct

PROFILE = 'observed_move_kind4_header_prefix_v1'
# Whole-word discovery profiles, not a general field-width/selector formula.
HEADER_PROFILES = {
    0x00880000: (36, (28, 32)),
    0x00880001: (40, (28, 32, 36)),
    0x80880001: (40, (32, 36)),
    0x8088000a: (44, (36, 40)),
    0x01101081: (40, (28, 36)),
}


def inspect_kind4(data, at, size, consume):
    """Return one complete measured prefix or raise without partial metadata.

    Parent framing must already authorize this candidate and its ordinal/hash.
    Discovery contains no terminal kind-4 example: a bounded next-header prefix
    with ordinal one is mandatory. The remainder's kind, words and body remain
    opaque, and arbitrary parameter changes need not be rejected.
    """
    stop = at + size

    def span(pos, count):
        if (type(at) is not int or type(size) is not int or at < 0 or size < 0
                or stop > len(data) or count < 0 or pos < at or pos > stop-count):
            raise ValueError('MoVE kind-4 header exceeds its bounded candidate')

    span(at, 16)
    kind, ordinal, name, word, marker = struct.unpack_from('<HHIII', data, at)
    profile = HEADER_PROFILES.get(word)
    if kind != 4 or ordinal or profile is None or marker != 1:
        raise ValueError('unsupported MoVE kind-4 whole-word header profile')
    width, zeros = profile
    span(at, width + 8)
    if any(struct.unpack_from('<I', data, at+p)[0] for p in zeros):
        raise ValueError('unsupported MoVE kind-4 zero-slot profile')
    tail = at + width
    if struct.unpack_from('<H', data, tail+2)[0] != 1:
        raise ValueError('unsupported MoVE kind-4 opaque-remainder ordinal')
    consume(7)  # Header, two regions, opaque span, boundary witness and summary/view metadata.
    return dict(status='complete', profile=PROFILE, form='kind4_measured_header_prefix',
        header=dict(data_offset=at, byte_length=width, raw_kind_u16=kind,
            raw_ordinal_u16=ordinal, name_hash_bits=f'0x{name:08x}',
            raw_profile_word_bits=f'0x{word:08x}', raw_marker_u32=marker,
            value_bits='0x'+data[at:tail][::-1].hex()),
        references=[], records=[],
        regions=[dict(name='header_prefix', data_offset=at, byte_length=width),
                 dict(name='opaque_remainder', data_offset=tail, byte_length=stop-tail)],
        opaque_regions=[dict(data_offset=tail, byte_length=stop-tail,
            sha256=hashlib.sha256(data[tail:stop]).hexdigest(), interpretation='opaque')],
        remainder_header=dict(data_offset=tail, byte_length=8, raw_ordinal_u16=1,
            value_bits='0x'+data[tail:tail+8][::-1].hex(),
            interpretation='opaque boundary witness only; kind and words unassigned'),
        summary=dict(header_prefixes=1, header_selector_fields=0, header_prefix_bytes=width),
        interpretation='measured whole-word header prefix only; field widths, references and motion meanings unknown')
