"""RPF9 container introspection (read-only).

Only what can be *verified* from the bytes is implemented here: the plaintext
32-byte header, the invariant build stamp, the constant 32-byte block, and
heuristics that describe the encrypted index honestly -- this module never
claims to decrypt anything.

What the header tells us (measured on all 22 archives of 1.0.2.1)
----------------------------------------------------------------
* ``f1`` (0x04) is the **index size**: the payload area begins exactly at
  ``f1``.  Verified 22/22: 15 archives have zero padding immediately after
  ``f1``; the other 7 have resource bytes starting there directly.  The first
  resource may sit further in (``movies.rpf`` has ``f1 = 0x6AC0`` and its first
  KB2 at 0x7000), so ``f1`` is the end of the index, not the offset of any
  particular entry.
* ``f2`` (0x08) and ``f3`` (0x0c) are still unidentified.  Both are 16-byte
  multiples and sum consistently with the plaintext size of a name table and an
  entry table (``f3 / 16`` gives plausible entry counts for every archive), so
  the working hypothesis is *uncompressed name- and entry-table sizes*; it
  cannot be confirmed without the index key.
* ``h1``/``h2`` (0x10/0x14) vary per archive and are most likely a double-word
  index hash, used to validate decryption.
* ``stamp`` (0x18) is invariant (``0x00047A00``), ``f4`` (0x1c) is invariant
  (336) -- both are set fingerprint, not per-archive data.
* 0x20..0x40 holds a small per-archive structure (two u16 version/feature words,
  a 29-bit counter, a per-archive dword, a format word ``0x00090F01/02`` and the
  dword ``16``), then **32 invariant bytes at 0x40** shared by every archive.

Nested archives
---------------
`9FPR` headers also occur inside an archive's data area (e.g. ``anim.rpf`` at
0x5000 and 0x7000), each followed by the same 32-byte invariant block.  They
are nested RPF9 archives, not extra archive headers; their ``f1`` is their own
index size.  Nothing here decrypts them either.
"""

from __future__ import annotations

import math
import os
import struct
from collections import Counter
from dataclasses import dataclass

RPF9_MAGIC = 0x52504639
RPF7_MAGIC = 0x52504637
HEADER_SIZE = 32
TOC_OFFSET = 0x40
GAP_PROBE = 1 << 20      # how far to look for zero padding after the index
BUILD_STAMP = 0x00047A00

#: 32 ciphertext bytes found at 0x40 in *every* archive and nested archive.
CONSTANT_TOC_BLOCK = bytes.fromhex(
    "5f08daabecbdd40258c3516807024c24"
    "fb9f756755ef4be458785bfed8aa6989"
)

__all__ = [
    "RPF9_MAGIC", "RPF7_MAGIC", "HEADER_SIZE", "TOC_OFFSET", "GAP_PROBE",
    "BUILD_STAMP", "CONSTANT_TOC_BLOCK", "Header", "read_header",
    "constant_block", "has_constant_block", "entropy", "entropy_at",
    "toc_word_plausibility", "toc_entry_plausibility", "looks_encrypted",
    "index_gap", "describe",
]


@dataclass(frozen=True)
class Header:
    """The 32 plaintext bytes at the start of an RPF9 archive.

    ``f1`` is named (index size); the remaining fields keep their measured
    names because their meaning is not established.
    """

    magic: int
    f1: int
    f2: int
    f3: int
    h1: int
    h2: int
    stamp: int
    f4: int
    file_size: int = 0

    @property
    def is_rpf9(self) -> bool:
        return self.magic == RPF9_MAGIC

    @property
    def revision(self) -> str:
        return "RPF9" if self.is_rpf9 else f"0x{self.magic:08X}"

    @property
    def stamp_ok(self) -> bool:
        """True when the invariant build stamp is present."""
        return self.stamp == BUILD_STAMP

    @property
    def on_disk_magic(self) -> bytes:
        return struct.pack("<I", self.magic)

    @property
    def index_size(self) -> int:
        """``f1``: bytes occupied by the encrypted index, from offset 0."""
        return self.f1

    @property
    def data_offset(self) -> int:
        """First byte after the index -- the payload area starts here."""
        return self.f1

    @property
    def index_region_ok(self) -> bool:
        return 0 < self.f1 <= self.file_size

    def as_dict(self) -> dict:
        return {
            "revision": self.revision,
            "magic": f"0x{self.magic:08X}",
            "on_disk_magic": self.on_disk_magic.decode("latin1"),
            "index_size": self.index_size,
            "data_offset": self.data_offset,
            "field_08": self.f2,
            "field_0c": self.f3,
            "f1": self.f1,
            "f2": self.f2,
            "f3": self.f3,
            "h1": f"0x{self.h1:08X}",
            "h2": f"0x{self.h2:08X}",
            "stamp": self.stamp,
            "stamp_ok": self.stamp_ok,
            "f4": self.f4,
            "file_size": self.file_size,
        }


def read_header(path: str | os.PathLike) -> Header:
    """Parse the plaintext header. Raises ValueError on a short or foreign file."""
    with open(path, "rb") as fh:
        raw = fh.read(HEADER_SIZE)
    if len(raw) < HEADER_SIZE:
        raise ValueError(f"{path}: too short for an RPF9 header ({len(raw)} bytes)")
    magic, f1, f2, f3, h1, h2, stamp, f4 = struct.unpack("<8I", raw)
    return Header(magic, f1, f2, f3, h1, h2, stamp, f4, os.path.getsize(path))


def constant_block(path: str | os.PathLike) -> bytes:
    """The 32 bytes at 0x40 (identical in every archive and nested archive)."""
    with open(path, "rb") as fh:
        fh.seek(TOC_OFFSET)
        return fh.read(len(CONSTANT_TOC_BLOCK))


def has_constant_block(path: str | os.PathLike) -> bool:
    return constant_block(path) == CONSTANT_TOC_BLOCK


def entropy(data: bytes) -> float:
    """Shannon entropy in bits per byte (0..8)."""
    if not data:
        return 0.0
    total = len(data)
    return -sum((n / total) * math.log2(n / total) for n in Counter(data).values())


def entropy_at(path: str | os.PathLike, offset: int, length: int = 65536) -> float:
    with open(path, "rb") as fh:
        fh.seek(offset)
        return entropy(fh.read(length))


def toc_word_plausibility(path: str | os.PathLike, max_words: int = 8192) -> dict:
    """How many 32-bit words in the table region look like in-file offsets.

    A plaintext RPF table is a run of {name offset, size, file offset, flags}
    records, so most words land inside the file.  Encrypted data does not.
    """
    hdr = read_header(path)
    span = max(0, min(hdr.f1, max_words * 4))
    with open(path, "rb") as fh:
        fh.seek(0x20)
        raw = fh.read(span)
    words = [struct.unpack_from("<I", raw, i)[0] for i in range(0, len(raw) - 3, 4)]
    if not words:
        return {"sampled_words": 0, "in_bounds": 0, "fraction": 0.0}
    inside = sum(1 for w in words if w < hdr.file_size)
    return {
        "sampled_words": len(words),
        "in_bounds": inside,
        "fraction": inside / len(words),
    }


def toc_entry_plausibility(path: str | os.PathLike, max_records: int = 2048) -> dict:
    """Fraction of 16-byte records that look like RPF directory/file entries.

    Scale-independent, unlike a raw in-bounds test: it checks the structural
    markers (directory tag 0x7FFFFF00, per-file encryption flag in {0,1}) and
    whether the packed size/offset fields land inside the archive.  A plaintext
    table scores near 100%; ciphertext or compressed data scores near zero.
    """
    hdr = read_header(path)
    span = max(0, min(hdr.f1, max_records * 16))
    with open(path, "rb") as fh:
        fh.seek(0x20)
        raw = fh.read(span)
    records = len(raw) // 16
    if not records:
        return {"records": 0, "plausible": 0, "fraction": 0.0}
    good = 0
    for i in range(records):
        base = i * 16
        tag = struct.unpack_from("<I", raw, base + 4)[0]
        if tag == 0x7FFFFF00:
            good += 1
            continue
        packed = struct.unpack_from("<Q", raw, base)[0]
        enc = struct.unpack_from("<I", raw, base + 12)[0]
        size = (packed >> 16) & 0xFFFFFF
        offset = ((packed >> 40) & 0xFFFFFF) * 512
        if enc in (0, 1) and 0 < size <= max(hdr.file_size, 1) and offset <= hdr.file_size:
            good += 1
    return {"records": records, "plausible": good, "fraction": good / records}


def looks_encrypted(path: str | os.PathLike) -> bool:
    """The table region carries no recognisable RPF entry structure."""
    return toc_entry_plausibility(path)["fraction"] < 0.10


def index_gap(path: str | os.PathLike) -> int:
    """Zero bytes immediately after the index, before the first resource.

    Not a validity rule: some archives have resource bytes at ``f1`` straight
    away (gap 0), others pad to the first resource offset.  Measured only.
    """
    hdr = read_header(path)
    if hdr.f1 >= hdr.file_size:
        return 0
    with open(path, "rb") as fh:
        fh.seek(hdr.f1)
        raw = fh.read(min(hdr.file_size - hdr.f1, GAP_PROBE))
    gap = 0
    for byte in raw:
        if byte:
            break
        gap += 1
    return gap


def describe(path: str | os.PathLike) -> dict:
    """Everything this tool knows about one archive, with no assumptions."""
    hdr = read_header(path)
    out = hdr.as_dict()
    out["name"] = os.path.basename(path)
    out["constant_block"] = has_constant_block(path)
    out["index_gap_bytes"] = index_gap(path)
    out["index_entropy"] = round(entropy_at(path, TOC_OFFSET, 4096), 3)
    # Backwards-compatible aliases used by the report renderer.
    out["constant_toc_block"] = out["constant_block"]
    out["toc_entropy"] = out["index_entropy"]
    out["toc_word_plausibility"] = toc_word_plausibility(path)
    out["toc_entry_plausibility"] = toc_entry_plausibility(path)
    out["likely_encrypted_toc"] = looks_encrypted(path)
    return out


def format_header(hdr: Header) -> str:
    """Small human-readable block used by the CLI and the TUI."""
    lines = [
        f"revision        : {hdr.revision}   (on-disk magic {hdr.on_disk_magic!r})",
        f"file size       : {hdr.file_size:,} bytes",
        f"index size f1   : {hdr.index_size:,}  (payload area starts at 0x{hdr.data_offset:x})",
        f"field 0x08      : {hdr.f2:,}  (unidentified, 16-byte multiple)",
        f"field 0x0c      : {hdr.f3:,}  (unidentified, 16-byte multiple)",
        f"unknown h1/h2   : 0x{hdr.h1:08X} / 0x{hdr.h2:08X}",
        f"build stamp     : {hdr.stamp:,} (0x{hdr.stamp:06X})"
        + ("  [invariant]" if hdr.stamp_ok else "  [!] unexpected"),
        f"unknown f4      : {hdr.f4:,}",
    ]
    return "\n".join(lines)
