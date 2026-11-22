"""Plaintext media carriers inside the RPF9 archives.

`movies.rpf` stores Bink2 video and `audio.rpf` stores AWC audio **without
encryption**: each payload sits at a 4 KiB-aligned offset, is preceded by zero
padding, and begins with its own magic.  That makes them carvable without any
key, which is what this module does.

Resource payloads (models, textures) show neither of these carriers, so they
are *not* handled here -- see the analysis for why.

Extraction is read-only with respect to the source: files are opened 'rb' and
output goes to a directory you name.
"""

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from typing import Iterable, Iterator

BINK2_MAGIC = b"KB2"
BINK1_MAGIC = b"BIK"
AWC_MAGIC = b"ADAT"
PADDING = b"\x00" * 8

CHUNK = 64 * 1024 * 1024
OVERLAP = 8192

MAX_BINK_SIZE = 400 * 1024 * 1024
MAX_AWC_SIZE = 256 * 1024 * 1024
AWC_GAP_CAP = 4 * 1024 * 1024  # only a fallback if a container has no tag table
AWC_HEADER_SIZE = 272  # smallest common header; the real size is declared

# AWC flag word: low 16 bits are the container version (1), high 16 bits are
# feature flags.  0xFF21/0xFF25/0xFF02 are feature words, not versions.
AWC_REQUIRED_MASK = 0xFF00FFFF
AWC_REQUIRED_VALUE = 0xFF000001
AWC_FORBIDDEN_FEATURES = 0x00980000
AWC_FEATURE_INDEX = 0x10000      # per-stream u16 table of cumulative tag counts
AWC_FEATURE_EXTRA = 0x200000     # (streams + 1) u32 prefix table
AWC_FEATURE_PREFIX = 0x400000    # one extra dword after the 16-byte header
AWC_MAX_HEADER = 4 * 1024 * 1024
AWC_MAX_STREAMS = 8192

AWC_TAG_FORMAT = 0x76
AWC_TAG_DATA = 0x55
AWC_TAG_MUSIC = 0x48
AWC_CODECS = {5: "xma2", 0x0B: "opus", 0: "pcm"}

KINDS = ("bink2", "bink1", "awc")
_MAGICS = {"bink2": BINK2_MAGIC, "bink1": BINK1_MAGIC, "awc": AWC_MAGIC}
_EXT = {"bink2": "bk2", "bink1": "bik", "awc": "awc"}

__all__ = [
    "Hit", "KINDS", "scan_file", "validate_bink2", "validate_bink1",
    "validate_awc", "extract_hits", "describe_hit",
]


@dataclass
class Hit:
    kind: str
    archive: str
    offset: int
    size: int | None
    meta: dict
    confidence: str = "high"

    @property
    def extension(self) -> str:
        return _EXT.get(self.kind, "bin")

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "archive": self.archive,
            "offset": self.offset,
            "offset_hex": f"0x{self.offset:09x}",
            "size": self.size,
            "confidence": self.confidence,
            **self.meta,
        }


def _u32(buf: bytes, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def validate_bink2(buf: bytes) -> dict | None:
    """Bink2 header: 'KB2' + version char, then size/frames/width/height/fps."""
    if len(buf) < 0x30 or not buf.startswith(BINK2_MAGIC):
        return None
    version = buf[3:4].decode("latin1")
    if not version.isalnum():
        return None
    size, frames, biggest, frames2, width, height, fps = struct.unpack_from("<7I", buf, 4)
    if not (0 < size <= MAX_BINK_SIZE):
        return None
    if not (64 <= width <= 4096 and 64 <= height <= 4096):
        return None
    if not (4 < frames2 < 200_000 and 1 <= fps <= 240 and biggest <= 64 * 1024 * 1024):
        return None
    return {
        "version": version,
        "size": size,
        "frames": frames,
        "width": width,
        "height": height,
        "fps": fps,
        "largest_frame": biggest,
    }


def validate_bink1(buf: bytes) -> dict | None:
    """Bink1 header. Loose: Bink1 packs several fields at 16-bit widths, so this
    accepts only headers whose size and dimensions are mutually plausible."""
    if len(buf) < 0x20 or not buf.startswith(BINK1_MAGIC):
        return None
    version = buf[3:4].decode("latin1")
    if version not in "bdefghijklmnopqrstuvwxyz":
        return None
    size = _u32(buf, 4)
    frames = struct.unpack_from("<H", buf, 8)[0]
    width = _u32(buf, 0x14)
    height = _u32(buf, 0x18)
    if not (0 < size <= MAX_BINK_SIZE and 0 < frames < 200_000):
        return None
    if not (16 <= width <= 4096 and 16 <= height <= 4096):
        return None
    return {
        "version": version,
        "size": size,
        "frames": frames,
        "width": width,
        "height": height,
        "fps": None,
    }


def _u16(buf: bytes, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def _u64(buf: bytes, off: int) -> int:
    return struct.unpack_from("<Q", buf, off)[0]


def awc_header_length(prefix: bytes) -> int | None:
    """Declared header size for a plausible AWC prefix, else None.

    Only the first 16 bytes are needed, which lets a scanner size its read
    before validating the whole header.
    """
    if len(prefix) < 16 or not prefix.startswith(AWC_MAGIC):
        return None
    flags = _u32(prefix, 4)
    if (flags & AWC_REQUIRED_MASK) != AWC_REQUIRED_VALUE:
        return None
    if flags & AWC_FORBIDDEN_FEATURES:
        return None
    streams = _u32(prefix, 8)
    header_size = _u32(prefix, 12)
    if not (0 < streams <= AWC_MAX_STREAMS):
        return None
    if not (20 <= header_size <= AWC_MAX_HEADER):
        return None
    return header_size


def validate_awc(buf: bytes) -> dict | None:
    """AWC container: 'ADAT', u32 flag word, u32 stream count, u32 header size.

    The flag word's low 16 bits are the container version (1) and its high
    16 bits are feature flags -- so the values historically written as
    ``0xFF21`` / ``0xFF25`` / ``0xFF02`` are feature words, not versions.
    Feature bits select optional tables before the per-stream index:

    * ``0x10000`` -- ``streams`` u16 entries, cumulative tag counts
    * ``0x200000`` -- ``streams + 1`` u32 prefix table
    * ``0x400000`` -- one extra dword after the 16-byte header

    After those comes a ``streams``-long u32 table: 29-bit stream id plus a
    3-bit tag count.  Each tag is a 64-bit word ``{type:8, size:28, rel:28}``
    where ``rel`` is relative to the container start.  The container's exact
    byte length is therefore ``max(header_size, rel + size)`` -- no gap
    heuristic is needed.
    """
    header_size = awc_header_length(buf[:16] if len(buf) >= 16 else buf)
    if header_size is None or len(buf) < header_size:
        return None
    flags = _u32(buf, 4)
    streams = _u32(buf, 8)
    version = flags & 0xFFFF
    features = flags >> 16

    pos = 16 + (4 if flags & AWC_FEATURE_PREFIX else 0)
    index_at = pos if flags & AWC_FEATURE_INDEX else -1
    if index_at >= 0:
        pos += streams * 2
    if flags & AWC_FEATURE_EXTRA:
        pos += (streams + 1) * 4
    info_at = pos
    pos += streams * 4
    if pos > header_size:
        return None

    ids: list[int] = []
    tag_total = 0
    cumulative = 0
    for i in range(streams):
        packed = _u32(buf, info_at + i * 4)
        tag_count = packed >> 29
        # The index table stores each stream's cumulative tag offset *before*
        # its own tags, so stream 0 is 0, not its own tag count.
        if index_at >= 0 and _u16(buf, index_at + i * 2) != cumulative:
            return None
        tag_total += tag_count
        cumulative += tag_count
        stream_id = packed & 0x1FFFFFFF
        if ids and stream_id < ids[-1]:
            return None
        ids.append(stream_id)
    if pos + tag_total * 8 != header_size:
        return None

    tag_types: dict[int, int] = {}
    stream_list: list[dict] = []
    data_bytes = 0
    extent = header_size
    cursor = pos
    for i in range(streams):
        packed = _u32(buf, info_at + i * 4)
        entry: dict = {"index": i, "id": ids[i], "tags": packed >> 29,
                       "codec": None, "sample_rate": None, "channels": None,
                       "samples": None, "data_offset": None, "data_bytes": 0,
                       "music": None}
        fmt = None
        for _ in range(packed >> 29):
            tag = _u64(buf, cursor)
            cursor += 8
            tag_type = (tag >> 56) & 0xFF
            size = (tag >> 28) & 0x0FFFFFFF
            rel = tag & 0x0FFFFFFF
            if size and rel < header_size:
                return None
            tag_types[tag_type] = tag_types.get(tag_type, 0) + 1
            if tag_type == AWC_TAG_DATA:
                data_bytes += size
                entry["data_offset"] = rel
                entry["data_bytes"] = size
            elif tag_type == AWC_TAG_FORMAT:
                fmt = (rel, size)
            elif tag_type == AWC_TAG_MUSIC:
                entry["music_offset"] = rel
                entry["music_size"] = size
            extent = max(extent, rel + size)
        if fmt and fmt[0] + 32 <= len(buf):
            at = fmt[0]
            samples = _u32(buf, at)
            rate = _u16(buf, at + 8)
            codec = buf[at + 28]
            channels = buf[at + 29]
            if 1000 <= rate <= 192000 and 1 <= channels <= 8:
                entry.update({"codec": codec, "sample_rate": rate,
                              "channels": channels, "samples": samples,
                              "duration": round(samples / rate, 3),
                              "codec_name": AWC_CODECS.get(codec, f"0x{codec:02x}")})
        music_at = entry.get("music_offset")
        music_size = entry.get("music_size") or 0
        if music_at is not None and 12 <= music_size and music_at + 12 <= len(buf):
            blocks = _u32(buf, music_at)
            chunk_bytes = _u32(buf, music_at + 4)
            music_channels = _u32(buf, music_at + 8)
            parsed = {"blocks": blocks, "chunk_bytes": chunk_bytes,
                      "channels": []}
            if (0 < blocks <= 131072 and 2048 <= chunk_bytes <= 16 * 1024 * 1024
                    and 0 < music_channels <= 32
                    and music_at + 12 + music_channels * 16 <= len(buf)
                    and music_at + music_size <= len(buf)):
                for channel in range(music_channels):
                    at = music_at + 12 + channel * 16
                    channel_id = _u32(buf, at) & 0x1FFFFFFF
                    samples = _u32(buf, at + 4)
                    rate = _u16(buf, at + 10)
                    codec = buf[at + 12]
                    parsed["channels"].append({
                        "index": channel, "id": channel_id,
                        "samples": samples, "sample_rate": rate,
                        "codec": codec,
                        "codec_name": AWC_CODECS.get(codec, f"0x{codec:02x}"),
                        "duration": round(samples / rate, 3) if rate else None,
                    })
                entry["music"] = parsed
                durations = [c["duration"] for c in parsed["channels"]
                             if c.get("duration")]
                entry["codec_name"] = "music"
                if durations:
                    entry["duration"] = max(durations)
            else:
                parsed["error"] = "invalid music block dimensions"
                entry["music"] = parsed
        stream_list.append(entry)
    if extent > MAX_AWC_SIZE:
        return None
    return {
        "version": version,
        "flags": f"0x{features:04X}",
        "flags_u32": f"0x{flags:08X}",
        "streams": streams,
        "header_size": header_size,
        "tags": tag_total,
        "tag_types": {"0x%02X" % k: v for k, v in sorted(tag_types.items())},
        "data_bytes": data_bytes,
        "size": extent,
        "exact_length": True,
        "has_index_table": index_at >= 0,
        "has_extra_table": bool(flags & AWC_FEATURE_EXTRA),
        "has_prefix_dword": bool(flags & AWC_FEATURE_PREFIX),
        "stream_list": stream_list,
        "confidence": "high",
    }


_VALIDATORS = {
    "bink2": validate_bink2,
    "bink1": validate_bink1,
    "awc": validate_awc,
}


def describe_hit(hit: Hit) -> str:
    bits = [hit.kind.upper(), f"@0x{hit.offset:x}"]
    meta = hit.meta
    if hit.kind in ("bink2", "bink1"):
        bits.append(f"{meta.get('width')}x{meta.get('height')}")
        if meta.get("fps"):
            bits.append(f"@{meta['fps']}fps")
        bits.append(f"{meta.get('frames')} frames")
        bits.append(f"{hit.size:,} B")
    elif hit.kind == "awc":
        bits.append(f"{meta.get('streams')} streams")
        bits.append(f"flags {meta.get('flags')}")
        bits.append(f"{meta.get('tags', 0)} tags")
        bits.append("size unknown" if hit.size is None else f"{hit.size:,} B")
    return "  ".join(bits)


def _hits_in_buffer(
    buf: bytes,
    base: int,
    archive: str,
    patterns: dict[str, bytes],
    prefix: int,
    align: int | None,
    file_size: int,
) -> Iterator[Hit]:
    """Yield validated carriers found in one buffer, offsets relative to base."""
    for kind, pattern in patterns.items():
        idx = buf.find(pattern)
        while idx != -1:
            off = base + idx + prefix
            if align is None or off % align == 0:
                start = idx + prefix
                if kind == "awc":
                    need = awc_header_length(buf[start:start + 16]) or AWC_HEADER_SIZE
                else:
                    need = 0x30
                head = buf[start: start + need]
                meta = _VALIDATORS[kind](head)
                if meta:
                    size = meta.get("size")
                    if size and off + size > file_size:
                        size = None  # declared length runs past EOF
                    yield Hit(kind, archive, off, size, meta,
                              meta.get("confidence", "high"))
            idx = buf.find(pattern, idx + 1)


def scan_windows(
    path: str | os.PathLike,
    kinds: Iterable[str] = ("bink2", "awc"),
    windows: int = 4,
    window_bytes: int = 48 * 1024 * 1024,
    require_padding: bool = True,
    align: int | None = 0x1000,
) -> list[Hit]:
    """Sample ``windows`` evenly spaced blocks instead of the file head.

    Carriers cluster in specific regions, so a head-only scan under-reports;
    this spreads coverage across the whole archive at a fixed cost.
    """
    kinds = tuple(k for k in kinds if k in _VALIDATORS)
    if not kinds:
        return []
    patterns = {k: (PADDING + _MAGICS[k] if require_padding else _MAGICS[k]) for k in kinds}
    prefix = len(PADDING) if require_padding else 0
    archive = os.path.basename(path)
    size = os.path.getsize(path)
    window_bytes = min(window_bytes, size)
    found: list[Hit] = []
    seen: set[tuple[str, int]] = set()
    fractions = [0.0] if windows <= 1 else [i / (windows - 1) for i in range(windows)]
    with open(path, "rb") as fh:
        for frac in fractions:
            offset = int(max(0, min(size - window_bytes, size * frac)))
            fh.seek(offset)
            buf = fh.read(window_bytes)
            for hit in _hits_in_buffer(buf, offset, archive, patterns, prefix, align, size):
                key = (hit.kind, hit.offset)
                if key not in seen:
                    seen.add(key)
                    found.append(hit)
    found.sort(key=lambda h: h.offset)
    return found


def scan_file(
    path: str | os.PathLike,
    kinds: Iterable[str] = ("bink2", "awc"),
    limit: int | None = None,
    require_padding: bool = True,
    align: int | None = 0x1000,
    progress=None,
) -> Iterator[Hit]:
    """progress(done_bytes, total_bytes, hits) is called periodically."""
    """Yield validated carriers found in *path*.

    ``limit`` caps how many bytes are read (None = whole file). With
    ``require_padding`` a hit must be preceded by eight zero bytes, which is
    how uncompressed RPF payloads are laid out; that also removes essentially
    all false positives from 3-byte magics.
    """
    kinds = tuple(k for k in kinds if k in _VALIDATORS)
    if not kinds:
        return
    patterns = {k: (PADDING + _MAGICS[k] if require_padding else _MAGICS[k]) for k in kinds}
    prefix = len(PADDING) if require_padding else 0
    archive = os.path.basename(path)
    file_size = os.path.getsize(path)
    total = min(limit, file_size) if limit else file_size
    pos = 0
    tail = b""
    hits = 0
    step = 512 * 1024 * 1024
    next_report = step
    with open(path, "rb") as fh:
        while pos < total:
            block = fh.read(min(CHUNK, total - pos))
            if not block:
                break
            buf = tail + block
            base = pos - len(tail)
            for hit in _hits_in_buffer(buf, base, archive, patterns, prefix, align, file_size):
                hits += 1
                yield hit
            if progress is not None and pos >= next_report:
                progress(pos, total, hits)
                next_report += step
            tail = buf[-OVERLAP:]
            pos += len(block)


def extract_hits(
    hits: list[Hit],
    out_dir: str | os.PathLike,
    source_root: str | os.PathLike = ".",
    max_bytes: int | None = None,
) -> list[dict]:
    """Write each hit to *out_dir*; returns a manifest of what was written.

    Bink2 and AWC both declare their byte length (AWC through its tag table), so
    carving is exact.  Only a container whose tag table fails validation falls
    back to a gap heuristic, and the manifest says which method was used.
    """
    os.makedirs(out_dir, exist_ok=True)
    by_archive: dict[str, list[Hit]] = {}
    for hit in hits:
        by_archive.setdefault(hit.archive, []).append(hit)

    written: list[dict] = []
    for archive, group in by_archive.items():
        group.sort(key=lambda h: h.offset)
        path = os.path.join(source_root, archive)
        if not os.path.isfile(path):
            # archives may live in sub-directories; search one level down
            matches = [os.path.join(dp, archive) for dp, _, fs in os.walk(source_root) if archive in fs]
            if not matches:
                continue
            path = matches[0]
        with open(path, "rb") as fh:
            for i, hit in enumerate(group):
                start = hit.offset
                if hit.size:
                    size, method = hit.size, "header"
                else:
                    nxt = group[i + 1].offset if i + 1 < len(group) else None
                    size = (nxt - start) if nxt else AWC_GAP_CAP
                    size = min(size, AWC_GAP_CAP)
                    method = "gap (approximate)"
                if max_bytes is not None and size > max_bytes:
                    size = max_bytes
                fh.seek(start)
                blob = fh.read(size)
                if not blob:
                    continue
                padded = len(blob)
                if method.startswith("gap"):
                    trimmed = blob.rstrip(b"\x00")
                    if len(trimmed) > AWC_HEADER_SIZE // 2:
                        blob = trimmed
                        method = "gap + zero-trim"
                name = f"{os.path.splitext(archive)[0]}_{hit.kind}_{start:09x}.{hit.extension}"
                dest = os.path.join(out_dir, name)
                with open(dest, "wb") as out:
                    out.write(blob)
                written.append({
                    "file": dest,
                    "archive": archive,
                    "kind": hit.kind,
                    "offset": start,
                    "bytes": len(blob),
                    "padded_bytes": padded,
                    "carve_method": method,
                    "sha256": hashlib.sha256(blob).hexdigest(),
                    "meta": hit.meta,
                })
    return written
