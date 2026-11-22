"""Command registration for the bounded native RBF0 structural browser."""
from __future__ import annotations

import json
import os

from . import rbf


def configure(subparsers):
    p = subparsers.add_parser('rbf', help='browse supported RBF0 token trees and raw metadata')
    p.add_argument('files', nargs='*', help='raw RBF0 files or archives (default: anim archives)')
    p.add_argument('--archive', action='append', default=[], help='archive name fragment')
    p.add_argument('--raw', action='store_true', help='require raw RBF0 input, without archive carving')
    p.add_argument('--start', type=lambda value: int(value, 0), help='compressed archive byte offset')
    p.add_argument('--limit', type=int, default=64, help='MiB scanned per archive (default 64)')
    p.add_argument('--full', action='store_true', help='scan full archives')
    p.add_argument('--max', type=int, default=20, help='maximum displayed resource summaries')
    p.add_argument('--max-nodes', type=int, default=100000, help='shared token/descriptor output budget')
    p.add_argument('--max-depth', type=int, default=32, help='maximum object nesting, up to128 (root depth0)')
    p.add_argument('--max-string-bytes', type=int, default=4096, help='maximum bytes per text value or name')
    p.add_argument('--rig-sets', action='store_true', help='add observed rig-set rows and exact Rig-string index')
    p.add_argument('--name', help='case-sensitive literal substring of rig-set key; implies --rig-sets')
    p.add_argument('--rig', help='exact literal Rig text; implies --rig-sets')
    p.add_argument('--out', help='write full structural JSON report to FILE')
    p.set_defaults(func=command)


def command(args):
    from .cli import _scan_targets, eprint, table
    if args.name is not None or args.rig is not None:
        args.rig_sets = True
    if any(getattr(args, key) < 1 for key in ('max_nodes', 'max_depth', 'max_string_bytes')):
        eprint('RBF node, depth and string limits must be positive')
        return 1
    if args.max_depth > rbf.MAX_DEPTH:
        eprint(f'RBF depth must not exceed {rbf.MAX_DEPTH}')
        return 1
    if args.max < 0 or (not args.full and args.limit < 1) or (args.start is not None and args.start < 0):
        eprint('RBF display/start limits must be nonnegative and scan limit positive')
        return 1
    if not args.files and not args.archive:
        args.archive = ['anim']
    targets = _scan_targets(args)
    if not targets:
        eprint('no RBF input or archive matched')
        return 1
    results, remaining = [], args.max_nodes
    for path in targets:
        try:
            with open(path, 'rb') as source:
                magic = source.read(4)
                if args.raw or magic == b'RBF0':
                    source.seek(0)
                    raw = source.read(rbf.MAX_BYTES + 1)
                else:
                    raw = None
            if raw is not None:
                row = dict(source=os.path.basename(path), framing='raw_file')
                try:
                    row.update(rbf.parse(raw, max_nodes=remaining, max_depth=args.max_depth,
                                         max_string_bytes=args.max_string_bytes))
                    remaining -= row['summary']['nodes']
                except ValueError as exc:
                    row.update(status='refused', reason=str(exc))
                results.append(row)
            else:
                for row in rbf.scan(path, start=args.start,
                        limit=None if args.full else args.limit * 1024 * 1024,
                        max_nodes=max(1, remaining), max_depth=args.max_depth,
                        max_string_bytes=args.max_string_bytes):
                    if remaining < 1 and row['status'] == 'complete':
                        row = dict(archive=os.path.basename(path), offset=row['offset'],
                                   status='refused', reason='RBF output exceeds node limit')
                    remaining -= row.get('summary', {}).get('nodes', 0)
                    results.append(row)
        except (OSError, ValueError) as exc:
            results.append(dict(source=os.path.basename(path), status='refused', reason=str(exc)))
    if args.rig_sets:
        from . import rbf_rigs
        for row in results:
            if row['status'] != 'complete':
                continue
            try:
                if remaining < 1:
                    raise rbf.RbfLimitError('rig-set output exceeds node limit')
                view = rbf_rigs.inspect_tree(row, max_nodes=remaining, name=args.name, rig=args.rig)
                remaining -= view.get('summary', {}).get('nodes', 0)
            except rbf.RbfLimitError as exc:
                view = dict(status='unresolved', reason=str(exc), rig_sets=[], rig_index=[])
            row['rig_set_view'] = view
    report = dict(format='gta6x-rbf0-scan-v1', resources=results,
        summary=dict(candidates=len(results), parsed=sum(r['status']=='complete' for r in results),
                     refused=sum(r['status']=='refused' for r in results), nodes=args.max_nodes-remaining),
        interpretation='Structural metadata only; token type and application meanings remain unknown.')
    if args.rig_sets:
        views = [row['rig_set_view'] for row in results if 'rig_set_view' in row]
        report['summary'].update(rig_profiles_resolved=sum(v['status']=='complete' for v in views),
            rig_profiles_unresolved=sum(v['status']=='unresolved' for v in views),
            selected_rig_sets=sum(v.get('summary', {}).get('selected_rig_sets', 0) for v in views),
            selected_entries=sum(v.get('summary', {}).get('selected_entries', 0) for v in views))
    if args.out:
        parent = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(parent, exist_ok=True)
        with open(args.out, 'w', encoding='utf-8') as dest:
            json.dump(report, dest, indent=2, allow_nan=False)
            dest.write('\n')
    if args.json:
        print(json.dumps(report, indent=2, allow_nan=False))
    else:
        rows = [[r.get('source', r.get('archive', '?')), r['status'],
                 str(r.get('byte_length', '?')), str(r.get('summary', {}).get('tree_nodes', '?')),
                 r.get('reason', 'exact token coverage; meanings unknown')] for r in results[:args.max]]
        if rows:
            print(table(rows, ['source', 'status', 'bytes', 'tokens', 'detail']))
        elif not results:
            print('no RBF0 candidates found')
        if args.rig_sets:
            rig_rows = []
            for resource in results:
                view = resource.get('rig_set_view', {})
                if view.get('status') == 'unresolved':
                    print(f"rig-set profile unresolved: {view['reason']}")
                for rig_set in view.get('rig_sets', []):
                    for entry in rig_set['entries']:
                        if len(rig_rows) < args.max:
                            fields = entry['fields']
                            rig_rows.append([rig_set['key'], fields['Rig'], fields['Dictionary'],
                                             fields['Group'], fields['Priority_bits']])
                    if not rig_set['entries'] and len(rig_rows) < args.max:
                        rig_rows.append([rig_set['key'], '(empty)', '', '', ''])
            if rig_rows:
                print(table(rig_rows, ['rig-set key', 'Rig', 'Dictionary', 'Group', 'Priority bits']))
            print(f"rig-set selection: {report['summary']['selected_rig_sets']:,} sets / "
                  f"{report['summary']['selected_entries']:,} entries; runtime meanings unknown")
        if args.out:
            print(f"structural JSON: {args.out}")
    return int(bool(report['summary']['refused'] or report['summary'].get('rig_profiles_unresolved', 0)))
