"""Native BCPack decoding and its bundled entropy/history tables.

Use gta6x.bc.decode_bcpack for codec 1/3/4/5/7 dispatch. These low-level APIs
retain the existing BC1 and BC3/4/5 contracts. ``decode_codec_symbols`` also
inspects BC6H/BC7 entropy. BC7 reconstruction has sparse provisional coverage;
BC6H block reconstruction remains unsupported.
"""
from .decoder import BCPackError, decode_bc1, decode_chunk, decode_codec_symbols
from .blocks import BCPackProvisionalWarning

__all__ = ['BCPackError', 'BCPackProvisionalWarning', 'decode_bc1',
           'decode_chunk', 'decode_codec_symbols']
