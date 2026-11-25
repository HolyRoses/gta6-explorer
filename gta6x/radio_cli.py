"""Standard radio-library command; research exports are never runtime inputs."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from . import radio_catalog, radio_library


def configure(subparsers):
    p = subparsers.add_parser('radio', help='export named stations, tag audio and create VLC playlists', allow_abbrev=False)
    p.add_argument('--list', action='store_true', help='list bundled researched stations without reading game data')
    p.add_argument('--list-tracks', action='store_true', help='list selected song/segment labels and credit status without audio reads')
    p.add_argument('--list-credits', action='store_true', help='list public station/show song credits, including titles with no identified audio')
    p.add_argument('--out', metavar='DIR', help='output library directory')
    p.add_argument('--station', action='append', default=[], metavar='NAME', help='station name/key/fragment; repeat to select several')
    p.add_argument('--song', action='append', default=[], metavar='TEXT', help='filter title/native name, artist or full name hash; repeated filters are alternatives')
    p.add_argument('--catalog', metavar='JSON', help='use an explicit radio catalog instead of the bundled research')
    p.add_argument('--catalog-out', metavar='JSON', help='write the complete portable name/hash/station catalog')
    p.add_argument('--names-out', metavar='JSON', help='write a names-command-compatible hash dictionary without extracting audio')
    p.add_argument('--archive', metavar='FILE', help='explicit audio.rpf path (default: package root/audio.rpf)')
    p.add_argument('--audio-dir', metavar='DIR', help='reuse extracted Opus files with source-address filenames; no game reads')
    p.add_argument('--include-imaging', action='store_true', help='also export station imaging/beds; talk stations are included by default')
    p.add_argument('--include-unassigned', action='store_true', help='also export remaining unclassified recordings under Unassigned')
    p.add_argument('--format', choices=tuple(radio_library.FORMATS), default='opus', help='Opus stream copy (default), or explicit conversion')
    p.add_argument('--premixed', choices=('split', 'continuous', 'both'), default='both', help='premixed playlist view; continuous suppresses split files; full banks retained (default both)')
    p.add_argument('--exact-chapters', action='store_true', help='re-encode Opus chapter splits for decoded-interval cuts instead of packet copy')
    p.add_argument('--order', choices=('catalog', 'title', 'artist'), default='catalog', help='library order; no recovered broadcast schedule is implied')
    p.add_argument('--pre-skip', type=int, default=312, help='explicit inherited Opus pre-skip assumption (default312; original alignment unknown)')
    p.add_argument('--skip-policy', choices=('zero', 'verified-overlap'), default='verified-overlap', help='native mono block-overlap policy; unsupported cases refuse')
    p.add_argument('--max', type=int, metavar='N', help='limit recordings per station (default all)')
    p.add_argument('--dry-run', action='store_true', help='show the complete selected plan without media reads or tool execution')
    p.add_argument('--overwrite', action='store_true', help='replace generated audio; otherwise matching tagged files are reused and conflicts refused')
    p.add_argument('--ffmpeg', metavar='FILE', help='FFmpeg executable (default PATH)')
    p.add_argument('--ffprobe', metavar='FILE', help='ffprobe executable (default PATH)')
    p.add_argument('--timeout', type=int, default=1800, help='per media-tool timeout in seconds (default1800)')
    p.add_argument('--max-records', type=int, default=1000000, help='native metadata/packet work limit per bank')
    p.set_defaults(func=run)


def run(args):
    from .cli import _check_output_paths, table
    try:
        for key in ('catalog', 'out', 'archive', 'audio_dir', 'catalog_out', 'names_out'):
            value = getattr(args, key)
            if value is not None and (not value.strip() or '\0' in value):
                raise ValueError('--' + key.replace('_', '-') + ' requires a nonempty path')
        catalog = radio_catalog.load(args.catalog)
        if args.list_credits:
            if any((args.out, args.list, args.list_tracks, args.dry_run, args.catalog_out, args.names_out)):
                raise ValueError('--list-credits cannot be combined with library/export actions')
            rows = radio_catalog.public_credits(catalog, args.station, args.song,
                maximum=args.max, order=args.order)
            evidence = 'Unordered public song lists; no recording, TRACKID or native station identity is assigned.'
            if args.json:
                print(json.dumps(dict(format='gta6x-radio-public-credits-v1',
                    catalog_sha256=catalog['sha256'], entries=rows, evidence=evidence),
                    indent=2, ensure_ascii=False))
            else:
                print(table([[r['context'], r['title'], r['artist']] for r in rows],
                    ['public station/show', 'title', 'artist/composer'], align='lll'))
                print(f'{len(rows)} public credits. ' + evidence)
            return 0
        selected = radio_catalog.select(catalog, args.station, include_imaging=args.include_imaging,
            include_unassigned=args.include_unassigned, maximum=args.max, order=args.order, songs=args.song)
        if args.catalog_out or args.names_out:
            inputs = [args.catalog or radio_catalog.DEFAULT_CATALOG,
                      args.archive or Path(args.root)/'audio.rpf']
            outputs = [p for p in (args.catalog_out, args.names_out) if p is not None]
            for path in outputs:
                if Path(path).suffix.lower() != '.json':
                    raise ValueError('radio catalog/dictionary outputs must name JSON files')
                if args.audio_dir and Path(path).resolve().is_relative_to(Path(args.audio_dir).resolve()):
                    raise ValueError('radio metadata output cannot overwrite supplied audio inputs')
            if args.out:
                outputs += [Path(args.out)/name for name in ('radio-library.json', 'radio-catalog.json',
                    'radio-names.json', 'credits-catalog.json', 'awc-names.json', 'awc-radio.json')]
            _check_output_paths(inputs, outputs)
            if args.catalog_out:
                radio_library._atomic(args.catalog_out, catalog['source_bytes'])
            if args.names_out:
                radio_library._json(args.names_out, radio_catalog.name_dictionary(catalog))
        if args.list or args.list_tracks or args.dry_run:
            rows = [dict(key=s['key'], name=s['name'], kind=s['kind'],
                         context_type=s.get('context_type', 'station'),
                         recordings=len(s['recordings'])) for s in selected]
            report = dict(format='gta6x-radio-plan-v1', catalog_sha256=catalog['sha256'], stations=rows,
                recordings=sum(r['recordings'] for r in rows), name_hashes=len(catalog['data']['names']),
                membership_evidence=catalog['data']['provenance']['station_membership'])
            if args.dry_run or args.list_tracks:
                report['selection'] = selected
            if args.json:
                print(json.dumps(report, indent=2, ensure_ascii=False))
            else:
                print(table([[r['name'], r['kind'] if r['context_type'] == 'station'
                              else r['context_type'].replace('_', ' '), str(r['recordings']), r['key']] for r in rows],
                            ['station', 'kind', 'recordings', 'key'], align='llrl'))
                print(f"{len(rows)} stations; {report['recordings']} selections; {report['name_hashes']} name/hash entries")
                print('Membership is supplied research; chapter TRACKIDs and unmatched credits remain explicit.')
                if args.list_tracks or args.dry_run:
                    print(table([[s['name'], r['title'], r['artist'], f"0x{r['offset']:x}", r['credit_status']]
                                 for s in selected for r in s['recordings']],
                                ['station', 'title', 'artist', 'AWC offset', 'credit evidence'], align='lllll'))
            return 0
        if not args.out:
            if args.catalog_out or args.names_out:
                return 0
            raise ValueError('radio requires --out DIR, --list or --dry-run')
        if args.audio_dir and args.archive:
            raise ValueError('--audio-dir and --archive are mutually exclusive')
        if args.audio_dir and getattr(args, '_supplied_options', set()) & {'--pre-skip', '--skip-policy'}:
            raise ValueError('--audio-dir uses its existing audio timeline; --pre-skip/--skip-policy apply only to native extraction')
        archive = None
        if not args.audio_dir:
            archive = Path(args.archive) if args.archive else Path(args.root) / 'audio.rpf'
            if not archive.is_file():
                raise ValueError('audio.rpf not found; use --root PACKAGE, --archive FILE or --audio-dir DIR')
        report = radio_library.export(catalog, selected, args.out, archive=archive,
            audio_dir=args.audio_dir, format=args.format, premixed=args.premixed,
            pre_skip=args.pre_skip, skip_policy=args.skip_policy, exact_chapters=args.exact_chapters,
            overwrite=args.overwrite, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, timeout=args.timeout,
            max_records=args.max_records, catalog_path=args.catalog,
            progress=lambda text: print(text, file=sys.stderr, flush=True))
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
        else:
            print(json.dumps(report['summary'], indent=2))
            print('Playlists: ' + str(Path(args.out) / 'playlists'))
            print('Details: ' + str(Path(args.out) / 'radio-library.json'))
        return int(bool(report['failures']))
    except (OSError, ValueError) as exc:
        print('radio export failed: ' + str(exc), file=sys.stderr)
        return 1
