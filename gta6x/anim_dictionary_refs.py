"""Complete word coverage of checked kind0 dictionary prefixes and nodes.

Only identifier/bucket/member/chain references are established. An unknown
word resembling a local address is retained without traversal or rig/bone
ownership. The containing allocation beyond the checked prefix is unknown.
"""
from __future__ import annotations

import struct

from . import anim_owners, anim_resources as resources, names

PROFILE = 'kind0_dictionary_reference_inventory_v1'

HEADER_FIELDS = (
    (0, 16, 'reserved_00'), (16, 8, 'unknown_10'), (24, 32, 'reserved_18'),
    (56, 8, 'identifier_reference'), (64, 2, 'identifier_length'),
    (66, 2, 'identifier_capacity'), (68, 4, 'identifier_flags'),
    (72, 8, 'bucket_reference'), (80, 4, 'bucket_count'),
    (84, 4, 'reserved_54'), (88, 4, 'node_count'), (92, 4, 'table_flags'),
    (96, 8, 'reserved_60'), (104, 4, 'identifier_hash_candidate'), (108, 4, 'kind0'),
)
NODE_FIELDS = ((0, 4, 'member_key'), (4, 4, 'reserved_04'),
               (8, 8, 'member_reference'), (16, 8, 'next_reference'),
               (24, 8, 'reserved_18'))


def inspect_animation(data, animation_start, *, consume):
    """Reparse a complete owner view, then expose source-backed field coverage.

    The extra hash/bucket checks define this narrower optional profile only.
    Failure leaves no partial word inventory; the underlying owner view remains
    independently available. Every traversal/output item charges the caller.
    """
    result = dict(status='unresolved', candidate_profile=PROFILE,
                  header_fields=[], nodes=[], references=[])
    try:
        parent = anim_owners.inspect_animation(data, animation_start, consume=consume)
        if parent['status'] != 'complete':
            raise ValueError('dictionary references require checked owner: ' + parent['reason'])
        owner = parent['dictionary_data_offset']
        text = parent['identifier']['value']
        word, = struct.unpack_from('<I', data, owner + 104)
        consume(3)
        algorithms = [label for label, algorithm in (('joaat_lower_ascii', names.joaat),
                                                      ('joaat_exact_ascii', names.joaat_exact))
                      if algorithm(text) == word]
        if not algorithms:
            raise ValueError('kind0 identifier hash has no supported literal preimage')
        slots = parent['table']['slots']
        for row in parent['nodes']:
            consume()
            if int(row['key'], 16) % slots != row['slot_index']:
                raise ValueError('kind0 member bucket differs from unsigned key modulo bucket count')

        def fields(start, layout):
            consume(len(layout))
            return [dict(role=role, data_offset=start + relative, byte_length=size,
                         raw_bits='0x' + data[start + relative:start + relative + size][::-1].hex())
                    for relative, size, role in layout]

        header = fields(owner, HEADER_FIELDS)
        nodes, references = [], []

        def reference(role, source, target, length, **extra):
            consume()
            value, = struct.unpack_from('<Q', data, source)
            expected = 0 if target is None else resources.VIRTUAL_BASE + target
            if value != expected:
                raise ValueError('checked dictionary reference differs from original source')
            references.append(dict(role=role, data_offset=source, raw_u64=f'0x{value:016x}',
                target_data_offset=target, target_byte_length=length, **extra))

        reference('identifier', owner + 56, parent['identifier']['data_offset'],
                  parent['identifier']['byte_length'] + 1)
        reference('bucket_array', owner + 72, parent['table']['data_offset'], slots * 8)
        node_offsets = {row['node_data_offset'] for row in parent['nodes']}
        for i in range(slots):
            consume()
            at = parent['table']['data_offset'] + 8 * i
            pointer, = struct.unpack_from('<Q', data, at)
            target = pointer - resources.VIRTUAL_BASE if pointer else None
            if target is not None and target not in node_offsets:
                raise ValueError('bucket head is not a checked node')
            reference('bucket_head', at, target, 32 if target is not None else 0, slot_index=i)
        for row in parent['nodes']:
            consume()
            at = row['node_data_offset']
            nodes.append(dict(index=row['index'], data_offset=at, byte_length=32,
                              fields=fields(at, NODE_FIELDS)))
            reference('animation_member', at + 8, row['target_data_offset'], 112,
                      member_index=row['index'])
            pointer = int(row['next_reference_bits'], 16)
            target = pointer - resources.VIRTUAL_BASE if pointer else None
            if target is not None and target not in node_offsets:
                raise ValueError('chain successor is not a checked node')
            reference('next_node', at + 16, target, 32 if target is not None else 0,
                      member_index=row['index'])
        unknown, = struct.unpack_from('<Q', data, owner + 16)
        consume()
        result.update(status='complete', profile=result.pop('candidate_profile'),
            dictionary_data_offset=owner, header_byte_length=112, node_byte_length=32,
            header_fields=header, nodes=nodes, references=references,
            identifier_hash=dict(data_offset=owner + 104, raw_u32=f'0x{word:08x}',
                literal=text, matching_algorithms=algorithms,
                status='literal preimage only; algorithm family not selected'),
            bucket_rule='unsigned member_key modulo bucket_count',
            unknown_10=dict(data_offset=owner + 16, raw_u64=f'0x{unknown:016x}',
                in_local_address_range=resources.VIRTUAL_BASE <= unknown < resources.VIRTUAL_BASE + len(data),
                traversed=False, meaning='unknown'),
            interpretation='checked prefix/node field coverage and local references; skeleton and bone ownership unknown',
            allocation_end=None, inferred_bone_links=[])
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
