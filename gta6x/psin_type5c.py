"""Opt-in local typed-record spans for a source-checked type5c header profile.

The local descriptor and target schema independently declare record stride.
Equal stored words and complete target coverage only corroborate bounded spans;
primitive, logical-element, count/capacity and semantic owner meanings stay unknown.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import struct

from . import psin_bucket_maps, psin_field_context, psin_references, psin_schema
from .psin_blocks import parse_blocks

PROFILE='local_type5c_complete_typed_record_spans_v1'
MAX_HEADERS=4096
MAX_LINKS=4096
MAX_SOURCE_EVENTS=4096
MAX_LINEAGE_STEPS=262144


def inspect(data,schema,instances,*,consume,max_depth=16):
    """Return source-owned header/span proofs and existing record references.

    Fresh native schema/instance objects are required, not authenticated JSON.
    Only complete eligible-header scans may authorize whole typed-target coverage.
    Invalid headers, incomplete owners and ambiguous declarations fail closed;
    work or report limits raise without returning a prefix. Targets are not read
    as scalar values, expanded, or interpreted as application objects.
    """
    psin_field_context._validate_queries([],max_depth,0)
    if not isinstance(schema,psin_schema.Schema):
        raise ValueError('type5c spans require a local native schema')
    used=0
    def charge(n=1):
        nonlocal used
        consume(n);used+=n
    enum_defs=schema.enum_table.definitions if schema.enum_table else []
    charge(1+len(schema.structures)+sum(len(s.fields)for s in schema.structures)
           +len(enum_defs)+sum(len(e.members)for e in enum_defs))
    schema=deepcopy(schema)
    # Owner-walk depth counts transitions, while field paths include the final
    # header field. This changes no owner-scan limit.
    execute=psin_field_context._prepare(data,schema,instances,consume=charge,
                                      max_depth=min(64,max_depth+1),max_sample_bytes=0)
    source=execute([])
    blocks=parse_blocks(data[:struct.unpack_from('>I',data,4)[0]])
    structures=psin_schema._index(schema.structures)
    charge(len(blocks))
    source_blocks=[]
    for block in blocks:
        row=instances['blocks'][block.index]
        charge(1+(block.byte_length+4095)//4096)
        expected=dict(index=block.index,table_offset=block.table_offset,
            type_hash=f'0x{block.type_hash:08x}',data_offset=block.data_offset,
            byte_length=block.byte_length,
            sha256=hashlib.sha256(memoryview(data)[block.data_offset:block.data_offset+block.byte_length]).hexdigest())
        if not isinstance(row,dict)or any(row.get(k)!=v for k,v in expected.items()):
            raise ValueError('type5c spans source block identity differs from its instance view')
        charge();source_blocks.append(expected)
    headers=[];other_headers=[];visited=set();scan_complete=True;reasons=[];groups={}
    source_events=[];first_sources={};lineage_steps=0
    def owner_identity(owner,at):
        return dict(structure_hash=f'0x{owner.name_hash:08x}',data_offset=at,
            byte_length=owner.byte_size,declaration_section_offset=owner.section_offset)
    def field_identity(owner,field,fi,at):
        return dict(field_index=fi,hash=f'0x{field.name_hash:08x}',data_offset=field.data_offset,
            type_word=f'0x{field.type_word:08x}',auxiliary=f'0x{field.auxiliary:08x}',
            declaration_section_offset=field.section_offset,
            header_data_offset=at+field.data_offset)
    def copy_lineage(lineage):
        nonlocal lineage_steps
        steps=1+len(lineage['ancestry'])
        if steps>MAX_LINEAGE_STEPS-lineage_steps:
            raise ValueError('type5c spans exceed the source-lineage step report limit')
        charge(steps);lineage_steps+=steps
        return deepcopy(lineage)
    def source_event(kind,owner,at,lineage,**extra):
        if len(source_events)>=MAX_SOURCE_EVENTS:
            raise ValueError('type5c spans exceed the source-event report limit')
        source_events.append(dict(kind=kind,owner=owner_identity(owner,at),
            source=copy_lineage(lineage),**extra))
    def incomplete(reason):
        nonlocal scan_complete
        scan_complete=False
        if reason not in reasons:
            charge();reasons.append(reason)
    def collect_header(owner,field,fi,start,context,lineage):
        if len(headers)+len(other_headers)>=MAX_HEADERS:
            raise ValueError('type5c spans exceed the 4096-header report limit')
        charge(1+len(owner.fields))
        item=dict(index=len(headers),status='unresolved',owner_hash=f'0x{owner.name_hash:08x}',
            owner_byte_length=owner.byte_size,field_index=fi,field_hash=f'0x{field.name_hash:08x}',
            field_type_word=f'0x{field.type_word:08x}',field_auxiliary=f'0x{field.auxiliary:08x}',
            declaration_section_offset=field.section_offset,source_context=dict(context),
            header_data_offset=start,header_byte_length=16,record_links=[],
            parent_type_meaning='unknown',logical_element_meaning='unknown',semantic_owner='unknown')
        headers.append(item)
        origin=copy_lineage(lineage)
        if origin['field_path'] is not None:origin['field_path'].append(fi)
        origin.update(owner=owner_identity(owner,start-field.data_offset),
            field=field_identity(owner,field,fi,start-field.data_offset),
            instance_addressable=False,instance_replay_status='pending')
        origin['field']['header_byte_length']=16
        item['source_lineage']=origin
        di=field.type_word>>16
        if (field.auxiliary or di>=len(owner.fields)or owner.fields[di]is field):
            incomplete('eligible structured header has unsupported descriptor attributes')
            item['reason']='unsupported local structured descriptor attributes';return
        descriptor=owner.fields[di]
        if descriptor.name_hash!=0x100 or descriptor.data_offset!=0 or descriptor.type_word!=5:
            incomplete('eligible structured header descriptor is not an exact local synthetic structure')
            item['reason']='descriptor is not an exact local synthetic structure';return
        definitions=structures.get(descriptor.auxiliary,[])
        if len(definitions)!=1 or definitions[0].byte_size<=0:
            incomplete('structured descriptor has no unique positive-sized local definition')
            item['reason']='missing or ambiguous local target structure';return
        target_owner=definitions[0]
        item.update(descriptor_index=di,descriptor_structure_hash=f'0x{descriptor.auxiliary:08x}',
            declared_record_stride=target_owner.byte_size)
        if (field.data_offset<0 or field.data_offset+16>owner.byte_size or
                not psin_references.field_slot_clear(owner,field,16)or not 0<=start<start+16<=len(data)):
            incomplete('structured header is outside or overlaps its declared owner slot')
            item['reason']='header exceeds or aliases its local owner';return
        a,b,word=struct.unpack_from('<IIQ',data,start)
        item.update(first_word=a,second_word=b,reference_bits=f'0x{word:016x}',
                    header_bits='0x'+data[start:start+16][::-1].hex())
        if not a or a!=b or not word:
            incomplete('structured header requires equal positive words and a nonzero reference')
            item['reason']='empty, unequal or non-reference structured header is unvalidated';return
        number,offset=word&0xfffff,word>>20
        if not 1<=number<=len(blocks):
            incomplete('structured header has an invalid local block reference')
            item['reason']='invalid referenced local block';return
        target=blocks[number-1];stride=target_owner.byte_size
        if (target.type_hash!=descriptor.auxiliary or structures.get(target.type_hash)!=definitions
                or target.byte_length%stride or offset%stride or offset>target.byte_length
                or a>(target.byte_length-offset)//stride):
            incomplete('structured target type/stride or referenced whole-record range is invalid')
            item['reason']='reference is not a bounded whole-record span of the local descriptor type';return
        item['target']=dict(block_index=target.index,structure_hash=f'0x{target.type_hash:08x}',
            byte_offset=offset,data_offset=target.data_offset+offset,byte_length=a*stride)
        groups.setdefault(target.index,[]).append(item)
    def visit(owner,at,end,context,lineage,depth,active):
        charge()
        identity=owner.name_hash,at
        if identity in active:
            source_event('cycle',owner,at,lineage)
            incomplete('embedded owner cycle prevents a complete candidate scan');return
        if identity in visited:
            source_event('physical_alias',owner,at,lineage,first_source=first_sources[identity]);return
        visited.add(identity)
        first_sources[identity]=dict(root_record=lineage['root_record'],field_path=lineage['field_path'])
        if depth>max_depth:
            source_event('depth_limit',owner,at,lineage)
            incomplete('embedded owner depth limit prevents a complete candidate scan');return
        if at<0 or at+owner.byte_size>min(end,len(data)):
            incomplete('local owning record exceeds its independently bounded span');return
        active=active|{identity}
        for fi,field in enumerate(owner.fields):
            charge()
            if field.name_hash==0x100:continue
            if field.type_word&0xffff==0x5c:
                di=field.type_word>>16
                if di>=len(owner.fields):
                    incomplete('type5c descriptor index is unavailable');continue
                descriptor=owner.fields[di]
                if descriptor.type_word==5:
                    collect_header(owner,field,fi,at+field.data_offset,context,lineage)
                else:
                    # Other locally bounded type5c headers must not disappear:
                    # a differently described use of the same typed target
                    # would leave its whole-target authorization ambiguous.
                    charge(1+len(owner.fields))
                    if (field.auxiliary or descriptor.name_hash!=0x100 or descriptor.data_offset!=0
                            or descriptor.type_word!=0x1b4d or descriptor.auxiliary
                            or field.data_offset<0 or field.data_offset+16>owner.byte_size
                            or not psin_references.field_slot_clear(owner,field,16)):
                        incomplete('another type5c field lacks a validated opaque descriptor and clear complete header');continue
                    if len(headers)+len(other_headers)>=MAX_HEADERS:
                        raise ValueError('type5c spans exceed the 4096-header report limit')
                    a,b,word=struct.unpack_from('<IIQ',data,at+field.data_offset)
                    number=word&0xfffff
                    if (a!=b or (word==0 and (a or b))or
                            (word!=0 and (not a or not 1<=number<=len(blocks)))):
                        incomplete('another opaque type5c header has unequal, invalid or unvalidated nonempty words')
                    elif word:
                        target=blocks[number-1];offset=word>>20
                        if (target.type_hash!=0x4d or structures.get(0x4d)or
                                target.byte_length%4 or offset%4 or offset>target.byte_length
                                or a>(target.byte_length-offset)//4):
                            incomplete('another opaque type5c header is outside its already validated local pool span')
                    other_headers.append(dict(data_offset=at+field.data_offset,
                        descriptor_type_word=f'0x{descriptor.type_word:08x}',
                        target_block_index=number-1 if word and 1<=number<=len(blocks)else None,
                        first_word=a,second_word=b,reference_bits=f'0x{word:016x}'))
            elif field.type_word==5:
                definitions=structures.get(field.auxiliary,[])
                if (len(definitions)!=1 or definitions[0].byte_size<=0 or field.data_offset<0
                        or field.data_offset+definitions[0].byte_size>owner.byte_size or
                        not psin_references.field_slot_clear(owner,field,definitions[0].byte_size)):
                    incomplete('embedded owner is missing, ambiguous or outside a clear local slot');continue
                child_context=dict(context,embedded_parent_hash=f'0x{owner.name_hash:08x}',
                                   embedded_field_index=fi)
                charge(1+len(lineage['ancestry']))
                child_lineage=dict(root_record=lineage['root_record'],
                    ancestry=lineage['ancestry']+[dict(kind='embedded_structure',
                        owner=owner_identity(owner,at),field=field_identity(owner,field,fi,at),
                        child=owner_identity(definitions[0],at+field.data_offset))],
                    field_path=None if lineage['field_path']is None else lineage['field_path']+[fi])
                visit(definitions[0],at+field.data_offset,at+owner.byte_size,child_context,
                      child_lineage,depth+1,active)
            elif field.type_word==0x75:
                charge(1+len(owner.fields))
                mapping=psin_bucket_maps._entries(data,at+field.data_offset,field,owner,
                    at+owner.byte_size,blocks,structures,charge)
                if mapping['status']!='complete':
                    incomplete('unresolved local bucket may hide structured-descriptor owners');continue
                if mapping.get('mode')=='embedded_structure_spans':
                    for entry in mapping['entries']:
                        charge();span=entry['value_span'];definitions=structures.get(int(span['structure_hash'],16),[])
                        if len(definitions)!=1:
                            incomplete('inline bucket value has no unique local owning declaration');continue
                        child_context=dict(context,bucket_field_index=fi,bucket_index=entry['bucket_index'],
                                           slot_index=entry['slot_index'],value_data_offset=span['data_offset'])
                        charge(1+len(lineage['ancestry']))
                        child_lineage=dict(root_record=lineage['root_record'],field_path=None,
                            ancestry=lineage['ancestry']+[dict(kind='inline_bucket_value',
                                owner=owner_identity(owner,at),field=field_identity(owner,field,fi,at),
                                bucket_field_path=None if lineage['field_path']is None else lineage['field_path']+[fi],
                                bucket_header={key:mapping[key]for key in ('header_data_offset','header_byte_length',
                                    'header_bits','bucket_count','count','reference_bits','key_descriptor_index','value_descriptor_index')},
                                bucket_allocation=dict(mapping['target']),
                                bucket_index=entry['bucket_index'],slot_index=entry['slot_index'],
                                entry_index=entry['index'],entry_data_offset=entry['entry_data_offset'],
                                entry_byte_length=entry['entry_byte_length'],
                                entry_structure_hash=entry['entry_structure_hash'],
                                entry_declaration_section_offset=structures[int(entry['entry_structure_hash'],16)][0].section_offset,
                                value_span=dict(span),child=owner_identity(definitions[0],span['data_offset']))])
                        visit(definitions[0],span['data_offset'],span['data_offset']+span['byte_length'],
                              child_context,child_lineage,depth+1,active)
    for block in blocks:
        charge();definitions=structures.get(block.type_hash,[])
        if not definitions:continue
        if len(definitions)!=1 or definitions[0].byte_size<=0 or block.byte_length%definitions[0].byte_size:
            incomplete('local block owner is ambiguous, nonpositive or does not tile its block');continue
        owner=definitions[0]
        for ri in range(block.byte_length//owner.byte_size):
            root=dict(block_index=block.index,record_index=ri,structure_hash=f'0x{owner.name_hash:08x}',
                data_offset=block.data_offset+ri*owner.byte_size,byte_length=owner.byte_size,
                block_table_offset=block.table_offset,structure_declaration_section_offset=owner.section_offset)
            visit(owner,block.data_offset+ri*owner.byte_size,block.data_offset+(ri+1)*owner.byte_size,
                  dict(block_index=block.index,record_index=ri),
                  dict(root_record=root,ancestry=[],field_path=[]),0,frozenset())
    # Replay only existing instance paths. Inline bucket values are bounded
    # source spans, not records reachable through the current instance API.
    for offset in range(0,len(headers),32):
        batch=headers[offset:offset+32];queries=[];pending=[]
        for header in batch:
            origin=header['source_lineage'];path=origin['field_path'];root=origin['root_record']
            expected_field=origin['field'];expected_owner=origin['owner'];inline=path is None
            if path is None:
                origin.update(instance_replay_status='unsupported_inline_bucket',
                    reason='inline bucket value has no supported instance-addressable field path')
                transition=next(t for t in origin['ancestry']if t['kind']=='inline_bucket_value')
                path=transition['bucket_field_path'];expected_field=transition['field'];expected_owner=transition['owner']
            if len(path)>64:
                origin.update(instance_replay_status='unresolved',reason='field path exceeds the instance API limit')
            else:
                queries.append((root['block_index'],root['record_index'],path))
                pending.append((origin,expected_field,expected_owner,inline))
        proofs=execute(queries)['queries']
        for (origin,expected,owner,inline),proof in zip(pending,proofs):
            if proof['status']!='resolved':
                if inline:origin['root_instance_replay_status']='unresolved'
                else:origin.update(instance_replay_status='unresolved',reason=proof['reason'])
                continue
            field=proof['field']
            if (any(field.get(k)!=expected[k]for k in ('field_index','hash','data_offset','type_word','auxiliary','declaration_section_offset'))
                    or field['source_slot']['data_offset']!=expected['header_data_offset']
                    or field['owner_hash']!=owner['structure_hash']or field['owner_data_offset']!=owner['data_offset']
                    or field['owner_byte_length']!=owner['byte_length']):
                raise ValueError('type5c source lineage differs from its replayed field path')
            if inline:origin['root_instance_replay_status']='resolved_to_first_bucket_header'
            else:origin.update(instance_replay_status='resolved',instance_addressable=True)
    targets=[];link_count=complete_fields=0
    for bi,fields in sorted(groups.items()):
        charge(1+len(fields));block=blocks[bi]
        stride=fields[0]['declared_record_stride']
        intervals=sorted({(row['target']['byte_offset'],row['target']['byte_length'])for row in fields})
        target=dict(block_index=bi,structure_hash=f'0x{block.type_hash:08x}',data_offset=block.data_offset,
            byte_length=block.byte_length,declared_record_stride=stride,header_count=len(fields),
            distinct_spans=len(intervals),exact_aliases=len(fields)-len(intervals),status='unresolved')
        targets.append(target);reason=None;cursor=0
        competing=[h for h in other_headers if h['target_block_index']==bi]
        charge(len(other_headers))
        if competing:target['competing_header_offsets']=[h['data_offset']for h in competing]
        if not scan_complete:reason='eligible structured-header scan is incomplete or ambiguous'
        elif competing:
            reason='differently described type5c headers also select this typed target'
            target['competing_header_offsets']=[h['data_offset']for h in competing]
        else:
            for offset,length in intervals:
                charge()
                if offset!=cursor:
                    reason='structured spans have a gap or partial overlap';break
                cursor=offset+length
            if reason is None and cursor!=block.byte_length:
                reason='structured spans do not cover the whole declared typed target'
        if reason is not None:
            target['reason']=reason
            for row in fields:row['reason']=reason
            continue
        row=instances['blocks'][bi];count=block.byte_length//stride
        if row.get('record_count')!=count or not isinstance(row.get('records'),list)or len(row['records'])!=count:
            raise ValueError('type5c target instance record stride differs from source')
        requested=sum(f['first_word']for f in fields)
        if requested>MAX_LINKS-link_count:raise ValueError('type5c spans exceed the 4096-record-link report limit')
        charge(requested)
        for field in fields:
            begin=field['target']['byte_offset']//stride;links=[]
            for ri in range(begin,begin+field['first_word']):
                at=block.data_offset+ri*stride;record=row['records'][ri]
                expected=dict(structure_hash=f'0x{block.type_hash:08x}',data_offset=at,byte_length=stride)
                if not isinstance(record,dict)or any(record.get(k)!=v for k,v in expected.items()):
                    raise ValueError('type5c target instance record identity differs from source')
                links.append(dict(block_index=bi,record_index=ri,**expected))
            field.update(status='complete',profile=PROFILE,record_links=links,
                target_coverage='all distinct eligible spans exhaust the complete local typed block')
            link_count+=len(links);complete_fields+=1
        target.update(status='complete',record_count=count,coverage_bytes=cursor)
    for row in headers:
        if row['status']!='complete'and'reason'not in row:
            row['reason']='no authorized complete typed-target coverage'
    return dict(format='gta6x-psin-type5c-record-spans-v1',profile=PROFILE,
        status='complete'if scan_complete and complete_fields==len(headers)else'partial',
        source_sha256=source['source_sha256'],schema_id=source['schema_id'],max_depth=max_depth,
        source_blocks=source_blocks,source_walk_events=source_events,
        scan_complete=scan_complete,scan_reasons=reasons,fields=headers,targets=targets,
        summary=dict(nodes=used,headers=len(headers),other_type5c_headers=len(other_headers),fields_complete=complete_fields,
            fields_unresolved=len(headers)-complete_fields,targets=len(targets),
            targets_complete=sum(t['status']=='complete'for t in targets),
            record_links=link_count,physical_owners_visited=len(visited),semantic_types_promoted=0),
        interpretation='Local declared typed-record span associations only; raw type5c, stored words, logical elements, values and semantic ownership remain unconfirmed. Existing parent fields stay unknown.')
