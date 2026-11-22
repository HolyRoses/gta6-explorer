"""Animation archive reconnaissance (`anim.rpf`).

The animation archive is made of zlib streams whose payloads use several
containers. The format is not decoded yet, but the containers below are
measurable and useful for browsing:

* ``0DRP`` page directories (marker at +0x10),
* ``MoVE`` motion containers,
* ``pack:/...`` name tables (``.clip``/``.anim``/``.motion``),
* ``SKEL_*`` bone-name tables,
* ``RBF0`` rig-set metadata,
* packed clip streams (u32 2/3 + ``01 01 00 00``),
* type-hash tables, PSIN metadata and raw streams.

This module classifies those streams and extracts the name tables. It does not
decode clips or bone curves; that remains open research.
"""

from __future__ import annotations

import os
import re
import struct
from dataclasses import dataclass, field
from typing import Iterator

from . import rpf, zlibcarve

PACK_NAME = re.compile(rb"pack:/[^\x00]{1,200}")
SKEL_NAME = re.compile(rb"(?:SKEL_|PH_)[A-Za-z0-9_]{1,100}")
RBF_SCHEMA = re.compile(rb"[\x20-\x7e]{4,120}")

SIGNATURES = (
    "page-directory", "move", "rbf0", "name-table", "skeleton-names",
    "typehash", "clip-stream", "psin", "zero-prefix", "text", "raw",
)

__all__ = ["AnimRecord", "classify", "scan"]


@dataclass
class AnimRecord:
    offset: int
    stored: int
    size: int
    signature: str
    version: int | None = None
    name: str = ""
    count: int | None = None
    detail: str = ""
    names: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "offset": self.offset,
            "offset_hex": f"0x{self.offset:x}",
            "stored": self.stored,
            "size": self.size,
            "signature": self.signature,
            "version": self.version,
            "name": self.name,
            "count": self.count,
            "detail": self.detail,
            "names": self.names,
        }


def _u32(data: bytes, at: int) -> int | None:
    return struct.unpack_from("<I", data, at)[0] if len(data) >= at + 4 else None


def _u64(data: bytes, at: int) -> int | None:
    return struct.unpack_from("<Q", data, at)[0] if len(data) >= at + 8 else None


def _first_text(data: bytes, prefix: bytes) -> str:
    start = data.find(prefix)
    if start < 0:
        return ""
    end = data.find(b"\x00", start)
    if end < 0:
        end = min(len(data), start + 200)
    return data[start:end].decode("ascii", "replace")


def _printable(data: bytes) -> bool:
    sample = data[:512]
    if len(sample) < 64:
        return False
    good = sum(1 for b in sample if 9 <= b < 127 or b in (10, 13))
    return good / len(sample) > 0.9


def classify(data: bytes, offset: int, stored: int) -> AnimRecord:
    """Classify one inflated animation stream."""
    record = AnimRecord(offset, stored, len(data), "raw")
    if data[:4] == b"MoVE":
        record.signature = "move"
        record.version = _u32(data, 4)
        hint = _u32(data, 0x14)
        if hint is not None:
            record.detail = f"size_hint={hint}"
    elif data[:4] == b"PSIN":
        record.signature = "psin"
        record.detail = "metadata container"
    elif data[:4] == b"RBF0":
        record.signature = "rbf0"
        match = RBF_SCHEMA.search(data[8:160])
        record.name = match.group().decode("ascii", "replace") if match else ""
        record.detail = "rig metadata"
    elif data[:6] == b"pack:/":
        record.signature = "name-table"
        found = [m.group().decode("ascii", "replace")
                 for m in PACK_NAME.finditer(data)]
        record.names = sorted(set(found))
        record.name = found[0] if found else ""
        record.count = len(record.names)
        record.detail = "pack:/ paths"
    elif data[:5] == b"SKEL_":
        record.signature = "skeleton-names"
        found = [m.group().decode("ascii", "replace")
                 for m in SKEL_NAME.finditer(data)]
        record.names = sorted(set(found))
        record.name = found[0] if found else ""
        record.count = len(record.names)
        record.detail = "bone names"
    elif len(data) >= 0x30 and data[16:20] == b"0DRP":
        record.signature = "page-directory"
        record.version = _u32(data, 0x14)
        record.count = _u64(data, 0x20)
        record.detail = "0DRP at +0x10"
    elif (len(data) >= 16 and _u32(data, 4) == 8 and _u32(data, 12) == 0
          and 0 < (_u32(data, 8) or 0) <= 4096):
        record.signature = "typehash"
        record.version = 8
        record.count = _u32(data, 8)
        record.detail = f"type=0x{_u32(data, 0):08x}"
    elif len(data) >= 8 and _u32(data, 0) in (2, 3) and data[4:8] == b"\x01\x01\x00\x00":
        record.signature = "clip-stream"
        record.version = _u32(data, 0)
        record.detail = "24-byte header"
    elif data[:8] == b"\x00" * 8:
        record.signature = "zero-prefix"
    elif _printable(data):
        record.signature = "text"
    else:
        record.signature = "raw"
        record.detail = data[:4].hex()
    return record


def scan(path: str | os.PathLike, limit: int | None = None,
         start: int | None = None) -> Iterator[AnimRecord]:
    """Yield classified zlib streams from an animation archive."""
    path = os.fspath(path)
    if start is None:
        try:
            start = rpf.read_header(path).index_size
        except (OSError, ValueError):
            start = 0
    length = (start + limit) if limit else None
    for blob in zlibcarve.carve_streams(path, length=length, min_out=64):
        if blob.offset < start:
            continue
        yield classify(blob.data, blob.offset, blob.compressed)
