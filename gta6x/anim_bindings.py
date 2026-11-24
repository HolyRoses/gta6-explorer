"""Ordered raw animation binding keys and conditional slot incidences.

A slot's quotient/remainder points into the stored binding table arithmetically.
This view does not bind source records, numeric samples, bones or properties.
"""
from __future__ import annotations

import bisect
import struct

from . import anim_packed, anim_resources as resources

PROFILE = 'ordered_raw_binding_keys_and_slot_incidence_v1'


def inspect_animation(data, animation_start, buffers, *, consume, key=None):
    """Recheck original references and expose all or one exact raw key.

    ``key`` is the pair ``(raw_word_1, raw_word_0)`` of unsigned u32 integers.
    It has no inferred name/hash meaning. Querying still checks the whole parent
    and strict source-key order. An absent key is a complete zero-match result;
    malformed/duplicate/out-of-order keys never select a preferred row.
    """
    result = dict(status='unresolved', candidate_profile=PROFILE, bindings=[])
    try:
        consume()
        if key is not None:
            if (not isinstance(key, (tuple, list)) or len(key) != 2
                    or any(type(word) is not int or not 0 <= word <= 0xffffffff for word in key)):
                raise ValueError('binding key requires raw_word_1 and raw_word_0 as unsigned u32 integers')
            key = tuple(key)
        if len(data) > resources.MAX_RESOURCE:
            raise ValueError('binding layout input exceeds resource size limit')
        if type(animation_start) is not int:
            raise ValueError('binding layout animation offset must be an integer')
        parent = anim_packed.inspect_animation(data, animation_start, buffers,
                                               consume=consume, with_channels=True)
        if parent['status'] != 'complete':
            raise ValueError('binding layout requires checked packed animation: ' + parent['reason'])
        table = parent['binding_header']
        refs, count = struct.unpack_from('<QH', data, animation_start + 80)
        forbidden = [(animation_start, animation_start + 112),
                     (refs - resources.VIRTUAL_BASE, refs - resources.VIRTUAL_BASE + 8 * count)]
        consume(2 + len(parent['buffers']))
        forbidden.extend((b['data_offset'], b['data_offset'] + b['byte_length'])
                         for b in parent['buffers'])
        if table['count']:
            start, end = table['data_offset'], table['data_offset'] + table['byte_length']
            if any(start < hi and lo < end for lo, hi in forbidden):
                raise ValueError('binding table overlaps animation header, buffer references or packed buffers')
        for buffer in parent['buffers']:
            directory = buffer['channel_layout']
            if directory['status'] != 'complete':
                raise ValueError('binding layout requires checked slot directory: ' + directory['reason'])
        records = parent['bindings']
        words = [struct.unpack_from('<III', data, row['data_offset']) for row in records]
        keys = [(row[1], row[0]) for row in words]
        # Check original bytes, not a caller-provided or deserialized packed view.
        if any(a >= b for a, b in zip(keys, keys[1:])):
            raise ValueError('binding raw keys are not strictly increasing by (raw_word_1, raw_word_0)')
        if key is None:
            selected = range(len(records))
        else:
            index = bisect.bisect_left(keys, key)
            selected = (index,) if index < len(keys) and keys[index] == key else ()
        consume(2)
        selected = set(selected)
        incidences = {index: [] for index in selected}
        for buffer in parent['buffers']:
            for group in buffer['channel_layout']['groups']:
                for ordinal, slot in enumerate(group['slots']):
                    # Meter traversal even when a query suppresses output.
                    consume()
                    index = slot['binding_index']
                    if index not in selected:
                        continue
                    consume()
                    incidences[index].append(dict(buffer_index=buffer['index'],
                        group_index=group['group_index'], directory_ordinal=ordinal,
                        directory_data_offset=group['data_offset'] + 2 * ordinal,
                        slot_index=slot['slot_index'], sub_index=slot['sub_index']))
        emitted = []
        for index in sorted(selected):
            row = records[index]
            consume(2)
            emitted.append(dict(index=index, data_offset=row['data_offset'], byte_length=12,
                key_words=[f'0x{word:08x}' for word in keys[index]],
                raw_words=list(row['raw_words']), directory_incidences=incidences[index],
                association_status='conditional slot arithmetic only; source/sample/bone ownership unconfirmed'))
        result.update(status='complete', profile=result.pop('candidate_profile'),
            interpretation='ordered raw binding keys and conditional directory incidences; meanings unknown',
            key_order=['raw_word_1', 'raw_word_0'],
            query_key=None if key is None else [f'0x{word:08x}' for word in key],
            binding_count=len(records), matched_binding_count=len(emitted),
            buffer_count=len(parent['buffers']), bindings=emitted,
            directory_incidence_count=sum(len(row['directory_incidences']) for row in emitted))
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
