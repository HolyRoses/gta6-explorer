"""32-bit name hashes (joaat) and a local name dictionary.

RAGE uses Jenkins one-at-a-time ("joaat") over the lower-case name for shader,
parameter, field and texture names. GTA VI does not ship the strings, but many
of them are recoverable from XML/text definitions, shader metadata and the
reconstructed path list. This module builds that hash -> name index locally and
resolves hashes without any game data being committed.

Two hashes are indexed per capitalized name: the lower-case form (the usual
lookup key) and the case-sensitive form (used by meta field names).
"""

from __future__ import annotations

import os
import re
from typing import Iterable

from . import zlibcarve

__all__ = ["joaat", "joaat_exact", "murmur3_x64_128", "hash64",
           "identifiers", "scan_cstrings", "build", "load", "lookup",
           "lookup64"]

IDENT = re.compile(rb"[0-9A-Za-z_]{3,96}")


def joaat(name: str) -> int:
    """Jenkins one-at-a-time over ASCII lower-case bytes."""
    h = 0
    for byte in name.lower().encode("ascii", "replace"):
        h = (h + byte) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


def joaat_exact(name: str) -> int:
    """joaat without case folding (meta field names)."""
    h = 0
    for byte in name.encode("ascii", "replace"):
        h = (h + byte) & 0xFFFFFFFF
        h = (h + (h << 10)) & 0xFFFFFFFF
        h ^= h >> 6
    h = (h + (h << 3)) & 0xFFFFFFFF
    h ^= h >> 11
    h = (h + (h << 15)) & 0xFFFFFFFF
    return h


def murmur3_x64_128(data: bytes, seed: int = 0) -> tuple[int, int]:
    """MurmurHash3 x64 128-bit reference implementation (public algorithm)."""
    mask = 0xFFFFFFFFFFFFFFFF

    def rotl(value: int, bits: int) -> int:
        return ((value << bits) | (value >> (64 - bits))) & mask

    def fmix(value: int) -> int:
        value ^= value >> 33
        value = (value * 0xFF51AFD7ED558CCD) & mask
        value ^= value >> 33
        value = (value * 0xC4CEB9FE1A85EC53) & mask
        value ^= value >> 33
        return value

    c1, c2 = 0x87C37B91114253D5, 0x4CF5AD432745937F
    h1 = h2 = seed & mask
    blocks = len(data) // 16
    for index in range(blocks):
        k1 = int.from_bytes(data[index * 16:index * 16 + 8], "little")
        k2 = int.from_bytes(data[index * 16 + 8:index * 16 + 16], "little")
        k1 = (k1 * c1) & mask
        k1 = rotl(k1, 31)
        k1 = (k1 * c2) & mask
        h1 ^= k1
        h1 = rotl(h1, 27)
        h1 = (h1 + h2) & mask
        h1 = (h1 * 5 + 0x52DCE729) & mask
        k2 = (k2 * c2) & mask
        k2 = rotl(k2, 33)
        k2 = (k2 * c1) & mask
        h2 ^= k2
        h2 = rotl(h2, 31)
        h2 = (h2 + h1) & mask
        h2 = (h2 * 5 + 0x38495AB5) & mask
    tail = data[blocks * 16:]
    k1 = k2 = 0
    for i, byte in enumerate(tail):
        if i < 8:
            k1 |= byte << (8 * i)
        else:
            k2 |= byte << (8 * (i - 8))
    if tail:
        if len(tail) > 8:
            k2 = (k2 * c2) & mask
            k2 = rotl(k2, 33)
            k2 = (k2 * c1) & mask
            h2 ^= k2
        k1 = (k1 * c1) & mask
        k1 = rotl(k1, 31)
        k1 = (k1 * c2) & mask
        h1 ^= k1
    h1 ^= len(data)
    h2 ^= len(data)
    h1 = (h1 + h2) & mask
    h2 = (h2 + h1) & mask
    h1 = fmix(h1)
    h2 = fmix(h2)
    h1 = (h1 + h2) & mask
    h2 = (h2 + h1) & mask
    return h1, h2


def hash64(name: str) -> int:
    """Low 64 bits of MurmurHash3 x64 128 (seed 0) over exact UTF-8 bytes."""
    return murmur3_x64_128(name.encode("utf-8"))[0]


def identifiers(data: bytes) -> set[str]:
    """Identifier-like words (3..96 chars, letters/digits/underscore)."""
    out: set[str] = set()
    for match in IDENT.finditer(data):
        word = match.group()
        if any(c < 0x80 and chr(c).isalpha() for c in word):
            out.add(word.decode("ascii"))
    return out


def scan_cstrings(path: str | os.PathLike, chunk: int = 8 << 20) -> set[str]:
    """NUL-delimited identifiers in a binary file (shaders.rpf)."""
    out: set[str] = set()
    carry = b""
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            parts = (carry + block).split(b"\x00")
            carry = parts.pop()
            for word in parts:
                if 4 <= len(word) <= 96:
                    try:
                        text = word.decode("ascii")
                    except UnicodeDecodeError:
                        continue
                    if text[0].isalpha() or text[0] == "_":
                        if all(c.isalnum() or c == "_" for c in text):
                            out.add(text)
    return out


def _merge64(dictionary: dict, source: str, names: Iterable[str]) -> int:
    added = 0
    buckets = dictionary.setdefault("hashes64", {})
    for name in names:
        for spelling in {name, name.lower()}:
            key = f"{hash64(spelling):016x}"
            bucket = buckets.setdefault(key, [])
            if not any(existing == spelling and src == source
                       for existing, src in bucket):
                bucket.append([spelling, source])
                added += 1
    return added


def _merge(dictionary: dict, source: str, names: Iterable[str]) -> int:
    added = 0
    for name in names:
        lower = name.lower()
        key = f"{joaat(lower):08x}"
        bucket = dictionary["hashes"].setdefault(key, [])
        for index, (existing, src) in enumerate(bucket):
            if src != source or existing.lower() != lower:
                continue
            if not existing.islower() and name.islower():
                bucket[index] = [name, source]
            break
        else:
            bucket.append([name, source])
            added += 1
        if any(c.isupper() for c in name):
            ekey = f"{joaat_exact(name):08x}"
            ebucket = dictionary["exact"].setdefault(ekey, [])
            if not any(existing == name and src == source
                       for existing, src in ebucket):
                ebucket.append([name, source])
    return added


def build(root: str, paths_file: str | None = None,
          include_shaders: bool = True) -> dict:
    """Collect names from common.rpf, shaders.rpf and the recovered path list."""
    dictionary = {"version": 1, "hashes": {}, "exact": {}, "counts": {}}
    common = os.path.join(root, "common.rpf")
    if os.path.isfile(common):
        names: set[str] = set()
        for blob in zlibcarve.carve_streams(common, min_out=64):
            names |= identifiers(blob.data)
        dictionary["counts"]["common"] = len(names)
        _merge(dictionary, "common", names)
        _merge64(dictionary, "common", names)
    if include_shaders:
        shaders = os.path.join(root, "shaders.rpf")
        if os.path.isfile(shaders):
            names = scan_cstrings(shaders)
            dictionary["counts"]["shaders"] = len(names)
            _merge(dictionary, "shaders", names)
            _merge64(dictionary, "shaders", names)
    if paths_file is None:
        repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        candidate = os.path.join(repo, "recovered", "paths.txt")
        paths_file = candidate if os.path.isfile(candidate) else None
    if paths_file and os.path.isfile(paths_file):
        names = set()
        with open(paths_file, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                names |= identifiers(line.encode("utf-8", "replace"))
        dictionary["counts"]["paths"] = len(names)
        _merge(dictionary, "paths", names)
        _merge64(dictionary, "paths", names)
    for bucket in list(dictionary["hashes"].values()) + list(dictionary["exact"].values()):
        bucket.sort(key=lambda item: (item[0] != item[0].lower(), item[0]))
    for bucket in dictionary.get("hashes64", {}).values():
        bucket.sort(key=lambda item: (item[0] != item[0].lower(), item[0]))
    return dictionary


def load(path: str | os.PathLike) -> dict:
    import json
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def lookup(dictionary: dict, value: str) -> list[tuple[str, str]]:
    text = value.strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    try:
        number = int(text, 16)
    except ValueError:
        return []
    if len(text) > 8:
        key = f"{number & 0xFFFFFFFFFFFFFFFF:016x}"
        return [(name, source) for name, source in
                dictionary.get("hashes64", {}).get(key, [])]
    key = f"{number & 0xFFFFFFFF:08x}"
    found = [(name, source) for name, source in dictionary.get("hashes", {}).get(key, [])]
    found += [(name, f"{source} (case-sensitive)")
              for name, source in dictionary.get("exact", {}).get(key, [])]
    return found


def lookup64(dictionary: dict, value: int) -> list[tuple[str, str]]:
    key = f"{value & 0xFFFFFFFFFFFFFFFF:016x}"
    return [(name, source) for name, source in
            dictionary.get("hashes64", {}).get(key, [])]
