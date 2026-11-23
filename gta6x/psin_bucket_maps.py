"""Local PSIN bucket-entry/reference associations from discovery bytes.

Exact schema-framed reference and embedded-structure values are supported. Keys, lookup
semantics, field names and application ownership remain unknown. No runtime
station, song or playlist meaning follows from these bounded associations.
"""
from __future__ import annotations

import hashlib
import struct

from . import psin,psin_schema,psin_references
from .psin_blocks import parse_blocks

PROFILE='local_bucket_reference_entries_v1'
STRUCTURE_PROFILE='local_bucket_structure_entries_v1'
STRUCTURE_VALUE_SIZES=frozenset((16,24,40))
MAX_BYTES=16*1024*1024


class BucketMapLimitError(ValueError):
    pass


def _entries(data,start,field,owner,block_end,blocks,structures,consume):
    result=dict(status='unresolved',candidate_profile=PROFILE,entries=[])
    def refuse(reason):return dict(result,reason=reason)
    if field.type_word!=0x75 or field.name_hash==0x100:
        return refuse('unsupported bucket-map field attributes')
    if (field.data_offset+16>owner.byte_size or start<0 or start+16>min(block_end,len(data))
            or not psin_references.field_slot_clear(owner,field,16)):
        return refuse('bucket-map header exceeds or aliases its local owning slot')
    ki,vi=field.auxiliary&0xffff,field.auxiliary>>16
    if ki==vi or max(ki,vi)>=len(owner.fields):return refuse('bucket-map descriptor indices are invalid')
    key,value=owner.fields[ki],owner.fields[vi]
    inline=value.type_word==5
    if inline:result['candidate_profile']=STRUCTURE_PROFILE
    if any(d.name_hash!=0x100 or d.data_offset!=0 for d in (key,value)):
        return refuse('bucket-map requires local synthetic descriptors at zero')
    if not inline and any(d.auxiliary for d in (key,value)):
        return refuse('bucket-map requires local synthetic descriptors at zero')
    if key.type_word!=0x1b4d or key.auxiliary or value.type_word not in (7,5):
        return refuse('unsupported bucket-map key/value profile; only opaque-key/local-reference values validated')
    value_schema=None
    value_width=8
    if inline:
        values=structures.get(value.auxiliary,[])
        if len(values)!=1 or values[0].byte_size not in STRUCTURE_VALUE_SIZES:
            return refuse('structure-valued bucket requires one local value schema with a discovery-validated 16/24/40-byte extent')
        value_schema=values[0];value_width=value_schema.byte_size
    buckets,count,word=struct.unpack_from('<IIQ',data,start)
    result.update(header_data_offset=start,header_byte_length=16,
        header_bits='0x'+data[start:start+16][::-1].hex(),bucket_count=buckets,count=count,
        reference_bits=f'0x{word:016x}',key_descriptor_index=ki,value_descriptor_index=vi)
    if not buckets or not count or count>buckets*16:
        return refuse('empty or over-capacity bucket-map profile is not validated')
    number,offset=word&0xfffff,word>>20
    if not 1<=number<=len(blocks):return refuse('bucket-map reference has an invalid block ID')
    target=blocks[number-1];definitions=structures.get(target.type_hash,[])
    if len(definitions)!=1:return refuse('bucket-map requires one unambiguous local bucket schema')
    bucket=definitions[0]
    if len(bucket.fields)!=4:return refuse('unsupported bucket schema field count')
    controls,slots=bucket.fields[1],bucket.fields[3]
    if (bucket.fields[0].name_hash!=0x100 or bucket.fields[0].data_offset!=0
            or bucket.fields[0].type_word!=0x11 or bucket.fields[0].auxiliary
            or controls.name_hash==0x100 or controls.data_offset!=0 or controls.type_word!=0x50 or controls.auxiliary!=16
            or bucket.fields[2].name_hash!=0x100 or bucket.fields[2].data_offset!=0 or bucket.fields[2].type_word!=5
            or slots.name_hash==0x100 or slots.data_offset!=16 or slots.type_word!=0x00020050 or slots.auxiliary!=16
            or not psin_references.field_slot_clear(bucket,controls,16)):
        return refuse('bucket schema differs from exact 16-control/16-entry descriptor layout')
    entries=structures.get(bucket.fields[2].auxiliary,[])
    if len(entries)!=1:return refuse('bucket entry requires one unambiguous local schema')
    entry=entries[0]
    if (entry.byte_size!=8+value_width or len(entry.fields)!=2
            or any(f.name_hash==0x100 for f in entry.fields)
            or entry.fields[0].data_offset!=0 or entry.fields[0].type_word!=key.type_word or entry.fields[0].auxiliary!=key.auxiliary
            or entry.fields[1].data_offset!=8 or entry.fields[1].type_word!=value.type_word or entry.fields[1].auxiliary!=value.auxiliary
            or bucket.byte_size!=16+16*entry.byte_size):
        return refuse('entry schema differs from bounded opaque-key/value layout' if inline else
                      'entry schema differs from bounded opaque-key/eight-byte-reference layout')
    stride=bucket.byte_size
    if target.byte_length%stride or offset%stride or offset>target.byte_length or buckets>(target.byte_length-offset)//stride:
        return refuse('bucket-map allocation is not a whole bounded bucket-record span')
    begin=target.data_offset+offset
    if begin<0 or begin+buckets*stride>len(data):raise ValueError('bucket-map span exceeds container bounds')
    pending=[]
    # Validate every occupied and empty slot before exposing any entry links.
    for bi in range(buckets):
        at=begin+bi*stride;consume()
        for si in range(16):
            consume();control=data[at+si];position=at+16+si*entry.byte_size;raw=data[position:position+entry.byte_size]
            if control==0x80:
                if any(raw):return refuse('empty bucket slot has nonzero unvalidated storage')
                continue
            if control>0x7f:return refuse('unsupported bucket control marker')
            if control!=(struct.unpack_from('<I',raw)[0]&0x7f):return refuse('bucket control differs from low-seven-bit key witness')
            if len(pending)>=count:return refuse('bucket occupancy exceeds declared entry count')
            if inline:
                value_span=dict(status='embedded_structure_span',data_offset=position+8,
                    byte_length=value_width,structure_hash=f'0x{value_schema.name_hash:08x}',
                    schema_definition_offset=value_schema.section_offset,
                    interpretation='inline locally declared storage only; fields and nested references not decoded')
            else:
                reference=psin_references.bind_record(struct.unpack_from('<Q',raw,8)[0],blocks,structures,data_size=len(data))
                if reference['status']!='record_reference':return refuse('occupied bucket slot lacks a bounded nonnull local record target: '+reference.get('reason',reference['status']))
            consume()
            row=dict(index=len(pending),bucket_index=bi,slot_index=si,
                entry_data_offset=position,entry_byte_length=entry.byte_size,entry_structure_hash=f'0x{entry.name_hash:08x}',
                key_storage_bits='0x'+raw[:8][::-1].hex(),key_meaning='opaque; no lookup or primitive meaning assigned')
            if inline:row['value_span']=value_span
            else:row.update(reference_bits=f'0x{struct.unpack_from("<Q",raw,8)[0]:016x}',target=reference)
            pending.append(row)
    if len(pending)!=count:return refuse('bucket occupancy differs from declared entry count')
    grouped={}
    for row in pending:grouped.setdefault(row['key_storage_bits'],[]).append(row)
    duplicates=[]
    for key_bits,rows in grouped.items():
        if len(rows)>1:
            consume()
            duplicate=dict(key_storage_bits=key_bits,entry_indices=[r['index'] for r in rows])
            if inline:duplicate['distinct_value_spans']=len({r['value_span']['data_offset'] for r in rows})
            else:duplicate['distinct_targets']=len({(r['target']['block_index'],r['target']['record_index']) for r in rows})
            duplicates.append(duplicate)
    result.update(status='complete',profile=result.pop('candidate_profile'),entries=pending,
        duplicate_key_storage_groups=duplicates,
        target=dict(block_index=target.index,byte_offset=offset,data_offset=begin,byte_length=buckets*stride,
            bucket_structure_hash=f'0x{bucket.name_hash:08x}'),
        interpretation='bounded local bucket entries/reference targets only; semantic ownership and membership unproven')
    if inline:
        result.update(mode='embedded_structure_spans',value_type='structure',
            value_structure_hash=f'0x{value_schema.name_hash:08x}',
            interpretation='bounded inline local structure spans only; values, nested pointers and semantic ownership remain unproven')
    return result


def inspect(data,*,max_nodes=100000,max_depth=16,with_values=False,with_pool_spans=False):
    """Inspect exact local bucket maps; no external registry or pointer expansion."""
    if with_pool_spans:with_values=True
    if type(max_nodes) is not int or max_nodes<1:raise BucketMapLimitError('bucket-map node budget must be positive')
    if type(max_depth) is not int or not 1<=max_depth<=64:raise ValueError('bucket-map depth must be 1..64')
    if not isinstance(data,bytes) or len(data)>MAX_BYTES:raise ValueError('bucket-map input exceeds byte bounds')
    container=psin.parse_container(data)
    if container is None or not container.checksum_verified:raise ValueError('bucket-map reader requires complete checksum-verified PSIN')
    schema=psin_schema.parse_schema(data);structures=psin_schema._index(schema.structures)
    enums=psin_schema._index(schema.enum_table.definitions)
    body=container.section('PSIN');blocks=parse_blocks(data[:body.length]);used=0;maps=[];skipped=[];missing=[];depth_limited=0
    def consume():
        nonlocal used
        if used>=max_nodes:raise BucketMapLimitError('PSIN bucket-map work/output exceeds node budget')
        used+=1
    consume()
    pool_index=None
    if with_pool_spans:
        from . import psin_bucket_pools
        pool_index=psin_bucket_pools.collect(data,blocks,structures,consume=consume,max_depth=max_depth,
            read_bucket=lambda start,field,owner,end:_entries(data,start,field,owner,end,blocks,structures,consume))
    value_counts=dict(bucket_value_records=0,bucket_value_fields=0,bucket_value_fields_complete=0,
        bucket_value_fields_unresolved=0,bucket_value_array_links=0,bucket_value_reference_links=0,
        bucket_value_nested_maps=0,bucket_value_nested_maps_unresolved=0,
        bucket_value_map_fields=0,bucket_value_map_fields_complete=0,bucket_value_map_links=0)
    if with_pool_spans:
        value_counts.update(bucket_value_pool_fields=0,bucket_value_pool_spans_complete=0,
            bucket_value_pool_spans_unresolved=0,bucket_value_pool_words=0)
    def count_value(value):
        value_counts['bucket_value_records']+=1
        for field in value['fields']:
            if field['status']=='descriptor':continue
            value_counts['bucket_value_fields']+=1
            value_counts['bucket_value_fields_complete']+=field['status']=='complete'
            value_counts['bucket_value_fields_unresolved']+=field['status']!='complete'
            if 'array' in field and field['array']['status']=='complete':
                value_counts['bucket_value_array_links']+=len(field['array']['elements'])
            if 'entry_map' in field:
                value_counts['bucket_value_map_fields']+=1
                value_counts['bucket_value_map_fields_complete']+=field['entry_map']['status']=='complete'
                value_counts['bucket_value_map_links']+=len(field['entry_map']['entries'])
            if 'pool_span' in field:
                storage=field['pool_span']
                value_counts['bucket_value_pool_fields']+=1
                value_counts['bucket_value_pool_spans_complete']+=storage['status']=='complete'
                value_counts['bucket_value_pool_spans_unresolved']+=storage['status']!='complete'
                value_counts['bucket_value_pool_words']+=len(storage['words'])
            if field.get('reference',{}).get('status')=='record_reference':
                value_counts['bucket_value_reference_links']+=1
            if 'value' in field and isinstance(field['value'],dict) and 'fields' in field['value']:
                count_value(field['value'])
    def read_bucket(start,field,owner,end,depth,active):
        row=_entries(data,start,field,owner,end,blocks,structures,consume)
        if row.get('mode')=='embedded_structure_spans':
            from .psin_bucket_values import inspect_value
            for entry in row['entries']:
                span=entry['value_span'];definition=structures[int(span['structure_hash'],16)][0]
                value=inspect_value(data,definition,span['data_offset'],structures=structures,
                    enums=enums,blocks=blocks,consume=consume,read_bucket=read_nested_bucket,
                    depth=depth,max_depth=max_depth,active=active,pool_index=pool_index)
                entry['value_fields']=value;count_value(value)
            row['values_status']='complete' if all(e['value_fields']['status']=='complete' for e in row['entries']) else 'partial'
        return row
    def read_nested_bucket(start,field,owner,end,depth,active):
        value_counts['bucket_value_nested_maps']+=1
        row=read_bucket(start,field,owner,end,depth,active)
        value_counts['bucket_value_nested_maps_unresolved']+=row.get('values_status',row['status'])!='complete'
        return row
    def visit(owner,at,end,source,path,depth,active):
        nonlocal depth_limited
        consume()
        if at<0 or at+owner.byte_size>end:raise ValueError('bucket-map owner escapes its bounded record')
        for fi,field in enumerate(owner.fields):
            consume()
            if field.name_hash==0x100:continue
            if field.type_word==0x75:
                row=(read_bucket(at+field.data_offset,field,owner,end,depth,active) if with_values else
                    _entries(data,at+field.data_offset,field,owner,end,blocks,structures,consume))
                maps.append(dict(row,owner=dict(source,structure_hash=f'0x{owner.name_hash:08x}',
                    data_offset=at,byte_length=owner.byte_size),field_hash=f'0x{field.name_hash:08x}',field_path=list(path+(fi,))))
            elif field.type_word==5:
                definitions=structures.get(field.auxiliary,[])
                if len(definitions)!=1 or definitions[0].byte_size<=0:
                    missing.append(dict(source,field_path=list(path+(fi,)),structure_hash=f'0x{field.auxiliary:08x}',
                        reason='embedded owner lacks one positive-sized local schema; possible nested maps uninspected'))
                    continue
                child=definitions[0];start=at+field.data_offset
                if field.data_offset+child.byte_size>owner.byte_size:raise ValueError('embedded bucket-map owner exceeds record')
                if depth>=max_depth or (child.name_hash,start) in active:
                    depth_limited+=1;continue
                visit(child,start,start+child.byte_size,source,path+(fi,),depth+1,active|{(child.name_hash,start)})
    for block in blocks:
        consume();definitions=structures.get(block.type_hash,[])
        if len(definitions)!=1 or definitions[0].byte_size<=0 or block.byte_length%definitions[0].byte_size:
            skipped.append(dict(block_index=block.index,type_hash=f'0x{block.type_hash:08x}',
                reason='block lacks one positive-sized local schema tiling its full span'))
            continue
        owner=definitions[0]
        for ri in range(block.byte_length//owner.byte_size):
            at=block.data_offset+ri*owner.byte_size
            visit(owner,at,at+owner.byte_size,dict(block_index=block.index,record_index=ri),(),0,{(owner.name_hash,at)})
    complete=[m for m in maps if m['status']=='complete']
    result=dict(format='gta6x-psin-bucket-maps-v1',status='partial' if len(complete)!=len(maps) or depth_limited or skipped or missing else 'complete',
        source_sha256=hashlib.sha256(data).hexdigest(),maps=maps,unrepresented_blocks=skipped,unresolved_embedded_owners=missing,
        summary=dict(nodes=used,maps=len(maps),maps_complete=len(complete),maps_unresolved=len(maps)-len(complete),
            entry_links=sum(len(m['entries']) for m in complete),unrepresented_blocks=len(skipped),
            unresolved_embedded_owners=len(missing),depth_limited=depth_limited),
        interpretation='local schema-bound associations only; keys, owner roles, station/song membership and lookup semantics remain unknown')
    if any(m.get('mode')=='embedded_structure_spans' for m in complete):
        result['summary'].update(reference_links=sum('target' in e for m in complete for e in m['entries']),
            structure_value_spans=sum('value_span' in e for m in complete for e in m['entries']))
    if with_values:
        result['summary'].update(value_counts)
        if value_counts['bucket_value_fields_unresolved'] or value_counts['bucket_value_nested_maps_unresolved']:
            result['status']='partial'
        result['values_status']='complete' if all(m.get('values_status',m['status'])=='complete' for m in maps) else 'partial'
        if result['values_status']!='complete':result['status']='partial'
    if with_pool_spans:
        result['summary'].update(bucket_pool_scan_complete=int(pool_index['scan_complete']),
            bucket_pool_headers=len(pool_index['headers']),
            bucket_pools_complete=sum(p['status']=='complete' for p in pool_index['pools'].values()),
            bucket_pools_unresolved=sum(p['status']!='complete' for p in pool_index['pools'].values()))
    return result
