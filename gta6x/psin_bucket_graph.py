"""Checked bucket-reference associations between existing typed PSIN rows.

This consumes same-source reader reports, not arbitrary authenticated JSON.
Opaque keys and inline spans never become typed nodes or guessed references.
"""
from __future__ import annotations

import struct

PROFILE = 'existing_checked_bucket_references_v1'
REFERENCE_PROFILE = 'local_bucket_reference_entries_v1'
INLINE_PROFILE = 'local_bucket_structure_entries_v1'
MAX_ITEMS = 2_000_000


def _integer(value, label, maximum=16*1024*1024):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('invalid bucket-graph '+label)
    return value


def _bits(value, length, label):
    if not isinstance(value,str) or len(value)!=2+2*length or not value.startswith('0x') or any(c not in '0123456789abcdefABCDEF' for c in value[2:]):
        raise ValueError('invalid bucket-graph '+label)
    try:
        return int(value,16).to_bytes(length,'little')
    except (ValueError,OverflowError) as exc:
        raise ValueError('invalid bucket-graph '+label) from exc


def append(report, nodes, sources, identities, blocks, edges, *, consume, edge):
    """Append validated logical bucket associations under the graph budget.

    A source is the existing typed map owner, including a checked embedded
    field path. The edge records the intervening physical bucket/entry location;
    it is not advertised as a direct pointer stored in that owner's field.
    """
    consume()
    if (not isinstance(report,dict) or report.get('format')!='gta6x-psin-bucket-maps-v1'
            or report.get('status') not in ('complete','partial')):
        raise ValueError('bucket graph requires an available same-source bucket report')
    digest=report.get('source_sha256')
    _bits('0x'+digest if isinstance(digest,str) else None,32,'source digest')
    mappings=report.get('maps')
    if not isinstance(mappings,list) or len(mappings)>MAX_ITEMS:
        raise ValueError('invalid bucket-graph map list')
    counts=dict(bucket_maps_supported=0,bucket_maps_unresolved=0,bucket_reference_edges=0,
        bucket_inline_maps_excluded=0,bucket_inline_entries_excluded=0,
        bucket_scan_partial=int(report['status']!='complete'))
    for mi,mapping in enumerate(mappings):
        consume()
        if not isinstance(mapping,dict) or mapping.get('status') not in ('complete','unresolved'):
            raise ValueError('invalid bucket-graph map view')
        entries=mapping.get('entries')
        if not isinstance(entries,list) or len(entries)>MAX_ITEMS:
            raise ValueError('invalid bucket-graph entry list')
        if mapping['status']!='complete':
            if entries:raise ValueError('unresolved bucket map contains an entry prefix')
            counts['bucket_maps_unresolved']+=1
            continue
        profile=mapping.get('profile')
        if profile==INLINE_PROFILE:
            counts['bucket_inline_maps_excluded']+=1
            counts['bucket_inline_entries_excluded']+=len(entries)
            continue
        if profile!=REFERENCE_PROFILE:
            counts['bucket_maps_unresolved']+=1
            continue
        owner=mapping.get('owner')
        if not isinstance(owner,dict):raise ValueError('invalid bucket-graph source owner')
        bi=_integer(owner.get('block_index'),'source block',len(blocks))
        ri=_integer(owner.get('record_index'),'source record')
        source=identities.get((bi,ri))
        if source is None:raise ValueError('bucket owner selects no existing typed record')
        current=sources[source]
        path=mapping.get('field_path')
        if not isinstance(path,list) or not 1<=len(path)<=64:
            raise ValueError('invalid bucket-graph source field path')
        consume(len(path))
        for depth,index in enumerate(path):
            fields=current.get('fields')
            fi=_integer(index,'source field index',MAX_ITEMS)
            if not isinstance(fields,list) or fi>=len(fields):
                raise ValueError('bucket source field path does not select existing fields')
            field=fields[fi]
            if not isinstance(field,dict):raise ValueError('invalid bucket source field')
            relative=_integer(field.get('data_offset'),'source field offset')
            if relative>=current['byte_length']:
                raise ValueError('bucket source field exceeds its existing owner')
            start=current['data_offset']+relative
            if depth<len(path)-1:
                child=field.get('value')
                if (field.get('type_word')!='0x00000005' or field.get('type_name')!='embedded_structure'
                        or not isinstance(child,dict) or not isinstance(child.get('fields'),list)
                        or child.get('status') not in ('complete','partial')
                        or field.get('status')!=child.get('status')
                        or child.get('data_offset')!=start
                        or type(child.get('byte_length')) is not int or child['byte_length']<=0
                        or start+child['byte_length']>current['data_offset']+current['byte_length']):
                    raise ValueError('bucket embedded source path lacks an exact existing child')
                current=child
        if (any(owner.get(key)!=current.get(key) for key in ('data_offset','byte_length','structure_hash'))
                or field.get('type_word')!='0x00000075' or field.get('status')=='descriptor'
                or field.get('hash')=='0x00000100' or field.get('hash')!=mapping.get('field_hash')
                or relative+16>current['byte_length']
                or mapping.get('header_data_offset')!=start or mapping.get('header_byte_length')!=16):
            raise ValueError('bucket source owner/header differs from existing field identity')
        buckets=_integer(mapping.get('bucket_count'),'bucket count',MAX_ITEMS)
        count=_integer(mapping.get('count'),'entry count',MAX_ITEMS)
        if not buckets or not count or count!=len(entries) or count>16*buckets:
            raise ValueError('bucket graph counts disagree with complete entries')
        raw=_bits(mapping.get('header_bits'),16,'header bits')
        nb,nc,word=struct.unpack('<IIQ',raw)
        if (nb,nc)!=(buckets,count) or _bits(mapping.get('reference_bits'),8,'allocation reference')!=raw[8:]:
            raise ValueError('bucket graph raw header disagrees with stored counts/reference')
        allocation=mapping.get('target')
        if not isinstance(allocation,dict):raise ValueError('invalid bucket-graph allocation')
        number,offset=word&0xfffff,word>>20
        if not 1<=number<=len(blocks):raise ValueError('bucket graph allocation has invalid block ID')
        block=blocks[number-1];begin=block['data_offset']+offset;length=272*buckets
        for key in ('block_index','byte_offset','data_offset','byte_length'):
            _integer(allocation.get(key),'allocation '+key)
        if (allocation.get('block_index')!=number-1 or allocation.get('byte_offset')!=offset
                or allocation.get('data_offset')!=begin or allocation.get('byte_length')!=length
                or allocation.get('bucket_structure_hash')!=block['type_hash']
                or offset%272 or offset>block['byte_length'] or length>block['byte_length']-offset):
            raise ValueError('bucket graph allocation disagrees with existing block span')
        for ordinal in range(buckets):
            consume()
            node_index=identities.get((number-1,offset//272+ordinal))
            if node_index is None:raise ValueError('bucket allocation has no existing typed bucket row')
            node=nodes[node_index]
            if node['data_offset']!=begin+272*ordinal or node['byte_length']!=272 or node['structure_hash']!=block['type_hash']:
                raise ValueError('bucket allocation differs from existing typed bucket stride')
        occupied=set()
        for ei,entry in enumerate(entries):
            consume()
            if not isinstance(entry,dict) or type(entry.get('index')) is not int or entry['index']!=ei:
                raise ValueError('invalid bucket-graph entry index')
            bucket_index=_integer(entry.get('bucket_index'),'entry bucket index',buckets-1)
            slot=_integer(entry.get('slot_index'),'entry slot',15)
            position=begin+272*bucket_index+16+16*slot
            if ((bucket_index,slot) in occupied or entry.get('entry_data_offset')!=position
                    or entry.get('entry_byte_length')!=16 or 'value_span' in entry):
                raise ValueError('bucket entry source differs from physical slot bounds')
            occupied.add((bucket_index,slot))
            _bits(entry.get('key_storage_bits'),8,'opaque key bits')
            _bits(entry.get('entry_structure_hash'),4,'entry schema hash')
            link=entry.get('target')
            reference=int.from_bytes(_bits(entry.get('reference_bits'),8,'entry reference'),'little')
            if not isinstance(link,dict) or link.get('status')!='record_reference':
                raise ValueError('bucket entry lacks a checked local record target')
            target_block=_integer(link.get('block_index'),'target block',len(blocks)-1)
            target_offset=_integer(link.get('data_offset'),'target data offset')
            expected=((target_offset-blocks[target_block]['data_offset'])<<20)|(target_block+1)
            if not reference or reference!=expected:
                raise ValueError('bucket entry reference disagrees with existing target address')
            edge(source,link,'bucket_reference',tuple(path),ei)
            edges[-1].update(bucket_map_index=mi,bucket_index=bucket_index,slot_index=slot,
                entry_data_offset=position,reference_data_offset=position+8,
                association_scope='checked owner-to-target association through bounded bucket storage; keys and ownership meaning unknown')
            counts['bucket_reference_edges']+=1
        counts['bucket_maps_supported']+=1
    return counts
