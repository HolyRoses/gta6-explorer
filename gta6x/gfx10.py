"""AMD Gfx10 (RDNA2, Xbox Series) 2D texture layout, as used by TTPF pools.

This is a Python port of the parts of addrlib's
``Gfx10Lib::ComputeSurfaceInfoMacroTiled`` that place mips for thin 2D
surfaces, matching the layout used by ``data/ttdb/*.ttpf``.

* A swizzle mode is a 4 KiB or 64 KiB block with a fixed bit order of the
  element-coordinate x/y bits inside it; blocks are stored row-major.
* Mips are stored **smallest first**; mip 0 is last.
* Mips that fit in half a block (``w <= block_w / 2``, ``h <= block_h``) and are
  among the last ``max_mips_in_tail`` share one mip-tail block at offset 0, each
  at a fixed 2D origin derived from its tail offset.

Verified against the reference implementation on 512x512 BC1, 128x128 BC7 and
the array/cube spacing cases below (see ``__main__`` style asserts in
``gta6x selftest``).
"""

from __future__ import annotations

from dataclasses import dataclass

#: ``True`` = x coordinate bit, ``False`` = y coordinate bit.
_X = True
_Y = False

#: Element-coordinate bit order inside a block, low bit first.
_EQUATIONS: dict[tuple[str, int], tuple[tuple[bool, int], ...]] = {
    ("S4K", 16): ((_Y, 0), (_Y, 1), (_X, 0), (_X, 1), (_Y, 2), (_X, 2),
                  (_Y, 3), (_X, 3)),
    ("S4K", 8): ((_X, 0), (_Y, 0), (_Y, 1), (_X, 1), (_X, 2), (_Y, 2),
                 (_X, 3), (_Y, 3), (_X, 4)),
    ("D64K", 16): ((_X, 0), (_Y, 0), (_X, 1), (_Y, 1), (_Y, 2), (_X, 2),
                   (_Y, 3), (_X, 3), (_Y, 4), (_X, 4), (_Y, 5), (_X, 5)),
    ("D64K", 8): ((_X, 0), (_Y, 0), (_X, 1), (_X, 2), (_Y, 1), (_Y, 2),
                  (_X, 3), (_Y, 3), (_X, 4), (_Y, 4), (_X, 5), (_Y, 5),
                  (_X, 6)),
}

#: TTPF tile-mode values (descriptor d1 bits 24..27) and their swizzle.
TILE_MODES = {0: "D64K", 1: "S4K", 2: "S4K", 3: "S4K"}
CUBE_TILE_MODES = {9, 10, 11, 12}

__all__ = ["Layout", "MipPlace", "TILE_MODES", "CUBE_TILE_MODES", "element_bytes_ok"]


def _ceil(value: int, boundary: int) -> int:
    return (value + boundary - 1) // boundary


def element_bytes_ok(bpe: int) -> bool:
    """Only 8- and 16-byte elements (BC1-BC7) have a validated bit equation."""
    return bpe in (8, 16)


@dataclass
class MipPlace:
    """Where one mip lives inside a slice."""

    w: int                 # width in elements
    h: int                 # height in elements
    offset: int = 0        # byte offset of the mip's first block (non-tail)
    tail: tuple[int, int] | None = None  # origin inside the tail block, in elements


class Layout:
    """Byte layout of a 2D texture's full mip chain inside a pool slice."""

    def __init__(self, equation, bpe: int, block_w: int, block_h: int,
                 block_bytes: int, mips: list[MipPlace], slice_bytes: int) -> None:
        self.eq = equation
        self.bpe = bpe
        self.block_w = block_w
        self.block_h = block_h
        self.block_bytes = block_bytes
        self.mips = mips
        self.slices = 1
        self.slice_major = False
        self.slice_bytes = slice_bytes
        self.base = 0
        self.total = slice_bytes

    @classmethod
    def new(cls, swizzle: str, w: int, h: int, mips: int, bpe: int) -> Layout | None:
        """Build a layout for ``w`` x ``h`` elements (BCn blocks or pixels)."""
        equation = _EQUATIONS.get((swizzle, bpe))
        if equation is None or w < 1 or h < 1 or mips < 1:
            return None
        nx = sum(1 for is_x, _ in equation if is_x)
        block_w = 1 << nx
        block_h = 1 << (len(equation) - nx)
        block_bytes = block_w * block_h * bpe
        log2 = block_bytes.bit_length() - 1
        max_tail = 1 + (1 << (log2 - 9)) if log2 <= 11 else log2 - 4
        tail_w, tail_h = block_w // 2, block_h
        n = mips
        dims = [(max(1, w >> i), max(1, h >> i)) for i in range(n)]
        first = n
        for i, (mw, mh) in enumerate(dims):
            if mw <= tail_w and mh <= tail_h and n - i <= max_tail:
                first = i
                break
        place = [MipPlace(mw, mh) for mw, mh in dims]
        off = block_bytes if first < n else 0
        for i in range(first - 1, -1, -1):
            mw, mh = dims[i]
            place[i].offset = off
            off += _ceil(mw, block_w) * block_w * _ceil(mh, block_h) * block_h * bpe
        b256 = (4, 4) if bpe == 16 else (8, 4)
        for k in range(first, n):
            m = max_tail - 1 - (k - first)
            mo = 16 << m if m > 6 else m << 8
            mx = my = 0
            for b in range(6):
                mx |= ((mo >> (9 + 2 * b)) & 1) << b
                my |= ((mo >> (8 + 2 * b)) & 1) << b
            place[k].offset = 0
            place[k].tail = (mx * b256[0], my * b256[1])
        return cls(equation, bpe, block_w, block_h, block_bytes, place, off)

    def with_slices(self, count: int) -> Layout:
        """Array of ``count`` slices, stored level by level (smallest first)."""
        n = max(1, count)
        self.slices = n
        self.total = self.slice_bytes * n
        return self

    def level_bytes(self, m: int) -> int:
        place = self.mips[m]
        if place.tail is not None:
            return self.block_bytes
        return (_ceil(place.w, self.block_w) * self.block_w
                * _ceil(place.h, self.block_h) * self.block_h * self.bpe)

    def level_start(self, m: int, slice_index: int) -> int:
        if self.slice_major:
            off = 0 if self.mips[m].tail is not None else self.mips[m].offset
            return self.base + slice_index * self.slice_bytes + off
        base = 0 if self.mips[m].tail is not None else self.mips[m].offset * self.slices
        return base + slice_index * self.level_bytes(m)

    def inblock(self, x: int, y: int) -> int:
        address = 0
        for k, (is_x, bit) in enumerate(self.eq):
            value = x if is_x else y
            address |= ((value >> bit) & 1) << k
        return address

    def mip_span(self, m: int) -> tuple[int, int]:
        start = self.level_start(m, 0)
        return start, start + self.level_bytes(m)

    def addr(self, m: int, slice_index: int, x: int, y: int) -> int:
        place = self.mips[m]
        base = self.level_start(m, slice_index)
        if place.tail is not None:
            cx, cy = place.tail
            return base + self.inblock(x + cx, y + cy) * self.bpe
        pitch = _ceil(place.w, self.block_w)
        block = (y // self.block_h) * pitch + (x // self.block_w)
        return (base + block * self.block_bytes
                + self.inblock(x % self.block_w, y % self.block_h) * self.bpe)

    def untile_slice(self, src: bytes, m: int, slice_index: int = 0) -> bytes:
        place = self.mips[m]
        bpe = self.bpe
        out = bytearray(place.w * place.h * bpe)
        for y in range(place.h):
            for x in range(place.w):
                at = self.addr(m, slice_index, x, y)
                if 0 <= at <= len(src) - bpe:
                    dst = (y * place.w + x) * bpe
                    out[dst:dst + bpe] = src[at:at + bpe]
        return bytes(out)
