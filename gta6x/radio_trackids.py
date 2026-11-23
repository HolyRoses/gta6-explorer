"""Conservative TRACKID/record candidates from native AWC metadata reports.

Marker-to-channel equality is local native evidence. Record joins use truncated
ids plus duration and remain candidates; credited titles/stations are external.
TRACKIDs can be reused for different material. Never select a conflicting first
match, infer station membership from ranges, or interpret config payloads here.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import struct

from . import awc_radio, music_catalog

MAX_BYTES = 128 * 1024 * 1024
DURATION_TOLERANCE_MS = 1


def _uint(value, label, maximum=0xffffffff):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('invalid radio-link '+label)
    return value


def _word(value, label):
    if isinstance(value, str):
        if len(value)!=10 or not value.startswith('0x'):
            raise ValueError('radio-link '+label+' requires a full hexadecimal u32')
        try:value=int(value,16)
        except ValueError as exc:raise ValueError('invalid radio-link '+label) from exc
    return _uint(value,label)


def _archive(value):
    if (not isinstance(value,str) or not value or len(value)>255 or not value.isprintable()
            or value in ('.','..') or '/' in value or '\\' in value):
        raise ValueError('radio-link archive must be a basename')
    return value


def load_awc_report(path):
    with Path(path).open('rb') as f:raw=f.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('AWC metadata report exceeds byte limit')
    try:data=json.loads(raw)
    except (ValueError,UnicodeError,RecursionError) as exc:raise ValueError('invalid AWC metadata JSON') from exc
    if not isinstance(data,list):raise ValueError('expected the JSON array from awc --radio')
    return data,hashlib.sha256(raw).hexdigest()


def resolve(banks, records, *, catalog=None, max_nodes=100000):
    """Build bounded candidates atomically; no source file or decoder is opened.

    Input is an awc --radio JSON report, not authenticated source bytes. Raw
    marker words are checked again; supplied chapter/title labels are ignored.
    Whole-channel observations need one TRACKID at zero, a unique exact local
    channel id and a matching frame bound. Other chapters are queries only.
    """
    try:
        return _resolve(banks,records,catalog=catalog,max_nodes=max_nodes)
    except (KeyError,TypeError,AttributeError,struct.error,OverflowError) as exc:
        raise ValueError('malformed radio-link metadata') from exc


def _resolve(banks, records, *, catalog, max_nodes):
    consume=music_catalog.budget(max_nodes)
    if not isinstance(banks,list) or not isinstance(records,list):
        raise ValueError('radio-link inputs must be lists')
    consume(len(records)+len(banks))
    index=defaultdict(list)
    for row in records:
        archive=_archive(row['archive']);key=_word(row['hash_b'],'hash B')
        duration=_uint(row['duration_ms'],'record duration')
        offset=_uint(row['offset'],'record offset',2**63-1)
        config_id=_uint(row['config_id'],'config id',0xffff)
        item=dict(archive=archive,offset=offset,config_id=config_id,
                  hash_b=f'0x{key:08x}',duration_ms=duration)
        if catalog is not None:
            annotated=music_catalog.annotate(item,catalog,consume=consume)
            item.update(catalog_matches=annotated['catalog_matches'],
                        catalog_match_status=annotated['catalog_match_status'])
        index[archive,key&0x1fffffff].append(item)
    observations=[];queries=[];excluded=[];seen_banks=set()
    for bank in banks:
        if not isinstance(bank,dict):raise ValueError('invalid AWC bank metadata')
        archive=_archive(bank.get('archive'));offset=_uint(bank.get('offset'),'AWC offset',2**63-1)
        source=dict(archive=archive,awc_offset=offset)
        identity=archive,offset
        if identity in seen_banks:raise ValueError('duplicate archive/offset in AWC metadata report')
        seen_banks.add(identity)
        streams=bank.get('streams');radio=bank.get('radio')
        if not isinstance(streams,list) or not isinstance(radio,dict):
            raise ValueError('AWC metadata must include streams and --radio tables')
        consume(len(streams));channels=[];stream_ids={}
        for stream in streams:
            i=_uint(stream['index'],'stream index',8191)
            if i in stream_ids:raise ValueError('duplicate AWC stream index')
            stream_ids[i]=_uint(stream['id'],'stream id',0x1fffffff)
            music=stream.get('music')
            if not music or music.get('error'):continue
            entries=music.get('channels')
            if not isinstance(entries,list) or not 1<=len(entries)<=32:
                raise ValueError('invalid radio-link channel table')
            consume(len(entries))
            for ordinal,c in enumerate(entries):
                if _uint(c['index'],'channel index',31)!=ordinal:raise ValueError('channel order differs from descriptor')
                raw_id=_uint(c['id'],'channel id',0x1fffffff)
                samples=_uint(c['samples'],'sample count')
                mode=_uint(c.get('channels_per_record'),'channels per record',255)
                rate=_uint(c['sample_rate'],'sample rate',65535)
                if mode not in (1,2) or not samples or samples%mode or rate!=48000:continue
                frames=samples//mode
                if c.get('frames')!=frames:raise ValueError('radio-link frame count differs from interleaved samples')
                channels.append(dict(stream_index=i,channel_index=ordinal,id=raw_id,frames=frames,rate=rate))
        tables=radio.get('tables')
        if not isinstance(tables,list):raise ValueError('invalid radio-link tables')
        consume(len(tables));local=defaultdict(list);table_keys=set()
        for table in tables:
            if table.get('type')!='0xbd':continue
            si=_uint(table['stream_index'],'marker stream',8191)
            ci=_uint(table['chunk_index'],'marker chunk',6)
            if (si,ci) in table_keys:raise ValueError('duplicate marker table identity')
            table_keys.add((si,ci))
            origin=dict(source,marker_stream_index=si,marker_chunk_index=ci)
            if table.get('status')!='parsed':
                excluded.append(dict(origin,reason='marker table is not completely parsed'));continue
            identifier=_word(table['stream_id'],'marker stream id')
            if stream_ids.get(si)!=identifier:raise ValueError('marker stream id differs from source stream metadata')
            bound=_uint(table['bound_frames'],'marker frame bound')
            rows=table.get('markers')
            if not isinstance(rows,list):raise ValueError('missing raw marker records')
            consume(len(rows))
            raw=bytearray()
            for m in rows:
                raw.extend(struct.pack('<4I',_word(m['tag'],'marker tag'),
                    _word(m['raw_value_bits'],'marker value bits'),
                    _uint(m['position_frames'],'marker position'),_uint(m['raw_reserved_u32'],'reserved marker word')))
            parsed=awc_radio.markers(bytes(raw),bound,max_records=max_nodes)
            chapters=awc_radio.chapters(parsed,bound);consume(len(chapters))
            matching=[c for c in channels if c['id']==identifier and c['frames']==bound]
            # A duplicate raw channel id is ambiguous even if durations differ.
            unique=len([c for c in channels if c['id']==identifier])==1 and len(matching)==1
            for chapter in chapters:
                query=dict(origin,track_id=chapter['track_id'],start_frames=chapter['start_frames'],
                           end_frames=chapter['end_frames'])
                queries.append(query)
                if unique:local[matching[0]['stream_index'],matching[0]['channel_index']].append((query,matching[0]))
            if chapters and not unique:
                excluded.append(dict(origin,reason='no unique exact local marker/channel id and frame-bound association'))
        for pairs in local.values():
            if len(pairs)!=1 or pairs[0][0]['start_frames']!=0:
                excluded.append(dict(source,stream_index=pairs[0][1]['stream_index'],
                    channel_index=pairs[0][1]['channel_index'],reason='channel has multiple TRACKIDs or no full interval from zero'))
                continue
            query,channel=pairs[0]
            matches=[]
            for row in index[archive,channel['id']]:
                consume()
                delta=abs(channel['frames']*1000-row['duration_ms']*channel['rate'])
                if delta<=DURATION_TOLERANCE_MS*channel['rate']:
                    matches.append(dict(row,duration_delta_ms=delta/channel['rate']))
            consume(1+len(matches))
            observations.append(dict(query,stream_index=channel['stream_index'],channel_index=channel['channel_index'],
                channel_id=f"0x{channel['id']:08x}",frames=channel['frames'],record_candidates=matches,
                evidence='exact local raw marker/channel id and full interval; record candidates use low29 hash plus duration only'))
    by_id=defaultdict(list)
    for observation in observations:by_id[observation['track_id']].append(observation)
    ids={q['track_id'] for q in queries};result=[]
    for identifier in sorted(ids):
        group=by_id[identifier];candidates={}
        for observation in group:
            for row in observation['record_candidates']:
                candidates.setdefault((row['archive'],row['offset'],row['hash_b']),row)
        matched=sorted(candidates.values(),key=lambda r:(r['hash_b'],r['archive'],r['offset']))
        keys={r['hash_b'] for r in matched}
        contexts={}
        for row in matched:
            for credit in row.get('catalog_matches',[]):
                consume()
                contexts.setdefault((row['hash_b'],credit['title'],credit['artist'],credit['station'],credit['source']),
                                    dict(credit,hash_b=row['hash_b']))
        status='unresolved' if not keys else 'record_candidate' if len(keys)==1 else 'conflicting_record_candidates'
        consume(1+len(matched)+len(contexts))
        result.append(dict(track_id=identifier,status=status,native_observations=group,
            record_candidates=matched,credit_candidates=list(contexts.values()),
            native_station_membership='unresolved',
            namespace_evidence='equal numeric TRACKID across supplied banks; global song identity is unproven'))
    counts=dict(track_ids=len(result),marker_intervals=len(queries),whole_channel_observations=len(observations),
        ids_with_record_candidates=sum(bool(r['record_candidates']) for r in result),
        conflicting_ids=sum(r['status']=='conflicting_record_candidates' for r in result),
        ids_with_credit_candidates=sum(bool(r['credit_candidates']) for r in result))
    return dict(format='gta6x-radio-trackid-links-v1',summary=counts,track_ids=result,
        marker_intervals=queries,excluded=excluded,duration_tolerance_ms=DURATION_TOLERANCE_MS,
        input_scope='supplied awc --radio metadata; original source bytes are not independently authenticated here',
        evidence='candidate joins only; full32 equality applies only from record hash B to optional external credit spellings; station membership and exact recording identity remain unresolved')
