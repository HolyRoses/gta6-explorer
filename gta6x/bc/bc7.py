"""BC7 (BPTC) decoder for native PNG previews.

Ported from Richard Geldreich's ``bc7decomp.cpp`` (MIT OR public domain,
Copyright (c) 2020 Richard Geldreich, Jr.). See
``LICENSES/bc7decomp-MIT.txt`` and ``THIRD_PARTY_NOTICES.md``.

The decoder handles all eight BC7 modes, including partitions, P-bits,
dual-plane alpha and index rotation. It returns tightly packed RGBA8.
"""

from __future__ import annotations

from .tables.bc7 import (
    ANCHOR2, ANCHOR3_1, ANCHOR3_2, MODE_FROM_BYTE, PARTITION2, PARTITION3,
)

__all__ = ["decode_block", "decode_bc7"]

MASK64 = (1 << 64) - 1
WEIGHTS = {
    2: (0, 21, 43, 64),
    3: (0, 9, 18, 27, 37, 46, 55, 64),
    4: (0, 4, 9, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 55, 60, 64),
}


def _insert_weight_zero(value: int, bits: int, offset: int) -> int:
    low = (1 << ((bits * (offset + 1)) - 1)) - 1
    high = MASK64 & ~low
    return (((value & high) << 1) | (value & low)) & MASK64


def _dequant(value: int, bits: int, pbit: int | None = None) -> int:
    if pbit is not None:
        total = bits + 1
        value = (value << 1) | pbit
        value <<= 8 - total
        value |= value >> total
        return value & 0xFF
    value <<= 8 - bits
    value |= value >> bits
    return value & 0xFF


def _interp(low: int, high: int, weight: int, bits: int) -> int:
    table = WEIGHTS[bits]
    return (low * (64 - table[weight]) + high * table[weight] + 32) >> 6


def _colors(endpoints: list[list[int]], subset: int, bits: int,
            comps: int) -> list[tuple[int, int, int, int]]:
    table = WEIGHTS[bits]
    low, high = endpoints[subset * 2], endpoints[subset * 2 + 1]
    out = []
    for index in range(len(table)):
        color = tuple(_interp(low[c], high[c], index, bits)
                      for c in range(comps))
        if comps < 4:
            color += (255,)
        out.append(color)
    return out


def _mode0_2(mode: int, low: int, high: int) -> list[tuple[int, int, int, int]]:
    weight_bits = 3 if mode == 0 else 2
    endpoint_bits = 4 if mode == 0 else 5
    endpoint_mask = (1 << endpoint_bits) - 1
    part_mask = (1 << (4 if mode == 0 else 6)) - 1
    part = (low >> (mode + 1)) & part_mask

    if mode == 0:
        chunks = [low >> 5, low >> 29, (low >> 53) | (high << 11)]
    else:
        chunks = [low >> 9, (low >> 39) | (high << 25), high >> 5]

    endpoints = [[0, 0, 0, 255] for _ in range(6)]
    for channel in range(3):
        chunk = chunks[channel]
        for endpoint in range(6):
            endpoints[endpoint][channel] = chunk & endpoint_mask
            chunk >>= endpoint_bits

    pbits = [0] * 6
    if mode == 0:
        pb = (high >> 13) & 0xFF
        for index in range(6):
            pbits[index] = (pb >> index) & 1

    weights = high >> (67 - 16 * weight_bits)
    weights = _insert_weight_zero(weights, weight_bits, 0)
    weights = _insert_weight_zero(
        weights, weight_bits, min(ANCHOR3_1[part], ANCHOR3_2[part]))
    weights = _insert_weight_zero(
        weights, weight_bits, max(ANCHOR3_1[part], ANCHOR3_2[part]))

    indexes = []
    for _ in range(16):
        indexes.append(weights & ((1 << weight_bits) - 1))
        weights >>= weight_bits

    for channel in range(3):
        chunk = chunks[channel]
        for endpoint in range(6):
            endpoints[endpoint][channel] = chunk & endpoint_mask
            chunk >>= endpoint_bits
    for endpoint in range(6):
        for channel in range(3):
            endpoints[endpoint][channel] = _dequant(
                endpoints[endpoint][channel], endpoint_bits,
                pbits[endpoint] if mode == 0 else None)

    subsets = [_colors(endpoints, subset, weight_bits, 3) for subset in range(3)]
    return [subsets[PARTITION3[part * 16 + i]][indexes[i]] for i in range(16)]


def _mode1_3_7(mode: int, low: int, high: int) -> list[tuple[int, int, int, int]]:
    weight_bits = 3 if mode == 1 else 2
    endpoint_bits = 5 if mode == 7 else (6 if mode == 1 else 7)
    endpoint_mask = (1 << endpoint_bits) - 1
    comps = 4 if mode == 7 else 3
    part = (low >> (mode + 1)) & 0x3F
    pbits_count = 2 if mode == 1 else 4
    shared_pbits = mode == 1

    if mode == 1:
        chunks = [low >> 8, low >> 32, (low >> 56) | (high << 8)]
        p_read = high >> 16
        weight_read = high >> 18
    elif mode == 3:
        chunks = [low >> 10, (low >> 38) | (high << 26), high >> 2]
        p_read = high >> 30
        weight_read = high >> 34
    else:
        chunks = [low >> 14, low >> 34, (low >> 54) | (high << 10), high >> 10]
        p_read = high >> 30
        weight_read = high >> 34

    endpoints = [[0, 0, 0, 255] for _ in range(4)]
    for channel in range(comps):
        chunk = chunks[channel]
        for endpoint in range(4):
            endpoints[endpoint][channel] = chunk & endpoint_mask
            chunk >>= endpoint_bits

    pbits = [(p_read >> i) & 1 for i in range(pbits_count)]
    weight_read = _insert_weight_zero(weight_read, weight_bits, 0)
    weight_read = _insert_weight_zero(weight_read, weight_bits, ANCHOR2[part])
    indexes = []
    for _ in range(16):
        indexes.append(weight_read & ((1 << weight_bits) - 1))
        weight_read >>= weight_bits

    for endpoint in range(4):
        for channel in range(4):
            if mode != 7 and channel == 3:
                endpoints[endpoint][3] = 255
                continue
            pbit = pbits[
                (endpoint >> 1) if shared_pbits else endpoint]
            endpoints[endpoint][channel] = _dequant(
                endpoints[endpoint][channel], endpoint_bits, pbit)

    subsets = [_colors(endpoints, subset, weight_bits, comps)
               for subset in range(2)]
    return [subsets[PARTITION2[part * 16 + i]][indexes[i]] for i in range(16)]


def _mode4_5(mode: int, low: int, high: int) -> list[tuple[int, int, int, int]]:
    weight_bits = 2
    alpha_weight_bits = 3 if mode == 4 else 2
    endpoint_bits = 5 if mode == 4 else 7
    endpoint_mask = (1 << endpoint_bits) - 1
    alpha_endpoint_bits = 6 if mode == 4 else 8
    alpha_endpoint_mask = (1 << alpha_endpoint_bits) - 1
    comp_rot = (low >> (mode + 1)) & 0x3
    index_mode = (low >> 7) & 1 if mode == 4 else 0
    color_read = low >> 8

    endpoints = [[0, 0, 0, 255] for _ in range(2)]
    for channel in range(3):
        for endpoint in range(2):
            endpoints[endpoint][channel] = color_read & endpoint_mask
            color_read >>= endpoint_bits

    if mode == 4:
        endpoints[0][3] = color_read & alpha_endpoint_mask
        endpoints[1][3] = (color_read >> alpha_endpoint_bits) & alpha_endpoint_mask
        rgb_weights = (low >> 50) | (high << 14)
        alpha_weights = high >> 17
    else:
        endpoints[0][3] = color_read & alpha_endpoint_mask
        endpoints[1][3] = ((low >> 58) | (high << 6)) & alpha_endpoint_mask
        rgb_weights = high >> 2
        alpha_weights = high >> 33

    rgb_weights = _insert_weight_zero(rgb_weights, weight_bits, 0)
    alpha_weights = _insert_weight_zero(alpha_weights, alpha_weight_bits, 0)

    bits = (alpha_weight_bits if index_mode else weight_bits,
            weight_bits if index_mode else alpha_weight_bits)
    masks = ((1 << bits[0]) - 1, (1 << bits[1]) - 1)
    if index_mode:
        rgb_weights, alpha_weights = alpha_weights, rgb_weights

    indexes = []
    for _ in range(16):
        indexes.append(rgb_weights & masks[0])
        rgb_weights >>= bits[0]
    alphas = []
    for _ in range(16):
        alphas.append(alpha_weights & masks[1])
        alpha_weights >>= bits[1]

    for endpoint in endpoints:
        for channel in range(4):
            endpoint[channel] = _dequant(
                endpoint[channel],
                alpha_endpoint_bits if channel == 3 else endpoint_bits)

    colors = [tuple(_interp(endpoints[0][c], endpoints[1][c], i, bits[0])
                    for c in range(3)) for i in range(1 << bits[0])]
    alpha_table = [_interp(endpoints[0][3], endpoints[1][3], i, bits[1])
                   for i in range(1 << bits[1])]

    out = []
    for index in range(16):
        color = list(colors[indexes[index]])
        color.append(alpha_table[alphas[index]])
        if comp_rot >= 1:
            target = comp_rot - 1
            color[target], color[3] = color[3], color[target]
        out.append(tuple(color))
    return out


def _mode6(low: int, high: int) -> list[tuple[int, int, int, int]]:
    def field(value: int, shift: int, bits: int) -> int:
        return (value >> shift) & ((1 << bits) - 1)

    p0 = field(low, 63, 1)
    p1 = field(high, 0, 1)
    channels = [
        field(low, 7, 7), field(low, 14, 7),
        field(low, 21, 7), field(low, 28, 7),
        field(low, 35, 7), field(low, 42, 7),
        field(low, 49, 7), field(low, 56, 7),
    ]
    end0 = (channels[0] << 1 | p0, channels[2] << 1 | p0,
            channels[4] << 1 | p0, channels[6] << 1 | p0)
    end1 = (channels[1] << 1 | p1, channels[3] << 1 | p1,
            channels[5] << 1 | p1, channels[7] << 1 | p1)
    colors = [tuple((end0[c] * (64 - WEIGHTS[4][w])
                     + end1[c] * WEIGHTS[4][w] + 32) >> 6
                    for c in range(4)) for w in range(16)]
    shifts = [1, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60]
    indices = [field(high, shift, 3 if i == 0 else 4)
               for i, shift in enumerate(shifts)]
    return [colors[indices[i]] for i in range(16)]


def decode_block(block: bytes) -> list[tuple[int, int, int, int]]:
    """Decode one 16-byte BC7 block into 16 RGBA tuples."""
    if len(block) < 16:
        block = block.ljust(16, b"\x00")
    low = int.from_bytes(block[:8], "little")
    high = int.from_bytes(block[8:16], "little")
    mode = MODE_FROM_BYTE[block[0]]
    if mode >= 8:
        return [(0, 0, 0, 0)] * 16
    if mode in (0, 2):
        return _mode0_2(mode, low, high)
    if mode in (1, 3, 7):
        return _mode1_3_7(mode, low, high)
    if mode in (4, 5):
        return _mode4_5(mode, low, high)
    return _mode6(low, high)


def decode_bc7(data: bytes, width: int, height: int) -> bytes:
    """Decode a BC7 payload to tightly packed RGBA8."""
    out = bytearray(width * height * 4)
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    at = 0
    for by in range(blocks_y):
        for bx in range(blocks_x):
            colors = decode_block(data[at:at + 16])
            at += 16
            for y in range(4):
                py = by * 4 + y
                if py >= height:
                    continue
                for x in range(4):
                    px = bx * 4 + x
                    if px >= width:
                        continue
                    dst = (py * width + px) * 4
                    out[dst:dst + 4] = bytes(colors[y * 4 + x])
    return bytes(out)
