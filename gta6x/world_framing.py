"""Diagnose declared 0DRP metadata extents without joining resource streams.

The version-122 metadata describes local spans, not a complete resource length.
A declared endpoint and zero page padding never establish ownership of adjacent
compressed streams. Unknown header words stay uninterpreted.
"""
from __future__ import annotations

import struct

from . import anim_resources


class ExtentFormatError(ValueError):
    """An invalid declaration, with the bounded inventory work already spent."""

    def __init__(self, message, nodes):
        super().__init__(message)
        self.nodes = nodes


def inspect_metadata_extent(data: bytes, *, max_nodes: int = 100000,
                            max_extent: int = anim_resources.MAX_RESOURCE) -> dict:
    """Inventory readable metadata references in one inflated stream/prefix.

    Missing referenced payloads are reported, never read or zero substituted.
    If a row table itself is missing, the inventory is explicitly incomplete:
    additional declared spans could exist in its unread rows. The returned
    minimum and 64-KiB rounding are diagnostics, not permission to concatenate.
    """
    if max_nodes < 1:
        raise anim_resources.ResourceLimitError('0DRP extent output exceeds node limit')
    if not anim_resources.HEADER_SIZE <= max_extent <= anim_resources.MAX_RESOURCE:
        raise ValueError('0DRP extent limit must be between header and resource limits')
    if len(data) > max_extent:
        raise ValueError('0DRP prefix exceeds extent limit')
    if len(data) < 80 or data[16:20] != b'0DRP':
        raise ValueError('not a bounded 0DRP resource header')
    if data[:8] != bytes(8) or data[24:32] != bytes(8):
        raise ValueError('unsupported nonzero 0DRP reserved header words')
    if struct.unpack_from('<I', data, 20)[0] != 122:
        raise ValueError('unsupported 0DRP version')
    ns, ne, nb, _ = struct.unpack_from('<4H', data, 72)
    nodes = 1
    spans = []

    def consume(count):
        nonlocal nodes
        if count > max_nodes - nodes:
            raise anim_resources.ResourceLimitError('0DRP extent output exceeds node limit')
        nodes += count

    def span(word, length, kind, at, index=None):
        if not length:
            if word:
                raise ExtentFormatError(f'unsupported nonnull empty 0DRP {kind}', nodes)
            return None
        offset = word - anim_resources.VIRTUAL_BASE
        if offset < 80 or offset > max_extent - length:
            raise ExtentFormatError(f'0DRP {kind} span exceeds extent limit or overlaps header', nodes)
        spans.append(dict(kind=kind, index=index, reference_data_offset=at,
                          data_offset=offset, byte_length=length, end=offset + length,
                          present=offset + length <= len(data)))
        return offset

    consume(ns + ne + nb)
    tables = []
    for kind, at, count, stride in (('structures', 40, ns, 32),
                                   ('enums', 48, ne, 24), ('blocks', 56, nb, 16)):
        word = struct.unpack_from('<Q', data, at)[0]
        offset = span(word, count * stride, kind, at)
        tables.append((kind, offset, count, stride))
    inventory_complete = True
    unread_tables = []
    for kind, offset, count, stride in tables:
        if not count:
            continue
        if offset + count * stride > len(data):
            inventory_complete = False
            unread_tables.append(kind)
            continue
        for index in range(count):
            at = offset + index * stride
            if kind == 'structures':
                word = struct.unpack_from('<Q', data, at + 16)[0]
                count = struct.unpack_from('<H', data, at + 30)[0]
                consume(count)
                span(word, count * 16, 'structure_fields', at + 16, index)
            elif kind == 'enums':
                word, count = struct.unpack_from('<QI', data, at + 8)
                consume(count)
                span(word, count * 16, 'enum_members', at + 8, index)
            else:
                length, word = struct.unpack_from('<IQ', data, at + 4)
                span(word, length, 'data_block', at + 8, index)
    minimum = max((item['end'] for item in spans), default=80)
    padded = (minimum + anim_resources.PAGE_UNIT - 1) // anim_resources.PAGE_UNIT * anim_resources.PAGE_UNIT
    present = inventory_complete and all(item['present'] for item in spans)
    # Full own-parser validation remains mandatory for a bounded metadata claim.
    if present:
        try:
            anim_resources.parse_resource(data, max_nodes=max_nodes)
        except anim_resources.ResourceLimitError:
            raise
        except ValueError as exc:
            raise ExtentFormatError(str(exc), nodes) from exc
    return dict(format='gta6x-0drp-extent-diagnostic-v1',
        status='bounded_metadata' if present else 'incomplete_metadata',
        prefix_bytes=len(data), reference_inventory_complete=inventory_complete,
        unread_row_tables=unread_tables, minimum_declared_extent=minimum,
        rounded_declared_extent=padded, resource_endpoint=None,
        page_padding_matches=(present and padded == len(data) and not any(data[minimum:])),
        nodes=nodes, spans=spans,
        unknown_header_words={f'0x{at:02x}': f'0x{struct.unpack_from("<Q", data, at)[0]:016x}'
                              for at in (8, 32, 64)},
        interpretation='Declared metadata spans only; complete resource extent and adjacent-stream ownership unknown.')
