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
* PSIN must be a complete seven-section container (see :mod:`gta6x.psin`).

The rules and limits mirror the structured-recovery pass in rpf9-explorer.
Measured on 1.0.2.1, this recovers complete XML manifests from ``common.rpf``
and complete PSIN containers from ``data.rpf`` that a per-stream carve leaves
truncated.
"""

from __future__ import annotations

import os
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

    def as_dict(self) -> dict:
        return {
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
        return ("psin", "PSIN") if container is not None else None
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


def recover(path: str | os.PathLike, limit: int = MAX_OUTPUT * 1024,
            start: int | None = None) -> Iterator[StructuredHit]:
    """Yield complete XML/PSIN resources found in the first *limit* payload bytes."""
    path = os.fspath(path)
    archive = os.path.basename(path)
    if start is None:
        try:
            start = rpf.read_header(path).index_size
        except (OSError, ValueError):
            start = 0
    blobs = [blob for blob in zlibcarve.carve_streams(
        path, length=start + limit, min_out=8) if blob.offset >= start]
    by_offset = {blob.offset: blob for blob in blobs}
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
            )
