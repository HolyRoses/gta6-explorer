"""Strict BC7 field packing and the BCPack endpoint/index state convention.

Derived from public Microsoft BC7 layout documentation and the repository
format specification. Standard partition anchors reuse the project's existing
MIT/public-domain BC7 tables; no BCPack reference tables are used.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..tables.bc7 import ANCHOR2, ANCHOR3_1, ANCHOR3_2

SUBSETS = (3, 2, 3, 2, 1, 1, 1, 2)
CHANNEL_BITS = ((4,4,4,0), (6,6,6,0), (5,5,5,0), (7,7,7,0),
                (5,5,5,6), (7,7,7,8), (7,7,7,7), (5,5,5,5))
INDEX_BITS = ((3,0), (3,0), (2,0), (2,0), (3,2), (2,2), (4,0), (2,0))
PARTITION_BITS = (4, 6, 6, 6, 0, 0, 0, 6)
PBIT_MODES = (0, 1, 3, 6, 7)


@dataclass(frozen=True)
class Control:
    mode: int
    partition: int = 0
    rotation: int = 0
    index_selection: int = 0

    def __post_init__(self):
        if type(self.mode) is not int or not 0 <= self.mode < 8:
            raise ValueError('invalid BC7 mode')
        for value, limit, name in (
                (self.partition, 1 << PARTITION_BITS[self.mode], 'partition'),
                (self.rotation, 4 if self.mode in (4,5) else 1, 'rotation'),
                (self.index_selection, 2 if self.mode == 4 else 1, 'index selection')):
            if type(value) is not int or not 0 <= value < limit:
                raise ValueError('invalid BC7 ' + name)

    def as_list(self):
        return [self.mode, self.partition, self.rotation, self.index_selection]


def all_controls():
    """Enumerate the 285 legal BC7 controls, without assigning BCPack codes."""
    return tuple(Control(mode, partition, rotation, selection)
                 for mode in range(8)
                 for partition in range(1 << PARTITION_BITS[mode])
                 for rotation in range(4 if mode in (4,5) else 1)
                 for selection in range(2 if mode == 4 else 1))


@dataclass(frozen=True)
class State:
    # Endpoints are top-aligned in bytes, R0 R1 G0 G1 B0 B1 A0 A1.
    # Only red carries the shared p-bit. Indices are top-aligned in four bits.
    endpoints: tuple[tuple[int, ...], ...]
    indices: tuple[tuple[int, ...], tuple[int, ...]]

    def __post_init__(self):
        if (not isinstance(self.endpoints, tuple) or not 1 <= len(self.endpoints) <= 3
                or any(not isinstance(row, tuple) or len(row) != 8
                       or any(type(v) is not int or not 0 <= v <= 255 for v in row)
                       for row in self.endpoints)
                or not isinstance(self.indices, tuple) or len(self.indices) != 2
                or any(not isinstance(row, tuple) or len(row) != 16
                       or any(type(v) is not int or not 0 <= v < 16 for v in row)
                       for row in self.indices)):
            raise ValueError('invalid BC7 reconstruction state')


ZERO = State(((0,)*8,), ((0,)*16, (0,)*16))


def channel_order(control):
    order = list(range(4))
    if control.rotation:
        order[3], order[control.rotation-1] = order[control.rotation-1], order[3]
    return order


def precisions(control):
    bits = list(CHANNEL_BITS[control.mode])
    if control.rotation:
        bits[3], bits[control.rotation-1] = bits[control.rotation-1], bits[3]
    if control.mode in PBIT_MODES:
        bits[0] += 1
    return bits


def anchors(control):
    if SUBSETS[control.mode] == 1:
        return (0,)
    if SUBSETS[control.mode] == 2:
        return (0, ANCHOR2[control.partition])
    return (0, ANCHOR3_1[control.partition], ANCHOR3_2[control.partition])


def pack(control: Control, state: State, *, omit_anchor_msb=False) -> bytes:
    """Write a BC7 block; MDU states may retain the omitted anchor high bit.

    Ordinary BC7 field states require canonical zero anchor MSBs by default.
    The BCPack writer explicitly omits those bits while preserving the full
    predictor state; it does not normalize endpoints or guess a missing bit.
    """
    if not isinstance(control, Control) or not isinstance(state, State):
        raise ValueError('invalid BC7 control/state')
    if len(state.endpoints) != SUBSETS[control.mode]:
        raise ValueError('BC7 subset count mismatch')
    value = cursor = 0
    def put(v, n):
        nonlocal value, cursor
        if not 0 <= v < 1 << n:
            raise ValueError('BC7 field outside precision')
        value |= v << cursor
        cursor += n
    mode = control.mode
    put(1 << mode, mode+1)
    put(control.partition, PARTITION_BITS[mode])
    if mode in (4,5):put(control.rotation, 2)
    if mode == 4:put(control.index_selection, 1)
    bits = precisions(control)
    for row in state.endpoints:
        for channel, precision in enumerate(bits):
            mask = (1 << (8-precision))-1
            if row[2*channel] & mask or row[2*channel+1] & mask:
                raise ValueError('BC7 endpoint has unused low bits')
    for physical, channel in enumerate(channel_order(control)):
        base_bits = CHANNEL_BITS[mode][physical]
        if not base_bits:continue
        for row in state.endpoints:
            for endpoint in (0,1):
                field = row[2*channel+endpoint] >> (8-bits[channel])
                if mode in PBIT_MODES and channel == 0:field >>= 1
                put(field, base_bits)
    if mode in PBIT_MODES:
        for row in state.endpoints:
            pbits = [(row[i] >> (8-bits[0])) & 1 for i in (0,1)]
            if mode == 1:
                if pbits[0] != pbits[1]:raise ValueError('BC7 shared p-bit mismatch')
                put(pbits[0], 1)
            else:
                for p in pbits:put(p,1)
    for plane in ((1,0) if mode == 4 else (0,1)):
        precision = INDEX_BITS[mode][plane]
        for pixel, field in enumerate(state.indices[plane]):
            if field & ((1 << (4-precision))-1):
                raise ValueError('BC7 index has unused low bits')
            if not precision:continue
            width = precision - (pixel in anchors(control))
            v = field >> (4-precision)
            if omit_anchor_msb and pixel in anchors(control):v &= (1 << width)-1
            put(v, width)
    if cursor != 128:raise ValueError('BC7 block bit count mismatch')
    return value.to_bytes(16, 'little')


def unpack(block: bytes) -> tuple[Control, State]:
    """Read a standard BC7 block without expanding endpoint precision to RGBA."""
    if not isinstance(block, bytes) or len(block) != 16:
        raise ValueError('BC7 block must be exactly sixteen bytes')
    word = int.from_bytes(block,'little')
    mode = next((m for m in range(8) if (word >> m) & 1), None)
    if mode is None:raise ValueError('reserved BC7 mode')
    cursor = mode+1
    def take(n):
        nonlocal cursor
        value = (word >> cursor) & ((1 << n)-1)
        cursor += n
        return value
    control = Control(mode, take(PARTITION_BITS[mode]),
                      take(2) if mode in (4,5) else 0, take(1) if mode == 4 else 0)
    bits = precisions(control)
    endpoints = [[0]*8 for _ in range(SUBSETS[mode])]
    for physical, channel in enumerate(channel_order(control)):
        width = CHANNEL_BITS[mode][physical]
        if not width:continue
        for row in endpoints:
            for endpoint in (0,1):
                v = take(width)
                if mode in PBIT_MODES and channel == 0:v <<= 1
                row[2*channel+endpoint] = v
    if mode in PBIT_MODES:
        for row in endpoints:
            p0 = take(1);p1 = p0 if mode == 1 else take(1)
            row[0] |= p0;row[1] |= p1
    for row in endpoints:
        for channel, width in enumerate(bits):
            for endpoint in (0,1):row[2*channel+endpoint] <<= 8-width
    indices = [[0]*16 for _ in range(2)]
    for plane in ((1,0) if mode == 4 else (0,1)):
        width = INDEX_BITS[mode][plane]
        if width:
            for pixel in range(16):
                indices[plane][pixel] = take(width-(pixel in anchors(control))) << (4-width)
    if cursor != 128:raise ValueError('BC7 block bit count mismatch')
    return control, State(tuple(map(tuple,endpoints)), tuple(map(tuple,indices)))
