"""Bounded offline inspection of tightly packed DX10 and legacy BC DDS files.

This reads serialized linear DDS subresources, not game tiling or allocations.
Layouts are exact; unsupported headers, padding, formats and previews refuse.
No game archive is reopened and no file is written by this module.
"""
from __future__ import annotations

import hashlib
import struct

from . import png, texture
from .bc import decode_rgba
from .bc.bcn import preview_policy

HEADER_BYTES = 148
LEGACY_HEADER_BYTES = 128
MAX_BYTES = 64 * 1024 * 1024 + HEADER_BYTES
MAX_SUBRESOURCES = 65536
MAX_PIXELS = 16 * 1024 * 1024
_CUBE_FACES = ('positive_x', 'negative_x', 'positive_y', 'negative_y', 'positive_z', 'negative_z')
_TYPELESS = {27, 48, 60, 70, 73, 76, 79, 82, 90, 94, 97}
# Public Microsoft DDS format mappings; unsupported aliases are not guessed.
_LEGACY_FORMATS = {b'DXT1': 71, b'DXT3': 74, b'DXT5': 77,
                   b'BC4U': 80, b'BC4S': 81, b'ATI2': 83, b'BC5S': 84}


def _limit(value, maximum, name):
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError(f'{name} must be an integer from 1 to {maximum}')


def _selectors(mip, slice_index, z_index, max_pixels):
    _limit(max_pixels, MAX_PIXELS, 'DDS preview pixel limit')
    if any(type(value) is not int or value < 0 for value in (mip, slice_index, z_index)):
        raise ValueError('DDS mip, slice and depth-plane selectors must be nonnegative integers')


def _read(path, max_bytes):
    _limit(max_bytes, MAX_BYTES, 'DDS input byte limit')
    with open(path, 'rb') as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('DDS file exceeds input byte limit')
    return data


def inspect(data, *, max_bytes=MAX_BYTES, max_subresources=MAX_SUBRESOURCES):
    """Return a complete source-backed DDS layout, or raise ValueError.

    The supported profile has tightly packed known-size formats, explicit mip
    counts, 2D arrays/cubemaps or uncompressed 3D textures, and no trailing bytes.
    A volume mip is one subresource containing consecutive depth planes. Legacy
    input supports only documented BC FourCCs, 2D textures and complete cubes.
    """
    _limit(max_bytes, MAX_BYTES, 'DDS input byte limit')
    _limit(max_subresources, MAX_SUBRESOURCES, 'DDS subresource limit')
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError('DDS source must be bounded bytes')
    if len(data) > max_bytes:
        raise ValueError('DDS source exceeds input byte limit')
    data = bytes(data)
    if len(data) < LEGACY_HEADER_BYTES or data[:4] != b'DDS ':
        raise ValueError('DDS source requires the complete base header')
    h = struct.unpack_from('<31I', data, 4)
    if h[0] != 124 or h[18] != 32:
        raise ValueError('DDS header or pixel-format size is invalid')
    if h[19] != 4 or any(h[21:26]):
        raise ValueError('unsupported DDS pixel-format profile; FourCC without legacy masks is required')
    fourcc = data[84:88]
    legacy = fourcc != b'DX10'
    if legacy:
        if fourcc in (b'DXT2', b'DXT4'):
            raise ValueError('unsupported DDS premultiplied-alpha FourCC; DXT2/DXT4 are not reinterpreted')
        if fourcc not in _LEGACY_FORMATS:
            raise ValueError('unsupported DDS legacy FourCC')
        fmt = _LEGACY_FORMATS[fourcc]
        dimension, misc, arrays, alpha = 3, (4 if h[27] & 0x200 else 0), 1, 0
        header_bytes = LEGACY_HEADER_BYTES
        dx10_words = None
        # Legacy does not encode the DX10 alpha-mode extension. DXT3/5 are
        # straight-alpha formats, but this absent field remains unspecified.
    else:
        if len(data) < HEADER_BYTES:
            raise ValueError('DDS source requires the complete DX10 header')
        fmt, dimension, misc, arrays, alpha = struct.unpack_from('<5I', data, 128)
        header_bytes = HEADER_BYTES
        dx10_words = [fmt, dimension, misc, arrays, alpha]
    name, element, block, compressed = texture.format_info(fmt)
    if not element:
        raise ValueError(f'unsupported DDS DXGI format {fmt}')
    if dimension not in (3, 4):
        raise ValueError('unsupported DDS resource dimension; only 2D and 3D are supported')
    if misc & ~4 or alpha & ~7:
        raise ValueError('unsupported DDS extension flags')
    flags, height, width, pitch, raw_depth, mips = h[1:7]
    if legacy and h[26] & ~0x401008:
        raise ValueError('unsupported legacy DDS surface caps')
    if legacy and mips == 0 and not flags & 0x20000 and not h[26] & 0x400000:
        # The public legacy header leaves mipMapCount unused for one level.
        # Do not repair zero when a mip chain is explicitly declared.
        mips = 1
    if flags & ~0x8a100f:
        raise ValueError('unsupported DDS header flags')
    if width < 1 or height < 1 or mips < 1 or arrays < 1:
        raise ValueError('DDS dimensions, array size and explicit mip count must be positive')
    # Deliberately narrower than a tolerant general-purpose DDS loader: native
    # writers supply these declarations. Missing advisory flags in some other
    # writers are unsupported here rather than silently repaired.
    if (flags & 0x1007) != 0x1007 or not h[26] & 0x1000:
        raise ValueError('unsupported DDS profile; required texture declarations are missing')
    if mips > 1 and (not flags & 0x20000 or not h[26] & 0x400000):
        raise ValueError('unsupported DDS profile; mip declarations are incomplete')
    cube = bool(misc & 4)
    volume = dimension == 4
    if volume:
        if cube or arrays != 1 or compressed or raw_depth < 1:
            raise ValueError('unsupported DDS volume profile; requires one uncompressed non-cube array element')
        if not flags & 0x800000 or h[27] != 0x200000:
            raise ValueError('DDS volume depth declarations disagree')
        depth, slices = raw_depth, 1
    else:
        if raw_depth not in (0, 1) or flags & 0x800000:
            raise ValueError('DDS 2D texture has conflicting volume declarations')
        if cube and (width != height or h[27] != 0xfe00):
            raise ValueError('DDS cube requires square complete faces and matching declarations')
        if not cube and h[27]:
            raise ValueError('unsupported DDS non-cube surface flags')
        depth, slices = 1, arrays * (6 if cube else 1)
    if (slices > 1 or mips > 1 or volume) and not h[26] & 8:
        raise ValueError('unsupported DDS profile; multiple surfaces require complex caps')
    if mips > max(width, height, depth).bit_length():
        raise ValueError('DDS mip count exceeds the dimension chain')
    if slices * mips > max_subresources:
        raise ValueError('DDS subresource count exceeds its limit')
    row_pitch = ((width + 3) // 4 if compressed else width) * element
    top_bytes = row_pitch * ((height + 3) // 4 if compressed else height)
    if compressed:
        if (flags & 0x80008) != 0x80000 or pitch != top_bytes:
            raise ValueError('DDS compressed top-level linear size is inconsistent')
    elif (flags & 0x80008) != 8 or pitch != row_pitch:
        raise ValueError('unsupported DDS row pitch; tightly packed uncompressed rows are required')
    rows = []
    at = header_bytes
    for layer in range(slices):
        for mip in range(mips):
            w, ht = max(1, width >> mip), max(1, height >> mip)
            dep = max(1, depth >> mip) if volume else 1
            stride = ((w + block - 1) // block) * element
            plane = stride * ((ht + block - 1) // block)
            length = plane * dep
            if at > len(data) - length:
                raise ValueError('DDS subresource payload is truncated')
            row = dict(index=len(rows), mip_index=mip, slice_index=layer,
                       width=w, height=ht, depth=dep, row_pitch=stride,
                       plane_byte_length=plane, data_offset=at, byte_length=length)
            if cube:
                row.update(cube_index=layer // 6, cube_face=_CUBE_FACES[layer % 6])
            rows.append(row)
            at += length
    if at != len(data):
        detail = '; only DX10 permits an extended header' if legacy else ''
        raise ValueError('DDS payload has trailing bytes outside the declared exact layout' + detail)
    report = dict(format='gta6x-dds-inspection-v1', status='complete',
        source=dict(byte_length=len(data), sha256=hashlib.sha256(data).hexdigest()),
        width=width, height=height, depth=depth, mip_count=mips, slice_count=slices,
        array_size=arrays, cube=cube, resource_dimension=dimension, dxgi_format=fmt,
        format_name=name, block_compressed=compressed, element_bytes=element,
        block_pixels=block, alpha_mode_code=alpha, header_words=list(h),
        dx10_words=dx10_words, header_bytes=header_bytes,
        payload_bytes=len(data)-header_bytes, subresource_count=len(rows), subresources=rows,
        preview_format_supported=fmt not in _TYPELESS and fmt != 65,
        interpretation='serialized linear DDS layout only; no game tiling, allocation, orientation or semantic ownership claim')
    if legacy:
        report.update(header_kind='legacy_fourcc', legacy_fourcc=fourcc.decode('ascii'),
            raw_mip_count=h[6],
            alpha_interpretation=('straight alpha' if fourcc in (b'DXT3', b'DXT5') else
                                  'BC1 block alpha' if fourcc == b'DXT1' else 'no alpha channel'),
            format_mapping='documented legacy FourCC to DXGI equivalent; no sRGB inference')
    return report


def inspect_file(path, *, max_bytes=MAX_BYTES, max_subresources=MAX_SUBRESOURCES):
    """Read a bounded file once and inspect those exact immutable bytes."""
    _limit(max_subresources, MAX_SUBRESOURCES, 'DDS subresource limit')
    return inspect(_read(path, max_bytes), max_bytes=max_bytes, max_subresources=max_subresources)


def preview(data, *, mip=0, slice_index=0, z_index=0, max_bytes=MAX_BYTES,
            max_subresources=MAX_SUBRESOURCES, max_pixels=MAX_PIXELS):
    """Return (inspection report, PNG bytes) for one exact selected plane.

    Metadata is always regenerated from supplied bytes. No caller-modified span
    table can authorize pixels. Existing BCn display conventions are retained;
    typeless formats and the unimplemented A8 display view refuse explicitly.
    """
    _selectors(mip, slice_index, z_index, max_pixels)
    _limit(max_bytes, MAX_BYTES, 'DDS input byte limit')
    if isinstance(data, bytearray):
        if len(data) > max_bytes:
            raise ValueError('DDS source exceeds input byte limit')
        data = bytes(data)
    report = inspect(data, max_bytes=max_bytes, max_subresources=max_subresources)
    if mip >= report['mip_count'] or slice_index >= report['slice_count']:
        raise ValueError('DDS preview mip or slice exceeds its declared range')
    row = report['subresources'][slice_index * report['mip_count'] + mip]
    if z_index >= row['depth']:
        raise ValueError('DDS preview depth plane exceeds the selected mip')
    if row['width'] * row['height'] > max_pixels:
        raise ValueError('DDS preview exceeds pixel limit')
    if not report['preview_format_supported']:
        raise ValueError('DDS format has no supported typed offline preview; layout inspection remains available')
    at = row['data_offset'] + z_index * row['plane_byte_length']
    linear = data[at:at + row['plane_byte_length']]
    rgba = decode_rgba(report['dxgi_format'], linear, row['width'], row['height'])
    if rgba is None or len(rgba) != row['width'] * row['height'] * 4:
        raise ValueError('DDS format has no complete RGBA8 preview decoder')
    image = png.png_bytes(row['width'], row['height'], rgba)
    policy = preview_policy(report['dxgi_format'])
    report['preview'] = dict(mip_index=mip, slice_index=slice_index, z_index=z_index,
        width=row['width'], height=row['height'], data_offset=at, byte_length=len(linear),
        linear_sha256=hashlib.sha256(linear).hexdigest(), rgba_sha256=hashlib.sha256(rgba).hexdigest(),
        png_sha256=hashlib.sha256(image).hexdigest(), conversion=policy,
        interpretation='existing typed RGBA8 preview conventions; no inferred orientation, gamma correction or alpha unpremultiplication')
    return report, image


def preview_file(path, *, mip=0, slice_index=0, z_index=0, max_bytes=MAX_BYTES,
                 max_subresources=MAX_SUBRESOURCES, max_pixels=MAX_PIXELS):
    """Read once, validate the full file, then create a selected PNG in memory."""
    _selectors(mip, slice_index, z_index, max_pixels)
    _limit(max_subresources, MAX_SUBRESOURCES, 'DDS subresource limit')
    return preview(_read(path, max_bytes), mip=mip, slice_index=slice_index, z_index=z_index,
                   max_bytes=max_bytes, max_subresources=max_subresources, max_pixels=max_pixels)
