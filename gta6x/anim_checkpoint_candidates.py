"""Conditional directory-slot alternatives for checked auxiliary checkpoints.

The stored selector/subindex is insufficient to establish channel ownership.
Even a singleton here is an unconfirmed candidate, not a selected binding.
"""
from __future__ import annotations

from . import anim_resources as resources

PROFILE = 'auxiliary_group_subindex_slot_alternatives_v1'


def inspect(directory, checkpoints, unsupported_source_rows, *, consume):
    """Build shared candidate sets from independently checked parent metadata.

    This internal view consumes checked directory/checkpoint dictionaries, never
    user-supplied JSON. Sets are emitted once per group/subindex; references keep
    repeated checkpoint observations from multiplying the same slot list.
    """
    result = dict(status='unresolved', candidate_profile=PROFILE,
                  checkpoints=[], candidate_sets=[])
    try:
        consume()
        if directory.get('status') != 'complete':
            raise ValueError('checkpoint candidates require a checked directory')
        groups = directory['groups']
        lookup = {}
        sets = []
        rows = []
        for checkpoint in checkpoints:
            selector = checkpoint['selector']
            subindex = checkpoint['raw_u8_01']
            key = selector, subindex
            if key not in lookup:
                group = groups[selector]
                # Meter search work as well as emitted slot dictionaries.
                consume(len(group['slots']))
                slots = []
                for ordinal, slot in enumerate(group['slots']):
                    if slot['sub_index'] != subindex:
                        continue
                    consume()
                    slots.append(dict(slot, directory_ordinal=ordinal,
                        data_offset=group['data_offset'] + 2 * ordinal))
                if not slots:
                    raise ValueError('checked checkpoint has no group/subindex-compatible directory slot')
                consume()
                lookup[key] = len(sets)
                sets.append(dict(index=len(sets), group_index=selector, sub_index=subindex,
                    candidate_count=len(slots), slots=slots,
                    association_status='unconfirmed group/subindex alternatives; no selected channel or source ordering'))
            index = lookup[key]
            count = sets[index]['candidate_count']
            consume()
            rows.append(dict(auxiliary_index=checkpoint['index'], candidate_set_index=index,
                candidate_count=count,
                cardinality='singleton_compatible' if count == 1 else 'ambiguous',
                association_status='unconfirmed even if only one compatible slot'))
        consume()
        result.update(status='complete', profile=result.pop('candidate_profile'),
            checkpoints=rows, candidate_sets=sets,
            summary=dict(rows=len(rows), candidate_sets=len(sets),
                candidate_slots=sum(s['candidate_count'] for s in sets),
                singleton_rows=sum(r['candidate_count'] == 1 for r in rows),
                ambiguous_rows=sum(r['candidate_count'] > 1 for r in rows),
                unsupported_source_rows=unsupported_source_rows),
            interpretation='conditional alternatives only; group meanings, source order and channel ownership unconfirmed')
    except resources.ResourceLimitError:
        raise
    except ValueError as exc:
        result['reason'] = str(exc)
    return result
