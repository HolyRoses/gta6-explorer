"""One additional level of observed MoVE storage prefixes.

The low/high bytes at +18/+19 bound reference/descriptor rows and extension
records in the supported forms. Extension bodies, referenced grandchildren
and other tail kinds remain opaque. No recursive motion graph is inferred.
"""
from __future__ import annotations

import hashlib
import struct

from . import move_objects
from .move import MAX_BYTES, MoveLimitError

PROFILE = 'observed_move_child_prefixes_v1'


def inspect_payload(data, offset, length, *, max_nodes=100000):
    """Inspect bounded immediate child candidates, preserving unknown siblings.

    A candidate's malformed/unsupported prefix returns no partial child rows.
    Independently bounded siblings remain available. Budget exhaustion refuses
    the entire new view. Only one extra level is followed; child bodies and
    descriptor tails are not recursively traversed.
    """
    if type(max_nodes) is not int or max_nodes < 1:
        raise MoveLimitError('MoVE child output exceeds node limit')
    used = 0

    def consume(count=1):
        nonlocal used
        if count > max_nodes - used:
            raise MoveLimitError('MoVE child output exceeds node limit')
        used += count

    consume()
    result = dict(status='unresolved', interpretation='candidate', candidate_profile=PROFILE,
                  children=[], summary=dict(nodes=1, candidates=0, resolved=0, unresolved=0))
    parent = move_objects.inspect_payload(data, offset, length, max_nodes=max(100000, max_nodes))
    if parent['status'] != 'complete':
        result['reason'] = 'child inspection requires supported root storage: ' + parent['reason']
        return result
    candidates = [(r['target_data_offset'], r['target_byte_length'], r['index'], r['hash_bits'],
                   'reference', r['data_offset']) for r in parent['references']]
    if parent['form'] == 'length_prefixed_descriptors':
        tail = parent['opaque_regions'][0]
        candidates.append((tail['data_offset'], tail['byte_length'], 0, None, 'descriptor_tail', None))

    def inspect_candidate(at, size, ordinal, expected_hash):
        consume()
        empty = dict(status='unresolved', interpretation='candidate', references=[],
                     descriptors=[], extensions=[], regions=[])
        stop = at + size

        def span(pos, count, end=stop):
            if count < 0 or pos < at or pos > end - count:
                raise ValueError('MoVE child prefix exceeds its bounded span')

        def bits(pos, count):
            return '0x' + data[pos:pos+count][::-1].hex()

        def opaque(pos, count):
            span(pos, count)
            return dict(data_offset=pos, byte_length=count,
                        sha256=hashlib.sha256(data[pos:pos+count]).hexdigest(),
                        interpretation='opaque; numeric, object and motion meanings unknown')

        def region(name, start, end):
            return dict(name=name, data_offset=start, byte_length=end-start)

        def extensions(start, count, end):
            records, pos = [], start
            for i in range(count):
                span(pos, 20, end)
                n = struct.unpack_from('<I', data, pos+16)[0]
                if n < 20 or n % 4:
                    raise ValueError('unsupported MoVE extension-record length')
                span(pos, n, end)
                consume(2)
                records.append(dict(index=i, data_offset=pos, byte_length=n,
                    header_bits=bits(pos,20), length_field_data_offset=pos+16,
                    body=opaque(pos+20,n-20)))
                pos += n
            if pos != end:
                raise ValueError('MoVE extension lengths disagree with independent table extent')
            return records

        try:
            if (type(at) is not int or type(size) is not int or at < 0 or size < 20
                    or size > MAX_BYTES or at > len(data)-size):
                raise ValueError('unsupported MoVE child bounds')
            kind, actual_ordinal, name = struct.unpack_from('<HHI',data,at)
            if actual_ordinal != ordinal or (expected_hash is not None and name != int(expected_hash,16)):
                raise ValueError('MoVE child header differs from its parent reference')
            if kind not in (1,22):
                raise ValueError(f'unsupported MoVE child kind {kind}; body remains opaque')
            bound, extra = data[at+18:at+20]
            if not bound:
                raise ValueError('unsupported zero MoVE child row bound')
            header = dict(raw_kind_u16=kind, raw_ordinal_u16=actual_ordinal,
                          name_hash_bits=f'0x{name:08x}', row_bound_u8=bound,
                          extension_count_u8=extra)
            if kind == 1:
                span(at,88)
                total = struct.unpack_from('<I',data,at+84)[0]
                basic_end = at+88+8*bound
                table_end = at+84+total
                raw_relative = struct.unpack_from('<I',data,at+36)[0]
                if total < 4+8*bound or not (raw_relative == basic_end-at-36 or (raw_relative == 0 and extra == 0)):
                    raise ValueError('MoVE child reference count or redundant extension start differs')
                span(at+84,total)
                ext = extensions(basic_end,extra,table_end)
                refs=[]
                for i in range(bound):
                    pos=at+88+8*i
                    hashed,relative=struct.unpack_from('<II',data,pos)
                    target=pos+4+relative
                    span(target,8)
                    if target < table_end or (refs and target < refs[-1][2]+8):
                        raise ValueError('MoVE child targets overlap storage or differ from source order')
                    code,order,stored=struct.unpack_from('<HHI',data,target)
                    if order != i or stored != hashed:
                        raise ValueError('MoVE grandchild header hash or ordinal differs')
                    refs.append((pos,relative,target,code,stored))
                consume(8+4*bound)
                records=[]
                spans=[region('header',at,at+84),region('reference_table',at+84,basic_end),
                       region('extensions',basic_end,table_end),region('opaque_gap',table_end,refs[0][2])]
                bodies=[opaque(table_end,refs[0][2]-table_end)]
                for i,(pos,relative,target,code,hashed) in enumerate(refs):
                    end=refs[i+1][2] if i+1<len(refs) else stop
                    records.append(dict(index=i,data_offset=pos,byte_length=8,
                        offset_field_data_offset=pos+4,relative_offset_bits=f'0x{relative:08x}',
                        hash_bits=f'0x{hashed:08x}',target_data_offset=target,target_byte_length=end-target,
                        child_header=dict(raw_kind_u16=code,raw_ordinal_u16=i,
                                          name_hash_bits=f'0x{hashed:08x}',value_bits=bits(target,8)),
                        interpretation='bounded immediate span; body not followed recursively'))
                    bodies.append(opaque(target+8,end-target-8))
                    spans.append(region(f'opaque_target_{i}',target,end))
                header.update(header_bits=bits(at,84),raw_relative_word_24=f'0x{raw_relative:08x}')
                view=dict(form='child_relative_references',header=header,references=records,
                    descriptors=[],extensions=ext,
                    reference_table=dict(data_offset=at+84,records_data_offset=at+88,
                        byte_length=basic_end-at-84,total_storage_byte_length=total,count=bound),
                    extension_table=dict(data_offset=basic_end,byte_length=table_end-basic_end,count=extra),
                    opaque_regions=bodies,regions=spans)
                counts=dict(references=bound,descriptor_records=0,fixed_cells=0,nested_blocks=0)
            else:
                span(at,48)
                if struct.unpack_from('<II',data,at+32)!=(0,12):
                    raise ValueError('unsupported MoVE child descriptor header')
                relative,count=struct.unpack_from('<II',data,at+40)
                start=at+40+relative
                if start<at+48 or count>bound:
                    raise ValueError('MoVE child descriptor count or extension extent differs')
                span(at+48,start-at-48)
                ext=extensions(at+48,extra,start)
                consume(8)
                descriptors=[];pos=start;previous=-1;cells=0;subcount=0
                for i in range(count):
                    span(pos,12)
                    n,index,a,b,c,d,e,reserved=struct.unpack_from('<IH6B',data,pos)
                    if n<12 or n%4 or reserved or not previous<index<bound:
                        raise ValueError('unsupported MoVE child descriptor size, index or counts')
                    span(pos,n);previous=index;end=pos+n;cursor=pos+12
                    fixed=16*(a+b+c)+8*d;span(cursor,fixed,end)
                    consume(5+a+b+c+d+2*e)
                    groups=[]
                    for group,(number,stride) in enumerate(zip((a,b,c,d),(16,16,16,8))):
                        groups.append(dict(group_index=group,count=number,record_stride=stride,
                            data_offset=cursor,byte_length=number*stride,
                            cells=[dict(index=j,data_offset=cursor+j*stride,byte_length=stride,
                                        value_bits=bits(cursor+j*stride,stride)) for j in range(number)],
                            interpretation='raw cells; group and numeric meanings unknown'))
                        cursor+=number*stride
                    nested=[]
                    for j in range(e):
                        span(cursor,8,end);w=struct.unpack_from('<4H',data,cursor)
                        if w[2]<8 or w[2]%4:
                            raise ValueError('unsupported MoVE child subblock length')
                        span(cursor,w[2],end)
                        nested.append(dict(index=j,data_offset=cursor,byte_length=w[2],
                            header_bits=bits(cursor,8),body=opaque(cursor+8,w[2]-8)))
                        cursor+=w[2]
                    if cursor!=end:
                        raise ValueError('unaccounted MoVE child descriptor bytes')
                    descriptors.append(dict(index=i,data_offset=pos,byte_length=n,raw_index_u16=index,
                        header_bits=bits(pos,12),raw_count_bytes=[a,b,c,d,e,reserved],
                        fixed_groups=groups,nested_blocks=nested))
                    cells+=a+b+c+d;subcount+=e;pos=end
                span(pos,8)
                if struct.unpack_from('<H',data,pos+2)[0]!=0:
                    raise ValueError('unsupported MoVE child opaque-tail ordinal')
                header.update(header_bits=bits(at,48),raw_relative_word_28=f'0x{relative:08x}')
                view=dict(form='child_descriptor_prefix',header=header,references=[],descriptors=descriptors,
                    extensions=ext,extension_table=dict(data_offset=at+48,byte_length=start-at-48,count=extra),
                    descriptor_table=dict(count_data_offset=at+44,data_offset=start,byte_length=pos-start,count=count),
                    opaque_regions=[opaque(pos,stop-pos)],
                    regions=[region('header',at,at+48),region('extensions',at+48,start),
                             region('descriptors',start,pos),region('opaque_tail',pos,stop)])
                counts=dict(references=0,descriptor_records=count,fixed_cells=cells,nested_blocks=subcount)
            view.update(status='complete',interpretation='bounded child prefix; referenced bodies and motion semantics unknown',
                        summary=dict(extension_records=len(ext),**counts))
            return view
        except MoveLimitError:
            raise
        except (ValueError,struct.error) as exc:
            return dict(empty,reason=str(exc))

    views=[]
    for at,size,ordinal,hashed,source,reference_at in candidates:
        view=inspect_candidate(at,size,ordinal,hashed)
        view.update(source=source,parent_reference_data_offset=reference_at,data_offset=at,byte_length=size)
        views.append(view)
    complete=[v for v in views if v['status']=='complete']
    unresolved=len(views)-len(complete)
    result.update(status='partial' if unresolved else 'complete',profile=result.pop('candidate_profile'),
        interpretation='one additional bounded storage level; unknown prefixes and all deeper bodies remain opaque',children=views,
        summary=dict(nodes=used,candidates=len(views),resolved=len(complete),unresolved=unresolved,
            **{key:sum(v['summary'][key] for v in complete) for key in
               ('extension_records','references','descriptor_records','fixed_cells','nested_blocks')}))
    return result
