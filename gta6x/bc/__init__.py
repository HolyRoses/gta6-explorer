"""Block-compressed texture decoding, with bundled runtime constants.

``decode_rgba`` converts standard BC1-BC7 blocks, 8-bit components and selected
16-bit/32-bit/packed normalized or floating-point data to preview pixels. Raw float
numeric previews clip to [0,1]; DDS retains the original precision.
``decode_bcpack`` reconstructs BC1/BC3/BC4/BC5 and selected BC7 blocks from BCPack
streams in stored Gfx10 order. BC3/BC4/BC5 provisional histories warn and unfitted entries
raise; BC1 retains the existing vendored decoder behavior.
BC6H previews are tone-mapped. No external decoder or research files are needed.
BC7 BCPack uses provisional, sparse observations, warns on success and refuses
unknown controls, endpoint history halves or index planes.
"""
from __future__ import annotations

from .bcn import decode_rgba
from .bcpack import decoder as _bcpack
from .bcpack.blocks import BCPackProvisionalWarning

BCPackError = _bcpack.BCPackError

__all__ = ['decode_rgba', 'decode_bcpack', 'BCPackError', 'BCPackProvisionalWarning']


def decode_bcpack(chunk: bytes, codec: int, out_size: int) -> bytes:
    """Decode codec 1/3/4/5/7 to exactly out_size BCn bytes in stored order.

    Raises ValueError for malformed input or unsupported profiles. BC3/4/5
    unfitted references are refused; BC1 retains its existing decoder behavior.
    The low-level decoders remain available from the bcpack subpackage.
    """
    if type(codec) is int and codec == 1:
        if not isinstance(chunk, bytes):
            raise BCPackError('chunk must be bytes')
        if type(out_size) is not int or out_size <= 0 or out_size % 8:
            raise BCPackError('BC1 output size must be a positive multiple of 8')
        return _bcpack.decode_bc1(chunk, out_size // 8)
    return _bcpack.decode_chunk(chunk, codec, out_size)
