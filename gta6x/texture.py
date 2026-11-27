"""Texture catalog and DDS export for ``RDS5``/TTPF pools.

The ETPF dictionary inside every pool describes its textures (width, height,
mip count, DXGI format, AMD Gfx10 tile mode, array size, virtual address).  This
module turns those descriptors into:

* a layout (:mod:`gta6x.gfx10`) that maps (mip, slice, x, y) to a byte offset in
  the pool's *virtual* space,
* a virtual reader that reassembles a texture from the pool's stored/zlib
  chunks (BC1/BC3/BC4/BC5 and selected BC7 decode with ``decode_bcpack``),
* a standard DDS file writer, so the result opens in any DDS viewer.

Supported 2D/array/cubemap layouts handle 1/2/4/8/16-byte elements. Single-mip
uncompressed 3D layouts are handled by :mod:`gta6x.volume`. Unsupported formats,
tile profiles and missing BCPack entries are reported before export.
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
    11: ("R16G16B16A16_UNORM", 8, 1, False),
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
    31: ("R8G8B8A8_SNORM", 4, 1, False),
    32: ("R8G8B8A8_SINT", 4, 1, False),
    48: ("R8G8_TYPELESS", 2, 1, False),
    50: ("R8G8_UINT", 2, 1, False),
    51: ("R8G8_SNORM", 2, 1, False),
    52: ("R8G8_SINT", 2, 1, False),
    60: ("R8_TYPELESS", 1, 1, False),
    62: ("R8_UINT", 1, 1, False),
    63: ("R8_SNORM", 1, 1, False),
    64: ("R8_SINT", 1, 1, False),
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
    "dds_header", "dds_bytes", "preview_subresource", "export_texture",
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
        # The final cubemap snapshot is six complete slice-major faces, not
        # `tile_mode - 8` interleaved copies; cube_base is the final chunk.
        return layout.with_cube_copies(texture.slices, 1, texture.cube_base)
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
                 fh=None, starts: list[int] | None = None,
                 decode_bcpack: bool = False,
                 decode_errors: list[str] | None = None) -> tuple[bytes, int, int]:
    """Assemble ``length`` bytes of virtual space.

    Returns ``(data, bcpack_bytes, uncovered_bytes)``. With ``decode_bcpack``
    native BC1/3/4/5 and supported provisional BC7 chunks are expanded.
    Failed/unsupported chunks and gaps are counted as missing; exporters
    refuse to write these ranges.
    ``decode_errors`` optionally collects precise refusal reasons.
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
                if decode_bcpack and chunk.codec in (1, 3, 4, 5, 7):
                    from .bc import decode_bcpack as decode_chunk
                    fh.seek(chunk.source_offset)
                    packed = fh.read(chunk.packed_size)
                    try:
                        if len(packed) != chunk.packed_size:
                            raise ValueError("truncated packed range")
                        padding = getattr(chunk, "padding", 0)
                        tail = fh.read(padding)
                        if len(tail) != padding:
                            raise ValueError("truncated BCPack container padding")
                        if any(tail):
                            raise ValueError("non-zero BCPack container padding")
                        raw = decode_chunk(packed, chunk.codec, chunk.size)
                        if len(raw) != chunk.size:
                            raise ValueError("BCPack output size mismatch")
                    except (ValueError, IndexError) as exc:
                        if decode_errors is not None:
                            decode_errors.append(f"BCPack codec {chunk.codec} at "
                                                 f"0x{chunk.source_offset:x}: {exc}")
                        bcpack += hi - lo
                        continue
                    start = lo - chunk.virtual_offset
                    out[lo - virtual:hi - virtual] = raw[start:start + hi - lo]
                    covered += hi - lo
                    continue
                if decode_bcpack and decode_errors is not None:
                    decode_errors.append(f"BCPack codec {chunk.codec}: native codec unsupported")
                bcpack += hi - lo
                continue
            fh.seek(chunk.source_offset)
            raw = fh.read(chunk.packed_size)
            if len(raw) != chunk.packed_size:
                raise ValueError(
                    f"chunk at 0x{chunk.source_offset:x} has a truncated packed range")
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
    if cube and (type(slices) is not int or slices <= 0 or slices % 6):
        raise ValueError('DDS cubemap requires complete groups of six faces')
    if any(type(value) is not int or value <= 0 for value in (width, height, mips, slices)):
        raise ValueError('DDS dimensions and subresource counts must be positive integers')
    if is_bc:
        pitch = -(-width // 4) * -(-height // 4) * element_bytes
        flags = 0xA1007
    else:
        pitch = width * element_bytes
        flags = 0x2100F
    caps = 0x1000 | (0x8 if slices > 1 or mips > 1 else 0) | (0x400000 if mips > 1 else 0)
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
    out += struct.pack("<I", slices // 6 if cube else slices)
    out += struct.pack("<I", 0)              # miscFlags2
    return bytes(out)


def dds_header_volume(texture: rds5.TtpTexture) -> bytes:
    """DDS header (148 bytes) for an uncompressed 3D texture."""
    _name, element_bytes, _block_pixels, is_bc = format_info(texture.dxgi_format)
    if element_bytes == 0 or is_bc:
        raise ValueError("unsupported volume format")
    flags = 0x2100F | 0x800000     # DDSD_DEPTH
    pitch = texture.width * element_bytes
    caps = 0x1000 | 0x8
    out = bytearray()
    out += b"DDS " + struct.pack("<I", 124)
    out += struct.pack("<I", flags)
    out += struct.pack("<I", texture.height) + struct.pack("<I", texture.width)
    out += struct.pack("<I", pitch)
    out += struct.pack("<I", texture.slices)       # depth
    out += struct.pack("<I", 1)                    # one mip
    out += b"\x00" * 44
    out += struct.pack("<I", 32) + struct.pack("<I", 4)
    out += b"DX10" + b"\x00" * 20
    out += struct.pack("<I", caps)
    out += struct.pack("<I", 0x200000)              # DDSCAPS2_VOLUME
    out += b"\x00" * 12
    out += struct.pack("<I", texture.dxgi_format)
    out += struct.pack("<I", 4)                     # TEXTURE3D
    out += struct.pack("<I", 0)
    out += struct.pack("<I", 1)                     # array size
    out += struct.pack("<I", 0)
    return bytes(out)


def dds_bytes_volume(texture: rds5.TtpTexture, layout, data: bytes) -> bytes:
    if len(data) < layout.total:
        raise ValueError('truncated volume graphics allocation')
    return dds_header_volume(texture) + layout.untile(data)


def dds_bytes(texture: rds5.TtpTexture, layout: gfx10.Layout,
              data: bytes) -> bytes:
    """Build a DDS file (header + untiled mips) for one TTPF texture."""
    width, height, mips, slices = (texture.width, texture.height,
                                   texture.mips, texture.slices)
    out = bytearray(dds_header(width, height, mips, slices, texture.dxgi_format,
                               cube=texture.is_cube))
    # DDS serializes a complete mip chain per array element/cube face.
    # Source placement remains the existing pool-specific layout.
    for slice_index in range(slices):
        for mip in range(mips):
            linear, _width, _height, _metadata = preview_subresource(
                texture, layout, data, mip=mip, slice_index=slice_index)
            out += linear
    return bytes(out)


def _preview_selection(width, height, mips, slices, *, is_volume,
                       mip, slice_index, z_index):
    """Validate explicit selection before allocating its pixel/element buffer."""
    if any(type(value) is not int for value in (mip, slice_index, z_index)):
        raise ValueError('texture subresource indices must be integers')
    if any(type(value) is not int or value <= 0 for value in (width, height, mips, slices)):
        raise ValueError('invalid texture dimensions or subresource counts')
    if not 0 <= mip < mips:
        raise ValueError('texture mip index out of range')
    if is_volume:
        if mips != 1 or mip != 0:
            raise ValueError('volume subresource mip layout is not validated')
        if slice_index != 0:
            raise ValueError('volume subresource uses a Z index, not an array slice')
        if not 0 <= z_index < slices:
            raise ValueError('texture volume Z index out of range')
    else:
        if z_index != 0:
            raise ValueError('2D/array/cube subresource has no volume Z index')
        if not 0 <= slice_index < slices:
            raise ValueError('texture slice index out of range')
    w, h = max(1, width >> mip), max(1, height >> mip)
    metadata = {'png_z_index': z_index} if is_volume else {}
    if mip or slice_index or z_index:
        metadata.update(png_mip_index=mip, png_width=w, png_height=h)
        metadata['png_z_index' if is_volume else 'png_slice_index'] = z_index if is_volume else slice_index
    return w, h, metadata


def preview_subresource(texture: rds5.TtpTexture, layout, data: bytes, *,
                        mip: int = 0, slice_index: int = 0,
                        z_index: int = 0) -> tuple[bytes, int, int, dict]:
    """Return one bounded raw subresource and its logical preview dimensions.

    This shares the existing pool source placement with DDS serialization;
    it does not infer additional element extents. Cube slices remain numeric
    indices. A volume has only its validated mip0; its Z plane is separate
    from a 2D array slice. The entire tiled allocation must be present even
    when a small subresource is requested.
    """
    is_volume = getattr(texture, 'dimension', 1) == 3
    width, height, metadata = _preview_selection(
        texture.width, texture.height, texture.mips, texture.slices,
        is_volume=is_volume, mip=mip, slice_index=slice_index, z_index=z_index)
    if (type(layout.total) is not int or not 0 < layout.total <= MAX_TEXTURE_BYTES
            or len(data) < layout.total):
        raise ValueError('subresource requires the complete bounded texture allocation')
    _, element, block, _ = format_info(texture.dxgi_format)
    if element not in (1, 2, 4, 8, 16):
        raise ValueError('unsupported texture subresource element size')
    if layout.bpe != element:
        raise ValueError('subresource element size differs from its supplied layout')
    ew, eh = -(-width // block), -(-height // block)
    if not is_volume:
        if mip >= len(layout.mips) or slice_index >= layout.slices:
            raise ValueError('subresource selection exceeds its supplied layout')
        place = layout.mips[mip]
        if place.w < ew or place.h < eh:
            raise ValueError('texture logical mip grid exceeds its validated layout')
    size = ew * eh * element
    if size > layout.total:
        raise ValueError('texture subresource exceeds its allocation')
    out = bytearray(size)
    for y in range(eh):
        for x in range(ew):
            at = layout.addr(x, y, z_index) if is_volume else layout.addr(mip, slice_index, x, y)
            if not 0 <= at <= layout.total - element:
                raise ValueError('texture subresource address exceeds allocation')
            dst = (y * ew + x) * element
            out[dst:dst+element] = data[at:at+element]
    return bytes(out), width, height, metadata


def _export_preview(result, texture, layout, data, out_dir, mip, slice_index, z_index):
    from .bc import decode_rgba
    from .bc.bcn import preview_policy
    from . import png as png_mod
    try:
        linear, width, height, metadata = preview_subresource(
            texture, layout, data, mip=mip, slice_index=slice_index, z_index=z_index)
        rgba = decode_rgba(texture.dxgi_format, linear, width, height)
        if rgba is None:
            raise ValueError('no PNG decoder for this format')
    except ValueError as exc:
        result['png_skipped'] = str(exc)
        return
    suffix = f'_m{mip}_s{slice_index}_z{z_index}' if mip or slice_index or z_index else ''
    png_dest = os.path.join(out_dir, f'{texture.hash:016x}{suffix}.png')
    png_mod.write_png(png_dest, width, height, rgba)
    result.update(metadata)
    result['png'] = png_dest
    policy = preview_policy(texture.dxgi_format)
    if policy is not None:
        result['png_conversion'] = policy
    result['bytes'] += os.path.getsize(png_dest)


def _note_bc7_evidence(result, index, virtual, length, starts):
    positions = chunk_starts(index) if starts is None else starts
    at = max(0, bisect.bisect_right(positions, virtual)-1)
    for chunk in index.chunks[at:]:
        if chunk.virtual_offset >= virtual+length:
            break
        if chunk.codec == 7 and chunk.virtual_offset+chunk.size > virtual:
            result['bcpack_provisional'] = True
            result['bcpack_evidence'] = ('BC7 provisional observations; original block bytes '
                                        'unconfirmed; black-box PNG anchor behavior differs from stored BC7')
            break


def export_texture(path, index: rds5.TtpIndex, texture: rds5.TtpTexture,
                   out_dir: str, fh=None, starts: list[int] | None = None,
                   png: bool = False, decode_bcpack: bool = False,
                   png_mip: int = 0, png_slice: int = 0, png_z: int = 0) -> dict:
    """Export one texture as ``<hash>.dds``; returns a manifest record."""
    if not png and any(type(value) is not int or value != 0 for value in (png_mip, png_slice, png_z)):
        raise ValueError('PNG subresource selectors require png=True')
    result = {"file": None, "hash": f"{texture.hash:016x}",
              "width": texture.width, "height": texture.height,
              "format": format_name(texture.dxgi_format),
              "mips": texture.mips, "slices": texture.slices, "bytes": 0,
              "skipped": None}
    decode_errors = []
    if getattr(texture, "dimension", 1) == 3:
        from . import volume
        vol = volume.layout_for(texture)
        if vol is None:
            result["skipped"] = "unsupported 3D volume layout"
            return result
        if vol.total > MAX_TEXTURE_BYTES:
            result['skipped'] = 'volume exceeds the 64 MiB export limit'
            return result
        if decode_bcpack:
            _note_bc7_evidence(result,index,texture.virtual_offset,vol.total,starts)
        data, bcpack, uncovered = read_virtual(
            path, index, texture.virtual_offset, vol.total, fh=fh, starts=starts,
            decode_bcpack=decode_bcpack, decode_errors=decode_errors)
        if bcpack or uncovered:
            result["skipped"] = (f"{bcpack} bytes in BCPack chunks; " if bcpack else "") + \
                f"{uncovered} bytes uncovered in volume"
            if decode_errors:
                result["decode_errors"] = decode_errors
                result["skipped"] += ": " + decode_errors[0]
            return result
        blob = dds_bytes_volume(texture, vol, data)
        dest = os.path.join(out_dir, f"{texture.hash:016x}.dds")
        with open(dest, "wb") as out:
            out.write(blob)
        result.update({"file": dest, "bytes": len(blob), "volume": True,
                       "depth": texture.slices})
        if png:
            _export_preview(result, texture, vol, data, out_dir, png_mip, png_slice, png_z)
        return result
    layout = layout_for(texture)
    if layout is None:
        result["skipped"] = "unsupported tile mode or element size"
        return result
    if layout.total > MAX_TEXTURE_BYTES:
        result["skipped"] = "texture exceeds the 64 MiB export limit"
        return result
    if decode_bcpack:
        _note_bc7_evidence(result,index,texture.virtual_offset,layout.total,starts)
    data, bcpack, uncovered = read_virtual(
        path, index, texture.virtual_offset, layout.total, fh=fh, starts=starts,
        decode_bcpack=decode_bcpack, decode_errors=decode_errors)
    if bcpack:
        result["skipped"] = f"{bcpack} bytes in BCPack chunks"
        if decode_errors:
            result["decode_errors"] = decode_errors
            result["skipped"] += ": " + decode_errors[0]
        return result
    if uncovered:
        result["skipped"] = f"{uncovered} bytes not covered by any chunk"
        return result
    try:
        blob = dds_bytes(texture, layout, data)
    except ValueError as exc:
        result['skipped'] = str(exc)
        return result
    dest = os.path.join(out_dir, f"{texture.hash:016x}.dds")
    with open(dest, "wb") as out:
        out.write(blob)
    result["file"] = dest
    result["bytes"] = len(blob)
    if png:
        _export_preview(result, texture, layout, data, out_dir, png_mip, png_slice, png_z)
    return result
