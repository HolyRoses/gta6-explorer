# gta6x — GTA VI (Xbox 1.0.2.1) package explorer

A read-only, dependency-free Python toolkit for inspecting and extracting from
a local `GTA6.Xbox.v1.0.2.1` package: RPF9 archives, RDS5/TTPF texture pools,
Bink2 video, AWC audio, PSIN metadata, and the zlib streams inside them.

Native code is standard library only — no install, nothing to build. Model
resources (drawables/fragments) are exported through an optional **SixNG**
backend, because decoding RAGE 9 geometry is a research project of its own.

```bash
python3 -m gta6x --root <pkg> info
```

The tool never writes to the package. Sources are opened `rb`; output goes only
to directories you name.

## What it can do

| Capability | Status |
|---|---|
| Package identity, composition, staging manifest | **yes** (`info`) |
| RPF9 header map: index size, constants, fingerprint, nesting | **yes**, 22/22 archives |
| RDS5/TTPF pool index: chunks, codecs, virtual space, ETPF descriptors | **yes**, 57/57 pools validate |
| List TTPF textures and export **DDS** files | **yes**, 305,095 of 357,115 descriptors (incl. cube maps) |
| **PNG previews** for streamed/embedded textures | **yes**, native BC1/2/3/4/5/**7** + RGBA8; backend only for BC6H and exotic formats |
| List and export embedded **txd** textures (DDS) | **yes**, native (leading mip chain) or SixNG backend |
| Find and extract **Bink2** video | **yes**, exact lengths |
| Browse movie metadata (resolution, fps, duration, bitrate) | **yes**, `movies`; 515 titles in `movies.rpf` |
| Find and extract **AWC** audio; list/extract streams and music channels | **yes**, exact lengths, native payloads |
| Remux Opus streams into playable **Ogg Opus** | **yes**, lossless, no re-encode |
| Bink1 video | **experimental** |
| PSIN containers, section bodies, stream-split fragments | **yes**, checksums verified (JOOAT) |
| Recover **DXBC shaders** from `shaders.rpf` | **yes**, 9,089 in the first 64 MiB |
| Recover complete **XML/PSIN** resources split across zlib pages | **yes**, 259 XML / 1,048 PSIN in 16 MiB samples |
| Carve zlib streams; catalogue; browser; reports; TUI | **yes** |
| List/extract **models** to glTF/GLB | **yes**, via optional SixNG backend |
| Index **animation archive** containers and clip/bone names | **yes**, `anim`; clips not decoded |
| Extract **world/map data** (placements, collision, navmesh, paths, lights, interiors, vehicles, meta/PSO) | **yes**, via optional SixNG backend |
| Build a local **joaat name dictionary** and resolve 32-bit hashes | **yes**, ~50k names from XML/text, shaders and paths |
| Decrypt the RPF9 index | **no** — the AES key is not in the package |
| Decode BCPack texture payloads | **partial** — native BC1; external helper for BC3/BC4/BC5 |
| Transcode Opus/XMA2 audio to WAV | **no** — Opus is remuxed to Ogg, not decoded |
| Native model decoding (no external tool) | **no** — use the backend |

## Requirements

* Python **3.10+** (uses `int | None` annotations and dataclasses).
* No third-party Python packages.
* Optional: Rust toolchain + [SixNG](https://github.com/holdmysocks/SixNG) for
  `models`. The backend is an external, user-supplied executable (GPL-3.0);
  nothing from it is bundled or linked.
* A local, readable copy of the package. The tools accept any path and assume
  no particular mount point.

## Quick start

```bash
# 1. what is this package?
python3 -m gta6x --root <pkg> info

# 2. archive headers + set-fingerprint check
python3 -m gta6x --root <pkg> headers

# 3. texture pool index
python3 -m gta6x --root <pkg> resources

# 4. list textures from one pool and export DDS files
python3 -m gta6x --root <pkg> textures --pool vehicles --max 20
python3 -m gta6x --root <pkg> textures --pool vehicles --out ./textures --all

# 5. plaintext media
python3 -m gta6x --root <pkg> scan --archive movies --kind bink2 --limit 64
python3 -m gta6x --root <pkg> extract --archive movies --kind bink2 \
        --limit 64 --out ./movies

# 6. audio containers and their streams
python3 -m gta6x --root <pkg> awc --archive audio --limit 64 --max 10
python3 -m gta6x --root <pkg> awc --archive audio --limit 64 --max 3 \
        --raw-out ./audio-streams

# 7. carve the resource payloads the index hides
python3 -m gta6x --root <pkg> zlib --archive levels --limit 64 --max 15

# 8. parser self-checks (no game data needed)
python3 -m gta6x selftest
```

`--root` may also be set with the `GTA6_ROOT` environment variable. Global
options (`--root`, `--json`) go before the subcommand.

## Commands

| Command | Purpose | Notable options |
|---|---|---|
| `info` | Package overview, store identity, chunk counts, composition by type | `--json` |
| `headers` | RPF9 header table: index size, constants, fingerprint, encryption test | `--json`, explicit files |
| `resources` | TTPF pool index: header fields, chunks, codecs, virtual size, ETPF, validation | `--json` |
| `textures` | TTPF pools and embedded txd dictionaries; export DDS/PNG | `--pool`, `--embedded`, `--archive`, `--via`, `--out`, `--png`, `--bcpack`, `--bcpack-helper`, `--max`, `--all`, `--hash-prefix`, `--min-size` |
| `scan` | Find validated Bink2/Bink1/AWC carriers | `--kind`, `--limit`, `--full`, `--spread`, `--no-padding`, `--no-align`, `--max` |
| `movies` | Movie metadata browser; optional extraction | `--archive`, `--limit`, `--full`, `--min/max-duration`, `--min-width/height`, `--sort`, `--out` |
| `extract` | Carve carriers; writes `extract-index.json` | `--out`, `--max-hits`, plus `scan` options |
| `awc` | Streams inside AWC containers; extract payloads, Ogg Opus, or per-channel music Ogg | `--archive`, `--limit`, `--max`, `--raw-out`, `--ogg-out`, `--music-out` |
| `models` | Index, list or export drawables/fragments (SixNG backend) | `info\|index\|list\|extract`, `--archive`, `--kind`, `--name`, `--max`, `--out`, `--backend`, `--work` |
| `zlib` | Carve non-overlapping zlib streams and classify them | `--archive`, `--limit`, `--full`, `--out`, `--max` |
| `catalog` | Carve + verify + index assets into JSON or SQLite | `--out`, `--db`, `--limit`, `--full`, `--skip-done`, `--archive` |
| `browse` | Render a searchable HTML browser from a catalogue | `--catalog`/`--db`, `--out`, `--chunk`, `--paths` |
| `get` | Re-read one catalogued asset by hash or `archive:offset` | `--catalog`/`--db`, `--out` |
| `psin` | Parse PSIN containers and stream-split fragments | `--archive`, `--limit`, `--full`, `--max` |
| `shaders` | Recover DXBC shader binaries from wrapper records | `--archive`, `--limit`, `--full`, `--out`, `--max` |
| `structured` | Recover complete XML/PSIN resources from stream-split pages | `--archive`, `--limit`, `--out`, `--max` |
| `hunt` | Score catalogued blobs for geometry-like floats | `--db` (required), `--kind`, `--archive`, `--scan`, `--window`, `--dump` |
| `report` | Markdown or HTML inventory (`.html` suffix selects HTML) | `--out`, `--hash`, `--with-media`, `--limit`, `--title` |
| `tui` | Two/three-pane terminal browser | `--db` |
| `verify` | Verify hashes against a `shasum -a 256` style manifest | — |
| `selftest` | Parser and layout self-checks | — |

## Textures (TTPF → DDS/PNG)

Every `data/ttdb/*.ttpf` pool (including the `pack/<archive>/data/ttdb` extension pools) is an `RDS5` container with an `ETPF` dictionary:
16-byte descriptors give each texture's width, height, mip count, DXGI format,
AMD Gfx10 tile mode, array size and virtual address. `textures` reassembles the
chunk table into virtual space, untiles each mip with the Gfx10 block equations,
and writes a standard DDS (DX10 header) file.

```bash
# inspect one pool
python3 -m gta6x --root <pkg> textures --pool ui --max 20

# export all readable textures from a pool
python3 -m gta6x --root <pkg> textures --pool vehicles --out ./textures --all

# one texture by hash prefix, or everything above 1 MP
python3 -m gta6x --root <pkg> textures --hash-prefix 006c --out ./one
python3 -m gta6x --root <pkg> textures --min-size 1048576 --out ./big --max 50

# DDS plus PNG previews (BC1/BC2/BC3/BC4/BC5/BC7, RGBA8/BGRA8/R8)
python3 -m gta6x --root <pkg> textures --pool vehicles --out ./textures --png --all

# native BC1 BCPack (pure Python, slow; no external tool)
python3 -m gta6x --root <pkg> textures --pool graphics --out ./textures --bcpack

# optional: BC3/BC4/BC5 via an external helper
python3 -m gta6x --root <pkg> textures --pool graphics --out ./textures \
        --bcpack-helper /path/to/Leonida/tools/ttpf_mips.py
```

Output is `<hash>.dds` plus `textures.json`, one record per candidate with a
`skipped` reason. `--png` also writes `<hash>.png` previews: a small stdlib
decoder handles BC1, BC2, BC3, BC4, BC5 and RGBA8/BGRA8/R8, which is **77.6%**
of descriptors. BC6H stays DDS-only natively, as do the
unmapped 1/2/4-byte layouts. Without `--out` the command only lists
descriptors.

For the remaining formats, `--via sixng` delegates TTPF decoding to the backend,
which handles BC6H and exports PNGs for every texture it can decode:

```bash
python3 -m gta6x --root <pkg> textures --via sixng --pool vehicles \
        --max 20 --out ./textures-backend --backend <sixng>
python3 -m gta6x --root <pkg> textures --via sixng --hash-prefix 01ccba7f \
        --out ./one --backend <sixng>
```

This path needs no archive index (the store is opened directly); `--hash-prefix`,
`--min-size`, `--max`/`--all` and `--pool` are applied before calling it. The
backend writes `<hash>_m<mip>_s<slice>.png` and reports its own metadata.

Measured on 1.0.2.1 (see [Verified numbers](#verified-numbers)): **99.0%** of
descriptors have a supported layout and **84.6%** are fully readable.

Limits: **BCPack** is the Xbox hardware texture codec. `--bcpack` decodes BC1
natively (vendored MIT/Apache `bcpack-rs` reference; slow pure Python).
`--bcpack-helper` remains for BC3/BC4/BC5 (Leonida, GPL-3.0, external).
Unsupported BCPack codecs and BC6H are reported and skipped. Cube maps
(tile modes 9–12) use the S4K cube-copy layout and export as six-face DDS:
**563 of 567** work. All 1/2/4-byte elements now have their Gfx10 ``SW_4KB_S``
and ``SW_64KB_D`` equations (R8/RGBA8/R16 families); only **8 descriptors**
remain unsupported (five unknown tile/format combinations, three cube
variants).

## Embedded textures (txd)

Not every texture lives in a TTPF pool. RAGE **texture dictionaries** inside RPF
resources hold a small system page of 0x70-byte descriptors plus one or more
compressed graphics pages. `textures --embedded` extracts them without a key.

**Native decoder (default)** — recognises a system page by its texture structs
and name pointer, appends the contiguous graphics streams (16-byte boundaries,
zero padding), deswizzles the 16x16-element tiles, and writes a DDS containing
**leading mip chain** (mip 0 through the last level whose element grid is at
least 32x32; smaller levels sit in a packed tail whose layout is not solved).
A 512x512 BC texture exports 3 mips and a 1024x1024 BC texture 4, natively.

```bash
# list embedded textures
python3 -m gta6x --root <pkg> textures --embedded --archive textures --limit 64 --max 20

# export DDS files
python3 -m gta6x --root <pkg> textures --embedded --archive textures \
        --limit 64 --out ./embedded --all
```

Measured on 1.0.2.1: `textures.rpf` yields **1,345 dictionaries / 3,155
textures** natively (a full archive scan takes ~15 s). A sample dictionary
(`non_break_glass_decals`) recovers seven textures — two BC3 and three BC7 at
512², one BC3 at 1024² — matching the backend's descriptor list. Unsupported
element sizes are reported and skipped, and the leading mip chain is written;
smaller tail mips are omitted.

**SixNG backend** — delegates to the same backend used for models, with its own
metadata output:

```bash
python3 -m gta6x --root <pkg> textures --embedded --via sixng --archive textures \
        --max 2 --out ./embedded-backend
```

It requires an index (`gta6x models index --archive textures`, stored in
`--work`, default `.sixng-work`). The sample dictionary produced 7 DDS files
with 3–4 mips each, comparable to the native leading-mip output.

Use native for the self-contained path; use the backend when you need BC6H
or its metadata. Neither path solves the small packed mip tail.

## Audio (AWC)

`scan`/`extract` locate `ADAT` containers and carve them with exact lengths
derived from the tag table. `awc` goes further and walks the tag table per
stream: 29-bit stream id, codec (`opus`, `xma2`, `pcm`), sample rate, channels,
sample count, duration and exact data range.

```bash
python3 -m gta6x --root <pkg> awc --archive audio --limit 64 --max 20
python3 -m gta6x --root <pkg> awc --archive audio --limit 64 --max 5 \
        --raw-out ./audio-streams
python3 -m gta6x --root <pkg> awc --archive audio --limit 64 \
        --ogg-out ./audio
python3 -m gta6x --root <pkg> awc --archive audio --limit 100 --max 1000 \
        --music-out ./music
```

`--raw-out` keeps the native payloads (`<archive>_<offset>_s<index>.opus`,
`.xma`, `.pcm`, `.bin`). `--ogg-out` additionally remuxes Opus streams into
standard Ogg Opus files: the original packets wrapped in `OpusHead`/`OpusTags`
pages with correct granules and CRCs, losslessly and without re-encoding.
`ffprobe` reads the output as `opus`, 48 kHz, with the expected channel count
and duration. No PCM/WAV decoding is attempted.

Music banks use a separate `0x48` descriptor: block count, chunk size, then one
16-byte record per channel. `--music-out` walks each block's 24-byte channel
table, honours the per-channel subblock counts/start and skip, and writes one
Ogg Opus file per channel. A 100 MiB `audio.rpf` sample produced **559 AWC
containers, 8,683 streams and 53 music-channel Ogg files**; `ffprobe` reports
`opus`, 48 kHz, mono, 42.03 s for the first channel.

## Video and media carriers

`movies.rpf` and `audio.rpf` store already-compressed payloads unencrypted, at
aligned offsets preceded by zero padding, each beginning with its own magic.

* **Bink2** (`KB2` + version char) — header carries width, height, frame count,
  frame rate and byte length; extraction is exact and bounded by plausibility
  checks.
* **AWC** (`ADAT`) — the u32 after the magic is a flag word: low 16 bits are the
  container version (`1`), high 16 bits are feature flags (`0xFF21`, `0xFF02`,
  `0xFF25` are feature words, not versions). Feature bits select optional
  tables; a per-stream table and 64-bit tags `{type:8, size:28, rel:28}` give
  the **exact** container length. Tag types `0x76`/`0x55`/`0x48` are
  format/data/music.
* **Bink1** (`BIK`) — experimental: fields are packed at 16-bit widths, so
  validation is looser and false positives are more likely.

Resource payloads inside the archives carry no such carrier magic; they are
handled by the zlib carving and catalogue commands instead.

## PSIN metadata

A complete PSIN resource is a seven-section container:

```
"PSIN" u32 BE length    <- section 1: instance table + payload ("body")
"LSCH" u32 BE length    <- schema: 32-byte struct headers, 16-byte fields
"LENM" u32 BE length    <- enum/name-value table (24-byte records, 0xEE fill)
"LSNS" u32 BE length    <- 128-bit names/ids (header + 16-byte records)
"LGID" u32 BE length    <- global 128-bit ids (count + 16-byte records)
"LRSC" u32 BE length    <- resource-reference/fixup table (0xBB fill)
"CHKS" u32 BE length    <- always 20 bytes: total length, checksum, platform tag
```

The section lengths tile the blob exactly and the `CHKS` total-length field
repeats `len(data)`. Section 1's body is the fill-padded entry table:

```
+0x00  "PSIN"
+0x04  u32 BE  declared size (= section length)
+0x08  u32 LE  field A
+0x0c  u32 LE  field B
+0x10  8-byte entries (u32, u32); unused slots 0xAAAAAAAA
...    0x70707070 ("pppp") fill run, then payload
```

Some PSIN resources are larger than one zlib page and are stream-split; a page
then starts with `PSIN` but declares a section longer than the page. Those are
reported as **fragments** (declared size, missing bytes, partial body), not as
a separate format.

`CHKS` is now verified: the stored checksum is RAGE **JOOAT** (signed bytes,
seed `0x3FAC7125`) over the entire container with the `CHKS` length and checksum
fields zeroed, stored big-endian. All **821/821** complete containers in an
8 MiB `data.rpf` sample verify (and the `psin` command reports 788/788 for its stream-local sample). The platform word in the sample is ASCII
`zppp`; other archives may use another tag.

## Joined XML and PSIN resources

Large resources are split into 64 KiB zlib pages. A per-stream carve leaves them
truncated; `structured` follows the continuation chain (next stream at the next
16-byte boundary, separated only by zero padding, not itself a new document),
concatenates the inflated pages, and validates the result: XML must parse with a
closed root (DTDs rejected), PSIN must be a complete seven-section container.

```bash
# list complete XML/PSIN resources
python3 -m gta6x --root <pkg> structured --archive common --limit 16 --max 20

# extract them
python3 -m gta6x --root <pkg> structured --archive common --out ./structured
python3 -m gta6x --root <pkg> structured --archive data --limit 16 --out ./structured
```

Output is `xml_<root>_at_<offset>.xml` or `metadata_PSIN_at_<offset>.psin`,
plus `structured.json` (page segments, sizes, roots). Measured on 1.0.2.1:
`common.rpf` yields 259 complete XML documents (79 joined from multiple pages)
and a 16 MiB slice of `data.rpf` yields 1,048 complete PSIN containers (28
joined). Joined files are written only after validation, so a false join cannot
produce a corrupt extract.

## Shaders (DXBC)

`shaders.rpf` stores shader binaries in wrappers::

    [u8 name_len + 1] [name] [0x00] [u8 name_len] [u32 stored]
    [magic 0x000DDCE7] [u32 stored] [u32 decoded] [raw deflate payload]

The payload is a DXBC container (magic, hash, total size, chunk table, chunks
tagged `SFI0`/`ISG1`/`OSG1`/`PSV0`/`HASH`/`DXIL`/`PRIV`). `shaders` scans the
archive, inflates every wrapper, and only reports those whose output length
matches the declared size and passes the full DXBC structure check.

```bash
# list what is there
python3 -m gta6x --root <pkg> shaders --archive shaders --limit 64 --max 20

# export .cso files plus shaders.json
python3 -m gta6x --root <pkg> shaders --archive shaders --limit 64 \
        --out ./shaders --full
```

Output is `<name>_<offset>.cso` (the inflated DXBC bytes) and a manifest. The
first 64 MiB of `shaders.rpf` yields 9,089 validated shaders; a 16 MiB scan
yields 2,174. Decompression is raw deflate, not zlib, so `zlib.decompress` is
called with `wbits=-15`; a wrong wrapper is rejected rather than written.

## Models (drawables and fragments)

RAGE 9 model resources (mesh blobs, meshlet index buffers, skeletons, materials)
are decoded by an external **SixNG** backend and exported as glTF/GLB:

```bash
# build once (Rust)
git clone https://github.com/holdmysocks/SixNG && cd SixNG
cargo build --release -p sixng-cli
export GTA6X_SIXNG=$PWD/target/release/sixng    # or pass --backend PATH

# index one archive (resumable; typically 1–3 min for packs.rpf)
python3 -m gta6x --root <pkg> models index --archive packs

# list and export
python3 -m gta6x --root <pkg> models list --archive packs --kind dr \
        --name '^ankle' --max 20
python3 -m gta6x --root <pkg> models extract --archive packs \
        --name '^ankle_gorecap_low$' --max 1 --out ./models
```

Output per model: `<out>/models/<archive>/<name>_<offset>/model.glb`, plus
`model_lod*.glb`, `buffers/`, `model.json` and a `manifest.jsonl`. Indexes live
in `--work` (default `.sixng-work`, gitignored) and are tied to the package
contents; delete them after a game update. Without a backend the command prints
the build instructions instead of guessing.

## World and map data (SixNG backend)

SixNG also decodes the world resources. `world` exposes those readers through a
single, read-only command; outputs are derived files under `--out`, never
changes to the package.

| `--kind` | Default archive | Output |
|---|---|---|
| `placements` | `levels` | per-map entity JSON + `index.jsonl`; `--batches` adds instanced batches |
| `collision` | `levels` | collision GLB + surface census |
| `navmesh` | `navmeshes` | walkable-surface GLB; `--roads-only` for road polygons |
| `paths` | `levels` | `paths/<archive>/graph.json` (nodes, lane links, speed limits) |
| `lights` | `levels` | world-space light emitters |
| `interiors` | `levels` | MLO instances and their entity lists |
| `vehicles` | `packs` | `vehicles/vehicles.json` (models, configurations, palettes) |
| `handling` | `data` | `pso/handling.json` (mass, drag, engine, suspension, …) |
| `meta` | `data` | meta schema index; `--dump` for full JSON |
| `pso` | `data` | decoded PSO resource JSON |
| `shaders` | `levels` | shader census (hash, usage, parameters, formats) |
| `surfaces` | `levels` | surface categories (needs collision/paths output) |
| `all` | — | the standard world pipeline in order |

Indexing is required once per archive:

```bash
# build the backend once (see Models above)
python3 -m gta6x --root <pkg> models index --archive levels
python3 -m gta6x --root <pkg> models index --archive navmeshes
python3 -m gta6x --root <pkg> models index --archive packs

# examples
python3 -m gta6x --root <pkg> world --kind vehicles --archive packs --out ./world
python3 -m gta6x --root <pkg> world --kind placements --limit 2000 --out ./world
python3 -m gta6x --root <pkg> world --kind collision --limit 100 \
        --bbox -1000,-1000,1000,1000 --out ./world
python3 -m gta6x --root <pkg> world --kind navmesh --roads-only --out ./world
python3 -m gta6x --root <pkg> world --kind all --out ./world-all
```

Filters: `--name`/`--exclude-name` (regex), `--min-size`, `--limit`, and
`--bbox minx,miny,maxx,maxy` for region-limited geometry and placements. Without
an index the backend reports which archive to index; without a backend the
command prints the build instructions.

## Name hashes (joaat + Murmur3)

Shaders, shader parameters, meta/PSO fields and many material names are stored
as 32-bit Jenkins one-at-a-time (`joaat`) hashes. GTA VI does not ship the
strings, but `names build` recovers them from the package itself:

- identifiers in `common.rpf` text/XML entries,
- NUL-terminated identifiers in `shaders.rpf`,
- identifiers in `recovered/paths.txt`.

```bash
python3 -m gta6x --root <pkg> names build --out names.json
python3 -m gta6x names lookup bcf03fc1 --index names.json
# standard  [common]
```

The dictionary stores the lower-case hash and, for capitalised names, the
case-sensitive hash (meta field names). It also stores 64-bit texture/archetype
keys: the **low 64 bits of MurmurHash3 x64 128** over the exact UTF-8 name
(seed 0), confirmed against the package and the latest upstream research.

```bash
# resolve a texture hash
python3 -m gta6x names lookup c875c99d196b2f1c --index names.json
# rope  [shaders]

# annotate TTPF listings/exports with resolved names
python3 -m gta6x --root <pkg> textures --pool vehicles --max 20 --names names.json
```

Measured on 1.0.2.1: **50,864 lower-case hashes**, **36,943 case-sensitive
hashes**, **87,807 64-bit hashes**, from 47,642 common identifiers, 4,512
shader identifiers and 3,212 path identifiers. Real 64-bit hits include `rope`,
`temp`, `sclera`, `mapdetail_atlas`, `veh_detail_atlas_control` and
`blank_black`.

Remaining hash gaps: 128-bit `LSNS`/`LGID` IDs look like opaque reference IDs;
29-bit audio stream ids use `joaat(normalized name) & 0x1FFFFFFF` but the names
are not recovered; 15-bit collision surface ids still have no candidate
function.

## Animation archive

`anim` indexes the animation archive's zlib streams and classifies the
containers that are measurable today. It does **not** decode clips yet.

```bash
python3 -m gta6x --root <pkg> anim --limit 64 --max 20
python3 -m gta6x --root <pkg> anim --full --out ./anim
```

Full `anim.rpf` scan (about 3.4 minutes in Python): **130,771 streams** and
**2,327 names**:

| Signature | Count | Meaning |
|---|---:|---|
| zero-prefix | 78,809 | zero-prefixed pages, often with pointers/name data |
| raw | 25,273 | unclassified payloads |
| page-directory | 22,904 | `0DRP` at +0x10 |
| clip-stream | 1,788 | `u32 2/3` + `01 01 00 00` packed clips |
| typehash | 1,379 | 16-byte type/chunk tables |
| move | 324 | `MoVE` motion containers |
| name-table | 274 | `pack:/…` path tables (`.clip`, `.anim`, `.motion`) |
| psin | 18 | PSIN metadata containers |
| skeleton-names | 1 | `SKEL_*` bone table |
| rbf0 | 1 | rig-set metadata |

`--out` writes `anim.json`, `anim-names.txt` and `anim-clips.txt` (game data
stays local); `--clips` prints the `.clip` paths directly. Upstream's full
census is 2,012 `.clip`, 274 `.anim` and 12 `.motion` paths. It also followed
`breakout_quick_front` and `idle` to page-0 clip records: duration `f32` at
record `+0x78`/`+0x68`, 0x48-byte track records with `type = 0xFFFF0001` and
two hashes, plus 63/38-entry and 12/38-entry bone masks. The page→packed-stream
join and keyframe values remain open; our browser does not guess them.

## Payload carving, catalogue and browser

The encrypted index prevents listing archive members, but resource payloads are
zlib streams. `zlib` carves and classifies them, `catalog` stores them, and
`browse`/`get`/`hunt` work from that catalogue.

```bash
# survey one archive
python3 -m gta6x --root <pkg> zlib --archive levels --limit 64 --max 15

# carve + verify + index (JSON, or SQLite at scale)
python3 -m gta6x --root <pkg> catalog --limit 64 --out gta6-catalog.json
python3 -m gta6x --root <pkg> catalog --db gta6.db --limit 512
python3 -m gta6x --root <pkg> catalog --db gta6.db --archive levels --limit 256 --skip-done

# render a browser
python3 -m gta6x --root <pkg> browse --catalog gta6-catalog.json \
        --out gta6-catalog.html --paths recovered/paths.txt
python3 -m gta6x --root <pkg> browse --db gta6.db --out ./site --chunk 5000

# retrieve one asset by identity (sha256 prefix or archive:offset)
python3 -m gta6x --root <pkg> get 15c3a3f5 --db gta6.db --out ./one

# score blobs for geometry-like float data
python3 -m gta6x --root <pkg> hunt --db gta6.db --scan 300 --window 32
```

Every catalogued asset is re-inflated with `zlib.decompress`, so `verified`
means the bytes round-trip byte-for-byte (Adler-32 checked), not "looked
plausible". `catalog --db` replaces an archive's rows on re-run rather than
duplicating them, and `--skip-done` makes sweeps resumable per archive. The
chunked browser keeps the HTML shell small regardless of asset count and loads
`assets/part-NNNN.js` files on demand.

## Verified numbers

Measured on a local `GTA6.Xbox.v1.0.2.1` package (Xbox Series) with the commands
above. These are observations, not format guarantees.

| Check | Result |
|---|---|
| `info` | 108 files, 223,880,932,870 bytes (208.51 GiB), 22 RPF9 archives, 57 RDS5 pools, identity `RockstarGamesInc.28872443D20A7` v1.0.2.1 |
| `headers` | 22/22 show magic `0x52504639`, stamp `0x047A00`, the 32-byte constant block, and an encrypted index |
| `resources` | 57/57 TTPF pools validate: header, chunk table, sentinel, embedded ETPF 634 |
| `textures` | 357,115 descriptors: 127 2D arrays, 567 cubemaps, 3 3D volumes; corrected 11-bit depth / 7-bit format / mip formula; native zlib/raw complete **305,954** + **47,695** BC1-BCPack; 3,461 partial (other BCPack); 5 unsupported DXGI formats; native PNG includes BC7; cubemaps 567/567 and arrays 127/127 validated; volumes 3/3 export |
| `textures` sample | 200 vehicle descriptors → 183 DDS exported; the rest BCPack-only or unmapped |
| `movies` | full `movies.rpf`: 515 Bink2 titles, 8.83 GB, 3.94 h total; 65 s scan |
| `awc` | 238 containers in the first 48 MiB of `audio.rpf`; a 100 MiB scan found 559 containers / 8,683 streams / 53 music-channel Ogg files; music descriptor block/channel parsing and `--music-out` verified with `ffprobe` (Opus 48 kHz mono, 42.03 s) |
| `psin` | 8 MiB `data.rpf`: 788 stream-local containers + 10 fragments, **788/788 checksums verified**; `structured` joins 821 complete; 817 bodies, 0–134 entries (avg 20.0), `0x70` fill |
| `models` | `packs.rpf` index: 80,424 entries, 75,135 model resources, 27,288 recovered names, ~40–60 s; sample GLBs 480 / 972 / 96 triangles |
| `shaders` | 9,089 validated DXBC shaders in the first 64 MiB of `shaders.rpf`; 2,174 in the first 16 MiB |
| `structured` | `common.rpf`: 259 complete XML (79 joined); 16 MiB of `data.rpf`: 1,048 complete PSIN (28 joined) |
| `textures --embedded` | native: 1,345 txd dictionaries / 3,155 textures in `textures.rpf`; native sample dictionary 7 textures, 512x512 BC3 8 mips → 3 exported mips, 1024x1024 BC3 11 mips → 4 exported mips; backend comparison optional |
| `selftest` | 57 checks, all passing (AWC, Ogg, RDS5, PSIN, XML, gfx10 1/2/4-byte/cube/array, DDS, PNG, shaders, txd, joaat/Murmur3, anim, BCPack, BC7); backend features are not self-tested |

The local SQLite catalogue used during development holds 176,971 checksum-
verified assets across 20 archives; that file is generated output, not part of
the repository.

## File formats, as verified

### RPF9 header (32 plaintext bytes)

| Offset | Field | Meaning |
|---|---|---|
| 0x00 | magic | `0x52504639`; on disk the bytes read `9FPR` |
| 0x04 | `f1` | **index size** — the payload area starts at this byte (22/22; 15 archives pad with zeroes, 7 continue with resource bytes) |
| 0x08 | `f2` | unidentified 16-byte multiple; candidate table size |
| 0x0c | `f3` | unidentified 16-byte multiple; `f3 / 16` gives plausible entry counts |
| 0x10 | `h1` | per-archive dword, likely part of an index hash |
| 0x14 | `h2` | second half of that value |
| 0x18 | stamp | `0x00047A00`, invariant |
| 0x1c | `f4` | `336`, invariant |
| 0x20..0x40 | — | per-archive structure (two u16, a counter, a dword, `0x00090F01/02`, then `16`) |
| 0x40..0x60 | — | **32 invariant bytes**, shared by every archive and nested archive |

`9FPR` headers also occur inside payload areas (e.g. `anim.rpf` at 0x5000);
those are **nested RPF9 archives**, each with its own header and the same
32-byte block.

### RDS5 / TTPF pool

```
+0x00  "RDS5"
+0x04  u32   entry count (chunks + 2 sentinels)
+0x08  u64   virtual size in bits 0..55, version byte 22 in bits 56..63
+0x10  u32   bitmap word count, ceil(count / 32)
+0x14  u32   alignment word: high nibble * 256 = source padding
+0x18  8 * (count - 1) bytes: chunk table, last entry is a sentinel
...    align 256: "ETPF" 634 texture dictionary
```

A chunk entry packs source offset/256, codec (0 stored, 8 zlib, 1/5/7 BCPack),
virtual offset/4096 and padding. The sentinel repeats the file length and the
virtual size.

### AWC

```
+0x00  "ADAT"
+0x04  u32   flag word: low 16 = version (1), high 16 = feature flags
+0x08  u32   stream count
+0x0c  u32   header size
       optional index / extra / prefix tables, per-stream u32 table
       per-stream 64-bit tags {type:8, size:28, rel:28}
```

Container length is `max(header_size, rel + size)` over all tags.

### PSIN

Seven tagged sections tile the blob; section 1 is the fill-padded entry table;
stream-split pages are fragments. See [PSIN metadata](#psin-metadata).

## Limits and known unknowns

* **No decryption.** The RPF9 index is AES ciphertext; the key is not in the
  package. `f2`, `f3`, `h1`/`h2`, `f4`, the `0x20..0x40` words and the key
  itself remain unresolved. `f1` is verified because the payload area is
  visible.
* **BCPack** texture payloads: BC1 decodes natively from the vendored MIT
  `bcpack-rs` reference; BC3/BC4/BC5 need the external helper; BC6H remains
  unsupported.
* **Texture tile coverage**: Gfx10 equations cover 1/2/4/8/16-byte elements
  (SW_4KB_S and SW_64KB_D); 8 descriptors remain unsupported. Cube maps export
  as six-face DDS (563 of 567).
* **Audio** payloads stay in their native codec; Opus/XMA2 → WAV is not
  implemented.
* **Models** depend on the external SixNG backend; no native model decoder is
  included.
* **Bink1** validation is experimental.
* **Scanning is capped** by `--limit` (defaults: 256 MiB for media, 64 MiB for
  zlib/catalog) for predictable runtime; `--full` reads whole archives. A
  209 GiB package takes roughly 80 minutes at ~43 MB/s.
* **Hashing is opt-in** (`report --hash`) because it reads whole payloads.
* The PSIN `CHKS` checksum algorithm is unknown; only the stored value is read.

## Layout

```
gta6x/
  rpf.py        RPF9 header, index size, fingerprint, encryption heuristics
  rds5.py       RDS5/TTPF index, chunk table, codecs, ETPF descriptors
  gfx10.py      AMD Gfx10 tiling: block equations, mip tails, array slices
  texture.py    TTPF texture catalog, virtual reader, DDS writer
  embedded.py   native txd (embedded texture dictionary) decoder and DDS export
  media.py      Bink1/Bink2/AWC detection, validation, carving, stream metadata
  audio.py      Opus packet extraction and lossless Ogg remux
  bcn.py        BC1-BC7/RGBA8 decoders for PNG previews
  bc7.py        native BC7 (BPTC) block decoder
  png.py        minimal PNG writer
  psin.py       PSIN containers, section bodies, stream-split fragments
  models.py     optional SixNG backend: index, list, glTF/GLB export
  shaders.py    DXBC shader wrapper scanner and validator
  structured.py joined XML/PSIN recovery across stream-split pages
  zlibcarve.py  zlib stream carving and blob classification
  catalog.py    JSON/SQLite catalogue and asset lookup
  browse.py     chunked HTML browser
  hunt.py       geometry-like float scoring and record dumps
  inventory.py  classification, hashing, manifest verification
  report.py     Markdown/HTML rendering
  tui.py        curses browsers (package and catalogue)
  cli.py        argument parsing and command implementations
```

## Generated output

These are derived and deliberately ignored by git; regenerate them from your
own package with the commands above:

* `gta6.db` (SQLite catalogue) and its `-wal`/`-shm` sidecars
* `site/` (chunked browser), `textures/`, `models/`, `shaders/`, `structured/`,
  `movies/`, `audio/`, `carved/`, `one/`
* `gta6-catalog.json`, `extract-index.json`, `manifest.sha256`,
  `report.md`, `report.html`
* `recovered/defs/`, `recovered/xml/` (bulk dumps; `recovered/paths.txt` and
  `recovered/FINDINGS.md` are kept)
* `.sixng-work/` (backend indexes) and Rust build trees

## Development

`python3 -m gta6x selftest` runs 57 synthetic checks covering the AWC header and
tag table, Opus packet records and Ogg pages, RDS5/TTPF validation, both PSIN
grammars, joined XML recovery, Gfx10 1/2/4-byte/cube/array/DDS round-tripping, BC1/PNG
previews, joaat hashes, the shader wrapper/DXBC validator and embedded txd
assembly — no game data required. `python3 -m compileall gta6x` is a quick
syntax check.

The parsers follow a simple rule: a field is only named when it has been
verified against the package; otherwise it keeps a measured placeholder and is
listed under [Limits and known unknowns](#limits-and-known-unknowns). Every
documented rule was checked across the archives named in the tables above.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 the gta6x
contributors. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the
vendored BCPack decoder and tables (MIT/Apache-2.0, Microsoft silicon-rans).

This repository contains the analysis tool only: no game data, keys or
executables. The tool reads a package you already own and writes only to paths
you choose.

## Acknowledgements

* [SixNG](https://github.com/holdmysocks/SixNG) — optional external backend for
  model decoding and glTF export (GPL-3.0, not bundled).
* [rpf9-explorer](https://github.com/breadbbbb/rpf9-explorer) — RPF9/TTPF, AWC,
  PSIN and texture-layout research used as a cross-check.
* [Leonida](https://github.com/ItsNotRexed/Leonida) — Murmur3 64-bit name
  hashes, audio-config and animation research; optional external BCPack helper
  for BC3/BC4/BC5 (GPL-3.0, not bundled).
* [bcpack-rs](https://github.com/Ahmet-Dedeler/bcpack-rs) — MIT/Apache-2.0
  clean-room BCPack entropy/BC1 decoder; vendored under `gta6x/bcpack*.py` with
  notices (see `THIRD_PARTY_NOTICES.md`).
* [bc7decomp](https://github.com/richgel999/bc7enc_rdo) — MIT/public-domain BC7
  decoder (Richard Geldreich, Jr.); ported under `gta6x/bc7*.py`.
* The RPF format references maintained by the GTA modding community.
