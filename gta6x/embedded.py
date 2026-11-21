"""Native extraction of embedded RAGE texture dictionaries (``txd`` resources).

GTA VI stores two kinds of textures:

* streamed pools (``data/ttdb/*.ttpf``), handled by :mod:`gta6x.texture`, and
* **embedded texture dictionaries** inside RPF resources -- the classic ``txd``
  shape, with a small *system* page of descriptors and one or more compressed
  *graphics* pages holding the pixel data.

This module assembles those resources from their zlib streams without any key:

* A system page is recognised by scanning for 0x70-byte texture structs
  (``u16 8`` at +0x0E, a graphics pointer ``0x6xxxxxxx`` at +0x18, dimensions,
  DXGI format and mip count) and a name pointer (``0x5xxxxxxx`` at +0x30).
* The following zlib streams are contiguous at 16-byte boundaries, separated by
  zero padding; they are appended into the graphics buffer until every
  descriptor's mip 0 is covered.
* Mips are stored smallest-first; mip 0 begins at the 4 KiB-aligned sum of the
  smaller mips. Pixel data is tiled in 16x16-element blocks and deswizzled with
  the format-size-dependent pattern below. Only mip 0 is exported (DDS), because
  smaller mips sit in a packed tail whose layout is not established.

The shape is the one documented by SixNG; rpf9-explorer's older dictionary
walk targets a different resource generation and does not find these pages in
1.0.2.1.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Iterator

from . import rpf, texture, zlibcarve

SYSTEM_MAX_PACKED = 256 * 1024
MAX_SYSTEM = 32 * 1024 * 1024
MAX_GFX = 224 * 1024 * 1024
MAX_STREAMS = 64

#: In-tile element bit patterns (element-coordinate bit -> x/y).
PATTERNS = {
    8: ((True, 0), (False, 0), (False, 1), (True, 1), (True, 2), (False, 2),
        (True, 3), (False, 3)),
    16: ((False, 0), (False, 1), (True, 0), (True, 1), (False, 2), (True, 2),
         (False, 3), (True, 3)),
}
DEFAULT_PATTERN = ((True, 0), (False, 0), (True, 1), (False, 1), (True, 2),
                   (False, 2), (True, 3), (False, 3))

__all__ = ["EmbeddedTexture", "EmbeddedResource", "parse_system", "iter_resources",
           "mip0", "dds_bytes", "format_name"]


@dataclass
class EmbeddedTexture:
    name: str
    width: int
    height: int
    depth: int
    mips: int
    dxgi_format: int
    data_off: int
    size_field: int
    struct_off: int

    @property
    def element_size(self) -> int:
        return texture.format_info(self.dxgi_format)[1]

    @property
    def block_pixels(self) -> int:
        return texture.format_info(self.dxgi_format)[2]

    @property
    def is_bc(self) -> bool:
        return texture.format_info(self.dxgi_format)[3]

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "depth": self.depth,
            "mips": self.mips,
            "dxgi_format": self.dxgi_format,
            "format": format_name(self.dxgi_format),
            "data_offset": self.data_off,
            "size_field": self.size_field,
            "struct_offset": self.struct_off,
        }


@dataclass
class EmbeddedResource:
    archive: str
    offset: int
    name: str
    system_size: int
    gfx_size: int
    textures: list[EmbeddedTexture] = field(default_factory=list)
    gfx: bytes = b""

    def as_dict(self) -> dict:
        return {
            "archive": self.archive,
            "offset": self.offset,
            "offset_hex": f"0x{self.offset:x}",
            "name": self.name,
            "system_bytes": self.system_size,
            "graphics_bytes": self.gfx_size,
            "textures": [t.as_dict() for t in self.textures],
        }


def format_name(dxgi_format: int) -> str:
    return texture.format_name(dxgi_format)


def _u16(buf: bytes, at: int) -> int:
    return struct.unpack_from("<H", buf, at)[0]


def _u32(buf: bytes, at: int) -> int:
    return struct.unpack_from("<I", buf, at)[0]


def _u64(buf: bytes, at: int) -> int:
    return struct.unpack_from("<Q", buf, at)[0]


def _ptr_offset(ptr: int, limit: int) -> int | None:
    if ptr >> 28 != 5:
        return None
    offset = ptr & 0x0FFFFFFF
    return offset if offset < limit else None


def _cstr(buf: bytes, at: int, limit: int = 256) -> str:
    end = buf.find(b"\x00", at, min(len(buf), at + limit))
    if end < 0:
        return ""
    return buf[at:end].decode("latin1", "replace")


def parse_system(system: bytes) -> list[EmbeddedTexture]:
    """Find every plausible texture struct in a resource's system page."""
    found: list[EmbeddedTexture] = []
    at = 0
    while at + 0x48 <= len(system):
        if _u16(system, at + 0x0E) == 8 and (_u64(system, at + 0x18) >> 28) == 6:
            width = _u16(system, at + 0x38)
            height = _u16(system, at + 0x3A)
            depth = _u16(system, at + 0x3C)
            fmt = system[at + 0x3F]
            mips = system[at + 0x42]
            if (width and height and 0 < depth <= 256 and 0 < mips <= 15
                    and 0 < fmt <= 132):
                name = ""
                name_off = _ptr_offset(_u64(system, at + 0x30), len(system))
                if name_off is not None:
                    name = _cstr(system, name_off + 8)
                found.append(EmbeddedTexture(
                    name=name, width=width, height=height, depth=depth,
                    mips=mips, dxgi_format=fmt,
                    data_off=_u64(system, at + 0x18) & 0x0FFFFFFF,
                    size_field=_u32(system, at + 8), struct_off=at))
                at += 0x70
                continue
        at += 8
    return found


def _valid_name(name: str) -> bool:
    return (2 <= len(name) <= 96 and all(c.isalnum() or c in "_-. " for c in name)
            and any(c.isalpha() for c in name))


def _dict_name(system: bytes) -> str:
    """Name string that follows the system page map, when present."""
    page_map = _ptr_offset(_u64(system, 8), len(system))
    if page_map is None:
        return ""
    at = page_map + 16
    limit = min(len(system), page_map + 0x200)
    while at < limit:
        if system[at]:
            name = _cstr(system, at)
            return name if _valid_name(name) else ""
        at += 1
    return ""


def _mip_bytes(tex: EmbeddedTexture, mip: int) -> int | None:
    element = tex.element_size
    if element == 0:
        return None
    block = tex.block_pixels
    width = max(1, tex.width >> mip)
    height = max(1, tex.height >> mip)
    return (-(-width // block)) * (-(-height // block)) * element


def _mip0_offset(tex: EmbeddedTexture) -> int | None:
    if tex.mips <= 1:
        return 0
    tail = 0
    for mip in range(1, tex.mips):
        size = _mip_bytes(tex, mip)
        if size is None:
            return None
        tail += size
    return (tail + 4095) & ~4095


def _required(texs: list[EmbeddedTexture]) -> int | None:
    best = 0
    for tex in texs:
        offset = _mip0_offset(tex)
        size = _mip_bytes(tex, 0)
        if offset is None or size is None:
            return None
        best = max(best, tex.data_off + offset + size)
    return best


def _align16(value: int) -> int:
    return (value + 15) & ~15


def _zero_padding(fh, start: int, end: int) -> bool:
    if end < start or end - start > 15:
        return False
    fh.seek(start)
    return set(fh.read(end - start)) <= {0}


def iter_resources(path: str | os.PathLike, limit: int | None = None,
                   start: int | None = None) -> Iterator[EmbeddedResource]:
    """Yield embedded texture resources from an archive's payload area."""
    path = os.fspath(path)
    archive = os.path.basename(path)
    if start is None:
        try:
            start = rpf.read_header(path).index_size
        except (OSError, ValueError):
            start = 0
    blobs = [blob for blob in zlibcarve.carve_streams(
        path, length=(start + limit) if limit else None, min_out=64)
        if blob.offset >= start]
    consumed: set[int] = set()
    with open(path, "rb") as fh:
        for i, first in enumerate(blobs):
            if first.offset in consumed or first.compressed > SYSTEM_MAX_PACKED:
                continue
            if len(first.data) > MAX_SYSTEM:
                continue
            texs = [tex for tex in parse_system(first.data) if tex.element_size]
            if not texs:
                continue
            names = [tex.name for tex in texs if _valid_name(tex.name)]
            dict_name = _dict_name(first.data)
            name = dict_name or (names[0] if names else "")
            if not name:
                continue  # too weak a signal for a system page
            need = _required(texs)
            if need is None or need > MAX_GFX:
                continue
            graphics = bytearray()
            appended: list[int] = []
            last = first
            j = i + 1
            while j < len(blobs) and len(graphics) < need and len(appended) < MAX_STREAMS:
                nxt = blobs[j]
                expected = _align16(last.offset + last.compressed)
                if nxt.offset != expected or not _zero_padding(
                        fh, last.offset + last.compressed, expected):
                    break
                if (nxt.compressed <= SYSTEM_MAX_PACKED and parse_system(nxt.data)):
                    break  # next resource's system page
                graphics.extend(nxt.data)
                appended.append(nxt.offset)
                last = nxt
                if len(graphics) > MAX_GFX:
                    break
                j += 1
            if len(graphics) < need:
                continue
            consumed.add(first.offset)
            consumed.update(appended)
            yield EmbeddedResource(
                archive=archive,
                offset=first.offset,
                name=name or f"txd_{first.offset:x}",
                system_size=len(first.data),
                gfx_size=len(graphics),
                textures=texs,
                gfx=bytes(graphics[:need]),
            )


def _lut(bpe: int) -> list[tuple[int, int]]:
    pattern = PATTERNS.get(bpe, DEFAULT_PATTERN)
    lut = []
    for element in range(256):
        x = y = 0
        for bit, (is_x, coord) in enumerate(pattern):
            if element >> bit & 1:
                if is_x:
                    x |= 1 << coord
                else:
                    y |= 1 << coord
        lut.append((x, y))
    return lut


_LUTS: dict[int, list[tuple[int, int]]] = {}


def _deswizzle(src: bytes, ew: int, eh: int, bpe: int) -> bytes:
    lut = _LUTS.get(bpe)
    if lut is None:
        lut = _LUTS[bpe] = _lut(bpe)
    tiles_x = -(-ew // 16)
    tiles_y = -(-eh // 16)
    out = bytearray(ew * eh * bpe)
    for ty in range(tiles_y):
        for tx in range(tiles_x):
            base = (ty * tiles_x + tx) * 256 * bpe
            for element, (lx, ly) in enumerate(lut):
                x = tx * 16 + lx
                y = ty * 16 + ly
                if x >= ew or y >= eh:
                    continue
                src_at = base + element * bpe
                if src_at + bpe > len(src):
                    continue
                dst = (y * ew + x) * bpe
                out[dst:dst + bpe] = src[src_at:src_at + bpe]
    return bytes(out)


def mip0(tex: EmbeddedTexture, gfx: bytes) -> bytes:
    """Linear (untiled) bytes of mip 0, in the texture's own format."""
    element = tex.element_size
    if element == 0:
        raise ValueError(f"unsupported DXGI format {tex.dxgi_format}")
    offset = _mip0_offset(tex)
    if offset is None:
        raise ValueError("mip layout unknown")
    block = tex.block_pixels
    ew = -(-tex.width // block)
    eh = -(-tex.height // block)
    padded = (-(-ew // 16) * 16) * (-(-eh // 16) * 16) * element
    start = tex.data_off + offset
    if start >= len(gfx):
        raise ValueError("texture data lies outside the graphics pages")
    return _deswizzle(gfx[start:start + padded], ew, eh, element)


def dds_bytes(tex: EmbeddedTexture, linear: bytes) -> bytes:
    """DDS with a single mip (mip 0), which is what the layout supports here."""
    header = texture.dds_header(tex.width, tex.height, 1, 1, tex.dxgi_format)
    return header + linear
