"""Carve zlib streams out of RPF9 payloads and RDS5 resources.

The resource payloads in this package are **zlib-compressed, not encrypted**:
a stream begins with `78 01`, `78 5E`, `78 9C` or `78 DA`, inflates cleanly, and
the inflate expansion is typically several times the compressed size. That makes
the payloads recoverable without any key -- the only thing missing is the
encrypted table of contents, which is why carving is the way in.

This module walks a byte range, inflates every stream it can, and (by resuming
after each stream's *consumed* input) avoids emitting overlapping duplicates.
"""

from __future__ import annotations

import hashlib
import os
import zlib
from dataclasses import dataclass
from typing import Iterator

ZLIB_HEADS = (b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda")
READ_CHUNK = 32 * 1024 * 1024
DEFAULT_MIN_OUT = 1024

__all__ = ["Blob", "carve_streams", "write_blobs", "classify_blob"]


@dataclass
class Blob:
    archive: str
    offset: int
    compressed: int
    size: int
    data: bytes

    def as_dict(self, keep_data: bool = False) -> dict:
        out = {
            "archive": self.archive,
            "offset": self.offset,
            "offset_hex": f"0x{self.offset:x}",
            "compressed_bytes": self.compressed,
            "inflated_bytes": self.size,
            "ratio": round(self.size / max(1, self.compressed), 2),
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "magic": self.data[:4].hex(),
            "kind": classify_blob(self.data),
        }
        if keep_data:
            out["data"] = self.data
        return out


def classify_blob(data: bytes) -> str:
    """Best-effort label from the inflated bytes."""
    if data[:4] in (b"RDS5", b"RSC7", b"RSC8"):
        return "resource"
    head = data[:64].lstrip(b"\xef\xbb\xbf \r\n\t")
    if head.startswith(b"<?xml") or head.startswith(b"<"):
        return "xml"
    if data[:4] == b"PSIN":
        return "psin-page"
    if data[:4] in (b"PRD0", b"0DRP"):
        return "page-index"
    printable = sum(1 for b in data[:512] if 32 <= b < 127 or b in (9, 10, 13))
    if len(data) >= 64 and printable > len(data[:512]) * 0.9:
        return "text"
    if len(data) >= 32 and data.count(0) > len(data) * 0.7:
        return "sparse/binary"
    return "binary"


def carve_streams(
    path: str | os.PathLike,
    start: int = 0,
    length: int | None = None,
    min_out: int = DEFAULT_MIN_OUT,
    max_out: int = 512 * 1024 * 1024,
    window: int = 16 * 1024 * 1024,
) -> Iterator[Blob]:
    """Yield non-overlapping zlib streams found in ``[start, start+length)``."""
    path = os.fspath(path)
    archive = os.path.basename(path)
    size = os.path.getsize(path)
    end = size if length is None else min(size, start + length)

    with open(path, "rb") as fh:
        fh.seek(start)
        base = start
        buf = fh.read(min(window, end - start))
        while buf:
            pos = 0
            while True:
                idx = -1
                for head in ZLIB_HEADS:
                    found = buf.find(head, pos)
                    if found != -1 and (idx == -1 or found < idx):
                        idx = found
                if idx == -1 or idx >= len(buf) - 8:
                    break
                try:
                    obj = zlib.decompressobj()
                    out = obj.decompress(buf[idx:], max_out)
                except zlib.error:
                    pos = idx + 1
                    continue
                if not obj.eof or len(out) < min_out:
                    pos = idx + 1
                    continue
                consumed = max(2, len(buf) - idx - len(obj.unused_data))
                yield Blob(archive, base + idx, consumed, len(out), out)
                pos = idx + consumed
            # slide the window, keeping a tail in case a stream straddles it
            if end <= base + len(buf):
                break
            keep = min(64 * 1024, len(buf))
            new_base = base + len(buf) - keep
            fh.seek(new_base)
            buf = fh.read(min(window, end - new_base))
            base = new_base


def write_blobs(
    blobs: list[Blob],
    out_dir: str | os.PathLike,
    prefix: str = "",
    suffix: str = ".bin",
) -> list[dict]:
    os.makedirs(out_dir, exist_ok=True)
    written: list[dict] = []
    for blob in blobs:
        name = f"{prefix}{os.path.splitext(blob.archive)[0]}_{blob.offset:09x}{suffix}"
        path = os.path.join(out_dir, name)
        with open(path, "wb") as fh:
            fh.write(blob.data)
        meta = blob.as_dict()
        meta["file"] = path
        written.append(meta)
    return written
