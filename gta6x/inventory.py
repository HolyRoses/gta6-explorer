"""Inventory, classification and hash verification.

Hashing policy matches the analysis document: whole-file SHA-256 for small
files, and a documented sampled fingerprint for the multi-gigabyte archives
(reading 208 GiB is a ~80 minute job at typical external-drive speed).

Sampled fingerprint definition::

    SHA-256( uint64le(file_size) || first 8 MiB || last 8 MiB )
"""

from __future__ import annotations

import hashlib
import os
import struct

FULL_HASH_LIMIT = 100 * 1024 * 1024
SAMPLE_CHUNK = 8 * 1024 * 1024

_TYPES = {
    ".rpf": "RPF9 archive",
    ".ttpf": "RDS5 resource",
    ".dll": "PE32+ DLL",
    ".xvd": "XVD container",
    ".png": "PNG art",
    ".xml": "XML manifest",
    ".config": "GDK config",
    ".pri": "MRM index",
    ".chunk": "marker",
    ".bin": "binary metadata",
}

__all__ = [
    "classify", "walk", "sha256_file", "sampled_fingerprint", "fingerprint",
    "verify_manifest", "totals",
]


def classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in _TYPES:
        return _TYPES[ext]
    if ext.startswith(".alignment"):
        return "marker"
    return ext.lstrip(".").upper() + " file" if ext else "file"


def sha256_file(path: str | os.PathLike, limit: int | None = None) -> str:
    digest = hashlib.sha256()
    remaining = limit
    with open(path, "rb") as fh:
        while True:
            want = 4 * 1024 * 1024 if remaining is None else min(4 * 1024 * 1024, remaining)
            if want <= 0:
                break
            block = fh.read(want)
            if not block:
                break
            digest.update(block)
            if remaining is not None:
                remaining -= len(block)
    return digest.hexdigest()


def sampled_fingerprint(path: str | os.PathLike, chunk: int = SAMPLE_CHUNK) -> str:
    size = os.path.getsize(path)
    digest = hashlib.sha256()
    digest.update(struct.pack("<Q", size))
    with open(path, "rb") as fh:
        digest.update(fh.read(chunk))
        if size > chunk:
            fh.seek(-chunk, os.SEEK_END)
            digest.update(fh.read(chunk))
    return digest.hexdigest()


def fingerprint(path: str | os.PathLike) -> tuple[str, str]:
    """Return (method, hexdigest) honouring the size policy."""
    if os.path.getsize(path) <= FULL_HASH_LIMIT:
        return "sha256", sha256_file(path)
    return "sampled", sampled_fingerprint(path)


def walk(root: str | os.PathLike, do_hash: bool = True) -> list[dict]:
    root = os.fspath(root)
    rows: list[dict] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                st = os.stat(path)
            except OSError:
                continue
            method, digest = fingerprint(path) if do_hash else ("skipped", "")
            rows.append({
                "path": os.path.relpath(path, root),
                "type": classify(name),
                "size": st.st_size,
                "mtime": st.st_mtime,
                "hash_method": method,
                "hash": digest,
            })
    rows.sort(key=lambda r: r["path"])
    return rows


def totals(rows: list[dict]) -> dict:
    by_type: dict[str, dict] = {}
    for row in rows:
        slot = by_type.setdefault(row["type"], {"files": 0, "bytes": 0})
        slot["files"] += 1
        slot["bytes"] += row["size"]
    return {
        "files": len(rows),
        "bytes": sum(r["size"] for r in rows),
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1]["bytes"])),
    }


def verify_manifest(root: str | os.PathLike, manifest: str | os.PathLike) -> dict:
    """Check a `shasum -a 256` style manifest (``<hex>  ./path``) against disk."""
    root = os.fspath(root)
    ok, bad, missing, unknown = [], [], [], []
    with open(manifest, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            expected, rel = parts[0].lower(), parts[1].lstrip("*")
            path = os.path.join(root, rel.lstrip("./"))
            if not os.path.isfile(path):
                missing.append(rel)
                continue
            try:
                if os.path.getsize(path) > FULL_HASH_LIMIT:
                    # try the cheap fingerprint first, then fall back to a full read
                    got, method = sampled_fingerprint(path), "sampled"
                    if got != expected:
                        got, method = sha256_file(path), "sha256"
                else:
                    got, method = sha256_file(path), "sha256"
            except OSError:
                missing.append(rel)
                continue
            (ok if got == expected else bad).append({"path": rel, "expected": expected,
                                                     "got": got, "method": method})
    return {"ok": ok, "bad": bad, "missing": missing, "unknown": unknown}
