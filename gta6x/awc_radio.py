"""Bounded AWC music marker/chapter and per-block raw-table views.

No station graph or native song-name table is inferred. Chapter intervals are
unclassified and may include imaging or repeated ids. Seek-table units remain
unknown; entries are never used as file offsets.
"""
from __future__ import annotations

import math
import struct

from . import media, names

RATE = 48000
MAX_RECORDS = 1000000
TRACK_ID = names.joaat('TRACKID')
MARKER_NAMES = {names.joaat(name):name for name in ('BEAT','INTRO','OUTRO','DJ','TRACKID')}
CHUNK_NAMES = media.AWC_CHUNK_HASH_NAMES


def _limit(value):
    if type(value) is not int or not 1<=value<=MAX_RECORDS:
        raise ValueError('radio max_records must be from 1 to 1000000')


def seek_table(payload, blocks, *, max_records=100000):
    _limit(max_records)
    if type(blocks) is not int or not 1<=blocks<=max_records:
        raise ValueError('radio block-table count exceeds budget')
    if len(payload)!=4*blocks:
        raise ValueError('radio block-table length differs from descriptor block count')
    values=list(struct.unpack('<'+str(blocks)+'I',payload))
    if any(b<=a for a,b in zip(values,values[1:])):
        raise ValueError('radio block-table values are not strictly ascending')
    return dict(status='parsed',raw_values=values,entries=blocks,
        unit='unresolved',interpretation='one ascending u32 per data block; not a byte-seek API')


def markers(payload, frames, *, max_records=100000):
    _limit(max_records)
    if type(frames) is not int or frames<0:
        raise ValueError('markers require a bounded per-channel frame count')
    if len(payload)%16 or len(payload)//16>max_records:
        raise ValueError('marker length/count exceeds complete 16-byte records or budget')
    result=[];previous={}
    for i in range(len(payload)//16):
        tag,bits,position,reserved=struct.unpack_from('<4I',payload,16*i)
        value=struct.unpack('<f',struct.pack('<I',bits))[0]
        if reserved:
            raise ValueError('unsupported nonzero marker reserved word')
        if position>frames or position<previous.get(tag,0):
            raise ValueError('marker position exceeds duration or descends within its tag group')
        previous[tag]=position
        entry=dict(index=i,tag=f'0x{tag:08x}',tag_name=MARKER_NAMES.get(tag),
            raw_value_bits=f'0x{bits:08x}',value=value if math.isfinite(value) else None,
            position_frames=position,position_s=position/RATE,raw_reserved_u32=reserved)
        if tag==TRACK_ID:
            if not math.isfinite(value) or value<0 or value>0xffffffff or not value.is_integer():
                raise ValueError('TRACKID float must encode an integral nonnegative u32')
            entry['track_id']=int(value)
        else:
            entry['value_meaning']='unresolved'
        result.append(entry)
    return result


def chapters(marker_rows, frames):
    """Keep every TRACKID occurrence; do not label intervals as songs."""
    selected=[row for row in marker_rows if 'track_id' in row]
    result=[];seen=set()
    for i,row in enumerate(selected):
        end=selected[i+1]['position_frames'] if i+1<len(selected) else frames
        if end<row['position_frames'] or end>frames:
            raise ValueError('chapter interval exceeds its declared timeline')
        identifier=row['track_id'];start=row['position_frames']
        result.append(dict(index=i,track_id=identifier,start_frames=start,end_frames=end,
            start_s=start/RATE,end_s=end/RATE,duration_s=(end-start)/RATE,
            repeated_track_id=identifier in seen,role='unclassified_marker_interval'))
        seen.add(identifier)
    return result


def chapter_text(rows):
    lines=[]
    for row in rows:
        seconds=row['start_frames']//RATE
        hours,seconds=divmod(seconds,3600);minutes,seconds=divmod(seconds,60)
        lines.append(f"{hours}:{minutes:02d}:{seconds:02d}\t0xb2\t{row['track_id']}")
    return '\n'.join(lines)+('\n' if lines else '')


def inspect_bank(bank: bytes, *, max_records=100000):
    """Inspect complete music banks atomically per table, retaining refusals."""
    _limit(max_records)
    view=media.validate_awc(bank)
    if view is None or view['size']!=len(bank):
        raise ValueError('radio metadata requires one complete bounded AWC container')
    return _inspect(view,lambda at,size:bank[at:at+size],max_records=max_records)


def inspect_file(path, offset, *, max_records=100000):
    """Read only header/format/table bytes at one validated archive address."""
    _limit(max_records)
    view=media.awc_metadata_at(path,offset).meta
    with open(path,'rb') as fh:
        def read(at,size):
            fh.seek(offset+at);data=fh.read(size)
            if len(data)!=size:raise ValueError('AWC table source changed or truncated')
            return data
        result=_inspect(view,read,max_records=max_records)
    result['read_scope']='header/format/table bytes only; encoded audio not validated'
    return result


def _inspect(view, read, *, max_records):
    channels=[c for s in view['stream_list'] if s.get('music') and not s['music'].get('error')
              for c in s['music']['channels']]
    if not channels:
        return dict(status='unsupported',reason='no supported blocked music descriptor',
                    tables=[],summary=dict(nodes=0,markers=0,chapters=0,seek_entries=0))
    if any(c['sample_rate']!=RATE or c.get('frames') is None or c['frames']<=0 for c in channels):
        raise ValueError('radio timing requires integral positive 48 kHz mono/stereo descriptor frames')
    frames=max(c['frames'] for c in channels)
    tables=[];used=0;refused=False
    for stream in view['stream_list']:
        for ordinal,chunk in enumerate(stream['chunks']):
            kind=int(chunk['type'],16)
            if kind not in (0xa3,0xbd):continue
            row=dict(chunk,stream_index=stream['index'],stream_id=f"0x{stream['id']:08x}",
                     chunk_index=ordinal,name_candidates=CHUNK_NAMES[kind])
            try:
                at,size=chunk['data_offset'],chunk['byte_length']
                if at>view['size']-size:raise ValueError('radio chunk escapes its complete container')
                needed=1+(size//16 if kind==0xbd else size//4)
                if needed>max_records-used:raise ValueError('radio metadata exceeds shared record budget')
                if kind==0xa3:
                    if not stream.get('music') or stream['music'].get('error'):
                        row.update(status='unresolved',reason='0xa3 hash-byte collision or missing local music descriptor; no seek-table interpretation')
                    else:
                        row.update(seek_table(read(at,size),stream['music']['blocks'],max_records=max_records-used))
                else:
                    matches=[c['frames'] for c in channels if c['id']==stream['id']]
                    if matches and len(set(matches))!=1:
                        raise ValueError('marker stream id has ambiguous descriptor durations')
                    bound=matches[0] if matches else frames
                    parsed=markers(read(at,size),bound,max_records=max_records-used)
                    intervals=chapters(parsed,bound)
                    if needed+len(intervals)>max_records-used:raise ValueError('chapter output exceeds shared record budget')
                    needed+=len(intervals)
                    row.update(status='parsed',markers=parsed,chapters=intervals,
                        timebase_hz=RATE,bound_frames=bound,
                        bound_evidence='matching raw stream/channel id' if matches else 'container music duration upper bound; precise channel association unresolved',
                        distinct_track_ids=len({c['track_id'] for c in intervals}),
                        interpretation='TRACKID-keyed intervals only; may include imaging; no song names or station graph inferred')
                used+=needed
            except ValueError as exc:
                refused=True;row.update(status='refused',reason=str(exc))
            tables.append(row)
    return dict(status='partial' if refused else 'parsed',tables=tables,
        summary=dict(nodes=used,markers=sum(len(t.get('markers',[])) for t in tables),
            chapters=sum(len(t.get('chapters',[])) for t in tables),
            seek_entries=sum(t.get('entries',0) for t in tables)),
        station_membership='unresolved; native graph location and layout are not established')
