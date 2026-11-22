"""BCn and 8-bit component decoders for RGBA8 PNG previews.

BC6H previews are tone-mapped. Signed normalized components map [-1,1] to
[0,255]; signed 8-bit integers map [-128,127] to [0,255]. These are display
conventions; DDS preserves the original blocks and format. Output is tightly
packed RGBA8, ready for :mod:`gta6x.png`.
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


def _signed8(value: int) -> int:
    return value - 256 if value >= 128 else value


def _snorm8_preview(numerator: int, denominator: int = 1) -> int:
    """Map a rational SNORM8 component to a byte, rounding nearest/half up.

    Keep interpolation fractional until this final display conversion. Both
    signed encodings -128 and -127 represent -1.0.
    """
    limit = 127 * denominator
    numerator = max(-limit, min(limit, numerator))
    return ((numerator + limit) * 255 + limit) // (2 * limit)


def _alpha_table(block: bytes, signed: bool = False) -> tuple[list[int], int]:
    if signed:
        # Clamp before comparison, choosing the four-interpolant case when
        # raw endpoints are -127/-128 (an implementation-dependent RGTC case).
        a0, a1 = (max(-127, _signed8(value)) for value in block[:2])
        table = [_snorm8_preview(a0), _snorm8_preview(a1)]
        if a0 > a1:
            table += [_snorm8_preview((7 - i) * a0 + i * a1, 7) for i in range(1, 7)]
        else:
            table += [_snorm8_preview((5 - i) * a0 + i * a1, 5) for i in range(1, 5)] + [0, 255]
        return table, int.from_bytes(block[2:8], "little")
    a0, a1 = block[0], block[1]
    if a0 > a1:
        table = [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    else:
        table = ([a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)]
                 + [0, 255])
    return table, int.from_bytes(block[2:8], "little")


def _put_bc4(block: bytes, out: bytearray, width: int, height: int,
             bx: int, by: int, channel: str, signed: bool = False) -> None:
    table, bits = _alpha_table(block, signed)
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
        _put_color(block[8:], out, width, height, bx, by, True)
        for y in range(4):
            for x in range(4):
                px, py = bx * 4 + x, by * 4 + y
                if px >= width or py >= height:
                    continue
                nibble = (block[(y * 4 + x) // 2] >> (4 * ((y * 4 + x) & 1))) & 0x0F
                out[(py * width + px) * 4 + 3] = nibble * 17
    return bytes(out)


def _bc3(data: bytes, width: int, height: int) -> bytes:
    out = bytearray(width * height * 4)
    for bx, by, block in _each_block(data, width, height, 16):
        _put_color(block[8:], out, width, height, bx, by, True)
        _put_bc4(block[:8], out, width, height, bx, by, "a")
    return bytes(out)


def _bc4(data: bytes, width: int, height: int, signed: bool = False) -> bytes:
    out = bytearray(width * height * 4)
    for bx, by, block in _each_block(data, width, height, 8):
        _put_bc4(block, out, width, height, bx, by, "r", signed)
        for y in range(4):
            for x in range(4):
                px, py = bx * 4 + x, by * 4 + y
                if px < width and py < height:
                    out[(py * width + px) * 4 + 3] = 255
    return bytes(out)


def _bc5(data: bytes, width: int, height: int, signed: bool = False) -> bytes:
    out = bytearray(width * height * 4)
    for bx, by, block in _each_block(data, width, height, 16):
        _put_bc4(block[:8], out, width, height, bx, by, "r", signed)
        _put_bc4(block[8:], out, width, height, bx, by, "g", signed)
        for y in range(4):
            for x in range(4):
                px, py = bx * 4 + x, by * 4 + y
                if px < width and py < height:
                    out[(py * width + px) * 4 + 3] = 255
    return bytes(out)


def _need(width: int, height: int, size: int) -> int:
    return ((width + 3) // 4) * ((height + 3) // 4) * size


def _byte_image(data: bytes, width: int, height: int, channels: int,
                kind: str = "unsigned") -> bytes | None:
    needed = width * height * channels
    if len(data) < needed:
        return None
    data = data[:needed]
    if kind == "snorm":
        data = bytes(_snorm8_preview(_signed8(value)) for value in data)
    elif kind == "sint":
        data = bytes(_signed8(value) + 128 for value in data)
    if channels == 4:
        return bytes(data)
    out = bytearray(width * height * 4)
    for pixel in range(width * height):
        at = pixel * channels
        red = data[at]
        rgba = (red, red, red, 255) if channels == 1 else (red, data[at + 1], 0, 255)
        out[4 * pixel:4 * pixel + 4] = bytes(rgba)
    return bytes(out)


def decode_rgba(dxgi_format: int, data: bytes, width: int, height: int) -> bytes | None:
    """Decode mip 0 to RGBA8, or return ``None`` for unsupported formats."""
    if width <= 0 or height <= 0:
        return None
    block_sizes = {70: 8, 71: 8, 72: 8, 73: 16, 74: 16, 75: 16,
                   76: 16, 77: 16, 78: 16, 79: 8, 80: 8, 81: 8,
                   82: 16, 83: 16, 84: 16, 94: 16, 95: 16, 96: 16,
                   97: 16, 98: 16, 99: 16}
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
        return _bc4(data, width, height, signed=(dxgi_format == 81))
    if dxgi_format in (82, 83, 84):
        return _bc5(data, width, height, signed=(dxgi_format == 84))
    if dxgi_format in (97, 98, 99):
        from .bc7 import decode_bc7
        return decode_bc7(data, width, height)
    if dxgi_format in (94, 95, 96):
        from .bc6h import decode_bc6h
        return decode_bc6h(data, width, height, signed=(dxgi_format == 96))
    if dxgi_format in (27, 28, 29, 30, 31, 32):
        kind = "snorm" if dxgi_format == 32 else "sint" if dxgi_format == 31 else "unsigned"
        return _byte_image(data, width, height, 4, kind)
    if dxgi_format in (48, 49, 50, 51, 52):
        kind = "snorm" if dxgi_format == 52 else "sint" if dxgi_format == 51 else "unsigned"
        return _byte_image(data, width, height, 2, kind)
    if dxgi_format in (87, 88, 90, 91):
        raw = bytearray(data[:width * height * 4].ljust(width * height * 4, b"\x00"))
        for i in range(0, len(raw), 4):
            raw[i], raw[i + 2] = raw[i + 2], raw[i]
        return bytes(raw)
    if dxgi_format in (60, 61, 62, 63, 64, 65):
        kind = "snorm" if dxgi_format == 64 else "sint" if dxgi_format == 63 else "unsigned"
        return _byte_image(data, width, height, 1, kind)
    return None
