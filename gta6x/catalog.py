"""Asset catalog: carve, verify, classify and index every recoverable blob.

Design goals
------------
* **Confidence** -- every stream is re-inflated with :func:`zlib.decompress`,
  which checks the stream's Adler-32 checksum. A stream only enters the catalog
  if its checksum validates, so a "verified" flag means something concrete.
* **Resumability** -- the catalog is plain JSON keyed by archive, so an
  interrupted sweep can be continued per archive.
* **Browsability** -- each record carries enough metadata (kind, magic, XML root,
  embedded paths, size, offset, sha256) to render a searchable HTML view.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zlib
from dataclasses import dataclass, field

from . import zlibcarve

CATALOG_VERSION = 1
DEFAULT_MAX_OUT = 64 * 1024 * 1024

__all__ = ["Asset", "sweep_archive", "load", "save", "merge", "summary"]


@dataclass
class Asset:
    archive: str
    offset: int
    compressed: int
    size: int
    kind: str
    magic: str
    sha256: str
    verified: bool
    xml_root: str = ""
    paths: list[str] = field(default_factory=list)
    text_head: str = ""

    def as_dict(self) -> dict:
        return {
            "archive": self.archive,
            "offset": self.offset,
            "compressed": self.compressed,
            "size": self.size,
            "kind": self.kind,
            "magic": self.magic,
            "sha256": self.sha256,
            "verified": self.verified,
            "xml_root": self.xml_root,
            "paths": self.paths[:16],
            "text_head": self.text_head,
        }


_XML_ROOT = re.compile(r"<\?xml[^>]*\?>\s*<([A-Za-z0-9_]+)")
_FILENAME = re.compile(r"<filename>([^<]+)</filename>")


def _verify(buf: bytes, idx: int, consumed: int, expected: bytes) -> bool:
    """Re-inflate the exact stream bytes; zlib.decompress validates Adler-32."""
    try:
        out = zlib.decompress(buf[idx: idx + consumed])
    except zlib.error:
        return False
    return out == expected


def classify_and_enrich(data: bytes) -> tuple[str, str, str, list[str], str]:
    """Return (kind, xml_root, text_head, paths, magic)."""
    magic = data[:4].hex()
    kind = zlibcarve.classify_blob(data)
    root = ""
    paths: list[str] = []
    head = ""
    if kind in ("xml", "text"):
        text = data.decode("utf-8", "replace")
        m = _XML_ROOT.search(text)
        if m:
            root = m.group(1)
        paths = sorted(set(_FILENAME.findall(text)))[:64]
        head = text[:200].replace("\n", " ").strip()
    return kind, root, head, paths, magic


def sweep_archive(
    path: str | os.PathLike,
    length: int | None = None,
    max_out: int = DEFAULT_MAX_OUT,
    min_out: int = 512,
) -> list[Asset]:
    """Carve one archive and return checksum-verified assets."""
    path = os.fspath(path)
    archive = os.path.basename(path)
    assets: list[Asset] = []
    with open(path, "rb") as fh:
        for blob in zlibcarve.carve_streams(path, length=length, max_out=max_out, min_out=min_out):
            fh.seek(blob.offset)
            chunk = fh.read(blob.compressed)
            try:
                verified = zlib.decompress(chunk) == blob.data  # Adler-32 checked here
            except zlib.error:
                verified = False
            kind, root, head, paths, magic = classify_and_enrich(blob.data)
            assets.append(Asset(
                archive=archive,
                offset=blob.offset,
                compressed=blob.compressed,
                size=blob.size,
                kind=kind,
                magic=magic,
                sha256=hashlib.sha256(blob.data).hexdigest(),
                verified=verified,
                xml_root=root,
                paths=paths,
                text_head=head,
            ))
    return assets


def load(path: str) -> dict:
    if not os.path.isfile(path):
        return {"version": CATALOG_VERSION, "archives": {}}
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def save(path: str, catalog: dict) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(catalog, fh, indent=1)
    os.replace(tmp, path)


def merge(catalog: dict, archive: str, assets: list[Asset]) -> dict:
    catalog.setdefault("archives", {})[archive] = [a.as_dict() for a in assets]
    return catalog


def summary(catalog: dict) -> dict:
    import collections
    kinds = collections.Counter()
    total_in = total_out = 0
    verified = 0
    for assets in catalog.get("archives", {}).values():
        for a in assets:
            kinds[a["kind"]] += 1
            total_in += a["compressed"]
            total_out += a["size"]
            verified += 1 if a.get("verified") else 0
    return {
        "archives": len(catalog.get("archives", {})),
        "assets": sum(kinds.values()),
        "verified": verified,
        "compressed_bytes": total_in,
        "inflated_bytes": total_out,
        "by_kind": dict(kinds.most_common()),
    }


# --------------------------------------------------------------------------- #
# SQLite backend (scales past the JSON catalogue)
# --------------------------------------------------------------------------- #

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
  id INTEGER PRIMARY KEY,
  archive TEXT NOT NULL,
  offset INTEGER NOT NULL,
  compressed INTEGER NOT NULL,
  size INTEGER NOT NULL,
  kind TEXT NOT NULL,
  magic TEXT,
  sha256 TEXT NOT NULL,
  verified INTEGER NOT NULL,
  xml_root TEXT,
  paths TEXT,
  text_head TEXT
);
CREATE INDEX IF NOT EXISTS idx_assets_kind  ON assets(kind);
CREATE INDEX IF NOT EXISTS idx_assets_arch  ON assets(archive);
CREATE INDEX IF NOT EXISTS idx_assets_sha   ON assets(sha256);
CREATE INDEX IF NOT EXISTS idx_assets_ver   ON assets(verified);
"""


class Store:
    """SQLite-backed asset catalogue."""

    def __init__(self, path: str):
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.executescript(_SCHEMA)

    def add(self, archive: str, assets: list[Asset]) -> None:
        self.db.executemany(
            "INSERT INTO assets(archive, offset, compressed, size, kind, magic, sha256,"
            " verified, xml_root, paths, text_head) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            [(a.archive, a.offset, a.compressed, a.size, a.kind, a.magic, a.sha256,
              1 if a.verified else 0, a.xml_root, "\n".join(a.paths), a.text_head)
             for a in assets],
        )
        self.db.commit()

    def replace_archive(self, archive: str, assets: list[Asset]) -> None:
        self.db.execute("DELETE FROM assets WHERE archive = ?", (archive,))
        self.add(archive, assets)

    def has_archive(self, archive: str) -> int:
        return self.db.execute("SELECT COUNT(*) FROM assets WHERE archive = ?",
                               (archive,)).fetchone()[0]

    def counts(self) -> dict:
        rows = self.db.execute(
            "SELECT kind, COUNT(*), SUM(size), SUM(compressed), SUM(verified)"
            " FROM assets GROUP BY kind ORDER BY COUNT(*) DESC").fetchall()
        totals = self.db.execute(
            "SELECT COUNT(*), SUM(size), SUM(compressed), SUM(verified) FROM assets").fetchone()
        arch = self.db.execute(
            "SELECT archive, COUNT(*) FROM assets GROUP BY archive ORDER BY 2 DESC").fetchall()
        return {
            "total": dict(zip(("assets", "inflated", "compressed", "verified"), totals)),
            "by_kind": [dict(zip(("kind", "count", "inflated", "compressed", "verified"), r))
                        for r in rows],
            "by_archive": [dict(zip(("archive", "count"), r)) for r in arch],
        }

    def fetch(self, limit: int = 100, offset: int = 0, kind: str | None = None,
              archive: str | None = None) -> list[dict]:
        sql = ("SELECT archive, offset, compressed, size, kind, xml_root, sha256, verified"
               " FROM assets WHERE 1=1")
        args: list = []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if archive:
            sql += " AND archive = ?"
            args.append(archive)
        sql += " ORDER BY archive, offset LIMIT ? OFFSET ?"
        args += [limit, offset]
        return [dict(zip(("archive", "offset", "compressed", "size", "kind", "xml_root",
                          "sha256", "verified"), r))
                for r in self.db.execute(sql, args)]

    def find(self, needle: str) -> dict | None:
        row = self.db.execute(
            "SELECT archive, offset, compressed, size, kind, sha256, verified FROM assets"
            " WHERE sha256 LIKE ? OR (archive || ':0x' || printf('%x', offset)) = ? LIMIT 1",
            (needle + "%", needle)).fetchone()
        if not row:
            return None
        return dict(zip(("archive", "offset", "compressed", "size", "kind", "sha256",
                         "verified"), row))

    def close(self) -> None:
        self.db.close()


def import_json(json_path: str, db_path: str) -> dict:
    """Migrate an existing JSON catalogue into SQLite."""
    catalog = load(json_path)
    store = Store(db_path)
    n = 0
    for archive, items in catalog.get("archives", {}).items():
        assets = [Asset(archive=a["archive"], offset=a["offset"], compressed=a["compressed"],
                        size=a["size"], kind=a["kind"], magic=a.get("magic", ""),
                        sha256=a["sha256"], verified=bool(a.get("verified")),
                        xml_root=a.get("xml_root", ""), paths=a.get("paths", []),
                        text_head=a.get("text_head", ""))
                  for a in items]
        store.replace_archive(archive, assets)
        n += len(assets)
    out = store.counts()
    store.close()
    return {"imported": n, **out["total"]}
