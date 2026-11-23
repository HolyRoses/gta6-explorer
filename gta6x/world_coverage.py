"""Sparse source-byte accounting for declared 0DRP spans, not resource bounds.

Overlaps and exact aliases are observations, not automatically invalid data.
Unclaimed zero bytes and the last known declaration never identify a complete
resource endpoint or authorize joining a neighboring compressed stream.
"""
from __future__ import annotations

from collections import defaultdict
import struct

from . import anim_resources, world_header_context

PROFILE = 'world_0drp_declared_byte_coverage_v1'


def inspect(data, extent, *, consume, consume_bytes, header_context=None):
    """Account for a fresh same-source extent inventory without byte-sized maps.

    Every consumed pointer/count/span identity is rechecked against source words;
    the caller still owns full parser validation and inventory provenance. This
    does not authenticate arbitrary saved reader JSON or unknown format fields.
    The byte callback bounds observed unclaimed scans before reading them. Both
    shared callback exceptions propagate without returning a result prefix.
    """
    if (not isinstance(data, bytes) or not 80 <= len(data) <= anim_resources.MAX_RESOURCE
            or data[16:20] != b'0DRP' or struct.unpack_from('<I', data, 20)[0] != 122
            or data[:8] != bytes(8) or data[24:32] != bytes(8)):
        raise ValueError('coverage requires a bounded version-122 0DRP prefix')
    if (not isinstance(extent, dict) or not isinstance(extent.get('spans'), list)
            or extent.get('prefix_bytes') != len(data)):
        raise ValueError('coverage requires a fresh same-source extent inventory')
    used = byte_work = 0

    def charge(n=1):
        nonlocal used
        consume(n); used += n

    def scan_bytes(n):
        nonlocal byte_work
        consume_bytes(n); byte_work += n

    charge()
    ns, ne, nb = struct.unpack_from('<3H', data, 72)
    charge(ns + ne + nb)
    expected = {}; unread = []; structures = []; blocks = []

    def reference(kind, index, position, length):
        word = struct.unpack_from('<Q', data, position)[0]
        if not length:
            if word: raise ValueError('coverage empty declaration has a nonnull reference')
            return None
        offset = word - anim_resources.VIRTUAL_BASE
        if offset < 80 or offset > anim_resources.MAX_RESOURCE - length:
            raise ValueError('coverage declaration escapes the supported extent')
        charge()
        row = dict(kind=kind, index=index, reference_data_offset=position,
            data_offset=offset, byte_length=length, end=offset+length,
            present=offset+length <= len(data))
        expected[kind, index] = row
        return offset

    for kind, at, count, stride in (('structures',40,ns,32), ('enums',48,ne,24), ('blocks',56,nb,16)):
        start = reference(kind, None, at, count*stride)
        if not count: continue
        if start + count*stride > len(data):
            unread.append(kind); continue
        for index in range(count):
            at = start + index*stride
            if kind == 'structures':
                count_fields = struct.unpack_from('<H', data, at+30)[0]
                reference('structure_fields', index, at+16, count_fields*16)
                name, size = struct.unpack_from('<I',data,at)[0], struct.unpack_from('<I',data,at+24)[0]
                structures.append(dict(hash=f'0x{name:08x}',byte_size=size))
            elif kind == 'enums':
                count_members = struct.unpack_from('<I',data,at+16)[0]
                reference('enum_members', index, at+8, count_members*16)
            else:
                name, length, word = struct.unpack_from('<IIQ',data,at)
                offset = reference('data_block', index, at+8, length)
                blocks.append(dict(index=index,type_hash=f'0x{name:08x}',
                    data_offset=offset,byte_length=length))
    if len(extent['spans']) != len(expected):
        raise ValueError('coverage inventory omits or fabricates a declaration')
    seen = set()
    for row in extent['spans']:
        charge()
        if not isinstance(row, dict) or not isinstance(row.get('kind'), str):
            raise ValueError('invalid coverage declaration inventory')
        index = row.get('index')
        if index is not None and (type(index) is not int or index < 0):
            raise ValueError('invalid coverage declaration index')
        key = row['kind'], index
        if key in seen or key not in expected:
            raise ValueError('coverage declaration identity is duplicated or unknown')
        seen.add(key)
        for word in ('reference_data_offset','data_offset','byte_length','end'):
            if type(row.get(word)) is not int or row[word] != expected[key][word]:
                raise ValueError('coverage declaration differs from source words')
        if type(row.get('present')) is not bool or row['present'] != expected[key]['present']:
            raise ValueError('coverage declaration presence differs from source bounds')
    minimum = max((row['end'] for row in expected.values()),default=80)
    complete = not unread
    if (extent.get('reference_inventory_complete') is not complete
            or extent.get('unread_row_tables') != unread
            or extent.get('minimum_declared_extent') != minimum):
        raise ValueError('coverage completeness/extent differs from source inventory')
    charge(1+len(expected))
    spans = [dict(index=0,kind='header',declaration_index=None,data_offset=0,byte_length=80,
                  end=80,present=True,basis='declared_header')]
    for row in expected.values():
        spans.append(dict(index=len(spans),kind=row['kind'],declaration_index=row['index'],
            reference_data_offset=row['reference_data_offset'],data_offset=row['data_offset'],
            byte_length=row['byte_length'],end=row['end'],present=row['present'],basis='declared_span'))
    candidate_context = None
    if header_context is not None:
        # This option is research categorization only. Recompute from the same
        # readable table words instead of accepting arbitrary caller ranges.
        if not isinstance(header_context,dict) or unread:
            raise ValueError('candidate context requires readable same-source row tables')
        scan_bytes(16)  # Maximum zero-slot examination in the supported profile.
        checked = world_header_context.inspect(data,structures,blocks,consume=charge)
        if checked['status'] != 'candidate' or any(header_context.get(key) != checked.get(key)
                for key in ('status','profile','reference_bits','target','corroboration')):
            raise ValueError('coverage candidate context does not reproduce source')
        context = checked['corroboration']; start=context['prefix_data_offset']
        stop = start+16+context['zero_slot_bytes']
        charge(); spans.append(dict(index=len(spans),kind='candidate_context',declaration_index=None,
            data_offset=start,byte_length=stop-start,end=stop,present=True,basis='candidate_only'))
        candidate_context = dict(data_offset=start,byte_length=stop-start,
            interpretation='Observed header-context prefix only; not a declared allocation or whole-resource bound.')
    charge(2*len(spans)+2)
    events = defaultdict(list)
    for span in spans:
        events[span['data_offset']].append((1,span['index']))
        events[span['end']].append((-1,span['index']))
    limit = max(len(data),minimum)
    events[0]; events[len(data)]; events[limit]
    positions=sorted(events)
    regions=[]; active=set(); totals=defaultdict(int)
    for i,start in enumerate(positions[:-1]):
        for delta,index in events[start]:
            charge()
            if delta==1:active.add(index)
            else:active.remove(index)
        stop=positions[i+1]
        if stop<=start:continue
        charge(1+len(active))
        selected=sorted(active)
        declared=[index for index in selected if spans[index]['basis']!='candidate_only']
        present=stop<=len(data)
        if declared:kind='covered' if present else 'missing_declared'
        elif present:kind='unclaimed_trailing' if start>=minimum else 'unclaimed_internal'
        else:kind='unobserved_unclaimed'
        row=dict(data_offset=start,byte_length=stop-start,kind=kind,span_indices=selected,
            declared_depth=len(declared),candidate_context_present=any(spans[index]['basis']=='candidate_only'for index in selected))
        if present and not declared:
            scan_bytes(stop-start)
            row['all_zero']=not any(memoryview(data)[start:stop])
            totals['unclaimed_zero_bytes'if row['all_zero']else'unclaimed_nonzero_region_bytes']+=stop-start
        if regions and all(regions[-1].get(k)==row.get(k) for k in row if k not in ('data_offset','byte_length')):
            regions[-1]['byte_length']+=stop-start
        else:regions.append(row)
        totals[kind+'_bytes']+=stop-start
        if present and len(declared)>1:totals['overlap_bytes']+=stop-start
    groups=defaultdict(list)
    for row in spans:
        charge()
        if row['basis']!='candidate_only':groups[row['data_offset'],row['end']].append(row['index'])
    aliases=[]
    charge(len(groups))
    for (start,stop),indices in sorted(groups.items()):
        if len(indices)>1:
            charge(1+len(indices));aliases.append(dict(data_offset=start,byte_length=stop-start,span_indices=indices))
    summary={key:totals[key]for key in ('covered_bytes','missing_declared_bytes','unclaimed_internal_bytes',
        'unclaimed_trailing_bytes','unobserved_unclaimed_bytes','overlap_bytes','unclaimed_zero_bytes','unclaimed_nonzero_region_bytes')}
    summary.update(nodes=used,scanned_bytes=byte_work,spans=len(spans),regions=len(regions),exact_alias_groups=len(aliases))
    return dict(profile=PROFILE,status='partial',reference_inventory_complete=complete,
        unread_row_tables=unread,prefix_bytes=len(data),minimum_declared_extent=minimum,
        spans=spans,regions=regions,exact_aliases=aliases,candidate_context=candidate_context,summary=summary,
        resource_endpoint=None,resource_joins_enabled=False,
        offset_space='decompressed same-source 0DRP prefix/declaration bytes',
        interpretation='Declared byte coverage and observed unclaimed bytes only; unknown layout, resource bounds and adjacent-stream ownership remain unconfirmed.')
