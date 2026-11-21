"""`PSIN` metadata containers.

A complete ``PSIN`` resource is a container of seven tagged sections::

    "PSIN" u32 BE length     <- section 1: the entry table + payload ("body")
    "LSCH" u32 BE length     <- section 2
    "LENM" u32 BE length     <- section 3
    "LSNS" u32 BE length     <- section 4
    "LGID" u32 BE length     <- section 5
    "LRSC" u32 BE length     <- section 6
    "CHKS" u32 BE length     <- section 7, always 20 bytes:
                                u32 BE total length
                                u32 BE stored checksum
                                u32 BE platform tag

The section lengths tile the blob exactly: the last one ends on the final byte,
and the CHKS total-length field repeats ``len(data)``.  This is the grammar that
community tools validate ("seven complete sections, matching CHKS total
length"); we reproduced it on 261 of 300 sampled ``psin-page`` assets.

The ``PSIN`` section body
-------------------------
The first section is itself structured -- an entry table with fill padding::

    +0x00  "PSIN"
    +0x04  u32 BE  declared size / upper bound      (528, 544, 2144, ...)
    +0x08  u32 LE  field A                          (256, 512, ...)
    +0x0c  u32 LE  field B                          (16, 24, ...)
    +0x10  entries, 8 bytes each: (u32 a, u32 b)
           unused slots are filled with 0xAAAAAAAA, and the table ends with a
           0x70707070 ("pppp") fill run
    ...    payload

An earlier version of this module treated that body as a standalone container
format.  It is not: it is section 1 of the tagged container, which is why the
``PSIN`` section length (not a small "declared size") is what appears at +0x04.

Fragments
---------
Some PSIN resources are larger than one zlib page and are stream-split.  A
single stream then begins with ``PSIN`` and declares a section longer than the
available page.  Those are reported as *fragments* carrying the declared size,
the available size and whatever body prefix could be read -- not as a different
format.  The remaining 39/300 sampled assets are exactly this case.

The ``CHKS`` checksum algorithm is still unknown; the stored value is exposed
but not verified.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

MAGIC = b"PSIN"
CONTAINER_TAGS = (b"PSIN", b"LSCH", b"LENM", b"LSNS", b"LGID", b"LRSC", b"CHKS")
CHKS_LENGTH = 20

ENTRY_STRIDE = 16          # measured: 8 bytes of data + 8 bytes of 0xAA fill
TABLE_BASE = 0x20          # entry table starts after the 32-byte body header
FILL_AA = 0xAAAAAAAA
FILL_PP = 0x70707070
HEADER_SIZE = 0x10
ENTRY_SIZE = 8

__all__ = [
    "MAGIC", "CONTAINER_TAGS", "PsinSection", "PsinBody", "PsinContainer",
    "PsinFragment", "parse", "parse_container", "parse_body", "parse_page",
    "is_psin", "summarise",
]


@dataclass(frozen=True)
class PsinSection:
    tag: str
    offset: int
    length: int

    def as_dict(self) -> dict:
        return {"tag": self.tag, "offset": self.offset, "length": self.length}


@dataclass
class PsinBody:
    """The entry-table body inside the ``PSIN`` section."""

    declared_size: int
    field_a: int
    field_b: int
    entries: list[tuple[int, int]] = field(default_factory=list)
    entry_stride: int = ENTRY_STRIDE
    record_count: int = 0
    has_terminator: bool = False
    field_a_kind: str = "unknown"
    payload_offset: int = HEADER_SIZE
    payload_size: int = 0
    fill: str = "none"
    total_size: int = 0
    truncated: bool = False
    confident: bool = False
    kind: str = "body"

    def as_dict(self) -> dict:
        return {
            "declared_size": self.declared_size,
            "field_a": self.field_a,
            "field_a_kind": self.field_a_kind,
            "field_b": self.field_b,
            "entries": len(self.entries),
            "entry_stride": self.entry_stride,
            "record_count": self.record_count,
            "has_terminator": self.has_terminator,
            "entries_sample": self.entries[:6],
            "payload_offset": self.payload_offset,
            "payload_size": self.payload_size,
            "fill": self.fill,
            "total_size": self.total_size,
            "truncated": self.truncated,
            "confident": self.confident,
        }


@dataclass
class PsinContainer:
    """A complete seven-section container."""

    sections: list[PsinSection] = field(default_factory=list)
    stored_checksum: int = 0
    platform_tag: int = 0
    total_size: int = 0
    body: PsinBody | None = None
    kind: str = "container"

    @property
    def checksum_verified(self) -> bool:
        return False  # algorithm not established yet

    def section(self, tag: str) -> PsinSection | None:
        for sec in self.sections:
            if sec.tag == tag:
                return sec
        return None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "total_size": self.total_size,
            "sections": [s.as_dict() for s in self.sections],
            "stored_checksum": f"0x{self.stored_checksum:08X}",
            "platform_tag": f"0x{self.platform_tag:08X}",
            "checksum_verified": self.checksum_verified,
            "body": self.body.as_dict() if self.body else None,
        }


@dataclass
class PsinFragment:
    """A stream-split prefix of a PSIN section (declared size > available)."""

    declared_size: int
    available: int
    field_a: int = 0
    field_b: int = 0
    total_size: int = 0
    body: PsinBody | None = None
    kind: str = "fragment"

    @property
    def missing(self) -> int:
        return max(0, self.declared_size - self.available)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "declared_size": self.declared_size,
            "available": self.available,
            "missing": self.missing,
            "field_a": self.field_a,
            "field_b": self.field_b,
            "total_size": self.total_size,
            "body": self.body.as_dict() if self.body else None,
        }


def is_psin(data: bytes) -> bool:
    return len(data) >= 8 and data[:4] == MAGIC


def _sections_tile(data: bytes) -> list[PsinSection] | None:
    """Return the seven sections if their lengths exactly tile ``data``."""
    if len(data) < 8 + 5 * 8 + CHKS_LENGTH or data[:4] != MAGIC:
        return None
    sections: list[PsinSection] = []
    pos = 0
    for tag in CONTAINER_TAGS:
        if pos + 8 > len(data):
            return None
        if data[pos:pos + 4] != tag:
            return None
        length = struct.unpack_from(">I", data, pos + 4)[0]
        if length < 8 or length > len(data) - pos:
            return None
        sections.append(PsinSection(tag.decode("ascii"), pos, length))
        pos += length
    return sections if pos == len(data) else None


def parse_container(data: bytes) -> PsinContainer | None:
    """Parse a complete seven-section container."""
    sections = _sections_tile(data)
    if not sections:
        return None
    chks = sections[-1]
    if chks.length != CHKS_LENGTH:
        return None
    base = chks.offset
    if struct.unpack_from(">I", data, base + 8)[0] != len(data):
        return None
    stored = struct.unpack_from(">I", data, base + 12)[0]
    platform = struct.unpack_from(">I", data, base + 16)[0]
    body_sec = sections[0]
    body = parse_body(data[body_sec.offset: body_sec.offset + body_sec.length])
    return PsinContainer(sections, stored, platform, len(data), body)


def parse_body(data: bytes) -> PsinBody | None:
    """Parse the ``PSIN`` section body (entry table + fill + payload)."""
    if len(data) < HEADER_SIZE or data[:4] != MAGIC:
        return None
    declared = struct.unpack_from(">I", data, 4)[0]
    field_a, field_b = struct.unpack_from("<2I", data, 8)

    def is_fill(a: int, b: int) -> bool:
        return a in (FILL_AA, FILL_PP, 0) and b in (FILL_AA, FILL_PP, 0)

    slots: list[tuple[int, int, int]] = []
    pos = HEADER_SIZE
    while pos + ENTRY_SIZE <= len(data):
        a, b = struct.unpack_from("<2I", data, pos)
        slots.append((pos, a, b))
        pos += ENTRY_SIZE

    # Payload starts at the first non-fill slot that has a non-fill successor
    # and follows padding -- that is where the entry table ends.
    payload_at = len(data)
    for k in range(len(slots) - 1):
        a, b = slots[k][1], slots[k][2]
        na, nb = slots[k + 1][1], slots[k + 1][2]
        if is_fill(a, b) or is_fill(na, nb):
            continue
        if k == 0 or is_fill(slots[k - 1][1], slots[k - 1][2]):
            payload_at = slots[k][0]
            break

    entries = [(a, b) for p, a, b in slots
               if p < payload_at and not is_fill(a, b)]
    fill = "none"
    for p, a, b in slots:
        if p >= payload_at:
            break
        if FILL_AA in (a, b):
            fill = "AA"
        elif FILL_PP in (a, b):
            fill = "70"

    body = PsinBody(
        declared_size=declared,
        field_a=field_a,
        field_b=field_b,
        entries=entries,
        payload_offset=payload_at,
        payload_size=max(0, len(data) - payload_at),
        fill=fill,
        total_size=len(data),
        truncated=declared > len(data),
    )
    span = max(0, body.payload_offset - TABLE_BASE)
    body.record_count = span // ENTRY_STRIDE
    body.has_terminator = (span % ENTRY_STRIDE) == 8
    body.field_a_kind = ("type-tag" if field_a <= 0x10000 else
                         "hash-or-float" if field_a else "zero")
    body.confident = (
        0 < declared <= max(len(data), 1 << 20)
        and body.payload_size > 0
        and body.payload_offset <= len(data)
        and len(entries) <= 512
        and not body.truncated
    )
    return body


#: Backwards-compatible name: the old code called the body a "page".
parse_page = parse_body


def parse(data: bytes) -> PsinContainer | PsinBody | None:
    """Parse a container, a standalone body, or None.

    A stream-split fragment (declared section longer than the data) is parsed
    with :func:`parse_fragment` instead, so callers that want fragment support
    should use it explicitly or accept a body with ``truncated=True``.
    """
    container = parse_container(data)
    if container:
        return container
    body = parse_body(data)
    if body and body.declared_size == len(data):
        return body
    return body if body and not body.truncated else None


def parse_fragment(data: bytes) -> PsinFragment | None:
    """Parse a stream-split PSIN prefix (container declared larger than data)."""
    if not is_psin(data):
        return None
    declared = struct.unpack_from(">I", data, 4)[0]
    if declared <= len(data) - 8:
        return None
    field_a, field_b = struct.unpack_from("<2I", data, 8) if len(data) >= 16 else (0, 0)
    return PsinFragment(declared_size=declared, available=len(data),
                        field_a=field_a, field_b=field_b,
                        total_size=len(data), body=parse_body(data))


def summarise(items: list[PsinContainer | PsinBody | PsinFragment]) -> dict:
    """Aggregate stats over containers, bodies and fragments."""
    import collections
    containers = [i for i in items if i.kind == "container"]
    fragments = [i for i in items if i.kind == "fragment"]
    body_objs = []
    for item in items:
        body = getattr(item, "body", None)
        if body is not None:
            body_objs.append(body)
        elif item.kind == "body":
            body_objs.append(item)
    tags: collections.Counter[str] = collections.Counter()
    for c in containers:
        for sec in c.sections:
            tags[sec.tag] += 1
    decl = collections.Counter(b.declared_size for b in body_objs)
    fills = collections.Counter(b.fill for b in body_objs)
    entries = [len(b.entries) for b in body_objs]
    payloads = [b.payload_size for b in body_objs]
    return {
        "total": len(items),
        "containers": len(containers),
        "fragments": len(fragments),
        "bodies": len(body_objs),
        "confident": (sum(1 for i in items if i.kind == "container")
                      + sum(1 for i in items if i.kind == "body" and i.confident)),
        "section_tags": tags.most_common(),
        "declared_size_top": decl.most_common(6),
        "fill_top": fills.most_common(),
        "entries_min": min(entries) if entries else 0,
        "entries_max": max(entries) if entries else 0,
        "entries_avg": round(sum(entries) / len(entries), 1) if entries else 0,
        "payload_total": sum(payloads),
        "payload_avg": round(sum(payloads) / len(payloads), 1) if payloads else 0,
        "container_bytes": sum(c.total_size for c in containers),
        "fragment_missing": sum(f.missing for f in fragments),
    }
