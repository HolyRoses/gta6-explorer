"""Recover complete XML and PSIN resources from stream-split zlib pages.

Large resources are stored as a chain of independently compressed pages. The
first page of a document is flagged by ``<?xml`` or ````PSIN``; continuation
pages follow at the next 16-byte boundary after the previous stream, separated
only by zero padding, and are not themselves a new document. Treating each
stream in isolation -- as a plain zlib carve does -- yields truncated XML and
PSIN resources.

This module measures the streams in an archive's payload area, follows the
continuation chain (only 64 KiB pages are joined, matching how the package
splits them), and validates the *joined* bytes before reporting them:

* XML is parsed by ElementTree, DTDs are rejected, and the document must have a
  closed root element.
* PSIN must be a complete seven-section container with matching CHKS checksum
  (see :mod:`gta6x.psin`). A short stored terminal tail can follow full zlib
  pages only when exact section lengths and CHKS authorize all its bytes.

The earlier zlib framing was cross-checked with rpf9-explorer during prior
research. The stored-terminal extension was derived independently from this
project's PSIN section/checksum rules and discovery-only package observations;
no additional upstream implementation was consulted. Whole/interior stored
pages and alternate PSIN section orders remain unsupported.
"""

from __future__ import annotations

from bisect import bisect_left
import os
import struct
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Iterator

from . import psin, rpf, zlibcarve

PAGE = 65536
MAX_OUTPUT = 16 * 1024 * 1024
MAX_DEPTH = 128
PREFIX = 512

__all__ = ["StructuredHit", "recover", "looks_xml", "looks_psin"]


@dataclass
class StructuredHit:
    archive: str
    offset: int
    kind: str                    # "xml" or "psin"
    root: str
    packed: int
    unpacked: int
    blocks: int
    segments: list[tuple[int, int, int]] = field(default_factory=list)
    data: bytes = b""
    segment_storage: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        result = {
            "archive": self.archive,
            "offset": self.offset,
            "offset_hex": f"0x{self.offset:x}",
            "kind": self.kind,
            "root": self.root,
            "blocks": self.blocks,
            "packed": self.packed,
            "unpacked": self.unpacked,
            "segments": self.segments,
        }
        if self.segment_storage:
            result["segment_storage"] = self.segment_storage
        return result


def _text_prefix(data: bytes) -> str:
    if data[:2] == b"\xff\xfe" or data[:2] == b"<\x00":
        encoding = "utf-16-le"
    elif data[:2] == b"\xfe\xff" or data[:2] == b"\x00<":
        encoding = "utf-16-be"
    else:
        encoding = "utf-8"
    try:
        text = data[:PREFIX].decode(encoding, "replace")
    except (LookupError, UnicodeError):
        text = data[:PREFIX].decode("utf-8", "replace")
    return text.lstrip("\ufeff \t\r\n")


def looks_psin(data: bytes) -> bool:
    return data[:4] == b"PSIN"


def looks_xml(data: bytes) -> bool:
    return _text_prefix(data).startswith("<")


def _declares_xml(data: bytes) -> bool:
    return _text_prefix(data).startswith("<?xml")


def _validate(data: bytes) -> tuple[str, str] | None:
    """Return (kind, root) when the joined bytes are a complete resource."""
    if data[:4] == b"PSIN":
        container = psin.parse_container(data)
        return ("psin", "PSIN") if container is not None and container.checksum_verified else None
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head:
        return None
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    tag = root.tag.split("}")[-1] if "}" in root.tag else root.tag
    return ("xml", tag or "document")


def _padding_zero(fh, start: int, end: int) -> bool:
    if end < start or end - start > 16:
        return False
    fh.seek(start)
    return set(fh.read(end - start)) <= {0}


def _psin_extent(data: bytes) -> int | None:
    """Measure a complete known section chain; never search inside payloads."""
    at = 0
    for tag in psin.CONTAINER_TAGS:
        if at + 8 > len(data) or data[at:at + 4] != tag:
            return None
        length = struct.unpack_from('>I', data, at + 4)[0]
        if length < 8 or length > MAX_OUTPUT - at:
            return None
        at += length
        if tag == b'CHKS':
            return at if length == psin.CHKS_LENGTH and at <= len(data) else None
    return None


def _stored_psin_tail(fh, blocks, scan_end):
    """Authorize one short stored terminal tail by exact sections and CHKS.

    Only full compressed pages precede it. A missing compressed stream alone
    is not evidence for a raw page. Full/interior raw pages are unsupported.
    Try each measured compressed boundary so a valid zlib signature inside an
    opaque raw tail cannot redirect or mask the checksum-authorized resource.
    """
    prefix = bytearray()
    for index, block in enumerate(blocks):
        if len(block.data) != PAGE:
            break
        prefix.extend(block.data)
        if len(prefix) >= MAX_OUTPUT:
            break
        end = block.offset + block.compressed
        start = (end + 15) & ~15
        if start >= scan_end or not _padding_zero(fh, end, start):
            continue
        fh.seek(start)
        tail = fh.read(min(PAGE, MAX_OUTPUT - len(prefix), scan_end - start))
        joined = bytes(prefix) + tail
        extent = _psin_extent(joined)
        if extent is None or not 0 < extent - len(prefix) < PAGE:
            continue
        value = joined[:extent]
        container = psin.parse_container(value)
        if container is None or not container.checksum_verified:
            continue
        raw_size = extent - len(prefix)
        stored = zlibcarve.Blob(block.archive, start, raw_size, raw_size, tail[:raw_size])
        return blocks[:index + 1] + [stored], value
    return None


def recover(path: str | os.PathLike, limit: int = MAX_OUTPUT * 1024,
            start: int | None = None) -> Iterator[StructuredHit]:
    """Yield complete XML/PSIN resources found in the first *limit* payload bytes."""
    path = os.fspath(path)
    if type(limit) is not int or limit < 0:
        raise ValueError('structured scan limit must be a nonnegative integer')
    archive = os.path.basename(path)
    if start is None:
        try:
            start = rpf.read_header(path).index_size
        except (OSError, ValueError):
            start = 0
    if type(start) is not int or start < 0:
        raise ValueError('structured scan start must be a nonnegative integer')
    scan_end = min(os.path.getsize(path), start + limit)
    if scan_end <= start:
        return
    blobs = [blob for blob in zlibcarve.carve_streams(
        path, length=scan_end, min_out=8, max_out=MAX_OUTPUT) if blob.offset >= start]
    by_offset = {blob.offset: blob for blob in blobs}
    offsets = sorted(by_offset)
    consumed: set[int] = set()
    with open(path, "rb") as fh:
        for first in blobs:
            if first.offset in consumed:
                continue
            is_psin = looks_psin(first.data)
            is_xml = not is_psin and looks_xml(first.data)
            if not is_xml and not is_psin:
                continue
            if len(first.data) > MAX_OUTPUT:
                continue
            blocks = [first]
            total = len(first.data)
            validated = _validate(first.data)
            storage = []
            if validated is None and len(first.data) == PAGE and (
                    is_psin or _declares_xml(first.data)):
                while len(blocks) <= MAX_OUTPUT // PAGE:
                    last = blocks[-1]
                    end = last.offset + last.compressed
                    nxt = (end + 15) & ~15
                    continuation = by_offset.get(nxt)
                    if (continuation is None or nxt in consumed
                            or not _padding_zero(fh, end, nxt)
                            or _declares_xml(continuation.data)
                            or (is_psin and looks_psin(continuation.data))
                            or len(continuation.data) > PAGE
                            or total + len(continuation.data) > MAX_OUTPUT):
                        break
                    blocks.append(continuation)
                    total += len(continuation.data)
                    if len(continuation.data) != PAGE:
                        break
                if len(blocks) > 1:
                    validated = _validate(b"".join(block.data for block in blocks))
            if validated is None and is_psin and len(first.data) == PAGE:
                stored_tail = _stored_psin_tail(fh, blocks, scan_end)
                if stored_tail is not None:
                    blocks, value = stored_tail
                    total = len(value)
                    validated = ('psin', 'PSIN')
                    storage = ['zlib'] * (len(blocks) - 1) + ['stored']
                    # Opaque stored bytes can contain independently valid zlib
                    # streams. They are not additional archive resources.
                    tail = blocks[-1]
                    lo = bisect_left(offsets, tail.offset)
                    hi = bisect_left(offsets, tail.offset + tail.compressed)
                    consumed.update(offsets[lo:hi])
            if validated is None:
                continue
            consumed.update(block.offset for block in blocks)
            kind, root = validated
            segments = [(block.offset, block.compressed, len(block.data))
                        for block in blocks]
            yield StructuredHit(
                archive=archive,
                offset=first.offset,
                kind=kind,
                root=root,
                packed=sum(block.compressed for block in blocks),
                unpacked=total,
                blocks=len(blocks),
                segments=segments,
                data=b"".join(block.data for block in blocks),
                segment_storage=storage,
            )
