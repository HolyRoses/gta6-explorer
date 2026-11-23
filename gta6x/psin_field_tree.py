"""Expand bounded local PSIN field paths without assigning application meaning.

Only checked embedded declarations extend a tree. Opaque leaves remain opaque;
source slots do not establish value widths or exclusive ownership. Inputs must
be fresh native reader objects, never purportedly authenticated JSON caches.
"""
from __future__ import annotations

from . import psin_field_context

PROFILE = 'local_psin_embedded_field_tree_v1'
MAX_FIELDS = 4096


def inspect(data, schema, instances, queries, *, consume, max_depth=16,
            max_sample_bytes=8):
    """Return preorder checked contexts rooted at <=32 physical field paths.

    Paths include the root's full depth. Cycles, unavailable children, schema
    descriptors and depth limits are explicit; arrays and pointers are leaves.
    Work is shared with the caller and charged before output or pending paths
    are allocated. A format/work/field-limit failure returns no partial tree.
    """
    psin_field_context._validate_queries(queries, max_depth, max_sample_bytes)
    used = 0
    def charge(n=1):
        nonlocal used
        consume(n)
        used += n

    execute = psin_field_context._prepare(data, schema, instances, consume=charge,
        max_depth=max_depth, max_sample_bytes=max_sample_bytes)
    checked = execute([])
    trees = []
    fields = resolved = unresolved = prefix_bytes = 0
    for block, record, root_path in queries:
        charge(1 + len(root_path))
        tree = dict(block_index=block, record_index=record,
                    field_path=list(root_path), nodes=[], status='complete')
        trees.append(tree)
        pending = [(tuple(root_path), None)]
        while pending:
            if fields >= MAX_FIELDS:
                raise ValueError('PSIN field tree exceeds its 4096-field report limit')
            path, parent = pending.pop()
            context = execute([(block, record, path)])['queries'][0]
            charge(1 + len(path))
            index = len(tree['nodes'])
            node = dict(index=index, parent_index=parent, context=context,
                        expansion='leaf')
            tree['nodes'].append(node)
            fields += 1
            if context['status'] != 'resolved':
                unresolved += 1
                node.update(expansion='unresolved', reason=context['reason'])
                tree['status'] = 'partial'
                continue
            resolved += 1
            prefix_bytes += context['opaque_prefix']['byte_length']
            child = context.get('child_declaration')
            if child is None:
                continue
            ancestry = {entry['owner_hash'] for entry in context['declaration_path']}
            if child['hash'] in ancestry:
                node.update(expansion='cycle_limited', reason='embedded declaration repeats an ancestor')
                tree['status'] = 'partial'
                continue
            if len(path) >= max_depth:
                node.update(expansion='depth_limited', reason='embedded descendants exceed the full field-path depth limit')
                tree['status'] = 'partial'
                continue
            children = child['fields']
            if not children:
                node['expansion'] = 'empty_embedded'
                continue
            charge(len(children) * (2 + len(path)))
            if fields + len(pending) + len(children) > MAX_FIELDS:
                raise ValueError('PSIN field tree exceeds its 4096-field report limit')
            # Reverse stack order gives stable physical-field preorder.
            for field in reversed(children):
                pending.append((path + (field['field_index'],), index))
            node['expansion'] = 'expanded'
    complete = sum(tree['status'] == 'complete' for tree in trees)
    return dict(format='gta6x-psin-field-trees-v1', profile=PROFILE,
                status='complete' if complete == len(trees) else 'partial',
                source_sha256=checked['source_sha256'], schema_id=checked['schema_id'],
                max_depth=max_depth, max_sample_bytes=max_sample_bytes,
                summary=dict(nodes=used, requested_trees=len(trees),
                             trees_complete=complete, trees_partial=len(trees)-complete,
                             fields=fields, resolved=resolved, unresolved=unresolved,
                             opaque_prefix_bytes=prefix_bytes), trees=trees,
                interpretation='Local embedded field contexts only; unknown leaves, value widths, exclusive ownership and transform meanings remain explicit.')
