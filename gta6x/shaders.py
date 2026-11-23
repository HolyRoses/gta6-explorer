"""DXBC shader extraction from RPF9 archives.

`shaders.rpf` stores shader binaries in small wrappers::

    [u8 name_len + 1] [name bytes] [0x00] [u8 name_len]
    [u32 stored]      [u32 decoded] [magic 0x000DDCE7]
    [raw deflate stream of `decoded` bytes]

The inflated bytes are a DXBC container: magic, 16-byte hash, a dword `1`,
the total size, a chunk count, a table of 4-byte-aligned chunk offsets, then
chunks whose 4-byte tags are printable ASCII and whose sizes fit the file, with
at most three trailing zero bytes.

Names end in ``_Wrapped`` (e.g. ``VS_AlphaTransmissionFullScreenTri_4f16bf6c_Wrapped``).
Only wrappers whose deflate stream inflates to exactly the declared length and
whose output passes the DXBC structure check are reported, so coincidental magic
matches are rejected.

Measured on 1.0.2.1: the first 64 MiB of ``shaders.rpf`` contains **9,135**
validated shaders.
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from typing import Iterator

MAGIC = 0x000DDCE7
MAGIC_BYTES = struct.pack("<I", MAGIC)
MAX_STORED = 1024 * 1024
MAX_SHADER = 8 * 1024 * 1024
CHUNK = 32 * 1024 * 1024
LOOKAHEAD = MAX_STORED + 4096
PREFIX = 1024
MAX_CHUNKS = 64

__all__ = ["MAGIC", "ShaderHit", "scan", "validate_dxbc", "safe_name", "metadata"]


def metadata(data: bytes, *, max_records: int = 4096) -> dict:
    """Inspect public program/signature headers without decoding instructions.

    Extraction remains independent of this optional, bounded metadata view.
    Unsupported parts retain their tag, extent and hash.
    """
    from .shader_metadata import inspect
    return inspect(data, max_records=max_records)


@dataclass(frozen=True)
class ShaderHit:
    """One recovered shader wrapper."""

    archive: str
    offset: int          # offset of the deflate payload (after the 12-byte head)
    name: str
    stored: int          # compressed payload bytes
    decoded: int         # inflated bytes
    data: bytes          # inflated DXBC container

    def as_dict(self) -> dict:
        return {
            "archive": self.archive,
            "offset": self.offset,
            "offset_hex": f"0x{self.offset:09x}",
            "name": self.name,
            "stored": self.stored,
            "decoded": self.decoded,
            "sha256": __import__("hashlib").sha256(self.data).hexdigest(),
        }


def _u32(buf: bytes, at: int) -> int:
    return struct.unpack_from("<I", buf, at)[0]


def validate_dxbc(data: bytes) -> bool:
    """Structural DXBC check (magic, size fields, chunk table and chunks)."""
    if len(data) < 32 or len(data) > MAX_SHADER or data[:4] != b"DXBC":
        return False
    if _u32(data, 20) != 1 or _u32(data, 24) != len(data):
        return False
    count = _u32(data, 28)
    if not 0 < count <= MAX_CHUNKS or 32 + count * 4 > len(data):
        return False
    offsets = []
    for i in range(count):
        offset = _u32(data, 32 + i * 4)
        if offset < 32 + count * 4 or offset > len(data) - 8 or offset & 3:
            return False
        offsets.append(offset)
    offsets.sort()
    previous_end = 32 + count * 4
    for at in offsets:
        if at < previous_end:
            return False
        size = _u32(data, at + 4)
        if size > len(data) - at - 8:
            return False
        if any(c < 32 or c > 126 for c in data[at:at + 4]):
            return False
        previous_end = at + 8 + size
    if len(data) - previous_end > 3:
        return False
    return set(data[previous_end:]) <= {0}


def safe_name(name: str, limit: int = 180) -> str:
    cleaned = "".join(c if c.isalnum() or c in "_-. " else "_" for c in name)
    return (cleaned.strip(" .") or "shader")[:limit]


def _parse(buf: bytes, at: int, base: int, archive: str) -> ShaderHit | None:
    if at < 16 or at + 12 > len(buf):
        return None
    stored, decoded = _u32(buf, at + 4), _u32(buf, at + 8)
    if not (12 < stored <= MAX_STORED and 32 <= decoded <= MAX_SHADER):
        return None
    if at + stored > len(buf) or _u32(buf, at - 4) != stored:
        return None
    if buf[at - 5] in (0,) or buf[at - 5] >= 128:
        return None
    name_bytes = None
    for length in range(10, 256):
        prefix = at - 6 - length
        if prefix < 0:
            break
        if buf[prefix] != length or buf[prefix + length] != 0:
            continue
        candidate = buf[prefix + 1:prefix + length]
        if not candidate.endswith(b"_Wrapped"):
            continue
        if not all(65 <= c <= 90 or 97 <= c <= 122 or 48 <= c <= 57 or c == 95
                   for c in candidate):
            continue
        name_bytes = candidate
        break
    if name_bytes is None:
        return None
    try:
        out = zlib.decompress(buf[at + 12:at + stored], -15)
    except zlib.error:
        return None
    if len(out) != decoded or not validate_dxbc(out):
        return None
    return ShaderHit(archive, base + at + 12, name_bytes.decode("ascii"),
                     stored - 12, decoded, out)


def scan(path: str | os.PathLike, limit: int | None = None,
         progress=None) -> Iterator[ShaderHit]:
    """Yield validated shaders from *path*, optionally only the first *limit* bytes."""
    path = os.fspath(path)
    archive = os.path.basename(path)
    size = os.path.getsize(path)
    end = min(size, limit) if limit else size
    prefix = b""
    pos = 0
    hits = 0
    with open(path, "rb") as fh:
        while pos < end:
            data = fh.read(min(CHUNK + LOOKAHEAD, end - pos))
            if not data:
                break
            buf = prefix + data
            base = pos - len(prefix)
            start = len(prefix)
            stop = start + min(CHUNK, len(data))
            found = buf.find(MAGIC_BYTES, start)
            while 0 <= found < stop:
                hit = _parse(buf, found, base, archive)
                if hit is not None:
                    hits += 1
                    yield hit
                found = buf.find(MAGIC_BYTES, found + 1)
            prefix = buf[-PREFIX:]
            pos += min(CHUNK, len(data))
            if progress is not None:
                progress(min(pos, end), end, hits)
