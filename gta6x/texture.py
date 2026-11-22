"""Texture catalog and DDS export for ``RDS5``/TTPF pools.

The ETPF dictionary inside every pool describes its textures (width, height,
mip count, DXGI format, AMD Gfx10 tile mode, array size, virtual address).  This
module turns those descriptors into:

* a layout (:mod:`gta6x.gfx10`) that maps (mip, slice, x, y) to a byte offset in
  the pool's *virtual* space,
* a virtual reader that reassembles a texture from the pool's stored/zlib
  chunks (BCPack chunks have no public decoder and are reported as unavailable),
* a standard DDS file writer, so the result opens in any DDS viewer.

Only formats with 8- or 16-byte elements (BC1-BC7) have a validated Gfx10 bit
equation, which covers 99.2% of the 328,091 textures in the 1.0.2.1 pools.
Cube-map copies (tile modes 9-12) are listed but not exported yet.
"""

from __future__ import annotations

import bisect
import os
import struct
import zlib

from . import gfx10, rds5

#: DXGI format -> (name, element bytes, block pixels, block compressed)
FORMATS: dict[int, tuple[str, int, int, bool]] = {
    10: ("R16G16B16A16_FLOAT", 8, 1, False),
    24: ("R10G10B10A2_UNORM", 4, 1, False),
    28: ("R8G8B8A8_UNORM", 4, 1, False),
    29: ("R8G8B8A8_UNORM_SRGB", 4, 1, False),
    34: ("R16G16_FLOAT", 4, 1, False),
    41: ("R32_FLOAT", 4, 1, False),
    49: ("R8G8_UNORM", 2, 1, False),
    54: ("R16_FLOAT", 2, 1, False),
    56: ("R16_UNORM", 2, 1, False),
    61: ("R8_UNORM", 1, 1, False),
    65: ("A8_UNORM", 1, 1, False),
    71: ("BC1_UNORM", 8, 4, True),
    72: ("BC1_UNORM_SRGB", 8, 4, True),
    74: ("BC2_UNORM", 16, 4, True),
    75: ("BC2_UNORM_SRGB", 16, 4, True),
    77: ("BC3_UNORM", 16, 4, True),
    78: ("BC3_UNORM_SRGB", 16, 4, True),
    80: ("BC4_UNORM", 8, 4, True),
    81: ("BC4_SNORM", 8, 4, True),
    83: ("BC5_UNORM", 16, 4, True),
    84: ("BC5_SNORM", 16, 4, True),
    87: ("B8G8R8A8_UNORM", 4, 1, False),
    88: ("B8G8R8X8_UNORM", 4, 1, False),
    91: ("B8G8R8A8_UNORM_SRGB", 4, 1, False),
    93: ("B8G8R8X8_UNORM_SRGB", 4, 1, False),
    95: ("BC6H_UF16", 16, 4, True),
    96: ("BC6H_SF16", 16, 4, True),
    98: ("BC7_UNORM", 16, 4, True),
    99: ("BC7_UNORM_SRGB", 16, 4, True),
}

#: Additional DXGI variants seen in embedded dictionaries. Element sizes follow
#: the BCn block sizes and the SixNG format families; the exact DXGI value is
#: preserved in the DDS header.
FORMATS.update({
    2: ("R32G32B32A32_FLOAT", 16, 1, False),
    26: ("R11G11B10_FLOAT", 4, 1, False),
    27: ("R8G8B8A8_TYPELESS", 4, 1, False),
    30: ("R8G8B8A8_UINT", 4, 1, False),
    31: ("R8G8B8A8_SINT", 4, 1, False),
    32: ("R8G8B8A8_SNORM", 4, 1, False),
    48: ("R8G8_TYPELESS", 2, 1, False),
    50: ("R8G8_UINT", 2, 1, False),
    51: ("R8G8_SINT", 2, 1, False),
    52: ("R8G8_SNORM", 2, 1, False),
    60: ("R8_TYPELESS", 1, 1, False),
    62: ("R8_UINT", 1, 1, False),
    63: ("R8_SINT", 1, 1, False),
    64: ("R8_SNORM", 1, 1, False),
    70: ("BC1_TYPELESS", 8, 4, True),
    73: ("BC2_TYPELESS", 16, 4, True),
    76: ("BC3_TYPELESS", 16, 4, True),
    79: ("BC4_TYPELESS", 8, 4, True),
    82: ("BC5_TYPELESS", 16, 4, True),
    90: ("B8G8R8A8_TYPELESS", 4, 1, False),
    94: ("BC6H_TYPELESS", 16, 4, True),
    97: ("BC7_TYPELESS", 16, 4, True),
})

MAX_TEXTURE_BYTES = 64 * 1024 * 1024
DDS_HEADER_BYTES = 148

__all__ = [
    "FORMATS", "MAX_TEXTURE_BYTES", "format_name", "format_info",
    "chunk_starts", "bcpack_bytes", "coverage", "layout_for", "read_virtual",
    "dds_header", "dds_bytes", "export_texture",
]


def format_info(dxgi_format: int) -> tuple[str, int, int, bool]:
    return FORMATS.get(dxgi_format, (f"DXGI_{dxgi_format}", 0, 1, False))


def format_name(dxgi_format: int) -> str:
    return format_info(dxgi_format)[0]


def layout_for(texture: rds5.TtpTexture) -> gfx10.Layout | None:
    """Gfx10 layout for a texture, or None when unsupported."""
    _name, element_bytes, block_pixels, _is_bc = format_info(texture.dxgi_format)
    if not gfx10.element_bytes_ok(element_bytes):
        return None
    blocks_w = -(-texture.width // block_pixels)
    blocks_h = -(-texture.height // block_pixels)
    if texture.is_cube:
        layout = gfx10.Layout.new("S4K", blocks_w, blocks_h,
                                  texture.mips, element_bytes)
        if layout is None:
            return None
        return layout.with_cube_copies(texture.slices, texture.tile_mode - 8,
                                       texture.cube_base)
    swizzle = gfx10.TILE_MODES.get(texture.tile_mode)
    if swizzle is None:
        return None
    layout = gfx10.Layout.new(swizzle, blocks_w, blocks_h,
                              texture.mips, element_bytes)
    if layout is None:
        return None
    if texture.slices > 1:
        layout.with_slices(texture.slices)
    return layout


def chunk_starts(index: rds5.TtpIndex) -> list[int]:
    """Sorted virtual offsets of a pool's chunks (for binary search)."""
    return [chunk.virtual_offset for chunk in index.chunks]


def bcpack_bytes(index: rds5.TtpIndex, virtual: int, length: int,
                 starts: list[int] | None = None) -> int:
    """Virtual bytes in ``[virtual, virtual + length)`` that are BCPack only."""
    if length <= 0:
        return 0
    if starts is None:
        starts = chunk_starts(index)
    end = virtual + length
    pos = max(0, bisect.bisect_right(starts, virtual) - 1)
    total = 0
    for chunk in index.chunks[pos:]:
        if chunk.virtual_offset >= end:
            break
        if chunk.codec in (rds5.CODEC_STORED, rds5.CODEC_ZLIB):
            continue
        lo = max(virtual, chunk.virtual_offset)
        hi = min(end, chunk.virtual_offset + chunk.size)
        if hi > lo:
            total += hi - lo
    return total


def coverage(index: rds5.TtpIndex, virtual: int, length: int,
             starts: list[int] | None = None) -> tuple[int, int, int]:
    """``(covered, bcpack, uncovered)`` virtual bytes for a byte range."""
    if length <= 0:
        return 0, 0, 0
    if starts is None:
        starts = chunk_starts(index)
    end = virtual + length
    pos = max(0, bisect.bisect_right(starts, virtual) - 1)
    covered = bcpack = 0
    for chunk in index.chunks[pos:]:
        if chunk.virtual_offset >= end:
            break
        lo = max(virtual, chunk.virtual_offset)
        hi = min(end, chunk.virtual_offset + chunk.size)
        if hi <= lo:
            continue
        if chunk.codec in (rds5.CODEC_STORED, rds5.CODEC_ZLIB):
            covered += hi - lo
        else:
            bcpack += hi - lo
    return covered, bcpack, max(0, length - covered - bcpack)


def read_virtual(path, index: rds5.TtpIndex, virtual: int, length: int,
                 fh=None, starts: list[int] | None = None) -> tuple[bytes, int, int]:
    """Assemble ``length`` bytes of virtual space.

    Returns ``(data, bcpack_bytes, uncovered_bytes)``.  BCPack chunks and gaps
    between chunks are left zero and counted, so callers can decide whether a
    texture is exportable.
    """
    out = bytearray(length)
    if length <= 0:
        return bytes(out), 0, 0
    if starts is None:
        starts = chunk_starts(index)
    end = virtual + length
    pos = max(0, bisect.bisect_right(starts, virtual) - 1)
    bcpack = covered = 0
    own = fh is None
    if own:
        fh = open(path, "rb")
    try:
        for chunk in index.chunks[pos:]:
            if chunk.virtual_offset >= end:
                break
            chunk_end = chunk.virtual_offset + chunk.size
            if chunk_end <= virtual:
                continue
            lo = max(virtual, chunk.virtual_offset)
            hi = min(end, chunk_end)
            if hi <= lo:
                continue
            if chunk.codec not in (rds5.CODEC_STORED, rds5.CODEC_ZLIB):
                bcpack += hi - lo
                continue
            fh.seek(chunk.source_offset)
            raw = fh.read(chunk.packed_size)
            if chunk.codec == rds5.CODEC_ZLIB:
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    raise ValueError(
                        f"chunk at 0x{chunk.source_offset:x} failed to inflate")
            if len(raw) < chunk.size:
                raise ValueError(
                    f"chunk at 0x{chunk.source_offset:x} is shorter than its virtual size")
            start = lo - chunk.virtual_offset
            out[lo - virtual:hi - virtual] = raw[start:start + hi - lo]
            covered += hi - lo
    finally:
        if own:
            fh.close()
    return bytes(out), bcpack, max(0, length - covered - bcpack)


def dds_header(width: int, height: int, mips: int, slices: int,
               dxgi_format: int, cube: bool = False) -> bytes:
    """DDS header (148 bytes) for a DX10 2D texture or 2D array."""
    _name, element_bytes, _block_pixels, is_bc = format_info(dxgi_format)
    if element_bytes == 0:
        raise ValueError(f"unsupported DXGI format {dxgi_format}")
    if is_bc:
        pitch = -(-width // 4) * element_bytes
        flags = 0xA1007
    else:
        pitch = width * element_bytes
        flags = 0x2100F
    caps = 0x1000 | (0x8 if slices > 1 else 0) | (0x400000 if mips > 1 else 0)
    caps2 = 0x200 | 0xFC00 if cube else 0
    misc = 4 if cube else 0
    out = bytearray()
    out += b"DDS " + struct.pack("<I", 124)
    out += struct.pack("<I", flags)
    out += struct.pack("<I", height) + struct.pack("<I", width)
    out += struct.pack("<I", pitch)
    out += struct.pack("<I", 0)              # depth
    out += struct.pack("<I", mips)
    out += b"\x00" * 44                      # reserved1
    out += struct.pack("<I", 32) + struct.pack("<I", 4)
    out += b"DX10" + b"\x00" * 20           # pixel format
    out += struct.pack("<I", caps)
    out += struct.pack("<I", caps2)          # cube faces when applicable
    out += b"\x00" * 12
    out += struct.pack("<I", dxgi_format)
    out += struct.pack("<I", 3)              # D3D10_RESOURCE_DIMENSION_TEXTURE2D
    out += struct.pack("<I", misc)           # D3D10_RESOURCE_MISC_TEXTURECUBE
    out += struct.pack("<I", slices)
    out += struct.pack("<I", 0)              # miscFlags2
    return bytes(out)


def dds_bytes(texture: rds5.TtpTexture, layout: gfx10.Layout,
              data: bytes) -> bytes:
    """Build a DDS file (header + untiled mips) for one TTPF texture."""
    width, height, mips, slices = (texture.width, texture.height,
                                   texture.mips, texture.slices)
    out = bytearray(dds_header(width, height, mips, slices, texture.dxgi_format,
                               cube=texture.is_cube))
    for mip in range(mips):
        for slice_index in range(slices):
            out += layout.untile_slice(data, mip, slice_index)
    return bytes(out)


def export_texture(path, index: rds5.TtpIndex, texture: rds5.TtpTexture,
                   out_dir: str, fh=None, starts: list[int] | None = None,
                   png: bool = False) -> dict:
    """Export one texture as ``<hash>.dds``; returns a manifest record."""
    result = {"file": None, "hash": f"{texture.hash:016x}",
              "width": texture.width, "height": texture.height,
              "format": format_name(texture.dxgi_format),
              "mips": texture.mips, "slices": texture.slices, "bytes": 0,
              "skipped": None}
    layout = layout_for(texture)
    if layout is None:
        result["skipped"] = "unsupported tile mode or element size"
        return result
    if layout.total > MAX_TEXTURE_BYTES:
        result["skipped"] = "texture exceeds the 64 MiB export limit"
        return result
    data, bcpack, uncovered = read_virtual(
        path, index, texture.virtual_offset, layout.total, fh=fh, starts=starts)
    if bcpack:
        result["skipped"] = f"{bcpack} bytes in BCPack chunks"
        return result
    if uncovered:
        result["skipped"] = f"{uncovered} bytes not covered by any chunk"
        return result
    blob = dds_bytes(texture, layout, data)
    dest = os.path.join(out_dir, f"{texture.hash:016x}.dds")
    with open(dest, "wb") as out:
        out.write(blob)
    result["file"] = dest
    result["bytes"] = len(blob)
    if png:
        from . import bcn, png as png_mod
        rgba = bcn.decode_rgba(texture.dxgi_format,
                               layout.untile_slice(data, 0, 0),
                               texture.width, texture.height)
        if rgba is None:
            result["png_skipped"] = "no PNG decoder for this format"
        else:
            png_dest = os.path.join(out_dir, f"{texture.hash:016x}.png")
            png_mod.write_png(png_dest, texture.width, texture.height, rgba)
            result["png"] = png_dest
            result["bytes"] += os.path.getsize(png_dest)
    return result
