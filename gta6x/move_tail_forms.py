"""Bounded additional MoVE tail storage from independent byte observations.

Kind 3 has a reference table, counted length-prefixed opaque records and an
additional tail pointer. An additional kind-12 profile describes five counted
groups of opaque cells. Referenced bodies and all application meanings remain
opaque. This view follows no recursive graph and preserves prior child views.
"""
from __future__ import annotations

import hashlib
import struct

from .move import MAX_BYTES, MoveLimitError

PROFILE = 'observed_move_kind3_tail_v1'


def inspect_payload(data, offset, length, *, max_nodes=100000):
    """Inspect previously unsupported immediate candidates without recursion."""
    from . import move_children
    if type(max_nodes) is not int or max_nodes < 1:
        raise MoveLimitError('MoVE tail-form output exceeds node limit')
    if len(data) > MAX_BYTES:
        raise MoveLimitError('MoVE tail-form input exceeds size limit')
    used = 1

    def consume(n=1):
        nonlocal used
        if n > max_nodes-used:
            raise MoveLimitError('MoVE tail-form output exceeds node limit')
        used += n

    previous = move_children.inspect_payload(data, offset, length, max_nodes=100000)
    forms = []
    for child in previous['children']:
        if child['status'] != 'unresolved':
            continue
        consume()
        at, size = child['data_offset'], child['byte_length']
        item = dict(data_offset=at, byte_length=size, source=child['source'],
                    parent_reference_data_offset=child['parent_reference_data_offset'],
                    status='unresolved', references=[], records=[], regions=[], opaque_regions=[])
        try:
            # The previous layer checks parent ordinal/hash before reporting this
            # exact unsupported-kind reason. Malformed parent checks stay refused.
            if child['reason'] == 'unsupported MoVE child kind 3; body remains opaque':
                item.update(_kind3(data, at, size, consume))
            elif child['reason'] == 'unsupported MoVE child kind 12; body remains opaque':
                from . import move_more_forms
                item.update(move_more_forms.inspect_kind12(data, at, size, consume))
            elif child['reason'] == 'unsupported MoVE child kind 11; body remains opaque':
                from . import move_extra_forms
                item.update(move_extra_forms.inspect_kind11(data, at, size, consume))
            elif child['reason'] == 'unsupported MoVE child kind 28; body remains opaque':
                from . import move_selector_forms
                item.update(move_selector_forms.inspect_kind28(data, at, size, consume))
            else:
                raise ValueError(child['reason'])
        except MoveLimitError:
            raise
        except ValueError as exc:
            item['reason'] = str(exc)
        forms.append(item)
    resolved = sum(f['status']=='complete' for f in forms)
    result = dict(profile=PROFILE, status=('complete' if resolved==len(forms) and previous['status']!='unresolved'
                                        else 'partial' if forms else 'unresolved'),
        interpretation='One bounded storage level only; referenced bodies and motion semantics remain opaque.',
        forms=forms, summary=dict(nodes=used, candidates=len(forms), resolved=resolved,
            unresolved=len(forms)-resolved, references=sum(len(f['references']) for f in forms),
            opaque_records=sum(len(f['records']) for f in forms)))
    counted = [f for f in forms if f.get('form') == 'kind12_five_counted_opaque_groups']
    if counted:
        for key in ('counted_groups', 'selector_words', 'opaque_cells'):
            result['summary'][key] = sum(f['summary'][key] for f in counted)
    headers = [f for f in forms if f.get('form') in ('kind11_measured_selector_header',
                                                        'kind28_measured_selector_header')]
    if headers:
        for key in ('header_prefixes', 'header_selector_fields', 'header_prefix_bytes'):
            result['summary'][key] = sum(f['summary'][key] for f in headers)
    return result


def _kind3(data, at, size, consume):
    stop = at+size

    def span(pos, n, end=stop):
        if type(pos) is not int or n < 0 or pos < at or pos > end-n:
            raise ValueError('MoVE kind-3 storage exceeds its bounded candidate')

    def opaque(pos, n):
        span(pos,n)
        return dict(data_offset=pos, byte_length=n,
                    sha256=hashlib.sha256(data[pos:pos+n]).hexdigest(), interpretation='opaque')

    def region(name, begin, end):
        return dict(name=name,data_offset=begin,byte_length=end-begin)

    span(at,96)
    count, extra = data[at+18:at+20]
    selected_rel = struct.unpack_from('<I',data,at+8)[0]
    total, tail_count, tail_rel = struct.unpack_from('<III',data,at+84)
    if not count or extra or struct.unpack_from('<I',data,at+36)[0] or total != 12+8*count or tail_count != 1:
        raise ValueError('unsupported MoVE kind-3 header/count profile')
    table_end = at+84+total
    span(at+84,total)
    tail = at+92+tail_rel
    span(tail,8)
    rows=[]
    for i in range(count):
        pos=at+96+8*i
        hashed,relative=struct.unpack_from('<II',data,pos)
        target=pos+4+relative
        span(target,8,tail)
        if target < table_end or (rows and target < rows[-1][2]+8):
            raise ValueError('MoVE kind-3 reference order or storage overlap differs')
        kind,order,name=struct.unpack_from('<HHI',data,target)
        if order != i or name != hashed:
            raise ValueError('MoVE kind-3 reference hash or ordinal differs')
        rows.append((pos,relative,target,kind,hashed))
    selected = at+8+selected_rel
    if selected not in [r[2] for r in rows]:
        raise ValueError('MoVE kind-3 selected pointer is not a listed target')
    record_count=struct.unpack_from('<I',data,at+80)[0]
    record_end=rows[0][2]
    if record_count > (record_end-table_end)//8:
        raise ValueError('MoVE kind-3 opaque-record count exceeds available bytes')
    records=[];pos=table_end
    for i in range(record_count):
        span(pos,8,record_end)
        n,raw=struct.unpack_from('<HH',data,pos)
        if n<8 or n%4:
            raise ValueError('unsupported MoVE kind-3 opaque-record length')
        span(pos,n,record_end);consume(2)
        records.append(dict(index=i,data_offset=pos,byte_length=n,
            length_field_data_offset=pos,raw_header_u16=raw,body=opaque(pos+4,n-4)))
        pos+=n
    if pos != record_end:
        raise ValueError('MoVE kind-3 record lengths/count disagree with first target')
    consume(10+4*count)
    references=[];opaques=[]
    for i,(pos,relative,target,kind,hashed) in enumerate(rows):
        end=rows[i+1][2] if i+1<count else tail
        references.append(dict(index=i,data_offset=pos,offset_field_data_offset=pos+4,
            relative_bits=f'0x{relative:08x}',hash_bits=f'0x{hashed:08x}',
            target_data_offset=target,target_byte_length=end-target,
            target_header=dict(raw_kind_u16=kind,raw_ordinal_u16=i,name_hash_bits=f'0x{hashed:08x}')))
        opaques.append(opaque(target+8,end-target-8))
    opaques.append(opaque(tail,stop-tail))
    regions=[region('header',at,at+84),region('reference_table',at+84,table_end)]
    regions += [region('opaque_record',r['data_offset'],r['data_offset']+r['byte_length']) for r in records]
    regions += [region('referenced_storage',r['target_data_offset'],r['target_data_offset']+r['target_byte_length']) for r in references]
    regions.append(region('opaque_tail',tail,stop))
    return dict(status='complete',form='kind3_relative_references_and_tail',
        header=dict(raw_kind_u16=3,raw_ordinal_u16=struct.unpack_from('<H',data,at+2)[0],
            name_hash_bits=f'0x{struct.unpack_from("<I",data,at+4)[0]:08x}',row_bound_u8=count,
            opaque_record_count=record_count),
        reference_table=dict(data_offset=at+84,byte_length=total,records_data_offset=at+96,count=count),
        selected_reference=dict(offset_field_data_offset=at+8,relative_bits=f'0x{selected_rel:08x}',target_data_offset=selected),
        additional_tail=dict(count_field_data_offset=at+88,count=tail_count,
            offset_field_data_offset=at+92,relative_bits=f'0x{tail_rel:08x}',data_offset=tail,byte_length=stop-tail),
        references=references,records=records,regions=regions,opaque_regions=opaques)
