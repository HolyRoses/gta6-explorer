"""Exact PSIN block-table framing, independent of schema interpretation.

Derived from authored fixtures and direct local game observations. Type words
remain raw identifiers; the table does not establish record or scalar meanings.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

__all__ = ['InstanceBlock', 'InstanceLimitError', 'parse_blocks']


class InstanceLimitError(ValueError):
    """The requested instance output exceeds its explicit node budget."""


@dataclass(frozen=True)
class InstanceBlock:
    index: int
    table_offset: int
    type_hash: int
    byte_length: int
    data_offset: int


def parse_blocks(body: bytes, *, max_blocks: int = 65536) -> list[InstanceBlock]:
    """Parse an exact PSIN body, refusing other layouts and nonzero padding.

    Entries start at +8, including the first type/length pair. Each is followed
    by eight AA bytes. An eight-PP terminator precedes aligned block payloads.
    """
    if max_blocks < 1:
        raise ValueError('max_blocks must be positive')
    if (len(body) < 16 or body[:4] != b'PSIN'
            or struct.unpack_from('>I', body, 4)[0] != len(body)):
        raise ValueError('instance reader requires an exact PSIN body')
    position = 8
    entries = []
    while True:
        if position + 8 > len(body):
            raise ValueError('missing PSIN block-table terminator')
        if body[position:position + 8] == b'pppppppp':
            position += 8
            break
        if position + 16 > len(body) or body[position + 8:position + 16] != b'\xaa' * 8:
            raise ValueError('unsupported PSIN instance block-table layout')
        if len(entries) >= max_blocks:
            raise InstanceLimitError('PSIN block count exceeds limit')
        key, size = struct.unpack_from('<II', body, position)
        if size == 0:
            raise ValueError('zero-sized PSIN instance block is not validated')
        entries.append((position, key, size))
        position += 16
    blocks = []
    for index, (table_offset, key, size) in enumerate(entries):
        end = position + size
        aligned = (end + 15) & ~15
        if aligned > len(body):
            raise ValueError('truncated PSIN instance block or padding')
        if any(body[end:aligned]):
            raise ValueError('nonzero PSIN instance block padding is not validated')
        blocks.append(InstanceBlock(index, table_offset, key, size, position))
        position = aligned
    if position != len(body):
        raise ValueError('unaccounted PSIN instance body bytes')
    return blocks
