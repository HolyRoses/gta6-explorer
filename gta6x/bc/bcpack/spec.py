"""Public BCPack mode constants and BC3/BC4/BC5 reconstruction contract.

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

# Container readers normalize the stored codec bits to these mode numbers.
# BC6H/BC7 metadata enables entropy inspection. BC7's separate sparse-table
# rebuilder also uses this metadata; CODECS retains the BC3/4/5 fitter contract.
ENTROPY_CODECS = {
    1: {
        "name": "BC1", "block_bytes": 8, "elements_per_block": 1,
        "lanes": 12, "default_widths": (8, 8, 5, 6, 5, 5, 6, 5, 8, 8, 8, 8),
    },
    **CODECS,
    6: {
        "name": "BC6H", "block_bytes": 16, "elements_per_block": 2,
        "lanes": 16, "default_widths": (4, 4, 8, 8, 8, 5, 5, 5, 6, 6, 6, 8, 8, 8, 8, 5),
    },
    7: {
        "name": "BC7", "block_bytes": 16, "elements_per_block": 2,
        "lanes": 16, "default_widths": (4, 4, 8, 8, 8, 8, 8, 7, 7, 5, 6, 8, 8, 8, 8, 5),
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
    return _validate(codec, out_size, CODECS)


def validate_entropy_request(codec: int, out_size: int) -> int:
    """Validate a symbol-only request, including BC6H and BC7."""
    return _validate(codec, out_size, ENTROPY_CODECS)


def _validate(codec, out_size, codecs):
    if type(codec) is not int:
        raise ValueError("codec must be an integer")
    info = codecs.get(codec)
    if info is None:
        raise ValueError(f"unsupported BCPack codec {codec}")
    if type(out_size) is not int or out_size <= 0 or out_size % info["block_bytes"]:
        raise ValueError("out_size is not a whole number of BCn blocks")
    return out_size // info["block_bytes"]
