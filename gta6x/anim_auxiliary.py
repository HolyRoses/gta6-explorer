"""Explicit packed-animation source/bit checkpoints from auxiliary metadata.

Known selectors bind stored word offsets to independently bounded prefix records
and, for width tables, stored row-bit offsets. Directory slots remain compatible
candidates only. No channel, bone, scalar, sample, codec or timing is decoded.
"""
from __future__ import annotations

import struct

from . import anim_bitrows, anim_channels, anim_prefix, anim_resources as resources

PROFILE = 'auxiliary_source_and_row_bit_checkpoints_v1'
SUPPORTED_SELECTORS = (0, 1, 2, 4, 5)
BOUNDARY_PROFILE = 'auxiliary_prefix_boundary_and_row_end_cursor_v1'


def _boundary_layout(rows, offset, prefix, bits, consume):
    """Check byte boundaries and an end cursor, without assigning a record.

    Selectors 7/8 remain unsupported source/slot rows in the parent view. An
    empty counted prefix supplies a boundary but cannot supply a source record.
    The stored bit value denotes only a checked cursor; it is never a bit span.
    """
    result = dict(status='unresolved', candidate_profile=BOUNDARY_PROFILE,
                  checkpoints=[])
    try:
        consume()
        starts = {record['data_offset'] for record in prefix['opaque_records']}
        empty = not starts
        if empty:
            starts.add(prefix['prefix']['data_offset'] + prefix['prefix']['byte_length'])
        cursor = bits['row_layout']['active_bits_per_row']
        checkpoints = []
        for row in rows:
            if row['selector'] not in (7, 8):
                continue
            position = offset + 32 + 4 * row['raw_u16_02']
            if position not in starts:
                raise ValueError('auxiliary boundary does not select a counted-prefix start or its empty boundary')
            if row['raw_u16_04'] != cursor:
                raise ValueError('auxiliary boundary cursor disagrees with independently checked active row end')
            consume(3)
            checkpoints.append(dict(auxiliary_index=row['index'], selector=row['selector'],
                auxiliary_data_offset=row['data_offset'], data_offset=position,
                boundary_kind='empty_counted_prefix' if empty else 'counted_prefix_record_start',
                row_end_bit_cursor=cursor,
                interpretation='byte boundary and row-end cursor only; no source-record, slot or numeric association'))
        result.update(status='complete', profile=result.pop('candidate_profile'),
                      checkpoints=checkpoints)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result


def inspect_buffer(data, offset, length, binding_count, *, consume, with_candidates=False):
    """Check supported rows atomically; retain unsupported selectors per row.

    A damaged supported checkpoint invalidates this entire view, with no prefix
    rows. Exact aliases remain distinct observations of the same source span.
    Unknown selectors never acquire a target, slot or bit span by proximity.
    """
    consume()
    result = dict(status='unresolved', candidate_profile=PROFILE, checkpoints=[], unsupported_rows=[])
    try:
        if len(data)>resources.MAX_RESOURCE:
            raise ValueError('auxiliary checkpoint input exceeds resource size limit')
        if type(offset) is not int or type(length) is not int or offset<0 or length<32 or offset>len(data)-length:
            raise ValueError('auxiliary checkpoint buffer exceeds input bounds')
        directory = anim_channels.inspect_buffer(data,offset,length,binding_count,consume=consume)
        bits = anim_bitrows.inspect_buffer(data,offset,length,binding_count,consume=consume)
        prefix = anim_prefix.inspect_buffer(data,offset,length,binding_count,consume=consume)
        for label,view in (('directory',directory),('bit rows',bits),('prefix',prefix)):
            if view['status']!='complete':
                raise ValueError('auxiliary checkpoints require supported '+label+': '+view['reason'])
        counts=[group['count'] for group in directory['groups']]
        families={0:prefix['triplet_records'][:counts[0]],
                  1:prefix['triplet_records'][counts[0]:],2:prefix['word_records'],
                  4:bits['fixed_width_records'],5:bits['variable_width_records']}
        by_start={selector:{record['data_offset']:i for i,record in enumerate(records)}
                  for selector,records in families.items()}
        # Width sums are independent of the stored auxiliary bit-offset words.
        expected_bits={};bit=0
        for selector in (4,5):
            for ordinal,record in enumerate(families[selector]):
                expected_bits[selector,ordinal]=bit;bit+=record['width_bits']
        if bit!=bits['row_layout']['active_bits_per_row']:
            raise ValueError('auxiliary checkpoint widths do not exhaust checked row bits')
        header=struct.unpack_from('<5I5H2B',data,offset)
        high,low=header[-1]>>4,header[-1]&15
        start=offset+header[4];row_count=high+low
        if start+6*row_count!=offset+length:
            raise ValueError('auxiliary checkpoint rows do not exhaust nibble-counted tail')
        checkpoints=[];unsupported=[];seen={};aliases=0
        for index in range(row_count):
            at=start+6*index;selector,raw_b,word_offset,stored_bit=struct.unpack_from('<BBHH',data,at)
            consume()
            row=dict(index=index,data_offset=at,byte_length=6,
                nibble_group='high' if index<high else 'low',
                selector=selector,raw_u8_01=raw_b,raw_u16_02=word_offset,raw_u16_04=stored_bit,
                raw_bits='0x'+data[at:at+6][::-1].hex())
            if selector not in SUPPORTED_SELECTORS:
                row.update(status='unresolved',reason='selector has no validated source/slot checkpoint profile')
                unsupported.append(row);continue
            position=offset+32+4*word_offset
            ordinal=by_start[selector].get(position)
            if ordinal is None:
                raise ValueError(f'auxiliary checkpoint {index} does not select a complete independently bounded source record')
            record=families[selector][ordinal]
            expected=expected_bits[selector,ordinal] if selector in (4,5) else 0
            if stored_bit!=expected:
                raise ValueError(f'auxiliary checkpoint {index} bit offset disagrees with independent width/count bounds')
            slots=directory['groups'][selector]['slots']
            if ordinal>=len(slots) or raw_b!=slots[ordinal]['sub_index']:
                raise ValueError(f'auxiliary checkpoint {index} disagrees with compatible source-order directory subindex')
            consume(2)
            row.update(status='complete',source_record=dict(selector=selector,source_ordinal=ordinal,
                data_offset=position,byte_length=record['byte_length']),
                compatible_directory_slot=dict(slots[ordinal],group_index=selector,
                    association_status='candidate; full channel/binding association remains unconfirmed',
                    ordering='same source ordinal hypothesis; alternative slot orderings are not excluded'))
            if selector in (4,5):
                width=record['width_bits']
                if width<=0 or expected+width>bit or not bits['rows']:
                    raise ValueError('auxiliary checkpoint cannot create a zero-width or absent row-bit span')
                consume()
                row['row_bit_checkpoint']=dict(bit_offset=stored_bit,bit_length=width,
                    row_count=bits['row_layout']['header_row_count'],
                    source_row_data_offset=bits['row_layout']['data_offset'],
                    row_stride=bits['row_layout']['row_stride'],
                    meaning='explicit source-record bit checkpoint; numeric/channel meaning unconfirmed')
            identity=selector,ordinal
            if identity in seen:
                row['alias_of_checkpoint_index']=seen[identity];aliases+=1
            else:seen[identity]=index
            checkpoints.append(row)
        consume(3)
        if unsupported:result['reason']='unsupported auxiliary selector rows remain unresolved'
        result.update(status='partial' if unsupported else 'complete',profile=result.pop('candidate_profile'),
            interpretation='explicit auxiliary source/bit checkpoint metadata only; slots and numeric semantics unconfirmed',
            auxiliary=dict(data_offset=start,byte_length=6*row_count,high_nibble_rows=high,low_nibble_rows=low),
            checkpoints=checkpoints,unsupported_rows=unsupported,
            summary=dict(rows=row_count,supported_rows=len(checkpoints),unsupported_rows=len(unsupported),
                aliases=aliases,unique_source_records=len(seen),
                row_bit_checkpoints=sum('row_bit_checkpoint' in row for row in checkpoints)))
        boundary = _boundary_layout(unsupported, offset, prefix, bits, consume)
        result['boundary_checkpoint_layout'] = boundary
        result['summary'].update(boundary_checkpoints=len(boundary['checkpoints']),
            boundary_layouts_unresolved=int(boundary['status'] != 'complete'))
        if with_candidates:
            from . import anim_checkpoint_candidates
            result['candidate_layout'] = anim_checkpoint_candidates.inspect(
                directory, checkpoints, len(unsupported), consume=consume)
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason']=str(exc)
    return result
