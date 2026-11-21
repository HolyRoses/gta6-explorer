"""Heuristic geometry hunting.

Inflated payloads are mostly page tables, index structures and fill patterns.
A vertex buffer looks statistically different: it is dense with *float32 values
in plausible world coordinates*, and often contains unit-length triples
(normals). Random 32-bit words almost never satisfy those constraints, so a
density score separates the two cleanly.

This module scores candidate blobs and reports the best ones. It is a *filter*,
not a proof: a high score means "worth looking at", not "these are vertices".
"""

from __future__ import annotations

import math
import struct
from dataclasses import dataclass

__all__ = ["GeometryScore", "score", "sample_floats"]

_MAX_VALUE = 1.0e5          # plausible world/object coordinate magnitude
_MIN_VALUE = 1.0e-3         # ignore denormals and pure zeros
_SCAN_LIMIT = 512 * 1024    # bytes scored per blob


@dataclass
class GeometryScore:
    bytes_scored: int
    float_ratio: float       # fraction of 4-byte words that are plausible floats
    unit_ratio: float        # fraction of float triples whose length is ~1
    sign_ratio: float        # fraction of floats that are negative (geometry is signed)
    verdict: str

    def as_dict(self) -> dict:
        return {
            "bytes_scored": self.bytes_scored,
            "float_ratio": round(self.float_ratio, 4),
            "unit_ratio": round(self.unit_ratio, 4),
            "sign_ratio": round(self.sign_ratio, 4),
            "verdict": self.verdict,
        }


def _plausible(v: float) -> bool:
    if not math.isfinite(v):
        return False
    a = abs(v)
    return _MIN_VALUE < a < _MAX_VALUE


def score(data: bytes) -> GeometryScore:
    """Score a blob for vertex-buffer-like content."""
    n = min(len(data), _SCAN_LIMIT)
    n -= n % 12                      # whole triples only
    if n < 96:
        return GeometryScore(n, 0.0, 0.0, 0.0, "too-small")

    # fast pass over u32 words, reinterpreted as float32
    count = n // 4
    words = struct.unpack_from(f"<{count}I", data, 0)
    float_ratio = 0.0
    plausible = 0
    negatives = 0
    for w in words:
        v = struct.unpack("<f", struct.pack("<I", w))[0]
        if _plausible(v):
            plausible += 1
            if v < 0:
                negatives += 1
    if words:
        float_ratio = plausible / len(words)

    # triples: look for unit-length runs (normals) or coherent direction data
    tri_count = n // 12
    unit = 0
    for i in range(tri_count):
        x, y, z = struct.unpack_from("<3f", data, i * 12)
        if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
            continue
        length = math.sqrt(x * x + y * y + z * z)
        if 0.9 <= length <= 1.1:
            unit += 1
    unit_ratio = unit / tri_count if tri_count else 0.0

    sign_ratio = (negatives / plausible) if plausible else 0.0

    if float_ratio > 0.75 and unit_ratio > 0.25:
        verdict = "vertex+normal candidate"
    elif float_ratio > 0.75:
        verdict = "vertex-like"
    elif unit_ratio > 0.30:
        verdict = "normal-like"
    elif float_ratio > 0.45:
        verdict = "mixed floats"
    else:
        verdict = "not geometry"

    return GeometryScore(n, float_ratio, unit_ratio, sign_ratio, verdict)


def sample_floats(data: bytes, count: int = 8) -> list[float]:
    n = min(len(data), count * 4)
    n -= n % 4
    return [round(v, 3) for v in struct.unpack_from(f"<{n // 4}f", data, 0)]


def score_windows(data: bytes, window: int = 32 * 1024, step: int = 16 * 1024,
                  limit: int = 4 * 1024 * 1024) -> tuple[GeometryScore, int]:
    """Best geometry score across sliding windows, plus the offset it occurs at.

    A single blob often mixes index tables with an embedded geometry section, so
    whole-blob statistics dilute the signal. Windowed scoring finds the dense
    region and reports where it starts.
    """
    n = min(len(data), limit)
    best = GeometryScore(0, 0.0, 0.0, 0.0, "too-small")
    best_off = 0
    if n < window:
        return score(data), 0
    for off in range(0, max(1, n - window) + 1, step):
        sc = score(data[off: off + window])
        if (sc.float_ratio, sc.unit_ratio) > (best.float_ratio, best.unit_ratio):
            best, best_off = sc, off
    return best, best_off


def stride_profile(data: bytes, max_stride: int = 64, sample: int = 65536) -> dict[int, tuple[float, float]]:
    """Byte-equality and mean |delta| at each stride.

    Interleaved records repeat their padding and high bytes at the record size, so
    equality rises far above the random baseline (1/256 ≈ 0.0039). Perfect 1.000
    at every multiple of a small number means a repeating fill, not records.
    """
    d = data[:sample]
    n = len(d)
    prof: dict[int, tuple[float, float]] = {}
    for s in range(4, max_stride + 1):
        if n - s <= 0:
            continue
        positions = range(0, n - s, s)
        count = len(positions)
        eq = sum(1 for i in positions if d[i] == d[i + s]) / count
        diff = sum(abs(d[i] - d[i + s]) for i in positions) / count
        prof[s] = (eq, diff)
    return prof


def best_stride(data: bytes, max_stride: int = 64) -> tuple[int, float, float, bool]:
    """(stride, equality, mean |delta|, looks_repetitive)."""
    prof = stride_profile(data, max_stride)
    if not prof:
        return 0, 0.0, 0.0, False
    best = max(prof.items(), key=lambda kv: kv[1][0])
    stride, (eq, diff) = best
    # a fill pattern repeats identically at 2x, 3x ... of its base period
    repetitive = eq > 0.999 and any(prof.get(s, (0, 0))[0] > 0.999 for s in (stride * 2, stride * 3))
    return stride, eq, diff, repetitive


def record_dump(data: bytes, stride: int, count: int = 8, offset: int = 0) -> list[str]:
    """Render `count` records of `stride` bytes as hex plus f16/u16 interpretations."""
    out = []
    for r in range(count):
        base = offset + r * stride
        rec = data[base: base + stride]
        if len(rec) < stride:
            break
        halves = struct.unpack_from(f"<{stride // 2}H", rec, 0)
        f16 = [round(v, 3) for v in struct.unpack_from(f"<{stride // 2}e", rec, 0)]
        out.append(f"+{base:08x}  {rec.hex(' ')}  u16={halves[:6]}  f16={f16[:6]}")
    return out
