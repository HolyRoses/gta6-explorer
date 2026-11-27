"""`RDS5` streaming resource pools (`data/ttdb/*.ttpf`).

GTA VI keeps its streamed textures in "TTDB" pools.  Each pool is an ``RDS5``
container that indexes independently stored or zlib-compressed chunks which
together form a *virtual* texture address space, plus an embedded ``ETPF``
texture dictionary describing how that space is sliced into mips.

Layout as verified
------------------

::

    +0x000  "RDS5"
    +0x004  u32   entry count          (chunks + 2 sentinels, >= 3)
    +0x008  u64   size word            bits 0..55 virtual size, bits 56..63 = 22
    +0x010  u32   ETPF offset / 256    also ceil(count / 32), +1 tolerated;
                                       legacy API name: bitmap_words
    +0x014  u32   alignment word       bits 28..31 * 256 = source padding,
                                       bits 0..27 must be zero
    +0x018  8 * (count - 1) bytes      chunk table, last entry is a sentinel
    ...     align 256                  "ETPF" texture dictionary (version 634)

Each 64-bit chunk-table entry packs a source range and a virtual range::

    bits  0..25   source offset / 256
    bits  26..29   codec (0 = stored, 8 = zlib)
    bits  30..51   virtual offset / 4096
    bits  52..63   padding bytes before the next chunk's source offset

The sentinel repeats the source length and the virtual size, which is what lets
a pool be validated without decoding a single texture.

Verified on all 46 pools of a local GTA VI package: header, bitmap word count,
alignment word, chunk table, sentinel and embedded ``ETPF`` agree every time.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, replace

from .rpf import entropy

RDS5_MAGIC = b"RDS5"
ETPF_MAGIC = b"ETPF"
ETPF_VERSION = 634
HEADER_SIZE = 24
TABLE_ALIGN = 256
PAGE_ALIGN = 4096
SIZE_WORD_VERSION = 22
SIZE_MASK = (1 << 56) - 1
ENTRY_SIZE = 8
MIN_ENTRIES = 3

CODEC_STORED = 0
CODEC_ZLIB = 8
#: Codecs 0 and 8 are plaintext; every other observed value (1, 5, 7) is a
#: BCPack block-compression profile that needs the console's decoder.
CODECS = {CODEC_STORED: "stored", CODEC_ZLIB: "zlib"}

__all__ = [
    "RDS5_MAGIC", "ETPF_MAGIC", "ETPF_VERSION", "TtpHeader", "TtpChunk",
    "TtpIndex", "read_header", "read_index", "describe",
]


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def _align(value: int, boundary: int) -> int:
    return (value + boundary - 1) // boundary * boundary


@dataclass(frozen=True)
class TtpHeader:
    """The 24-byte ``RDS5`` header, with every field named."""

    magic: bytes
    entry_count: int
    size_word: int
    bitmap_words: int
    alignment_word: int
    file_size: int

    @property
    def is_rds5(self) -> bool:
        return self.magic == RDS5_MAGIC

    @property
    def version(self) -> int:
        return self.size_word >> 56

    @property
    def virtual_size(self) -> int:
        return self.size_word & SIZE_MASK

    @property
    def source_padding(self) -> int:
        return (self.alignment_word >> 28) * 256

    @property
    def chunk_count(self) -> int:
        return max(0, self.entry_count - 2)

    @property
    def expected_bitmap_words(self) -> int:
        return (self.entry_count + 31) // 32

    @property
    def dwords(self) -> tuple[int, ...]:
        """The six raw little-endian dwords, kept for compatibility."""
        return (
            self.entry_count,
            self.size_word & 0xFFFFFFFF,
            self.size_word >> 32,
            self.bitmap_words,
            self.alignment_word,
            0,
        )

    def as_dict(self) -> dict:
        return {
            "magic": self.magic.decode("latin1"),
            "file_size": self.file_size,
            "entry_count": self.entry_count,
            "chunk_count": self.chunk_count,
            "version": self.version,
            "virtual_size": self.virtual_size,
            "bitmap_words": self.bitmap_words,
            "alignment_word": f"0x{self.alignment_word:08X}",
            "source_padding": self.source_padding,
            "version_ok": self.version == SIZE_WORD_VERSION,
        }


@dataclass(frozen=True)
class TtpChunk:
    """One entry of the ``RDS5`` chunk table."""

    index: int
    packed: int
    source_offset: int
    virtual_offset: int
    size: int
    packed_size: int
    codec: int
    padding: int

    @property
    def source_end(self) -> int:
        return self.source_offset + self.packed_size

    @property
    def virtual_end(self) -> int:
        return self.virtual_offset + self.size

    @property
    def kind(self) -> str:
        return CODECS.get(self.codec, "bcpack")

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "kind": self.kind,
            "codec": self.codec,
            "source_offset": self.source_offset,
            "virtual_offset": self.virtual_offset,
            "packed": self.packed_size,
            "size": self.size,
            "padding": self.padding,
        }


@dataclass(frozen=True)
class TtpTexture:
    """One ETPF texture descriptor."""

    index: int
    hash: int
    d0: int
    d1: int
    loc: int
    width: int
    height: int
    mips: int
    dxgi_format: int
    tile_mode: int
    slices: int
    cube_base: int | None = None
    dimension: int = 1
    non_tail: int = 0

    @property
    def virtual_offset(self) -> int:
        """First 4 KiB page of the texture, counted from the pool start."""
        return (self.loc & 0x1FFFFF) * 0x1000

    @property
    def is_cube(self) -> bool:
        return self.tile_mode in (9, 10, 11, 12)

    @property
    def name(self) -> str:
        return f"{self.hash:016x}"

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "hash": f"0x{self.hash:016x}",
            "width": self.width,
            "height": self.height,
            "mips": self.mips,
            "dxgi_format": self.dxgi_format,
            "tile_mode": self.tile_mode,
            "slices": self.slices,
            "dimension": self.dimension,
            "non_tail": self.non_tail,
            "virtual_offset": self.virtual_offset,
            "cube": self.is_cube,
            "cube_base": self.cube_base,
        }


@dataclass(frozen=True)
class TtpIndex:
    """A parsed and validated pool index."""

    header: TtpHeader
    chunks: tuple[TtpChunk, ...]
    etpf_offset: int
    etpf_version: int
    texture_count: int
    metadata_area: int
    problems: tuple[str, ...] = ()
    textures: tuple[TtpTexture, ...] = ()

    @property
    def validated(self) -> bool:
        return not self.problems

    def as_dict(self) -> dict:
        out = self.header.as_dict()
        out["chunks"] = [c.as_dict() for c in self.chunks]
        out["etpf"] = {
            "offset": self.etpf_offset,
            "version": self.etpf_version,
            "textures": self.texture_count,
            "area_bytes": self.metadata_area,
        }
        out["validated"] = self.validated
        out["problems"] = list(self.problems)
        out["texture_index"] = [t.as_dict() for t in self.textures[:8]]
        return out


def read_header(path: str | os.PathLike) -> TtpHeader:
    with open(path, "rb") as fh:
        raw = fh.read(HEADER_SIZE)
    if len(raw) < HEADER_SIZE:
        raise ValueError(f"{path}: too short for an RDS5 header")
    if raw[:4] != RDS5_MAGIC:
        raise ValueError(f"{path}: not an RDS5 container")
    count = _u32(raw, 4)
    size_word = struct.unpack_from("<Q", raw, 8)[0]
    bitmap = _u32(raw, 16)
    alignment = _u32(raw, 20)
    return TtpHeader(RDS5_MAGIC, count, size_word, bitmap, alignment,
                     os.path.getsize(path))


def read_index(path: str | os.PathLike) -> TtpIndex:
    """Parse the full pool index and collect any rule violations."""
    header = read_header(path)
    problems: list[str] = []
    file_size = header.file_size

    if header.entry_count < MIN_ENTRIES:
        problems.append(f"entry count {header.entry_count} < {MIN_ENTRIES}")
    if header.version != SIZE_WORD_VERSION:
        problems.append(f"size-word version {header.version} != {SIZE_WORD_VERSION}")
    if not 4096 <= header.virtual_size <= 1 << 34:
        problems.append(f"virtual size {header.virtual_size} out of range")
    if header.bitmap_words not in (header.expected_bitmap_words,
                                   header.expected_bitmap_words + 1):
        problems.append(
            f"bitmap words {header.bitmap_words} != {header.expected_bitmap_words}")
    if header.alignment_word & 0x0FFFFFFF:
        problems.append("alignment word low 28 bits are not zero")

    table_end = HEADER_SIZE + (header.entry_count - 1) * ENTRY_SIZE
    etpf_at = _align(table_end, TABLE_ALIGN)
    with open(path, "rb") as fh:
        fh.seek(HEADER_SIZE)
        table = fh.read(max(0, (header.entry_count - 1) * ENTRY_SIZE))
        fh.seek(etpf_at)
        etpf = fh.read(16)

    if len(table) != (header.entry_count - 1) * ENTRY_SIZE:
        problems.append("chunk table is truncated")
        return TtpIndex(header, (), etpf_at, 0, 0, 0, tuple(problems))

    sentinel = int.from_bytes(table[-ENTRY_SIZE:], "little")
    sentinel_source = (sentinel & 0x3FFFFFF) * 256
    sentinel_virtual = ((sentinel >> 30) & 0x3FFFFF) * 4096
    if sentinel_source != file_size:
        problems.append(
            f"sentinel source {sentinel_source} != file size {file_size}")
    if sentinel_virtual != header.virtual_size:
        problems.append(
            f"sentinel virtual {sentinel_virtual} != virtual size {header.virtual_size}")

    etpf_version = texture_count = area = 0
    if etpf[:4] != ETPF_MAGIC:
        problems.append(f"no ETPF dictionary at 0x{etpf_at:x}")
    else:
        etpf_version = _u32(etpf, 4)
        texture_count = _u32(etpf, 8)
        area = _u32(etpf, 12)
        if etpf_version != ETPF_VERSION:
            problems.append(f"ETPF version {etpf_version} != {ETPF_VERSION}")
        if texture_count < 1:
            problems.append("ETPF declares no textures")
        if area < texture_count * 16:
            problems.append("ETPF record area is smaller than its texture count")

    textures: list[TtpTexture] = []
    if texture_count and etpf_at + 16 + 16 * texture_count <= file_size:
        with open(path, "rb") as fh:
            fh.seek(etpf_at + 16)
            meta = fh.read(16 * texture_count + 8 * texture_count)
        if len(meta) >= 16 * texture_count + 8 * texture_count:
            for i in range(texture_count):
                d0, d1, loc = struct.unpack_from("<IIQ", meta, i * 16)
                hashes_at = 16 * texture_count + i * 8
                texture_hash = int.from_bytes(meta[hashes_at:hashes_at + 8], "little")
                width = (d0 & 0x3FFF) + 1
                height = ((d0 >> 14) & 0x3FFF) + 1
                tile_mode = (d1 >> 24) & 0xF
                non_tail = d1 & 7
                mips = max(1, (d0 >> 28) + non_tail)
                slices = ((d1 >> 10) & 0x7FF) + 1
                dimension = (d1 >> 21) & 3
                if not (1 <= width <= 16384 and 1 <= height <= 16384
                        and 1 <= mips <= 32 and 1 <= slices <= 2048
                        and 1 <= dimension <= 3):
                    problems.append(f"texture {i} has out-of-range dimensions")
                    continue
                textures.append(TtpTexture(
                    i, texture_hash, d0, d1, loc, width, height, mips,
                    (d1 >> 3) & 0x7F, tile_mode, slices,
                    dimension=dimension, non_tail=non_tail))

    chunks: list[TtpChunk] = []
    previous_source = previous_virtual = -1
    for i in range(header.chunk_count):
        value = int.from_bytes(table[i * ENTRY_SIZE:(i + 1) * ENTRY_SIZE], "little")
        nxt = int.from_bytes(table[(i + 1) * ENTRY_SIZE:(i + 2) * ENTRY_SIZE], "little")
        start = (value & 0x3FFFFFF) * 256
        end = (nxt & 0x3FFFFFF) * 256
        virtual = ((value >> 30) & 0x3FFFFF) * 4096
        virtual_end = ((nxt >> 30) & 0x3FFFFF) * 4096
        padding = value >> 52
        codec = (value >> 26) & 0xF
        packed = end - start - padding
        size = virtual_end - virtual
        if start < previous_source or virtual < previous_virtual:
            problems.append(f"chunk {i} is not ordered")
        if end > file_size or start < 0:
            problems.append(f"chunk {i} source range leaves the file")
        if packed < 1 or size < 1:
            problems.append(f"chunk {i} has a non-positive length")
        if codec == CODEC_STORED and packed != size:
            problems.append(f"chunk {i} is stored but packed {packed} != size {size}")
        previous_source, previous_virtual = start, virtual
        chunks.append(TtpChunk(i, value, start, virtual, size, packed, codec, padding))

    if chunks and textures:
        by_virtual = {chunk.virtual_offset: i for i, chunk in enumerate(chunks)}
        updated: list[TtpTexture] = []
        for texture in textures:
            base = None
            if texture.is_cube:
                index = by_virtual.get(texture.virtual_offset)
                copies = texture.tile_mode - 8
                if index is not None and index + copies - 1 < len(chunks):
                    base = (chunks[index + copies - 1].virtual_offset
                            - texture.virtual_offset)
            updated.append(replace(texture, cube_base=base)
                           if base is not None else texture)
        textures = updated

    if chunks:
        metadata_bytes = 16 + area + texture_count * 32
        padded_metadata = _align(metadata_bytes, PAGE_ALIGN)
        if chunks[0].virtual_offset != padded_metadata:
            problems.append("first chunk virtual offset != padded ETPF metadata")
        expected_source = etpf_at + padded_metadata + header.source_padding
        if chunks[0].source_offset != expected_source:
            problems.append("first chunk source offset != ETPF boundary + padding")

    return TtpIndex(header, tuple(chunks), etpf_at, etpf_version,
                    texture_count, area, tuple(problems), tuple(textures))


def describe(path: str | os.PathLike) -> dict:
    """Named summary used by ``gta6x resources``."""
    index = read_index(path)
    header = index.header
    codecs: dict[str, int] = {}
    for chunk in index.chunks:
        codecs[chunk.kind] = codecs.get(chunk.kind, 0) + 1
    data_at = index.chunks[0].source_offset if index.chunks else HEADER_SIZE
    try:
        payload_entropy = round(_entropy_at(path, data_at), 3)
    except OSError:
        payload_entropy = 0.0
    out = header.as_dict()
    out.update({
        "name": os.path.basename(path),
        "chunks": codecs,
        "packed_bytes": sum(c.packed_size for c in index.chunks),
        "virtual_bytes": sum(c.size for c in index.chunks),
        "etpf": {
            "offset": index.etpf_offset,
            "version": index.etpf_version,
            "textures": index.texture_count,
            "area_bytes": index.metadata_area,
        },
        "validated": index.validated,
        "problems": list(index.problems),
        "payload_entropy": payload_entropy,
        "dwords": header.dwords,
    })
    return out


def _entropy_at(path: str | os.PathLike, offset: int, length: int = 65536) -> float:
    with open(path, "rb") as fh:
        fh.seek(offset)
        return entropy(fh.read(length))
