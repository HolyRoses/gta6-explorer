"""BCn decoders for PNG previews (BC1-BC5, BC7 and RGBA8).

BC6H still returns ``None`` and stays DDS-only. Output is tightly packed RGBA8,
ready for :mod:`gta6x.png`.
"""

from __future__ import annotations

import struct

__all__ = ["decode_rgba"]


def _rgb565(value: int) -> tuple[int, int, int]:
    return (((value >> 11) & 0x1F) * 255 // 31,
            ((value >> 5) & 0x3F) * 255 // 63,
            (value & 0x1F) * 255 // 31)


def _colors(block: bytes, four_color: bool) -> list[tuple[int, int, int, int]]:
    c0, c1 = struct.unpack_from("<HH", block, 0)
    a, b = _rgb565(c0), _rgb565(c1)
    if four_color or c0 > c1:
        return [a + (255,), b + (255,),
                tuple((2 * a[i] + b[i]) // 3 for i in range(3)) + (255,),
                tuple((a[i] + 2 * b[i]) // 3 for i in range(3)) + (255,)]
    return [a + (255,), b + (255,),
            tuple((a[i] + b[i]) // 2 for i in range(3)) + (255,),
            (0, 0, 0, 0)]


def _put_color(block: bytes, out: bytearray, width: int, height: int,
               bx: int, by: int, four_color: bool) -> None:
    colors = _colors(block, four_color)
    indices = struct.unpack_from("<I", block, 4)[0]
    for y in range(4):
        for x in range(4):
            px, py = bx * 4 + x, by * 4 + y
            if px >= width or py >= height:
                continue
            dst = (py * width + px) * 4
            out[dst:dst + 4] = bytes(colors[(indices >> (2 * (y * 4 + x))) & 3])


def _alpha_table(block: bytes) -> tuple[list[int], int]:
    a0, a1 = block[0], block[1]
    if a0 > a1:
        table = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        table = ([a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)]
                 + [0, 255])
    return table, int.from_bytes(block[2:8], "little")


def _put_bc4(block: bytes, out: bytearray, width: int, height: int,
             bx: int, by: int, channel: str) -> None:
    table, bits = _alpha_table(block)
    for y in range(4):
        for x in range(4):
            px, py = bx * 4 + x, by * 4 + y
            if px >= width or py >= height:
                continue
            value = table[(bits >> (3 * (y * 4 + x))) & 7]
            dst = (py * width + px) * 4
            if channel == "a":
                out[dst + 3] = value
            elif channel == "g":
                out[dst + 1] = value
            else:
                out[dst] = value


def _each_block(data: bytes, width: int, height: int, size: int):
    blocks_x = (width + 3) // 4
    blocks_y = (height + 3) // 4
    at = 0
    for by in range(blocks_y):
        for bx in range(blocks_x):
            yield bx, by, data[at:at + size]
            at += size


def _bc1(data: bytes, width: int, height: int, four_color: bool = False) -> bytes:
    out = bytearray(width * height * 4)
    for bx, by, block in _each_block(data, width, height, 8):
        _put_color(block, out, width, height, bx, by, four_color)
    return bytes(out)


def _bc2(data: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    for bx, by, block in _each_block(data, width, height, 16):
        _put_color(block[:8], out, width, height, bx, by, True)
        for y in range(4):
            for x in range(4):
                px, py = bx * 4 + x, by * 4 + y
                if px >= width or py >= height:
                    continue
                nibble = (block[8 + (y * 4 + x) // 2] >> (4 * ((y * 4 + x) & 1))) & 0x0F
                out[(py * width + px) * 4 + 3] = nibble * 17
    return bytes(out)


def _bc3(data: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    for bx, by, block in _each_block(data, width, height, 16):
        _put_bc4(block[:8], out, width, height, bx, by, "a")
        _put_color(block[8:], out, width, height, bx, by, True)
    return bytes(out)


def _bc4(data: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    for bx, by, block in _each_block(data, width, height, 8):
        _put_bc4(block, out, width, height, bx, by, "r")
        for y in range(4):
            for x in range(4):
                px, py = bx * 4 + x, by * 4 + y
                if px < width and py < height:
                    out[(py * width + px) * 4 + 3] = 255
    return bytes(out)


def _bc5(data: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    for bx, by, block in _each_block(data, width, height, 16):
        _put_bc4(block[:8], out, width, height, bx, by, "r")
        _put_bc4(block[8:], out, width, height, bx, by, "g")
        for y in range(4):
            for x in range(4):
                px, py = bx * 4 + x, by * 4 + y
                if px < width and py < height:
                    out[(py * width + px) * 4 + 3] = 255
    return bytes(out)


def _need(width: int, height: int, size: int) -> int:
    return ((width + 3) // 4) * ((height + 3) // 4) * size


def decode_rgba(dxgi_format: int, data: bytes, width: int, height: int) -> bytes | None:
    """Decode mip 0 to RGBA8, or return ``None`` for unsupported formats."""
    if width <= 0 or height <= 0:
        return None
    block_sizes = {70: 8, 71: 8, 72: 8, 73: 16, 74: 16, 75: 16,
                   76: 16, 77: 16, 78: 16, 79: 8, 80: 8, 81: 8,
                   82: 16, 83: 16, 84: 16, 97: 16, 98: 16, 99: 16}
    size = block_sizes.get(dxgi_format)
    if size is not None and len(data) < _need(width, height, size):
        return None
    if dxgi_format in (70, 71, 72):
        return _bc1(data, width, height)
    if dxgi_format in (73, 74, 75):
        return _bc2(data, width, height)
    if dxgi_format in (76, 77, 78):
        return _bc3(data, width, height)
    if dxgi_format in (79, 80, 81):
        return _bc4(data, width, height)
    if dxgi_format in (82, 83, 84):
        return _bc5(data, width, height)
    if dxgi_format in (97, 98, 99):
        from .bc7 import decode_bc7
        return decode_bc7(data, width, height)
    if dxgi_format in (28, 29, 30, 31, 32):
        return bytes(data[:width * height * 4]).ljust(width * height * 4, b"\x00")
    if dxgi_format in (87, 88, 90, 91):
        raw = bytearray(data[:width * height * 4].ljust(width * height * 4, b"\x00"))
        for i in range(0, len(raw), 4):
            raw[i], raw[i + 2] = raw[i + 2], raw[i]
        return bytes(raw)
    if dxgi_format in (60, 61, 62, 63, 64, 65):
        gray = data[:width * height].ljust(width * height, b"\x00")
        out = bytearray(width * height * 4)
        for i, value in enumerate(gray):
            out[i * 4:i * 4 + 4] = bytes((value, value, value, 255))
        return bytes(out)
    return None
