"""Checked typed-span candidate associations between existing PSIN rows.

Inputs are fresh same-source native reports, never authenticated saved JSON.
The unknown parent field, logical element and semantic owner stay unknown.
"""
from __future__ import annotations

import struct

from . import psin_type5c

PROFILE = 'existing_checked_type5c_record_spans_v1'
MAX_ITEMS = 4096


def _require(condition, reason):
    if not condition:
        raise ValueError('type5c graph ' + reason)


def _uint(value, maximum=16*1024*1024):
    _require(type(value) is int and 0 <= value <= maximum, 'has invalid integer')
    return value


def _bits(value, length):
    _require(isinstance(value, str) and value.startswith('0x') and len(value)==2+2*length
        and all(c in '0123456789abcdefABCDEF' for c in value[2:]),
             'has invalid raw bits')
    try:
        return int(value, 16).to_bytes(length, 'little')
    except (ValueError, OverflowError) as exc:
        raise ValueError('type5c graph has invalid raw bits') from exc


def append(report, instances, nodes, sources, identities, blocks, edges, *, consume, edge):
    """Recheck complete span witnesses and append only instance-addressable edges."""
    consume()
    _require(isinstance(report, dict) and report.get('format')=='gta6x-psin-type5c-record-spans-v1'
        and report.get('profile')==psin_type5c.PROFILE and report.get('status') in ('complete','partial')
        and report.get('schema_id')==instances.get('schema_id'), 'requires same-schema typed-span evidence')
    digest=report.get('source_sha256')
    _require(isinstance(digest,str), 'has invalid source digest')
    _bits('0x'+digest,32)
    keys=('index','table_offset','type_hash','data_offset','byte_length','sha256')
    expected=[{k:b.get(k) for k in keys} for b in blocks]
    _require(report.get('source_blocks')==expected, 'source block identities differ from instances')
    fields=report.get('fields');targets=report.get('targets');summary=report.get('summary')
    _require(isinstance(fields,list) and len(fields)<=MAX_ITEMS and isinstance(targets,list)
        and len(targets)<=MAX_ITEMS and isinstance(summary,dict), 'has invalid bounded lists')
    counts=dict(type5c_headers_supported=0,type5c_headers_unresolved=0,
        type5c_record_edges=0,type5c_inline_headers_excluded=0,type5c_inline_links_excluded=0,
        type5c_scan_partial=int(report.get('scan_complete') is not True))
    groups={}; total_links=0; complete=0; physical=set()
    for fi,item in enumerate(fields):
        consume()
        _require(isinstance(item,dict) and type(item.get('index')) is int and item['index']==fi
            and item.get('status') in ('complete','unresolved'), 'has invalid header index/status')
        links=item.get('record_links')
        _require(isinstance(links,list) and len(links)<=MAX_ITEMS, 'has invalid link list')
        if item['status']!='complete':
            _require(not links, 'unresolved header contains link prefix')
            counts['type5c_headers_unresolved']+=1;continue
        complete+=1;total_links+=len(links)
        _require(total_links<=MAX_ITEMS and report.get('scan_complete') is True
            and item.get('profile')==psin_type5c.PROFILE, 'requires complete eligible-header scan')
        _require(all(item.get(k)=='unknown' for k in
            ('parent_type_meaning','logical_element_meaning','semantic_owner')), 'changes unknown semantics')
        start=_uint(item.get('header_data_offset'))
        _require(start not in physical, 'duplicates a physical header');physical.add(start)
        raw=_bits(item.get('header_bits'),16);a,b,word=struct.unpack('<IIQ',raw)
        stride=_uint(item.get('declared_record_stride'))
        _require(type(item.get('first_word')) is int and type(item.get('second_word')) is int
            and a>0 and a==b and word>0 and stride>0 and a==item.get('first_word')
            and b==item.get('second_word') and raw[8:]==_bits(item.get('reference_bits'),8)
            and item.get('header_byte_length')==16 and a==len(links), 'header/count/reference differs')
        number,offset=word&0xfffff,word>>20
        _require(1<=number<=len(blocks), 'reference selects no block')
        block=blocks[number-1];target=item.get('target')
        _require(isinstance(target,dict) and target==dict(block_index=number-1,
            structure_hash=block['type_hash'],byte_offset=offset,
            data_offset=block['data_offset']+offset,byte_length=a*stride)
            and item.get('descriptor_structure_hash')==block['type_hash']
            and offset%stride==0 and block['byte_length']%stride==0
            and offset+a*stride<=block['byte_length'], 'target span differs from block/reference')
        groups.setdefault(number-1,[]).append(item)
        for ordinal,link in enumerate(links):
            consume()
            ri=offset//stride+ordinal;ni=identities.get((number-1,ri))
            _require(ni is not None and isinstance(link,dict), 'selects no existing target row')
            for key in ('block_index','record_index','data_offset','byte_length'):
                _uint(link.get(key))
            expected_link=dict(block_index=number-1,record_index=ri,structure_hash=block['type_hash'],
                data_offset=block['data_offset']+offset+ordinal*stride,byte_length=stride)
            _require(link==expected_link and all(nodes[ni][k]==v for k,v in expected_link.items()),
                'link differs from existing target identity')
    _require(type(report.get('scan_complete')) is bool
        and report.get('status')==('complete' if report['scan_complete'] and complete==len(fields) else 'partial'),
        'status differs from complete scan/headers')
    _require(summary.get('headers')==len(fields) and summary.get('fields_complete')==complete
        and summary.get('fields_unresolved')==len(fields)-complete and summary.get('record_links')==total_links,
        'summary differs from header/link counts')
    _require(all(type(summary.get(k)) is int for k in ('headers','fields_complete','fields_unresolved','record_links')),
        'summary contains noninteger counts')
    target_rows={}
    for row in targets:
        consume()
        _require(isinstance(row,dict) and type(row.get('block_index')) is int
            and row['block_index'] not in target_rows and row.get('status') in ('complete','unresolved'),
            'has invalid target coverage list')
        target_rows[row['block_index']]=row
    _require(summary.get('targets')==len(targets)
        and summary.get('targets_complete')==sum(r['status']=='complete'for r in targets),
        'target summary differs from coverage')
    for bi,items in groups.items():
        block=blocks[bi];row=target_rows.get(bi);stride=items[0]['declared_record_stride']
        spans=sorted({(f['target']['byte_offset'],f['target']['byte_length']) for f in items});cursor=0
        for offset,length in spans:
            consume();_require(offset==cursor, 'coverage has gap or partial overlap');cursor+=length
        _require(isinstance(row,dict) and row.get('status')=='complete' and cursor==block['byte_length']
            and all(f['declared_record_stride']==stride for f in items)
            and all(row.get(k)==v for k,v in dict(block_index=bi,structure_hash=block['type_hash'],
                data_offset=block['data_offset'],byte_length=block['byte_length'],declared_record_stride=stride,
                header_count=len(items),distinct_spans=len(spans),exact_aliases=len(items)-len(spans),
                record_count=block['byte_length']//stride,coverage_bytes=cursor).items()),
            'coverage witness differs from complete typed target')
    _require({bi for bi,r in target_rows.items() if r['status']=='complete'}==set(groups),
        'has unmatched complete target coverage')
    for item in fields:
        if item['status']!='complete':continue
        lineage=item.get('source_lineage')
        _require(isinstance(lineage,dict), 'requires checked source lineage')
        if lineage.get('instance_replay_status')=='unsupported_inline_bucket':
            _require(lineage.get('instance_addressable') is False and lineage.get('field_path') is None,
                'inline source declares an instance path')
            counts['type5c_inline_headers_excluded']+=1
            counts['type5c_inline_links_excluded']+=len(item['record_links']);continue
        _require(lineage.get('instance_addressable') is True and lineage.get('instance_replay_status')=='resolved',
            'source lineage is not instance-addressable')
        root=lineage.get('root_record');path=lineage.get('field_path')
        _require(isinstance(root,dict) and isinstance(path,list) and 1<=len(path)<=64,
            'has invalid source path')
        source=identities.get((_uint(root.get('block_index')),_uint(root.get('record_index'))))
        _require(source is not None and all(root.get(k)==nodes[source][k] for k in
            ('block_index','record_index','structure_hash','data_offset','byte_length')),
            'root differs from existing typed row')
        _require(root.get('block_table_offset')==blocks[root['block_index']]['table_offset'],
            'root block table differs')
        ancestry=lineage.get('ancestry')
        _require(isinstance(ancestry,list) and len(ancestry)==len(path)-1, 'ancestry differs from field path')
        _require(item.get('source_context',{}).get('block_index')==root['block_index']
            and item.get('source_context',{}).get('record_index')==root['record_index'], 'source context differs from root')
        owner=sources[source]
        for depth,index in enumerate(path):
            consume();index=_uint(index)
            _require(index<len(owner['fields']), 'path selects no field')
            field=owner['fields'][index];start=owner['data_offset']+field['data_offset']
            if depth+1<len(path):
                child=field.get('value')
                _require(field.get('type_word')=='0x00000005' and field.get('type_name')=='embedded_structure'
                    and isinstance(child,dict) and child.get('data_offset')==start
                    and child.get('status') in ('complete','partial') and field.get('status')==child['status']
                    and type(child.get('byte_length')) is int and child['byte_length']>0
                    and start+child['byte_length']<=owner['data_offset']+owner['byte_length'],
                    'embedded path differs from existing child')
                transition=ancestry[depth]
                _require(isinstance(transition,dict) and transition.get('kind')=='embedded_structure'
                    and isinstance(transition.get('owner'),dict) and isinstance(transition.get('child'),dict)
                    and isinstance(transition.get('field'),dict)
                    and all(transition['owner'].get(k)==owner[k] for k in ('structure_hash','data_offset','byte_length'))
                    and all(transition['child'].get(k)==child[k] for k in ('structure_hash','data_offset','byte_length'))
                    and all(transition['field'].get(k)==v for k,v in dict(field_index=index,hash=field['hash'],
                        data_offset=field['data_offset'],type_word=field['type_word'],
                        auxiliary=child['structure_hash'],header_data_offset=start).items()),
                    'ancestry differs from existing embedded owner/field/child')
                if depth==0:
                    _require(transition['owner'].get('declaration_section_offset')==root.get('structure_declaration_section_offset'), 'root declaration differs from ancestry')
                if depth+1<len(ancestry):
                    _require(transition['child']==ancestry[depth+1].get('owner'), 'ordered ancestry declarations differ')
                owner=child
        proof=lineage.get('field');owner_proof=lineage.get('owner')
        _require(isinstance(proof,dict) and isinstance(owner_proof,dict)
            and all(owner_proof.get(k)==owner[k] for k in ('structure_hash','data_offset','byte_length'))
            and item.get('owner_hash')==owner['structure_hash'] and item.get('owner_byte_length')==owner['byte_length']
            and item.get('field_auxiliary')=='0x00000000'
            and owner_proof.get('declaration_section_offset') is not None
            and item.get('field_index')==path[-1] and field.get('hash')==item.get('field_hash')
            and field.get('type_word')==item.get('field_type_word')
            and field.get('status')=='unresolved' and int(field['type_word'],16)&0xffff==0x5c
            and start==item['header_data_offset'] and field['data_offset']+16<=owner['byte_length']
            and all(proof.get(k)==v for k,v in dict(field_index=path[-1],hash=field['hash'],
                data_offset=field['data_offset'],type_word=field['type_word'],auxiliary=item['field_auxiliary'],
                declaration_section_offset=item['declaration_section_offset'],
                header_data_offset=start,header_byte_length=16).items()), 'source field differs from existing unknown field')
        _require((not ancestry and owner_proof.get('declaration_section_offset')==root.get('structure_declaration_section_offset'))
            or (ancestry and owner_proof==ancestry[-1]['child']), 'owner declaration differs from ancestry')
        descriptor_index=_uint(item.get('descriptor_index'))
        _require(descriptor_index==int(field['type_word'],16)>>16 and descriptor_index<len(owner['fields'])
            and owner['fields'][descriptor_index].get('hash')=='0x00000100'
            and owner['fields'][descriptor_index].get('type_word')=='0x00000005'
            and owner['fields'][descriptor_index].get('status')=='descriptor'
            and owner['fields'][descriptor_index].get('data_offset')==0, 'local synthetic descriptor differs')
        for ordinal,link in enumerate(item['record_links']):
            edge(source,dict(link,status='record_reference'),'type5c_record_span',tuple(path),ordinal)
            edges[-1].update(type5c_field_index=item['index'],header_data_offset=start,
                association_scope='candidate declared typed-record span; parent type, logical elements and semantic owner unknown')
            counts['type5c_record_edges']+=1
        counts['type5c_headers_supported']+=1
    return counts
