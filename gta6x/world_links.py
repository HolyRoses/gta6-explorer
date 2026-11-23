"""Bounded local counted-record ranges in the observed world 0DRP profile.

Metadata table pointers and body references are distinct encodings. Only exact
local descriptor/slot relationships authorize these associations. Values, object
roles, primitive descriptors and target records are never decoded or expanded.
The declarations supplied here must be the own reader's same-source output,
not arbitrary persisted JSON offered as an authenticated source.
"""
from __future__ import annotations

import struct

PROFILE = 'world_0drp_local_counted_structure_ranges_v1'
MAX_BYTES = 16 * 1024 * 1024


def _integer(value, label, maximum=MAX_BYTES):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('invalid world-link ' + label)
    return value


def inspect(data, structures, blocks, *, consume, max_depth=16):
    """Inspect normalized, same-source 0DRP declarations under a shared budget.

    A link selects a whole range in an already declared local typed block.
    Inline fixed arrays retain a checked field/element path within their source
    row. Nulls are counted, unknown fields stay explicit, and a malformed known
    header refuses the entire view with no returned link prefix. The caller's
    budget exception propagates. No target row is expanded into an object.
    """
    if (not isinstance(data, bytes) or not 80 <= len(data) <= MAX_BYTES
            or data[16:20] != b'0DRP' or struct.unpack_from('<I', data, 20)[0] != 122):
        raise ValueError('world links require bounded version-122 0DRP source bytes')
    if type(max_depth) is not int or not 1 <= max_depth <= 64:
        raise ValueError('world-link max_depth must be 1..64')
    if not isinstance(structures, list) or not isinstance(blocks, list):
        raise ValueError('world links require local normalized declarations')
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n); used += n
    charge()
    index = {}
    for definition in structures:
        charge()
        if (not isinstance(definition, dict) or not isinstance(definition.get('hash'), str)
                or not isinstance(definition.get('fields'), list)):
            raise ValueError('invalid world-link structure declaration')
        _integer(definition.get('byte_size'), 'structure extent')
        for field in definition['fields']:
            charge()
            if not isinstance(field, list) or len(field) != 4:
                raise ValueError('invalid world-link field declaration')
            for value in field:_integer(value, 'field word', 0xffffffff)
        index.setdefault(definition['hash'], []).append(definition)
    for bi, block in enumerate(blocks):
        charge()
        if (not isinstance(block, dict) or type(block.get('index')) is not int
                or block['index'] != bi or not isinstance(block.get('type_hash'), str)):
            raise ValueError('invalid world-link block declaration')
        length = _integer(block.get('byte_length'), 'block extent')
        at = block.get('data_offset')
        if not length and at is None:continue
        _integer(at, 'block offset')
        if at < 80 or at > len(data)-length:
            raise ValueError('world-link block exceeds its source bytes')

    # Plans skip entire unsupported primitive-leaf blocks; they do not scan
    # millions of raw groups in the hope of finding pointer-looking values.
    cache = {}
    def plan(owner, depth, active):
        key = owner['hash'], depth, active
        if key in cache:return cache[key]
        charge()
        fields = owner['fields']; operations = []; unknown = 0; depth_limited = 0
        if depth > max_depth or owner['hash'] in active:
            return dict(operations=[], unknown=len([f for f in fields if f[0] != 0x100]), depth_limited=1)
        active = active | {owner['hash']}
        for fi, field in enumerate(fields):
            charge()
            name, offset, word, auxiliary = field
            if name == 0x100:continue
            code, di = word & 0xffff, word >> 16
            if code not in (0x50, 0x5c) or di >= len(fields):
                unknown += 1;continue
            descriptor = fields[di]
            definitions = index.get(f'0x{descriptor[3]:08x}', [])
            if (di == fi or descriptor[:3] != [0x100, 0, 5]
                    or len(definitions) != 1 or definitions[0]['byte_size'] <= 0):
                unknown += 1;continue
            target = definitions[0]
            others = [f[1] for j,f in enumerate(fields) if j != fi and f[0] != 0x100]
            if offset >= owner['byte_size'] or offset in others:
                raise ValueError('world-link field shares or exceeds its owning slot')
            end = min([v for v in others if v > offset] + [owner['byte_size']])
            if code == 0x5c:
                if auxiliary or end-offset != 16:
                    raise ValueError('unsupported world counted-record field slot')
                operations.append(dict(kind='counted',field_index=fi,offset=offset,
                    field_hash=name,target_hash=target['hash'],stride=target['byte_size'],owner_hash=owner['hash']))
            else:
                if not auxiliary or auxiliary * target['byte_size'] != end-offset:
                    raise ValueError('world fixed-array count does not exhaust its local field slot')
                child = plan(target, depth+1, active)
                depth_limited += auxiliary * child['depth_limited']
                if child['operations']:
                    operations.append(dict(kind='fixed',field_index=fi,offset=offset,count=auxiliary,
                        stride=target['byte_size'],child=child))
                else:
                    unknown += auxiliary * child['unknown']
        result = dict(operations=operations,unknown=unknown,depth_limited=depth_limited)
        cache[key] = result
        return result

    links = []; paths = []; path_index = {}
    counts = dict(counted_headers=0,null_headers=0,reference_ranges=0,referenced_records=0,
        fixed_array_fields=0,unrepresented_blocks=0,unsupported_field_observations=0,
        unsupported_record_groups=0,depth_limited=0)
    def visit(owner_plan, at, block_index, record_index, owner_hash, path):
        charge()
        counts['unsupported_field_observations'] += owner_plan['unknown']
        counts['depth_limited'] += owner_plan['depth_limited']
        for operation in owner_plan['operations']:
            charge();position = at+operation['offset']
            fi = operation['field_index']
            if operation['kind'] == 'fixed':
                counts['fixed_array_fields'] += 1
                for element in range(operation['count']):
                    visit(operation['child'],position+element*operation['stride'],block_index,
                        record_index,owner_hash,path+((fi,element),))
                continue
            counts['counted_headers'] += 1
            count,other,word = struct.unpack_from('<IIQ',data,position)
            if (count,other,word) == (0,0,0):
                counts['null_headers'] += 1;continue
            if not count or count != other or not word:
                raise ValueError('world counted-record header requires equal positive words and a nonnull reference')
            number, offset = word & 0xfffff, word >> 20
            if not 1 <= number <= len(blocks):
                raise ValueError('world counted-record reference has an invalid local block ID')
            target = blocks[number-1];stride = operation['stride']
            if (target['type_hash'] != operation['target_hash'] or not target['byte_length']
                    or target['byte_length'] % stride or offset % stride
                    or offset > target['byte_length'] or count > (target['byte_length']-offset)//stride):
                raise ValueError('world counted-record target is not a whole bounded matching local record range')
            target_start = target['data_offset']+offset
            if target_start > len(data)-count*stride:
                raise ValueError('world counted-record target escapes its source bytes')
            complete_path = path+((fi,None),)
            identity = owner_hash,complete_path
            if identity not in path_index:
                charge(1+len(complete_path));path_index[identity] = len(paths)
                paths.append(dict(index=len(paths),source_structure_hash=owner_hash,
                    field_path=[dict(field_index=f,**({'element_index':e} if e is not None else {}))
                                for f,e in complete_path],
                    field_structure_hash=operation['owner_hash'],field_hash=f"0x{operation['field_hash']:08x}",
                    target_structure_hash=operation['target_hash'],target_stride=stride))
            charge()
            links.append(dict(source_block_index=block_index,source_record_index=record_index,
                source_path_index=path_index[identity],source_data_offset=position,
                count=count,reference_bits=f'0x{word:016x}',target_block_index=number-1,
                target_record_index=offset//stride))
            counts['reference_ranges'] += 1;counts['referenced_records'] += count
    for block in blocks:
        charge();definitions = index.get(block['type_hash'], [])
        if (len(definitions) != 1 or definitions[0]['byte_size'] <= 0
                or not block['byte_length'] or block['byte_length'] % definitions[0]['byte_size']):
            counts['unrepresented_blocks'] += 1;continue
        owner = definitions[0];number = block['byte_length']//owner['byte_size']
        owner_plan = plan(owner,0,frozenset())
        if not owner_plan['operations']:
            counts['unsupported_record_groups'] += number
            counts['unsupported_field_observations'] += number*owner_plan['unknown']
            counts['depth_limited'] += number*owner_plan['depth_limited']
            continue
        for ri in range(number):
            visit(owner_plan,block['data_offset']+ri*owner['byte_size'],block['index'],ri,owner['hash'],())
    counts.update(nodes=used,source_paths=len(paths))
    partial = any(counts[k] for k in ('unrepresented_blocks','unsupported_field_observations','unsupported_record_groups','depth_limited'))
    return dict(status='partial' if partial else 'complete',profile=PROFILE,links=links,
        source_paths=paths,summary=counts,
        offset_space='decompressed same-source 0DRP bytes; field paths belong to existing declared source rows',
        interpretation='local counted-record ranges only; primitive values, target objects, world roles and graph completeness unconfirmed')
