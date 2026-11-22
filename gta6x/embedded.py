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
  zero padding; they are appended until the declared graphics allocations are
  covered. Descriptor +0x08 counts format elements, including allocation padding.
* BCn 2D textures and explicitly tagged 2D arrays use Gfx10 S4K placement, with ceil-divided hardware mip
  dimensions, smallest-first macroblocks and a shared 4 KiB tail. Logical DDS
  dimensions are cropped to floor-divided pixel dimensions. Full declared mip
  chains are exported after checking the allocation footprint exactly.
* Array layers contain consecutive complete hardware mip chains. DDS output
  retains every layer; selecting a layer for preview is explicit in the API.
* Single-level non-BC 2D textures retain the measured 16x16-element layout.
* Single-level uncompressed 3D textures with shape tag 3 use the public
  non-XOR S4K volume equations. DDS retains every depth plane. Non-BC mip
  chains, cubemaps and unknown shape tags are refused.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Iterator
from types import SimpleNamespace

from . import gfx10, rpf, texture, volume, zlibcarve

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
           "mip0", "mip_linear", "exportable_mips", "dds_bytes", "dds_mips", "dds_mip0",
           "format_name", "volume_linear", "volume_slice"]


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
    swizzle_mode: int = 5
    shape_tag: int | None = None

    @property
    def shape(self) -> str:
        if self.shape_tag == 1 or (self.shape_tag is None and self.depth == 1):
            return "2d_array" if self.depth > 1 else "2d"
        return "3d" if self.shape_tag == 3 else "unknown"

    @property
    def slices(self) -> int:
        """2D array layer count; volumes have no validated 2D slices."""
        return self.depth if self.shape in ("2d", "2d_array") else 0

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
            "swizzle_mode": self.swizzle_mode,
            "shape_tag": self.shape_tag,
            "shape": self.shape,
            "slices": self.slices,
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
                    size_field=_u32(system, at + 8), struct_off=at,
                    swizzle_mode=_u16(system, at + 0x40),
                    shape_tag=system[at + 0x3E]))
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


def _required(texs: list[EmbeddedTexture]) -> int | None:
    best = 0
    for tex in texs:
        size = tex.size_field * tex.element_size
        if tex.data_off < 0 or size <= 0 or tex.data_off + size > MAX_GFX:
            return None
        best = max(best, tex.data_off + size)
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
    if ew <= 0 or eh <= 0 or bpe not in (1, 2, 4, 8, 16):
        raise ValueError("invalid embedded element grid")
    required = -(-ew // 16) * -(-eh // 16) * 256 * bpe
    if len(src) < required:
        raise ValueError("truncated embedded tiled data")
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
                dst = (y * ew + x) * bpe
                out[dst:dst + bpe] = src[src_at:src_at + bpe]
    return bytes(out)


def _layout(tex: EmbeddedTexture) -> gfx10.Layout | volume.VolumeLayout | None:
    """Validate the shape and allocation before selecting a measured layout."""
    if tex.element_size not in (1, 2, 4, 8, 16):
        raise ValueError(f"unsupported DXGI format {tex.dxgi_format}")
    if (tex.width < 1 or tex.height < 1 or tex.mips < 1 or tex.mips > 15
            or tex.mips > max(tex.width, tex.height).bit_length()):
        raise ValueError("invalid embedded dimensions or mip count")
    # Older authored descriptors omitted this field. Preserve their 2D API,
    # but never infer an array or cube solely from a depth of six.
    if tex.shape not in ("2d", "2d_array", "3d") or not 1 <= tex.depth <= 256:
        raise ValueError("embedded depth/array shape tag is not validated")
    if tex.swizzle_mode != 5:
        raise ValueError("embedded swizzle mode is not validated")
    allocated = tex.size_field * tex.element_size
    if tex.data_off < 0 or allocated <= 0 or tex.data_off + allocated > MAX_GFX:
        raise ValueError("invalid embedded graphics allocation")
    if tex.shape == "3d":
        if tex.mips != 1:
            raise ValueError("embedded volume mip layout is not validated")
        if tex.is_bc:
            raise ValueError("embedded BC volume layout is not validated")
        layout = volume.layout_for(_volume_descriptor(tex))
        if layout is None:
            raise ValueError("embedded volume format is not validated")
        if layout.total != allocated:
            raise ValueError("embedded volume S4K footprint does not match allocation")
        return layout
    if not tex.is_bc:
        if tex.depth != 1:
            raise ValueError("embedded non-BC array layout is not validated")
        if tex.mips != 1:
            raise ValueError("embedded non-BC mip layout is not validated")
        required = -(-tex.width // 16) * -(-tex.height // 16) * 256 * tex.element_size
        if required > allocated:
            raise ValueError("embedded tiled footprint exceeds allocation")
        return None
    layout = gfx10.Layout.new(
        "S4K", -(-tex.width // 4), -(-tex.height // 4), tex.mips,
        tex.element_size, round_mips_up=True)
    assert layout is not None
    if tex.mips == 1:
        # A non-mipmapped resource has no tail, including tiny solid textures.
        layout.mips[0].tail = None
    # Public non-XOR S4K subresource addressing advances by the complete
    # hardware chain size per array layer, including that layer's mip tail.
    layout.slices = tex.depth
    layout.slice_major = True
    layout.total = layout.slice_bytes * tex.depth
    if layout.total != allocated:
        raise ValueError("embedded S4K footprint does not match allocation")
    return layout


def exportable_mips(tex: EmbeddedTexture) -> int:
    """All declared levels of a validated allocation, or ValueError."""
    _layout(tex)
    return tex.mips


def mip_linear(tex: EmbeddedTexture, gfx: bytes, mip: int, *, slice_index: int = 0) -> bytes:
    """One mip of one 2D layer, in the texture's own format (default layer 0)."""
    layout = _layout(tex)
    if tex.shape == "3d":
        raise ValueError("embedded volume plane requires volume_slice with an explicit z index")
    if not isinstance(mip, int) or mip < 0 or mip >= tex.mips:
        raise ValueError("embedded mip index out of range")
    if not isinstance(slice_index, int) or not 0 <= slice_index < tex.slices:
        raise ValueError("embedded slice index out of range")
    element = tex.element_size
    end = tex.data_off + tex.size_field * element
    if end > len(gfx):
        raise ValueError("truncated embedded graphics allocation")
    block = tex.block_pixels
    width = max(1, tex.width >> mip)
    height = max(1, tex.height >> mip)
    ew = -(-width // block)
    eh = -(-height // block)
    if layout is not None:
        # Crop hardware padding without changing its stored pitch. Check every
        # address rather than using Layout.untile_slice's pool zero-fill policy.
        out = bytearray(ew * eh * element)
        for y in range(eh):
            for x in range(ew):
                at = tex.data_off + layout.addr(mip, slice_index, x, y)
                if at < tex.data_off or at + element > end:
                    raise ValueError("embedded mip address exceeds allocation")
                dst = (y * ew + x) * element
                out[dst:dst + element] = gfx[at:at + element]
        return bytes(out)
    padded = (-(-ew // 16) * 16) * (-(-eh // 16) * 16) * element
    start = tex.data_off
    return _deswizzle(gfx[start:start + padded], ew, eh, element)


def mip0(tex: EmbeddedTexture, gfx: bytes, *, slice_index: int = 0) -> bytes:
    """Mip 0 of one 2D layer (default layer 0); DDS exports retain all layers."""
    return mip_linear(tex, gfx, 0, slice_index=slice_index)


def dds_bytes(tex: EmbeddedTexture, linear: bytes) -> bytes:
    """DDS with a single mip (mip 0)."""
    _layout(tex)
    if tex.shape == "3d":
        raise ValueError("embedded volume DDS requires every depth plane; use dds_mip0")
    if tex.slices != 1:
        raise ValueError("embedded array DDS requires all layers; use dds_mip0")
    if len(linear) != _mip_bytes(tex, 0):
        raise ValueError("embedded mip 0 byte count mismatch")
    header = texture.dds_header(tex.width, tex.height, 1, 1, tex.dxgi_format)
    return header + linear


def dds_mips(tex: EmbeddedTexture, gfx: bytes) -> tuple[bytes, int]:
    """Native DDS with the complete declared mip chain; no partial output."""
    count = exportable_mips(tex)
    if tex.shape == "3d":
        return texture.dds_header_volume(_volume_descriptor(tex)) + volume_linear(tex, gfx), count
    payload = bytearray()
    for layer in range(tex.slices):
        for mip in range(count):
            payload.extend(mip_linear(tex, gfx, mip, slice_index=layer))
    return (texture.dds_header(tex.width, tex.height, count, tex.slices,
                               tex.dxgi_format) + payload, count)


def dds_mip0(tex: EmbeddedTexture, gfx: bytes) -> bytes:
    """DDS containing mip 0 of every validated array layer or volume plane."""
    _layout(tex)
    if tex.shape == "3d":
        return texture.dds_header_volume(_volume_descriptor(tex)) + volume_linear(tex, gfx)
    payload = b"".join(mip0(tex, gfx, slice_index=i) for i in range(tex.slices))
    return texture.dds_header(tex.width, tex.height, 1, tex.slices,
                              tex.dxgi_format) + payload


def _volume_descriptor(tex: EmbeddedTexture):
    """Adapt depth to the existing public volume-layout/DDS helper interface."""
    return SimpleNamespace(width=tex.width, height=tex.height, slices=tex.depth,
                           mips=tex.mips, dxgi_format=tex.dxgi_format, dimension=3)


def _volume_planes(tex: EmbeddedTexture, gfx: bytes, z_start: int, z_count: int) -> bytes:
    layout = _layout(tex)
    if tex.shape != "3d":
        raise ValueError("embedded texture is not a validated volume")
    if type(z_start) is not int or not 0 <= z_start < tex.depth:
        raise ValueError("embedded volume z index out of range")
    end = tex.data_off + layout.total
    if end > len(gfx):
        raise ValueError("truncated embedded volume graphics allocation")
    # Do not use VolumeLayout.untile's pool zero-fill policy. Even a selected
    # preview plane requires the complete declared allocation to be present.
    element = tex.element_size
    out = bytearray(tex.width * tex.height * z_count * element)
    for z in range(z_start, z_start + z_count):
        for y in range(tex.height):
            for x in range(tex.width):
                at = tex.data_off + layout.addr(x, y, z)
                if at < tex.data_off or at + element > end:
                    raise ValueError("embedded volume address exceeds allocation")
                dst = (((z - z_start) * tex.height + y) * tex.width + x) * element
                out[dst:dst + element] = gfx[at:at + element]
    return bytes(out)


def volume_linear(tex: EmbeddedTexture, gfx: bytes) -> bytes:
    """Complete single-mip volume, x fastest followed by y and then z."""
    return _volume_planes(tex, gfx, 0, tex.depth)


def volume_slice(tex: EmbeddedTexture, gfx: bytes, z_index: int) -> bytes:
    """One explicit XY plane; the complete volume allocation must be present."""
    return _volume_planes(tex, gfx, z_index, 1)
