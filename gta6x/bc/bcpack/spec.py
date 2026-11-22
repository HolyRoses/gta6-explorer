"""Public BCPack BC3/BC4/BC5 constants and implementation contract.

This module contains only public format facts: codec ids, lane widths, block
sizes and the validation API. It deliberately contains no fitted endpoint
history or index-codebook values; independently fitted constants live in
data/bc345_tables.json with their observation provenance.
"""

from __future__ import annotations

CODECS = {
    3: {
        "name": "BC3", "block_bytes": 16, "elements_per_block": 2,
        "lanes": 12, "default_widths": (4, 4, 8, 6, 6, 6, 6, 5, 6, 5, 8, 8),
    },
    4: {
        "name": "BC4", "block_bytes": 8, "elements_per_block": 1,
        "lanes": 12, "default_widths": (8, 8, 8, 8, 6, 6, 6, 6, 6, 6, 6, 6),
    },
    5: {
        "name": "BC5", "block_bytes": 16, "elements_per_block": 2,
        "lanes": 12, "default_widths": (4, 4, 8, 8, 6, 6, 6, 6, 6, 6, 6, 6),
    },
}

#: Public contract for the native block rebuilder. A clean-room
#: implementation returns exactly ``out_size`` bytes of BCn blocks (the
#: TTPF chunk virtual size), in the surface's stored tile order.
API = "decode_chunk(chunk: bytes, codec: int, out_size: int) -> bytes"


def element_count(codec: int, out_size: int) -> int:
    """Number of lane elements needed for ``out_size`` output bytes."""
    blocks = validate_request(codec, out_size)
    info = CODECS.get(codec)
    return blocks * info["elements_per_block"]


def validate_request(codec: int, out_size: int) -> int:
    """Validate a decode request and return the block count."""
    if type(codec) is not int:
        raise ValueError("codec must be an integer")
    info = CODECS.get(codec)
    if info is None:
        raise ValueError(f"unsupported BCPack codec {codec}")
    if type(out_size) is not int or out_size <= 0 or out_size % info["block_bytes"]:
        raise ValueError("out_size is not a whole number of BCn blocks")
    return out_size // info["block_bytes"]
