"""BC7 BCPack reconstruction with explicit controls and preset observations.

Unknown controls and preset states are refused. The mechanics follow the
repository format specification; BC7 field packing uses public format facts.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import hashlib
from pathlib import Path
import warnings

from .bc7_layout import (Control, State, ZERO, SUBSETS, INDEX_BITS,
                         precisions, pack)
from .spec import validate_entropy_request
from .blocks import BCPackProvisionalWarning


@dataclass(frozen=True)
class Preset:
    """Independently observed halves; None always means unknown, never zero."""
    endpoints: tuple | None = None
    indices: tuple = (None, None)

    def __post_init__(self):
        if self.endpoints is not None:State(self.endpoints,ZERO.indices)
        if (not isinstance(self.indices,tuple) or len(self.indices)!=2
                or any(row is not None and (not isinstance(row,tuple) or len(row)!=16
                    or any(type(v) is not int or not 0<=v<16 for v in row)) for row in self.indices)):
            raise ValueError('invalid BC7 preset index observation')


def unzigzag(value):
    return -(value//2)-1 if value & 1 else value//2


def reference_byte(even, odd):
    return sum(((even >> b) & 1) << (2*b) | ((odd >> b) & 1) << (2*b+1)
               for b in range(4))


def references(symbols, block):
    index = reference_byte(*symbols[1][2*block:2*block+2])
    delta = unzigzag(reference_byte(*symbols[0][2*block:2*block+2]))
    return (index+delta) & 255, index


def control_code(symbols, block):
    even, odd = symbols[15][2*block:2*block+2]
    if odd & 16:raise ValueError('BC7 control has reserved high bit')
    return even | (odd << 5)


def rebuild(control, symbols, block, endpoint_predictor=ZERO, index_predictor=ZERO):
    """Apply one record's residuals to explicit predictors; no table lookup."""
    widths = precisions(control)
    endpoints = []
    for subset in range(SUBSETS[control.mode]):
        previous = endpoint_predictor.endpoints[
            subset if subset < len(endpoint_predictor.endpoints) else 0]
        row = [0]*8
        for channel, width in enumerate(widths):
            if not width:continue
            lane = ((2+channel) if subset == 0 else (6+channel) if subset == 1
                    else (10,5,9)[channel])
            for parity in (0,1):
                v = (previous[2*channel+parity] >> (8-width))
                v = (v+unzigzag(symbols[lane][2*block+parity])) & ((1 << width)-1)
                row[2*channel+parity] = v << (8-width)
        endpoints.append(tuple(row))
    indices = [[0]*16 for _ in range(2)]
    for plane, width in enumerate(INDEX_BITS[control.mode]):
        if not width:continue
        for row in range(4):
            lane = 11+row if plane == 0 else (6,7,8,10)[row]
            for half in (0,1):
                symbol = symbols[lane][2*block+half]
                parts = [sum(((symbol >> (2*b+p)) & 1) << b for b in range(4))
                         for p in (0,1)]
                if row < 3:parts.reverse()
                for within, residual in enumerate(parts):
                    pixel = 4*row+2*half+within
                    prior = index_predictor.indices[plane][pixel] >> (4-width)
                    indices[plane][pixel] = ((prior+unzigzag(residual)) & ((1 << width)-1)) << (4-width)
    state = State(tuple(endpoints), tuple(map(tuple,indices)))
    # Preserve full index predictor state. The MDU writer omits anchor MSBs;
    # canonical standard-block packing and MDU-state packing are distinct.
    return state


@lru_cache(maxsize=2,typed=True)
def load_tables(extended=True):
    """Load the immutable initial observations and an optional checked overlay.

    ``extended=False`` replays the original profile without altering its sealed
    file. Extensions cannot replace any previously observed field or control.
    """
    if type(extended) is not bool:
        raise ValueError('invalid BC7 table profile')
    path=Path(__file__).with_name('data')/'bc7_tables.json'
    base_text=path.read_text()
    data=json.loads(base_text)
    if not isinstance(data,dict) or data.get('format')!='gta6x-bcpack-bc7-provisional-v1':
        raise ValueError('invalid BC7 provisional tables')
    controls={};history={}
    def add_records(document,control_statuses):
        if not isinstance(document.get('controls'),dict) or not isinstance(document.get('history'),dict):
            raise ValueError('invalid BC7 provisional tables')
        for key,entry in document['controls'].items():
            if (not isinstance(key,str) or not key.isdecimal() or str(int(key))!=key
                    or not 0<=int(key)<512 or not isinstance(entry,dict)
                    or entry.get('status') not in control_statuses
                    or not isinstance(entry.get('value'),list) or len(entry['value'])!=4):
                raise ValueError('invalid BC7 provisional control')
            code=int(key);control=Control(*entry['value'])
            if code in controls and controls[code]!=control:
                raise ValueError('BC7 extension changes an existing control')
            if code not in controls and control in controls.values():
                raise ValueError('duplicate BC7 provisional control assignment')
            controls[code]=control
        for key,entry in document['history'].items():
            if (not isinstance(key,str) or not key.isdecimal() or str(int(key))!=key
                    or not 1<=int(key)<=255 or not isinstance(entry,dict)
                    or entry.get('status')!='sixng_pixel_provisional'
                    or entry.get('endpoints') is not None
                    or not isinstance(entry.get('indices'),list) or len(entry['indices'])!=2
                    or entry['indices'][1] is not None or not isinstance(entry['indices'][0],list)):
                raise ValueError('invalid BC7 provisional preset')
            slot=int(key);preset=Preset(indices=(tuple(entry['indices'][0]),None))
            if slot in history and history[slot]!=preset:
                raise ValueError('BC7 extension changes an existing preset')
            history[slot]=preset
    add_records(data,{'canonical_profile_provisional'})
    extension=path.with_name('bc7_extensions.json')
    if extended and extension.exists():
        more=json.loads(extension.read_text())
        if (not isinstance(more,dict) or more.get('format')!='gta6x-bcpack-bc7-extension-v1'
                or more.get('base_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest()):
            raise ValueError('BC7 extension base identity mismatch')
        add_records(more,{'pixel_palette_provisional'})
    return controls,history


def assemble(symbols, out_size, *, controls=None, history=None):
    """Reconstruct BC7 blocks atomically using caller-supplied observations.

    Explicit controls/presets support authored tests and independent observations.
    Omitting controls loads the bundled provisional observations and warns on
    success. Unknown endpoint halves and index planes are always refused.
    A pre-chunk distance uses slot ``256 + block - distance``.
    """
    count = validate_entropy_request(7,out_size)
    from .spec import ENTROPY_CODECS
    widths = ENTROPY_CODECS[7]['default_widths']
    if len(symbols)!=16 or any(len(row)!=2*count for row in symbols):
        raise ValueError('BC7 lane element count mismatch')
    for row, width in zip(symbols,widths):
        if any(type(v) is not int or not 0<=v<1<<width for v in row):
            raise ValueError('BC7 symbol outside alphabet')
    provisional=controls is None
    if provisional:
        if history is not None:raise ValueError('explicit BC7 history requires explicit controls')
        controls,history=load_tables()
    if (not isinstance(controls, dict) or any(type(k) is not int or not 0<=k<512
            or not isinstance(v, Control) for k,v in controls.items())):
        raise ValueError('invalid BC7 control observations')
    presets = {} if history is None else history
    if (not isinstance(presets, dict) or any(type(k) is not int or not 1<=k<=255
            or not isinstance(v, (State,Preset)) for k,v in presets.items())):
        raise ValueError('invalid BC7 preset observations')
    ring = [None]*256
    output = bytearray()
    def predictor(distance, block, component, control):
        if not distance:return ZERO
        if distance <= block:return ring[(block-distance)&255]
        slot = 256+block-distance
        if slot not in presets:raise ValueError(f'BC7 unfitted history entry {slot} at block {block}')
        value=presets[slot]
        if isinstance(value,State):return value
        if component=='endpoint':
            if value.endpoints is None:raise ValueError(f'BC7 unfitted endpoint history entry {slot} at block {block}')
            return State(value.endpoints,ZERO.indices)
        rows=[]
        for plane,width in enumerate(INDEX_BITS[control.mode]):
            if width and value.indices[plane] is None:
                raise ValueError(f'BC7 unfitted index history entry {slot} plane {plane} at block {block}')
            rows.append(value.indices[plane] if width else (0,)*16)
        return State(ZERO.endpoints,tuple(rows))
    for block in range(count):
        code = control_code(symbols,block)
        control = controls.get(code)
        if control is None:raise ValueError(f'BC7 unfitted control {code} at block {block}')
        ep, ix = references(symbols,block)
        state = rebuild(control,symbols,block,predictor(ep,block,'endpoint',control),
                        predictor(ix,block,'index',control))
        output += pack(control,state,omit_anchor_msb=True)
        ring[block&255] = state
    if len(output)!=out_size:raise ValueError('BC7 output size mismatch')
    if provisional:
        warnings.warn('BCPack BC7: provisional control and pixel-derived index observations; '
                      'original block bytes are unconfirmed and pixel differences are documented',
                      BCPackProvisionalWarning,stacklevel=2)
    return bytes(output)
