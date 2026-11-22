"""BC6H (HDR BCn) decoder for native PNG previews.

Ported from ``bcdec.h`` by Sergii "iOrange" Kudlai (Unlicense / public
domain). See ``LICENSES/bcdec-MIT.txt``. DDS export keeps the native
BC6H payload; this module only produces approximate 8-bit previews.
"""

from __future__ import annotations

import struct

from .tables.bc6h import ACTUAL_BITS, MODE_READS, PARTITIONS, WEIGHTS3, WEIGHTS4

__all__ = ["decode_block", "decode_bc6h"]


def _extend_sign(value: int, bits: int) -> int:
    value &= (1 << bits) - 1
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def _transform_inverse(value: int, anchor: int, bits: int, signed: bool) -> int:
    value = (value + anchor) & ((1 << bits) - 1)
    return _extend_sign(value, bits) if signed else value


def _unquantize(value: int, bits: int, signed: bool) -> int:
    if not signed:
        if bits >= 15:
            return value
        if value == 0:
            return 0
        if value == (1 << bits) - 1:
            return 0xFFFF
        return ((value << 16) + 0x8000) >> bits
    if bits >= 16:
        return value
    sign = 0
    if value < 0:
        sign = 1
        value = -value
    if value == 0:
        unq = 0
    elif value >= (1 << (bits - 1)) - 1:
        unq = 0x7FFF
    else:
        unq = ((value << 15) + 0x4000) >> (bits - 1)
    return -unq if sign else unq


def _finish_unquantize(value: int, signed: bool) -> int:
    if not signed:
        return ((value * 31) >> 6) & 0xFFFF
    value = -(((-value) * 31) >> 5) if value < 0 else (value * 31) >> 5
    sign = 0
    if value < 0:
        sign = 0x8000
        value = -value
    return (sign | value) & 0xFFFF


def _interp(a: int, b: int, weights: tuple[int, ...], index: int) -> int:
    return (a * (64 - weights[index]) + b * weights[index] + 32) >> 6


class _Bits:
    __slots__ = ("low", "high")

    def __init__(self, block: bytes) -> None:
        self.low = int.from_bytes(block[:8], "little")
        self.high = int.from_bytes(block[8:16], "little")

    def read(self, count: int) -> int:
        mask = (1 << count) - 1
        value = self.low & mask
        self.low >>= count
        self.low |= (self.high & mask) << (64 - count)
        self.high >>= count
        return value

    def read_rev(self, count: int) -> int:
        value = self.read(count)
        result = 0
        while count:
            result = (result << 1) | (value & 1)
            value >>= 1
            count -= 1
        return result


def decode_block(block: bytes, signed: bool = False) -> list[tuple[int, int, int]]:
    """Decode one 16-byte BC6H block into 16 half-float RGB triples."""
    reader = _Bits(block.ljust(16, b"\x00"))
    mode = reader.read(2)
    if mode > 1:
        mode |= reader.read(3) << 2
    entry = MODE_READS.get(mode)
    if entry is None:
        return [(0, 0, 0)] * 16
    mode, reads = entry
    r = [0, 0, 0, 0]
    g = [0, 0, 0, 0]
    b = [0, 0, 0, 0]
    channels = {0: r, 1: g, 2: b}
    partition = 0
    for operation in reads:
        if operation[0] == "p":
            partition = reader.read(operation[1])
        else:
            channel, index, kind, count, shift = operation
            value = reader.read_rev(count) if kind == "r" else reader.read(count)
            channels["rgb".index(channel)][index] |= value << shift

    num_partitions = 0 if mode >= 10 else 1
    endpoint_bits = ACTUAL_BITS[0][mode]
    if signed:
        for channel in (r, g, b):
            channel[0] = _extend_sign(channel[0], endpoint_bits)
    if (mode != 9 and mode != 10) or signed:
        for index in range(1, (num_partitions + 1) * 2):
            for channel, row in zip((r, g, b), (1, 2, 3)):
                channel[index] = _extend_sign(
                    channel[index], ACTUAL_BITS[row][mode])
    if mode != 9 and mode != 10:
        for index in range(1, (num_partitions + 1) * 2):
            r[index] = _transform_inverse(r[index], r[0], endpoint_bits, signed)
            g[index] = _transform_inverse(g[index], g[0], endpoint_bits, signed)
            b[index] = _transform_inverse(b[index], b[0], endpoint_bits, signed)

    for index in range((num_partitions + 1) * 2):
        r[index] = _unquantize(r[index], endpoint_bits, signed)
        g[index] = _unquantize(g[index], endpoint_bits, signed)
        b[index] = _unquantize(b[index], endpoint_bits, signed)

    weights = WEIGHTS4 if mode >= 10 else WEIGHTS3
    out: list[tuple[int, int, int]] = []
    for y in range(4):
        for x in range(4):
            if mode >= 10:
                marker = 128 if (x | y) == 0 else 0
            else:
                marker = PARTITIONS[partition][y * 4 + x]
            bits = 4 if mode >= 10 else 3
            if marker & 0x80:
                bits -= 1
            subset = marker & 1
            index = reader.read(bits)
            anchor = subset * 2
            out.append((
                _finish_unquantize(_interp(r[anchor], r[anchor + 1],
                                          weights, index), signed),
                _finish_unquantize(_interp(g[anchor], g[anchor + 1],
                                          weights, index), signed),
                _finish_unquantize(_interp(b[anchor], b[anchor + 1],
                                          weights, index), signed),
            ))
    return out


def _half_to_float(value: int) -> float:
    return struct.unpack("<e", struct.pack("<H", value))[0]


def decode_bc6h(data: bytes, width: int, height: int,
                signed: bool = False) -> bytes:
    """Decode BC6H to approximate 8-bit RGBA for previews.

    The source is HDR; DDS preserves the exact half-float values. This preview
    uses a Reinhard tone map and sRGB transfer so highlights remain visible.
    """
    out = bytearray(width * height * 4)
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    at = 0
    for by in range(blocks_y):
        for bx in range(blocks_x):
            pixels = decode_block(data[at:at + 16], signed)
            at += 16
            for y in range(4):
                py = by * 4 + y
                if py >= height:
                    continue
                for x in range(4):
                    px = bx * 4 + x
                    if px >= width:
                        continue
                    red, green, blue = pixels[y * 4 + x]
                    values = []
                    for value in (red, green, blue):
                        linear = max(0.0, _half_to_float(value))
                        mapped = linear / (1.0 + linear)
                        values.append(max(0.0, min(1.0, mapped)) ** (1.0 / 2.2))
                    dst = (py * width + px) * 4
                    out[dst:dst + 4] = bytes((
                        int(values[0] * 255 + 0.5),
                        int(values[1] * 255 + 0.5),
                        int(values[2] * 255 + 0.5), 255))
    return bytes(out)
