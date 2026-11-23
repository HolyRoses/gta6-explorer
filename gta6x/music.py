"""Music/radio record table in the `audio.rpf` config blob.

The config is a set of zlib streams before the first AWC bank. Its records are
46-byte entries; the marker is at +4 and the real duration is the u32 four
bytes before it. `hash B` is joaat(normalized track name) and the AWC stream id
is its low 29 bits. This module extracts record-level metadata only: names are
not recovered and no playback order is inferred.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Iterator

from . import rpf, zlibcarve

MARKER = b"\x0c\x01"
CONFIG_MARKER = b"\x02\x00\x0c\x00"
TAIL_MARKER = b"\x00\x00\x02\x23"
DEFAULT_CONFIG_LIMIT = 64 * 1024 * 1024

__all__ = ["MusicRecord", "scan", "carve_config", "scan_file"]


@dataclass
class MusicRecord:
    offset: int
    duration_ms: int
    config_id: int
    hash_a: int
    hash_b: int
    stream_id: int

    def as_dict(self) -> dict:
        return {
            "offset": self.offset,
            "offset_hex": f"0x{self.offset:x}",
            "duration_ms": self.duration_ms,
            "duration_s": round(self.duration_ms / 1000.0, 3),
            "config_id": self.config_id,
            "hash_a": f"0x{self.hash_a:08x}",
            "hash_b": f"0x{self.hash_b:08x}",
            "stream_id": f"0x{self.stream_id:08x}",
        }


def _u32(data: bytes, at: int) -> int:
    return struct.unpack_from("<I", data, at)[0]


def _duration_range(min_ms, max_ms):
    if (type(min_ms) is not int or type(max_ms) is not int
            or not 0 <= min_ms <= max_ms <= 0xffffffff):
        raise ValueError('invalid music duration range')


def scan(blob: bytes, min_ms: int = 20_000, max_ms: int = 2_000_000) -> Iterator[MusicRecord]:
    """Yield plausible 46-byte music records from one joined config blob."""
    _duration_range(min_ms, max_ms)
    at = 4
    size = len(blob)
    while at + 24 <= size:
        found = blob.find(MARKER, at)
        if found < 0:
            return
        at = found
        if (found >= 4 and at + 20 <= size
                and blob[found + 4:found + 8] == CONFIG_MARKER
                and blob[found + 16:found + 20] == TAIL_MARKER):
            duration = _u32(blob, found - 4)
            if min_ms <= duration <= max_ms:
                hash_a = _u32(blob, found + 8)
                hash_b = _u32(blob, found + 12)
                yield MusicRecord(
                    offset=found - 4,
                    duration_ms=duration,
                    config_id=struct.unpack_from("<H", blob, found + 2)[0],
                    hash_a=hash_a,
                    hash_b=hash_b,
                    stream_id=hash_b & 0x1FFFFFFF,
                )
                at = found + 46
                continue
        at = found + 2


def carve_config(path: str | os.PathLike, limit: int | None = None,
                 start: int | None = None) -> bytes:
    """Concatenate the zlib config streams before the AWC banks."""
    path = os.fspath(path)
    if start is None:
        try:
            start = rpf.read_header(path).index_size
        except (OSError, ValueError):
            start = 0
    if limit is None:
        limit = DEFAULT_CONFIG_LIMIT
    out = bytearray()
    for blob in zlibcarve.carve_streams(path, length=start + limit, min_out=256):
        if blob.offset >= start:
            out.extend(blob.data)
    return bytes(out)


def scan_file(path: str | os.PathLike, limit: int | None = None,
              start: int | None = None, *, min_ms: int = 20_000,
              max_ms: int = 2_000_000) -> list[MusicRecord]:
    _duration_range(min_ms, max_ms)
    return list(scan(carve_config(path, limit=limit, start=start),
                     min_ms=min_ms, max_ms=max_ms))
