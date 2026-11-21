"""Markdown / HTML report generation from collected inventory and scan data."""

from __future__ import annotations

import datetime as _dt
import html
import os

from . import inventory, media, rpf

__all__ = ["build", "to_markdown", "to_html"]


def _human(n: int) -> str:
    for unit, scale in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if abs(n) >= scale:
            return f"{n / scale:.2f} {unit}"
    return f"{n} B"


def build(root: str, rows: list[dict], hits: list[media.Hit], title: str) -> dict:
    archives = [p for p in rows if p["path"].lower().endswith(".rpf")]
    headers = []
    for row in archives:
        path = os.path.join(root, row["path"])
        try:
            headers.append(rpf.describe(path))
        except (OSError, ValueError):
            continue
    by_kind: dict[str, int] = {}
    for hit in hits:
        by_kind[hit.kind] = by_kind.get(hit.kind, 0) + 1
    return {
        "title": title,
        "root": os.path.abspath(root),
        "generated": _dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z"),
        "rows": rows,
        "totals": inventory.totals(rows),
        "headers": headers,
        "hits": hits,
        "hits_by_kind": by_kind,
    }


def to_markdown(doc: dict) -> str:
    t = doc["totals"]
    lines = [
        f"# {doc['title']} — inventory report",
        "",
        f"- Root: `{doc['root']}`",
        f"- Generated: {doc['generated']}",
        f"- Files: **{t['files']:,}**",
        f"- Size: **{t['bytes']:,} bytes** ({_human(t['bytes'])})",
        "",
        "## Composition",
        "",
        "| Type | Files | Size | Share |",
        "|---|---:|---:|---:|",
    ]
    for name, slot in t["by_type"].items():
        share = 100 * slot["bytes"] / max(1, t["bytes"])
        lines.append(f"| {name} | {slot['files']:,} | {_human(slot['bytes'])} | {share:.1f}% |")

    if doc["headers"]:
        lines += ["", "## RPF9 headers", "",
                  "| Archive | f1 | f2 | f3 | Stamp | Const 0x40 | Encrypted TOC |",
                  "|---|---:|---:|---:|---|---|---|"]
        for d in doc["headers"]:
            lines.append(
                f"| `{d['name']}` | {d['f1']:,} | {d['f2']:,} | {d['f3']:,} | "
                f"`0x{d['stamp']:06X}` | {'yes' if d['constant_toc_block'] else 'no'} | "
                f"{'yes' if d['likely_encrypted_toc'] else 'no'} |")

    if doc["hits"]:
        lines += ["", "## Plaintext media carriers", ""]
        lines.append("| Kind | Count |")
        lines.append("|---|---:|")
        for kind, count in sorted(doc["hits_by_kind"].items()):
            lines.append(f"| {kind} | {count:,} |")
        lines += ["", "| Archive | Kind | Offset | Bytes | Detail |", "|---|---|---|---:|---|"]
        for hit in doc["hits"][:200]:
            meta = hit.meta
            detail = (f"{meta.get('width')}x{meta.get('height')} @{meta.get('fps')}fps"
                      if hit.kind.startswith("bink") else f"{meta.get('streams')} streams")
            lines.append(f"| `{hit.archive}` | {hit.kind} | `0x{hit.offset:x}` | "
                         f"{hit.size or '-'} | {detail} |")
        if len(doc["hits"]) > 200:
            lines.append(f"\n_({len(doc['hits']) - 200:,} further carriers omitted)_")

    lines += ["", "## Files", "", "| Path | Type | Size | Hash |", "|---|---|---:|---|"]
    for row in doc["rows"]:
        digest = f"`{row['hash'][:16]}…` ({row['hash_method']})" if row.get("hash") else "—"
        lines.append(f"| `{row['path']}` | {row['type']} | {row['size']:,} | {digest} |")
    return "\n".join(lines) + "\n"


def to_html(doc: dict) -> str:
    esc = html.escape
    t = doc["totals"]
    parts = [
        "<!doctype html><meta charset='utf-8'>",
        f"<title>{esc(doc['title'])}</title>",
        "<style>",
        "body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;margin:2rem;color:#1b1b1f;background:#fbfbfd}",
        "h1{font-size:1.5rem;margin:0 0 .2rem}h2{font-size:1.05rem;margin:2rem 0 .5rem}",
        "code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.9em}",
        "table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem}",
        "th,td{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #e6e6ec;vertical-align:top}",
        "th{font-weight:600;background:#f2f2f7}td.n{text-align:right;font-variant-numeric:tabular-nums}",
        ".meta{color:#666;font-size:.9rem}",
        "</style>",
        f"<h1>{esc(doc['title'])}</h1>",
        f"<p class='meta'>{esc(doc['root'])} &middot; generated {esc(doc['generated'])}</p>",
        f"<p><strong>{t['files']:,}</strong> files &middot; <strong>{_human(t['bytes'])}</strong></p>",
        "<h2>Composition</h2><table><tr><th>Type</th><th>Files</th><th>Size</th><th>Share</th></tr>",
    ]
    for name, slot in t["by_type"].items():
        share = 100 * slot["bytes"] / max(1, t["bytes"])
        parts.append(f"<tr><td>{esc(name)}</td><td class='n'>{slot['files']:,}</td>"
                     f"<td class='n'>{_human(slot['bytes'])}</td><td class='n'>{share:.1f}%</td></tr>")
    parts.append("</table>")

    if doc["headers"]:
        parts.append("<h2>RPF9 headers</h2><table><tr><th>Archive</th><th>f1</th><th>f2</th>"
                     "<th>f3</th><th>Stamp</th><th>Const 0x40</th><th>Encrypted TOC</th></tr>")
        for d in doc["headers"]:
            parts.append(
                f"<tr><td><code>{esc(d['name'])}</code></td>"
                f"<td class='n'>{d['f1']:,}</td><td class='n'>{d['f2']:,}</td>"
                f"<td class='n'>{d['f3']:,}</td><td><code>0x{d['stamp']:06X}</code></td>"
                f"<td>{'yes' if d['constant_toc_block'] else 'no'}</td>"
                f"<td>{'yes' if d['likely_encrypted_toc'] else 'no'}</td></tr>")
        parts.append("</table>")

    if doc["hits"]:
        parts.append("<h2>Plaintext media carriers</h2><table><tr><th>Archive</th><th>Kind</th>"
                     "<th>Offset</th><th>Bytes</th><th>Detail</th></tr>")
        for hit in doc["hits"][:500]:
            meta = hit.meta
            detail = (f"{meta.get('width')}x{meta.get('height')} @{meta.get('fps')}fps"
                      if hit.kind.startswith("bink") else f"{meta.get('streams')} streams")
            parts.append(f"<tr><td><code>{esc(hit.archive)}</code></td><td>{hit.kind}</td>"
                         f"<td><code>0x{hit.offset:x}</code></td>"
                         f"<td class='n'>{hit.size or '-'}</td><td>{esc(detail)}</td></tr>")
        parts.append("</table>")

    parts.append("<h2>Files</h2><table><tr><th>Path</th><th>Type</th><th>Size</th>"
                 "<th>Hash</th></tr>")
    for row in doc["rows"]:
        parts.append(f"<tr><td><code>{esc(row['path'])}</code></td><td>{esc(row['type'])}</td>"
                     f"<td class='n'>{row['size']:,}</td>"
                     f"<td><code>{row['hash'][:20]}…</code> {row['hash_method']}</td></tr>"
                     if row.get("hash") else
                     f"<tr><td><code>{esc(row['path'])}</code></td><td>{esc(row['type'])}</td>"
                     f"<td class='n'>{row['size']:,}</td><td>—</td></tr>")
    parts.append("</table>")
    return "\n".join(parts) + "\n"
