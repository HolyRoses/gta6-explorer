"""AMD Gfx10 3D (``SW_4KB_S``) volumes, as used by three TTPF descriptors.

The layout is a single mip level; each 4 KiB tile interleaves x, y and z bits
with the pattern for the element size.  Only uncompressed formats are valid.
The rules here follow the measured TTPF 3D-volume layout: a 16x16x16 volume
tile for 1-byte elements, 16x8x16 for 2 bytes, 8x8x16 for 4, 8x8x8 for 8 and
8x4x8 for 16.
"""

from __future__ import annotations

from dataclasses import dataclass

TILE = 4096
PATTERNS = {
    0: (1, 2, 101, -1, 102, -2, 3, 103, -3, 4, 104, -4),
    1: (0, 1, 2, 101, -1, 102, 3, -2, 103, 4, -3, 104),
    2: (0, 0, 1, 2, 101, -1, 102, -2, 3, 103, -3, 104),
    3: (0, 0, 0, 1, 101, -1, 2, 102, -2, 3, 103, -3),
    4: (0, 0, 0, 0, 1, -1, 101, 2, -2, 102, 3, 103),
}
EXTENTS = {
    0: (16, 16, 16),
    1: (16, 8, 16),
    2: (8, 8, 16),
    3: (8, 8, 8),
    4: (8, 4, 8),
}
ELEMENT_LOG = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4}

__all__ = ["VolumeLayout", "layout_for"]


@dataclass
class VolumeLayout:
    width: int
    height: int
    depth: int
    bpe: int
    bw: int
    bh: int
    bd: int
    padded_w: int
    padded_h: int
    padded_d: int
    tile_stride: int
    total: int

    def addr(self, x: int, y: int, z: int) -> int:
        pattern = PATTERNS[ELEMENT_LOG[self.bpe]]
        z_base = (z // self.bd) * self.tile_stride
        z_in = 0
        for bit, source in enumerate(pattern):
            if source >= 101:
                z_in |= ((z >> (source - 101)) & 1) << bit
        tiles_x = self.padded_w // self.bw
        y_tile = (y // self.bh) * tiles_x
        y_in = z_in
        for bit, source in enumerate(pattern):
            if source < 0:
                y_in |= ((y >> (-source - 1)) & 1) << bit
        off = z_base + (y_tile + x // self.bw) * TILE + y_in
        for bit, source in enumerate(pattern):
            if 0 < source < 100:
                off |= ((x >> (source - 1)) & 1) << bit
        return off

    def untile(self, data: bytes) -> bytes:
        """Z-major linear bytes (x fastest, then y, then z)."""
        out = bytearray(self.width * self.height * self.depth * self.bpe)
        for z in range(self.depth):
            z_row = z * self.width * self.height * self.bpe
            for y in range(self.height):
                row = z_row + y * self.width * self.bpe
                for x in range(self.width):
                    at = self.addr(x, y, z)
                    if at + self.bpe <= len(data):
                        dst = row + x * self.bpe
                        out[dst:dst + self.bpe] = data[at:at + self.bpe]
        return bytes(out)


def layout_for(texture) -> VolumeLayout | None:
    """Volume layout for a TTPF descriptor, or ``None`` when unsupported."""
    if getattr(texture, "dimension", 1) != 3 or texture.mips != 1:
        return None
    from .texture import format_info
    _name, bpe, block_pixels, is_bc = format_info(texture.dxgi_format)
    if is_bc or block_pixels != 1 or bpe not in ELEMENT_LOG:
        return None
    bw, bh, bd = EXTENTS[ELEMENT_LOG[bpe]]
    pw = -(-texture.width // bw) * bw
    ph = -(-texture.height // bh) * bh
    pd = -(-texture.slices // bd) * bd
    stride = (pw // bw) * (ph // bh) * TILE
    return VolumeLayout(texture.width, texture.height, texture.slices, bpe,
                        bw, bh, bd, pw, ph, pd, stride, (pd // bd) * stride)
