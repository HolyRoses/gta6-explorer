"""Minimal RGBA8 PNG writer (stdlib only)."""

from __future__ import annotations

import struct
import zlib

__all__ = ["png_bytes", "write_png"]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))


def png_bytes(width: int, height: int, rgba: bytes) -> bytes:
    """Encode tightly packed RGBA8 pixels as a PNG."""
    if len(rgba) != width * height * 4:
        raise ValueError("RGBA buffer size does not match the dimensions")
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        rows.append(0)                    # filter: none
        rows += rgba[y * stride:(y + 1) * stride]
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", header)
            + _chunk(b"IDAT", zlib.compress(bytes(rows), 6))
            + _chunk(b"IEND", b""))


def write_png(path: str, width: int, height: int, rgba: bytes) -> None:
    with open(path, "wb") as out:
        out.write(png_bytes(width, height, rgba))
