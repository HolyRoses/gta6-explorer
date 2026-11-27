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
    endpoint_masks: tuple | None = None
    index_masks: tuple = (None, None)

    def __post_init__(self):
        if self.endpoints is not None:State(self.endpoints,ZERO.indices)
        if (not isinstance(self.indices,tuple) or len(self.indices)!=2
                or any(row is not None and (not isinstance(row,tuple) or len(row)!=16
                    or any(type(v) is not int or not 0<=v<16 for v in row)) for row in self.indices)):
            raise ValueError('invalid BC7 preset index observation')
        if self.endpoint_masks is not None:
            if (self.endpoints is None or not isinstance(self.endpoint_masks,tuple)
                    or len(self.endpoint_masks)!=len(self.endpoints)
                    or any(not isinstance(row,tuple) or len(row)!=8 for row in self.endpoint_masks)):
                raise ValueError('invalid BC7 endpoint observation masks')
            for values,masks in zip(self.endpoints,self.endpoint_masks):
                if any(type(m) is not int or not 0<=m<=255 or v&~m for v,m in zip(values,masks)):
                    raise ValueError('invalid BC7 endpoint observation masks')
        if not isinstance(self.index_masks,tuple) or len(self.index_masks)!=2:
            raise ValueError('invalid BC7 index observation masks')
        for values,masks in zip(self.indices,self.index_masks):
            if masks is None:continue
            if (values is None or not isinstance(masks,tuple) or len(masks)!=16
                    or any(type(m) is not int or not 0<=m<16 or v&~m for v,m in zip(values,masks))):
                raise ValueError('invalid BC7 index observation masks')

    def project_endpoint(self, control):
        if self.endpoints is None:raise ValueError('unfitted endpoint fields')
        if SUBSETS[control.mode]>len(self.endpoints):
            raise ValueError('unfitted endpoint subsets')
        widths=precisions(control)
        for subset in range(SUBSETS[control.mode]):
            source=subset if subset<len(self.endpoints) else 0
            masks=(255,)*8 if self.endpoint_masks is None else self.endpoint_masks[source]
            for channel,width in enumerate(widths):
                required=((1<<width)-1)<<(8-width)
                if any(masks[2*channel+p]&required!=required for p in (0,1)):
                    raise ValueError('unfitted endpoint precision')
        return State(self.endpoints,ZERO.indices)

    def project_indices(self, control):
        rows=[]
        for plane,width in enumerate(INDEX_BITS[control.mode]):
            if not width:rows.append((0,)*16);continue
            row=self.indices[plane]
            if row is None:raise ValueError(f'unfitted index plane {plane}')
            masks=(15,)*16 if self.index_masks[plane] is None else self.index_masks[plane]
            required=((1<<width)-1)<<(4-width)
            if any(mask&required!=required for mask in masks):
                raise ValueError(f'unfitted index precision in plane {plane}')
            rows.append(row)
        return State(ZERO.endpoints,tuple(rows))


def merge_presets(old, new):
    """Add observed bits without replacing frozen knowledge or filling gaps."""
    if not isinstance(old,Preset) or not isinstance(new,Preset):
        raise ValueError('invalid BC7 preset merge')
    def merge_rows(a,am,b,bm,full):
        if a is None:return b,bm
        if b is None:return a,am
        if len(a)!=len(b):raise ValueError('incompatible BC7 preset observation shape')
        am=(full,)*len(a) if am is None else am
        bm=(full,)*len(b) if bm is None else bm
        if any((av^bv)&ma&mb for av,bv,ma,mb in zip(a,b,am,bm)):
            raise ValueError('BC7 extension changes observed preset bits')
        values=tuple(av|bv for av,bv in zip(a,b));masks=tuple(ma|mb for ma,mb in zip(am,bm))
        return values,None if all(m==full for m in masks) else masks
    endpoints=old.endpoints;em=old.endpoint_masks
    if endpoints is None:endpoints,em=new.endpoints,new.endpoint_masks
    elif new.endpoints is not None:
        if len(endpoints)!=len(new.endpoints):raise ValueError('incompatible BC7 endpoint subsets')
        pairs=[merge_rows(a,None if em is None else em[i],b,
                         None if new.endpoint_masks is None else new.endpoint_masks[i],255)
               for i,(a,b) in enumerate(zip(endpoints,new.endpoints))]
        endpoints=tuple(p[0] for p in pairs)
        em=None if all(p[1] is None for p in pairs) else tuple(p[1] or (255,)*8 for p in pairs)
    indices=[];im=[]
    for plane in (0,1):
        row,mask=merge_rows(old.indices[plane],old.index_masks[plane],
                           new.indices[plane],new.index_masks[plane],15)
        indices.append(row);im.append(mask)
    return Preset(endpoints,tuple(indices),em,tuple(im))


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


@lru_cache(maxsize=64,typed=True)
def load_tables(extended=True, refined=True, latest=True, corrected=True, observed=True, bulk=True):
    """Load the immutable initial observations and an optional checked overlay.

    ``extended=False`` replays the original profile; ``refined=False`` replays
    the first extension. Additive observations cannot replace frozen knowledge.
    ``latest=False`` replays the precision profile before slot32 was completed.
    ``corrected=False`` replays the completed profile's original observations.
    ``observed=False`` replays the profile before adding histories35/7.
    ``bulk=False`` replays the profile before bulk control/endpoint fitting.
    Corrections require a separate parent-bound record and an exact old-bit
    precondition. Additive overlays still cannot replace known bits.
    Precision masks preserve unobserved bits and refuse unsupported requests.
    """
    if any(type(flag) is not bool for flag in (extended,refined,latest,corrected,observed,bulk)):
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
    def add_precision(extra):
        def rows(value):
            if value is None:return None
            if not isinstance(value,list) or any(not isinstance(row,list) for row in value):
                raise ValueError('invalid BC7 precision rows')
            return tuple(map(tuple,value))
        for key,entry in extra['history'].items():
            if (not isinstance(key,str) or not key.isdecimal() or str(int(key))!=key
                    or not 1<=int(key)<=255 or not isinstance(entry,dict)
                    or entry.get('status')!='sixng_pixel_provisional'):
                raise ValueError('invalid BC7 precision observation')
            fields=[]
            for name in ('indices','index_masks'):
                field=entry.get(name)
                if not isinstance(field,list) or len(field)!=2:
                    raise ValueError('invalid BC7 precision index rows')
                fields.append(tuple(None if row is None else rows([row])[0] for row in field))
            observed=Preset(rows(entry.get('endpoints')),fields[0],
                            rows(entry.get('endpoint_masks')),fields[1])
            slot=int(key);history[slot]=merge_presets(history.get(slot,Preset()),observed)
    refinement=path.with_name('bc7_precision.json')
    if extended and refined and refinement.exists():
        extra=json.loads(refinement.read_text())
        if (not isinstance(extra,dict) or extra.get('format')!='gta6x-bcpack-bc7-precision-v1'
                or extra.get('base_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest()
                or not extension.exists()
                or extra.get('extension_sha256')!=hashlib.sha256(extension.read_bytes()).hexdigest()
                or not isinstance(extra.get('history'),dict)):
            raise ValueError('BC7 precision overlay identity mismatch')
        add_precision(extra)
    completed=path.with_name('bc7_history_completion.json')
    if extended and refined and latest and completed.exists():
        extra=json.loads(completed.read_text())
        if (not isinstance(extra,dict) or extra.get('format')!='gta6x-bcpack-bc7-history-extension-v1'
                or not refinement.exists()
                or extra.get('parent_sha256')!=hashlib.sha256(refinement.read_bytes()).hexdigest()
                or not isinstance(extra.get('history'),dict)):
            raise ValueError('BC7 history extension identity mismatch')
        add_precision(extra)
    corrections=path.with_name('bc7_corrections.json')
    if extended and refined and latest and corrected and corrections.exists():
        document=json.loads(corrections.read_text())
        if (not isinstance(document,dict)
                or document.get('format')!='gta6x-bcpack-bc7-corrections-v1'
                or not completed.exists()
                or document.get('parent_sha256')!=hashlib.sha256(completed.read_bytes()).hexdigest()
                or not isinstance(document.get('corrections'),list)
                or not 1<=len(document['corrections'])<=512):
            raise ValueError('BC7 correction profile identity mismatch')
        seen=set()
        for entry in document['corrections']:
            if not isinstance(entry,dict) or entry.get('status')!='natural_pixel_correction_provisional':
                raise ValueError('invalid BC7 correction status')
            slot,plane,pixel,mask,previous,value=(entry.get(k) for k in
                ('slot','plane','pixel','mask','previous','value'))
            if (any(type(v) is not int for v in (slot,plane,pixel,mask,previous,value))
                    or not 1<=slot<=255 or not 0<=plane<2 or not 0<=pixel<16
                    or not 1<=mask<=15 or not 0<=previous<=15 or not 0<=value<=15
                    or previous&~mask or value&~mask or previous==value):
                raise ValueError('invalid BC7 correction field')
            field=(slot,plane,pixel)
            if field in seen:raise ValueError('duplicate BC7 correction field')
            seen.add(field);old=history.get(slot)
            if old is None or old.indices[plane] is None:
                raise ValueError('BC7 correction requires an observed index field')
            known=15 if old.index_masks[plane] is None else old.index_masks[plane][pixel]
            if known&mask!=mask or old.indices[plane][pixel]&mask!=previous:
                raise ValueError('BC7 correction old-bit precondition failed')
            rows=list(old.indices);row=list(rows[plane]);row[pixel]=(row[pixel]&~mask)|value
            rows[plane]=tuple(row)
            history[slot]=Preset(old.endpoints,tuple(rows),old.endpoint_masks,old.index_masks)
    observations=path.with_name('bc7_observations.json')
    if extended and refined and latest and corrected and observed and observations.exists():
        extra=json.loads(observations.read_text())
        if (not isinstance(extra,dict) or extra.get('format')!='gta6x-bcpack-bc7-observations-v1'
                or not corrections.exists()
                or extra.get('parent_sha256')!=hashlib.sha256(corrections.read_bytes()).hexdigest()
                or not isinstance(extra.get('history'),dict)):
            raise ValueError('BC7 observation profile identity mismatch')
        add_precision(extra)
    bulk_path=path.with_name('bc7_bulk.json')
    if extended and refined and latest and corrected and observed and bulk and bulk_path.exists():
        extra=json.loads(bulk_path.read_text())
        if (not isinstance(extra,dict) or extra.get('format')!='gta6x-bcpack-bc7-bulk-v1'
                or not observations.exists()
                or extra.get('parent_sha256')!=hashlib.sha256(observations.read_bytes()).hexdigest()
                or not isinstance(extra.get('controls'),dict) or not isinstance(extra.get('history'),dict)):
            raise ValueError('BC7 bulk profile identity mismatch')
        evidence=extra.get('evidence',{})
        baseline=evidence.get('baseline_sha256') if isinstance(evidence,dict) else None
        if (not isinstance(evidence,dict) or evidence.get('status')!='provisional'
                or type(evidence.get('confirmed_controls')) is not int or evidence['confirmed_controls']!=0
                or type(evidence.get('confirmed_history')) is not int or evidence['confirmed_history']!=0
                or not isinstance(baseline,str) or len(baseline)!=64
                or any(c not in '0123456789abcdef' for c in baseline)):
            raise ValueError('invalid BC7 bulk provenance')
        add_records(dict(controls=extra['controls'],history={}),{'pixel_palette_provisional'})
        add_precision(extra)
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
    ring_controls = [None]*256
    output = bytearray()
    def predictor(distance, block, component, control):
        if not distance:return ZERO
        if distance <= block:return ring[(block-distance)&255]
        slot = 256+block-distance
        if slot not in presets:raise ValueError(f'BC7 unfitted history entry {slot} at block {block}')
        value=presets[slot]
        if isinstance(value,State):return value
        try:
            return value.project_endpoint(control) if component=='endpoint' else value.project_indices(control)
        except ValueError as error:
            raise ValueError(f'BC7 {error} in history entry {slot} at block {block}') from None
    for block in range(count):
        code = control_code(symbols,block)
        control = controls.get(code)
        if control is None:raise ValueError(f'BC7 unfitted control {code} at block {block}')
        ep, ix = references(symbols,block)
        # Version-paired probes and plain lower mips support mode6's cleared
        # secondary prediction. Other cross-control dual transitions remain
        # unsupported by the bundled observations.
        if (provisional and INDEX_BITS[control.mode][1] and 0<ix<=block
                and ring_controls[(block-ix)&255]!=control
                and ring_controls[(block-ix)&255].mode!=6):
            raise ValueError(f'BC7 unresolved dual-plane index transition at block {block}')
        state = rebuild(control,symbols,block,predictor(ep,block,'endpoint',control),
                        predictor(ix,block,'index',control))
        output += pack(control,state,omit_anchor_msb=True)
        ring[block&255] = state
        ring_controls[block&255] = control
    if len(output)!=out_size:raise ValueError('BC7 output size mismatch')
    if provisional:
        warnings.warn('BCPack BC7: provisional control and pixel-derived endpoint/index observations; '
                      'original block bytes are unconfirmed and pixel differences are documented',
                      BCPackProvisionalWarning,stacklevel=2)
    return bytes(output)
