"""Command registration for the native bounded MoVE metadata browser."""
from __future__ import annotations

import json
import os

from . import move


def configure(subparsers):
    p = subparsers.add_parser('move', help='browse supported MoVE motion-resource metadata')
    p.add_argument('files', nargs='*', help='raw MoVE files or archives (default: anim archives)')
    p.add_argument('--archive', action='append', default=[], help='archive name fragment')
    p.add_argument('--raw', action='store_true', help='require raw MoVE input')
    p.add_argument('--start', type=lambda value: int(value, 0), help='compressed archive byte offset')
    p.add_argument('--limit', type=int, default=64, help='MiB scanned per archive (default 64)')
    p.add_argument('--full', action='store_true', help='scan full archives')
    p.add_argument('--max', type=int, default=20, help='maximum displayed resource summaries')
    p.add_argument('--max-nodes', type=int, default=100000, help='shared metadata output budget')
    p.add_argument('--objects', action='store_true', help='inspect supported root references/descriptor storage; child meanings remain unknown')
    p.add_argument('--children', action='store_true', help='inspect one further child-prefix level; implies --objects; deeper bodies remain opaque')
    p.add_argument('--tail-forms', action='store_true', help='inspect supported additional opaque tail storage; implies --children')
    p.add_argument('--out', help='write metadata JSON report to FILE')
    p.set_defaults(func=command)


def command(args):
    from .cli import _scan_targets, eprint, table
    if args.tail_forms:
        args.children = True
    if args.children:
        args.objects = True
    if args.max_nodes < 1 or args.max < 0 or (not args.full and args.limit < 1):
        eprint('MoVE node/scan limits must be positive and display limit nonnegative')
        return 1
    if args.start is not None and args.start < 0:
        eprint('MoVE scan start must be nonnegative')
        return 1
    if not args.files and not args.archive:
        args.archive = ['anim']
    targets = _scan_targets(args)
    if not targets:
        eprint('no MoVE input or archive matched')
        return 1
    results, remaining = [], args.max_nodes
    for path in targets:
        try:
            with open(path, 'rb') as source:
                magic = source.read(4)
                if args.raw or magic == b'MoVE':
                    source.seek(0)
                    raw = source.read(move.MAX_BYTES + 1)
                else:
                    raw = None
            if raw is not None:
                row = dict(source=os.path.basename(path), framing='raw_file')
                try:
                    row.update(move.parse(raw, max_nodes=remaining, with_objects=args.objects, with_children=args.children, with_tail_forms=args.tail_forms))
                    remaining -= row['summary']['nodes']
                except ValueError as exc:
                    row.update(status='refused', reason=str(exc))
                results.append(row)
            else:
                for row in move.scan(path, start=args.start,
                        limit=None if args.full else args.limit * 1024 * 1024,
                        max_nodes=max(1, remaining), with_objects=args.objects, with_children=args.children, with_tail_forms=args.tail_forms):
                    if remaining < 1 and row['status'] != 'refused':
                        row = dict(archive=os.path.basename(path), offset=row['offset'], status='refused',
                                   reason='MoVE output exceeds node limit')
                    remaining -= row.get('summary', {}).get('nodes', 0)
                    results.append(row)
        except (OSError, ValueError) as exc:
            results.append(dict(source=os.path.basename(path), status='refused', reason=str(exc)))
    report = dict(format='gta6x-move-scan-v1', resources=results,
        summary=dict(candidates=len(results), parsed=sum(r['status']!='refused' for r in results),
                     refused=sum(r['status']=='refused' for r in results), nodes=args.max_nodes-remaining),
        interpretation='Bounded structural metadata only; motion, pose and timing meanings remain unknown.')
    if args.objects:
        for key in ('object_profiles_resolved','object_profiles_unresolved','object_nodes',
                    'immediate_references','descriptor_records','fixed_cells','nested_subblocks'):
            report['summary'][key] = sum(r.get('summary',{}).get(key,0) for r in results)
    if args.children:
        for key in ('child_nodes','child_candidates','child_profiles_resolved','child_profiles_unresolved',
                    'child_views_partial','child_views_unresolved','child_extension_records','child_references',
                    'child_descriptor_records','child_fixed_cells','child_subblocks'):
            report['summary'][key] = sum(r.get('summary',{}).get(key,0) for r in results)
    if args.tail_forms:
        for key in ('tail_form_nodes','tail_form_candidates','tail_forms_resolved','tail_forms_unresolved',
                    'tail_form_references','tail_form_opaque_records'):
            report['summary'][key] = sum(r.get('summary',{}).get(key,0) for r in results)
        for key in ('tail_form_counted_groups', 'tail_form_selector_words', 'tail_form_opaque_cells',
                    'tail_form_header_prefixes', 'tail_form_header_selector_fields', 'tail_form_header_prefix_bytes'):
            if any(key in r.get('summary', {}) for r in results):
                report['summary'][key] = sum(r.get('summary', {}).get(key, 0) for r in results)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as dest:
            json.dump(report, dest, indent=2, allow_nan=False)
            dest.write('\n')
    if args.json:
        print(json.dumps(report, indent=2, allow_nan=False))
    else:
        rows = [[r.get('source', r.get('archive', '?')), r['status'],
                 str(r.get('byte_length', '?')), r.get('reason', 'objects: ' + r['object_layout'].get('reason', r['object_layout'].get('form','unknown'))
                       if args.objects and 'object_layout' in r else 'bounded metadata; motion semantics unknown')]
                for r in results[:args.max]]
        if rows:
            print(table(rows, ['source', 'status', 'bytes', 'detail']))
        elif not results:
            print('no MoVE candidates found')
        if args.children:
            print(f"child prefixes: {report['summary']['child_profiles_resolved']:,} resolved, "
                  f"{report['summary']['child_profiles_unresolved']:,} unresolved; deeper bodies remain opaque")
            reasons = [(child['data_offset'],child['reason']) for row in results
                       for child in row.get('tail_form_layout' if args.tail_forms else 'child_layout',{}).get(
                           'forms' if args.tail_forms else 'children',[]) if child['status']=='unresolved']
            for at,reason in reasons[:args.max]:
                print(f"  child at 0x{at:x}: {reason}")
        if args.tail_forms:
            print(f"additional tail forms: {report['summary']['tail_forms_resolved']:,} resolved, "
                  f"{report['summary']['tail_forms_unresolved']:,} unresolved; bodies remain opaque")
        if args.out:
            print(f"metadata JSON: {args.out}")
    return int(bool(report['summary']['refused'] or report['summary'].get('object_profiles_unresolved',0)
                    or report['summary'].get('tail_forms_unresolved' if args.tail_forms else 'child_profiles_unresolved',0)
                    or report['summary'].get('child_views_unresolved',0)))
