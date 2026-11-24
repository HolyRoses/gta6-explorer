"""Static HTML browser for a gta6x catalog.

Self-contained: no network assets, no build step. Renders every catalogued asset
with its verification state, and (optionally) the recovered file-path tree from
the XML mount manifests. Search and kind-filters run in the page.
"""

from __future__ import annotations

import html
import json
import os

__all__ = ["render"]

_STYLE = """
:root{--fg:#1b1b1f;--muted:#6b6b76;--line:#e4e4ec;--bg:#fbfbfd;--accent:#0b5fff}
*{box-sizing:border-box}
body{margin:0;font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:var(--fg);background:var(--bg)}
header{padding:1.4rem 1.6rem .8rem;border-bottom:1px solid var(--line);background:#fff}
h1{margin:0 0 .2rem;font-size:1.3rem}
.sub{color:var(--muted);font-size:.88rem}
.stats{display:flex;gap:1.4rem;flex-wrap:wrap;margin:.8rem 0 0}
.stat b{display:block;font-size:1.15rem}
.stat span{color:var(--muted);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em}
.controls{padding:.9rem 1.6rem;display:flex;gap:.7rem;flex-wrap:wrap;align-items:center;
  border-bottom:1px solid var(--line);background:#fff;position:sticky;top:0;z-index:2}
input[type=search],select{padding:.42rem .6rem;border:1px solid var(--line);border-radius:6px;font:inherit;background:#fff}
input[type=search]{min-width:19rem}
main{padding:1rem 1.6rem 4rem}
table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:.4rem .55rem;border-bottom:1px solid var(--line);vertical-align:top}
th{position:sticky;top:3.1rem;background:var(--bg);font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted)}
td.n{text-align:right}
code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.86em}
.ok{color:#0a7d32;font-weight:600}
.no{color:#b3261e;font-weight:600}
.pill{display:inline-block;padding:.05rem .45rem;border-radius:999px;background:#eef0f6;font-size:.76rem;color:#333}
details{margin-top:1.6rem}
summary{cursor:pointer;font-weight:600;margin-bottom:.6rem}
.tree{white-space:pre;font-family:ui-monospace,Menlo,monospace;font-size:.82rem;line-height:1.45;
  max-height:28rem;overflow:auto;background:#fff;border:1px solid var(--line);border-radius:8px;padding:.9rem}
.hidden{display:none}
"""

_SCRIPT = """
const rows=[...document.querySelectorAll('tbody tr')];
const q=document.getElementById('q'), kind=document.getElementById('kind'),
      arch=document.getElementById('arch'), only=document.getElementById('only');
function apply(){
  const t=q.value.toLowerCase(), k=kind.value, a=arch.value, v=only.checked;
  let shown=0;
  for(const r of rows){
    const hay=r.dataset.hay;
    let ok=(!t||hay.includes(t))&&(!k||r.dataset.kind===k)&&(!a||r.dataset.arch===a);
    if(v&&r.dataset.verified!=='1') ok=false;
    r.classList.toggle('hidden',!ok);
    if(ok)shown++;
  }
  document.getElementById('shown').textContent=shown;
}
[q,kind,arch,only].forEach(e=>e.addEventListener('input',apply));
apply();
"""


def _human(n: int) -> str:
    for unit, scale in (("GiB", 1024 ** 3), ("MiB", 1024 ** 2), ("KiB", 1024)):
        if abs(n) >= scale:
            return f"{n / scale:.2f} {unit}"
    return f"{n} B"


def render(catalog: dict, paths_file: str | None = None) -> str:
    esc = html.escape
    assets: list[dict] = []
    for archive, items in catalog.get("archives", {}).items():
        for a in items:
            a = dict(a)
            a["archive"] = archive
            assets.append(a)
    assets.sort(key=lambda a: (a["archive"], a["offset"]))

    kinds: dict[str, int] = {}
    archives: dict[str, int] = {}
    for a in assets:
        kinds[a["kind"]] = kinds.get(a["kind"], 0) + 1
        archives[a["archive"]] = archives.get(a["archive"], 0) + 1

    verified = sum(1 for a in assets if a.get("verified"))
    total_in = sum(a["compressed"] for a in assets)
    total_out = sum(a["size"] for a in assets)

    rows = []
    for a in assets:
        hay = " ".join([a["archive"], a["kind"], a["xml_root"], a["text_head"],
                        " ".join(a.get("paths", [])), a["sha256"]]).lower()
        rows.append(
            f'<tr data-kind="{esc(a["kind"])}" data-arch="{esc(a["archive"])}" '
            f'data-verified="{1 if a.get("verified") else 0}" data-hay="{esc(hay)}">'
            f'<td><code>{esc(a["archive"])}</code></td>'
            f'<td><code>0x{a["offset"]:09x}</code></td>'
            f'<td><span class="pill">{esc(a["kind"])}</span></td>'
            f'<td class="n">{a["compressed"]:,}</td>'
            f'<td class="n">{a["size"]:,}</td>'
            f'<td class="n">{a["size"] / max(1, a["compressed"]):.1f}×</td>'
            f'<td>{"<span class=ok>verified</span>" if a.get("verified") else "<span class=no>unverified</span>"}</td>'
            f'<td>{esc(a.get("xml_root") or "")}</td>'
            f'<td><code>{esc(a["sha256"][:16])}…</code></td></tr>')

    kind_opts = "".join(f'<option value="{esc(k)}">{esc(k)} ({v:,})</option>'
                        for k, v in sorted(kinds.items()))
    arch_opts = "".join(f'<option value="{esc(k)}">{esc(k)} ({v:,})</option>'
                        for k, v in sorted(archives.items()))

    tree_block = ""
    if paths_file and os.path.isfile(paths_file):
        with open(paths_file, "r", encoding="utf-8", errors="replace") as fh:
            paths = [line.strip() for line in fh if line.strip()]
        tree_block = (
            "<details><summary>Recovered file tree ("
            f"{len(paths):,} paths from XML mount manifests)</summary>"
            f'<div class="tree">{esc(chr(10).join(sorted(paths)))}</div></details>')

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>gta6x asset catalog</title><style>{_STYLE}</style></head>
<body>
<header>
  <h1>gta6x asset catalog</h1>
  <div class="sub">{esc(catalog.get('package', 'Rockstar Games Explorer'))} &middot;
     generated by <code>gta6x catalog</code></div>
  <div class="stats">
    <div class="stat"><b>{len(assets):,}</b><span>assets</span></div>
    <div class="stat"><b>{verified:,}</b><span>checksum-verified</span></div>
    <div class="stat"><b>{len(archives)}</b><span>archives</span></div>
    <div class="stat"><b>{_human(total_in)}</b><span>compressed</span></div>
    <div class="stat"><b>{_human(total_out)}</b><span>inflated</span></div>
    <div class="stat"><b>{total_out / max(1, total_in):.1f}×</b><span>expansion</span></div>
  </div>
</header>
<div class="controls">
  <input id="q" type="search" placeholder="search archive, kind, XML root, paths, sha256…">
  <select id="kind"><option value="">all kinds</option>{kind_opts}</select>
  <select id="arch"><option value="">all archives</option>{arch_opts}</select>
  <label><input id="only" type="checkbox"> verified only</label>
  <span class="sub"><b id="shown">0</b> shown</span>
</div>
<main>
<table>
<thead><tr><th>archive</th><th>offset</th><th>kind</th><th>packed</th><th>inflated</th>
<th>ratio</th><th>integrity</th><th>xml root</th><th>sha256</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody></table>
{tree_block}
</main>
<script>{_SCRIPT}</script>
</body></html>
"""


# --------------------------------------------------------------------------- #
# Chunked site renderer (scales: index.html + assets/part-NNNN.js)
# --------------------------------------------------------------------------- #

_SITE_JS = """
const CHUNKS=%CHUNKS%, KIND=%KINDS%, ARCH=%ARCHS%, CHUNK_SIZE=%CHUNK%;
const rows=[]; let loaded=0, page=0; const PAGE=250;
const q=document.getElementById('q'), ksel=document.getElementById('kind'),
      asel=document.getElementById('arch'), only=document.getElementById('only'),
      tbody=document.querySelector('tbody'), status=document.getElementById('status');
window.GTA6X={push:(r)=>{for(const x of r)rows.push(x);}};
function loadChunk(i){
  if(i>=CHUNKS){buildIndex();render();return;}
  const s=document.createElement('script');
  s.src='assets/part-'+String(i).padStart(4,'0')+'.js';
  s.onload=()=>{loaded++; status.textContent='loaded '+loaded+'/'+CHUNKS+' chunks, '+rows.length.toLocaleString()+' assets'; loadChunk(i+1);};
  s.onerror=()=>{status.textContent='chunk '+i+' failed';loadChunk(i+1);};
  document.head.appendChild(s);
}
function buildIndex(){
  const kinds=new Map(), archs=new Map();
  for(const r of rows){kinds.set(r[2],(kinds.get(r[2])||0)+1);archs.set(r[0],(archs.get(r[0])||0)+1);}
  for(const [v,c] of [...kinds].sort()) ksel.insertAdjacentHTML('beforeend',`<option value="${v}">${v} (${c.toLocaleString()})</option>`);
  for(const [v,c] of [...archs].sort()) asel.insertAdjacentHTML('beforeend',`<option value="${v}">${v} (${c.toLocaleString()})</option>`);
}
function filtered(){
  const t=q.value.toLowerCase(), k=ksel.value, a=asel.value, v=only.checked;
  return rows.filter(r=>{
    if(k&&r[2]!==k) return false;
    if(a&&r[0]!==a) return false;
    if(v&&r[5]!==1) return false;
    if(!t) return true;
    return (r[0]+' '+r[2]+' '+r[6]+' '+r[7]).toLowerCase().includes(t);
  });
}
function render(){
  const f=filtered(); const pages=Math.max(1,Math.ceil(f.length/PAGE));
  if(page>=pages) page=pages-1;
  const slice=f.slice(page*PAGE,(page+1)*PAGE);
  tbody.innerHTML=slice.map(r=>`<tr><td><code>${r[0]}</code></td><td><code>0x${r[1].toString(16).padStart(9,'0')}</code></td>`+
    `<td><span class="pill">${r[2]}</span></td><td class="n">${r[3].toLocaleString()}</td>`+
    `<td class="n">${r[4].toLocaleString()}</td><td class="n">${(r[4]/Math.max(1,r[3])).toFixed(1)}x</td>`+
    `<td>${r[5]?'<span class=ok>verified</span>':'<span class=no>unverified</span>'}</td>`+
    `<td>${r[6]||''}</td><td><code>${r[7].slice(0,16)}…</code></td></tr>`).join('');
  document.getElementById('meta').innerHTML=
    `<b>${f.length.toLocaleString()}</b> matching &middot; page ${page+1} / ${pages}`+
    ` <button id=prev ${page===0?'disabled':''}>&larr; prev</button>`+
    ` <button id=next ${page>=pages-1?'disabled':''}>next &rarr;</button>`;
  document.getElementById('prev').onclick=()=>{page--;render();};
  document.getElementById('next').onclick=()=>{page++;render();};
  window.scrollTo(0,0);
}
[q,ksel,asel,only].forEach(e=>e.addEventListener('input',()=>{page=0;render();}));
loadChunk(0);
"""


def render_site(store, out_dir: str, chunk_rows: int = 4000) -> dict:
    """Write index.html plus assets/part-NNNN.js chunks for a SQLite store."""
    os.makedirs(os.path.join(out_dir, "assets"), exist_ok=True)
    counts = store.counts()
    total = counts["total"]["assets"] or 0
    chunks = max(1, (total + chunk_rows - 1) // chunk_rows)

    index = 0
    written = 0
    for c in range(chunks):
        batch = store.fetch(limit=chunk_rows, offset=c * chunk_rows)
        payload = [[b["archive"], b["offset"], b["kind"], b["compressed"], b["size"],
                    b["verified"], b["xml_root"] or "", b["sha256"]] for b in batch]
        path = os.path.join(out_dir, "assets", f"part-{c:04d}.js")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("window.GTA6X.push(")
            json.dump(payload, fh, separators=(",", ":"))
            fh.write(");\n")
        written += len(payload)

    kinds = {k["kind"]: k["count"] for k in counts["by_kind"]}
    archs = {a["archive"]: a["count"] for a in counts["by_archive"]}
    script = (_SITE_JS.replace("%CHUNKS%", str(chunks))
              .replace("%KINDS%", json.dumps(kinds))
              .replace("%ARCHS%", json.dumps(archs))
              .replace("%CHUNK%", str(chunk_rows)))

    stats_rows = "".join(
        f"<tr><td><span class='pill'>{html.escape(k['kind'])}</span></td>"
        f"<td class='n'>{k['count']:,}</td><td class='n'>{_human(k['inflated'] or 0)}</td>"
        f"<td class='n'>{k['verified']:,}</td></tr>" for k in counts["by_kind"])
    arch_rows = "".join(
        f"<tr><td><code>{html.escape(a['archive'])}</code></td>"
        f"<td class='n'>{a['count']:,}</td></tr>" for a in counts["by_archive"])

    doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>gta6x asset catalog</title><style>{_STYLE}</style></head><body>
<header><h1>gta6x asset catalog</h1>
<div class="sub">Rockstar Games Explorer &middot; GTA VI &middot; chunked browser</div>
<div class="stats">
 <div class="stat"><b>{total:,}</b><span>assets</span></div>
 <div class="stat"><b>{counts['total']['verified'] or 0:,}</b><span>verified</span></div>
 <div class="stat"><b>{_human(counts['total']['compressed'] or 0)}</b><span>compressed</span></div>
 <div class="stat"><b>{_human(counts['total']['inflated'] or 0)}</b><span>inflated</span></div>
 <div class="stat"><b>{chunks}</b><span>data chunks</span></div>
</div></header>
<div class="controls">
 <input id="q" type="search" placeholder="search archive, kind, xml root, sha256…">
 <select id="kind"><option value="">all kinds</option></select>
 <select id="arch"><option value="">all archives</option></select>
 <label><input id="only" type="checkbox"> verified only</label>
 <span class="sub" id="status">loading…</span>
</div>
<main>
<div id="meta" class="sub"></div>
<table><thead><tr><th>archive</th><th>offset</th><th>kind</th><th>packed</th><th>inflated</th>
<th>ratio</th><th>integrity</th><th>xml root</th><th>sha256</th></tr></thead>
<tbody></tbody></table>
<details><summary>Per-kind totals</summary><table><tbody>{stats_rows}</tbody></table></details>
<details><summary>Per-archive totals</summary><table><tbody>{arch_rows}</tbody></table></details>
</main>
<script>{script}</script></body></html>
"""
    with open(os.path.join(out_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(doc)
    return {"assets": written, "chunks": chunks, "index": os.path.join(out_dir, "index.html")}
