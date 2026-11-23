"""Bounded indexed audio-config records and checked external name tables.

Derived from local source bytes, not another game's audio decoder. Header
families, record kinds and opaque tails retain raw values. Ordered wave-slot
lists are not radio playlists; station membership is not inferred.
"""
from __future__ import annotations

import hashlib
import os
import struct

from . import names, rpf, zlibcarve, music

MAX_RESOURCE = 32 * 1024 * 1024
MAX_NODES = 1_000_000
FOOTER = struct.pack('<4I', 4, 0, 4, 0)


class ConfigLimitError(ValueError):
    pass


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _budget(limit):
    if type(limit) is not int or not 1 <= limit <= MAX_NODES:
        raise ValueError(f'max_nodes must be an integer from 1 to {MAX_NODES}')
    used = 0

    def consume(n=1):
        nonlocal used
        if used+n > limit:
            raise ConfigLimitError('audio-config output exceeds node limit')
        used += n
    return consume, lambda: used


def parse_index(data: bytes, *, max_nodes=100000):
    """Read one complete bounded index; record spans are upper bounds only."""
    consume, used = _budget(max_nodes)
    consume()
    if not isinstance(data, bytes) or not 32 <= len(data) <= MAX_RESOURCE:
        raise ValueError('audio-config input size is unsupported')
    family, size = struct.unpack_from('<II', data)
    if family > 65535 or size < 5 or size > len(data)-28:
        raise ValueError('audio-config data extent is invalid or incomplete')
    index_at = 8+size
    if data[index_at:index_at+16] != FOOTER:
        raise ValueError('unsupported audio-config index prefix')
    count = struct.unpack_from('<I', data, index_at+16)[0]
    if not count or count > (len(data)-index_at-20)//8:
        raise ValueError('audio-config index count exceeds available bytes')
    consume(count)
    entries = []
    keys, offsets = set(), set()
    for i in range(count):
        key, offset = struct.unpack_from('<II', data, index_at+20+8*i)
        if key in keys or offset in offsets:
            raise ValueError('audio-config index has duplicate hashes or record offsets')
        if not 4 <= offset < size:
            raise ValueError('audio-config record offset escapes its data region')
        keys.add(key); offsets.add(offset); entries.append((key, offset))
    ordered = sorted(offsets)
    if ordered[0] != 4:
        raise ValueError('audio-config index does not begin after the raw data word')
    ends = dict(zip(ordered, ordered[1:]+[size]))
    records = []
    for i, (key, offset) in enumerate(entries):
        start, end = 8+offset, 8+ends[offset]
        records.append(dict(ordinal=i, name_hash=f'0x{key:08x}',
            data_offset=start, byte_length=end-start,
            extent_interpretation='index-bounded storage; complete object extent unconfirmed',
            raw_kind_u8=data[start], name=None, name_status='unresolved'))
    tail = index_at+20+8*count
    return dict(status='indexed', raw_family=family, byte_length=len(data),
        sha256=_hash(data), data_word_bits=f'0x{struct.unpack_from("<I",data,8)[0]:08x}',
        data_region=dict(data_offset=8, byte_length=size),
        index=dict(data_offset=index_at, byte_length=20+8*count, record_count=count),
        records=records, opaque_tail=dict(data_offset=tail, byte_length=len(data)-tail,
            sha256=_hash(data[tail:]), interpretation='uninterpreted'), nodes=used())


def _strings(data):
    if not data or len(data)>MAX_RESOURCE or data[-1:] != b'\0':
        return None
    result = {}
    at = 0
    while at < len(data):
        end = data.find(b'\0', at, min(len(data),at+257))
        if end <= at or any(c<32 or c>126 for c in data[at:end]):
            return None
        result[at] = data[at:end].decode('ascii')
        if len(result)>MAX_NODES:
            raise ConfigLimitError('audio-config name table exceeds work limit')
        at = end+1
    return result


def attach_names(view, data, table):
    """Resolve family-26 offsets only if the entire table/index agrees.

    Returns a new record list or None. No source proximity or ordinal pairing
    is used; every encoded offset, complete string boundary and hash is checked.
    """
    if view['raw_family'] != 26:
        return None
    strings = _strings(table)
    if strings is None or len(strings) != len(view['records']):
        return None
    result, occupied = [], set()
    for record in view['records']:
        at = record['data_offset']
        if record['byte_length']<4:
            return None
        offset = struct.unpack_from('<I',data,at)[0] >> 8
        name = strings.get(offset)
        if name is None or offset in occupied or names.joaat(name) != int(record['name_hash'],16):
            return None
        occupied.add(offset)
        result.append(dict(record, name=name, name_status='offset_and_hash_match',
            name_table_offset=offset,
            raw_after_name_word=data[at+4:at+min(8,record['byte_length'])].hex()))
    return result


def wave_slot_list(view, data, *, consume):
    """Link the measured named list to all local kind-8 records, atomically."""
    key = f'0x{names.joaat("WaveSlotsList"):08x}'
    owner = next((r for r in view['records'] if r['name_hash']==key),None)
    if owner is None:
        return dict(status='unresolved', reason='no local WaveSlotsList record', entries=[])
    try:
        if view['raw_family']!=26 or owner['name']!='WaveSlotsList':
            raise ValueError('wave-slot list requires the checked local name table')
        at, size = owner['data_offset'],owner['byte_length']
        if size<12 or data[at]!=9 or data[at+4:at+8]!=b'\xaa'*4:
            raise ValueError('unsupported wave-slot list header')
        count=struct.unpack_from('<I',data,at+8)[0]
        if not count or size!=12+4*count:
            raise ValueError('wave-slot list count does not exhaust its index-bounded span')
        targets={r['name_hash']:r for r in view['records'] if r['raw_kind_u8']==8}
        values=[f'0x{struct.unpack_from("<I",data,at+12+4*i)[0]:08x}' for i in range(count)]
        if len(set(values))!=count or set(values)!=set(targets):
            raise ValueError('wave-slot list does not cover the exact local kind-8 index')
        consume(1+count)
        return dict(status='complete', owner_hash=key, count=count,
            interpretation='stored wave-slot listing order only; not a radio playlist',
            entries=[dict(ordinal=i, name_hash=value, data_offset=targets[value]['data_offset'],
                          name=targets[value]['name']) for i,value in enumerate(values)])
    except ConfigLimitError:
        raise
    except ValueError as exc:
        return dict(status='unresolved', reason=str(exc), entries=[])


def _sources(path, start, end):
    """Join only immediate, zero-padded full pages through a short terminal."""
    group=[]
    with open(path,'rb') as fh:
        for blob in zlibcarve.carve_streams(path,start=start,length=end-start,
                min_out=8,max_out=MAX_RESOURCE):
            if group:
                last=group[-1];aligned=(last.offset+last.compressed+15)&~15
                fh.seek(last.offset+last.compressed)
                contiguous=(blob.offset==aligned and not any(fh.read(aligned-last.offset-last.compressed)))
                if last.size!=65536 or not contiguous:
                    yield group,last.size<65536
                    group=[]
            group.append(blob)
            if sum(b.size for b in group)>MAX_RESOURCE:
                raise ConfigLimitError('audio-config resource exceeds assembly limit')
            if blob.size<65536:
                yield group,True;group=[]
        if group:yield group,False


def inspect_file(path, *, start=None, length=64*1024*1024, max_nodes=100000,
                 min_ms=20000, max_ms=2000000):
    """Inspect selected archive metadata; unknown families/tails stay explicit."""
    consume, used = _budget(max_nodes)
    if any(type(v) is not int for v in (min_ms,max_ms)) or not 0<=min_ms<=max_ms<=0xffffffff:
        raise ValueError('audio-config duration range is invalid')
    if type(length) is not int or length<1:
        raise ValueError('audio-config scan length must be positive')
    if start is None:
        start=rpf.read_header(path).index_size
    if type(start) is not int or start<0:
        raise ValueError('audio-config scan start must be nonnegative')
    end=min(os.path.getsize(path),start+length)
    if start>end:
        raise ValueError('audio-config scan start exceeds file bounds')
    resources=[];tables={};refused=[];payloads={}
    for group,complete in _sources(path,start,end):
        data=b''.join(b.data for b in group);source=dict(offset=group[0].offset,
            segments=[[b.offset,b.compressed,b.size] for b in group],sha256=_hash(data))
        consume()
        if not complete:
            refused.append(dict(source,reason='no short terminal page within the selected range'));continue
        strings=_strings(data)
        if strings is not None:
            consume(len(strings))
            tables.setdefault(_hash(data),(data,source));continue
        if len(data)<12 or struct.unpack_from('<I',data)[0]>65535:
            continue
        try:
            view=parse_index(data,max_nodes=max(1,max_nodes-used()))
            consume(view.pop('nodes'))
        except ConfigLimitError:raise
        except ValueError as exc:
            refused.append(dict(source,reason=str(exc)));continue
        view['source']=source;resources.append(view);payloads[view['sha256']]=data
    for view in resources:
        data=payloads[view['sha256']];matches=[]
        for digest,(table,source) in tables.items():
            records=attach_names(view,data,table)
            if records is not None:matches.append((records,source))
        if len(matches)==1:
            view['records'],view['name_table_source']=matches[0]
        elif matches:
            view['name_table_reason']='multiple complete matching name tables; not selected'
        else:view['name_table_reason']='no supported complete offset/hash-matching name table'
        view['wave_slots']=wave_slot_list(view,data,consume=consume)
        observations=[]
        for record in view['records']:
            start=record['data_offset'];stop=start+record['byte_length']
            for item in music.scan(data[start:stop],min_ms=min_ms,max_ms=max_ms):
                if item.offset+46>record['byte_length']:
                    continue
                consume()
                observations.append(dict(item.as_dict(),data_offset=start+item.offset,
                    owner_hash=record['name_hash'],owner_name=record['name'],
                    owner_kind_u8=record['raw_kind_u8'],
                    interpretation='existing music-marker observation within one indexed record; station relationship unknown'))
        view['music_records']=observations
    return dict(status='partial' if refused else 'indexed', resources=resources,refused=refused,
        summary=dict(resources=len(resources),records=sum(len(v['records']) for v in resources),
            names_resolved=sum(r['name'] is not None for v in resources for r in v['records']),
            music_records=sum(len(v['music_records']) for v in resources),
            wave_slot_links=sum(len(v['wave_slots']['entries']) for v in resources),nodes=used()),
        radio_linkage=dict(status='unresolved',reason='station membership, track ordering and playlist reference grammar are not established'))
