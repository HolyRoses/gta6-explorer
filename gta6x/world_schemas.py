"""Source-backed native world declarations; names remain hash candidates.

The helper consumes normalized declarations from this project's verified readers.
It checks every declaration word against its bounded source table, without
interpreting world field types, values, pointers or application ownership.
"""
from __future__ import annotations

import hashlib
import json
import struct

from . import names, psin

MAX_RESOURCE = 16 * 1024 * 1024
BASE = 0x50000000


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _uint(value, bits, label):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError('invalid world-schema ' + label)
    return value


def _hash(value):
    if not isinstance(value, str) or len(value) != 10 or not value.startswith('0x'):
        raise ValueError('invalid world-schema declaration hash')
    try:
        return _uint(int(value, 16), 32, 'declaration hash')
    except ValueError as exc:
        raise ValueError('invalid world-schema declaration hash') from exc


def inspect_resource(data, kind, definitions, enums, *, consume, dictionary=None,
                     structure_hash=None, field_hash=None, type_word=None):
    """Return shared declarations and resource-local source offsets atomically.

    The caller already owns checksum/framing validation and the normalized input.
    This routine does not authenticate arbitrary persisted reader JSON. Queries
    annotate matches; no declaration or resource identity is removed. All work
    and emitted candidates use the enclosing catalogue's node budget.
    """
    used = 0
    def spend(n=1):
        nonlocal used
        consume(n); used += n
    spend()
    if not isinstance(data, bytes) or len(data) > MAX_RESOURCE or kind not in ('psin', '0drp'):
        raise ValueError('unsupported world-schema source')
    for value, label in ((structure_hash, 'structure query'), (field_hash, 'field query'), (type_word, 'type-word query')):
        if value is not None:
            _uint(value, 32, label)
    if (not isinstance(definitions, list) or not isinstance(enums, list)
            or len(definitions) > 65535 or len(enums) > 65535):
        raise ValueError('invalid world-schema declaration lists')
    # Preflight output before copying field/member tables or candidate strings.
    rows = 0
    for items, key in ((definitions, 'fields'), (enums, 'members')):
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get(key), list):
                raise ValueError('invalid world-schema declaration rows')
            words = item.get('unknown_words')
            if not isinstance(words, list) or len(words) != (4 if key == 'fields' else 2):
                raise ValueError('invalid world-schema unknown words')
            for word in words:
                _uint(word, 32, 'unknown word')
            if key == 'fields':
                _uint(item.get('byte_size'), 32, 'structure size')
            rows += len(item[key])
    spend(3 + 2 * (len(definitions) + len(enums) + rows))
    if dictionary is not None and (not isinstance(dictionary, dict)
            or any(not isinstance(dictionary.get(k, {}), dict) for k in ('hashes', 'exact'))):
        raise ValueError('world-schema names require hash/exact dictionary objects')
    candidate_cache = {}; rejected = 0
    def candidates(value):
        nonlocal rejected
        if dictionary is None:
            return []
        if value not in candidate_cache:
            found = []
            for family, algorithm in (('hashes', names.joaat), ('exact', names.joaat_exact)):
                bucket = dictionary.get(family, {}).get(f'{value:08x}', [])
                if not isinstance(bucket, list):
                    raise ValueError('invalid world-schema name candidate bucket')
                spend(len(bucket))
                for entry in bucket:
                    if (not isinstance(entry, (list, tuple)) or len(entry) != 2
                            or any(not isinstance(v, str) or '\0' in v or len(v) > 4096 for v in entry)):
                        raise ValueError('invalid world-schema name candidate')
                    text, source = entry
                    if not text or not text.isascii() or algorithm(text) != value:
                        rejected += 1
                        continue
                    found.append(dict(name=text, source=source,
                        hash_method='joaat_lowercase_ascii' if family == 'hashes' else 'joaat_exact_ascii',
                        status='hash_preimage_candidate', interpretation='hash equality only; field identity and meaning unconfirmed'))
            candidate_cache[value] = found
        spend(len(candidate_cache[value]))
        return [dict(v) for v in candidate_cache[value]]

    def span(at, size):
        if type(at) is not int or type(size) is not int or at < 0 or size < 0 or at > len(data) - size:
            raise ValueError('world-schema declaration span exceeds source')
        return data[at:at+size]

    if kind == 'psin':
        sections = psin._sections_tile(data)
        if sections is None:
            raise ValueError('world-schema requires complete PSIN section framing')
        by_tag = {s.tag:s for s in sections}; lsch=by_tag['LSCH']; lenm=by_tag['LENM']
        structure_at = lsch.offset + 8; enum_at = lenm.offset + 8
        fields_at = structure_at + 32 * len(definitions)
        members_at = enum_at + 24 * len(enums)
        span(structure_at, 32 * len(definitions)); span(enum_at, 24 * len(enums))
    else:
        span(0, 80)
        if data[16:20] != b'0DRP' or struct.unpack_from('<I', data, 20)[0] != 122:
            raise ValueError('unsupported world-schema 0DRP metadata version')
        ns,ne=struct.unpack_from('<HH',data,72)
        if (ns,ne)!=(len(definitions),len(enums)):
            raise ValueError('world-schema counts differ from source header')
        def table(at, count, stride):
            word=struct.unpack_from('<Q',data,at)[0]
            if not count:
                if word:raise ValueError('world-schema empty table has nonnull reference')
                return None
            position=word-BASE
            if position<80:raise ValueError('world-schema table reference overlaps header')
            span(position,count*stride)
            return position
        structure_at=table(40,len(definitions),32);enum_at=table(48,len(enums),24)

    structure_index={};enum_index={}
    for index, definition in enumerate(definitions):
        structure_index.setdefault(_hash(definition.get('hash')),[]).append(index)
    for index, definition in enumerate(enums):
        enum_index.setdefault(_hash(definition.get('hash')),[]).append(index)
    structures=[];enum_rows=[];structure_occurrences=[];enum_occurrences=[];usage={}
    structure_matches=[];field_matches=[]
    for index, definition in enumerate(definitions):
        at=structure_at+32*index;raw=span(at,32)
        name,a,b,c,word,width,tail,count=struct.unpack('<IIIIQIHH',raw)
        expected=(_hash(definition['hash']),*definition.get('unknown_words',[])[:3],
                  definition.get('byte_size'),definition.get('unknown_words',[None]*4)[-1],len(definition['fields']))
        if (name,a,b,c,width,tail,count)!=expected:
            raise ValueError('world-schema structure declaration differs from source words')
        if kind=='psin':
            if raw[16:24]!=b'\xaa'*8:raise ValueError('world-schema LSCH header padding differs')
            first=fields_at;fields_at+=16*count
            if fields_at>lsch.offset+lsch.length:raise ValueError('world-schema fields escape LSCH')
        else:
            first=word-BASE if count else None
            if count and first<80:raise ValueError('world-schema fields overlap 0DRP header')
            if not count and word:raise ValueError('world-schema empty fields have nonnull reference')
        if count:span(first,16*count)
        fields=[];offsets=[]
        for fi, values in enumerate(definition['fields']):
            if (not isinstance(values,list) or len(values)!=4
                    or any(type(v)is not int or not 0<=v<=0xffffffff for v in values)):
                raise ValueError('invalid world-schema field words')
            pos=first+16*fi;bits=span(pos,16)
            if tuple(values)!=struct.unpack('<4I',bits):raise ValueError('world-schema field differs from source words')
            fh,offset,code,aux=values
            if offset>=width:raise ValueError('world-schema field start exceeds structure')
            spend(len(structure_index.get(aux,[])) + len(enum_index.get(aux,[])))
            fields.append(dict(index=fi,hash=f'0x{fh:08x}',record_offset=offset,type_word=f'0x{code:08x}',
                type_low16=code&0xffff,type_high16=code>>16,auxiliary_bits=f'0x{aux:08x}',raw_bits='0x'+bits[::-1].hex(),
                name_candidates=candidates(fh),type_meaning='unknown in this world-schema view',
                auxiliary_word_matches=dict(structure_indices=list(structure_index.get(aux,[])),
                    enum_indices=list(enum_index.get(aux,[])),interpretation='stored u32 equality only; not a proven reference')))
            offsets.append(dict(field_index=fi,data_offset=pos,byte_length=16))
            spend(1 + (code not in usage));usage.setdefault(code,[]).append(dict(structure_index=index,field_index=fi))
            if (structure_hash is None or name==structure_hash) and (field_hash is None or fh==field_hash) and (type_word is None or code==type_word):
                if any(q is not None for q in (structure_hash,field_hash,type_word)):
                    spend();field_matches.append(dict(structure_index=index,field_index=fi))
        variant=_fingerprint(dict(format=kind,definition=definition))
        structures.append(dict(index=index,hash=definition['hash'],variant_id=variant,byte_size=width,
            unknown_words=[f'0x{v:08x}'for v in definition['unknown_words']],name_candidates=candidates(name),fields=fields))
        structure_occurrences.append(dict(structure_index=index,data_offset=at,byte_length=32,
            header_bits='0x'+raw[::-1].hex(),fields=offsets))
        if structure_hash is not None and name==structure_hash:
            spend();structure_matches.append(index)
    for index, definition in enumerate(enums):
        at=enum_at+24*index;raw=span(at,24);name,a,word,count,tail=struct.unpack('<IIQII',raw)
        if (name,a,count,tail)!=(_hash(definition['hash']),definition['unknown_words'][0],len(definition['members']),definition['unknown_words'][1]):
            raise ValueError('world-schema enum declaration differs from source words')
        if kind=='psin':
            if raw[8:16]!=b'\xee'*8:raise ValueError('world-schema LENM header padding differs')
            first=members_at;members_at+=16*count
            if members_at>lenm.offset+lenm.length:raise ValueError('world-schema members escape LENM')
        else:
            first=word-BASE if count else None
            if count and first<80:raise ValueError('world-schema members overlap 0DRP header')
            if not count and word:raise ValueError('world-schema empty members have nonnull reference')
        if count:span(first,16*count)
        members=[];offsets=[]
        for mi,values in enumerate(definition['members']):
            if (not isinstance(values,list)or len(values)!=3 or type(values[0])is not int
                    or not 0<=values[0]<1<<64 or any(type(v)is not int or not 0<=v<=0xffffffff for v in values[1:])):
                raise ValueError('invalid world-schema enum words')
            pos=first+16*mi;bits=span(pos,16)
            if tuple(values)!=struct.unpack('<QII',bits):raise ValueError('world-schema member differs from source words')
            value,mh,unknown=values
            members.append(dict(index=mi,hash=f'0x{mh:08x}',value_bits=f'0x{value:016x}',unknown_bits=f'0x{unknown:08x}',
                raw_bits='0x'+bits[::-1].hex(),name_candidates=candidates(mh)))
            offsets.append(dict(member_index=mi,data_offset=pos,byte_length=16))
        enum_rows.append(dict(index=index,hash=definition['hash'],unknown_words=[f'0x{v:08x}'for v in definition['unknown_words']],
            name_candidates=candidates(name),members=members))
        enum_occurrences.append(dict(enum_index=index,data_offset=at,byte_length=24,header_bits='0x'+raw[::-1].hex(),members=offsets))
    if kind=='psin' and (fields_at!=lsch.offset+lsch.length or members_at!=lenm.offset+lenm.length):
        raise ValueError('world-schema declarations do not exhaust LSCH/LENM sections')
    group_id=_fingerprint(dict(format=kind,structures=definitions,enums=enums))
    declarations=dict(format=kind,id=group_id,structures=structures,enums=enum_rows,
        type_usages=[dict(type_word=f'0x{k:08x}',occurrences=v)for k,v in sorted(usage.items())],
        query=dict(structure_hash=None if structure_hash is None else f'0x{structure_hash:08x}',
            field_hash=None if field_hash is None else f'0x{field_hash:08x}',type_word=None if type_word is None else f'0x{type_word:08x}',
            structure_indices=structure_matches,fields=field_matches),
        scope='raw format-qualified local declarations only; names are hash candidates, world meanings unknown')
    occurrences=dict(offset_space='decompressed resource bytes',structures=structure_occurrences,enums=enum_occurrences)
    return dict(declarations=declarations,occurrences=occurrences,summary=dict(nodes=used,structures=len(structures),
        fields=sum(len(s['fields'])for s in structures),enums=len(enum_rows),members=sum(len(e['members'])for e in enum_rows),
        name_candidates=sum(len(v)for v in candidate_cache.values()),name_candidates_rejected=rejected,
        structure_matches=len(structure_matches),field_matches=len(field_matches)))
