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
The supported block table begins at +8. Each little-endian (type identifier,
byte length) pair is followed by eight AA bytes. Eight literal ``p`` bytes end
the table. Block payloads follow in table order, each padded to 16 bytes with
zeroes, and exactly exhaust the section. Type identifiers are raw values, not
proof of scalar or schema meanings. A table entry describes a block, not a
record within that block.

The compatibility fields ``field_a`` and ``field_b`` expose the raw words at
+8/+12: normally the first block's type and length, or the terminator words for
an empty body. ``entries`` and ``record_count`` now count verified table pairs,
including the first pair. Missing table terminators leave payload bounds unknown.
Unsupported bodies remain explicit even inside checksum-verified containers.

Fragments
---------
Some PSIN resources are larger than one zlib page and are stream-split.  A
single stream then begins with ``PSIN`` and declares a section longer than the
available page.  Those are reported as *fragments* carrying the declared size,
the available size and whatever body prefix could be read -- not as a different
format.  The remaining 39/300 sampled assets are exactly this case.

The ``CHKS`` checksum is now verified: RAGE JOOAT (signed bytes) with seed
``0x3FAC7125`` over the whole container, with the ``CHKS`` length and checksum
fields zeroed.  It matches every complete container sampled from the local
GTA VI package.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .psin_blocks import InstanceBlock, parse_blocks

MAGIC = b"PSIN"
CONTAINER_TAGS = (b"PSIN", b"LSCH", b"LENM", b"LSNS", b"LGID", b"LRSC", b"CHKS")
CHKS_LENGTH = 20
CHKS_SEED = 0x3FAC7125

ENTRY_STRIDE = 16          # measured: 8 bytes of data + 8 bytes of 0xAA fill
TABLE_BASE = 8             # first type/byte-length pair follows the section header
FILL_AA = 0xAAAAAAAA
FILL_PP = 0x70707070
HEADER_SIZE = 0x10
ENTRY_SIZE = 8

__all__ = [
    "MAGIC", "CONTAINER_TAGS", "CHKS_SEED", "PsinSection", "PsinBody",
    "PsinContainer", "PsinFragment", "joaat_checksum", "container_checksum",
    "parse", "parse_container", "parse_body", "parse_page", "parse_fragment", "is_psin",
    "summarise",
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
    """Block framing inside the ``PSIN`` section, including partial prefixes.

    ``record_count`` is a compatibility alias for verified table-pair count;
    it does not count typed instance records. Payload sizes describe the
    declared physical span; incomplete tables leave them unknown.
    """

    declared_size: int
    field_a: int
    field_b: int
    entries: list[tuple[int, int]] = field(default_factory=list)
    entry_stride: int = ENTRY_STRIDE
    record_count: int = 0
    has_terminator: bool = False
    field_a_kind: str = "unknown"
    payload_offset: int | None = None
    payload_size: int | None = None
    fill: str = "none"
    total_size: int = 0
    truncated: bool = False
    confident: bool = False
    kind: str = "body"
    status: str = "unresolved"
    reason: str | None = None
    table_complete: bool = False
    blocks: list[InstanceBlock] = field(default_factory=list)
    logical_payload_size: int | None = None
    padding_size: int | None = None

    @property
    def block_count(self) -> int | None:
        return len(self.entries) if self.table_complete else None

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
            "status": self.status,
            "reason": self.reason,
            "table_offset": TABLE_BASE,
            "table_complete": self.table_complete,
            "block_count": self.block_count,
            "logical_payload_size": self.logical_payload_size,
            "padding_size": self.padding_size,
            "blocks": [dict(index=b.index, table_offset=b.table_offset,
                            type_hash=b.type_hash, byte_length=b.byte_length,
                            data_offset=b.data_offset) for b in self.blocks],
        }


@dataclass
class PsinContainer:
    """A complete seven-section container."""

    sections: list[PsinSection] = field(default_factory=list)
    stored_checksum: int = 0
    platform_tag: int = 0
    total_size: int = 0
    body: PsinBody | None = None
    computed_checksum: int = 0
    kind: str = "container"

    @property
    def checksum_verified(self) -> bool:
        return self.computed_checksum == self.stored_checksum

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
            "computed_checksum": f"0x{self.computed_checksum:08X}",
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


def joaat_checksum(data: bytes, seed: int = CHKS_SEED) -> int:
    """RAGE JOOAT: signed bytes, one-at-a-time, with the finalisation steps."""
    value = seed & 0xFFFFFFFF
    for byte in data:
        value = (value + (byte - 256 if byte >= 128 else byte)) & 0xFFFFFFFF
        value = (value + (value << 10)) & 0xFFFFFFFF
        value ^= value >> 6
    value = (value + (value << 3)) & 0xFFFFFFFF
    value ^= value >> 11
    value = (value + (value << 15)) & 0xFFFFFFFF
    return value


def container_checksum(data: bytes, chks_offset: int) -> int:
    """JOOAT over a container with CHKS length+checksum zeroed."""
    body = bytearray(data)
    body[chks_offset + 8:chks_offset + 16] = b"\x00" * 8
    return joaat_checksum(bytes(body))


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
    computed = container_checksum(data, base)
    return PsinContainer(sections, stored, platform, len(data), body, computed)


def parse_body(data: bytes) -> PsinBody | None:
    """Inspect supported block framing; preserve explicit incomplete/unknown states.

    Prefix entries require a complete pair and AA marker. Payload bytes are
    never searched for table-like words. Complete bodies use the same exact
    bounds/padding validator as the instance reader.
    """
    if not is_psin(data):
        return None
    declared = struct.unpack_from(">I", data, 4)[0]
    field_a, field_b = struct.unpack_from("<2I", data, 8) if len(data) >= 16 else (0, 0)
    body = PsinBody(declared, field_a, field_b, total_size=len(data),
                    truncated=declared > len(data))

    def fail(reason: str, *, incomplete: bool = False) -> PsinBody:
        body.status = "partial" if incomplete else "unresolved"
        body.reason = reason
        return body

    if declared < 16:
        return fail("PSIN body is shorter than the supported empty table")
    if declared < len(data):
        return fail("bytes follow the declared PSIN body")
    end = min(declared, len(data))
    position = TABLE_BASE
    while True:
        if position + 8 > end:
            return fail("incomplete PSIN block-table terminator", incomplete=body.truncated)
        if data[position:position + 8] == b"p" * 8:
            position += 8
            body.table_complete = body.has_terminator = True
            body.payload_offset = position
            body.payload_size = declared - position
            body.fill = "AA/70" if body.entries else "70"
            body.field_a_kind = "first-block-type" if body.entries else "terminator"
            break
        if position + 16 > end:
            return fail("incomplete PSIN block-table entry", incomplete=body.truncated)
        if data[position + 8:position + 16] != b"\xaa" * 8:
            return fail("unsupported PSIN block-table marker")
        if len(body.entries) >= 65536:
            return fail("PSIN block count exceeds limit")
        key, size = struct.unpack_from("<II", data, position)
        if not size:
            return fail("zero-sized PSIN instance block is not validated")
        body.entries.append((key, size))
        body.record_count = len(body.entries)
        body.field_a_kind = "first-block-type"
        body.fill = "AA"
        position += ENTRY_STRIDE

    # Compute only declared extents, then check every available padding byte.
    logical = 0
    for index, (key, size) in enumerate(body.entries):
        block_end = position + size
        aligned = (block_end + 15) & ~15
        if aligned > declared:
            return fail("PSIN block or padding exceeds declared body")
        if any(data[block_end:min(aligned, end)]):
            return fail("nonzero PSIN instance block padding is not validated")
        body.blocks.append(InstanceBlock(index, TABLE_BASE + index * ENTRY_STRIDE,
                                         key, size, position))
        logical += size
        position = aligned
    if position != declared:
        return fail("unaccounted PSIN instance body bytes")
    body.logical_payload_size = logical
    body.padding_size = body.payload_size - logical
    if body.truncated:
        return fail("PSIN block payload or padding is incomplete", incomplete=True)
    try:
        body.blocks = parse_blocks(data)
    except ValueError as exc:
        return fail(str(exc))
    body.status, body.reason, body.confident = "complete", None, True
    return body


#: Backwards-compatible name: the old code called the body a "page".
parse_page = parse_body


def parse(data: bytes) -> PsinContainer | PsinBody | None:
    """Parse a container, a standalone body, or None.

    A stream-split fragment (declared section longer than the data) is parsed
    with :func:`parse_fragment` instead, so callers that want fragment support
    should use it explicitly.
    """
    container = parse_container(data)
    if container:
        return container
    body = parse_body(data)
    if body and body.declared_size == len(data):
        return body
    return None


def parse_fragment(data: bytes) -> PsinFragment | None:
    """Parse a stream-split PSIN prefix (container declared larger than data)."""
    if not is_psin(data):
        return None
    declared = struct.unpack_from(">I", data, 4)[0]
    if declared <= len(data):
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
    verified = sum(1 for c in containers if c.checksum_verified)
    for c in containers:
        for sec in c.sections:
            tags[sec.tag] += 1
    decl = collections.Counter(b.declared_size for b in body_objs)
    fills = collections.Counter(b.fill for b in body_objs)
    entries = [b.block_count for b in body_objs if b.block_count is not None]
    payloads = [b.payload_size for b in body_objs if b.payload_size is not None]
    statuses = collections.Counter(b.status for b in body_objs)
    return {
        "total": len(items),
        "containers": len(containers),
        "fragments": len(fragments),
        "bodies": len(body_objs),
        "body_statuses": dict(statuses),
        "bodies_with_known_table": len(entries),
        "bodies_with_known_payload": len(payloads),
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
        "checksums_verified": verified,
        "checksums_bad": len(containers) - verified,
    }
