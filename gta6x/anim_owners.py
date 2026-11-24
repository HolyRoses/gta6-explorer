"""Bounded local animation-dictionary membership; no rig or bone binding.

The animation +24 word is followed only under a checked kind-0 dictionary
profile. Node/name agreement and a unique reverse member establish a local
structural association, without assigning skeleton, bone or numeric ownership.
"""
from __future__ import annotations

import struct

from . import anim_resources as resources, names

PROFILE = 'local_animation_kind0_dictionary_backlink_v1'


def inspect_animation(data, animation_start, *, consume):
    """Check the entire dictionary before returning its unique current member.

    All offsets are relative to the joined source dictionary. Unsupported
    profiles return no partial nodes. ResourceLimitError propagates unchanged.
    This inspector checks target prefixes/names, not their packed samples.
    """
    result = dict(status='unresolved', candidate_profile=PROFILE, nodes=[])
    try:
        consume()
        if len(data) > resources.MAX_RESOURCE or type(animation_start) is not int:
            raise ValueError('invalid animation-owner source bounds')

        def span(word, length, label):
            at = word - resources.VIRTUAL_BASE
            if at < 112 or length < 0 or at > len(data) - length:
                raise ValueError(f'animation owner {label} exceeds source bounds or overlaps dictionary header')
            return at

        def prefix(at):
            span(resources.VIRTUAL_BASE + at, 112, 'animation prefix')
            if data[at:at + 16] != bytes(16) or data[at + 56:at + 72] != bytes(16):
                raise ValueError('unsupported animation-owner member prefix')

        def text(word, length, label):
            if not 0 < length <= 512:
                raise ValueError(f'animation owner {label} length is unsupported')
            pos = span(word, length + 1, label)
            raw = data[pos:pos + length]
            if data[pos + length] or any(b < 32 or b > 126 for b in raw):
                raise ValueError(f'animation owner {label} requires exact final-NUL ASCII')
            consume(1 + (length + 63) // 64)
            return dict(value=raw.decode('ascii'), data_offset=pos, byte_length=length)

        prefix(animation_start)
        reference_at = animation_start + 24
        pointer, = struct.unpack_from('<Q', data, reference_at)
        owner = span(pointer, 112, 'kind0 dictionary prefix')
        if (data[owner:owner + 16] != bytes(16)
                or data[owner + 24:owner + 56] != bytes(32)):
            raise ValueError('unsupported kind0 animation dictionary prefix')
        word, length, capacity, string_flags = struct.unpack_from('<QHHI', data, owner + 56)
        if capacity != length + 1 or string_flags != 1:
            raise ValueError('unsupported kind0 animation dictionary identifier header')
        identifier = text(word, length, 'dictionary identifier')
        word, slots, zero, count, flags, reserved, tag, kind = struct.unpack_from('<QIIIIQII', data, owner + 72)
        if not slots or zero or flags != 0x01000000 or reserved or kind != 0:
            raise ValueError('unsupported kind0 animation dictionary table attributes')
        table = span(word, slots * 8, 'bucket table')
        consume(slots + 2 * count)
        heads = struct.unpack_from(f'<{slots}Q', data, table)
        nodes, visited = [], set()
        for slot, head in enumerate(heads):
            current = head
            while current:
                if current in visited or len(visited) >= count:
                    raise ValueError('animation dictionary node cycle/alias or declared count exceeded')
                visited.add(current)
                at = span(current, 32, 'node')
                key, node_tag, target, following, tail = struct.unpack_from('<IIQQQ', data, at)
                if node_tag or tail:
                    raise ValueError('animation dictionary node reserved word is nonzero')
                target_at = span(target, 112, 'member')
                prefix(target_at)
                name_word, = struct.unpack_from('<Q', data, target_at + 48)
                name_at = span(name_word, 1, 'member name')
                end = data.find(b'\0', name_at, min(len(data), name_at + 513))
                if end < 0:
                    raise ValueError('animation dictionary member name lacks bounded NUL')
                name = text(name_word, end - name_at, 'member name')
                value = name['value']
                stem = value.rsplit('/', 1)[-1][:-5]
                if not value.startswith('pack:/') or not value.endswith('.anim') or not stem or names.joaat(stem) != key:
                    raise ValueError('animation dictionary member name stem/hash differs')
                nodes.append(dict(index=len(nodes), slot_index=slot, node_data_offset=at,
                    key=f'0x{key:08x}', target_data_offset=target_at,
                    target_reference_bits=f'0x{target:016x}', next_reference_bits=f'0x{following:016x}', name=name))
                current = following
        if len(nodes) != count:
            raise ValueError('animation dictionary chains do not exhaust declared node count')
        members = [r['index'] for r in nodes if r['target_data_offset'] == animation_start]
        if len(members) != 1:
            raise ValueError('animation dictionary requires exactly one current-animation member')
        result.update(status='complete', profile=result.pop('candidate_profile'),
            owner_reference_data_offset=reference_at, owner_reference_bits=f'0x{pointer:016x}',
            dictionary_data_offset=owner, dictionary_prefix_byte_length=112, identifier=identifier,
            dictionary_unknown_10_bits=f'0x{struct.unpack_from("<Q", data, owner + 16)[0]:016x}',
            table=dict(data_offset=table, slots=slots, node_count=count, unknown_68_bits=f'0x{tag:08x}'),
            current_member_index=members[0], nodes=nodes,
            interpretation='checked local animation-dictionary membership/backlink; rig and bone ownership unknown')
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
