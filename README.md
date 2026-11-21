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
| List TTPF textures and export **DDS** files | **yes**, 301,677 of 357,115 descriptors |
| **PNG previews** for streamed/embedded textures | **yes**, BC1/2/3/4/5 + RGBA8, 277,297 of 357,115 (77.6%) |
| List and export embedded **txd** textures (DDS) | **yes**, native (mip 0) or SixNG backend (multi-mip) |
| Find and extract **Bink2** video | **yes**, exact lengths |
| Find and extract **AWC** audio; list/extract streams | **yes**, exact lengths, native payloads |
| Remux Opus streams into playable **Ogg Opus** | **yes**, lossless, no re-encode |
| Bink1 video | **experimental** |
| PSIN containers, section bodies, stream-split fragments | **yes** |
| Recover **DXBC shaders** from `shaders.rpf` | **yes**, 9,089 in the first 64 MiB |
| Recover complete **XML/PSIN** resources split across zlib pages | **yes**, 259 XML / 1,048 PSIN in 16 MiB samples |
| Carve zlib streams; catalogue; browser; reports; TUI | **yes** |
| List/extract **models** to glTF/GLB | **yes**, via optional SixNG backend |
| Decrypt the RPF9 index | **no** — the AES key is not in the package |
| Decode BCPack texture payloads | **no** — no public decoder |
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
| `textures` | TTPF pools and embedded txd dictionaries; export DDS/PNG | `--pool`, `--embedded`, `--archive`, `--via`, `--out`, `--png`, `--max`, `--all`, `--hash-prefix`, `--min-size` |
| `scan` | Find validated Bink2/Bink1/AWC carriers | `--kind`, `--limit`, `--full`, `--spread`, `--no-padding`, `--no-align`, `--max` |
| `extract` | Carve carriers; writes `extract-index.json` | `--out`, `--max-hits`, plus `scan` options |
| `awc` | Streams inside AWC containers; extract payloads or Ogg Opus | `--archive`, `--limit`, `--max`, `--raw-out`, `--ogg-out` |
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

# DDS plus PNG previews (BC1/BC2/BC3/BC4/BC5, RGBA8/BGRA8/R8)
python3 -m gta6x --root <pkg> textures --pool vehicles --out ./textures --png --all
```

Output is `<hash>.dds` plus `textures.json`, one record per candidate with a
`skipped` reason. `--png` also writes `<hash>.png` previews: a small stdlib
decoder handles BC1, BC2, BC3, BC4, BC5 and RGBA8/BGRA8/R8, which is **77.6%**
of descriptors. BC6H/BC7 (about 21.8%) stay DDS-only natively, as do cube maps
and the unmapped 1/2/4-byte layouts. Without `--out` the command only lists
descriptors.

Measured on 1.0.2.1 (see [Verified numbers](#verified-numbers)): **99.0%** of
descriptors have a supported layout and **84.5%** are fully readable.

Limits: **BCPack** is the Xbox hardware texture codec and has no public decoder,
so textures whose mips live in BCPack chunks are reported and skipped; 567
cube-map descriptors (tile modes 9–12) are listed but not exported; 2,910
descriptors use uncompressed element sizes (R8/RGBA8/R16/R32, i.e. 1/2/4-byte
elements) for which the Gfx10 bit equations are not mapped.

## Embedded textures (txd)

Not every texture lives in a TTPF pool. RAGE **texture dictionaries** inside RPF
resources hold a small system page of 0x70-byte descriptors plus one or more
compressed graphics pages. `textures --embedded` extracts them without a key.

**Native decoder (default)** — recognises a system page by its texture structs
and name pointer, appends the contiguous graphics streams (16-byte boundaries,
zero padding), deswizzles the 16x16-element tiles, and writes a DDS containing
**mip 0** (the smaller mips sit in a packed tail whose layout is not solved).

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
element sizes are reported and skipped, and only mip 0 is written.

**SixNG backend** — delegates to the same backend used for models, which exports
complete mip chains and its own metadata:

```bash
python3 -m gta6x --root <pkg> textures --embedded --via sixng --archive textures \
        --max 2 --out ./embedded-backend
```

It requires an index (`gta6x models index --archive textures`, stored in
`--work`, default `.sixng-work`). The sample dictionary produced 7 DDS files
with 3–4 mips each, three times the pixel data of the native mip-0 output.

Use native when you want a self-contained, dependency-free path; use the backend
when you need full mip chains or broader format coverage.

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
```

`--raw-out` keeps the native payloads (`<archive>_<offset>_s<index>.opus`,
`.xma`, `.pcm`, `.bin`). `--ogg-out` additionally remuxes Opus streams into
standard Ogg Opus files: the original packets wrapped in `OpusHead`/`OpusTags`
pages with correct granules and CRCs, losslessly and without re-encoding.
`ffprobe` reads the output as `opus`, 48 kHz, with the expected channel count
and duration. No PCM/WAV decoding is attempted.

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
"PSIN" u32 BE length    <- section 1: entry table + payload ("body")
"LSCH" u32 BE length
"LENM" u32 BE length
"LSNS" u32 BE length
"LGID" u32 BE length
"LRSC" u32 BE length
"CHKS" u32 BE length    <- always 20 bytes: total length, stored checksum, platform tag
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
a separate format. The `CHKS` checksum algorithm is still unknown; the stored
value is reported but not verified.

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

# index one archive (resumable; ~1 min for packs.rpf)
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
| `textures` | 357,115 descriptors in all 57 pools; 353,638 (99.0%) with a supported layout; 301,677 (84.5%) fully exportable; 277,297 (77.6%) decodable to PNG; 567 cube maps; 2,910 unmapped element sizes |
| `textures` sample | 200 vehicle descriptors → 183 DDS exported; the rest BCPack-only or unmapped |
| `awc` | 238 containers in the first 48 MiB of `audio.rpf`, zero overlaps; sampled containers end in zero padding; first 4 containers = 58 Opus 48 kHz streams; `--ogg-out` verified with `ffprobe` (Opus 48 kHz, 1.27 s first stream) |
| `psin` | 8 MiB slice of `data.rpf`: 788 containers + 10 fragments, 817 section bodies, 0–134 entries each (avg 20.0), `0x70` terminator fill on every body |
| `models` | `packs.rpf` index: 80,424 entries, 75,135 model resources, 27,288 recovered names, ~40–60 s; sample GLBs 480 / 972 / 96 triangles |
| `shaders` | 9,089 validated DXBC shaders in the first 64 MiB of `shaders.rpf`; 2,174 in the first 16 MiB |
| `structured` | `common.rpf`: 259 complete XML (79 joined); 16 MiB of `data.rpf`: 1,048 complete PSIN (28 joined) |
| `textures --embedded` | native: 1,345 txd dictionaries / 3,155 textures in `textures.rpf`; sample dictionary 7 textures; backend: 7 DDS with 3–4 mips |
| `selftest` | 42 checks, all passing (AWC, Ogg, RDS5, PSIN, XML, gfx10, DDS, PNG, shaders, txd) |

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
* **BCPack** texture payloads require the Xbox hardware codec; no public
  decoder exists, so those textures are skipped rather than approximated.
* **Texture tile coverage**: Gfx10 equations are validated for 8- and 16-byte
  elements (BC1–BC7). Uncompressed element sizes and cube-map copies are not
  exported yet.
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
  bcn.py        BC1-BC5/RGBA8 decoders for PNG previews
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

`python3 -m gta6x selftest` runs 42 synthetic checks covering the AWC header and
tag table, Opus packet records and Ogg pages, RDS5/TTPF validation, both PSIN
grammars, joined XML recovery, Gfx10/DDS round-tripping, BC1/PNG previews, the
shader wrapper/DXBC validator and embedded txd assembly — no game data required. `python3 -m compileall gta6x` is a quick
syntax check.

The parsers follow a simple rule: a field is only named when it has been
verified against the package; otherwise it keeps a measured placeholder and is
listed under [Limits and known unknowns](#limits-and-known-unknowns). Every
documented rule was checked across the archives named in the tables above.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 the gta6x
contributors.

This repository contains the analysis tool only: no game data, keys or
executables. The tool reads a package you already own and writes only to paths
you choose.

## Acknowledgements

* [SixNG](https://github.com/holdmysocks/SixNG) — optional external backend for
  model decoding and glTF export (GPL-3.0, not bundled).
* [rpf9-explorer](https://github.com/breadbbbb/rpf9-explorer) — RPF9/TTPF, AWC,
  PSIN and texture-layout research used as a cross-check.
* The RPF format references maintained by the GTA modding community.
