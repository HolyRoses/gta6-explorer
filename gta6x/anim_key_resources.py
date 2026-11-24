"""Opt-in native resource metadata with raw key-holder and parent views.

Default metadata readers stay independent. Successful leaf validation/output
work shares the resource budget; exhaustion consumes the remaining allowance
and returns no partial metadata. No key gains a bone or rig meaning.
"""
from __future__ import annotations

from . import anim_bone_keys, anim_key_parents, anim_resources as resources


def scan_resources(path, *, start=None, limit=None, max_nodes=100000):
    """Yield checked metadata and independent structural key-chain views.

    Unsupported profiles retain their reasons. Malformed recognized profiles
    refuse the resource atomically; a metadata-only scan remains available.
    """
    if type(max_nodes) is not int or max_nodes < 0:
        raise ValueError('key resource node budget must be a nonnegative integer')
    remaining = max_nodes
    for row, data, error in resources._scan_chains(path, start=start, limit=limit,
            is_start=lambda d: d[16:20] == b'0DRP', independent_start=resources._independent_start):
        if error is not None:
            yield dict(row, status='refused', reason=error)
            continue
        used = 0
        try:
            parsed = resources.parse_resource(data, max_nodes=remaining)
            used = parsed['summary']['nodes']
            for name, inspect in (('key_holder_layout', anim_bone_keys.inspect),
                                  ('key_parent_layout', anim_key_parents.inspect)):
                if remaining - used < 1:
                    raise resources.ResourceLimitError('key resource views exceed shared node budget')
                view = inspect(data, max_work=remaining - used)
                used += view['work_units']
                parsed[name] = view
            parsed['summary']['nodes'] = used
            remaining -= used
            row.update(parsed)
        except resources.ResourceLimitError as exc:
            # No partly built tables or key views escape; later sources cannot
            # start a fresh allowance after exhausting this shared budget.
            row.update(status='refused', reason=str(exc), summary=dict(nodes=remaining))
            remaining = 0
        except ValueError as exc:
            # Completed leaf work stays charged even when a later view refuses.
            remaining -= used
            row.update(status='refused', reason=str(exc), summary=dict(nodes=used))
        yield row
