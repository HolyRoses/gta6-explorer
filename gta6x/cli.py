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

    if not args.archive:
        args.archive = ["anim"]
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
        return 1
    limit = None if args.full else args.limit * 1024 * 1024
    records: list[anim_mod.AnimRecord] = []
    names: set[str] = set()
    for path in targets:
        count = 0
        try:
            for record in anim_mod.scan(path, limit=limit):
                records.append(record)
                count += 1
                names.update(record.names)
                if record.name:
                    names.add(record.name)
        except OSError as exc:
            eprint(f"skip {path}: {exc}")
            continue
        eprint(f"{os.path.basename(path):24s} {count:6d} stream(s)")
    if not records:
        print("no animation streams found")
        return 0
    summary: dict[str, int] = {}
    for record in records:
        summary[record.signature] = summary.get(record.signature, 0) + 1
    clips = sorted(name for name in names if name.endswith(".clip"))
    anims = sorted(name for name in names if name.endswith(".anim"))
    motions = sorted(name for name in names if name.endswith(".motion"))
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        manifest = os.path.join(args.out, "anim.json")
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump({"summary": summary,
                       "clips": clips, "anims": anims, "motions": motions,
                       "names": sorted(names),
                       "records": [r.as_dict() for r in records]}, handle, indent=1)
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
                              "motions": len(motions)}, indent=2))
            return 0
        print(f"{len(records):,} stream(s), {len(names):,} name(s) -> {args.out}")
        print(f"manifest: {manifest}")
        print(f"names: {len(names):,}  clips: {len(clips):,}  "
              f"anim: {len(anims):,}  motion: {len(motions):,}")
        for key, value in sorted(summary.items(), key=lambda kv: -kv[1]):
            print(f"  {key:16s} {value:7,}")
        if args.clips:
            for name in clips[:args.max]:
                print(name)
        return 0
    if args.json:
        print(json.dumps({"summary": summary, "names": sorted(names),
                          "records": [r.as_dict() for r in records[:args.max]]}, indent=2))
        return 0
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
    return 0


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
    """Recover complete XML/PSIN resources from stream-split zlib pages."""
    from . import structured as structured_mod

    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
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
    print(f"\n{total:,} complete resource(s); {joined:,} joined from multiple zlib pages")
    print("pass --out DIR to write .xml/.psin files")
    return 0


def cmd_psin(args) -> int:
    """Parse PSIN containers found in an archive's zlib streams.

    Two dialects appear in the package: tagged sections (PSIN/LSCH/LENM/LSNS/
    LGID/LRSC/CHKS) and the older page + 0xAA-fill entry table.  Both are
    reported; the summary keeps them apart.
    """
    targets = _scan_targets(args)
    if not targets:
        eprint("no archive matched")
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
                         f"{len(item.entries)}", f"0x{item.payload_offset:x}",
                         f"{item.payload_size:,} B"])
    print()
    print(table(rows, ["bytes", "kind", "declared/sections", "missing/fieldA",
                       "entries", "checksum/payload@", "chks"], align="rlrrrrl"))
    return 0


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
    for path in targets:
        for hit in shaders_mod.scan(path, limit=limit):
            total += 1
            name = shaders_mod.safe_name(hit.name)
            if args.out:
                dest = os.path.join(args.out, f"{name}_{hit.offset:09x}.cso")
                with open(dest, "wb") as out:
                    out.write(hit.data)
                written += 1
                record = hit.as_dict()
                record["file"] = dest
                manifest.append(record)
            if len(rows) < args.max:
                rows.append([os.path.basename(path)[:22], hit.name[:46],
                             f"0x{hit.offset:09x}", f"{hit.stored:,}",
                             f"{hit.decoded:,}"])
        eprint(f"{os.path.basename(path):24s} shaders so far: {total:,}")
    if args.out:
        manifest_path = os.path.join(args.out, "shaders.json")
        with open(manifest_path, "w", encoding="utf-8") as out:
            json.dump(manifest, out, indent=1)
        if args.json:
            print(json.dumps({"shaders": total, "written": written,
                              "manifest": manifest_path}, indent=2))
            return 0
        print(f"recovered {total:,} shader(s); wrote {written:,} .cso files to {args.out}")
        print(f"manifest: {manifest_path}")
        return 0
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("no validated shaders found")
        return 0
    print(table(rows, ["archive", "name", "payload@", "deflate", "dxbc"],
                align="llrrr"))
    print(f"\n{total:,} shader(s); pass --out DIR to write .cso files")
    return 0


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
                if args.ogg_out:
                    from . import audio as audio_mod
                    os.makedirs(args.ogg_out, exist_ok=True)
                    stem = os.path.splitext(os.path.basename(path))[0]
                    for stream in streams:
                        if stream.get("codec_name") != "opus":
                            continue
                        name = f"{stem}_{hit.offset:09x}_s{stream['index']}.opus"
                        dest = os.path.join(args.ogg_out, name)
                        try:
                            blob = audio_mod.extract_ogg(buf, stream, title=name)
                        except ValueError:
                            continue
                        with open(dest, "wb") as out:
                            out.write(blob)
                        record.setdefault("ogg_files", []).append(dest)
                        ogg_written += 1
                records.append(record)
        if scanned >= args.max:
            break

    if args.json:
        print(json.dumps(records, indent=2))
        return 0
    if not rows:
        print("no AWC containers found")
        return 0
    print(table(rows, ["archive", "offset", "bytes", "streams", "codecs", "duration"],
                align="llrrll"))
    print(f"\n{scanned} container(s) shown; {sum(len(r['streams']) for r in records):,} stream(s)"
          + (f"; {written} raw payload(s) written to {args.raw_out}" if args.raw_out else "")
          + (f"; {ogg_written} Ogg Opus file(s) written to {args.ogg_out}" if args.ogg_out else "")
          + (f"; {music_written} music-channel Ogg file(s) written to {args.music_out}" if args.music_out else ""))
    print("raw payloads keep their native codec; --ogg-out remuxes Opus losslessly; --music-out extracts one Ogg per music channel")
    return 0


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
                        linear = embedded_mod.mip0(tex, resource.gfx)
                        blob, mip_count = embedded_mod.dds_mips(tex, resource.gfx)
                    except ValueError as exc:
                        reason = str(exc)
                        skipped[reason] = skipped.get(reason, 0) + 1
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
                        from . import png as png_mod
                        rgba = decode_rgba(tex.dxgi_format, linear, tex.width, tex.height)
                        if rgba is not None:
                            png_dest = os.path.splitext(dest)[0] + ".png"
                            png_mod.write_png(png_dest, tex.width, tex.height, rgba)
                            record["png"] = png_dest
                    records.append(record)
                else:
                    rows.append([os.path.basename(path)[:20], resource.name[:30],
                                 tex.name[:30], f"{tex.width}x{tex.height}",
                                 embedded_mod.format_name(tex.dxgi_format),
                                 str(tex.mips), "ok"])
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
            return 0
        print(f"resources {resources:,}   textures {textures:,}   exported {exported:,}"
              f" DDS files to {args.out}")
        for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1]):
            print(f"  skipped {count:>6,}  {reason}")
        print(f"manifest: {manifest}")
        return 0

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
                            png=args.png, decode_bcpack=args.bcpack)
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
            return 0
        pngs = sum(1 for record in records if record.get("png"))
        print(f"scanned {seen:,} textures; exported {exported:,} DDS files"
              + (f" and {pngs:,} PNG previews" if args.png else "")
              + f" to {args.out}")
        if args.png:
            for record in records:
                if record.get("png_skipped"):
                    key = _skip_category(record["png_skipped"])
                    skipped[key] = skipped.get(key, 0) + 1
        for reason, count in sorted(skipped.items(), key=lambda kv: -kv[1]):
            print(f"  skipped {count:>7,}  {reason}")
        print(f"manifest: {manifest}")
        return 0

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

    # PSIN dialect B: magic + dword fields + 8-byte entries padded with AA, then "pppp".
    page = (b"PSIN" + _s.pack(">I", 88) + _s.pack("<2I", 256, 16)
            + _s.pack("<2I", 0x101, 0x18) + b"\xaa" * 8
            + _s.pack("<2I", 0x60596ACC, 0x1A0) + b"\xaa" * 8
            + b"\x70" * 8 + b"\x11" * 32)
    parsed = _psin.parse_page(page)
    check("psin page parses header", parsed is not None and parsed.declared_size == 88)
    check("psin page finds entries", parsed is not None and len(parsed.entries) == 2)
    check("psin page 16-byte stride", parsed is not None and parsed.entry_stride == 16
          and parsed.record_count == 1 and parsed.has_terminator)
    check("psin page field A typed", parsed is not None and parsed.field_a_kind == "type-tag")
    check("psin page locates payload", parsed is not None and parsed.payload_offset == 0x38
          and parsed.payload_size == 32 and parsed.confident)
    check("psin rejects non-psin", _psin.parse(b"NOPE" + b"\x00" * 64) is None)

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
          _bcn.decode_rgba(32, bytes((128, 129, 0, 127)), 1, 1) == bytes((0, 0, 128, 255))
          and _bcn.decode_rgba(31, bytes((128, 129, 0, 127)), 1, 1) == bytes((0, 1, 128, 255)))

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
    _s.pack_into("<H", system, 0x40 + 0x0E, 8)
    _s.pack_into("<Q", system, 0x40 + 0x18, 0x60000000)
    _s.pack_into("<H", system, 0x40 + 0x38, 4)
    _s.pack_into("<H", system, 0x40 + 0x3A, 4)
    _s.pack_into("<H", system, 0x40 + 0x3C, 1)
    system[0x40 + 0x3F] = 71
    system[0x40 + 0x42] = 1
    _s.pack_into("<Q", system, 0x40 + 0x30, 0x50000000 | name_off)
    system[name_off + 8:name_off + 8 + 8] = b"tex_test"
    graphics = bytes(range(256)) * 8
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

    p = sub.add_parser("psin", help="parse PSIN page containers inside an archive")
    p.add_argument("files", nargs="*")
    p.add_argument("--archive", action="append")
    p.add_argument("--limit", type=int, default=48, help="MiB per archive")
    p.add_argument("--full", action="store_true")
    p.add_argument("--max", type=int, default=12)
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
    p.set_defaults(func=cmd_awc, spread=0, quiet=False, no_padding=False,
                   no_align=False, align=0x1000)

    p = sub.add_parser("shaders", help="recover DXBC shaders from shaders.rpf")
    p.add_argument("files", nargs="*", help="specific .rpf files")
    p.add_argument("--archive", action="append", default=[], help="archive name fragment")
    p.add_argument("--limit", type=int, default=64, help="MiB to scan per archive")
    p.add_argument("--full", action="store_true", help="scan whole archives")
    p.add_argument("--out", help="write .cso files into this directory")
    p.add_argument("--max", type=int, default=20, help="rows to display (default 20)")
    p.set_defaults(func=cmd_shaders)

    p = sub.add_parser("structured", help="recover complete XML/PSIN resources from split pages")
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
                   help="also write PNG previews (BC1-BC7 and 8-bit R/RG/RGBA/BGRA)")
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
