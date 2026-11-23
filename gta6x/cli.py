"""Command line interface: ``python3 -m gta6x <command>``."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import hashlib
import xml.etree.ElementTree as ET

from . import catalog as catalog_mod
from . import hunt as hunt_mod
from . import inventory, media, psin, rds5, rpf, zlibcarve

ARCHIVE_GLOBS = (".rpf",)
DEFAULT_ROOT = "."


# --------------------------------------------------------------------------- #
# formatting helpers
# --------------------------------------------------------------------------- #

def human(n: int | float) -> str:
    for unit, scale in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if abs(n) >= scale:
            return f"{n / scale:.2f} {unit}"
    return f"{n} B"


def table(rows: list[list[str]], headers: list[str], align: str | None = None) -> str:
    """Minimal fixed-width table renderer (no third-party deps)."""
    cols = len(headers)
    align = (align or "l" + "r" * (cols - 1))
    align = (align + "l" * cols)[:cols]
    widths = [len(h) for h in headers]
    for row in rows:
        for i in range(cols):
            widths[i] = max(widths[i], len(str(row[i])))

    def line(cells):
        out = []
        for i, cell in enumerate(cells):
            text = str(cell)
            out.append(text.ljust(widths[i]) if align[i] == "l" else text.rjust(widths[i]))
        return "  ".join(out).rstrip()

    parts = [line(headers), "  ".join("-" * w for w in widths)]
    parts += [line(r) for r in rows]
    return "\n".join(parts)


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


# --------------------------------------------------------------------------- #
# package-level discovery
# --------------------------------------------------------------------------- #

def find_archives(root: str, limit_depth: int = 3) -> list[str]:
    found: list[str] = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath[len(root):].count(os.sep)
        if depth >= limit_depth:
            dirnames[:] = []
        for name in sorted(filenames):
            if name.lower().endswith(ARCHIVE_GLOBS):
                found.append(os.path.join(dirpath, name))
    return sorted(found, key=lambda p: -os.path.getsize(p))


def find_resources(root: str) -> list[str]:
    out = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith(".ttpf"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def read_identity(root: str) -> dict:
    """Pull the store identity out of MicrosoftGame.Config, if present."""
    path = os.path.join(root, "MicrosoftGame.Config")
    info: dict = {}
    if not os.path.isfile(path):
        return info
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        tree = ET.fromstring(raw)
    except (OSError, ET.ParseError) as exc:
        return {"error": str(exc)}
    identity = tree.find("Identity")
    if identity is not None:
        info["identity_name"] = identity.get("Name")
        info["publisher"] = identity.get("Publisher")
        info["version"] = identity.get("Version")
    for tag, key in (("TitleId", "title_id"), ("StoreId", "store_id"),
                     ("MSAAppId", "msa_app_id")):
        node = tree.find(tag)
        if node is not None and node.text:
            info[key] = node.text.strip()
    exe = tree.find("./ExecutableList/Executable")
    if exe is not None:
        info["executable"] = exe.get("Name")
        info["target_device_family"] = exe.get("TargetDeviceFamily")
    visuals = tree.find("ShellVisuals")
    if visuals is not None:
        info["display_name"] = visuals.get("DefaultDisplayName")
    return info


def read_layout(root: str) -> dict:
    for name in sorted(os.listdir(root)):
        if not (name.startswith("layout_") and name.endswith(".xml")):
            continue
        path = os.path.join(root, name)
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                text = fh.read()
        except OSError:
            continue
        chunks = re.findall(r"<Chunk\b[^>]*>", text)
        return {
            "file": name,
            "chunks": len(chunks),
            "files": len(re.findall(r"<FileGroup\b", text)),
            "launch_marked": [c for c in chunks if 'Marker="Launch"' in c],
            "source_roots": sorted(set(re.findall(r'SourcePath="([^"]*)"', text)))[:6],
        }
    return {}


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_info(args) -> int:
    root = args.root
    rows = inventory.walk(root, do_hash=False)
    sums = inventory.totals(rows)
    identity = read_identity(root)
    layout = read_layout(root)
    archives = find_archives(root)
    resources = find_resources(root)

    if args.json:
        print(json.dumps({"identity": identity, "layout": layout,
                          "totals": sums, "archives": len(archives),
                          "resources": len(resources)}, indent=2))
        return 0

    print(f"root            : {os.path.abspath(root)}")
    print(f"files           : {sums['files']:,}")
    print(f"size            : {sums['bytes']:,} bytes ({human(sums['bytes'])})")
    print(f"RPF9 archives   : {len(archives)}")
    print(f"RDS5 resources  : {len(resources)}")
    if identity:
        print("\npackage identity")
        for key, value in identity.items():
            print(f"  {key:22s}: {value}")
    if layout:
        print("\nstaging manifest")
        print(f"  file                  : {layout['file']}")
        print(f"  chunks / file entries : {layout['chunks']} / {layout['files']}")
        print(f"  launch-marked chunks  : {len(layout['launch_marked'])}")

    print("\ncomposition by type")
    body = [[t, f"{v['files']:,}", human(v['bytes']), f"{100 * v['bytes'] / max(1, sums['bytes']):.1f}%"]
            for t, v in sums["by_type"].items()]
    print(table(body, ["type", "files", "size", "share"], align="lrrr"))
    return 0


def cmd_headers(args) -> int:
    archives = args.files or find_archives(args.root)
    if not archives:
        eprint("no .rpf archives found")
        return 1
    out = []
    for path in archives:
        try:
            desc = rpf.describe(path)
        except (OSError, ValueError) as exc:
            eprint(f"skip {path}: {exc}")
            continue
        out.append(desc)
    if args.json:
        print(json.dumps(out, indent=2))
        return 0

    body = []
    for d in out:
        body.append([
            d["name"][:40],
            d["revision"],
            f"{d['index_size']:,}",
            f"{d['field_08']:,}",
            f"{d['field_0c']:,}",
            f"0x{d['data_offset']:x}",
            f"0x{d['stamp']:06X}",
            "yes" if d["constant_block"] else "NO",
            "yes" if d["likely_encrypted_toc"] else "no",
            f"{d['index_gap_bytes']:,}",
        ])
    print(table(body, ["archive", "rev", "index(f1)", "0x08", "0x0c", "payload@",
                       "stamp", "const32", "encrypted", "gap0"],
                align="llrrrrrllr"))
    flag = sum(1 for d in out if not d["stamp_ok"]) + sum(1 for d in out if not d["constant_block"])
    print(f"\n{len(out)} archives; {flag} unexpected value(s) against the known set fingerprint")
    print("index(f1) = encrypted index size; payload@ = first byte after it; "
          "gap0 = zero padding before the first resource")
    return 0


def cmd_resources(args) -> int:
    paths = args.files or find_resources(args.root)
    if not paths:
        eprint("no .ttpf files found")
        return 1
    out = []
    for path in paths:
        try:
            out.append(rds5.describe(path))
        except (OSError, ValueError) as exc:
            eprint(f"skip {path}: {exc}")
            continue
    if args.json:
        print(json.dumps(out, indent=2))
        return 0
    body = []
    for d in out:
        chunks = d["chunks"]
        chunk_txt = "+".join(f"{k}:{v:,}" for k, v in sorted(chunks.items())) or "-"
        body.append([d["name"][:42], str(d["version"]), f"{d['chunk_count']:,}",
                     human(d["virtual_size"]), f"{d['etpf']['textures']:,}",
                     chunk_txt, "ok" if d["validated"] else "FAIL"])
    print(table(body, ["file", "ver", "chunks", "virtual", "textures",
                       "chunk kinds", "checked"], align="lrrrrll"))
    ok = sum(1 for d in out if d["validated"])
    print(f"\n{len(out)} RDS5 pools; {ok} validate against the full TTPF rules")
    return 0


def _progress(name: str):
    """Byte-progress on stderr, so stdout stays machine-readable."""
    def report(done: int, total: int, hits: int) -> None:
        pct = 100 * done / max(1, total)
        eprint(f"  {name[:28]:28s} {done / 1024 ** 3:7.2f} / {total / 1024 ** 3:.2f} GiB "
               f"({pct:5.1f}%)  hits={hits}")
    return report


def _collect(path: str, kinds, limit, args) -> list[media.Hit]:
    common = dict(kinds=kinds, require_padding=not args.no_padding,
                  align=None if args.no_align else args.align)
    if getattr(args, "spread", 0):
        return media.scan_windows(path, windows=args.spread,
                                  window_bytes=(limit or 48 * 1024 * 1024), **common)
    return list(media.scan_file(path, limit=limit,
                                progress=None if args.quiet else _progress(os.path.basename(path)),
                                **common))


def _scan_targets(args) -> list[str]:
    if args.files:
        resolved: list[str] = []
        for name in args.files:
            if os.path.exists(name):
                resolved.append(name)
                continue
            candidate = os.path.join(args.root, name)
            if os.path.exists(candidate):
                resolved.append(candidate)
                continue
            matches = [os.path.join(dp, name) for dp, _, fs in os.walk(args.root) if name in fs]
            resolved.append(matches[0] if matches else name)
        return resolved
    archives = find_archives(args.root)
    if args.archive:
        wanted = [a.lower() for a in args.archive]
        archives = [a for a in archives if any(w in os.path.basename(a).lower() for w in wanted)]
    return archives


def cmd_anim(args) -> int:
    """Index animation archive streams and name tables (no clip decode)."""
    from . import anim as anim_mod

    if args.prefix_layout:
        args.bit_layout = True
    if args.lookup_candidates:
        args.bit_layout = True
    if args.bit_layout:
        args.storage_layout = True
    if args.payload_layout:
        args.storage_layout = True
    if args.storage_layout:
        args.channel_layout = True
    if args.channel_layout:
        args.packed_layout = True
    if args.packed_layout:
        args.clip_components = True
    if args.clip_components:
        args.clip_records = True

    if args.max_nodes < 1:
        eprint("--max-nodes must be positive")
        return 1

    if not args.full and args.limit <= 0:
        eprint("--limit must be positive")
        return 1

    if args.start is not None and args.start < 0:
        eprint("--start must be nonnegative")
        return 1

    if not args.archive:
        args.archive = ["anim"]
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    records: list[anim_mod.AnimRecord] = []
    names: set[str] = set()
    scan_failed = False
    resources = []
    clip_dictionaries = []
    remaining_nodes = args.max_nodes
    for path in targets:
        count = 0
        try:
            for record in anim_mod.scan(path, limit=limit, start=args.start):
                records.append(record)
                count += 1
                names.update(record.names)
                if record.name:
                    names.add(record.name)
        except (OSError, ValueError) as exc:
            scan_failed = True
            eprint(f"skip {path}: {exc}")
            continue
        if args.resources:
            from . import anim_resources
            try:
                for resource in anim_resources.scan_resources(path, start=args.start, limit=limit, max_nodes=remaining_nodes):
                    resources.append(resource)
                    remaining_nodes -= resource.get('summary', {}).get('nodes', 0)
            except (OSError, ValueError) as exc:
                eprint(f"resource scan failed for {os.path.basename(path)}: {exc}")
                return 1
        if args.clip_records:
            from . import anim_clips
            try:
                for dictionary in anim_clips.scan_dictionaries(path, start=args.start, limit=limit,
                                                               max_nodes=remaining_nodes, with_components=args.clip_components,
                                                               with_packed_layout=args.packed_layout, with_channels=args.channel_layout, with_storage=args.storage_layout, with_payloads=args.payload_layout, with_bitrows=args.bit_layout, with_lookups=args.lookup_candidates, with_prefix=args.prefix_layout):
                    clip_dictionaries.append(dictionary)
                    remaining_nodes -= dictionary.get('summary', {}).get('nodes', 0)
                    names.update(e['name']['value'] for e in dictionary.get('entries', [])
                                 if e['status'] == 'record_reference')
                    for entry in dictionary.get('entries', []):
                        view = entry.get('components', {})
                        if view.get('status') == 'complete':
                            names.update(segment['animation']['name']['value']
                                         for group in view['groups'] for segment in group['segments'])
            except (OSError, ValueError) as exc:
                eprint(f"clip scan failed for {os.path.basename(path)}: {exc}")
                return 1
        eprint(f"{os.path.basename(path):24s} {count:6d} stream(s)")
    failed = int(scan_failed or any(r['status'] == 'refused' or r.get('summary', {}).get('clips_unresolved', 0)
                     or r.get('summary', {}).get('component_clips_unresolved', 0)
                     or r.get('summary', {}).get('packed_layouts_unresolved', 0)
                     or r.get('summary', {}).get('channel_layouts_unresolved', 0)
                     or r.get('summary', {}).get('storage_layouts_unresolved', 0)
                     or r.get('summary', {}).get('payload_layouts_unresolved', 0)
                     or r.get('summary', {}).get('bitrow_layouts_unresolved', 0)
                     or r.get('summary', {}).get('lookup_layouts_unresolved', 0)
                     or r.get('summary', {}).get('prefix_layouts_unresolved', 0)
                     for r in resources + clip_dictionaries))
    if not records:
        print("no animation streams found")
        return failed
    summary: dict[str, int] = {}
    for record in records:
        summary[record.signature] = summary.get(record.signature, 0) + 1
    clips = sorted(name for name in names if name.endswith(".clip"))
    anims = sorted(name for name in names if name.endswith(".anim"))
    motions = sorted(name for name in names if name.endswith(".motion"))
    detail = {}
    if args.resources:
        detail = dict(resource_summary=dict(
            candidates=len(resources), metadata_parsed=sum(r['status'] == 'partial' for r in resources),
            refused=sum(r['status'] == 'refused' for r in resources),
            nodes=sum(r.get('summary', {}).get('nodes', 0) for r in resources),
            **{key: sum(r.get('summary', {}).get(key, 0) for r in resources)
               for key in ('structures', 'fields', 'enums', 'enum_members', 'blocks')}),
            resources=resources)
        if not args.json:
            info = detail['resource_summary']
            print(f"0DRP: {info['metadata_parsed']:,} metadata parsed, {info['refused']:,} refused; "
                  f"{info['structures']:,} structures / {info['fields']:,} fields; "
                  "0DRP payload semantics remain unresolved")
            for resource in [r for r in resources if r['status'] == 'refused'][:args.max]:
                print(f"  0DRP at 0x{resource['offset']:x}: {resource['reason']}")
    if args.clip_records:
        clip_summary = dict(candidates=len(clip_dictionaries),
            metadata_parsed=sum(r['status'] == 'partial' for r in clip_dictionaries),
            refused=sum(r['status'] == 'refused' for r in clip_dictionaries),
            **{key: sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
               for key in ('nodes', 'entries', 'clips_linked', 'clips_unresolved')})
        if args.clip_components:
            for key in ('component_clips_attempted', 'component_clips_resolved', 'component_clips_unresolved',
                        'component_groups', 'animation_links', 'payload_spans'):
                clip_summary[key] = sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
        if args.packed_layout:
            for key in ('packed_layouts_attempted', 'packed_layouts_resolved', 'packed_layouts_unresolved',
                        'packed_buffer_layouts', 'channel_binding_rows', 'packed_auxiliary_rows'):
                clip_summary[key] = sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
        if args.channel_layout:
            for key in ('channel_layouts_attempted', 'channel_layouts_resolved', 'channel_layouts_unresolved',
                        'channel_groups', 'channel_slots'):
                clip_summary[key] = sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
        if args.storage_layout:
            for key in ('storage_layouts_attempted', 'storage_layouts_resolved', 'storage_layouts_unresolved',
                        'stored_sample_rows', 'sample_bit_layouts_resolved', 'sample_bit_layouts_unresolved'):
                clip_summary[key] = sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
        if args.payload_layout:
            for key in ('payload_layouts_attempted', 'payload_layouts_resolved', 'payload_layouts_unresolved',
                        'payload_word_records', 'payload_words', 'payload_slot_candidates'):
                clip_summary[key] = sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
        if args.bit_layout:
            for key in ('bitrow_layouts_attempted', 'bitrow_layouts_resolved', 'bitrow_layouts_unresolved',
                        'bitrow_fixed_records', 'bitrow_variable_records', 'bitrow_raw_rows', 'bitrow_nonzero_views'):
                clip_summary[key] = sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
        if args.lookup_candidates:
            for key in ('lookup_layouts_attempted', 'lookup_layouts_resolved', 'lookup_layouts_unresolved',
                        'lookup_records', 'lookup_entries', 'lookup_index_observations'):
                clip_summary[key] = sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
        if args.prefix_layout:
            for key in ('prefix_layouts_attempted', 'prefix_layouts_resolved', 'prefix_layouts_unresolved',
                        'prefix_triplet_records', 'prefix_raw_words', 'prefix_opaque_records'):
                clip_summary[key] = sum(r.get('summary', {}).get(key, 0) for r in clip_dictionaries)
        detail.update(clip_record_summary=clip_summary, clip_dictionaries=clip_dictionaries)
        if not args.json:
            print(f"named clips: {clip_summary['clips_linked']:,} linked, "
                  f"{clip_summary['clips_unresolved']:,} unresolved; "
                  f"{clip_summary['refused']:,} dictionary refusals; curves remain unknown")
            if args.clip_components:
                print(f"components: {clip_summary['component_clips_resolved']:,} clips resolved, "
                      f"{clip_summary['component_clips_unresolved']:,} unresolved; "
                      f"{clip_summary['animation_links']:,} animation links / "
                      f"{clip_summary['payload_spans']:,} opaque buffer spans")
            if args.packed_layout:
                print(f"packed layouts: {clip_summary['packed_layouts_resolved']:,} resolved, "
                      f"{clip_summary['packed_layouts_unresolved']:,} unresolved; "
                      f"{clip_summary['channel_binding_rows']:,} raw channel-binding rows; samples remain undecoded")
            if args.channel_layout:
                print(f"channel directories: {clip_summary['channel_layouts_resolved']:,} resolved, "
                      f"{clip_summary['channel_layouts_unresolved']:,} unresolved; "
                      f"{clip_summary['channel_slots']:,} slot associations; group meanings remain unknown")
            if args.storage_layout:
                storage_bit_label = 'unresolved in storage-only view' if args.bit_layout else 'unknown'
                print(f"storage layouts: {clip_summary['storage_layouts_resolved']:,} resolved, "
                      f"{clip_summary['storage_layouts_unresolved']:,} unresolved; "
                      f"{clip_summary['stored_sample_rows']:,} opaque sample rows; "
                      f"{clip_summary['sample_bit_layouts_unresolved']:,} bit grammars {storage_bit_label}")
            if args.payload_layout:
                print(f"payload word inventories: {clip_summary['payload_layouts_resolved']:,} resolved, "
                      f"{clip_summary['payload_layouts_unresolved']:,} unsupported; "
                      f"{clip_summary['payload_words']:,} raw words; slot associations unconfirmed")
            if args.bit_layout:
                print(f"bit-row layouts: {clip_summary['bitrow_layouts_resolved']:,} resolved, "
                      f"{clip_summary['bitrow_layouts_unresolved']:,} unresolved; "
                      f"{clip_summary['bitrow_nonzero_views']:,} nonzero-table views; scalar and codec meanings unknown")
            if args.lookup_candidates:
                print(f"lookup candidate views: {clip_summary['lookup_layouts_resolved']:,} checked, "
                      f"{clip_summary['lookup_layouts_unresolved']:,} unresolved; "
                      f"{clip_summary['lookup_entries']:,} raw entries; order and channel assignments unconfirmed")
            if args.prefix_layout:
                print(f"prefix layouts: {clip_summary['prefix_layouts_resolved']:,} resolved, "
                      f"{clip_summary['prefix_layouts_unresolved']:,} unresolved; "
                      f"{clip_summary['prefix_raw_words']:,} raw words / {clip_summary['prefix_opaque_records']:,} opaque records; associations unknown")
            reasons = [(r['offset'], r['reason']) for r in clip_dictionaries if r['status'] == 'refused']
            reasons += [(r['offset'], e['reason']) for r in clip_dictionaries for e in r.get('entries', [])
                        if e['status'] == 'unresolved']
            reasons += [(r['offset'], e['components']['reason']) for r in clip_dictionaries
                        for e in r.get('entries', []) if e.get('components', {}).get('status') == 'unresolved']
            reasons += [(r['offset'], segment['animation']['packed_layout']['reason'])
                        for r in clip_dictionaries for e in r.get('entries', [])
                        if e.get('components', {}).get('status') == 'complete'
                        for group in e['components']['groups'] for segment in group['segments']
                        if segment['animation'].get('packed_layout', {}).get('status') == 'unresolved']
            if args.channel_layout:
                reasons += [(r['offset'], buffer['channel_layout']['reason'])
                            for r in clip_dictionaries for e in r.get('entries', [])
                            if e.get('components', {}).get('status') == 'complete'
                            for group in e['components']['groups'] for segment in group['segments']
                            if segment['animation'].get('packed_layout', {}).get('status') == 'complete'
                            for buffer in segment['animation']['packed_layout']['buffers']
                            if buffer['channel_layout']['status'] == 'unresolved']
            if args.storage_layout:
                reasons += [(r['offset'], buffer['storage_layout']['reason'])
                            for r in clip_dictionaries for e in r.get('entries', [])
                            if e.get('components', {}).get('status') == 'complete'
                            for group in e['components']['groups'] for segment in group['segments']
                            if segment['animation'].get('packed_layout', {}).get('status') == 'complete'
                            for buffer in segment['animation']['packed_layout']['buffers']
                            if buffer['storage_layout']['status'] == 'unresolved']
            if args.payload_layout:
                reasons += [(r['offset'], buffer['payload_layout']['reason'])
                            for r in clip_dictionaries for e in r.get('entries', [])
                            if e.get('components', {}).get('status') == 'complete'
                            for group in e['components']['groups'] for segment in group['segments']
                            if segment['animation'].get('packed_layout', {}).get('status') == 'complete'
                            for buffer in segment['animation']['packed_layout']['buffers']
                            if buffer['payload_layout']['status'] == 'unresolved']
            if args.bit_layout:
                reasons += [(r['offset'], buffer['bitrow_layout']['reason'])
                            for r in clip_dictionaries for e in r.get('entries', [])
                            if e.get('components', {}).get('status') == 'complete'
                            for group in e['components']['groups'] for segment in group['segments']
                            if segment['animation'].get('packed_layout', {}).get('status') == 'complete'
                            for buffer in segment['animation']['packed_layout']['buffers']
                            if buffer['bitrow_layout']['status'] == 'unresolved']
            if args.lookup_candidates:
                reasons += [(r['offset'], buffer['lookup_layout']['reason'])
                            for r in clip_dictionaries for e in r.get('entries', [])
                            if e.get('components', {}).get('status') == 'complete'
                            for group in e['components']['groups'] for segment in group['segments']
                            if segment['animation'].get('packed_layout', {}).get('status') == 'complete'
                            for buffer in segment['animation']['packed_layout']['buffers']
                            if buffer['lookup_layout']['status'] == 'unresolved']
            if args.prefix_layout:
                reasons += [(r['offset'], buffer['prefix_layout']['reason'])
                            for r in clip_dictionaries for e in r.get('entries', [])
                            if e.get('components', {}).get('status') == 'complete'
                            for group in e['components']['groups'] for segment in group['segments']
                            if segment['animation'].get('packed_layout', {}).get('status') == 'complete'
                            for buffer in segment['animation']['packed_layout']['buffers']
                            if buffer['prefix_layout']['status'] == 'unresolved']
            for offset, reason in reasons[:args.max]:
                print(f"  clip dictionary at 0x{offset:x}: {reason}")
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        manifest = os.path.join(args.out, "anim.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump({"summary": summary,
                       "clips": clips, "anims": anims, "motions": motions,
                       "names": sorted(names),
                       "records": [r.as_dict() for r in records], **detail}, handle, indent=1)
        names_path = os.path.join(args.out, "anim-names.txt")
        with open(names_path, "w", encoding="utf-8") as handle:
            for name in sorted(names):
                handle.write(name + "\n")
        clips_path = os.path.join(args.out, "anim-clips.txt")
        with open(clips_path, "w", encoding="utf-8") as handle:
            for name in clips:
                handle.write(name + "\n")
        if args.json:
            print(json.dumps({"summary": summary, "names": len(names),
                              "manifest": manifest, "names_file": names_path,
                              "clips_file": clips_path,
                              "clips": len(clips), "anims": len(anims),
                              "motions": len(motions),
                              **{key: value for key, value in detail.items() if key.endswith("summary")}}, indent=2))
            return failed
        print(f"{len(records):,} stream(s), {len(names):,} name(s) -> {args.out}")
        print(f"manifest: {manifest}")
        print(f"names: {len(names):,}  clips: {len(clips):,}  "
              f"anim: {len(anims):,}  motion: {len(motions):,}")
        for key, value in sorted(summary.items(), key=lambda kv: -kv[1]):
            print(f"  {key:16s} {value:7,}")
        if args.clips:
            for name in clips[:args.max]:
                print(name)
        return failed
    if args.json:
        print(json.dumps({"summary": summary, "names": sorted(names),
                          "records": [r.as_dict() for r in records[:args.max]],
                          **{key: value[:args.max] if isinstance(value, list) else value
                             for key, value in detail.items()}}, indent=2))
        return failed
    rows = []
    for record in records[:args.max]:
        rows.append([f"0x{record.offset:09x}", f"{record.stored:,}", f"{record.size:,}",
                     record.signature, record.name[:32],
                     str(record.count) if record.count is not None else "-"])
    print(table(rows, ["offset", "stored", "size", "signature", "name", "count"],
                align="lrrllr"))
    print(f"\n{len(records):,} stream(s), {len(names):,} name(s): "
          f"{len(clips):,} clips, {len(anims):,} anim, {len(motions):,} motion")
    print("clip payloads are indexed, not decoded")
    for key, value in sorted(summary.items(), key=lambda kv: -kv[1]):
        print(f"  {key:16s} {value:7,}")
    if args.clips:
        for name in clips[:args.max]:
            print(name)
    return failed


def cmd_movies(args) -> int:
    """List Bink2 movie metadata and optionally extract the selected payloads."""
    if not args.archive:
        args.archive = ["movies"]
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    hits: list[media.Hit] = []
    for path in targets:
        try:
            found = _collect(path, ("bink2",), limit, args)
        except OSError as exc:
            eprint(f"skip {path}: {exc}")
            continue
        hits.extend(found)
        if found:
            eprint(f"{os.path.basename(path):24s} {len(found):5d} movie(s)")

    records: list[dict] = []
    for hit in hits:
        meta = hit.meta or {}
        fps = meta.get("fps") or 0
        frames = meta.get("frames") or 0
        duration = frames / fps if fps else 0.0
        width, height = meta.get("width") or 0, meta.get("height") or 0
        size = hit.size or 0
        if duration < args.min_duration or (
                args.max_duration and duration > args.max_duration):
            continue
        if width < args.min_width or height < args.min_height:
            continue
        if size < args.min_size:
            continue
        records.append({
            "kind": hit.kind,
            "archive": hit.archive,
            "offset": hit.offset,
            "offset_hex": f"0x{hit.offset:09x}",
            "bytes": size,
            "width": width,
            "height": height,
            "fps": fps,
            "frames": frames,
            "duration": round(duration, 3),
            "largest_frame": meta.get("largest_frame"),
            "version": meta.get("version"),
            "bitrate_mbps": round(size * 8 / duration / 1_000_000, 2) if duration else 0,
        })
    if args.sort == "size":
        records.sort(key=lambda r: -r["bytes"])
    elif args.sort == "duration":
        records.sort(key=lambda r: -r["duration"])
    elif args.sort == "resolution":
        records.sort(key=lambda r: -(r["width"] * r["height"]))
    else:
        records.sort(key=lambda r: (r["archive"], r["offset"]))

    written: list[dict] = []
    if args.out and records:
        selected = [h for h in hits if any(
            h.offset == r["offset"] and h.archive == r["archive"] for r in records)]
        written = media.extract_hits(selected, args.out, source_root=args.root)
        by_key = {(r["archive"], r["offset"]): r for r in records}
        for item in written:
            record = by_key.get((item["archive"], item["offset"]), {})
            item.update({k: record.get(k) for k in
                         ("width", "height", "fps", "frames", "duration",
                          "largest_frame", "version", "bitrate_mbps")})
        manifest = args.manifest or os.path.join(args.out, "movies.json")
        os.makedirs(os.path.dirname(os.path.abspath(manifest)), exist_ok=True)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(written, fh, indent=1)
        if args.json:
            print(json.dumps(written, indent=2))
            return 0
        total = sum(w["bytes"] for w in written)
        print(f"extracted {len(written)} movie(s), {total / (1024 * 1024):.1f} MiB "
              f"-> {os.path.abspath(args.out)}")
        print(f"manifest: {manifest}")
        for item in written[:10]:
            print(f"  {os.path.basename(item['file']):40s} {item['width']}x{item['height']} "
                  f"@{item['fps']}fps  {item['bytes']:,} B")
        return 0

    if args.json:
        print(json.dumps(records, indent=2))
        return 0
    if not records:
        print("no matching Bink2 movies")
        return 0
    rows = []
    for record in records[:None if args.all else args.max]:
        rows.append([record["archive"][:18], record["offset_hex"],
                     f"{record['bytes']:,}",
                     f"{record['width']}x{record['height']}",
                     f"{record['fps']}",
                     f"{record['frames']}",
                     f"{record['duration']:.2f}s",
                     f"{record['bitrate_mbps']:.1f}"])
    print(table(rows, ["archive", "offset", "bytes", "resolution", "fps",
                       "frames", "duration", "Mbps"], align="llrrrrrr"))
    total_bytes = sum(r["bytes"] for r in records)
    total_duration = sum(r["duration"] for r in records)
    print(f"\n{len(records)} movie(s), {total_bytes / (1024 * 1024):.1f} MiB, "
          f"{total_duration:.1f}s total; pass --out DIR to extract")
    if not args.all and len(records) > args.max:
        print(f"... {len(records) - args.max} more (raise --max or use --all)")
    return 0


def cmd_scan(args) -> int:
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    kinds = tuple(k.strip() for k in args.kind.split(",") if k.strip())
    limit = None if args.full else args.limit * 1024 * 1024
    hits: list[media.Hit] = []
    for path in targets:
        try:
            found = _collect(path, kinds, limit, args)
        except OSError as exc:
            eprint(f"skip {path}: {exc}")
            continue
        hits.extend(found)
        if found:
            eprint(f"{os.path.basename(path):24s} {len(found):5d} hit(s)")

    if args.json:
        print(json.dumps([h.as_dict() for h in hits], indent=2))
        return 0

    if not hits:
        print("no validated carriers found")
        return 0

    by_kind: dict[str, int] = {}
    for hit in hits:
        by_kind[hit.kind] = by_kind.get(hit.kind, 0) + 1
    print(table([[k, str(v)] for k, v in sorted(by_kind.items())],
                ["kind", "hits"], align="lr"))
    print()
    rows = []
    for hit in hits[: args.max]:
        meta = hit.meta
        if hit.kind.startswith("bink"):
            detail = f"{meta.get('width')}x{meta.get('height')} @{meta.get('fps')}fps"
        else:
            detail = f"{meta.get('streams')} streams, flags {meta.get('flags')}"
        rows.append([hit.archive[:22], hit.kind, f"0x{hit.offset:09x}",
                     f"{hit.size:,}" if hit.size else "-", detail])
    print(table(rows, ["archive", "kind", "offset", "bytes", "detail"], align="lllrl"))
    if len(hits) > args.max:
        print(f"... {len(hits) - args.max:,} more (raise --max)")
    return 0


def cmd_extract(args) -> int:
    targets = _scan_targets(args)
    kinds = tuple(k.strip() for k in args.kind.split(",") if k.strip())
    limit = None if args.full else args.limit * 1024 * 1024
    hits: list[media.Hit] = []
    for path in targets:
        found = _collect(path, kinds, limit, args)
        hits.extend(found)
        if found:
            eprint(f"{os.path.basename(path):24s} {len(found):5d} carrier(s)")
    if not hits:
        eprint("nothing to extract")
        return 1
    if args.max_hits:
        hits = hits[: args.max_hits]
    written = media.extract_hits(hits, args.out, source_root=args.root)
    index = os.path.join(args.out, "extract-index.json")
    with open(index, "w", encoding="utf-8") as fh:
        json.dump(written, fh, indent=2)
    total = sum(w["bytes"] for w in written)
    print(f"extracted {len(written)} file(s), {human(total)} -> {os.path.abspath(args.out)}")
    print(f"index: {index}")
    for row in written[: min(10, len(written))]:
        print(f"  {os.path.basename(row['file']):46s} {row['bytes']:>10,} B  {row['carve_method']}")
    if len(written) > 10:
        print(f"  ... {len(written) - 10} more")
    return 0


def cmd_verify(args) -> int:
    result = inventory.verify_manifest(args.root, args.manifest)
    print(f"match    : {len(result['ok'])}")
    print(f"mismatch : {len(result['bad'])}")
    print(f"missing  : {len(result['missing'])}")
    for row in result["bad"][:10]:
        print(f"  BAD {row['path']} ({row['method']})")
    for path in result["missing"][:10]:
        print(f"  MISSING {path}")
    return 0 if not (result["bad"] or result["missing"]) else 2


def cmd_report(args) -> int:
    from . import report
    rows = inventory.walk(args.root, do_hash=args.hash)
    hits: list[media.Hit] = []
    for path in find_archives(args.root):
        if args.with_media:
            hits.extend(media.scan_file(path, limit=args.limit * 1024 * 1024))
    doc = report.build(args.root, rows, hits, args.title)
    if args.out.endswith(".html"):
        text = report.to_html(doc)
    else:
        text = report.to_markdown(doc)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(f"wrote {args.out} ({len(text):,} bytes)")
    return 0


def cmd_zlib(args) -> int:
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    all_blobs = []
    for path in targets:
        blobs = list(zlibcarve.carve_streams(path, length=limit, min_out=args.min_out))
        total = sum(b.size for b in blobs)
        eprint(f"{os.path.basename(path):24s} {len(blobs):5d} streams  "
               f"{total / 1024 ** 2:8.1f} MiB inflated")
        all_blobs.extend(blobs)
        if args.out:
            zlibcarve.write_blobs(blobs, args.out)
    if not all_blobs:
        print("no zlib streams found")
        return 0
    if args.json:
        print(json.dumps([b.as_dict() for b in all_blobs[: args.max]], indent=2))
        return 0
    import collections
    kinds = collections.Counter(zlibcarve.classify_blob(b.data) for b in all_blobs)
    print()
    print(table([[k, str(v)] for k, v in kinds.most_common()], ["inflated kind", "count"], align="lr"))
    total = sum(b.size for b in all_blobs)
    print(f"\n{len(all_blobs)} streams, {total / 1024 ** 2:.1f} MiB inflated")
    rows = []
    for b in all_blobs[: args.max]:
        rows.append([os.path.basename(b.archive)[:20], f"0x{b.offset:09x}",
                     f"{b.compressed:,}", f"{b.size:,}",
                     f"{b.size / max(1, b.compressed):.1f}x",
                     zlibcarve.classify_blob(b.data)])
    print(table(rows, ["archive", "offset", "packed", "inflated", "ratio", "kind"],
                align="llrrrl"))
    return 0


def cmd_catalog(args) -> int:
    targets = _scan_targets(args)
    if args.db:
        return _catalog_db(args, targets)
    cat_path = args.out
    catalog = catalog_mod.load(cat_path)
    if not targets:
        eprint("no archive matched")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    for path in targets:
        name = os.path.basename(path)
        assets = catalog_mod.sweep_archive(path, length=limit, min_out=args.min_out)
        verified = sum(1 for a in assets if a.verified)
        eprint(f"{name:26s} {len(assets):6d} assets  verified={verified:6d}  "
               f"{sum(a.size for a in assets) / 1024 ** 2:9.1f} MiB inflated")
        catalog_mod.merge(catalog, name, assets)
    catalog_mod.save(cat_path, catalog)
    s = catalog_mod.summary(catalog)
    print(f"catalog: {cat_path}")
    print(f"  archives {s['archives']}   assets {s['assets']:,}   verified {s['verified']:,}")
    print(f"  compressed {human(s['compressed_bytes'])} -> inflated {human(s['inflated_bytes'])}")
    print(table([[k, f"{v:,}"] for k, v in s["by_kind"].items()], ["kind", "count"], align="lr"))
    return 0


def _catalog_db(args, targets) -> int:
    store = catalog_mod.Store(args.db)
    limit = None if args.full else args.limit * 1024 * 1024
    for path in targets:
        name = os.path.basename(path)
        if args.skip_done and store.has_archive(name):
            eprint(f"{name:26s} already catalogued, skipping")
            continue
        assets = catalog_mod.sweep_archive(path, length=limit, min_out=args.min_out)
        store.replace_archive(name, assets)
        verified = sum(1 for a in assets if a.verified)
        if not args.quiet:
            eprint(f"{name:26s} {len(assets):7d} assets  verified={verified:7d}  "
                   f"{sum(a.size for a in assets) / 1024 ** 2:9.1f} MiB inflated")
    counts = store.counts()
    store.close()
    t = counts["total"]
    print(f"database: {args.db}")
    print(f"  assets {t['assets'] or 0:,}   verified {t['verified'] or 0:,}")
    print(f"  compressed {human(t['compressed'] or 0)} -> inflated {human(t['inflated'] or 0)}")
    print(table([[k["kind"], f"{k['count']:,}", human(k["inflated"] or 0)]
                 for k in counts["by_kind"]], ["kind", "count", "inflated"], align="lrr"))
    return 0


def cmd_browse(args) -> int:
    from . import browse
    if args.db:
        store = catalog_mod.Store(args.db)
        out = args.out
        if out.endswith(".html"):
            out = os.path.dirname(out) or "."
        info = browse.render_site(store, out, chunk_rows=args.chunk)
        store.close()
        print(f"wrote {info['index']}  ({info['assets']:,} assets in {info['chunks']} chunks)")
        return 0
    catalog = catalog_mod.load(args.catalog)
    if not catalog.get("archives"):
        eprint(f"empty catalog: {args.catalog}")
        return 1
    html_doc = browse.render(catalog, paths_file=args.paths)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html_doc)
    print(f"wrote {args.out} ({len(html_doc):,} bytes)")
    return 0


def cmd_structured(args) -> int:
    """Recover complete XML/PSIN resources from supported page chains."""
    from . import structured as structured_mod

    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    if args.limit < 0:
        eprint("--limit must be nonnegative")
        return 1
    limit = args.limit * 1024 * 1024
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    rows: list[list[str]] = []
    manifest: list[dict] = []
    total = joined = 0
    for path in targets:
        for hit in structured_mod.recover(path, limit=limit):
            total += 1
            joined += 1 if hit.blocks > 1 else 0
            if len(rows) < args.max:
                rows.append([os.path.basename(path)[:22], hit.kind, hit.root[:34],
                             f"0x{hit.offset:09x}", str(hit.blocks),
                             f"{hit.packed:,}", f"{hit.unpacked:,}"])
            if args.out:
                safe = "".join(c if c.isalnum() or c in "_-." else "_" for c in hit.root)
                if hit.kind == "psin":
                    name = f"metadata_PSIN_at_{hit.offset:016x}.psin"
                else:
                    name = f"xml_{safe[:64]}_at_{hit.offset:016x}.xml"
                dest = os.path.join(args.out, name)
                with open(dest, "wb") as out:
                    out.write(hit.data)
                record = hit.as_dict()
                record["file"] = dest
                manifest.append(record)
        eprint(f"{os.path.basename(path):24s} resources so far: {total:,}")
    if args.out:
        manifest_path = os.path.join(args.out, "structured.json")
        with open(manifest_path, "w", encoding="utf-8") as out:
            json.dump(manifest, out, indent=1)
        if args.json:
            print(json.dumps({"resources": total, "joined": joined,
                              "manifest": manifest_path}, indent=2))
            return 0
        print(f"recovered {total:,} complete resource(s) ({joined:,} joined from "
              f"multiple pages); wrote them to {args.out}")
        print(f"manifest: {manifest_path}")
        return 0
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no complete XML/PSIN resources found")
        return 0
    print(table(rows, ["archive", "kind", "root", "offset", "pages",
                       "packed", "unpacked"], align="lllrrrr"))
    print(f"\n{total:,} complete resource(s); {joined:,} joined from multiple pages")
    print("pass --out DIR to write .xml/.psin files")
    return 0


def cmd_psin(args) -> int:
    """Parse PSIN containers found in an archive's zlib streams.

    Report complete containers, their bodies and stream-split fragments.
    Schema mode joins recoverable pages and inspects checksum-verified LSCH.
    """
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    if args.schema or args.out or args.instances or args.resource_header or args.record_graph or args.registry or args.registry_out:
        return _cmd_psin_schema(args, targets)
    if args.names:
        eprint("--names requires --schema, --instances or --out")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    items = []
    for path in targets:
        for blob in zlibcarve.carve_streams(path, length=limit, min_out=64):
            if psin.is_psin(blob.data):
                parsed = psin.parse(blob.data) or psin.parse_fragment(blob.data)
                if parsed:
                    items.append(parsed)
        eprint(f"{os.path.basename(path):24s} total PSIN containers so far: {len(items)}")
    if not items:
        print("no PSIN containers found")
        return 0
    info = psin.summarise(items)
    if args.json:
        print(json.dumps({"summary": info,
                          "items": [p.as_dict() for p in items[: args.max]]}, indent=2))
        return 0
    print(f"containers {info['containers']:,}   fragments {info['fragments']:,}"
          f"   bodies {info['bodies']:,}   confident {info['confident']:,}")
    print(f"section tags: {info['section_tags']}")
    if info["containers"]:
        print(f"checksums verified: {info['checksums_verified']:,}/"
              f"{info['containers']:,} containers")
    if info["bodies"]:
        print(f"body entries: min {info['entries_min']} avg {info['entries_avg']} "
              f"max {info['entries_max']}")
        print(f"body payload: total {human(info['payload_total'])}  "
              f"avg {info['payload_avg']:,.0f} B")
        print(f"declared-size values: {info['declared_size_top']}")
        print(f"table fill patterns : {info['fill_top']}")
    if info["fragments"]:
        print(f"fragment bytes still missing: {human(info['fragment_missing'])} "
              f"(split across zlib pages)")
    rows = []
    for item in items[: args.max]:
        if item.kind == "container":
            body = item.body
            rows.append([f"{item.total_size:,}", "container",
                         f"{len(item.sections)}", "-",
                         f"{len(body.entries) if body else 0}",
                         f"0x{item.stored_checksum:08X}",
                         "ok" if item.checksum_verified else "BAD"])
        elif item.kind == "fragment":
            rows.append([f"{item.total_size:,}", "fragment",
                         f"{item.declared_size:,}", f"{item.missing:,}",
                         f"{len(item.body.entries) if item.body else 0}", "-", ""])
        else:
            rows.append([f"{item.total_size:,}", "body",
                         f"{item.declared_size:,}", f"{item.field_a:,}",
                         f"{len(item.entries)}",
                         f"0x{item.payload_offset:x}" if item.payload_offset is not None else "?",
                         f"{item.payload_size:,} B" if item.payload_size is not None else "unresolved"])
    print()
    print(table(rows, ["bytes", "kind", "declared/sections", "missing/fieldA",
                       "entries", "checksum/payload@", "chks"], align="rlrrrrl"))
    return 0


def _cmd_psin_schema(args, targets: list[str]) -> int:
    from . import names as names_mod, psin_schema, psin_registry

    if args.record_graph:
        args.instances = True
    if args.max < 0 or (not args.full and args.limit < 0):
        eprint("--max and --limit must be nonnegative")
        return 1
    if args.resource_header and args.max_nodes < 1:
        eprint('--max-nodes must be positive')
        return 1
    if args.instances and (args.max_nodes < 1 or not 1 <= args.max_depth <= 64):
        eprint('--max-nodes must be positive and --max-depth must be 1..64')
        return 1
    outputs = [p for p in (args.out,args.registry_out) if p]
    inputs = targets + [p for p in (args.names,args.registry) if p]
    for dest in outputs:
        for source in inputs + [p for p in outputs if p != dest]:
            if (os.path.realpath(dest) == os.path.realpath(source)
                    or (os.path.exists(dest) and os.path.exists(source)
                        and os.path.samefile(dest, source))):
                eprint("schema output must not overwrite an input or name dictionary")
                return 1
    if args.out and args.registry_out and args.out == args.registry_out:
        eprint('schema and registry outputs must be different')
        return 1
    dictionary = None
    if args.names:
        try:
            dictionary = names_mod.load(args.names)
            if not isinstance(dictionary, dict) or any(
                    not isinstance(dictionary.get(key, {}), dict)
                    for key in ('hashes', 'exact')):
                raise ValueError('name dictionary must contain hash objects')
        except (OSError, ValueError) as exc:
            eprint(f"cannot read names dictionary: {exc}")
            return 1
    registry = None
    build = None
    try:
        if args.registry:
            registry = psin_registry.Registry.load(args.registry)
        if args.registry_out:
            registry = registry if registry is not None else psin_registry.Registry()
            build = registry.build(targets, limit=None if args.full else args.limit*1024*1024)
            registry.save(args.registry_out)
    except (OSError, ValueError) as exc:
        eprint(f'cannot build/load PSIN registry: {exc}')
        return 1
    if args.registry_out and not (args.schema or args.out or args.instances or args.resource_header):
        result = dict(format='gta6x-psin-registry-build-v1', summary=registry.summary(), build=build)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"registry: {result['summary']['schema_pairs']:,} schema pairs, "
                  f"{result['summary']['structure_variants']:,} structure variants, "
                  f"{result['summary']['enum_variants']:,} enum variants -> {args.registry_out}")
            for source in build['refused']:
                eprint(f"{source['file']}:{source.get('offset',0):#x}: {source['error']}")
        return 1 if build['refused'] else 0
    report = psin_schema.inspect_sources(
        targets, limit=None if args.full else args.limit * 1024 * 1024,
        dictionary=dictionary, with_instances=args.instances, with_resource_header=args.resource_header, with_record_graph=args.record_graph,
        max_nodes=args.max_nodes, max_depth=args.max_depth, registry=registry)
    if build is not None:
        report['registry_build'] = build
    if args.out:
        try:
            with open(args.out, 'w', encoding='utf-8') as handle:
                json.dump(report, handle, indent=2)
                handle.write('\n')
        except OSError as exc:
            eprint(f"cannot write schema JSON: {exc}")
            return 1
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        info = report['summary']
        print(f"verified {info['resources_verified']:,}   refused {info['resources_refused']:,}"
              f"   unique schemas {info['unique_schemas']:,}"
              f"   structures {info['structures']:,}   field descriptors {info['field_descriptors']:,}"
              f"   enums {info['enum_definitions']:,}   enum members {info['enum_members']:,}")
        rows = []
        for schema in report['schemas']:
            for structure in schema['structures']:
                if len(rows) >= args.max:
                    break
                matches = ', '.join(dict.fromkeys(m['name'] for m in structure['name_matches']))
                rows.append([schema['id'][:12], structure['hash'], matches or '-',
                             str(structure['byte_size']), str(structure['field_count'])])
            if len(rows) >= args.max:
                break
        print(table(rows, ['schema', 'structure hash/id', 'name candidates', 'bytes', 'descriptors']))
        if args.instances:
            print(f"instance resources: complete {info['instance_resources_complete']:,}"
                  f"   partial {info['instance_resources_partial']:,}"
                  f"   refused {info['instance_resources_refused']:,}"
                  f"   values decoded {info['instance_values_decoded']:,}")
            if info['instance_hash32_arrays_resolved']:
                print(f"hash32 arrays: resolved {info['instance_hash32_arrays_resolved']:,}"
                      f"   linked value observations {info['instance_hash32_array_values_decoded']:,}")
            if info['instance_enum32_arrays_resolved']:
                print(f"enum32 arrays: resolved {info['instance_enum32_arrays_resolved']:,}"
                      f"   existing record links {info['instance_enum32_array_records_linked']:,}")
            if info['instance_structure_arrays_resolved']:
                print(f"structure arrays: resolved {info['instance_structure_arrays_resolved']:,}"
                      f"   record links {info['instance_structure_array_records_linked']:,}")
            if info['instance_reference_arrays_resolved']:
                print(f"reference arrays: resolved {info['instance_reference_arrays_resolved']:,}"
                      f"   record links {info['instance_reference_array_records_linked']:,}"
                      f"   null slots {info['instance_reference_array_null_entries']:,}")
            if info['instance_reference_fields_resolved'] or info['instance_reference_fields_unresolved']:
                print(f"reference fields: linked {info['instance_reference_fields_linked']:,}"
                      f"   nulls {info['instance_reference_fields_null']:,}"
                      f"   unresolved {info['instance_reference_fields_unresolved']:,}")
            if info['instance_text_reference_fields_attempted']:
                print(f"text fields: linked {info['instance_text_reference_pool_entries_linked']:,}"
                      f"   unresolved {info['instance_text_reference_fields_unresolved']:,}")
            if info['instance_maps_resolved'] or info['instance_maps_unresolved']:
                print(f"maps: resolved {info['instance_maps_resolved']:,}"
                      f"   entry links {info['instance_map_entries_linked']:,}"
                      f"   unresolved {info['instance_maps_unresolved']:,}")
        if args.resource_header or args.record_graph:
            print(f"LRSC headers: {info['resource_headers_complete']:,} complete, "
                  f"{info['resource_headers_unresolved']:,} unresolved, "
                  f"{info['resource_headers_refused']:,} refused; "
                  f"{info['resource_header_record_candidates']:,} record candidates; roles unconfirmed")
        if args.record_graph:
            print(f"record association views: {info['record_graph_resources_complete']:,} complete, "
                  f"{info['record_graph_resources_partial']:,} partial, "
                  f"{info['record_graph_resources_refused']:,} refused; "
                  f"{info['record_graph_records']:,} records / {info['record_graph_edges']:,} links")
            print(f"candidate reachability: {info['record_graph_reachable_records']:,} records; "
                  f"{info['record_graph_unanchored']:,} unanchored resources; "
                  f"{info['record_graph_depth_limited']:,} depth-limited views")
        print(report['interpretation'])
        if registry is not None:
            print(f"registry: {registry.summary()['schema_pairs']:,} schema pairs; local definitions take precedence")
        for resource in report['resources']:
            if resource['status'] == 'refused':
                eprint(f"{resource['file']}:{resource.get('offset', 0):#x}: {resource['error']}")
            elif resource.get('instances', {}).get('status') == 'refused':
                eprint(f"{resource['file']}:{resource.get('offset', 0):#x}: instances: {resource['instances']['reason']}")
            if args.resource_header and resource.get('resource_header', {}).get('status') in ('unresolved', 'refused'):
                eprint(f"{resource['file']}:{resource.get('offset', 0):#x}: resource header: {resource['resource_header']['reason']}")
            if resource.get('record_graph', {}).get('status') == 'refused':
                eprint(f"{resource['file']}:{resource.get('offset', 0):#x}: record graph: {resource['record_graph']['reason']}")
        if args.out:
            print(f"schema JSON: {args.out}")
    return 1 if (report['summary']['resources_refused']
                 or report['summary'].get('instance_resources_refused', 0)
                 or (args.resource_header and (report['summary'].get('resource_headers_unresolved', 0)
                                              or report['summary'].get('resource_headers_refused', 0)))
                 or report['summary'].get('record_graph_resources_refused', 0)
                 or (build is not None and build['refused'])) else 0


def cmd_get(args) -> int:
    """Extract one catalogued asset by sha256 prefix or archive:offset."""
    target = args.id.lower()
    if args.db:
        store = catalog_mod.Store(args.db)
        found = store.find(target)
        store.close()
        if not found:
            eprint(f"no catalog entry matches {args.id!r}")
            return 1
        item = dict(found)
        archive = item["archive"]
        return _write_asset(args, archive, item)
    catalog = catalog_mod.load(args.catalog)
    hit = None
    for archive, items in catalog.get("archives", {}).items():
        for item in items:
            if item["sha256"].startswith(target) or f"{archive}:0x{item['offset']:x}" == target \
               or f"{archive}:{item['offset']}" == target:
                hit = (archive, item)
                break
        if hit:
            break
    if not hit:
        eprint(f"no catalog entry matches {args.id!r}")
        return 1
    archive, item = hit
    return _write_asset(args, archive, item)


def _write_asset(args, archive: str, item: dict) -> int:
    path = None
    for dirpath, _dirs, files in os.walk(args.root):
        if archive in files:
            path = os.path.join(dirpath, archive)
            break
    if not path:
        eprint(f"archive {archive} not found under {args.root}")
        return 1
    with open(path, "rb") as fh:
        fh.seek(item["offset"])
        chunk = fh.read(item["compressed"])
    import zlib as _zlib
    try:
        blob = _zlib.decompress(chunk)
        verified = len(blob) == item["size"] and hashlib.sha256(blob).hexdigest() == item["sha256"]
    except _zlib.error as exc:
        eprint(f"inflate failed: {exc}")
        return 1
    suffix = {"xml": ".xml", "text": ".txt", "psin-page": ".psin"}.get(item["kind"], ".bin")
    os.makedirs(args.out, exist_ok=True)
    dest = os.path.join(args.out, f"{archive.split('.')[0]}_{item['offset']:09x}{suffix}")
    with open(dest, "wb") as fh:
        fh.write(blob)
    print(f"{dest}")
    print(f"  kind={item['kind']}  {len(blob):,} bytes  sha256={item['sha256'][:16]}…  "
          f"verified={'yes' if verified else 'NO'}")
    return 0 if verified else 2


def _reload(root: str, archive: str, offset: int, size: int) -> bytes | None:
    import zlib as _zlib
    for dirpath, _dirs, files in os.walk(root):
        if archive in files:
            path = os.path.join(dirpath, archive)
            break
    else:
        return None
    with open(path, "rb") as fh:
        fh.seek(offset)
        head = size
        chunk = fh.read(max(4096, head))
        # compressed size unknown here; read a window and inflate what we can
    try:
        return _zlib.decompressobj().decompress(chunk, 8 * 1024 * 1024)
    except _zlib.error:
        return None


def cmd_hunt(args) -> int:
    """Score catalogued blobs for vertex-buffer-like float content."""
    import zlib as _zlib
    results = []
    if args.db:
        store = catalog_mod.Store(args.db)
        sql = ("SELECT archive, offset, compressed, size, kind, sha256 FROM assets"
               " WHERE size >= ?")
        params: list = [args.min_size]
        if args.kind:
            sql += " AND kind = ?"; params.append(args.kind)
        if args.archive:
            sql += " AND archive LIKE ?"; params.append(f"%{args.archive}%")
        sql += " ORDER BY size DESC LIMIT ?"
        params.append(args.scan)
        rows = store.db.execute(sql, params).fetchall()
        store.close()
    else:
        eprint("hunt needs --db")
        return 1
    cache: dict[str, str] = {}
    missing: set[str] = set()
    for archive, offset, compressed, size, kind, sha in rows:
        path = cache.get(archive)
        if path is None:
            for dirpath, _dirs, files in os.walk(args.root):
                if archive in files:
                    path = os.path.join(dirpath, archive); break
            cache[archive] = path or ""
        if not path:
            missing.add(archive)
            continue
        try:
            with open(path, "rb") as fh:
                fh.seek(offset); chunk = fh.read(compressed)
            blob = _zlib.decompress(chunk)
        except Exception:
            continue
        if args.window:
            sc, inside = hunt_mod.score_windows(blob, window=args.window * 1024)
        else:
            sc, inside = hunt_mod.score(blob), 0
        stride, eq, diff, rep = hunt_mod.best_stride(blob)
        results.append((sc, archive, offset, size, kind, sha, inside, stride, eq, diff, rep))
    if missing:
        eprint(f"warning: {len(missing)} archive(s) not found under {os.path.abspath(args.root)}: "
               f"{', '.join(sorted(missing)[:4])}")
        eprint("         pass --root <package directory> to point at the archives")
    results.sort(key=lambda r: (-r[0].float_ratio, -r[0].unit_ratio))
    if args.json:
        print(json.dumps([{"score": r[0].as_dict(), "archive": r[1], "offset": r[2],
                           "size": r[3], "kind": r[4], "sha256": r[5]}
                          for r in results[: args.max]], indent=2))
        return 0
    import collections
    verdicts = collections.Counter(r[0].verdict for r in results)
    print(f"scanned {len(results):,} blobs (>= {args.min_size:,} B)")
    print(table([[k, str(v)] for k, v in verdicts.most_common()], ["verdict", "count"], align="lr"))
    print()
    rows_out = []
    for sc, archive, offset, size, kind, sha, inside, stride, eq, diff, rep in results[: args.max]:
        rows_out.append([archive[:18], f"0x{offset:09x}", f"{size:,}", kind[:10],
                         f"{sc.float_ratio:.2f}", f"{stride}", f"{eq:.3f}",
                         "fill" if rep else "", sha[:12]])
    print(table(rows_out, ["archive", "offset", "bytes", "kind", "floats", "stride", "eq",
                           "note", "sha256"], align="llrlrrll"))
    if args.dump:
        for sc, archive, offset, size, kind, sha, inside, stride, eq, diff, rep in results[:3]:
            if rep or eq < 0.2:
                continue
            blob = _reload(args.root, archive, offset, size)
            if not blob:
                continue
            print(f"\nrecords of stride {stride} from {archive} @0x{offset:x}:")
            for line in hunt_mod.record_dump(blob, stride, args.dump):
                print("  " + line)
    return 0


def _run_tui(root: str, db: str | None) -> int:
    tui = __import__("gta6x.tui", fromlist=["run", "run_catalog"])
    return tui.run_catalog(db) if db else tui.run(root)


def cmd_shaders(args) -> int:
    """Recover DXBC shaders from RPF9 archives."""
    from . import shaders as shaders_mod

    include_metadata = getattr(args, "metadata", False)
    max_records = getattr(args, "max_records", 4096)
    if include_metadata:
        from .shader_metadata import MAX_RECORDS
        if not 1 <= max_records <= MAX_RECORDS:
            eprint(f"--max-records must be from 1 to {MAX_RECORDS}")
            return 1
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    total = 0
    written = 0
    rows: list[list[str]] = []
    manifest: list[dict] = []
    shown_metadata: list[dict] = []
    metadata_incomplete = 0
    for path in targets:
        for hit in shaders_mod.scan(path, limit=limit):
            total += 1
            name = shaders_mod.safe_name(hit.name)
            record = hit.as_dict() if include_metadata or args.out else None
            if include_metadata:
                record["metadata"] = shaders_mod.metadata(hit.data, max_records=max_records)
                if record["metadata"]["status"] != "complete":
                    metadata_incomplete += 1
            if args.out:
                dest = os.path.join(args.out, f"{name}_{hit.offset:09x}.cso")
                with open(dest, "wb") as out:
                    out.write(hit.data)
                written += 1
                record["file"] = dest
                manifest.append(record)
            if len(rows) < args.max:
                row = [os.path.basename(path)[:22], hit.name[:46],
                       f"0x{hit.offset:09x}", f"{hit.stored:,}", f"{hit.decoded:,}"]
                if include_metadata:
                    programs = record["metadata"]["programs"]
                    if len(programs) == 1:
                        program = programs[0]
                        stage = program["stage"] or f"stage-{program['stage_code']}"
                        profile = f"{stage} {program['shader_model_major']}.{program['shader_model_minor']}"
                    else:
                        profile = "multiple" if programs else "unavailable"
                    row.append(profile)
                    row.append(record["metadata"]["status"])
                    if not args.out:
                        shown_metadata.append(record)
                rows.append(row)
        eprint(f"{os.path.basename(path):24s} shaders so far: {total:,}")
    if args.out:
        manifest_path = os.path.join(args.out, "shaders.json")
        with open(manifest_path, "w", encoding="utf-8") as out:
            json.dump(manifest, out, indent=1)
        if args.json:
            summary = {"shaders": total, "written": written, "manifest": manifest_path}
            if include_metadata:
                summary["metadata_incomplete"] = metadata_incomplete
            print(json.dumps(summary, indent=2))
            return int(metadata_incomplete > 0)
        print(f"recovered {total:,} shader(s); wrote {written:,} .cso files to {args.out}")
        print(f"manifest: {manifest_path}")
        if metadata_incomplete:
            print(f"metadata incomplete for {metadata_incomplete:,} shader(s); see manifest reasons")
        return int(metadata_incomplete > 0)
    if args.json:
        result = {"shaders": total, "shown": len(shown_metadata),
                  "records": shown_metadata, "metadata_incomplete": metadata_incomplete} if include_metadata else rows
        print(json.dumps(result, indent=2))
        return int(metadata_incomplete > 0)
    if not rows:
        print("no validated shaders found")
        return 0
    headings = ["archive", "name", "payload@", "deflate", "dxbc"]
    if include_metadata:
        headings.extend(["profile", "metadata"])
    print(table(rows, headings, align="llrrrll" if include_metadata else "llrrr"))
    print(f"\n{total:,} shader(s); pass --out DIR to write .cso files")
    if metadata_incomplete:
        print(f"metadata incomplete for {metadata_incomplete:,} shader(s); use --json for reasons")
    return int(metadata_incomplete > 0)


def cmd_models(args) -> int:
    """List or extract drawables/fragments through the SixNG backend."""
    from . import models as models_mod

    backend = models_mod.find_backend(args.backend)
    if not backend:
        eprint("no sixng backend found.")
        eprint("  build it once (Rust): git clone https://github.com/holdmysocks/SixNG && \\")
        eprint("  cd SixNG && cargo build --release -p sixng-cli, then set GTA6X_SIXNG=.../sixng")
        eprint("  or pass --backend PATH. Model decoding lives in that external GPL-3.0 tool.")
        return 2
    if not os.path.isdir(args.root):
        eprint(f"not a game folder: {args.root}")
        return 1
    work = os.path.abspath(args.work)
    try:
        if args.action == "index":
            payload = models_mod.index(backend, args.root, work,
                                       [args.archive], force=args.force)
            if args.json:
                print(json.dumps(payload, indent=2))
                return 0
            for item in payload.get("indexed", []):
                stats = item.get("stats", {})
                print(f"indexed {item['archive']}: {stats.get('entries', 0):,} entries, "
                      f"{stats.get('streams', 0):,} streams, "
                      f"{item.get('named_entries', 0):,} named, "
                      f"{item.get('seconds', 0):.1f}s")
            return 0

        info = models_mod.info(backend, args.root, work)
        if args.action == "info":
            rows = [[a["id"], a["container"],
                     "yes" if a.get("indexed") else "no",
                     f"{a['size']:,}"] for a in info.get("archives", [])]
            if args.json:
                print(json.dumps(info, indent=2))
                return 0
            print(table(rows, ["archive", "container", "indexed", "bytes"],
                        align="lllr"))
            return 0

        target = None
        for archive in info.get("archives", []):
            if archive["id"] == args.archive or args.archive in archive["id"]:
                target = archive
                break
        if target is None:
            eprint(f"no archive matching {args.archive!r} in {args.root}")
            return 1
        if not target.get("indexed"):
            eprint(f"{target['id']} is not indexed yet; run: "
                   f"gta6x models index --archive {args.archive}")
            return 1

        if args.action == "list":
            entries = models_mod.list_models(backend, args.root, work, target["id"],
                                             rtype=args.kind, name=args.name,
                                             limit=args.max)
            if args.json:
                print(json.dumps(entries, indent=2))
                return 0
            rows = [[e.get("name") or "-", e.get("rtype", ""), e["id"],
                     f"{e.get('usize', 0):,}", f"{e.get('csize', 0):,}",
                     str(e.get("nstreams", 0))] for e in entries]
            print(table(rows, ["name", "type", "id", "usable", "stored", "streams"],
                        align="lllrrr"))
            print(f"\n{len(entries)} entr{'y' if len(entries) == 1 else 'ies'} "
                  f"({args.kind}); extract with: gta6x models extract "
                  f"--archive {args.archive} --name <regex> --out <dir>")
            return 0

        if not args.out:
            eprint("--out DIR is required for extraction")
            return 1
        result = models_mod.extract_models(backend, args.root, work, target["id"],
                                           os.path.abspath(args.out),
                                           rtype=args.kind, name=args.name,
                                           limit=args.max, raw=args.raw,
                                           textures=args.textures)
        if args.json:
            print(json.dumps(result, indent=2))
            return 0
        print(f"exported {result.get('exported', 0)} / {result.get('selected', 0)} "
              f"to {result.get('out', args.out)} in {result.get('seconds', 0):.1f}s")
        for warning in result.get("warnings", [])[:5]:
            print(f"  warning: {warning}")
        glbs = []
        for dirpath, _dirs, files in os.walk(args.out):
            glbs += [os.path.join(dirpath, f) for f in files if f.endswith(".glb")]
        for path in glbs[:10]:
            print(f"  {path}")
        if len(glbs) > 10:
            print(f"  ... {len(glbs) - 10} more .glb files")
        if result.get("manifest"):
            print(f"manifest: {result['manifest']}")
        return 0
    except RuntimeError as exc:
        eprint(str(exc))
        return 1


def cmd_music(args) -> int:
    """Extract the audio-config music record table."""
    from . import music as music_mod

    if not args.archive:
        args.archive = ["audio"]
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    rows: list[list[str]] = []
    records: list[dict] = []
    for path in targets:
        try:
            recs = music_mod.scan_file(path, limit=limit, start=None)
        except OSError as exc:
            eprint(f"skip {path}: {exc}")
            continue
        selected = [r for r in recs
                    if args.min_ms <= r.duration_ms <= args.max_ms]
        for rec in selected:
            rows.append([os.path.basename(path)[:24], f"0x{rec.config_id:04x}",
                         f"{rec.duration_ms / 1000:.3f}s",
                         f"0x{rec.stream_id:08x}", f"0x{rec.hash_b:08x}"])
            records.append(dict(rec.as_dict(), archive=os.path.basename(path)))
        eprint(f"{os.path.basename(path):24s} {len(selected):6d} record(s)")
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        dest = os.path.join(args.out, "music.json")
        with open(dest, "w", encoding="utf-8") as out:
            json.dump(records, out, indent=1)
        if args.json:
            print(json.dumps({"records": len(records), "manifest": dest}, indent=2))
        else:
            print(f"{len(records):,} music record(s) -> {dest}")
        return 0
    if args.json:
        print(json.dumps(records[:args.max], indent=2))
        return 0
    if not rows:
        print("no music records found")
        return 0
    print(table(rows[:args.max], ["archive", "id", "duration", "stream", "hashB"],
                align="llrll"))
    total = sum(r["duration_ms"] for r in records) / 1000
    print(f"\n{len(records):,} record(s), {total:,.1f}s total; "
          f"{len({r['config_id'] for r in records}):,} distinct ids")
    return 0


def cmd_awc(args) -> int:
    """List the streams inside AWC containers, optionally extracting payloads."""
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    scanned = 0
    rows: list[list[str]] = []
    records: list[dict] = []
    written = 0
    ogg_written = 0
    music_written = 0
    music_wav_written = 0
    music_wav_failed = False
    music_wav_skipped: dict[str, int] = {}
    wav_written = 0
    wav_failed = False
    ogg_failed = False
    wav_skipped: dict[str, int] = {}
    ogg_skipped: dict[str, int] = {}
    if args.opus_library and not (args.wav_out or args.music_wav_out):
        eprint("--opus-library requires --wav-out or --music-wav-out")
        return 1
    if args.wav_pre_skip is not None and not 0 <= args.wav_pre_skip <= 5760:
        eprint("--wav-pre-skip must be between 0 and 5760 frames")
        return 1
    if args.wav_policy != "declared" and not args.wav_out:
        eprint("--wav-policy packet-sequence requires --wav-out")
        return 1
    wav_pre_skip = args.wav_pre_skip
    if wav_pre_skip is None:
        wav_pre_skip = 0 if args.wav_policy == "packet-sequence" else 312
    music_pre_skip = 312 if args.wav_pre_skip is None else args.wav_pre_skip
    if args.music_skip_policy != "zero" and not args.music_wav_out:
        eprint("--music-skip-policy verified-overlap requires --music-wav-out")
        return 1
    if args.ogg_policy != "legacy" and not args.ogg_out:
        eprint("--ogg-policy declared requires --ogg-out")
        return 1
    if args.ogg_pre_skip is not None and not 0 <= args.ogg_pre_skip <= 5760:
        eprint("--ogg-pre-skip must be between 0 and 5760 frames")
        return 1
    if args.ogg_pre_skip is not None and (not args.ogg_out or args.ogg_policy != "declared"):
        eprint("--ogg-pre-skip requires --ogg-out and --ogg-policy declared")
        return 1
    for path in targets:
        hits = _collect(path, ("awc",), limit, args)
        with open(path, "rb") as fh:
            for hit in hits:
                if scanned >= args.max:
                    break
                scanned += 1
                fh.seek(hit.offset)
                buf = fh.read(hit.size or 0)
                meta = media.validate_awc(buf) if buf else None
                if not meta:
                    continue
                streams = meta.get("stream_list", [])
                duration = sum(stream.get("duration") or 0 for stream in streams)
                codecs = sorted({stream.get("codec_name") or "?" for stream in streams})
                rows.append([
                    os.path.basename(path)[:24], f"0x{hit.offset:09x}",
                    f"{hit.size:,}", str(len(streams)), ",".join(codecs),
                    f"{duration:.2f}s",
                ])
                record = {"archive": os.path.basename(path), "offset": hit.offset,
                          "size": hit.size, "flags": meta["flags"],
                          "streams": streams, "files": []}
                if args.raw_out:
                    os.makedirs(args.raw_out, exist_ok=True)
                    stem = os.path.splitext(os.path.basename(path))[0]
                    for stream in streams:
                        length = stream.get("data_bytes") or 0
                        at = stream.get("data_offset")
                        if not length or at is None:
                            continue
                        ext = {"opus": "opus", "xma2": "xma", "pcm": "pcm"}.get(
                            stream.get("codec_name") or "", "bin")
                        name = f"{stem}_{hit.offset:09x}_s{stream['index']}.{ext}"
                        dest = os.path.join(args.raw_out, name)
                        with open(dest, "wb") as out:
                            out.write(buf[at:at + length])
                        record["files"].append(dest)
                        written += 1
                if args.music_out:
                    from . import audio as audio_mod
                    os.makedirs(args.music_out, exist_ok=True)
                    stem = os.path.splitext(os.path.basename(path))[0]
                    for stream in streams:
                        if not stream.get("music"):
                            continue
                        for channel in audio_mod.music_channels(buf, stream):
                            if channel.get("codec") != 0x0B:
                                continue
                            name = (f"{stem}_{hit.offset:09x}_s{stream['index']}"
                                    f"_c{channel['index']}.opus")
                            dest = os.path.join(args.music_out, name)
                            try:
                                blob = audio_mod.extract_music_ogg(
                                    buf, stream, channel["index"], title=name)
                            except ValueError:
                                continue
                            with open(dest, "wb") as out:
                                out.write(blob)
                            record.setdefault("music_files", []).append(dest)
                            music_written += 1
                if args.music_wav_out:
                    from . import audio_music_pcm, audio_pcm
                    music_pcm_backend = audio_music_pcm
                    music_pcm_options = {}
                    if args.music_skip_policy == "verified-overlap":
                        from . import audio_music_skips
                        music_pcm_backend = audio_music_skips
                        music_pcm_options['skip_policy'] = 'verified-overlap'
                    os.makedirs(args.music_wav_out, exist_ok=True)
                    stem = os.path.splitext(os.path.basename(path))[0]
                    for stream in streams:
                        if not stream.get("music"):
                            continue
                        try:
                            music_view = music_pcm_backend.inspect_channels(buf, stream, **music_pcm_options)
                        except ValueError as exc:
                            reason = str(exc)
                            unsupported = isinstance(exc, audio_music_pcm.MusicUnsupportedError)
                            music_wav_failed = music_wav_failed or not unsupported
                            music_wav_skipped[reason] = music_wav_skipped.get(reason, 0) + 1
                            record.setdefault("music_wav_skipped", []).append(dict(
                                stream_index=stream['index'], channel_index=None, reason=reason,
                                unsupported=unsupported, decoder_unavailable=False))
                            continue
                        for channel in music_view['channels']:
                            index = channel['index']
                            try:
                                if not channel['supported_wav']:
                                    raise audio_music_pcm.MusicUnsupportedError(channel['reason'])
                                blob, music_pcm_info = music_pcm_backend.extract_wav(
                                    buf, stream, index, library_path=args.opus_library,
                                    pre_skip=music_pre_skip, **music_pcm_options)
                            except (ValueError, audio_pcm.OpusUnavailableError) as exc:
                                reason = str(exc)
                                unsupported = isinstance(exc, audio_music_pcm.MusicUnsupportedError)
                                unavailable = isinstance(exc, audio_pcm.OpusUnavailableError)
                                music_wav_failed = music_wav_failed or not unsupported
                                music_wav_skipped[reason] = music_wav_skipped.get(reason, 0) + 1
                                record.setdefault("music_wav_skipped", []).append(dict(
                                    stream_index=stream['index'], channel_index=index, reason=reason,
                                    unsupported=unsupported, decoder_unavailable=unavailable))
                                continue
                            dest = os.path.join(args.music_wav_out,
                                f"{stem}_{hit.offset:09x}_s{stream['index']}_c{index}.wav")
                            with open(dest, "wb") as out:
                                out.write(blob)
                            record.setdefault("music_wav_files", []).append(dest)
                            record.setdefault("music_wav_metadata", []).append(dict(
                                music_pcm_info, stream_index=stream['index'], file=dest))
                            music_wav_written += 1
                if args.ogg_out:
                    from . import audio as audio_mod
                    os.makedirs(args.ogg_out, exist_ok=True)
                    stem = os.path.splitext(os.path.basename(path))[0]
                    for stream in streams:
                        if stream.get("codec_name") != "opus" and args.ogg_policy == "legacy":
                            continue
                        name = f"{stem}_{hit.offset:09x}_s{stream['index']}.opus"
                        dest = os.path.join(args.ogg_out, name)
                        try:
                            if args.ogg_policy == "declared":
                                from . import audio_ogg
                                skip = 312 if args.ogg_pre_skip is None else args.ogg_pre_skip
                                blob, ogg_info = audio_ogg.extract_ogg(buf, stream, pre_skip=skip, title=name)
                            else:
                                blob = audio_mod.extract_ogg(buf, stream, title=name)
                                ogg_info = None
                        except ValueError as exc:
                            if args.ogg_policy == "declared":
                                reason = str(exc)
                                candidate = (stream.get("codec") == 0x0b and not stream.get("music")
                                             and stream.get("channels") == 1 and stream.get("sample_rate") == 48000)
                                ogg_failed = ogg_failed or candidate
                                ogg_skipped[reason] = ogg_skipped.get(reason, 0) + 1
                                record.setdefault("ogg_skipped", []).append(dict(stream_index=stream['index'], reason=reason))
                            continue
                        with open(dest, "wb") as out:
                            out.write(blob)
                        record.setdefault("ogg_files", []).append(dest)
                        if ogg_info is not None:
                            record.setdefault("ogg_metadata", []).append(dict(ogg_info, stream_index=stream['index'], file=dest))
                        ogg_written += 1
                if args.wav_out:
                    from . import audio_pcm
                    os.makedirs(args.wav_out, exist_ok=True)
                    stem = os.path.splitext(os.path.basename(path))[0]
                    for stream in streams:
                        candidate = (stream.get("codec") == 0x0b and stream.get("codec_name") == "opus"
                                     and not stream.get("music")
                                     and stream.get("channels") in ((1, 2) if args.wav_policy == "packet-sequence" else (1,))
                                     and stream.get("sample_rate") == 48000)
                        try:
                            blob, pcm_info = audio_pcm.extract_wav(
                                buf, stream, library_path=args.opus_library, pre_skip=wav_pre_skip,
                                interval_policy=args.wav_policy)
                        except (ValueError, audio_pcm.OpusUnavailableError) as exc:
                            reason = str(exc)
                            unavailable = isinstance(exc, audio_pcm.OpusUnavailableError)
                            wav_failed = wav_failed or candidate or unavailable
                            wav_skipped[reason] = wav_skipped.get(reason, 0) + 1
                            record.setdefault("wav_skipped", []).append(dict(
                                stream_index=stream['index'], reason=reason,
                                decoder_unavailable=unavailable))
                            continue
                        dest = os.path.join(args.wav_out, f"{stem}_{hit.offset:09x}_s{stream['index']}.wav")
                        with open(dest, "wb") as out:
                            out.write(blob)
                        record.setdefault("wav_files", []).append(dest)
                        record.setdefault("wav_metadata", []).append(dict(
                            pcm_info, stream_index=stream['index'], file=dest))
                        wav_written += 1
                records.append(record)
        if scanned >= args.max:
            break

    if args.json:
        print(json.dumps(records, indent=2))
        return int(wav_failed or ogg_failed or music_wav_failed)
    if not rows:
        print("no AWC containers found")
        return 0
    print(table(rows, ["archive", "offset", "bytes", "streams", "codecs", "duration"],
                align="llrrll"))
    print(f"\n{scanned} container(s) shown; {sum(len(r['streams']) for r in records):,} stream(s)"
          + (f"; {written} raw payload(s) written to {args.raw_out}" if args.raw_out else "")
          + (f"; {ogg_written} Ogg Opus file(s) written to {args.ogg_out}" if args.ogg_out else "")
          + (f"; {music_written} music-channel Ogg file(s) written to {args.music_out}" if args.music_out else "")
          + (f"; {wav_written} PCM WAV file(s) written to {args.wav_out}" if args.wav_out else "")
          + (f"; {music_wav_written} music-channel WAV file(s) written to {args.music_wav_out}" if args.music_wav_out else ""))
    if args.wav_out:
        for reason, count in sorted(wav_skipped.items(), key=lambda item: -item[1]):
            print(f"  WAV skipped {count:,}: {reason}")
        interval = "the complete packet sequence" if args.wav_policy == "packet-sequence" else "declared duration"
        print(f"WAV uses {wav_pre_skip} pre-skip frames and {interval}; original sample alignment is unconfirmed")
    if args.music_wav_out:
        for reason, count in sorted(music_wav_skipped.items(), key=lambda item: -item[1]):
            print(f"  music WAV skipped {count:,}: {reason}")
        if args.music_skip_policy == "zero":
            print(f"Music WAV requires zero block skips; {music_pre_skip} pre-skip frames and original alignment remain unconfirmed")
        else:
            print(f"Music WAV verifies whole-packet overlaps; {music_pre_skip} pre-skip frames and original alignment remain unconfirmed")
    if args.ogg_policy == "declared":
        for reason, count in sorted(ogg_skipped.items(), key=lambda item: -item[1]):
            print(f"  declared-length Ogg skipped {count:,}: {reason}")
        print("Ogg uses explicit pre-skip and declared duration; original sample alignment is unconfirmed")
    print("raw payloads keep their native codec; --ogg-out remuxes Opus losslessly; --music-out extracts one Ogg per music channel")
    return int(wav_failed or ogg_failed or music_wav_failed)


def _find_pools(root: str, wanted: list[str]) -> list[str]:
    pools: list[str] = []
    for name in wanted:
        if os.path.isfile(name):
            pools.append(name)
    bases = [os.path.join(root, "data", "ttdb")]
    pack_root = os.path.join(root, "pack")
    if os.path.isdir(pack_root):
        for dirpath, _dirs, _files in os.walk(pack_root):
            if os.path.basename(dirpath) == "ttdb":
                bases.append(dirpath)
    for base in bases:
        if not os.path.isdir(base):
            continue
        for dirpath, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(".ttpf"):
                    pools.append(os.path.join(dirpath, name))
    pools = sorted(set(pools))
    if wanted:
        needles = [w.lower() for w in wanted if not os.path.isfile(w)]
        if needles:
            pools = [p for p in pools if any(n in p.lower() for n in needles)]
    return pools


def _skip_category(reason: str) -> str:
    if "BCPack" in reason:
        return "BCPack chunks (unsupported or decode failed)"
    if "not covered" in reason:
        return "uncovered virtual range"
    if "cube" in reason:
        return "cube-map copies"
    if "64 MiB" in reason:
        return "larger than 64 MiB"
    if "unsupported" in reason:
        return "unsupported tile/format"
    return reason


def _cmd_embedded_via_backend(args) -> int:
    """Embedded txd extraction delegated to the SixNG backend."""
    from . import models as models_mod

    if not args.out:
        eprint("--out DIR is required for extraction")
        return 1
    backend = models_mod.find_backend(args.backend)
    if not backend:
        eprint("no sixng backend found; build it (see README) or use --via native")
        return 2
    work = os.path.abspath(args.work)
    try:
        info = models_mod.info(backend, args.root, work)
        wanted = [name.lower() for name in args.archive]
        archives = [a for a in info.get("archives", [])
                    if a["id"].endswith(".rpf")]
        target = None
        for archive in archives:
            if wanted and any(name in archive["id"].lower() for name in wanted):
                target = archive
                break
        if target is None and not wanted and archives:
            target = archives[0]
        if target is None:
            eprint(f"no archive matching {args.archive!r}")
            return 1
        if not target.get("indexed"):
            hint = wanted[0] if wanted else target["id"]
            eprint(f"{target['id']} is not indexed; run: "
                   f"gta6x models index --archive {hint}")
            return 1
        command = ["extract", target["id"], "--rtype", "txd",
                   "--limit", str(args.max), "-o", os.path.abspath(args.out),
                   "--tex", "dds"]
        if args.name:
            command += ["--name", args.name]
        payload = models_mod.run(backend, args.root, work, command)
        result = payload.get("result", payload)
    except RuntimeError as exc:
        eprint(str(exc))
        return 1
    os.makedirs(args.out, exist_ok=True)
    dds = []
    for dirpath, _dirs, files in os.walk(args.out):
        dds += [os.path.join(dirpath, f) for f in files if f.endswith(".dds")]
    if args.json:
        print(json.dumps({"result": result, "dds": dds}, indent=2))
        return 0
    print(f"backend exported {result.get('exported', 0)} dictionaries "
          f"({len(dds)} DDS files) to {result.get('out', args.out)}")
    for path in dds[:8]:
        print(f"  {path}")
    if len(dds) > 8:
        print(f"  ... {len(dds) - 8} more")
    print(f"manifest: {result.get('manifest')}")
    return 0


def _cmd_embedded_textures(args) -> int:
    """List/extract textures from embedded RAGE dictionaries (txd resources)."""
    from . import embedded as embedded_mod

    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    if args.pool:
        eprint("--pool is for TTPF pools; omit it with --embedded")
        return 1
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    name_re = re.compile(args.name) if args.name else None
    limit = None if args.full else args.limit * 1024 * 1024
    max_n = None if args.all else args.max
    rows: list[list[str]] = []
    records: list[dict] = []
    resources = textures = exported = 0
    skipped: dict[str, int] = {}
    done = False
    png_failed = False
    for path in targets:
        for resource in embedded_mod.iter_resources(path, limit=limit):
            resources += 1
            for tex in resource.textures:
                if name_re and not (name_re.search(tex.name)
                                    or name_re.search(resource.name)):
                    continue
                if tex.width * tex.height < args.min_size:
                    continue
                textures += 1
                if max_n is not None and (exported if args.out else len(rows)) >= max_n:
                    done = True
                    break
                if args.out:
                    try:
                        blob, mip_count = embedded_mod.dds_mips(tex, resource.gfx)
                    except ValueError as exc:
                        reason = str(exc)
                        skipped[reason] = skipped.get(reason, 0) + 1
                        png_failed = png_failed or args._png_selection_requested
                        continue
                    safe = "".join(c if c.isalnum() or c in "_-." else "_"
                                   for c in f"{resource.name}_{tex.name or 'tex'}")
                    dest = os.path.join(
                        args.out, f"{safe[:120]}_{resource.offset:09x}_{tex.struct_off:03x}.dds")
                    with open(dest, "wb") as out:
                        out.write(blob)
                    exported += 1
                    record = tex.as_dict()
                    record.update({"archive": resource.archive,
                                   "resource": resource.name,
                                   "resource_offset": resource.offset,
                                   "file": dest, "bytes": len(blob),
                                   "exported_mips": mip_count})
                    if args.png:
                        from .bc import decode_rgba
                        from .bc.bcn import preview_policy
                        from . import png as png_mod
                        # DDS retains the complete shape even when a preview
                        # selects one array layer or one volume Z plane.
                        try:
                            linear, png_width, png_height, selection = embedded_mod.preview_subresource(
                                tex, resource.gfx, mip=args.png_mip,
                                slice_index=args.png_slice, z_index=args.png_z)
                            rgba = decode_rgba(tex.dxgi_format, linear, png_width, png_height)
                            if rgba is None:
                                record["png_skip_reason"] = "unsupported PNG preview format"
                            else:
                                suffix = (f"_m{args.png_mip}_s{args.png_slice}_z{args.png_z}"
                                          if any((args.png_mip, args.png_slice, args.png_z)) else "")
                                png_dest = os.path.splitext(dest)[0] + suffix + ".png"
                                png_mod.write_png(png_dest, png_width, png_height, rgba)
                                record["png"] = png_dest
                                record["png_z_index" if tex.shape == "3d" else "png_slice_index"] = 0
                                record.update(selection)
                                policy = preview_policy(tex.dxgi_format)
                                if policy is not None:
                                    record["png_conversion"] = policy
                        except ValueError as exc:
                            record["png_skip_reason"] = str(exc)
                        if args._png_selection_requested and record.get("png_skip_reason"):
                            png_failed = True
                            reason = "PNG: " + record["png_skip_reason"]
                            skipped[reason] = skipped.get(reason, 0) + 1
                    records.append(record)
                else:
                    try:
                        embedded_mod.exportable_mips(tex)
                        status = "ok"
                    except ValueError as exc:
                        status = str(exc)
                    rows.append([os.path.basename(path)[:20], resource.name[:30],
                                 tex.name[:30], (f"{tex.width}x{tex.height}" if tex.depth == 1
                                                else f"{tex.width}x{tex.height}x{tex.depth} {tex.shape}"),
                                 embedded_mod.format_name(tex.dxgi_format),
                                 str(tex.mips), status])
            if done:
                break
        if done:
            break

    if args.out:
        manifest = os.path.join(args.out, "embedded.json")
        with open(manifest, "w", encoding="utf-8") as out:
            json.dump(records, out, indent=1)
        if args.json:
            print(json.dumps({"resources": resources, "textures": textures,
                              "exported": exported, "skipped": skipped,
                              "manifest": manifest}, indent=2))
            return int(png_failed)
        print(f"resources {resources:,}   textures {textures:,}   exported {exported:,}"
              f" DDS files to {args.out}")
        for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1]):
            print(f"  skipped {count:>6,}  {reason}")
        print(f"manifest: {manifest}")
        return int(png_failed)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no matching embedded textures")
        return 0
    print(table(rows, ["archive", "dictionary", "texture", "size", "format",
                       "mips", "status"], align="lllllrr"))
    print(f"\n{resources:,} resource(s), {textures:,} texture(s) matched; "
          f"pass --out DIR to export DDS files")
    return 0


def _cmd_textures_via_backend(args) -> int:
    """Full-format PNG previews for TTPF pools through SixNG's `ttpf`."""
    from . import models as models_mod

    if not args.out:
        eprint("--out DIR is required for backend export")
        return 1
    backend = models_mod.find_backend(args.backend)
    if not backend:
        eprint("no sixng backend found; build it (see README) or use the native path")
        return 2
    pools = _find_pools(args.root, args.pool)
    if not pools:
        eprint("no .ttpf pools found")
        return 1
    os.makedirs(args.out, exist_ok=True)
    max_n = None if args.all else args.max
    total = 0
    exported = 0
    written: list[str] = []
    for pool in pools:
        if max_n is not None and total >= max_n:
            break
        index = rds5.read_index(pool)
        selected = []
        for tex in index.textures:
            if args.hash_prefix and not f"{tex.hash:016x}".startswith(args.hash_prefix.lower()):
                continue
            if tex.width * tex.height < args.min_size:
                continue
            selected.append(tex)
        if not selected:
            continue
        store = os.path.relpath(pool, args.root)
        command = ["ttpf", store, "--out", os.path.abspath(args.out)]
        if args.hash_prefix:
            for tex in selected[:max_n - total if max_n is not None else None]:
                command += ["--hash", f"{tex.hash:016x}"]
            remaining = max_n - total if max_n is not None else len(selected)
            expected = min(len(selected), remaining)
        else:
            remaining = max_n - total if max_n is not None else len(selected)
            expected = min(len(selected), remaining)
            command += ["--first", str(expected)]
        try:
            payload = models_mod.run_any(backend, args.root,
                                         os.path.abspath(args.work), command)
        except RuntimeError as exc:
            eprint(str(exc))
            return 1
        items = payload if isinstance(payload, list) else payload.get("items", [])
        for item in items:
            png = item.get("png") if isinstance(item, dict) else None
            if png:
                written.append(png)
        exported += len(items)
        total += expected
    if args.json:
        print(json.dumps({"exported": exported, "png": written}, indent=2))
        return 0
    print(f"backend exported {exported:,} TTPF PNG previews to {args.out}")
    for path in written[:8]:
        print(f"  {path}")
    if len(written) > 8:
        print(f"  ... {len(written) - 8} more")
    return 0


def cmd_textures(args) -> int:
    """List TTPF textures, or export them as DDS files."""
    from . import texture as texture_mod

    selections = (args.png_mip, args.png_slice, args.png_z)
    args._png_selection_requested = any(value is not None for value in selections)
    if any(value is not None and value < 0 for value in selections):
        eprint("PNG mip, slice and Z indices must be nonnegative")
        return 1
    if args._png_selection_requested and (not args.png or not args.out):
        eprint("PNG subresource selectors require --png and --out")
        return 1
    if args.png_slice is not None and args.png_z is not None:
        eprint("--png-slice and --png-z select different texture shapes; choose one")
        return 1
    if args._png_selection_requested and args.via != "native":
        eprint("PNG subresource selectors require --via native")
        return 1
    args.png_mip, args.png_slice, args.png_z = (value or 0 for value in selections)

    if getattr(args, "embedded", False):
        if args.via == "sixng":
            return _cmd_embedded_via_backend(args)
        return _cmd_embedded_textures(args)
    if args.via == "sixng":
        return _cmd_textures_via_backend(args)

    pools = _find_pools(args.root, args.pool)
    if not pools:
        eprint("no .ttpf pools found under <root>/data/ttdb")
        return 1
    from . import names as names_mod
    names_index = None
    if args.names and os.path.isfile(args.names):
        try:
            names_index = names_mod.load(args.names)
        except (OSError, ValueError) as exc:
            eprint(f"cannot read names dictionary {args.names}: {exc}")
    if args.out:
        os.makedirs(args.out, exist_ok=True)
    limit = None if args.all else args.max
    seen = exported = 0
    png_failed = False
    skipped: dict[str, int] = {}
    records: list[dict] = []
    rows: list[list[str]] = []
    for pool in pools:
        try:
            index = rds5.read_index(pool)
        except (OSError, ValueError) as exc:
            eprint(f"skip {pool}: {exc}")
            continue
        starts = texture_mod.chunk_starts(index)
        fh = open(pool, "rb") if args.out else None
        try:
            for tex in index.textures:
                if args.hash_prefix and not tex.name.startswith(args.hash_prefix.lower()):
                    continue
                if tex.width * tex.height < args.min_size:
                    continue
                seen += 1
                label = ""
                if names_index is not None:
                    found = names_mod.lookup64(names_index, tex.hash)
                    label = found[0][0] if found else ""
                if getattr(tex, "dimension", 1) == 3:
                    from . import volume as volume_mod
                    layout = volume_mod.layout_for(tex)
                else:
                    layout = texture_mod.layout_for(tex)
                missing = uncovered = 0
                if layout is not None:
                    __covered, missing, uncovered = texture_mod.coverage(
                        index, tex.virtual_offset, layout.total, starts)
                reason = None
                if layout is None:
                    reason = "unsupported tile mode or element size"
                elif layout.total > texture_mod.MAX_TEXTURE_BYTES:
                    reason = "larger than 64 MiB"
                elif missing:
                    reason = f"{missing:,} B in BCPack chunks"
                elif uncovered:
                    reason = f"{uncovered:,} B uncovered"
                if args.out:
                    if reason is None or (args.bcpack and "BCPack" in (reason or "")):
                        record = texture_mod.export_texture(
                            pool, index, tex, args.out, fh=fh, starts=starts,
                            png=args.png, decode_bcpack=args.bcpack,
                            png_mip=args.png_mip, png_slice=args.png_slice, png_z=args.png_z)
                    else:
                        record = {"file": None, "hash": f"{tex.hash:016x}",
                                  "skipped": reason}
                    # A native refusal can still use the explicitly selected
                    # external exporter. Both flags may be used together.
                    native_reason = record.get("skipped")
                    helper = args.bcpack_helper
                    if helper and "BCPack" in (native_reason or ""):
                        import subprocess
                        dest = os.path.join(args.out, f"{tex.hash:016x}.dds")
                        try:
                            proc = subprocess.run(
                                [sys.executable, "-I", helper, "export", pool,
                                 str(tex.index), dest, "--force"],
                                capture_output=True, text=True, timeout=120)
                        except (OSError, subprocess.TimeoutExpired) as exc:
                            proc = None
                            eprint(f"bcpack {tex.hash:016x}: {exc}")
                        if proc is not None and proc.returncode == 0 and os.path.isfile(dest):
                            record.update({"file": dest, "width": tex.width,
                                           "height": tex.height,
                                           "format": texture_mod.format_name(tex.dxgi_format),
                                           "mips": tex.mips, "slices": tex.slices,
                                           "bytes": os.path.getsize(dest), "skipped": None,
                                           "bcpack": True, "native_skipped": native_reason})
                    if label:
                        record["name"] = label
                    if args._png_selection_requested and not record.get("png"):
                        png_failed = True
                        if record.get("file") and not record.get("png_skipped"):
                            record["png_skipped"] = "native PNG selection unavailable after external DDS fallback"
                        if record.get("png_skipped"):
                            reason = "PNG: " + record["png_skipped"]
                            skipped[reason] = skipped.get(reason, 0) + 1
                    exported += 1 if record.get("file") else 0
                    if record.get("skipped"):
                        key = _skip_category(record["skipped"])
                        skipped[key] = skipped.get(key, 0) + 1
                    records.append(record)
                else:
                    row = [
                        os.path.basename(pool)[:30], f"{tex.hash:016x}",
                        f"{tex.width}x{tex.height}", texture_mod.format_name(tex.dxgi_format),
                        str(tex.mips), str(tex.slices), f"0x{tex.virtual_offset:x}",
                        reason or "decodable",
                    ]
                    if names_index is not None:
                        row.insert(2, label)
                    rows.append(row)
                if limit is not None and seen >= limit:
                    break
        finally:
            if fh:
                fh.close()
        if limit is not None and seen >= limit:
            break

    if args.out:
        manifest = os.path.join(args.out, "textures.json")
        with open(manifest, "w", encoding="utf-8") as out:
            json.dump(records, out, indent=1)
        if args.json:
            print(json.dumps({"scanned": seen, "exported": exported,
                              "skipped": skipped, "manifest": manifest}, indent=2))
            return int(png_failed)
        pngs = sum(1 for record in records if record.get("png"))
        print(f"scanned {seen:,} textures; exported {exported:,} DDS files"
              + (f" and {pngs:,} PNG previews" if args.png else "")
              + f" to {args.out}")
        if args.png and not args._png_selection_requested:
            for record in records:
                if record.get("png_skipped"):
                    key = _skip_category(record["png_skipped"])
                    skipped[key] = skipped.get(key, 0) + 1
        for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1]):
            print(f"  skipped {count:>7,}  {reason}")
        print(f"manifest: {manifest}")
        return int(png_failed)

    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no matching textures")
        return 0
    headers = ["pool", "hash", "size", "format", "mips", "slices",
               "virtual", "status"]
    if names_index is not None:
        headers.insert(2, "name")
    print(table(rows, headers, align="lllrrlll"))
    print(f"\n{len(rows):,} texture(s) shown; pass --out DIR to export DDS files")
    return 0


def cmd_names(args) -> int:
    """Build or query the local joaat name dictionary."""
    from . import names as names_mod

    if args.action == "build":
        dictionary = names_mod.build(args.root, paths_file=args.paths,
                                     include_shaders=not args.no_shaders)
        out = os.path.abspath(args.out)
        parent = os.path.dirname(out)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(out, "w", encoding="utf-8") as handle:
            json.dump(dictionary, handle, indent=1)
        if args.json:
            print(json.dumps({"out": out,
                              "hashes": len(dictionary["hashes"]),
                              "case_sensitive": len(dictionary["exact"]),
                              "identifiers": dictionary["counts"]}, indent=2))
            return 0
        print(f"wrote {out}")
        print(f"  hashes: {len(dictionary['hashes']):,}  "
              f"case-sensitive: {len(dictionary['exact']):,}  "
              f"64-bit: {len(dictionary.get('hashes64', {})):,}")
        for source, count in sorted(dictionary["counts"].items()):
            print(f"  {source}: {count:,} identifiers")
        return 0

    if not args.hash:
        eprint("names lookup needs a hash")
        return 1
    try:
        dictionary = names_mod.load(args.index)
    except (OSError, ValueError) as exc:
        eprint(f"cannot read {args.index}: {exc}")
        return 1
    found = names_mod.lookup(dictionary, args.hash)
    if args.json:
        print(json.dumps({"hash": args.hash, "names": [
            {"name": name, "source": source} for name, source in found]}, indent=2))
        return 0
    if not found:
        print(f"no name for {args.hash}")
        return 0
    for name, source in found:
        print(f"{name}  [{source}]")
    return 0


def cmd_world(args) -> int:
    """Extract world/map data through the optional SixNG backend."""
    from . import models as models_mod
    from . import world as world_mod

    backend = models_mod.find_backend(args.backend)
    if not backend:
        eprint("no sixng backend found; build it (see README) or pass --backend")
        return 2
    filters = {"name": args.name, "exclude_name": args.exclude_name,
               "min_size": args.min_size, "limit": args.limit,
               "bbox": args.bbox}
    options = {"dump": args.dump, "roads_only": args.roads_only,
               "batches": args.batches, "batches_only": args.batches_only}
    try:
        archive_label, result = world_mod.run(
            backend, args.root, os.path.abspath(args.work), args.kind,
            args.archive, args.out, filters=filters, options=options,
            navmeshes=args.navmeshes)
    except (RuntimeError, OSError) as exc:
        eprint(str(exc))
        return 1
    if args.json:
        print(json.dumps({"kind": args.kind, "archive": archive_label,
                          "result": result}, indent=2))
        return 0
    stats = result.get("stats") if isinstance(result.get("stats"), dict) else {}
    destination = (result.get("index") or result.get("file")
                   or stats.get("out") or args.out)
    print(f"{args.kind}: {archive_label} -> {destination}")
    for key, value in {**result, **stats}.items():
        if key in ("ok", "archive", "seconds", "stats", "out", "index", "file"):
            continue
        if isinstance(value, (int, float, str, bool)):
            print(f"  {key}: {value}")
    if "seconds" in result:
        print(f"  seconds: {result['seconds']:.2f}")
    files = sum(len(names) for _root, _dirs, names in os.walk(args.out))
    print(f"  files written: {files:,}")
    if args.kind == "all":
        print("  steps: placements, batches, collision, navmesh, paths, lights, "
              "interiors, surfaces")
    return 0


def cmd_selftest(args) -> int:
    """Parser self-checks against synthetic structures -- no game data needed."""
    import struct as _s
    import tempfile

    from . import gfx10 as _gfx10
    from . import psin as _psin
    from . import rds5 as _rds5
    from . import shaders as _shaders
    from . import audio as _audio
    from .bc import bcn as _bcn
    from . import embedded as _embedded
    from . import names as _names
    from . import anim as _anim_mod
    from . import png as _png
    from . import structured as _structured
    from . import texture as _texture

    failures = []

    def check(name, cond):
        print(("  ok   " if cond else "  FAIL ") + name)
        if not cond:
            failures.append(name)

    # Bink2 header: 2560x1440@30, 115 frames, 3.8 MB
    bink = (b"KB2n" + _s.pack("<7I", 3_838_204, 115, 101_724, 115, 2560, 1440, 30) + b"\x00" * 16)
    meta = media.validate_bink2(bink)
    check("bink2 validates", meta is not None and meta["width"] == 2560 and meta["fps"] == 30)
    check("bink2 rejects noise", media.validate_bink2(b"KB2n" + b"\xff" * 44) is None)

    # AWC, flat variant (feature word 0xFF02): two streams, one format and one data tag.
    flat = bytearray(136)
    _s.pack_into("<4sIII", flat, 0, b"ADAT", 0xFF020001, 2, 40)
    _s.pack_into("<I", flat, 16, (1 << 29) | 0x100)
    _s.pack_into("<I", flat, 20, (1 << 29) | 0x200)
    _s.pack_into("<Q", flat, 24, (0x76 << 56) | (32 << 28) | 40)
    _s.pack_into("<Q", flat, 32, (0x55 << 56) | (64 << 28) | 72)
    _s.pack_into("<I", flat, 40, 48000)      # samples
    _s.pack_into("<H", flat, 48, 48000)      # sample rate
    flat[68] = 0x0B                          # codec: Opus
    flat[69] = 1                             # channels
    meta = media.validate_awc(bytes(flat))
    check("awc validates", meta is not None and meta["streams"] == 2)
    check("awc stream metadata",
          meta is not None and meta["stream_list"][0]["codec_name"] == "opus"
          and meta["stream_list"][0]["sample_rate"] == 48000
          and abs(meta["stream_list"][0]["duration"] - 1.0) < 0.001)
    check("awc flags split from version",
          meta is not None and meta["version"] == 1 and meta["flags"] == "0xFF02")
    check("awc tag table yields exact length",
          meta is not None and meta["size"] == 136 and meta["exact_length"])
    check("awc rejects forbidden feature bits",
          media.validate_awc(bytes(flat[:4]) + _s.pack("<I", 0xFF020001 | 0x00080000) +
                             bytes(flat[8:])) is None)

    # AWC, indexed variant (feature word 0xFF21): index table + extra table + one data tag.
    indexed = bytearray(54)
    _s.pack_into("<4sIII", indexed, 0, b"ADAT", 0xFF210001, 1, 38)
    _s.pack_into("<H", indexed, 16, 0)
    _s.pack_into("<2I", indexed, 18, 0, 0)
    _s.pack_into("<I", indexed, 26, (1 << 29) | 0x77)
    _s.pack_into("<Q", indexed, 30, (0x55 << 56) | (16 << 28) | 38)
    meta = media.validate_awc(bytes(indexed))
    check("awc 0xFF21 tables",
          meta is not None and meta["has_index_table"] and meta["has_extra_table"]
          and meta["size"] == 54)

    # RPF9 header: index size f1 drives the aligned data offset.
    hdr = _s.pack("<8I", rpf.RPF9_MAGIC, 864, 832, 64, 0x24E63799, 0xB766DF72,
                  rpf.BUILD_STAMP, 336)
    parsed = rpf.Header(*_s.unpack("<8I", hdr), 0)
    check("rpf9 header parses", parsed.is_rpf9 and parsed.stamp_ok)
    check("rpf9 index size and data offset",
          parsed.index_size == 864 and parsed.data_offset == 864)
    check("constant block is 32 bytes", len(rpf.CONSTANT_TOC_BLOCK) == 32)
    check("human() scales", inventory.__name__ and True)

    # PSIN dialect A: seven tagged sections tiling the blob.
    parts = [b"PSIN", _s.pack(">I", 16), b"\x00" * 8]
    for tag in ("LSCH", "LENM", "LSNS", "LGID", "LRSC"):
        parts += [tag.encode("ascii"), _s.pack(">I", 8)]
    total = sum(len(p) for p in parts) + 20
    parts += [b"CHKS", _s.pack(">I", 20), _s.pack(">I", total),
              _s.pack(">I", 0x12345678), _s.pack(">I", 5)]
    container = b"".join(parts)
    parsed = _psin.parse(container)
    check("psin tagged sections parse",
          parsed is not None and parsed.kind == "container"
          and len(parsed.sections) == 7)
    check("psin checksum and platform exposed",
          parsed is not None and parsed.stored_checksum == 0x12345678
          and parsed.platform_tag == 5)
    check("psin section body attached", parsed is not None and parsed.body is not None)

    # PSIN body: two exact blocks, AA-padded table and PP terminator.
    page = (b"PSIN" + _s.pack(">I", 80)
            + _s.pack("<2I", 0x101, 16) + b"\xaa" * 8
            + _s.pack("<2I", 0x60596ACC, 16) + b"\xaa" * 8
            + b"\x70" * 8 + b"\x11" * 32)
    parsed = _psin.parse_page(page)
    check("psin page parses header", parsed is not None and parsed.declared_size == 80)
    check("psin page finds entries", parsed is not None and len(parsed.entries) == 2)
    check("psin page 16-byte stride", parsed is not None and parsed.entry_stride == 16
          and parsed.record_count == 2 and parsed.has_terminator)
    check("psin page includes first block type", parsed is not None
          and parsed.field_a_kind == "first-block-type"
          and parsed.entries == [(0x101, 16), (0x60596ACC, 16)])
    check("psin page locates payload", parsed is not None and parsed.payload_offset == 48
          and parsed.payload_size == 32 and parsed.status == "complete" and parsed.confident)
    check("psin rejects non-psin", _psin.parse(b"NOPE" + b"\x00" * 64) is None)
    check("psin exact body is not a fragment", _psin.parse_fragment(page) is None)
    partial_body = _psin.parse_fragment(page[:23]).body
    check("psin partial table leaves payload bounds unknown",
          partial_body.status == "partial" and partial_body.payload_offset is None
          and not partial_body.confident)
    bad_body = bytearray(page)
    _s.pack_into("<I", bad_body, 12, 15)
    check("psin nonzero block padding stays unresolved",
          _psin.parse_body(bytes(bad_body)).status == "unresolved")

    # RDS5/TTPF: one stored chunk plus the sentinel, embedded ETPF dictionary.
    etpf_at = 256
    virtual = 8192
    padded_metadata = 4096
    source0 = etpf_at + padded_metadata
    size0 = 4096
    file_size = source0 + size0
    pool = bytearray(file_size)
    _s.pack_into("<4sI", pool, 0, b"RDS5", 3)
    _s.pack_into("<Q", pool, 8, (22 << 56) | virtual)
    _s.pack_into("<I", pool, 16, 1)
    _s.pack_into("<I", pool, 20, 0)
    _s.pack_into("<Q", pool, 24, (source0 // 256) | (1 << 30))
    _s.pack_into("<Q", pool, 32, (file_size // 256) | ((virtual // 4096) << 30))
    _s.pack_into("<4sIII", pool, etpf_at, b"ETPF", _rds5.ETPF_VERSION, 1, 16)
    # One valid 4x4 BC1 descriptor: packed_mips=0, non_tail=0, dimension=2D,
    # SW_4KB_S tile mode, first page 2.
    _d0 = 3 | (3 << 14)
    _d1 = (71 << 3) | (1 << 21) | (1 << 24)
    _s.pack_into("<IIQ", pool, etpf_at + 16, _d0, _d1, 2)
    _s.pack_into("<Q", pool, etpf_at + 32, 0x123456789ABCDEF0)
    with tempfile.NamedTemporaryFile(suffix=".ttpf", delete=False) as fh:
        fh.write(pool)
        pool_path = fh.name
    try:
        index = _rds5.read_index(pool_path)
        check("rds5 pool validates", index.validated)
        check("rds5 chunk decoded",
              len(index.chunks) == 1 and index.chunks[0].size == size0
              and index.chunks[0].kind == "stored")
        check("rds5 texture dictionary found",
              index.texture_count == 1 and index.etpf_version == _rds5.ETPF_VERSION)
    finally:
        os.unlink(pool_path)

    # Gfx10 layout: reference spacing cases from the tiling implementation.
    check("gfx10 4 KiB tail layout",
          _gfx10.Layout.new("S4K", 16, 16, 6, 8).total == 4096)
    layout = _gfx10.Layout.new("S4K", 32, 32, 7, 8)
    check("gfx10 mip offsets",
          layout.total == 12288 and layout.mips[0].offset == 4096
          and layout.mips[1].tail == (16, 0))
    array = _gfx10.Layout.new("D64K", 64, 64, 9, 16).with_slices(8)
    cube = _gfx10.Layout.new("S4K", 32, 32, 6, 16)
    check("gfx10 cube base", cube is not None
          and cube.with_cube_copies(6, 3, None) is not None
          and cube.base == 18 * 4096 and cube.total == 54 * 4096)
    cube2 = _gfx10.Layout.new("S4K", 128, 128, 7, 8)
    check("gfx10 cube total", cube2 is not None
          and cube2.with_cube_copies(6, 4, None) is not None
          and cube2.base == 104 * 4096
          and cube2.total == (104 + 258) * 4096)
    s4k4 = _gfx10.Layout.new("S4K", 32, 32, 1, 4)
    d64k4 = _gfx10.Layout.new("D64K", 128, 128, 1, 4)
    check("gfx10 S4K 4-byte block", s4k4 is not None and s4k4.block_w == 32
          and s4k4.block_h == 32 and s4k4.bpe == 4)
    check("gfx10 D64K 4-byte block", d64k4 is not None and d64k4.block_w == 128
          and d64k4.block_h == 128 and d64k4.bpe == 4)
    check("gfx10 array slicing",
          array.total == 1 << 20 and array.mip_span(0) == (8 * 65536, 9 * 65536)
          and array.addr(0, 3, 0, 0) == 11 * 65536)

    # DDS writer: a 4x4 BC1 texture lives in one 4 KiB tail block.
    layout = _gfx10.Layout.new("S4K", 1, 1, 1, 8)
    texture = _rds5.TtpTexture(0, 0x1234, 0, 0, 1, 4, 4, 1, 71, 2, 1)
    block = bytes(range(8))
    tiled = bytearray(layout.total)
    at = layout.addr(0, 0, 0, 0)
    tiled[at:at + 8] = block
    dds = _texture.dds_bytes(texture, layout, bytes(tiled))
    check("dds header", dds[:4] == b"DDS "
          and _s.unpack_from("<I", dds, 12)[0] == 4
          and _s.unpack_from("<I", dds, 16)[0] == 4)
    check("dds payload", len(dds) == _texture.DDS_HEADER_BYTES + 8
          and dds[_texture.DDS_HEADER_BYTES:] == block)

    # Authored public BCn layouts and signed-component display conventions.
    bc2 = b"\xff" * 8 + _s.pack("<HHI", 0xf800, 0, 0)
    check("BC2 alpha before colour", _bcn.decode_rgba(74, bc2, 4, 4)
          == bytes((255, 0, 0, 255)) * 16)
    check("BC4 signed minimum", _bcn.decode_rgba(81, b"\x80\x7f" + b"\0" * 6, 4, 4)
          == bytes((0, 0, 0, 255)) * 16)
    bc5 = b"\x7f\x81" + b"\0" * 6 + b"\x80\x7f" + b"\0" * 6
    check("BC5 signed channels", _bcn.decode_rgba(84, bc5, 4, 4)
          == bytes((255, 0, 0, 255)) * 16)
    check("signed 8-bit preview mapping",
          _bcn.decode_rgba(31, bytes((128, 129, 0, 127)), 1, 1) == bytes((0, 0, 128, 255))
          and _bcn.decode_rgba(32, bytes((128, 129, 0, 127)), 1, 1) == bytes((0, 1, 128, 255)))
    check("16-bit and packed UNORM previews preserve normalized component order",
          _bcn.decode_rgba(11, _s.pack('<4H', 0, 32768, 65535, 65535), 1, 1)
          == bytes((0, 128, 255, 255))
          and _bcn.decode_rgba(24, _s.pack('<I', 1023 | (512 << 20) | (2 << 30)), 1, 1)
          == bytes((255, 0, 128, 170)))
    check("half-float previews apply explicit clipping and nonfinite display rules",
          _bcn.decode_rgba(10, _s.pack('<4H', 0x7e00, 0xfc00, 0x7c00, 0x3800), 1, 1)
          == bytes((0, 0, 255, 128)))
    check("BGRX previews force opaque alpha and BGRA short reads refuse",
          all(_bcn.decode_rgba(fmt, bytes((1, 2, 3, 0)), 1, 1) == bytes((3, 2, 1, 255))
              for fmt in (88, 93))
          and _bcn.decode_rgba(87, bytes(3), 1, 1) is None)

    # Shader wrapper: name prefix, sizes, magic, raw deflate DXBC payload.
    dxbc = bytearray(64)
    dxbc[:4] = b"DXBC"
    _s.pack_into("<I", dxbc, 20, 1)
    _s.pack_into("<I", dxbc, 24, 64)
    _s.pack_into("<I", dxbc, 28, 1)
    _s.pack_into("<I", dxbc, 32, 36)
    dxbc[36:40] = b"SHDR"
    _s.pack_into("<I", dxbc, 40, 20)
    name = b"VS_Test_abcd_Wrapped"
    compressor = __import__("zlib").compressobj(9, __import__("zlib").DEFLATED, -15)
    raw = compressor.compress(bytes(dxbc)) + compressor.flush()
    stored = 12 + len(raw)
    head = (bytes([len(name) + 1]) + name + b"\x00" + bytes([len(name)])
            + _s.pack("<I", stored) + _shaders.MAGIC_BYTES
            + _s.pack("<II", stored, len(dxbc)))
    blob = b"\x00" * 64 + head + raw
    with tempfile.NamedTemporaryFile(suffix=".rpf", delete=False) as fh:
        fh.write(blob)
        shader_path = fh.name
    try:
        hits = list(_shaders.scan(shader_path))
        check("shader wrapper found", len(hits) == 1)
        check("shader decoded", hits and hits[0].name == name.decode()
              and hits[0].data == bytes(dxbc) and hits[0].decoded == len(dxbc))
    finally:
        os.unlink(shader_path)
    check("dxbc rejects noise", not _shaders.validate_dxbc(b"DXBC" + b"\x00" * 60))

    def shader_container(*parts):
        data = bytearray(32 + 4*len(parts))
        data[:4] = b'DXBC'
        _s.pack_into('<I', data, 20, 1)
        _s.pack_into('<I', data, 28, len(parts))
        for index, (tag, body) in enumerate(parts):
            data.extend(bytes((-len(data)) % 4))
            _s.pack_into('<I', data, 32+4*index, len(data))
            data.extend(tag + _s.pack('<I', len(body)) + body)
        _s.pack_into('<I', data, 24, len(data))
        return bytes(data)

    public_program = shader_container((b'SHDR', _s.pack('<II', 0x10050, 2)),
                                      (b'TEST', b'raw!'))
    metadata = _shaders.metadata(public_program)
    check("shader metadata reads public stage/model without decoding instructions",
          metadata['status'] == 'complete'
          and metadata['programs'][0]['stage'] == 'vertex'
          and metadata['programs'][0]['shader_model_major'] == 5
          and metadata['chunks'][1]['status'] == 'opaque')
    signature = (_s.pack('<II', 1, 8)
                 + _s.pack('<6IBBHI', 0, 40, 0, 0, 3, 0, 15, 15, 0, 0)
                 + b'POSITION\0' + bytes(23))
    metadata = _shaders.metadata(shader_container((b'ISG1', signature)))
    check("shader metadata retains signature names, registers and masks",
          metadata['status'] == 'complete'
          and metadata['signatures'][0]['parameters'][0]['semantic_name'] == 'POSITION'
          and metadata['signatures'][0]['parameters'][0]['mask'] == 15)
    invalid_signature = bytearray(signature)
    _s.pack_into('<I', invalid_signature, 12, 8)
    metadata = _shaders.metadata(shader_container((b'ISG1', invalid_signature)))
    check("shader metadata refuses a name pointer into parameter storage",
          metadata['status'] == 'partial' and not metadata['signatures']
          and bool(metadata['reasons']))
    metadata = _shaders.metadata(public_program, max_records=1)
    check("shader metadata budgets refuse atomically",
          metadata['status'] == 'unresolved'
          and not metadata['chunks'] and not metadata['programs'] and not metadata['signatures'])

    # Structured recovery: an XML document split over a 64 KiB page and a tail.
    import zlib as _zl
    prefix = b'<?xml version="1.0"?><root>'
    block1 = prefix + b" " * (65536 - len(prefix))
    block2 = b"<item>1</item></root>"
    z1, z2 = _zl.compress(block1), _zl.compress(block2)
    padding = (-len(z1)) % 16
    blob = z1 + b"\x00" * padding + z2
    with tempfile.NamedTemporaryFile(suffix=".rpf", delete=False) as fh:
        fh.write(blob)
        structured_path = fh.name
    try:
        items = list(_structured.recover(structured_path, limit=1 << 20, start=0))
        check("structured joins split XML",
              len(items) == 1 and items[0].kind == "xml" and items[0].root == "root")
        check("structured payload complete",
              items and items[0].blocks == 2 and items[0].data == block1 + block2)
    finally:
        os.unlink(structured_path)

    # Embedded txd: one system page with one descriptor, one graphics page.
    name_off = 0x80
    system = bytearray(0x98)
    _s.pack_into("<I", system, 0x40 + 8, 512)  # 4096 bytes / BC1 element
    _s.pack_into("<H", system, 0x40 + 0x0E, 8)
    _s.pack_into("<Q", system, 0x40 + 0x18, 0x60000000)
    _s.pack_into("<H", system, 0x40 + 0x38, 4)
    _s.pack_into("<H", system, 0x40 + 0x3A, 4)
    _s.pack_into("<H", system, 0x40 + 0x3C, 1)
    system[0x40 + 0x3E] = 1
    system[0x40 + 0x3F] = 71
    _s.pack_into("<H", system, 0x40 + 0x40, 5)  # public ADDR_SW_4KB_S
    system[0x40 + 0x42] = 1
    _s.pack_into("<Q", system, 0x40 + 0x30, 0x50000000 | name_off)
    system[name_off + 8:name_off + 8 + 8] = b"tex_test"
    graphics = bytes(range(256)) * 16
    zs = _zl.compress(bytes(system))
    zg = _zl.compress(graphics)
    pad = (-len(zs)) % 16
    txd_blob = zs + b"\x00" * pad + zg
    with tempfile.NamedTemporaryFile(suffix=".rpf", delete=False) as fh:
        fh.write(txd_blob)
        txd_path = fh.name
    try:
        resources = list(_embedded.iter_resources(txd_path, limit=1 << 20, start=0))
        check("embedded txd resource found",
              len(resources) == 1 and len(resources[0].textures) == 1)
        tex = resources[0].textures[0] if resources else None
        check("embedded texture descriptor",
              tex is not None and tex.name == "tex_test" and tex.width == 4
              and tex.dxgi_format == 71)
        linear = _embedded.mip0(tex, resources[0].gfx)
        blob = _embedded.dds_bytes(tex, linear)
        check("embedded dds", len(blob) == _texture.DDS_HEADER_BYTES + 8
              and blob[:4] == b"DDS " and _s.unpack_from("<I", blob, 128)[0] == 71)
    finally:
        os.unlink(txd_path)

    # Authored BC3 tail slot addresses, independent of Layout's placement.
    tail_tex = _embedded.EmbeddedTexture("tail_test", 32, 32, 1, 6, 77,
                                         0, 256, 0)
    tail_gfx = bytearray(4096)
    for m, at in enumerate((0x800, 0x600, 0x500, 0x400, 0x300, 0x200)):
        tail_gfx[at:at + 16] = bytes([m + 1]) * 16
    tail_dds, tail_count = _embedded.dds_mips(tail_tex, bytes(tail_gfx))
    check("embedded full mip chain",
          tail_count == 6 and len(tail_dds) == 148 + (64 + 16 + 4 + 1 + 1 + 1) * 16)
    check("embedded tail slot addresses",
          all(_embedded.mip_linear(tail_tex, bytes(tail_gfx), m)[:16]
              == bytes([m + 1]) * 16 for m in range(6)))
    try:
        _embedded.dds_mips(tail_tex, bytes(tail_gfx[:-1]))
        tail_rejected = False
    except ValueError:
        tail_rejected = True
    check("embedded truncation refused", tail_rejected)

    array_tex = _embedded.EmbeddedTexture("array_test", 32, 32, 2, 1, 77,
                                          0, 512, 0, shape_tag=1)
    array_gfx = bytes([17]) * 4096 + bytes([34]) * 4096
    array_dds = _embedded.dds_mip0(array_tex, array_gfx)
    check("embedded array DDS retains every layer",
          _s.unpack_from("<I", array_dds, 140)[0] == 2
          and array_dds[148:] == bytes([17]) * 1024 + bytes([34]) * 1024)
    check("embedded array preview selects one explicit layer",
          _embedded.mip0(array_tex, array_gfx, slice_index=1) == bytes([34]) * 1024)
    try:
        _embedded.dds_bytes(array_tex, bytes(1024))
        partial_array_refused = False
    except ValueError:
        partial_array_refused = True
    check("embedded array cannot be mislabeled as one 2D slice", partial_array_refused)

    volume_tex = _embedded.EmbeddedTexture("volume_test", 2, 2, 2, 1, 28,
                                           0, 1024, 0, shape_tag=3)
    volume_gfx, volume_expected = bytearray(4096), bytearray()
    for z in range(2):
        for y in range(2):
            for x in range(2):
                pixel = bytes((x * 50, y * 60, z * 70, 255))
                at = 4 * x + 32 * y + 16 * z
                volume_gfx[at:at + 4] = pixel
                volume_expected.extend(pixel)
    volume_dds, volume_mips = _embedded.dds_mips(volume_tex, bytes(volume_gfx))
    check("embedded volume DDS retains all Z planes with 3D header",
          volume_mips == 1 and volume_dds[148:] == bytes(volume_expected)
          and _s.unpack_from("<I", volume_dds, 24)[0] == 2
          and _s.unpack_from("<I", volume_dds, 132)[0] == 4
          and _s.unpack_from("<I", volume_dds, 140)[0] == 1)
    check("embedded volume preview selects an explicit Z plane",
          _embedded.volume_slice(volume_tex, bytes(volume_gfx), 1) == bytes(volume_expected[16:]))
    try:
        _embedded.mip0(volume_tex, bytes(volume_gfx))
        ambiguous_volume_refused = False
    except ValueError:
        ambiguous_volume_refused = True
    check("embedded volume cannot use an implicit 2D preview", ambiguous_volume_refused)
    try:
        _embedded.volume_slice(volume_tex, bytes(volume_gfx[:-1]), 0)
        volume_padding_refused = False
    except ValueError:
        volume_padding_refused = True
    check("embedded volume preview requires complete allocation padding", volume_padding_refused)

    # Opus packet records and Ogg remux.
    block = _s.pack("<H", 1) + b"\x00" + _s.pack("<H", 2) + b"\x01\x02"
    opus_packets = _audio.packets(block + b"\x00" * (2048 - len(block)))
    check("audio packets split",
          len(opus_packets) == 2 and opus_packets[1] == b"\x01\x02")
    check("audio packet samples", _audio.packet_samples(b"\x00") == 480)
    ogg = _audio.ogg_opus(opus_packets, 960)
    check("ogg opus pages",
          ogg.startswith(b"OggS") and b"OpusHead" in ogg[:64]
          and ogg.count(b"OggS") == 4)

    bc1 = _s.pack("<HHI", 0xF800, 0x0000, 0)
    check("bc1 preview decodes", _bcn.decode_rgba(71, bc1, 4, 4)[:4] == b"\xff\x00\x00\xff")
    check("png preview writes",
          _png.png_bytes(2, 1, bytes((255, 0, 0, 255, 0, 255, 0, 255)))
          .startswith(b"\x89PNG\r\n\x1a\n"))
    sample_names = _anim_mod.classify(b"pack:/a.clip\x00pack:/b.anim\x00", 0, 1)
    check("anim name table classifies",
          sample_names.signature == "name-table"
          and set(sample_names.names) == {"pack:/a.clip", "pack:/b.anim"})
    clip = _anim_mod.classify(_s.pack("<I", 2) + b"\x01\x01\x00\x00" + b"\x00" * 16, 0, 1)
    check("anim clip stream classifies", clip.signature == "clip-stream")
    from .bc.bcpack import decoder as _bcpack
    from .bc import bc7 as _bc7
    from .bc import bc6h as _bc6h
    check("bcpack model tables", _bcpack.tables_ok())
    check("bc7 decoder", _bc7.decode_block(b"\x00" * 16) == [(0, 0, 0, 0)] * 16)
    from . import music as _music
    _mrec = _s.pack("<I", 30000) + b"\x0c\x01" + _s.pack("<H", 0xB422)
    _mrec += b"\x02\x00\x0c\x00" + _s.pack("<II", 1, 0x031EEAF6)
    _mrec += b"\x00\x00\x02\x23" + b"\x00" * 22
    _mfound = list(_music.scan(_mrec))
    check("music record parser",
          len(_mfound) == 1 and _mfound[0].config_id == 0xB422
          and _mfound[0].stream_id == 0x031EEAF6)
    check("bc6h decoder", _bc6h.decode_block(
        bytes.fromhex("cee15065fdf96d84c07a79f92f6b113b"))[0]
        == (16753, 10274, 11206))
    from . import volume as _volume

    class _VolumeStub:
        dimension = 3
        mips = 1
        width = 32
        height = 32
        slices = 32
        dxgi_format = 10

    _vol = _volume.layout_for(_VolumeStub())
    check("3D volume layout", _vol is not None and _vol.total == 262144
          and len(_vol.untile(bytes(262144))) == 262144)
    _win = [tuple((slot * 7 + k * 13) % (1 << _bcpack.BC1_ENDPOINT_WIDTHS[k])
                  for k in range(6)) for slot in range(256)]
    _tab = [tuple((slot >> (2 * k)) & 3 for k in range(4)) for slot in range(256)]
    _chunk = bytes.fromhex("15141b1bdf1013143d3e0911032814030101f51c011005117117b7af000ffd546cd2eaa47468dc766c102bed1d6501f41b1891e3c1741b181c27031cd50549282123f3a681061d6bab65db8a93dca83da80466f51a543ddf1a934a771b363c936022312ac4a3259f97e1fca17966d0bba11828c4c727ae63d6dc02edbb720a0a2faef42ae4ec11a791d6c23d1f5fe9e9f57134c7521acb80d40a22fd095bf964ef543aaa20930639841501ff6dc74cba235d2b5d255e3db2451915498be65eb9082a450c74da1af0d71601bcce47f079f31a58e96adf0377271173850de4830100636bbf674385cd75223f3b0c4d0beadcf70903010cf50ba316883d93202516b7d82c59e89f04872e7e04c16b42fc1597b515132b1860017207c456e012a7f4c79c8e7bfbfba01196077c347d05db970b3299dff62cdef05d2149643d6a7e206bf9b1792220b694644fa3d20d841e447009518b3e6736077a9abb357994030f248f7711afcd1d0534df3985578986c5a27ad4139aed76526f2c253de0231df3a2ee66b84e333af3caa4422c882bb43fd1916af12750045d96b6c41feb95caf603010448119f6d23f61e50817efb91180eb7a84e5609f6e835e1f352170a01ae4b3defff85a559da2e66066ff630362d99b05f8625d5b3462762f2d0d287f796009c35d22b8814856b20888760f0c10c7772d3d32003e53d9720463194e0a4c080f64c")
    _out = _bcpack.decode_bc1(_chunk, 64, window=_win, table=_tab)
    import hashlib as _hashlib
    check("bcpack BC1 synthetic vector",
          _hashlib.sha256(_out).hexdigest() == "2cd7ef1ec482d1c09b2420b821cda81166c49170d69aa8c8a313852fcd258fca")
    check("murmur3 64-bit hash", _names.hash64("rope") == 0xC875C99D196B2F1C)
    check("joaat known hashes",
          _names.joaat("standard") == 0xBCF03FC1
          and _names.joaat("diffusetex") == 0xC8E8C282)
    check("joaat exact differs",
          _names.joaat_exact("BumpTex") != _names.joaat("BumpTex"))
    check("psin checksum vector", _psin.joaat_checksum(b"") == 0x6AE15BB2)
    parts = bytearray()
    parts += b"PSIN" + _s.pack(">I", 16) + b"\x00" * 8
    for tag in (b"LSCH", b"LENM", b"LSNS", b"LGID", b"LRSC"):
        parts += tag + _s.pack(">I", 8)
    parts += b"CHKS" + _s.pack(">I", 20) + _s.pack(">I", 76) + b"\x00" * 4 + b"zppp"
    checksum = _psin.container_checksum(bytes(parts), 56)
    _s.pack_into(">I", parts, 68, checksum)
    parsed = _psin.parse_container(bytes(parts))
    check("psin checksum verifies", parsed is not None and parsed.checksum_verified)

    # Authored LSCH structure table followed by two field descriptors.
    from . import psin_schema as _schema
    schema_payload = _s.pack('<4I8sIHH', 0x11223344, 9, 10, 11,
                             b'\xaa' * 8, 8, 0, 2)
    schema_payload += _s.pack('<8I', 0x12345678, 0, 0x432100fe, 12,
                              0x87654321, 4, 0xffff, 13)
    schema_section = b'LSCH' + _s.pack('>I', len(schema_payload) + 8) + schema_payload
    schema = _schema.parse_lsch(schema_section)
    check("LSCH structure and field grouping",
          len(schema.structures) == 1 and len(schema.structures[0].fields) == 2
          and schema.structures[0].fields[1].data_offset == 4)
    check("LSCH unknown type preserved",
          schema.structures[0].fields[0].type_word == 0x432100fe
          and schema.as_dict()['structures'][0]['fields'][0]['type_name'] is None)
    broken_schema = bytearray(schema_section)
    _s.pack_into('<I', broken_schema, 60, 8)  # second field starts past size 8
    try:
        _schema.parse_lsch(bytes(broken_schema))
        schema_refused = False
    except ValueError:
        schema_refused = True
    check("LSCH field bounds refused", schema_refused)
    # The verified PSIN fixture above carries an empty LSCH section.
    schema_verified = _schema.parse_schema(bytes(parts)).structures == []
    parts[68] ^= 1
    try:
        _schema.parse_schema(bytes(parts))
        checksum_refused = False
    except ValueError:
        checksum_refused = True
    check("PSIN schema checksum gate", schema_verified and checksum_refused)

    # Authored LENM header and full-width values; no external enum table.
    enum_payload = _s.pack('<II8sII', 7, 9, b'\xee' * 8, 2, 0)
    enum_payload += _s.pack('<QIIQII', 0, 0x12345678, 0,
                            (1 << 64) - 1, 0x87654321, 0)
    enum_section = b'LENM' + _s.pack('>I', len(enum_payload) + 8) + enum_payload
    enums = _schema.parse_lenm(enum_section)
    check("LENM grouped enum members",
          len(enums.definitions) == 1 and len(enums.definitions[0].members) == 2)
    enum_member = enums.definitions[0].members[1].as_dict()
    check("LENM full-width signed value preserved",
          enum_member['value_signed'] == -1 and enum_member['value_bits'] == '0xffffffffffffffff')
    linked_section = bytearray(schema_section)
    _s.pack_into('<II', linked_section, 48, 0x62, 7)
    linked = _schema.parse_lsch(bytes(linked_section))
    linked.enum_table = enums
    fields = linked.as_dict()['structures'][0]['fields']
    check("LSCH enum meaning explicitly inferred",
          fields[0]['type_name'] == 'enum32' and fields[0]['type_info']['status'] == 'inferred')
    check("LSCH unsupported type remains unknown", fields[1]['type_name'] is None)
    original_id = linked.schema_id
    changed_enums = bytearray(enum_section)
    changed_enums[32] = 1
    linked.enum_table = _schema.parse_lenm(bytes(changed_enums))
    check("schema identity includes LENM", linked.schema_id != original_id)

    # Authored instance block, including the first entry at PSIN +8.
    from . import psin_instances as _instances
    instance_body = (b'PSIN' + _s.pack('>I', 48)
                     + _s.pack('<II', 0x11223344, 8) + b'\xaa' * 8
                     + b'pppppppp' + _s.pack('<B3xf', 1, 1.25) + bytes(8))
    instance_schema = bytearray(schema_section)
    _s.pack_into('<II', instance_schema, 48, 1, 0)
    _s.pack_into('<II', instance_schema, 64, 0x21, 0)

    def instance_fixture(ls, body=instance_body, enm=None, lrsc=None):
        value = body + bytes(ls)
        value += b'LENM' + _s.pack('>I', 8) if enm is None else bytes(enm)
        value += b''.join(tag + _s.pack('>I', 8) for tag in (b'LSNS', b'LGID'))
        value += b'LRSC' + _s.pack('>I', 8 + len(lrsc or b'')) + (lrsc or b'')
        trailer = len(value)
        value += b'CHKS' + _s.pack('>III', 20, trailer + 20, 0) + b'zppp'
        checksum = _psin.container_checksum(value, trailer)
        return value[:trailer + 12] + _s.pack('>I', checksum) + value[trailer + 16:]

    instance_data = instance_fixture(instance_schema)
    instance_blocks = _instances.parse_blocks(instance_body)
    check('PSIN first instance block retained',
          len(instance_blocks) == 1 and instance_blocks[0].table_offset == 8
          and instance_blocks[0].data_offset == 32)
    decoded_instance = _instances.decode_instances(instance_data)
    values = decoded_instance['blocks'][0]['records'][0]['fields']
    check('PSIN native scalar instance values',
          values[0]['value'] is True and values[1]['value'] == 1.25
          and decoded_instance['status'] == 'complete')

    bitset_payload = (_s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa'*8, 8, 0, 1)
                      + _s.pack('<4I', 0x12345678, 0, (35 << 16) | 0x65, 7))
    bitset_schema = b'LSCH' + _s.pack('>I', len(bitset_payload)+8) + bitset_payload
    bitset_enums = (_s.pack('<II8sII', 7, 0, b'\xee'*8, 35, 0)
                    + b''.join(_s.pack('<QII', i, 0x1000+i, 0) for i in range(35)))
    bitset_lenm = b'LENM' + _s.pack('>I', len(bitset_enums)+8) + bitset_enums
    bitset_body = bytearray(instance_body)
    _s.pack_into('<Q', bitset_body, 32, (1 << 34) | 1)
    bitset_data = instance_fixture(bitset_schema, body=bytes(bitset_body), enm=bitset_lenm)
    bitset_report = _instances.decode_instances(bitset_data)
    bitset_value = bitset_report['blocks'][0]['records'][0]['fields'][0]
    check('PSIN exact-extent bitsets retain high set indices and original bits',
          bitset_value['status'] == 'decoded' and bitset_value['value'] == [0, 34]
          and bitset_value['value_bits'] == '0x0000000400000001'
          and bitset_value['type_confidence'] == 'inferred')
    _s.pack_into('<Q', bitset_body, 32, 1 << 35)
    bitset_invalid = _instances.decode_instances(instance_fixture(
        bitset_schema, body=bytes(bitset_body), enm=bitset_lenm))
    bitset_invalid = bitset_invalid['blocks'][0]['records'][0]['fields'][0]
    check('PSIN bitset padding is refused without masking source bits',
          bitset_invalid['status'] == 'unresolved' and 'value' not in bitset_invalid)
    try:
        _instances.decode_instances(bitset_data, max_nodes=bitset_report['summary']['nodes']-1)
        bitset_budget_refused = False
    except _instances.InstanceLimitError:
        bitset_budget_refused = True
    check('PSIN set-bit aliases consume the existing instance budget', bitset_budget_refused)
    try:
        _instances.parse_blocks(instance_body[:-1] + b'\x01')
        padding_refused = False
    except ValueError:
        padding_refused = True
    check('PSIN instance padding refused', padding_refused)
    try:
        _instances.decode_instances(instance_data, max_nodes=3)
        nodes_refused = False
    except _instances.InstanceLimitError:
        nodes_refused = True
    check('PSIN instance node budget enforced', nodes_refused)
    _s.pack_into('<I', instance_schema, 48, 7)
    unresolved_instance = _instances.decode_instances(instance_fixture(instance_schema))
    unknown_value = unresolved_instance['blocks'][0]['records'][0]['fields'][0]
    check('PSIN unknown instance field preserved',
          unknown_value['status'] == 'unresolved' and 'value' not in unknown_value)

    # Authored cross-file metadata; no game bytes or external schema tables.
    from . import psin_registry as _registry
    _s.pack_into('<I', instance_schema, 48, 1)
    registry = _registry.Registry()
    registry.add(instance_fixture(instance_schema))
    registry.add(instance_fixture(instance_schema), {'file': 'second.psin'})
    check('PSIN registry equivalent definitions deduplicate',
          registry.summary()['structure_variants'] == 1 and registry.source_count == 2)
    foreign_data = instance_fixture(b'LSCH' + _s.pack('>I', 8))
    foreign = _instances.decode_instances(foreign_data, registry=registry)
    check('PSIN registry cross-file instance values',
          foreign['blocks'][0]['structure_resolution']['scope'] == 'registry'
          and foreign['summary']['decoded_values'] == 2 and foreign['status'] == 'complete')
    loaded_registry = _registry.Registry.from_dict(registry.as_dict())
    check('PSIN registry reload states verification limit',
          loaded_registry.as_dict() == registry.as_dict()
          and 'not_reverified' in loaded_registry.verification)
    _s.pack_into('<I', instance_schema, 8, 0x100)
    reserved_registry = _registry.Registry()
    reserved_registry.add(instance_fixture(instance_schema))
    check('PSIN registry synthetic ids stay local',
          reserved_registry.resolve('structure', 0x100).status == 'reserved')
    _s.pack_into('<I', instance_schema, 8, 0x11223344)
    _s.pack_into('<I', instance_schema, 48, 0x4a)
    registry.add(instance_fixture(instance_schema))
    conflicted = _instances.decode_instances(foreign_data, registry=registry)
    check('PSIN registry same-signature conflicts remain unknown',
          registry.resolve('structure', 0x11223344).status == 'signature_conflict'
          and conflicted['summary']['decoded_values'] == 0)

    def pool_fixture(key, raw):
        body = (b'PSIN' + _s.pack('>I', 32 + ((len(raw) + 15) & ~15))
                + _s.pack('<II', key, len(raw)) + b'\xaa' * 8 + b'p' * 8
                + raw + bytes(-len(raw) % 16))
        return instance_fixture(b'LSCH' + _s.pack('>I', 8), body)

    hash_pool = _instances.decode_instances(pool_fixture(0x4a, _s.pack('<II', 0, 0x12345678)))
    check('PSIN low-ID hash32 pool',
          hash_pool['summary']['pool_values_decoded'] == 2
          and hash_pool['blocks'][0]['pool']['elements'][1]['value'] == '0x12345678')
    text_pool = _instances.decode_instances(pool_fixture(0x10, b'one\0\0'))
    check('PSIN low-ID ASCII pool retains empty strings',
          [e['value'] for e in text_pool['blocks'][0]['pool']['elements']] == ['one', ''])
    reference_pool = _instances.decode_instances(pool_fixture(7, _s.pack('<Q', 1)))
    check('PSIN reference candidate never follows target',
          reference_pool['blocks'][0]['pool']['elements'][0]['reference']['status'] == 'in_bounds'
          and reference_pool['summary']['decoded_values'] == 0 and reference_pool['status'] == 'partial')
    opaque_pool = _instances.decode_instances(pool_fixture(0x14, bytes(4)))
    check('PSIN opaque pool keeps meaning unknown',
          opaque_pool['blocks'][0]['pool']['interpretation'] == 'unknown'
          and 'value' not in opaque_pool['blocks'][0]['pool']['elements'][0])
    bad_text_pool = _instances.decode_instances(pool_fixture(0x10, b'bad'))
    check('PSIN unvalidated text pool refuses whole profile',
          bad_text_pool['blocks'][0]['pool']['status'] == 'unresolved'
          and bad_text_pool['summary']['decoded_values'] == 0)

    array_schema = (b'LSCH' + _s.pack('>I', 72)
                    + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa' * 8, 16, 0, 2)
                    + _s.pack('<8I', 0x100, 0, 0x4a, 0, 0x87654321, 0, 0x52, 0))

    def array_fixture(word=2, count=2, second=2, target_type=0x4a, schema=array_schema):
        body = (b'PSIN' + _s.pack('>I', 80)
                + _s.pack('<II', 0x11223344, 16) + b'\xaa' * 8
                + _s.pack('<II', target_type, 8) + b'\xaa' * 8 + b'p' * 8
                + _s.pack('<QHHI', word, count, second, 0)
                + _s.pack('<II', 0x11111111, 0x22222222) + bytes(8))
        return instance_fixture(schema, body)

    array_data = array_fixture()
    array_report = _instances.decode_instances(array_data)
    array_value = array_report['blocks'][0]['records'][0]['fields'][1]['array']
    check('PSIN bounded hash32 array resolves its exact span',
          [e['value'] for e in array_value['elements']] == ['0x11111111', '0x22222222']
          and array_report['summary']['hash32_array_values_decoded'] == 2)
    empty_array = _instances.decode_instances(array_fixture(0, 0, 0))
    empty_value = empty_array['blocks'][0]['records'][0]['fields'][1]['array']
    check('PSIN null empty hash32 array has no invented values',
          empty_value['status'] == 'complete' and empty_value['elements'] == []
          and empty_value['target'] is None)
    unequal_array = _instances.decode_instances(array_fixture(second=1))
    unequal_value = unequal_array['blocks'][0]['records'][0]['fields'][1]
    check('PSIN unequal array header words remain unresolved',
          unequal_value['status'] == 'unresolved' and unequal_value['array']['elements'] == [])
    overrun_array = _instances.decode_instances(array_fixture((4 << 20) | 2))
    overrun_value = overrun_array['blocks'][0]['records'][0]['fields'][1]
    check('PSIN array span cannot read target padding',
          overrun_value['status'] == 'unresolved' and 'span exceeds' in overrun_value['reason'])
    try:
        _instances.decode_instances(array_data, max_nodes=array_report['summary']['nodes'] - 1)
        array_budget_refused = False
    except _instances.InstanceLimitError:
        array_budget_refused = True
    check('PSIN array and pool observations share node budget', array_budget_refused)

    structure_array_schema = (b'LSCH' + _s.pack('>I', 120)
        + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa' * 8, 16, 0, 2)
        + _s.pack('<4I8sIHH', 0x22334455, 0, 0, 0, b'\xaa' * 8, 4, 0, 1)
        + _s.pack('<8I', 0x100, 0, 5, 0x22334455, 0x87654321, 0, 0x52, 0)
        + _s.pack('<4I', 0x12345678, 0, 0x4a, 0))
    structure_array = _instances.decode_instances(
        array_fixture(target_type=0x22334455, schema=structure_array_schema))
    structure_links = structure_array['blocks'][0]['records'][0]['fields'][1]['array']
    check('PSIN structure arrays select exact existing records',
          structure_links['mode'] == 'record_links'
          and [e['record_index'] for e in structure_links['elements']] == [0, 1]
          and structure_array['summary']['structure_array_records_linked'] == 2)
    check('PSIN structure-array links do not duplicate decoded values',
          structure_array['summary']['records'] == 3
          and structure_array['summary']['decoded_values'] == 2
          and all(e['status'] == 'record_reference' and 'value' not in e for e in structure_links['elements']))
    wrong_structure_target = _instances.decode_instances(array_fixture(schema=structure_array_schema))
    wrong_structure_value = wrong_structure_target['blocks'][0]['records'][0]['fields'][1]
    check('PSIN structure arrays reject matching-size wrong types',
          wrong_structure_value['status'] == 'unresolved'
          and 'differs from' in wrong_structure_value['reason'])
    missing_structure_schema = bytearray(array_schema)
    _s.pack_into('<II', missing_structure_schema, 48, 5, 0x22334455)
    missing_structure_array = _instances.decode_instances(
        array_fixture(target_type=0x22334455, schema=missing_structure_schema))
    check('PSIN structure arrays require a unique local target schema',
          missing_structure_array['summary']['structure_array_records_linked'] == 0
          and missing_structure_array['blocks'][0]['records'][0]['fields'][1]['status'] == 'unresolved')
    _s.pack_into('<I', missing_structure_schema, 52, 0x11223344)
    cycle_body = (b'PSIN' + _s.pack('>I', 48) + _s.pack('<II', 0x11223344, 16)
                  + b'\xaa' * 8 + b'p' * 8 + _s.pack('<QHHI', 1, 1, 1, 0))
    linked_cycle = _instances.decode_instances(instance_fixture(missing_structure_schema, cycle_body), max_depth=1)
    check('PSIN cyclic structure arrays stay finite links',
          linked_cycle['summary']['records'] == 1
          and linked_cycle['summary']['structure_array_records_linked'] == 1
          and linked_cycle['summary']['decoded_values'] == 0)

    reference_array_schema = (b'LSCH' + _s.pack('>I', 168)
        + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa' * 8, 16, 0, 2)
        + _s.pack('<4I8sIHH', 0x22334455, 0, 0, 0, b'\xaa' * 8, 4, 0, 1)
        + _s.pack('<4I8sIHH', 0x33445566, 0, 0, 0, b'\xaa' * 8, 4, 0, 1)
        + _s.pack('<8I', 0x100, 0, 7, 0, 0x87654321, 0, 0x52, 0)
        + _s.pack('<4I', 0x12345678, 0, 0x4a, 0) * 2)

    def reference_fixture(words=(3, 0, 4)):
        raw = b''.join(_s.pack('<Q', word) for word in words)
        body = (b'PSIN' + _s.pack('>I', 128 + ((len(raw) + 15) & ~15))
            + _s.pack('<II', 0x11223344, 16) + b'\xaa' * 8
            + _s.pack('<II', 7, len(raw)) + b'\xaa' * 8
            + _s.pack('<II', 0x22334455, 8) + b'\xaa' * 8
            + _s.pack('<II', 0x33445566, 4) + b'\xaa' * 8 + b'p' * 8
            + _s.pack('<QHHI', 2, len(words), len(words), 0)
            + raw + bytes(-len(raw) % 16)
            + _s.pack('<II', 0x11111111, 0x22222222) + bytes(8)
            + _s.pack('<I', 0x33333333) + bytes(12))
        return instance_fixture(reference_array_schema, body)

    reference_data = reference_fixture()
    reference_report = _instances.decode_instances(reference_data)
    references = reference_report['blocks'][0]['records'][0]['fields'][1]['array']
    check('PSIN reference arrays link mixed local record types',
          references['mode'] == 'reference_record_links'
          and [e.get('structure_hash') for e in references['elements']] == ['0x22334455', None, '0x33445566'])
    check('PSIN reference-array links do not duplicate record values',
          reference_report['summary']['reference_array_records_linked'] == 2
          and reference_report['summary']['records'] == 4
          and reference_report['summary']['decoded_values'] == 3)
    null_references = _instances.decode_instances(reference_fixture((0, 0)))
    check('PSIN reference arrays preserve null slots without invented records',
          null_references['summary']['reference_array_null_entries'] == 2
          and null_references['summary']['reference_array_records_linked'] == 0)
    failed_references = _instances.decode_instances(reference_fixture((3, 0, 0xffff)))
    failed_array = failed_references['blocks'][0]['records'][0]['fields'][1]['array']
    check('PSIN bad reference-array member discards every prefix link',
          failed_array['status'] == 'unresolved' and failed_array['elements'] == []
          and failed_array['failed_element_index'] == 2)
    try:
        _instances.decode_instances(reference_data, max_nodes=reference_report['summary']['nodes'] - 1)
        reference_budget_refused = False
    except _instances.InstanceLimitError:
        reference_budget_refused = True
    check('PSIN reference links and raw pool slots share output budget', reference_budget_refused)

    reference_field_schema = (b'LSCH' + _s.pack('>I', 104)
        + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa' * 8, 8, 0, 1)
        + _s.pack('<4I8sIHH', 0x22334455, 0, 0, 0, b'\xaa' * 8, 4, 0, 1)
        + _s.pack('<4I', 0x87654321, 0, 7, 0)
        + _s.pack('<4I', 0x12345678, 0, 0x4a, 0))

    def reference_field_fixture(word=2, lrsc=None):
        body = (b'PSIN' + _s.pack('>I', 80)
            + _s.pack('<II', 0x11223344, 8) + b'\xaa' * 8
            + _s.pack('<II', 0x22334455, 8) + b'\xaa' * 8 + b'p' * 8
            + _s.pack('<Q', word) + bytes(8)
            + _s.pack('<II', 0x11111111, 0x22222222) + bytes(8))
        return instance_fixture(reference_field_schema, body, lrsc=lrsc)

    field_data = reference_field_fixture()
    field_report = _instances.decode_instances(field_data)
    field_value = field_report['blocks'][0]['records'][0]['fields'][0]
    check('PSIN standalone reference links existing local records without duplicate values',
          field_value['reference']['status'] == 'record_reference'
          and field_value['type_name'] is None and field_report['summary']['decoded_values'] == 2
          and field_report['summary']['records'] == 3)
    null_field = _instances.decode_instances(reference_field_fixture(0))
    check('PSIN standalone zero reference preserves null without an invented target',
          null_field['summary']['reference_fields_null'] == 1
          and null_field['blocks'][0]['records'][0]['fields'][0]['reference']['target'] is None)
    bad_field = _instances.decode_instances(reference_field_fixture(3))
    check('PSIN bad standalone reference stays unresolved with original bits',
          bad_field['summary']['reference_fields_unresolved'] == 1
          and bad_field['blocks'][0]['records'][0]['fields'][0]['reference']['reference_bits'] == '0x0000000000000003')
    field_cycle_body = (b'PSIN' + _s.pack('>I', 48) + _s.pack('<II', 0x11223344, 8)
                        + b'\xaa' * 8 + b'p' * 8 + _s.pack('<Q', 1) + bytes(8))
    field_cycle = _instances.decode_instances(instance_fixture(reference_field_schema, field_cycle_body), max_depth=1)
    check('PSIN standalone reference cycle is not expanded',
          field_cycle['summary']['reference_fields_linked'] == 1
          and field_cycle['summary']['records'] == 1 and field_cycle['summary']['decoded_values'] == 0)
    try:
        _instances.decode_instances(field_data, max_nodes=field_report['summary']['nodes'] - 1)
        field_budget_refused = False
    except _instances.InstanceLimitError:
        field_budget_refused = True
    check('PSIN standalone reference metadata shares output budget', field_budget_refused)

    # Authored map entries; duplicate keys are retained as stored record links.
    map_schema = (b'LSCH' + _s.pack('>I', 152)
        + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa' * 8, 24, 0, 3)
        + _s.pack('<4I8sIHH', 0x22334455, 0, 0, 0, b'\xaa' * 8, 8, 0, 2)
        + _s.pack('<4I', 0x100, 0, 0x4a, 0)
        + _s.pack('<4I', 0x100, 0, 0x4a, 0)
        + _s.pack('<4I', 0x87654321, 0, 0x71, 1 << 16)
        + _s.pack('<4I', 0x12345678, 0, 0x4a, 0)
        + _s.pack('<4I', 0x23456789, 4, 0x4a, 0))

    def map_fixture(word=2, count=2, prefix=1):
        body = (b'PSIN' + _s.pack('>I', 96)
            + _s.pack('<II', 0x11223344, 24) + b'\xaa' * 8
            + _s.pack('<II', 0x22334455, 16) + b'\xaa' * 8 + b'p' * 8
            + _s.pack('<QQHHI', prefix, word, count, count, 0) + bytes(8)
            + _s.pack('<4I', 7, 11, 7, 22))
        return instance_fixture(map_schema, body)

    map_data = map_fixture()
    map_report = _instances.decode_instances(map_data)
    map_value = map_report['blocks'][0]['records'][0]['fields'][2]['map']
    check('PSIN map entries retain duplicate keys through existing record links',
          [e['record_index'] for e in map_value['entries']] == [0, 1]
          and map_report['blocks'][1]['records'][0]['fields'][0]['value']
              == map_report['blocks'][1]['records'][1]['fields'][0]['value'])
    check('PSIN map links do not duplicate decoded values',
          map_report['summary']['decoded_values'] == 4 and map_report['summary']['records'] == 3)
    empty_map = _instances.decode_instances(map_fixture(0, 0))
    check('PSIN empty map preserves a null entry target',
          empty_map['blocks'][0]['records'][0]['fields'][2]['map']['target'] is None)
    bad_map = _instances.decode_instances(map_fixture(count=3))
    check('PSIN map span cannot consume target padding or return prefix entries',
          bad_map['summary']['maps_unresolved'] == 1
          and bad_map['blocks'][0]['records'][0]['fields'][2]['map']['entries'] == [])
    zero_map = _instances.decode_instances(map_fixture(0, 0, 0))
    check('PSIN all-zero map header is unresolved rather than an invented empty map',
          zero_map['summary']['maps_unresolved'] == 1)
    try:
        _instances.decode_instances(map_data, max_nodes=map_report['summary']['nodes'] - 1)
        map_budget_refused = False
    except _instances.InstanceLimitError:
        map_budget_refused = True
    check('PSIN map headers and links share output budget', map_budget_refused)

    enum_map_schema = (b'LSCH' + _s.pack('>I', 200)
        + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa' * 8, 24, 0, 3)
        + _s.pack('<4I8sIHH', 0x22334455, 0, 0, 0, b'\xaa' * 8, 8, 0, 2)
        + _s.pack('<4I8sIHH', 0x44556677, 0, 0, 0, b'\xaa' * 8, 4, 0, 1)
        + _s.pack('<4I', 0x100, 0, 0x62, 0x33445566)
        + _s.pack('<4I', 0x100, 0, 5, 0x44556677)
        + _s.pack('<4I', 0x87654321, 0, 0x71, 1 << 16)
        + _s.pack('<4I', 0x12345678, 0, 0x62, 0x33445566)
        + _s.pack('<4I', 0x23456789, 4, 5, 0x44556677)
        + _s.pack('<4I', 0x3456789a, 0, 0x4a, 0))
    enum_map_lenm = (b'LENM' + _s.pack('>I', 48)
        + _s.pack('<II8sII', 0x33445566, 0, b'\xee' * 8, 1, 0)
        + _s.pack('<QII', 7, 0x55667788, 0))
    enum_map_body = (b'PSIN' + _s.pack('>I', 96)
        + _s.pack('<II', 0x11223344, 24) + b'\xaa' * 8
        + _s.pack('<II', 0x22334455, 16) + b'\xaa' * 8 + b'p' * 8
        + _s.pack('<QQHHI', 1, 2, 2, 2, 0) + bytes(8)
        + _s.pack('<4I', 7, 11, 7, 22))
    enum_map_report = _instances.decode_instances(instance_fixture(enum_map_schema, enum_map_body, enum_map_lenm))
    enum_map_value = enum_map_report['blocks'][0]['records'][0]['fields'][2]['map']
    check('PSIN enum-key maps link locally typed rows with local LENM membership',
          enum_map_value['status'] == 'complete' and enum_map_value['key_type'] == 'enum32'
          and len(enum_map_value['entries']) == 2 and enum_map_report['summary']['decoded_values'] == 4)
    bad_enum_body = bytearray(enum_map_body)
    _s.pack_into('<I', bad_enum_body, 88, 8)
    bad_enum_report = _instances.decode_instances(instance_fixture(enum_map_schema, bad_enum_body, enum_map_lenm))
    check('PSIN enum-key map refuses an unknown key without prefix links',
          bad_enum_report['blocks'][0]['records'][0]['fields'][2]['map']['entries'] == []
          and bad_enum_report['summary']['maps_unresolved'] == 1)
    missing_enum = _instances.decode_instances(instance_fixture(enum_map_schema, enum_map_body))
    check('PSIN enum-key map cannot borrow an absent local enum definition',
          missing_enum['summary']['maps_unresolved'] == 1)

    enum_array_schema = (b'LSCH' + _s.pack('>I', 120)
        + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa' * 8, 16, 0, 2)
        + _s.pack('<4I8sIHH', 0x22334455, 0, 0, 0, b'\xaa' * 8, 4, 0, 1)
        + _s.pack('<4I', 0x100, 0, 0x62, 0x33445566)
        + _s.pack('<4I', 0x12345678, 0, 0x52, 0)
        + _s.pack('<4I', 0x23456789, 0, 0x62, 0x33445566))
    enum_array_body = (b'PSIN' + _s.pack('>I', 80)
        + _s.pack('<II', 0x11223344, 16) + b'\xaa' * 8
        + _s.pack('<II', 0x22334455, 8) + b'\xaa' * 8 + b'p' * 8
        + _s.pack('<QHHI', 2, 2, 2, 0) + _s.pack('<II', 7, 7) + bytes(8))
    enum_array_report = _instances.decode_instances(instance_fixture(enum_array_schema, enum_array_body, enum_map_lenm))
    enum_array_view = enum_array_report['blocks'][0]['records'][0]['fields'][1]['array']
    check('PSIN enum arrays link existing exact local rows without duplicate values',
          enum_array_view['status'] == 'complete' and enum_array_view['mode'] == 'enum_record_links'
          and enum_array_report['summary']['enum32_array_records_linked'] == 2
          and enum_array_report['summary']['decoded_values'] == 2)
    bad_enum_array_body = bytearray(enum_array_body)
    _s.pack_into('<I', bad_enum_array_body, 68, 99)
    bad_enum_array_report = _instances.decode_instances(instance_fixture(enum_array_schema, bad_enum_array_body, enum_map_lenm))
    bad_enum_array_view = bad_enum_array_report['blocks'][0]['records'][0]['fields'][1]['array']
    check('PSIN enum arrays reject an unknown member without prefix links',
          bad_enum_array_view['status'] == 'unresolved' and bad_enum_array_view['elements'] == [])
    empty_enum_array_body = bytearray(enum_array_body)
    empty_enum_array_body[48:64] = bytes(16)
    empty_enum_array_report = _instances.decode_instances(instance_fixture(enum_array_schema, empty_enum_array_body, enum_map_lenm))
    check('PSIN empty enum arrays retain an explicit unsupported profile',
          empty_enum_array_report['blocks'][0]['records'][0]['fields'][1]['array']['status'] == 'unresolved')

    from . import anim_resources as _anim_resources
    import zlib as _directory_zlib

    def directory_fixture(shift=0):
        value = bytearray(152 + shift)
        value[16:20] = b'0DRP'
        _s.pack_into('<I', value, 20, 122)
        _s.pack_into('<4Q', value, 40, 0x50000050 + shift, 0, 0x50000070 + shift, 0)
        _s.pack_into('<4H', value, 72, 1, 0, 1, 9)
        _s.pack_into('<IIIIQIHH', value, 80 + shift,
                     0x11223344, 1, 2, 3, 0x50000080 + shift, 8, 4, 1)
        _s.pack_into('<IIQ', value, 112 + shift, 0x11223344, 8, 0x50000090 + shift)
        _s.pack_into('<4I', value, 128 + shift, 0x22334455, 0, 0xffff, 7)
        _s.pack_into('<II', value, 144 + shift, 11, 22)
        return bytes(value)

    directory_data = directory_fixture()
    directory = _anim_resources.parse_resource(directory_data)
    check('0DRP bounded schema and block tables',
          directory['summary']['fields'] == 1 and directory['blocks'][0]['data_offset'] == 144
          and directory['blocks'][0]['byte_length'] == 8)
    check('0DRP unsupported types and unknown header roles stay explicit',
          directory['status'] == 'partial' and directory['structures'][0]['fields'][0]['type_name'] is None
          and directory['header']['unknown_4e'] == 9)
    broken_directory = bytearray(directory_data)
    _s.pack_into('<Q', broken_directory, 120, (1 << 63) | 0x50000090)
    try:
        _anim_resources.parse_resource(bytes(broken_directory))
        directory_pointer_refused = False
    except ValueError:
        directory_pointer_refused = True
    check('0DRP full-width pointers cannot alias bounded spans', directory_pointer_refused)
    try:
        _anim_resources.parse_resource(directory_data, max_nodes=directory['summary']['nodes'] - 1)
        directory_budget_refused = False
    except _anim_resources.ResourceLimitError:
        directory_budget_refused = True
    check('0DRP metadata shares an explicit output budget', directory_budget_refused)
    paged_directory = directory_fixture(65536)
    first_page = _directory_zlib.compress(paged_directory[:65536])
    with tempfile.TemporaryDirectory() as directory_tmp:
        directory_path = os.path.join(directory_tmp, 'authored.rpf')
        with open(directory_path, 'wb') as handle:
            handle.write(first_page + bytes(-len(first_page) % 16)
                         + _directory_zlib.compress(paged_directory[65536:]))
        joined_directory = list(_anim_resources.scan_resources(directory_path, start=0))
        check('0DRP adjacent zero-padded pages rejoin before bounds checks',
              len(joined_directory) == 1 and joined_directory[0]['status'] == 'partial'
              and len(joined_directory[0]['segments']) == 2
              and joined_directory[0]['blocks'][0]['data_offset'] == 65680)
        with open(directory_path, 'wb') as handle:
            handle.write(first_page)
        missing_directory = list(_anim_resources.scan_resources(directory_path, start=0))
        check('0DRP missing continuation refuses metadata without prefix output',
              missing_directory[0]['status'] == 'refused' and 'structures' not in missing_directory[0])

    from . import anim_clips as _anim_clips
    clip_fixture = bytearray(344)
    _s.pack_into('<QHHI', clip_fixture, 56, 0x50000070, 8, 9, 1)
    _s.pack_into('<QIIIIQII', clip_fixture, 72, 0x50000080, 1, 0, 1, 0x01000000, 0, 0x1234abcd, 2)
    clip_fixture[112:120] = b'authored'
    _s.pack_into('<Q', clip_fixture, 128, 0x50000088)
    clip_path = b'pack:/authored.clip'
    clip_key = _names.joaat('authored')
    _s.pack_into('<IIQQQ', clip_fixture, 136, clip_key, 0x1234abcd, 0x500000a8, 0, 0)
    _s.pack_into('<QQI', clip_fixture, 184, 1, 0x50000000, 2)
    _s.pack_into('<QHHI', clip_fixture, 208, 0x50000138, len(clip_path), len(clip_path) + 1, 1)
    _s.pack_into('<II', clip_fixture, 256, clip_key, 0x1234abcd)
    _s.pack_into('<f', clip_fixture, 288, 1.5)
    clip_fixture[312:312 + len(clip_path)] = clip_path
    named_clip = _anim_clips.parse_dictionary(bytes(clip_fixture))
    check('named clip links verify node, record and referenced path stem',
          named_clip['summary']['clips_linked'] == 1
          and named_clip['entries'][0]['name']['value'] == 'pack:/authored.clip'
          and named_clip['entries'][0]['duration_candidate']['status'] == 'candidate'
          and named_clip['status'] == 'partial')
    bad_clip = bytearray(clip_fixture)
    _s.pack_into('<I', bad_clip, 256, 0)
    unresolved_clip = _anim_clips.parse_dictionary(bytes(bad_clip))['entries'][0]
    check('named clip hash mismatch preserves an unresolved member without an invented name',
          unresolved_clip['status'] == 'unresolved' and 'name' not in unresolved_clip)
    bad_clip = bytearray(clip_fixture)
    _s.pack_into('<Q', bad_clip, 144, (1 << 63) | 0x500000a8)
    check('named clip full-width record pointers cannot alias by masking',
          _anim_clips.parse_dictionary(bytes(bad_clip))['summary']['clips_unresolved'] == 1)
    bad_clip = bytearray(clip_fixture)
    _s.pack_into('<Q', bad_clip, 152, 0x50000088)
    try:
        _anim_clips.parse_dictionary(bytes(bad_clip))
        clip_cycle_refused = False
    except ValueError:
        clip_cycle_refused = True
    check('named clip node cycles refuse dictionary output', clip_cycle_refused)
    try:
        _anim_clips.parse_dictionary(bytes(clip_fixture), max_nodes=named_clip['summary']['nodes'] - 1)
        clip_budget_refused = False
    except _anim_resources.ResourceLimitError:
        clip_budget_refused = True
    check('named clip nodes and strings share an explicit budget', clip_budget_refused)
    with tempfile.TemporaryDirectory() as clip_tmp:
        clip_tmp_path = os.path.join(clip_tmp, 'authored.rpf')
        with open(clip_tmp_path, 'wb') as handle:
            handle.write(_directory_zlib.compress(bytes(clip_fixture) + bytes(65536 - len(clip_fixture))))
        clip_prefix = list(_anim_clips.scan_dictionaries(clip_tmp_path, start=0))
        check('named clip metadata can bind a bounded prefix without claiming full file size',
              clip_prefix[0]['framing'] == 'bounded_metadata_prefix'
              and clip_prefix[0]['summary']['clips_linked'] == 1
              and clip_prefix[0]['status'] == 'partial')

    component_fixture = bytearray(clip_fixture) + bytearray(280)
    _s.pack_into('<QHHI', component_fixture, 272, 0x50000158, 1, 1, 0)
    _s.pack_into('<QHHIII', component_fixture, 344, 0x50000170, 1, 1, 0, 0x3fc00000, 0)
    component_path = b'pack:/rig_authored_0.anim'
    _s.pack_into('<QII', component_fixture, 368, 0x500001a8, _names.joaat('rig_authored_0'), 0)
    _s.pack_into('<Q', component_fixture, 472, 0x50000218)
    _s.pack_into('<Q', component_fixture, 496, 48)
    _s.pack_into('<QHHI', component_fixture, 504, 0x50000238, 1, 1, 0)
    component_fixture[536:536 + len(component_path)] = component_path
    _s.pack_into('<Q', component_fixture, 568, 0x50000240)
    _s.pack_into('<8I', component_fixture, 576, 0x11223344, 16, 0, 0, 0, 0, 0, 0)
    component_fixture[608:624] = bytes(range(16))
    components = _anim_clips.parse_dictionary(bytes(component_fixture), with_components=True)
    component_view = components['entries'][0]['components']
    check('clip components link checked animation names and opaque buffer spans',
          component_view['status'] == 'complete' and component_view['animation_links'] == 1
          and component_view['payload_spans'] == 1
          and component_view['groups'][0]['segments'][0]['animation']['name']['value'] == component_path.decode())
    import hashlib as _component_hashlib
    component_buffer = component_view['groups'][0]['segments'][0]['animation']['buffers'][0]
    check('clip component buffer lengths and hashes match source bytes',
          component_buffer['byte_length'] == 48 and component_buffer['data_offset'] == 576
          and component_buffer['sha256'] == _component_hashlib.sha256(component_fixture[576:624]).hexdigest())
    bad_component = bytearray(component_fixture)
    _s.pack_into('<Q', bad_component, 496, 49)
    mismatched_component = _anim_clips.parse_dictionary(bytes(bad_component), with_components=True)
    check('clip component length disagreement preserves named links but no prefix buffers',
          mismatched_component['summary']['clips_linked'] == 1
          and mismatched_component['entries'][0]['components']['status'] == 'unresolved'
          and mismatched_component['entries'][0]['components']['groups'] == [])
    bad_component = bytearray(component_fixture)
    _s.pack_into('<Q', bad_component, 568, (1 << 63) | 0x50000240)
    check('clip component buffer references retain full-width bounds',
          _anim_clips.parse_dictionary(bytes(bad_component), with_components=True)
          ['summary']['component_clips_unresolved'] == 1)
    try:
        _anim_clips.parse_dictionary(bytes(component_fixture), with_components=True,
                                    max_nodes=components['summary']['nodes'] - 1)
        component_budget_refused = False
    except _anim_resources.ResourceLimitError:
        component_budget_refused = True
    check('clip component metadata and buffer hashes share the output budget', component_budget_refused)
    truncated_components = _anim_clips.parse_dictionary(bytes(component_fixture[:608]), with_components=True)
    check('clip component buffers cannot consume missing bytes or fabricate padding',
          truncated_components['summary']['clips_linked'] == 1
          and truncated_components['entries'][0]['components']['status'] == 'unresolved'
          and truncated_components['entries'][0]['components']['groups'] == [])

    packed_fixture = bytearray(component_fixture) + bytearray(24)
    _s.pack_into('<HH', packed_fixture, 460, 3, 2)
    _s.pack_into('<QHHI', packed_fixture, 520, 0x50000270, 2, 2, 0)
    _s.pack_into('<6I', packed_fixture, 624, 0x11223344, 0x55667788, 0xffffffff,
                 0x89abcdef, 0xfedcba98, 2)
    _s.pack_into('<II', packed_fixture, 588, 34, 36)
    _s.pack_into('<5H2B', packed_fixture, 596, 2, 3, 0, 0, 0, 11, 0x11)
    _s.pack_into('<BBHHBBHH', packed_fixture, 612, 7, 6, 5, 4, 3, 2, 1, 0)
    packed_report = _anim_clips.parse_dictionary(bytes(packed_fixture), with_packed_layout=True)
    packed_view = packed_report['entries'][0]['components']['groups'][0]['segments'][0]['animation']['packed_layout']
    check('packed animation headers partition source regions and bounded auxiliary rows',
          packed_view['status'] == 'complete' and packed_view['auxiliary_row_count'] == 2
          and [x['byte_length'] for x in packed_view['buffers'][0]['regions']] == [32, 2, 2, 12])
    check('packed channel candidates preserve unknown words without guessed types',
          packed_view['binding_count'] == 2 and packed_view['bindings'][0]['raw_words'][2] == '0xffffffff'
          and 'type_name' not in packed_view['bindings'][0])
    bad_packed = bytearray(packed_fixture)
    bad_packed[606] = 12
    refused_layout = _anim_clips.parse_dictionary(bytes(bad_packed), with_packed_layout=True)
    check('unsupported packed header markers preserve parent buffer associations',
          refused_layout['summary']['component_clips_resolved'] == 1
          and refused_layout['summary']['packed_layouts_unresolved'] == 1)
    bad_packed = bytearray(packed_fixture)
    _s.pack_into('<I', bad_packed, 588, 31)
    bad_regions = _anim_clips.parse_dictionary(bytes(bad_packed), with_packed_layout=True)
    bad_layout = bad_regions['entries'][0]['components']['groups'][0]['segments'][0]['animation']['packed_layout']
    check('packed invalid region offsets return no prefix layout rows',
          bad_layout['status'] == 'unresolved' and bad_layout['buffers'] == [] and bad_layout['bindings'] == [])
    bad_packed = bytearray(packed_fixture)
    _s.pack_into('<H', bad_packed, 460, 4)
    check('packed sample-count candidates must reconcile with the animation total',
          _anim_clips.parse_dictionary(bytes(bad_packed), with_packed_layout=True)
          ['summary']['packed_layouts_unresolved'] == 1)
    try:
        _anim_clips.parse_dictionary(bytes(packed_fixture), with_packed_layout=True,
                                    max_nodes=packed_report['summary']['nodes'] - 1)
        packed_budget_refused = False
    except _anim_resources.ResourceLimitError:
        packed_budget_refused = True
    check('packed header and channel rows share the dictionary output budget', packed_budget_refused)

    from . import anim_channels as _channels
    directory = (_s.pack('<5I5H2B', 0, 30, 0, 32, 62, 2, 3, 0, 0, 0, 11, 0)
                 + _s.pack('<11H', 1, *([0] * 10)) + _s.pack('<4H', 0, 4, 4, 4))
    directory_view = _channels.inspect_buffer(directory, 0, len(directory), 1, consume=lambda n=1: None)
    check('packed channel directory exposes bounded unknown groups',
          directory_view['status'] == 'complete' and directory_view['group_count'] == 11
          and directory_view['active_slot_count'] == 1
          and directory_view['groups'][0]['slots'] == [dict(slot_index=0, binding_index=0, sub_index=0)]
          and directory_view['groups'][0]['meaning'] == 'unknown')
    bad_directory = bytearray(directory)
    _s.pack_into('<H', bad_directory, len(directory) - 2, 3)
    refused_directory = _channels.inspect_buffer(bytes(bad_directory), 0, len(directory), 1,
                                                  consume=lambda n=1: None)
    check('packed channel directory rejects bad sentinel padding without prefix groups',
          refused_directory['status'] == 'unresolved' and refused_directory['groups'] == [])
    channel_report = _anim_clips.parse_dictionary(bytes(packed_fixture), with_channels=True)
    check('unsupported channel directory preserves valid parent layout',
          channel_report['summary']['packed_layouts_resolved'] == 1
          and channel_report['summary']['channel_layouts_unresolved'] == 1)

    from . import anim_storage as _storage
    storage_directory = _s.pack('<11H', 1, *([0] * 10)) + _s.pack('<4H', 0, 4, 4, 4)
    storage_raw = (_s.pack('<5I5H2B', 0, 70, 0, 32, 102, 2, 2, 4, 0, 5, 11, 0)
                   + bytes(32) + _s.pack('<2I', 3, 7) + storage_directory)
    storage_view = _storage.inspect_buffer(storage_raw, 0, len(storage_raw), 1, consume=lambda n=1: None)
    check('packed storage uses body-relative split and exact fixed-stride rows',
          storage_view['status'] == 'complete' and storage_view['body_relative_split']['data_offset'] == 64
          and storage_view['sample_rows']['row_count'] == 2
          and sum(r['byte_length'] for r in storage_view['regions']) == len(storage_raw))
    check('packed storage checks bit-width and high zero padding without decoded values',
          storage_view['sample_bit_layout']['active_bits_per_row'] == 5
          and storage_view['sample_bit_layout']['high_zero_padding_bits'] == 27
          and 'values' not in storage_view['sample_rows'])
    bad_storage = bytearray(storage_raw)
    _s.pack_into('<I', bad_storage, 64, 1 << 31)
    refused_storage = _storage.inspect_buffer(bytes(bad_storage), 0, len(bad_storage), 1,
                                              consume=lambda n=1: None)
    check('packed storage refuses nonzero padding without prefix regions',
          refused_storage['status'] == 'unresolved' and refused_storage['regions'] == [])

    from . import anim_payloads as _payloads
    payload_prefix = _s.pack('<12I', 0xffffffff, 0x7fc00000, 0x80000000, *range(9))
    payload_directory = _s.pack('<11H', 4, *([0] * 10)) + _s.pack('<4H', 0, 4, 8, 12)
    payload_raw = (_s.pack('<5I5H2B', 0, 78, 0, 48, 110, 2, 3, 0, 0, 0, 11, 0)
                   + payload_prefix + payload_directory)
    payload_view = _payloads.inspect_buffer(payload_raw, 0, len(payload_raw), 4, consume=lambda n=1: None)
    check('packed payload inventory preserves raw words without numeric sample guesses',
          payload_view['status'] == 'complete' and payload_view['record_count'] == 4
          and payload_view['records'][0]['raw_words'] == ['0xffffffff', '0x7fc00000', '0x80000000']
          and 'values' not in payload_view)
    check('packed payload slot candidates stay separate and unconfirmed',
          payload_view['association_status'] == 'unconfirmed'
          and 'slot_index' not in payload_view['records'][0]
          and payload_view['slot_candidates'][0]['slot_index'] == 0)
    unsupported_payload = _payloads.inspect_buffer(storage_raw, 0, len(storage_raw), 1,
                                                   consume=lambda n=1: None)
    check('unsupported packed payload retains a reason without prefix records',
          unsupported_payload['status'] == 'unresolved' and unsupported_payload['records'] == []
          and unsupported_payload['slot_candidates'] == [] and bool(unsupported_payload['reason']))

    from . import rbf as _rbf
    rbf_raw = (b'RBF0\xfb\xff\x01\x00' + _s.pack('<HH', 0, 4)
               + b'Root' + bytes(6) + b'\xff\xff')
    rbf_view = _rbf.parse(rbf_raw)
    check('RBF0 structural parser consumes exact authored tree',
          rbf_view['consumed_bytes'] == len(rbf_raw) and rbf_view['nodes'][0]['name'] == 'Root'
          and rbf_view['summary']['kinds'] == {'object': 1}
          and rbf_view['summary']['descriptors'] == 1)
    try:
        _rbf.parse(rbf_raw + b'\0')
        rbf_extra_refused = False
    except ValueError:
        rbf_extra_refused = True
    check('RBF0 trailing bytes refuse the tree', rbf_extra_refused)
    try:
        _rbf.parse(rbf_raw, max_nodes=1)
        rbf_budget_refused = False
    except _rbf.RbfLimitError:
        rbf_budget_refused = True
    check('RBF0 descriptors share the token output budget', rbf_budget_refused)

    from . import rbf_rigs as _rigs
    rig_bytes = bytearray(b'RBF0\xfb\xff\x01\x00')
    rig_names = {}
    def rig_token(name, kind):
        key = (name, kind)
        if key not in rig_names:
            rig_names[key] = len(rig_names)
            raw = name.encode('ascii')
            rig_bytes.extend(_s.pack('<HH', rig_names[key] | kind << 12, len(raw)) + raw)
        else:
            rig_bytes.extend(_s.pack('<H', rig_names[key] | kind << 12))
    def rig_object(name, attributes=0):
        rig_token(name, 0)
        rig_bytes.extend(bytes(4) + _s.pack('<H', attributes))
    rig_object('rage__crRigSetManager')
    rig_object('RigSet')
    rig_object('Item', 1)
    rig_token('key', 6)
    rig_bytes.extend(_s.pack('<H', 8) + b'authored')
    rig_object('Entries')
    rig_object('Item')
    for field, value in (('Dictionary', b'D'), ('Rig', b'R'), ('Group', b'G')):
        rig_object(field)
        rig_bytes.extend(b'\xfd\xff' + _s.pack('<I', len(value) + 1) + value + b'\0' + b'\xff\xff')
    rig_token('Priority', 1)
    rig_bytes.extend(_s.pack('<Q', 0xffffffffffffffff) + b'\xff\xff' * 5)
    rig_tree = _rbf.parse(bytes(rig_bytes))
    rig_view = _rigs.inspect_tree(rig_tree)
    check('RBF rig-set view preserves literal fields and raw Priority bits',
          rig_view['status'] == 'complete' and rig_view['summary']['selected_entries'] == 1
          and rig_view['rig_sets'][0]['entries'][0]['fields']['Priority_bits'] == '0xffffffffffffffff'
          and rig_view['rig_index'][0]['rig'] == 'R')
    check('RBF rig filter is exact literal matching',
          _rigs.inspect_tree(rig_tree, rig='R')['summary']['selected_entries'] == 1
          and _rigs.inspect_tree(rig_tree, rig='r')['summary']['selected_entries'] == 0)
    bad_rig_tree = dict(rig_tree, nodes=[dict(n) for n in rig_tree['nodes']])
    bad_rig_tree['nodes'][1]['children'] = [1]
    refused_rigs = _rigs.inspect_tree(bad_rig_tree, name='no-match')
    check('RBF rig profile validates cycles before filtering without prefix rows',
          refused_rigs['status'] == 'unresolved' and refused_rigs['rig_sets'] == []
          and refused_rigs['rig_index'] == [])

    from . import move as _move
    move_raw = bytearray(b'MoVE' + _s.pack('<I', 19) + bytes(24))
    move_raw.extend(_s.pack('<2I', 1, 0x11223344) + _s.pack('<I', 0))
    move_raw.extend(_s.pack('<I', 0x12345678) + _s.pack('<I', 1) + _s.pack('<IB', 0x55667788, 255))
    move_raw.extend(bytes(range(10)) + b'opaque!')
    _s.pack_into('<I', move_raw, 24, len(move_raw) - 46 - 5)
    move_view = _move.parse(bytes(move_raw))
    check('MoVE counted envelope spans exactly partition authored input',
          move_view['status'] == 'partial' and move_view['summary']['word_rows'] == 1
          and move_view['tables'][2]['records'][0]['raw_tag'] == 255
          and sum(r['byte_length'] for r in move_view['regions']) == len(move_raw))
    try:
        _move.parse(bytes(move_raw) + b'\0')
        move_length_refused = False
    except ValueError:
        move_length_refused = True
    check('MoVE redundant length check refuses appended bytes', move_length_refused)
    try:
        _move.parse(bytes(move_raw), max_nodes=move_view['summary']['nodes'] - 1)
        move_budget_refused = False
    except _move.MoveLimitError:
        move_budget_refused = True
    check('MoVE table rows and regions share the metadata budget', move_budget_refused)

    from . import move_objects as _move_objects
    move_payload = bytearray(104)
    _s.pack_into('<HHI', move_payload, 0, 1, 0, 0xabcdef01)
    _s.pack_into('<H', move_payload, 18, 1)
    _s.pack_into('<I', move_payload, 36, 60)
    _s.pack_into('<3I', move_payload, 84, 12, 0x12345678, 4)
    _s.pack_into('<HHI', move_payload, 96, 22, 0, 0x12345678)
    object_view = _move_objects.inspect_payload(bytes(move_payload), 0, len(move_payload))
    check('MoVE immediate references use field-relative offsets and redundant headers',
          object_view['status'] == 'complete' and object_view['summary']['references'] == 1
          and object_view['references'][0]['target_data_offset'] == 96
          and 'children' not in object_view['references'][0])
    _s.pack_into('<I', move_payload, 88, 0x87654321)
    bad_object_view = _move_objects.inspect_payload(bytes(move_payload), 0, len(move_payload))
    check('MoVE mismatched child hashes refuse without prefix references',
          bad_object_view['status'] == 'unresolved' and bad_object_view['references'] == [])
    try:
        _move_objects.inspect_payload(bytes(move_payload), 0, len(move_payload),
                                      max_nodes=object_view['summary']['nodes'] - 1)
        object_budget_refused = False
    except _move.MoveLimitError:
        object_budget_refused = True
    check('MoVE object spans share an explicit metadata budget', object_budget_refused)

    from . import audio_pcm as _pcm
    pcm_packet_block = _s.pack('<H', 3) + b'abc' + bytes(2043)
    check('WAV packet framing reads exact authored records with zero block padding',
          _pcm.strict_packets(pcm_packet_block) == [b'abc'])
    bad_pcm_block = bytearray(pcm_packet_block)
    bad_pcm_block[-1] = 1
    try:
        _pcm.strict_packets(bytes(bad_pcm_block))
        pcm_padding_refused = False
    except ValueError:
        pcm_padding_refused = True
    check('WAV framing refuses nonzero padding instead of dropping bytes', pcm_padding_refused)
    pcm_bytes = _s.pack('<4h', -32768, -1, 0, 32767)
    pcm_wav = _pcm.wav_bytes(pcm_bytes, channels=1)
    check('WAV wraps exact PCM16 bytes without a decoder dependency',
          pcm_wav[:4] == b'RIFF' and pcm_wav[8:12] == b'WAVE'
          and _s.unpack_from('<I', pcm_wav, 24)[0] == 48000
          and pcm_wav[44:] == pcm_bytes)

    from . import audio_ogg as _audio_ogg
    declared_ogg, declared_info = _audio_ogg.ogg_opus([b'\0'] * 3, 600, pre_skip=0)
    check('declared Ogg retains the packet prefix and exact final granule',
          declared_ogg[:4] == b'OggS' and declared_info['retained_packet_count'] == 2
          and declared_info['dropped_tail_packets'] == 1 and declared_info['final_granule'] == 600)
    boundary_ogg, boundary_info = _audio_ogg.ogg_opus([b'\0'] * 3, 960, pre_skip=0)
    check('declared Ogg handles an exact packet-boundary end without an extra packet',
          boundary_info['retained_packet_count'] == 2 and boundary_info['final_packet_trim_frames'] == 0)
    try:
        _audio_ogg.ogg_opus([b'\0', b'\x02'], 1, pre_skip=0)
        malformed_tail_refused = False
    except ValueError:
        malformed_tail_refused = True
    check('declared Ogg validates omitted source packet tails before emission', malformed_tail_refused)

    from . import audio_music_pcm as _music_pcm
    music_descriptor = (_s.pack('<3I', 1, 4096, 1)
                        + _s.pack('<IIHHB3x', 7, 4, 0, 48000, 11))
    music_block_header = _s.pack('<6I', 0xffffffff, 1, 0, 480, 0, 0) + _s.pack('<I', 0)
    music_packet_block = _s.pack('<H', 1) + b'\0' + bytes(2045)
    music_block = music_block_header + bytes(2048-len(music_block_header)) + music_packet_block
    music_bank = music_descriptor + bytes(2048-len(music_descriptor)) + music_block
    music_entry = dict(data_offset=2048, data_bytes=4096, music_offset=0, music_size=28,
        music=dict(blocks=1, chunk_bytes=4096, channels=[dict(index=0, id=7, samples=4,
                                                          sample_rate=48000, codec=11)]))
    music_storage = _music_pcm.inspect_channels(music_bank, music_entry)
    check('music WAV framing validates full channel allocations without a decoder',
          music_storage['summary']['supported_channels'] == 1
          and music_storage['channels'][0]['spans'][0]['data_offset'] == 4096)
    try:
        _music_pcm.inspect_channels(music_bank[:-1], music_entry)
        music_truncation_refused = False
    except ValueError:
        music_truncation_refused = True
    check('music WAV framing cannot consume a truncated allocation', music_truncation_refused)
    two_descriptor = _s.pack('<3I', 2, 4096, 1) + music_descriptor[12:]
    second_music_block = bytearray(music_block)
    _s.pack_into('<I', second_music_block, 8, 1)
    _s.pack_into('<I', second_music_block, 24, 479)
    two_music_bank = two_descriptor + bytes(2048-len(two_descriptor)) + music_block + bytes(second_music_block)
    two_music_entry = dict(music_entry, data_bytes=8192,
        music=dict(music_entry['music'], blocks=2))
    try:
        _music_pcm.extract_wav(two_music_bank, two_music_entry)
        unknown_music_skip_refused = False
    except _music_pcm.MusicUnsupportedError:
        unknown_music_skip_refused = True
    check('music WAV refuses unconfirmed nonzero skips before decoder loading', unknown_music_skip_refused)

    from . import move_children as _move_children
    descriptor_child = bytearray(48)
    _s.pack_into('<HHI', descriptor_child, 0, 22, 0, 0x12345678)
    descriptor_child[18:20] = bytes((1, 1))
    _s.pack_into('<4I', descriptor_child, 32, 0, 12, 28, 1)
    descriptor_child.extend(bytes(16) + _s.pack('<I', 20))
    descriptor_child.extend(_s.pack('<IH6B', 12, 0, 0, 0, 0, 0, 0, 0))
    descriptor_child.extend(_s.pack('<HHI', 31337, 0, 0x87654321))
    child_root = bytearray(84)
    _s.pack_into('<HHI', child_root, 0, 1, 0, 0xabcdef01)
    _s.pack_into('<H', child_root, 18, 1)
    _s.pack_into('<I', child_root, 36, 60)
    child_root.extend(_s.pack('<3I', 12, 0x12345678, 4) + descriptor_child)
    child_view = _move_children.inspect_payload(bytes(child_root), 0, len(child_root))
    check('MoVE child prefixes validate extension lengths and descriptor spans',
          child_view['status'] == 'complete' and child_view['summary']['resolved'] == 1
          and child_view['children'][0]['extensions'][0]['byte_length'] == 20
          and child_view['children'][0]['descriptor_table']['data_offset'] == 164)
    bad_child_root = bytearray(child_root)
    _s.pack_into('<I', bad_child_root, 160, 24)
    bad_child_view = _move_children.inspect_payload(bytes(bad_child_root), 0, len(bad_child_root))
    check('MoVE malformed child prefixes preserve explicit unsupported status without prefix records',
          bad_child_view['summary']['unresolved'] == 1
          and bad_child_view['children'][0]['descriptors'] == [])
    try:
        _move_children.inspect_payload(bytes(child_root), 0, len(child_root),
                                       max_nodes=child_view['summary']['nodes']-1)
        child_budget_refused = False
    except _move.MoveLimitError:
        child_budget_refused = True
    check('MoVE child prefix rows share a bounded output budget', child_budget_refused)

    # Contextual text links select an existing bounded pool entry, without a
    # global schema type annotation or a second decoded string observation.
    text_schema = (b'LSCH' + _s.pack('>I', 56)
        + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa' * 8, 24, 0, 1)
        + _s.pack('<4I', 0x12345678, 0, 0x44, 0))
    text_body = (b'PSIN' + _s.pack('>I', 96)
        + _s.pack('<II', 0x11223344, 24) + b'\xaa' * 8
        + _s.pack('<II', 0x10, 11) + b'\xaa' * 8 + b'p' * 8
        + _s.pack('<QHHIQ', (6 << 20) | 2, 4, 5, 1, 0) + bytes(8)
        + b'Alpha\0Beta\0' + bytes(5))
    text_report = _instances.decode_instances(instance_fixture(text_schema, text_body))
    text_field = text_report['blocks'][0]['records'][0]['fields'][0]
    check('PSIN contextual text header links an existing exact ASCII pool entry',
          text_field['text_reference']['status'] == 'pool_element_reference'
          and text_field['text_reference']['pool_element_index'] == 1
          and text_report['summary']['decoded_values'] == 2 and text_field['type_name'] is None)
    bad_text_body = bytearray(text_body)
    _s.pack_into('<Q', bad_text_body, 48, (7 << 20) | 2)
    bad_text = _instances.decode_instances(instance_fixture(text_schema, bad_text_body))
    check('PSIN contextual text rejects an interior substring without guessing a target',
          bad_text['summary']['text_reference_fields_unresolved'] == 1
          and 'pool_element_index' not in bad_text['blocks'][0]['records'][0]['fields'][0]['text_reference'])
    bad_text_header = bytearray(text_body)
    _s.pack_into('<H', bad_text_header, 56, 3)
    bad_text = _instances.decode_instances(instance_fixture(text_schema, bad_text_header))
    check('PSIN contextual text rejects inconsistent lengths while preserving pool values',
          bad_text['summary']['text_reference_fields_unresolved'] == 1
          and bad_text['summary']['decoded_values'] == 2)

    from . import audio_music_skips as _music_skips
    overlap_packet = _s.pack('<H', 2) + b'\x08A' + bytes(2044)
    overlap_first = music_block_header + bytes(2048-len(music_block_header)) + overlap_packet
    overlap_second = bytearray(overlap_first)
    _s.pack_into('<I', overlap_second, 8, 960)
    overlap_bank = two_descriptor + bytes(2048-len(two_descriptor)) + overlap_first + bytes(overlap_second)
    overlap_view = _music_skips.inspect_channels(overlap_bank, two_music_entry,
                                                skip_policy='verified-overlap')
    check('music overlap verifies whole compressed packet identity before decoder loading',
          overlap_view['channels'][0]['supported_wav']
          and overlap_view['channels'][0]['packet_overlap'][1]['repeated_frames'] == 960)
    bad_overlap_bank = bytearray(overlap_bank)
    bad_overlap_bank[8195] = ord('B')
    bad_overlap = _music_skips.inspect_channels(bytes(bad_overlap_bank), two_music_entry,
                                               skip_policy='verified-overlap')
    check('music overlap refuses same-duration packets with different compressed bytes',
          not bad_overlap['channels'][0]['supported_wav'])
    check('music overlap remains opt-in and preserves the original zero policy',
          _music_skips.inspect_channels(overlap_bank, two_music_entry)
              == _music_pcm.inspect_channels(overlap_bank, two_music_entry))

    from . import move_tail_forms as _move_tail_forms
    tail_kind3 = bytearray(84)
    _s.pack_into('<HHI', tail_kind3, 0, 3, 0, 0x12345678)
    tail_kind3[18] = 1
    _s.pack_into('<I', tail_kind3, 8, 112)
    _s.pack_into('<I', tail_kind3, 80, 1)
    tail_kind3.extend(_s.pack('<5I', 20, 1, 40, 0x87654321, 20))
    tail_kind3.extend(_s.pack('<HH', 16, 257) + bytes(12))
    tail_kind3.extend(_s.pack('<HHI', 22, 0, 0x87654321) + b'body' + b'opaque tail!')
    tail_parent = bytearray(48)
    _s.pack_into('<HHI', tail_parent, 0, 22, 0, 0xabcdef01)
    _s.pack_into('<H', tail_parent, 18, 1)
    _s.pack_into('<3I', tail_parent, 32, 0, 12, 8)
    tail_payload = bytes(tail_parent) + bytes(tail_kind3)
    tail_view = _move_tail_forms.inspect_payload(tail_payload, 0, len(tail_payload))
    check('MoVE kind-3 storage bounds reference rows and counted opaque records',
          tail_view['status'] == 'complete' and tail_view['summary']['references'] == 1
          and tail_view['forms'][0]['records'][0]['byte_length'] == 16)
    bad_tail = bytearray(tail_payload)
    _s.pack_into('<I', bad_tail, 48 + 96, 0)
    bad_tail_view = _move_tail_forms.inspect_payload(bytes(bad_tail), 0, len(bad_tail))
    check('MoVE kind-3 hash mismatch emits no partial deeper records',
          bad_tail_view['summary']['unresolved'] == 1
          and bad_tail_view['forms'][0]['references'] == []
          and bad_tail_view['forms'][0]['records'] == [])
    try:
        _move_tail_forms.inspect_payload(tail_payload, 0, len(tail_payload),
                                        max_nodes=tail_view['summary']['nodes']-1)
        tail_budget_refused = False
    except _move.MoveLimitError:
        tail_budget_refused = True
    check('MoVE kind-3 references and opaque records share a metadata budget', tail_budget_refused)

    # Kind-12 stores five counted groups. Cell bits remain opaque.
    counted_header = bytearray(52)
    _s.pack_into('<HHI', counted_header, 0, 12, 0, 0x12345678)
    _s.pack_into('<I', counted_header, 12, 0x1156)
    counted_cells = (bytes(counted_header) + _s.pack('<IIQQ', 2, 10, 0xffffffffffffffff, 7)
                     + _s.pack('<4I', 0, 0, 0, 0))
    counted_payload = bytes(tail_parent) + counted_cells
    counted_view = _move_tail_forms.inspect_payload(counted_payload, 0, len(counted_payload))
    check('MoVE kind-12 bounds five counted groups and retains opaque cell bits once',
          counted_view['status'] == 'complete' and counted_view['summary']['opaque_cells'] == 2
          and len(counted_view['forms'][0]['groups']) == 5
          and counted_view['forms'][0]['records'] == [])
    bad_counted = bytearray(counted_payload)
    _s.pack_into('<I', bad_counted, 48 + 56, 0x8000000a)
    bad_counted_view = _move_tail_forms.inspect_payload(bytes(bad_counted), 0, len(bad_counted))
    check('MoVE kind-12 rejects nonzero unused selector bits without prefix groups',
          bad_counted_view['summary']['unresolved'] == 1
          and 'groups' not in bad_counted_view['forms'][0])
    try:
        _move_tail_forms.inspect_payload(counted_payload, 0, len(counted_payload),
                                        max_nodes=counted_view['summary']['nodes']-1)
        counted_budget_refused = False
    except _move.MoveLimitError:
        counted_budget_refused = True
    check('MoVE kind-12 cells and groups share the output budget', counted_budget_refused)

    from . import psin_nested_maps as _nested_maps
    nested_owner_fields = [
        _schema.SchemaField(0, 0x100, 0, 0x15, 0),
        _schema.SchemaField(16, 0x100, 0, 0x4a, 0),
        _schema.SchemaField(32, 0x100, 0, 0x4a, 0),
        _schema.SchemaField(48, 0x100, 0, 0x71, (2 << 16) | 1),
        _schema.SchemaField(64, 101, 0, 0x71, 3 << 16)]
    nested_entry_fields = [
        _schema.SchemaField(0, 102, 0, 0x15, 0),
        _schema.SchemaField(16, 0x100, 0, 0x4a, 0),
        _schema.SchemaField(32, 0x100, 0, 0x4a, 0),
        _schema.SchemaField(48, 103, 8, 0x71, (2 << 16) | 1)]
    nested_owner = _schema.SchemaStructure(8, 0x11223344, 0, 0, 0, 24, 0, nested_owner_fields)
    nested_entry = _schema.SchemaStructure(40, 0x22334455, 0, 0, 0, 32, 0, nested_entry_fields)
    nested_data = _s.pack('<QQHHI', 1, 2, 1, 1, 0) + bytes(40)
    nested_blocks = [_instances.InstanceBlock(0, 8, 0x11223344, 24, 0),
                     _instances.InstanceBlock(1, 24, 0x22334455, 32, 32)]
    def nested_resolve(data=nested_data, structures=None):
        return _nested_maps.resolve_entries(data, 0, nested_owner_fields[4], nested_owner,
            24, nested_blocks, local_owner=True,
            local_structures={0x22334455: [nested_entry]} if structures is None else structures,
            consume=lambda: None)
    nested_link = nested_resolve()
    check('PSIN nested maps compare local descriptor trees and link existing bounded rows',
          nested_link['status'] == 'complete' and nested_link['key_type'] == 'opaque'
          and nested_link['entries'][0]['record_index'] == 0
          and 'value' not in nested_link['entries'][0])
    from dataclasses import replace as _replace
    wrong_nested_entry = _replace(nested_entry, fields=[
        _replace(nested_entry_fields[0], type_word=0x4a)] + nested_entry_fields[1:])
    mismatched_nested = nested_resolve(structures={0x22334455: [wrong_nested_entry]})
    check('PSIN nested maps refuse different descriptor trees without prefix links',
          mismatched_nested['status'] == 'unresolved' and mismatched_nested['entries'] == [])
    empty_nested = nested_resolve(_s.pack('<QQHHI', 1, 0, 0, 0, 0) + bytes(40))
    check('PSIN nested maps leave unvalidated empty profiles explicit',
          empty_nested['status'] == 'unresolved' and 'empty' in empty_nested['reason'])

    from . import anim_bitrows as _anim_bitrows
    bit_prefix = (_s.pack('<III', 5, 0xdeadbeef, 0x7fc00000)
                  + _s.pack('<6I', 3, 19, 1, 0x80000000, 0x7f800000, 0x12345678))
    bit_rows = _s.pack('<3I', 1, 127, 255)
    bit_directory = (_s.pack('<11H', 0, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0)
                     + _s.pack('<8H', 0, 8, 8, 8, 1, 8, 8, 8))
    bit_end = 32 + len(bit_prefix) + len(bit_rows) + len(bit_directory)
    bit_header = _s.pack('<5I5H2B', 0x12345678, bit_end-32, 0, len(bit_prefix),
                         bit_end, 2, 3, 4, 6, 5, 11, 0)
    bit_buffer = bit_header + bit_prefix + bit_rows + bit_directory
    def inspect_bit_buffer(data):
        return _anim_bitrows.inspect_buffer(data, 0, len(data), 2, consume=lambda n=1: None)
    bit_view = inspect_bit_buffer(bit_buffer)
    check('animation counted width tables explain complete opaque row widths',
          bit_view['status'] == 'complete' and bit_view['row_layout']['active_bits_per_row'] == 8
          and [int(r['raw_bits'], 16) for r in bit_view['rows']] == [1, 127, 255]
          and 'unconfirmed' in bit_view['association_status'])
    bad_bit_padding = bytearray(bit_buffer)
    _s.pack_into('<I', bad_bit_padding, 68, 1 << 8)
    bad_bit_view = inspect_bit_buffer(bytes(bad_bit_padding))
    check('animation bit rows reject nonzero high padding without partial rows',
          bad_bit_view['status'] == 'unresolved' and bad_bit_view['rows'] == []
          and bad_bit_view['variable_width_records'] == [])
    bad_bit_extent = bytearray(bit_buffer)
    _s.pack_into('<H', bad_bit_extent, 26, 5)
    bad_bit_view = inspect_bit_buffer(bytes(bad_bit_extent))
    check('animation variable width-table count must exhaust its independent extent',
          bad_bit_view['status'] == 'unresolved' and bad_bit_view['fixed_width_records'] == [])

    from . import psin_resource_header as _resource_header
    lrsc_header = (b'0DRP' + _s.pack('<I', 122) + bytes(8) + _s.pack('<Q', 1)
                   + b'\xbb' * 32 + _s.pack('<4H', 1, 0, 2, 0) + b'\xbb' * 8 + bytes(8))
    lrsc_data = instance_fixture(text_schema, text_body, lrsc=lrsc_header)
    lrsc_view = _resource_header.inspect(lrsc_data)
    check('PSIN LRSC header counts select one bounded local-record candidate',
          lrsc_view['status'] == 'complete' and lrsc_view['counts']['blocks'] == 2
          and lrsc_view['record_candidate']['block_index'] == 0
          and lrsc_view['record_candidate']['status'] == 'candidate'
          and 'fields' not in lrsc_view['record_candidate'])
    bad_lrsc = bytearray(lrsc_header)
    _s.pack_into('<H', bad_lrsc, 56, 2)
    bad_lrsc_view = _resource_header.inspect(instance_fixture(text_schema, text_body, lrsc=bytes(bad_lrsc)))
    check('PSIN LRSC header rejects mismatched independent counts atomically',
          bad_lrsc_view['status'] == 'unresolved' and 'record_candidate' not in bad_lrsc_view
          and 'header' not in bad_lrsc_view)
    _s.pack_into('<H', bad_lrsc, 56, 1)
    _s.pack_into('<Q', bad_lrsc, 16, (1 << 20) | 1)
    bad_lrsc_view = _resource_header.inspect(instance_fixture(text_schema, text_body, lrsc=bytes(bad_lrsc)))
    check('PSIN LRSC selector retains its full word without masking an offset',
          bad_lrsc_view['status'] == 'unresolved' and 'record_candidate' not in bad_lrsc_view)

    kind11_header = bytearray(44)
    _s.pack_into('<HHII', kind11_header, 0, 11, 0, 0x12345678, 0x556a)
    kind11_payload = bytes(tail_parent) + bytes(kind11_header) + _s.pack('<HHI', 31337, 1, 0x87654321)
    kind11_view = _move_tail_forms.inspect_payload(kind11_payload, 0, len(kind11_payload))
    check('MoVE kind-11 exposes checked selector headers while keeping remainders opaque',
          kind11_view['status'] == 'complete' and kind11_view['summary']['header_selector_fields'] == 10
          and kind11_view['forms'][0]['header']['byte_length'] == 44
          and kind11_view['forms'][0]['references'] == [])
    bad_kind11 = bytearray(kind11_payload)
    _s.pack_into('<I', bad_kind11, 48 + 24, 1)
    bad_kind11_view = _move_tail_forms.inspect_payload(bytes(bad_kind11), 0, len(bad_kind11))
    check('MoVE kind-11 rejects inconsistent zero slots without prefix metadata',
          bad_kind11_view['summary']['unresolved'] == 1
          and 'header' not in bad_kind11_view['forms'][0]
          and bad_kind11_view['forms'][0]['opaque_regions'] == [])
    try:
        _move_tail_forms.inspect_payload(kind11_payload, 0, len(kind11_payload),
                                        max_nodes=kind11_view['summary']['nodes']-1)
        kind11_budget_refused = False
    except _move.MoveLimitError:
        kind11_budget_refused = True
    check('MoVE kind-11 selector metadata shares the node budget', kind11_budget_refused)

    from . import anim_lookups as _anim_lookups
    lookup_prefix = (_s.pack('<3I', 5, 0x7fc00000, 0x80000000)
                     + _s.pack('<6I', 2, 5, 1, 0x80000000, 0x7f800000, 0x7ce1))
    lookup_rows = _s.pack('<4I', 0, 33, 66, 99)
    lookup_end = 32 + len(lookup_prefix) + len(lookup_rows) + len(bit_directory)
    lookup_header = _s.pack('<5I5H2B', 0x12345678, lookup_end-32, 0,
                           len(lookup_prefix), lookup_end, 2, 4, 4, 6, 5, 11, 0)
    lookup_buffer = lookup_header + lookup_prefix + lookup_rows + bit_directory
    def inspect_lookup(data):
        return _anim_lookups.inspect_buffer(data, 0, len(data), 2, consume=lambda n=1: None)
    lookup_view = inspect_lookup(lookup_buffer)
    check('animation source-order lookup candidates retain raw entries and uncertain assignments',
          lookup_view['status'] == 'complete' and lookup_view['entry_count'] == 4
          and [int(e['raw_bits'], 16) for e in lookup_view['lookup_candidates'][0]['entries']] == [1, 7, 31, 0]
          and 'unconfirmed' in lookup_view['association_status'])
    bad_lookup = bytearray(lookup_buffer)
    _s.pack_into('<I', bad_lookup, 76, 34)
    bad_lookup_view = inspect_lookup(bytes(bad_lookup))
    check('animation lookup candidates reject sparse observed indices without prefix entries',
          bad_lookup_view['status'] == 'unresolved' and bad_lookup_view['lookup_candidates'] == [])
    bad_lookup = bytearray(lookup_buffer)
    _s.pack_into('<I', bad_lookup, 64, 0x80007ce1)
    bad_lookup_view = inspect_lookup(bytes(bad_lookup))
    check('animation lookup candidates check high packed-entry padding',
          bad_lookup_view['status'] == 'unresolved' and bad_lookup_view['lookup_candidates'] == [])

    from . import psin_record_graph as _record_graph
    graph_lrsc = (b'0DRP' + _s.pack('<I', 122) + bytes(8) + _s.pack('<Q', 1)
                  + b'\xbb'*32 + _s.pack('<4H', 2, 0, 2, 0) + b'\xbb'*8 + bytes(8))
    graph_header = _resource_header.inspect(reference_field_fixture(lrsc=graph_lrsc))
    graph_view = _record_graph.inspect(field_report, graph_header)
    check('PSIN record graph links existing rows with bounded candidate reachability',
          graph_view['summary']['record_nodes'] == 3 and graph_view['summary']['record_edges'] == 1
          and graph_view['reachability']['reachable_records'] == 2
          and 'fields' not in graph_view['nodes'][0] and 'value' not in graph_view['nodes'][0])
    graph_cycle = _record_graph.inspect(field_cycle)
    check('PSIN record graph retains finite self-links without inventing an anchor',
          len(graph_cycle['nodes']) == 1 and len(graph_cycle['edges']) == 1
          and graph_cycle['edges'][0]['source_node_index'] == graph_cycle['edges'][0]['target_node_index']
          and graph_cycle['reachability']['status'] == 'unanchored')
    try:
        _record_graph.inspect(field_report, graph_header, max_nodes=graph_view['summary']['nodes']-1)
        graph_budget_refused = False
    except _record_graph.RecordGraphLimitError:
        graph_budget_refused = True
    check('PSIN graph nodes and field-path edges share a bounded output budget', graph_budget_refused)

    from . import anim_prefix as _anim_prefix
    mixed_prefix = (_s.pack('<4I', 0xffffffff, 0x7fc00000, 0x80000000, 0xdeadbeef)
                    + _s.pack('<3I', 5, 1, 2)
                    + _s.pack('<6I', 3, 19, 1, 0x80000000, 0x7f800000, 0x12345678)
                    + _s.pack('<I', 13) + bytes(48))
    mixed_directory = _s.pack('<11H', 1, 0, 1, 0, 1, 1, 0, 0, 0, 0, 1)
    mixed_directory += _s.pack('<4H', 0, 8, 8, 8) * 5
    mixed_end = 32 + len(mixed_prefix) + len(bit_rows) + len(mixed_directory)
    mixed_buffer = (_s.pack('<5I5H2B', 0x12345678, mixed_end-32, 0, len(mixed_prefix),
                    mixed_end, 2, 3, 4, 6, 5, 11, 0) + mixed_prefix + bit_rows + mixed_directory)
    def inspect_mixed_prefix(data, consume=lambda n=1: None):
        return _anim_prefix.inspect_buffer(data, 0, len(data), 2, consume=consume)
    mixed_view = inspect_mixed_prefix(mixed_buffer)
    check('animation mixed prefix retains raw word groupings and bounded opaque records',
          mixed_view['status'] == 'complete' and mixed_view['word_count'] == 4
          and mixed_view['opaque_record_count'] == 1
          and mixed_view['triplet_records'][0]['raw_words'][1] == '0x7fc00000'
          and 'unconfirmed' in mixed_view['association_status'])
    bad_mixed = bytearray(mixed_buffer)
    _s.pack_into('<I', bad_mixed, 84, 14)
    bad_mixed_view = inspect_mixed_prefix(bytes(bad_mixed))
    check('animation counted prefix must exhaust its independently bounded remainder',
          bad_mixed_view['status'] == 'unresolved' and bad_mixed_view['regions'] == []
          and bad_mixed_view['triplet_records'] == [])
    prefix_budget = [0]
    def count_prefix(amount=1):
        prefix_budget[0] += amount
    inspect_mixed_prefix(mixed_buffer, count_prefix)
    prefix_remaining = [prefix_budget[0]-1]
    def limit_prefix(amount=1):
        if amount > prefix_remaining[0]:
            raise _anim_resources.ResourceLimitError('authored mixed-prefix budget')
        prefix_remaining[0] -= amount
    try:
        inspect_mixed_prefix(mixed_buffer, limit_prefix)
        mixed_budget_refused = False
    except _anim_resources.ResourceLimitError:
        mixed_budget_refused = True
    check('animation raw prefix records share the existing metadata budget', mixed_budget_refused)

    kind28_header = bytearray(36)
    _s.pack_into('<HHIII', kind28_header, 0, 28, 0, 0x12345678, 0xabcdef01, 0xa)
    _s.pack_into('<I', kind28_header, 28, 0x7fc00001)
    kind28_payload = bytes(tail_parent) + bytes(kind28_header)
    kind28_view = _move_tail_forms.inspect_payload(kind28_payload, 0, len(kind28_payload))
    check('MoVE kind-28 retains measured whole-selector headers without field-width guesses',
          kind28_view['status'] == 'complete' and kind28_view['summary']['header_selector_fields'] == 16
          and kind28_view['forms'][0]['header']['byte_length'] == 36
          and 'field_byte_lengths' not in kind28_view['forms'][0]['header'])
    bad_kind28 = bytearray(kind28_payload)
    _s.pack_into('<I', bad_kind28, 48 + 12, 0x6)
    bad_kind28_view = _move_tail_forms.inspect_payload(bytes(bad_kind28), 0, len(bad_kind28))
    check('MoVE kind-28 refuses unfitted selector words without a partial prefix',
          bad_kind28_view['summary']['unresolved'] == 1
          and 'header' not in bad_kind28_view['forms'][0]
          and bad_kind28_view['forms'][0]['regions'] == [])
    try:
        _move_tail_forms.inspect_payload(kind28_payload, 0, len(kind28_payload),
                                        max_nodes=kind28_view['summary']['nodes']-1)
        kind28_budget_refused = False
    except _move.MoveLimitError:
        kind28_budget_refused = True
    check('MoVE kind-28 raw selector fields share the node budget', kind28_budget_refused)

    # Authored opaque-key map: descriptor equality links rows without reading keys.
    opaque_lsch = (b'LSCH' + _s.pack('>I', 152)
                   + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa'*8, 24, 0, 3)
                   + _s.pack('<4I8sIHH', 0x22334455, 0, 0, 0, b'\xaa'*8, 16, 0, 2)
                   + _s.pack('<4I', 0x100, 0, 0x054f, 0)
                   + _s.pack('<4I', 0x100, 0, 0x21, 0)
                   + _s.pack('<4I', 0x87654321, 0, 0x71, 1 << 16)
                   + _s.pack('<4I', 0x12345678, 0, 0x054f, 0)
                   + _s.pack('<4I', 0x23456789, 8, 0x21, 0))
    opaque_body = (b'PSIN' + _s.pack('>I', 112)
                   + _s.pack('<II', 0x11223344, 24) + b'\xaa'*8
                   + _s.pack('<II', 0x22334455, 32) + b'\xaa'*8 + b'p'*8
                   + _s.pack('<QQHHI', 1, 2, 2, 2, 0) + bytes(8)
                   + _s.pack('<QfI', 2, 0.5, 0) + _s.pack('<QfI', 1 << 63, 1.5, 0))
    opaque_report = _instances.decode_instances(instance_fixture(opaque_lsch, body=opaque_body))
    opaque_keys = [r['fields'][0] for r in opaque_report['blocks'][1]['records']]
    check('PSIN opaque-key maps link bounded typed rows while keys remain unknown',
          opaque_report['summary']['maps_resolved'] == 1
          and opaque_report['summary']['map_entries_linked'] == 2
          and opaque_report['summary']['decoded_values'] == 2
          and all(k['status'] == 'unresolved' and k['type_name'] is None
                  and 'reference' not in k and 'value' not in k for k in opaque_keys))
    opaque_graph = _record_graph.inspect(opaque_report)
    check('PSIN opaque-key map links enter the record graph without duplicating values',
          opaque_graph['summary']['record_edges'] == 2
          and opaque_graph['summary']['record_nodes'] == 3
          and opaque_graph['summary']['unsupported_associations'] == 0)
    bad_opaque_lsch = bytearray(opaque_lsch)
    _s.pack_into('<I', bad_opaque_lsch, 144, 0x4a)
    bad_opaque = _instances.decode_instances(instance_fixture(bad_opaque_lsch, body=opaque_body))
    bad_opaque_map = bad_opaque['blocks'][0]['records'][0]['fields'][2]['map']
    check('PSIN mismatched opaque-map descriptors refuse without partial links',
          bad_opaque_map['status'] == 'unresolved' and bad_opaque_map['entries'] == []
          and _record_graph.inspect(bad_opaque)['summary']['record_edges'] == 0)

    kind4_header = bytearray(36)
    _s.pack_into('<HHIII', kind4_header, 0, 4, 0, 0x12345678, 0x00880000, 1)
    _s.pack_into('<II', kind4_header, 16, 0xffffffff, 0x80000000)
    kind4_payload = bytes(tail_parent) + bytes(kind4_header) + _s.pack('<HHI', 31337, 1, 0x87654321)
    kind4_view = _move_tail_forms.inspect_payload(kind4_payload, 0, len(kind4_payload))
    check('MoVE kind-4 retains measured whole-word prefixes without pointer guesses',
          kind4_view['status'] == 'complete' and kind4_view['summary']['header_prefixes'] == 1
          and kind4_view['summary']['header_selector_fields'] == 0
          and kind4_view['forms'][0]['header']['byte_length'] == 36
          and kind4_view['forms'][0]['references'] == [])
    bad_kind4 = bytearray(kind4_payload)
    _s.pack_into('<I', bad_kind4, 48 + 12, 2)
    bad_kind4_view = _move_tail_forms.inspect_payload(bytes(bad_kind4), 0, len(bad_kind4))
    check('MoVE kind-4 refuses unfitted markers without partial header metadata',
          bad_kind4_view['summary']['unresolved'] == 1
          and 'header' not in bad_kind4_view['forms'][0]
          and bad_kind4_view['forms'][0]['regions'] == [])
    try:
        _move_tail_forms.inspect_payload(kind4_payload, 0, len(kind4_payload),
                                        max_nodes=kind4_view['summary']['nodes']-1)
        kind4_budget_refused = False
    except _move.MoveLimitError:
        kind4_budget_refused = True
    check('MoVE kind-4 prefixes share the node budget', kind4_budget_refused)

    # Authored complete PSIN with a compressed full page and stored terminal tail.
    stored_lsch = (b'LSCH' + _s.pack('>I', 40)
                   + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa'*8, 16, 0, 0))
    stored_body = (b'PSIN' + _s.pack('>I', 65568)
                   + _s.pack('<II', 0x11223344, 65536) + b'\xaa'*8 + b'p'*8 + bytes(65536))
    stored_data = instance_fixture(stored_lsch, body=stored_body)
    stored_first = _zl.compress(stored_data[:65536])
    stored_blob = stored_first + bytes(-len(stored_first) % 16) + stored_data[65536:]
    with tempfile.TemporaryDirectory() as stored_tmp:
        stored_path = os.path.join(stored_tmp, 'authored.rpf')
        with open(stored_path, 'wb') as fh:
            fh.write(stored_blob)
        stored_hits = list(_structured.recover(stored_path, start=0, limit=len(stored_blob)))
        check('PSIN recovery checks exact sections and checksum across a stored terminal tail',
              len(stored_hits) == 1 and stored_hits[0].data == stored_data
              and stored_hits[0].segment_storage == ['zlib', 'stored']
              and stored_hits[0].packed == len(stored_first) + len(stored_data) - 65536)
        check('PSIN stored-tail recovery stays inside the requested scan window',
              not list(_structured.recover(stored_path, start=0, limit=len(stored_blob)-1)))
        stored_bad = bytearray(stored_blob)
        stored_bad[-8] ^= 1
        with open(stored_path, 'wb') as fh:
            fh.write(stored_bad)
        check('PSIN recovery refuses stored-tail checksum corruption without partial output',
              not list(_structured.recover(stored_path, start=0, limit=len(stored_blob))))

    empty_lsch = (b'LSCH' + _s.pack('>I', 72)
                  + _s.pack('<4I8sIHH', 0x11223344, 0, 0, 0, b'\xaa'*8, 16, 0, 2)
                  + _s.pack('<4I', 0x100, 0, 5, 0x22334455)
                  + _s.pack('<4I', 101, 0, 0x52, 0))
    empty_body = (b'PSIN' + _s.pack('>I', 48)
                  + _s.pack('<II', 0x11223344, 16) + b'\xaa'*8 + b'p'*8 + bytes(16))
    empty_report = _instances.decode_instances(instance_fixture(empty_lsch, body=empty_body))
    empty_array = empty_report['blocks'][0]['records'][0]['fields'][1]['array']
    check('PSIN null-empty array headers retain missing element schemas without guessed strides',
          empty_array['status'] == 'complete' and empty_array['count'] == 0
          and empty_array['element_schema_status'] == 'missing'
          and empty_array['stride'] is None and empty_array['target'] is None
          and empty_report['summary']['decoded_values'] == 0)
    empty_graph = _record_graph.inspect(empty_report)
    check('PSIN null-empty array headers add no graph edges or unsupported associations',
          empty_graph['summary']['record_edges'] == 0
          and empty_graph['summary']['unsupported_associations'] == 0)
    empty_array['reference_bits'] = '0x0000000000000001'
    try:
        _record_graph.inspect(empty_report)
        empty_graph_refused = False
    except ValueError:
        empty_graph_refused = True
    check('PSIN null-empty graph profiles reject contradictory reference metadata', empty_graph_refused)

    extended_header = bytearray(60)
    _s.pack_into('<HHI', extended_header, 0, 12, 0, 0x12345678)
    _s.pack_into('<I', extended_header, 12, 0x1155)
    _s.pack_into('<I', extended_header, 44, 0x7fc00000)
    extended_cells = bytearray(extended_header)
    for count in (1, 0, 0, 0, 1):
        extended_cells.extend(_s.pack('<I', count))
        if count:
            extended_cells.extend(_s.pack('<IQ', 2, 0x800000007fc00000))
    extended_payload = bytes(tail_parent) + bytes(extended_cells) + _s.pack('<HHI', 31337, 1, 0x87654321)
    extended_view = _move_tail_forms.inspect_payload(extended_payload, 0, len(extended_payload))
    check('MoVE extended kind-12 headers retain five counted groups and opaque cells',
          extended_view['status'] == 'complete' and extended_view['summary']['counted_groups'] == 5
          and extended_view['summary']['opaque_cells'] == 2
          and extended_view['forms'][0]['regions'][0]['byte_length'] == 60
          and extended_view['forms'][0]['references'] == [])
    terminal_extended = _move_tail_forms.inspect_payload(extended_payload[:-8], 0, len(extended_payload)-8)
    check('MoVE extended kind-12 refuses an unvalidated terminal form without partial groups',
          terminal_extended['summary']['unresolved'] == 1
          and 'groups' not in terminal_extended['forms'][0])
    bad_extended = bytearray(extended_payload)
    _s.pack_into('<I', bad_extended, 48 + 12, 0x115a)
    bad_extended_view = _move_tail_forms.inspect_payload(bytes(bad_extended), 0, len(bad_extended))
    check('MoVE extended kind-12 keeps unfitted whole-word variants explicit',
          bad_extended_view['summary']['unresolved'] == 1
          and bad_extended_view['forms'][0]['regions'] == [])

    packed_float = (15 << 6) | ((14 << 6) << 11) | ((13 << 5) << 22)
    check('R11G11B10 unsigned-float previews preserve packed channel order',
          _bcn.decode_rgba(26, _s.pack('<I', packed_float), 1, 1) == bytes((255,128,64,255)))
    check('R32 float previews use the explicit numeric grayscale policy',
          _bcn.decode_rgba(41, _s.pack('<f', 0.5), 1, 1) == bytes((128,128,128,255)))
    check('RGBA32 float previews clip specials without replacing original DDS data',
          _bcn.decode_rgba(2, _s.pack('<4f', -1.0, 0.5, 2.0, float('nan')), 1, 1)
          == bytes((0,128,255,0)) and _bcn.decode_rgba(2, bytes(15), 1, 1) is None)

    selection_tex = _rds5.TtpTexture(0, 0x123, 0, 0, 0, 8, 8, 2, 71, 1, 2)
    selection_layout = _texture.layout_for(selection_tex)
    selection_data = bytearray(selection_layout.total)
    selection_expected = bytearray()
    for layer in range(2):
        for mip in range(2):
            color = (0xf800, 0x07e0, 0x001f, 0xffff)[layer*2+mip]
            encoded = _s.pack('<HHI', color, 0, 0)
            edge = (max(1, 8 >> mip)+3)//4
            for y in range(edge):
                for x in range(edge):
                    at = selection_layout.addr(mip, layer, x, y)
                    selection_data[at:at+8] = encoded
                    selection_expected.extend(encoded)
    selection_dds = _texture.dds_bytes(selection_tex, selection_layout, bytes(selection_data))
    cube_header = _texture.dds_header(8, 8, 2, 6, 71, cube=True)
    check('DDS arrays retain complete chains and cube headers count cubes',
          selection_dds[148:] == bytes(selection_expected)
          and _s.unpack_from('<I', cube_header, 140)[0] == 1
          and _s.unpack_from('<I', cube_header, 20)[0] == 32
          and _s.unpack_from('<I', selection_dds, 108)[0] & 8)
    selected, selected_w, selected_h, selected_meta = _texture.preview_subresource(
        selection_tex, selection_layout, bytes(selection_data), mip=1, slice_index=1)
    check('Texture preview selection retains the requested mip and array layer',
          (selected_w, selected_h) == (4,4) and selected_meta['png_mip_index'] == 1
          and selected_meta['png_slice_index'] == 1
          and _bcn.decode_rgba(71, selected, selected_w, selected_h) == bytes((255,255,255,255))*16)
    try:
        _texture.preview_subresource(selection_tex, selection_layout, bytes(selection_data), mip=2)
        selection_refused = False
    except ValueError:
        selection_refused = True
    check('Texture preview selection refuses an out-of-range mip without substitution', selection_refused)

    print(f"\n{len(failures)} failure(s)")
    return 0 if not failures else 1


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gta6x",
        description="Read-only explorer for the GTA VI Xbox 1.0.2.1 package "
                    "(RPF9 archives, RDS5 resources, plaintext Bink2/AWC media).",
    )
    parser.add_argument("--root", default=os.environ.get("GTA6_ROOT", DEFAULT_ROOT),
                        help="package directory (default: %(default)s)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)
    from . import rbf_cli
    rbf_cli.configure(sub)
    from . import move_cli
    move_cli.configure(sub)

    p = sub.add_parser("info", help="package overview and identity")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("headers", help="RPF9 header table + set fingerprint check")
    p.add_argument("files", nargs="*", help="specific .rpf files")
    p.set_defaults(func=cmd_headers)

    p = sub.add_parser("resources", help="RDS5 (.ttpf) header summary")
    p.add_argument("files", nargs="*")
    p.set_defaults(func=cmd_resources)

    def add_common(p):
        p.add_argument("files", nargs="*", help="specific archives (default: all)")
        p.add_argument("--archive", action="append",
                       help="filter archives by name fragment, e.g. --archive movies")
        p.add_argument("--kind", default="bink2,awc",
                       help="carrier kinds: bink2,bink1,awc (default: %(default)s)")
        p.add_argument("--limit", type=int, default=256,
                       help="MiB to scan per archive (default: %(default)s)")
        p.add_argument("--full", action="store_true", help="scan whole archives")
        p.add_argument("--align", type=int, default=0x1000, help="required alignment")
        p.add_argument("--no-align", action="store_true", help="do not require alignment")
        p.add_argument("--no-padding", action="store_true",
                       help="do not require 8 zero bytes before the magic")
        p.add_argument("--quiet", action="store_true", help="suppress progress output")
        p.add_argument("--spread", type=int, default=0,
                       help="sample N evenly spaced windows instead of the file head "
                            "(carriers cluster; suggested: 4)")

    p = sub.add_parser("anim", help="index animation streams and name tables")
    p.add_argument("files", nargs="*", help="specific archives (default: anim)")
    p.add_argument("--archive", action="append", default=[],
                   help="archive fragment (default: anim)")
    p.add_argument("--limit", type=int, default=64,
                   help="MiB to scan per archive (default 64)")
    p.add_argument("--full", action="store_true", help="scan whole archives")
    p.add_argument("--max", type=int, default=40, help="rows/stream cap hint")
    p.add_argument("--clips", action="store_true", help="print clip names")
    p.add_argument("--out", help="write anim.json and anim-names.txt")
    p.add_argument("--resources", action="store_true",
                   help="join bounded 0DRP resources and export raw schema/block metadata; curves remain unknown")
    p.add_argument("--max-nodes", type=int, default=100000,
                   help="total metadata node budget for --resources (default 100000)")
    p.add_argument("--clip-records", action="store_true",
                   help="link supported names to bounded clip-record prefixes; curves remain unknown")
    p.add_argument("--start", type=lambda value: int(value, 0),
                   help="compressed byte offset per archive for a bounded scan (decimal or 0x hex)")
    p.add_argument("--clip-components", action="store_true",
                   help="follow checked animation/component and opaque packed-buffer spans; implies --clip-records")
    p.add_argument("--packed-layout", action="store_true",
                   help="inspect bounded packed-header regions and raw channel rows; implies --clip-components")
    p.add_argument("--channel-layout", action="store_true",
                   help="inspect bounded packed-channel storage metadata; implies --packed-layout")
    p.add_argument("--storage-layout", action="store_true",
                   help="inspect bounded packed sample-storage rows; implies --channel-layout")
    p.add_argument("--prefix-layout", action="store_true",
                   help="inspect bounded mixed prefix words and counted opaque records; implies --bit-layout")
    p.add_argument("--lookup-candidates", action="store_true",
                   help="check source-order indexed-payload candidates; implies --bit-layout; assignments unconfirmed")
    p.add_argument("--bit-layout", action="store_true",
                   help="inspect supported packed bit-row profiles; implies --storage-layout")
    p.add_argument("--payload-layout", action="store_true",
                   help="inspect supported packed payload-word profiles; implies --storage-layout")
    p.set_defaults(func=cmd_anim)

    p = sub.add_parser("movies", help="Bink2 movie metadata browser and extractor")
    p.add_argument("files", nargs="*", help="specific archives (default: movies)")
    p.add_argument("--archive", action="append", default=[],
                   help="archive fragment (default: movies)")
    p.add_argument("--limit", type=int, default=256,
                   help="MiB to scan per archive (default 256)")
    p.add_argument("--full", action="store_true", help="scan whole archives")
    p.add_argument("--align", type=int, default=0x1000, help="required alignment")
    p.add_argument("--no-align", action="store_true")
    p.add_argument("--no-padding", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--spread", type=int, default=0,
                   help="sample N evenly spaced windows")
    p.add_argument("--min-duration", type=float, default=0.0,
                   help="minimum duration in seconds")
    p.add_argument("--max-duration", type=float, default=0.0,
                   help="maximum duration in seconds")
    p.add_argument("--min-width", type=int, default=0)
    p.add_argument("--min-height", type=int, default=0)
    p.add_argument("--min-size", type=int, default=0, help="minimum bytes")
    p.add_argument("--sort", choices=["offset", "size", "duration", "resolution"],
                   default="offset")
    p.add_argument("--max", type=int, default=40, help="rows to display")
    p.add_argument("--all", action="store_true", help="display every match")
    p.add_argument("--out", help="extract selected movies into this directory")
    p.add_argument("--manifest", help="manifest path (default <out>/movies.json)")
    p.set_defaults(func=cmd_movies)

    p = sub.add_parser("scan", help="find validated Bink2/Bink1/AWC carriers")
    add_common(p)
    p.add_argument("--max", type=int, default=40, help="rows to display")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("extract", help="carve carriers out to a directory")
    add_common(p)
    p.add_argument("--out", default="extracted", help="output directory")
    p.add_argument("--max-hits", type=int, default=0, help="cap number of carriers")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("verify", help="verify hashes against a shasum manifest")
    p.add_argument("manifest", help="path to <hash>  ./path manifest")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("report", help="write a markdown or HTML inventory report")
    p.add_argument("--out", default="gta6x-report.md")
    p.add_argument("--hash", action="store_true", help="include file hashes (slow: reads the payload)")
    p.add_argument("--title", default="GTA VI Xbox 1.0.2.1 package")
    p.add_argument("--with-media", action="store_true", help="include a media scan")
    p.add_argument("--limit", type=int, default=64, help="MiB per archive for the scan")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("tui", help="interactive terminal browser")
    p.add_argument("--db", help="browse a SQLite catalogue instead of the raw package")
    p.set_defaults(func=lambda a: _run_tui(a.root, getattr(a, "db", None)))

    p = sub.add_parser("zlib", help="carve zlib-compressed payloads (RPF/HDS5)")
    p.add_argument("files", nargs="*", help="specific archives (default: all)")
    p.add_argument("--archive", action="append", help="filter by name fragment")
    p.add_argument("--limit", type=int, default=64, help="MiB per archive (default: %(default)s)")
    p.add_argument("--full", action="store_true", help="scan whole archives")
    p.add_argument("--min-out", type=int, default=1024, help="minimum inflated size")
    p.add_argument("--quiet", action="store_true", help="suppress progress output")
    p.add_argument("--out", help="directory to write inflated blobs into")
    p.add_argument("--max", type=int, default=25, help="rows to display")
    p.set_defaults(func=cmd_zlib, spread=0, quiet=False, no_padding=False,
                   no_align=False, align=0x1000)
    p = sub.add_parser("catalog", help="carve + verify + index assets into a JSON catalog")
    p.add_argument("files", nargs="*", help="specific archives (default: all)")
    p.add_argument("--archive", action="append", help="filter by name fragment")
    p.add_argument("--limit", type=int, default=64, help="MiB per archive (default: %(default)s)")
    p.add_argument("--full", action="store_true", help="scan whole archives")
    p.add_argument("--min-out", type=int, default=512, help="minimum inflated size")
    p.add_argument("--out", default="gta6-catalog.json", help="catalog path (JSON)")
    p.add_argument("--db", help="write to a SQLite catalogue instead (recommended at scale)")
    p.add_argument("--skip-done", action="store_true", help="skip archives already in the DB")
    p.add_argument("--quiet", action="store_true", help="suppress per-archive progress")
    p.set_defaults(func=cmd_catalog, spread=0, quiet=False, no_padding=False,
                   no_align=False, align=0x1000)

    p = sub.add_parser("browse", help="render a searchable HTML browser from a catalog")
    p.add_argument("--catalog", default="gta6-catalog.json")
    p.add_argument("--db", help="render from a SQLite catalogue into a directory")
    p.add_argument("--chunk", type=int, default=4000, help="rows per data chunk")
    p.add_argument("--out", default="gta6-catalog.html")
    p.add_argument("--paths", help="optional paths.txt to include as a file tree")
    p.set_defaults(func=cmd_browse)

    p = sub.add_parser("psin", help="inspect PSIN containers, LSCH/LENM schemas and bounded values")
    p.add_argument("files", nargs="*")
    p.add_argument("--archive", action="append")
    p.add_argument("--limit", type=int, default=48, help="MiB per archive")
    p.add_argument("--full", action="store_true")
    p.add_argument("--max", type=int, default=12)
    p.add_argument("--schema", action="store_true",
                   help="browse LSCH types and LENM enums in verified resources; joins split pages")
    p.add_argument('--record-graph', action='store_true',
                   help='index checked local record associations and bounded candidate reachability (implies instances)')
    p.add_argument('--resource-header', action='store_true',
                   help='check LRSC header counts and a bounded local-record candidate (implies schema mode)')
    p.add_argument('--instances', action='store_true',
                   help='include bounded values, local array associations, low-ID pools and reference diagnostics (implies schema mode)')
    p.add_argument('--max-nodes', type=int, default=100000,
                   help='shared instance/header/record-graph output budget (default 100000)')
    p.add_argument('--max-depth', type=int, default=16,
                   help='embedded instance / graph reachability depth limit, 1..64 (default 16)')
    p.add_argument("--out", help="write schema/optional instance JSON to a file (implies --schema)")
    p.add_argument("--names", help="optional local name dictionary for schema hash candidates")
    p.add_argument('--registry', help='load a local PSIN cross-file schema registry')
    p.add_argument('--registry-out', help='build/extend a private registry from verified inputs')
    p.set_defaults(func=cmd_psin, spread=0, quiet=False, no_padding=False,
                   no_align=False, align=0x1000)

    p = sub.add_parser("get", help="extract one catalogued asset by sha256 or archive:offset")
    p.add_argument("id", help="sha256 prefix, or archive.rpf:0x<offset>")
    p.add_argument("--catalog", default="gta6-catalog.json")
    p.add_argument("--db", help="look the asset up in a SQLite catalogue")
    p.add_argument("--out", default="extracted-asset")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("hunt", help="score catalogued blobs for geometry-like floats")
    p.add_argument("--db", required=True, help="SQLite catalogue")
    p.add_argument("--kind", help="restrict to one kind (e.g. binary)")
    p.add_argument("--archive", help="restrict to archives matching a fragment")
    p.add_argument("--scan", type=int, default=800, help="blobs to scan")
    p.add_argument("--min-size", type=int, default=65536, help="minimum blob size")
    p.add_argument("--max", type=int, default=20, help="rows to display")
    p.add_argument("--window", type=int, default=32, help="windowed scoring, KiB per window")
    p.add_argument("--dump", type=int, default=0, help="dump N records at the best stride")
    p.set_defaults(func=cmd_hunt, spread=0, quiet=False, no_padding=False,
                   no_align=False, align=0x1000)

    p = sub.add_parser("names", help="build or query the joaat name dictionary")
    p.add_argument("action", choices=["build", "lookup"])
    p.add_argument("hash", nargs="?", help="hash to resolve (lookup)")
    p.add_argument("--out", default="names.json", help="output dictionary")
    p.add_argument("--index", default="names.json", help="dictionary to read")
    p.add_argument("--paths", default=None, help="extra recovered path list")
    p.add_argument("--no-shaders", action="store_true",
                   help="skip the shaders.rpf C-string scan")
    p.set_defaults(func=cmd_names)

    p = sub.add_parser("world", help="extract world/map data (SixNG backend)")
    p.add_argument("--kind", required=True, choices=sorted([
        "all", "collision", "handling", "interiors", "lights", "meta",
        "navmesh", "paths", "pso", "placements", "shaders", "surfaces",
        "vehicles"]), help="world data step")
    p.add_argument("--archive", help="RPF archive fragment (kind-specific default)")
    p.add_argument("--out", required=True, help="output directory")
    p.add_argument("--name", default="", help="regex on recovered names")
    p.add_argument("--exclude-name", default="", help="regex of names to skip")
    p.add_argument("--min-size", type=int, default=0, help="minimum entry size")
    p.add_argument("--limit", type=int, default=0, help="maximum entries")
    p.add_argument("--bbox", default="", help="world region minx,miny,maxx,maxy")
    p.add_argument("--dump", action="store_true", help="full meta dumps")
    p.add_argument("--roads-only", action="store_true", help="navmesh roads only")
    p.add_argument("--batches", action="store_true", help="placements: batches too")
    p.add_argument("--batches-only", action="store_true", help="placements: batches only")
    p.add_argument("--navmeshes", default="navmeshes", help="surfaces: navmesh archive")
    p.add_argument("--backend", default=None, help="path to the sixng executable")
    p.add_argument("--work", default=".sixng-work", help="backend work/index directory")
    p.set_defaults(func=cmd_world)

    p = sub.add_parser("models", help="list/extract drawables via the SixNG backend")
    p.add_argument("action", choices=["info", "index", "list", "extract"])
    p.add_argument("--archive", default="packs", help="archive id or fragment")
    p.add_argument("--kind", default="dr", help="resource type (dr, ft, txd, ...)")
    p.add_argument("--name", default=None, help="regex on recovered names")
    p.add_argument("--max", type=int, default=20, help="maximum entries (default 20)")
    p.add_argument("--out", help="output directory for extraction")
    p.add_argument("--work", default=".sixng-work", help="backend work/index directory")
    p.add_argument("--backend", default=None, help="path to the sixng executable")
    p.add_argument("--force", action="store_true", help="rebuild the index")
    p.add_argument("--raw", action="store_true", help="also write raw buffers")
    p.add_argument("--textures", action="store_true", help="also export embedded textures")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("music", help="extract the audio-config music record table")
    p.add_argument("files", nargs="*", help="specific audio archives (default: audio)")
    p.add_argument("--archive", action="append", default=[],
                   help="archive fragment (default: audio)")
    p.add_argument("--limit", type=int, default=64,
                   help="MiB of archive to carve (default 64)")
    p.add_argument("--full", action="store_true", help="carve the whole archive")
    p.add_argument("--min-ms", type=int, default=20000,
                   help="minimum duration (default 20000)")
    p.add_argument("--max-ms", type=int, default=2000000,
                   help="maximum duration (default 2000000)")
    p.add_argument("--out", help="write music.json here")
    p.add_argument("--max", type=int, default=40, help="rows to display")
    p.set_defaults(func=cmd_music)

    p = sub.add_parser("awc", help="list streams inside AWC audio containers")
    p.add_argument("files", nargs="*", help="specific .rpf files")
    p.add_argument("--archive", action="append", default=[], help="archive name fragment")
    p.add_argument("--limit", type=int, default=64, help="MiB to scan per archive")
    p.add_argument("--full", action="store_true", help="scan whole archives")
    p.add_argument("--max", type=int, default=20, help="maximum containers (default 20)")
    p.add_argument("--raw-out", help="write each stream payload to this directory")
    p.add_argument("--ogg-out", help="remux Opus streams to playable .opus files")
    p.add_argument("--music-out", help="extract one Ogg per AWC music channel")
    p.add_argument("--music-wav-out", help="decode supported music channels to separate PCM16 WAV files")
    p.add_argument("--music-skip-policy", choices=("zero", "verified-overlap"), default="zero",
                   help="music WAV block-skip policy (default zero; overlap mode requires exact packet identity)")
    p.add_argument("--ogg-policy", choices=("legacy", "declared"), default="legacy",
                   help="standalone Ogg timing policy (default: preserve legacy output)")
    p.add_argument("--ogg-pre-skip", type=int,
                   help="explicit pre-skip for --ogg-policy declared (default 312; original alignment unconfirmed)")
    p.add_argument("--wav-out", help="decode supported standalone 48 kHz Opus streams to PCM16 WAV using optional libopus")
    p.add_argument("--wav-policy", choices=("declared", "packet-sequence"), default="declared",
                   help="standalone WAV interval: declared mono duration (default) or full mono/stereo packet sequence")
    p.add_argument("--opus-library", help="path to a compatible libopus library for standalone or music WAV export")
    p.add_argument("--wav-pre-skip", type=int,
                   help="WAV pre-skip frames: default 312 for declared/music, 0 for packet-sequence; original alignment unconfirmed")
    p.set_defaults(func=cmd_awc, spread=0, quiet=False, no_padding=False,
                   no_align=False, align=0x1000)

    p = sub.add_parser("shaders", help="recover DXBC shaders from shaders.rpf")
    p.add_argument("files", nargs="*", help="specific .rpf files")
    p.add_argument("--archive", action="append", default=[], help="archive name fragment")
    p.add_argument("--limit", type=int, default=64, help="MiB to scan per archive")
    p.add_argument("--full", action="store_true", help="scan whole archives")
    p.add_argument("--out", help="write .cso files into this directory")
    p.add_argument("--metadata", action="store_true",
                   help="include bounded native DXBC stage/model and signature metadata")
    p.add_argument("--max-records", type=int, default=4096,
                   help="metadata output record limit per shader (default 4096)")
    p.add_argument("--max", type=int, default=20, help="rows to display (default 20)")
    p.set_defaults(func=cmd_shaders)

    p = sub.add_parser("structured", help="recover complete XML/PSIN resources, including supported stored PSIN tails")
    p.add_argument("files", nargs="*", help="specific .rpf files")
    p.add_argument("--archive", action="append", default=[], help="archive name fragment")
    p.add_argument("--limit", type=int, default=16, help="MiB of payload to scan")
    p.add_argument("--out", help="write .xml/.psin files into this directory")
    p.add_argument("--max", type=int, default=20, help="rows to display (default 20)")
    p.set_defaults(func=cmd_structured)

    p = sub.add_parser("textures", help="list TTPF textures and export DDS files")
    p.add_argument("files", nargs="*", help="specific .rpf archives (with --embedded)")
    p.add_argument("--pool", action="append", default=[],
                   help=".ttpf path or name fragment (repeatable)")
    p.add_argument("--embedded", action="store_true",
                   help="read embedded txd dictionaries from RPF archives")
    p.add_argument("--archive", action="append", default=[],
                   help="archive fragment for --embedded (repeatable)")
    p.add_argument("--limit", type=int, default=64,
                   help="MiB to scan per archive for --embedded (default 64)")
    p.add_argument("--full", action="store_true",
                   help="scan whole archives for --embedded")
    p.add_argument("--name", default="", help="regex on dictionary/texture names")
    p.add_argument("--names", default="names.json",
                   help="name dictionary for 64-bit hash annotation")
    p.add_argument("--out", help="export .dds files into this directory")
    p.add_argument("--via", choices=["native", "sixng"], default="native",
                   help="embedded path: native decoder (default) or SixNG backend")
    p.add_argument("--backend", default=None, help="path to the sixng executable")
    p.add_argument("--work", default=".sixng-work", help="backend work/index directory")

    p.add_argument("--max", type=int, default=100, help="maximum textures (default 100)")
    p.add_argument("--all", action="store_true", help="no limit")
    p.add_argument("--png", action="store_true",
                   help="also write PNG previews (BC1-BC7 and supported raw component formats)")
    p.add_argument("--png-mip", type=int, help="preview this mip level (default 0; requires --png and --out)")
    p.add_argument("--png-slice", type=int, help="preview this array layer or cube-face index (default 0)")
    p.add_argument("--png-z", type=int, help="preview this volume Z plane (default 0)")
    p.add_argument("--bcpack", action="store_true",
                   help="decode BC1/BC3/BC4/BC5 BCPack natively (slow, pure Python)")
    p.add_argument("--bcpack-helper", default=os.environ.get("GTA6X_BCPACK"),
                   help="optional external TTPF exporter, also used after native BCPack refusals")
    p.add_argument("--hash-prefix", default="", help="only hashes starting with this")
    p.add_argument("--min-size", type=int, default=0,
                   help="minimum width*height in pixels")
    p.set_defaults(func=cmd_textures, spread=0, quiet=False, no_padding=False,
                   full=False, limit=64, archive=None, files=[])

    p = sub.add_parser("selftest", help="run parser self-checks")
    p.set_defaults(func=cmd_selftest)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
