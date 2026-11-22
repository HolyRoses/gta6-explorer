"""Independently fitted BC3/4/5 block reconstruction.

Table metadata records fitting provenance and provisional history entries.
Using provisional entries emits a warning; unknown entries remain None and
are always refused.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import struct
import warnings

from .spec import CODECS, element_count, validate_request


class BCPackProvisionalWarning(UserWarning):
    """Decoded bytes depend on history observed only in a provisional oracle."""


def unzigzag(v):
    return -(v // 2) - 1 if v & 1 else v // 2


def reference_symbol(symbols, codec, block):
    """Undo the two-element formats' even/odd bit split."""
    if codec == 4:
        return symbols[0][block]
    a, b = symbols[0][2 * block:2 * block + 2]
    return sum(((a >> k) & 1) << (2 * k) |
               ((b >> k) & 1) << (2 * k + 1) for k in range(4))


def endpoint_layout(codec):
    if codec == 4:
        return (128, 128), (256, 256)
    if codec == 5:
        return (128,) * 4, (256,) * 4
    return (128, 128, 0, 0, 0, 0, 0, 0), (256, 256, 32, 64, 32, 32, 64, 32)


def residuals(symbols, codec, block):
    """Deltas in output endpoint order (BC3 alpha, then RGB565)."""
    if codec == 4:
        values = (symbols[2][block], symbols[3][block])
    elif codec == 5:
        values = tuple(symbols[lane][2 * block + p]
                       for lane in (2, 3) for p in (0, 1))
    else:
        values = tuple(symbols[2][2 * block + p] for p in (0, 1)) + tuple(
            symbols[lane][2 * block + p] for p in (0, 1) for lane in (7, 8, 9))
    return tuple(unzigzag(v) for v in values)


def index_ranks(symbols, codec, block):
    """Yield (codebook, rank, component, pixel-pair/quadrant) in output order."""
    if codec == 4:
        for p in range(8):
            yield "pairs", symbols[4 + p][block], 0, p
    else:
        for ch in range(2 if codec == 5 else 1):
            for p in range(8):
                lane = (4 + 4 * ch if codec == 5 else 3) + p // 2
                yield "pairs", symbols[lane][2 * block + p % 2], ch, p
        if codec == 3:
            for q in range(4):
                yield "quads", symbols[10 + q // 2][2 * block + q % 2], 0, q


def block_endpoints(block, codec):
    """Read public BCn endpoint fields; used by the independent fitter."""
    if codec == 4:
        return tuple(block[:2])
    if codec == 5:
        return tuple(block[:2] + block[8:10])
    c0, c1 = struct.unpack_from("<HH", block, 8)
    return tuple(block[:2]) + (c0 >> 11, (c0 >> 5) & 63, c0 & 31,
                              c1 >> 11, (c1 >> 5) & 63, c1 & 31)


QUADRANTS = ((0, 1, 4, 5), (2, 3, 6, 7), (8, 9, 12, 13), (10, 11, 14, 15))


@lru_cache(maxsize=1)
def load_tables():
    path = Path(__file__).with_name("data") / "bc345_tables.json"
    with path.open(encoding="utf-8") as handle:
        tables = json.load(handle)
    for key, values, size, limit in (
            [("pairs", tables["pairs"][str(c)], 64, 64) for c in (3, 4, 5)]
            + [("quads", tables["quads"], 256, 256)]):
        if len(values) != size or any(
                v is not None and (type(v) is not int or not 0 <= v < limit)
                for v in values):
            raise ValueError("invalid BC3/4/5 index table")
    for codec in (3, 4, 5):
        slots = tables["history"][str(codec)]
        _, mods = endpoint_layout(codec)
        if len(slots) != 256 or any(
                row is not None and (len(row) != len(mods) or any(
                    type(v) is not int or not 0 <= v < m for v, m in zip(row, mods)))
                for row in slots):
            raise ValueError("invalid BC3/4/5 history table")
    provisional = tables.get("provenance", {}).get("provisional_history", {})
    if not isinstance(provisional, dict) or set(provisional) - {"3", "4", "5"}:
        raise ValueError("invalid provisional history metadata")
    for codec, slots in provisional.items():
        if (not isinstance(slots, list) or any(type(s) is not int or not 1 <= s <= 255 for s in slots)
                or len(set(slots)) != len(slots)
                or any(tables["history"][codec][s] is None for s in slots)):
            raise ValueError("invalid provisional history metadata")
    return tables


def assemble(symbols, codec, out_size, tables=None):
    """Rebuild exact BCn blocks from twelve validated symbol vectors."""
    blocks = validate_request(codec, out_size)
    count = element_count(codec, out_size)
    widths = CODECS[codec]["default_widths"]
    if len(symbols) != 12 or any(len(lane) != count for lane in symbols):
        raise ValueError("BCPack lane element count mismatch")
    for lane, (values, width) in enumerate(zip(symbols, widths)):
        if any(type(v) is not int or not 0 <= v < 1 << width for v in values):
            raise ValueError(f"BCPack lane {lane}: symbol outside alphabet")
    if any(symbols[1]):
        raise ValueError(f"BCPack codec {codec}: non-zero lane 1 is unsupported")
    tables = load_tables() if tables is None else tables
    zero, mods = endpoint_layout(codec)
    endpoints = []
    provisional = set(tables.get("provenance", {}).get("provisional_history", {}).get(str(codec), []))
    used_provisional = set()
    out = bytearray()
    for i in range(blocks):
        d = unzigzag(reference_symbol(symbols, codec, i)) % 256
        if d == 0:
            predictor = zero
        elif d <= i:
            predictor = endpoints[i - d]
        else:
            slot = 256 + i - d
            predictor = tables["history"][str(codec)][slot]
            if predictor is None:
                raise ValueError(f"BCPack codec {codec}: unfitted history entry {slot} at block {i}")
            if slot in provisional:
                used_provisional.add(slot)
        ep = tuple((v + delta) % m for v, delta, m in zip(
            predictor, residuals(symbols, codec, i), mods))
        endpoints.append(ep)
        words = [0, 0]
        colour = 0
        for kind, rank, ch, position in index_ranks(symbols, codec, i):
            pattern = (tables["pairs"][str(codec)] if kind == "pairs"
                       else tables["quads"])[rank]
            if pattern is None:
                raise ValueError(f"BCPack codec {codec}: unfitted {kind} rank {rank}")
            if kind == "pairs":
                words[ch] |= pattern << (6 * position)
            else:
                for k, pixel in enumerate(QUADRANTS[position]):
                    colour |= ((pattern >> (2 * k)) & 3) << (2 * pixel)
        out += bytes(ep[:2]) + words[0].to_bytes(6, "little")
        if codec == 5:
            out += bytes(ep[2:]) + words[1].to_bytes(6, "little")
        elif codec == 3:
            c0 = ep[2] << 11 | ep[3] << 5 | ep[4]
            c1 = ep[5] << 11 | ep[6] << 5 | ep[7]
            out += struct.pack("<HHI", c0, c1, colour)
    if len(out) != out_size:
        raise ValueError("BCPack output size mismatch")
    if used_provisional:
        warnings.warn(f"BCPack codec {codec}: provisional history entries "
                      + ", ".join(map(str, sorted(used_provisional)))
                      + "; decoded bytes lack independent confirmation",
                      BCPackProvisionalWarning, stacklevel=2)
    return bytes(out)
