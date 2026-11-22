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
| List TTPF textures and export **DDS** files | **yes**, 305,954 descriptors have complete stored/zlib coverage; native BCPack adds partial coverage |
| **PNG previews** for streamed/embedded textures | **yes**, BC1–BC7 and 8-bit R/RG/RGBA/BGRA; signed BC4/BC5 and 8-bit SINT/SNORM are converted; BC6H is tone-mapped |
| Export TTPF texture arrays, cubemaps and 3D volumes | **yes**, DDS; 127 array / 567 cube / 3 volume layouts supported; volumes require a single uncompressed mip |
| List and export embedded **txd** textures (DDS) | **yes**, native full declared BCn 2D mip chains, including packed tails; optional SixNG backend |
| Find and extract **Bink2** video | **yes**, exact lengths |
| Browse movie metadata (resolution, fps, duration, bitrate) | **yes**, `movies`; 515 titles in `movies.rpf` |
| Find and extract **AWC** audio; list/extract streams and music channels | **yes**, exact lengths, native payloads |
| Remux Opus streams into playable **Ogg Opus** | **yes**, lossless, no re-encode |
| Extract audio-config **music records** | **yes**, durations, config ids, hashes and stream ids; track names/order remain unknown |
| Bink1 video | **experimental** |
| PSIN containers, section bodies, stream-split fragments | **yes**, complete-container checksums verified (JOOAT) |
| Browse native **LSCH/LENM schemas** and export JSON | **yes**, enum records, nine inferred type meanings and optional name candidates; unknowns preserved |
| Resolve **cross-file PSIN schemas** | **partial**, private signature-aware registry; local definitions win and conflicting versions remain unresolved |
| Read native **PSIN instance blocks** | **partial**, bounded scalar/enum/embedded values, local hash32 arrays, hash/text pools and opaque/reference diagnostics with `psin --instances`; unknowns remain explicit |
| Recover **DXBC shaders** from `shaders.rpf` | **yes**, 9,089 in the first 64 MiB |
| Recover complete **XML/PSIN** resources split across zlib pages | **yes**, 259 XML / 1,048 PSIN in 16 MiB samples |
| Carve zlib streams; catalogue; browser; reports; TUI | **yes** |
| List/extract **models** to glTF/GLB | **yes**, via optional SixNG backend |
| Index **animation archive** containers and clip/bone names | **yes**, `anim`; clips not decoded |
| Extract **world/map data** (placements, collision, navmesh, paths, lights, interiors, vehicles, meta/PSO) | **yes**, via optional SixNG backend |
| Build a local **joaat name dictionary** and resolve 32-bit hashes | **yes**, ~50k names from XML/text, shaders and paths |
| Decrypt the RPF9 index | **no** — no index key is supplied or recovered |
| Decode BCPack texture payloads | **partial** — native BC1/BC3/BC4/BC5; BC3/4/5 unfitted history is refused and provisional history warns; optional external fallback |
| Transcode Opus/XMA2 audio to WAV | **no** — Opus is remuxed to Ogg, not decoded |
| Native model decoding (no external tool) | **no** — use the backend |

## Requirements

* Python **3.10+** (uses `int | None` annotations and dataclasses).
* No third-party Python packages.
* Optional: a [SixNG](https://github.com/holdmysocks/SixNG) executable for
  `models`, `world` and `textures --via sixng`. Rust is needed only when building
  that backend yourself. The executable is user-supplied (GPL-3.0); nothing
  from it is bundled or linked.
* A local, readable copy of the package. The tools accept any path and assume
  no particular mount point.

## Quick start

Run these commands from the checkout root; no package-install step is needed.

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
| `anim` | Index animation streams and recover clip/bone names | `--archive`, `--limit`, `--full`, `--clips`, `--out`, `--max` |
| `textures` | TTPF pools and embedded txd dictionaries; export DDS/PNG | `--pool`, `--embedded`, `--archive`, `--via`, `--out`, `--png`, `--bcpack`, `--bcpack-helper`, `--max`, `--all`, `--hash-prefix`, `--min-size` |
| `scan` | Find validated Bink2/Bink1/AWC carriers | `--kind`, `--limit`, `--full`, `--spread`, `--no-padding`, `--no-align`, `--max` |
| `movies` | Movie metadata browser; optional extraction | `--archive`, `--limit`, `--full`, `--min/max-duration`, `--min-width/height`, `--sort`, `--out` |
| `extract` | Carve carriers; writes `extract-index.json` | `--out`, `--max-hits`, plus `scan` options |
| `music` | Extract the audio-config music record table | `--archive`, `--limit`, `--full`, `--min-ms`, `--max-ms`, `--out`, `--max` |
| `awc` | Streams inside AWC containers; extract payloads, Ogg Opus, or per-channel music Ogg | `--archive`, `--limit`, `--max`, `--raw-out`, `--ogg-out`, `--music-out` |
| `models` | Index, list or export drawables/fragments (SixNG backend) | `info\|index\|list\|extract`, `--archive`, `--kind`, `--name`, `--max`, `--out`, `--backend`, `--work` |
| `world` | Export world/map resources through SixNG | `--kind`, `--archive`, `--out`, `--name`, `--bbox`, `--limit`, `--backend`, `--work` |
| `names` | Build or query 32-bit joaat and 64-bit Murmur3 name dictionaries | `build\|lookup`, `--out`, `--index`, `--paths`, `--no-shaders` |
| `zlib` | Carve non-overlapping zlib streams and classify them | `--archive`, `--limit`, `--full`, `--out`, `--max` |
| `catalog` | Carve + verify + index assets into JSON or SQLite | `--out`, `--db`, `--limit`, `--full`, `--skip-done`, `--archive` |
| `browse` | Render a searchable HTML browser from a catalogue | `--catalog`/`--db`, `--out`, `--chunk`, `--paths` |
| `get` | Re-read one catalogued asset by hash or `archive:offset` | `--catalog`/`--db`, `--out` |
| `psin` | Inspect PSIN containers, LSCH/LENM schemas and bounded instance blocks | `--archive`, `--limit`, `--full`, `--max`, `--schema`, `--instances`, `--max-nodes`, `--max-depth`, `--names`, `--registry`, `--registry-out`, `--out` |
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

# DDS plus supported PNG previews (see format limitations below)
python3 -m gta6x --root <pkg> textures --pool vehicles --out ./textures --png --all

# native BC1/BC3/BC4/BC5 BCPack (BC3/4/5 refuse unfitted histories)
python3 -m gta6x --root <pkg> textures --pool graphics --out ./textures --bcpack

# optional: native attempt followed by external DDS fallback
python3 -m gta6x --root <pkg> textures --pool graphics --out ./textures \
        --bcpack --bcpack-helper <external-exporter.py>
```

Output is `<hash>.dds` plus `textures.json`, one record per candidate with a
`skipped` reason. `--png` also writes `<hash>.png` previews: a stdlib decoder
handles BC1–BC7 and RGBA8/BGRA8/RG8/R8-style formats, with the preview conventions
below. BC6H previews are tone-mapped; DDS preserves the original compressed HDR
blocks. PNG export uses mip 0 and slice/face 0; DDS retains the supported mip
chain and all slices/faces. Without `--out` the command only lists descriptors.

Arrays and cubemaps export as DDS. The native 3D path exports single-mip,
uncompressed volumes using the measured Gfx10 volume layout; volume PNG
previews are unavailable. Native 2D/array/cube export is capped at a 64 MiB
tiled footprint. Common higher-precision formats such as R16 and
RGBA16_FLOAT can be exported as DDS but have no native PNG conversion.

**Preview conversion:** BC2 reads its explicit alpha before the colour block,
following the
[standard BC2 layout](https://github.com/microsoft/DirectXTex/blob/main/DirectXTex/BC.h#L146-L151).
BC4/BC5 SNORM uses signed endpoints and interpolation. Signed normalized BC4,
BC5, R8, RG8 and RGBA8 components are displayed by mapping **−1 to 0, zero to
128 and +1 to 255**. The most-negative 8-bit encoding clamps to −1, following
[Direct3D's SNORM conversion rules](https://microsoft.github.io/DirectX-Specs/d3d/archive/D3D11_3_FunctionalSpec.htm).
Interpolation remains fractional until the final byte conversion, which rounds
to nearest with halves rounded up. The implementation-dependent −127/−128 BC4
endpoint pair uses clamping before comparison, one choice permitted by the
[RGTC specification](https://registry.khronos.org/OpenGL/extensions/ARB/ARB_texture_compression_rgtc.txt).

For 8-bit SINT R/RG/RGBA, the display range is **−128…127 → 0…255**; unsigned
8-bit components retain their byte values. Typeless 8-bit formats use unsigned
interpretation. R8/A8 previews are opaque grayscale; RG8 and BC5 put the stored
channels in red/green with blue zero and opaque alpha. Signed RGBA8 applies the
same display mapping to alpha. These display conventions leave DDS format tags
and original block/component bytes unchanged.

`--bcpack-helper` accepts a user-supplied Python exporter, also configurable
through `GTA6X_BCPACK`. Its protocol is `export <pool> <texture-index>
<destination.dds> --force`; gta6x invokes it with `python -I`. With `--bcpack`,
native decoding is tried first. The helper can also be used alone for BCPack
cases. This fallback writes DDS and does not add PNG previews.

For the remaining formats, `--via sixng` delegates TTPF decoding to the backend,
which remains useful for its own metadata and model routes:

```bash
python3 -m gta6x --root <pkg> textures --via sixng --pool vehicles \
        --max 20 --out ./textures-backend --backend <sixng>
python3 -m gta6x --root <pkg> textures --via sixng --hash-prefix 01ccba7f \
        --out ./one --backend <sixng>
```

This path needs no archive index (the store is opened directly); `--hash-prefix`,
`--min-size`, `--max`/`--all` and `--pool` are applied before calling it. The
backend writes `<hash>_m<mip>_s<slice>.png` and reports its own metadata.

The current metadata census covers **357,115 descriptors** across 57 pools:
**357,110** have supported layouts and **305,954 (85.7%)** have complete
stored/zlib coverage. Another **47,695** are BC1-only BCPack candidates and
**3,461** depend on other BCPack profiles. These are layout/coverage counts,
not a claim that every candidate has been decoded and validated.

Limits: **BCPack** is the Xbox hardware texture codec. `--bcpack` decodes
BC1/BC3/BC4/BC5 natively in pure Python. BC1 retains the vendored MIT/Apache
`bcpack-rs` path; BC3/4/5 use independently fitted tables. History coverage is
partial (35/256 BC3, 55/256 BC4, 214/256 BC5 entries). Six BC3/BC5 histories
are provisional legacy-adapter observations; native use warns. BC3/4/5 unknown
references and malformed streams are skipped with a precise reason; BC1 retains
its vendored decoder behavior. BC6H/BC7 BCPack reconstruction remains unsupported.
All **567 cubemap**, **127 array** and **3 volume** layouts are supported in
the measured package, although data coverage and compression can still limit
export. Gfx10 2D addressing covers 1/2/4/8/16-byte elements. The remaining
**five unsupported layouts** use DXGI format 11.

## Embedded textures (txd)

Not every texture lives in a TTPF pool. RAGE **texture dictionaries** inside RPF
resources hold a small system page of 0x70-byte descriptors plus one or more
compressed graphics pages. `textures --embedded` extracts them without a key.

**Native decoder (default)** — recognises a system page by its texture structs
and name pointer, appends the contiguous graphics streams (16-byte boundaries,
zero padding), and validates complete graphics allocations. Supported BCn 2D
textures use Gfx10 S4K addressing and export **every declared mip**, including
the packed 4 KiB tail. Hardware mip dimensions are rounded up for addressing;
DDS payloads retain the logical dimensions. Single-level tiny textures start
at offset zero. The allocation footprint must match the descriptor exactly.

```bash
# list embedded textures
python3 -m gta6x --root <pkg> textures --embedded --archive textures --limit 64 --max 20

# export DDS files
python3 -m gta6x --root <pkg> textures --embedded --archive textures \
        --limit 64 --out ./embedded --all
```

Measured on 1.0.2.1: a full `textures.rpf` scan yields **1,347 dictionaries /
3,167 texture descriptors**, including **3,020 supported 2D descriptors**.
All **31 mipmapped 2D textures** exported complete DDS chains: **253 levels**,
including **144 tail levels**, across BC1/BC3/BC7 formats. In the sample
`non_break_glass_decals` dictionary, the 512² BC3 texture exports all eight
declared mips and the 1024² BC3 texture all eleven.

Validation combines public S4K address rules, authored address vectors, exact
allocation/DDS byte counts and real-image consistency checks. All 141 measured
adjacent-mip comparisons beat a deliberately wrong tail-origin control; this
is consistency evidence, not byte confirmation from an independent decoder.
Truncated allocations, mismatched footprints and unknown swizzle modes are
refused. Embedded depth/array layouts (147 measured descriptors) and non-BC
mip chains remain unverified and are skipped with a reason. Single-level
non-BC 2D export remains available; PNG previews use mip 0.

**SixNG backend** — delegates to the same backend used for models, with its own
metadata output:

```bash
python3 -m gta6x --root <pkg> textures --embedded --via sixng --archive textures \
        --max 2 --out ./embedded-backend
```

It requires an index (`gta6x models index --archive textures`, stored in
`--work`, default `.sixng-work`). Its texture output is separate from the native
full-chain export described above.

The native path handles supported readable textures without a backend. SixNG
remains optional for model/world decoding and alternative texture export.

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
python3 -m gta6x --root <pkg> music --archive audio --out ./music-config
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

`music` extracts the separate audio-config record table: **1,589 records**,
**1,589 distinct config ids**, **272,442.8 s** total, each with duration, hash A,
hash B and the AWC stream id (`hash B & 0x1FFFFFFF`). Records are found by the
46-byte record layout, fixed markers and duration range (20 s to 2,000 s).
It does not recover track
names or playback order.

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
"LENM" u32 BE length    <- enum table: 24-byte headers, 16-byte members, 0xEE fill
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
+0x08  repeated 16-byte entries:
         u32 LE type/hash, u32 LE block byte length, 8 bytes 0xAA
...    8 bytes 0x70 ("pppppppp") terminate the table
...    block payloads in entry order, individually padded to 16 bytes
```

The ordinary body summary retains historical `field_a`/`field_b` labels and
heuristic entry counts for compatibility. The instance reader uses the strict
block model above, including the first type/length pair.

Some PSIN resources are larger than one zlib page and are stream-split; a page
then starts with `PSIN` but declares a section longer than the page. Those are
reported as **fragments** (declared size, missing bytes, partial body), not as
a separate format.

`CHKS` is now verified: the stored checksum is RAGE **JOOAT** (signed bytes,
seed `0x3FAC7125`) over the entire container with the `CHKS` length and checksum
fields zeroed, stored big-endian. All **821/821** complete containers in an
8 MiB `data.rpf` sample verify (and the `psin` command reports 788/788 for its stream-local sample). The platform word in the sample is ASCII
`zppp`; other archives may use another tag.

**Native schema browser:** `psin --schema` reads complete checksum-verified
containers, joining recoverable split pages. It parses the contiguous LSCH
structure-header table and groups field descriptors using the stored counts.
Counts must account for the section exactly, header padding must match the
supported layout, and each field start must lie inside its structure size.

```bash
# browse structures in an archive
python3 -m gta6x --root <pkg> psin --archive data --limit 8 --schema --max 20

# export every recovered schema; optionally annotate hashes with local names
python3 -m gta6x --root <pkg> psin --archive data --limit 8 \
        --out ./schemas.json --names ./names.json

# inspect an already extracted PSIN resource
python3 -m gta6x psin ./metadata.psin --schema --out ./schema.json
```

`--out` implies schema mode. JSON contains source offsets/checksum status,
resource hashes and schemas deduplicated by the **LSCH+LENM pair**, preserving
different enum definitions even when LSCH bytes match. The report format is
`gta6x-psin-schemas-v2`; each schema also retains separate `lsch_sha256` and
`lenm_sha256` fields. Pair IDs replace the LSCH-only IDs from v1. Distinct
definitions with the same structure hash remain separate. `--max` limits the
console table only; JSON exports all records. Global `--json` prints the same
report to stdout. Raw PSIN inputs are limited to 16 MiB; archive scan limits
use the existing recovery path. Incomplete/unrecoverable archive fragments
are omitted; the ordinary `psin` view still reports stream-local fragments.

Structure sizes, field offsets, original hashes/ids, numeric type words and
unresolved attributes are preserved. Name dictionaries add candidates with
their sources, without replacing hashes or choosing among collisions. Some
descriptors use synthetic ids such as `0x100`.

LENM headers and member counts must account for every section byte, including
the supported header padding. JSON preserves all 64 value bits, a signed
interpretation, an unsigned decimal string, member hashes/name candidates and
unknown words. Aliases, duplicate names and conflicting enum definitions are
retained; no value is narrowed to 32 bits in the export.

Supported LSCH annotations are **inferred from game observations**, with
`type_info.status = "inferred"`; their storage sizes are inferred too:

| Type code | Inferred label | Required context |
|---|---|---|
| `0x01` | `bool8` | supported zero upper/auxiliary words |
| `0x21` | `float32` | supported zero upper/auxiliary words |
| `0x4a` | `hash32` | supported zero upper/auxiliary words |
| `0x05` | `embedded_structure` | one matching structure definition |
| `0x52` | `dynamic_array` | valid synthetic element-descriptor index |
| `0x71` | `map` | valid synthetic key/value-descriptor indices |
| `0x62` | `enum32` | one matching LENM definition with representable values |
| `0x65`, `0x68` | `enum_bitset32`, `enum_bitset64` | matching enum and supported bit-count/storage pattern |

Missing or ambiguous references, unsupported attributes and inferred extents
outside structure bounds leave `type_name: null` with diagnostic context.
Other codes remain unknown, including enum-associated `0x63`, whose upper bits
and width are unresolved. Original numeric words are always retained. Schema
annotations alone do not decode values; the explicit instance option below
handles a bounded subset without chasing pointers or resolving fixups.
Bad checksums, malformed LENM/LSCH records and invalid field starts produce
explicit refusal records and a nonzero exit status.

Game-data checks: the discovery sample contains **821** verified containers
and **433** distinct LSCH sections. A disjoint payload range validates
**223/223** additional containers and **34** schemas absent from that sample,
without type-rule changes. Discovery contains **11,794 enum headers / 118,111
members**; the separate range contains **1,748 / 26,632**. All 13,004 checked
enum32 payload values in that range match their LENM definitions. Boolean and
float probes also agree with the inferred labels. Map and enum_bitset64 have
discovery evidence only, with no examples in that range. These are consistency
checks, not an independent semantic decoder oracle or a fresh blind holdout;
the range was previously used for structural LSCH validation.

**Bounded instance reader:** add `--instances` to include values from supported
PSIN body blocks. This implies schema mode and works on raw PSIN files or
joined archive resources:

```bash
python3 -m gta6x psin ./metadata.psin --instances --names ./names.json \
        --out ./values.json
```

Each resource's `instances` object contains block boundaries and records, with
Boolean, finite float32, hash32, enum32 and embedded-structure values where the
schema is unambiguous (local by default, optionally using the registry below).
Field hashes and name candidates remain separate;
enum aliases are preserved. Interpretations remain **inferred**. Unknown types,
missing schemas, unsupported array/map pointers and bitsets produce explicit unresolved
fields instead of fabricated values. Nonfinite floats and invalid Boolean/enum
values keep their bits and a reason. JSON contains no NaN/Infinity numbers.
Block/record offsets refer to the decompressed PSIN container; field offsets
are relative to the owning record.

The body reader includes the first block-table entry at +8, checks AA padding,
the PP terminator, every block extent, zero alignment padding and exact EOF.
Bad bodies refuse instance output while retaining any verified schema. A
resource/block/record status of `partial` is expected when fields are unresolved;
`complete` means its listed fields were handled, not a confirmed object graph.
The enclosing resource's `status: ok` still refers to schema/checksum validation.

`--max-nodes` defaults to 100,000 across the entire report; records, fields,
blocks, enum aliases and every array/pool element consume this budget. Budget exhaustion refuses that
resource's instance output and subsequent instance work explicitly; it does not
return a silently truncated list. Increase the budget deliberately for larger
exports. `--max-depth` defaults to 16 (allowed 1..64); depth/cycle boundaries stay
unresolved. Instance refusals return a nonzero exit status, while valid partial
decodes return zero. Keep all exported game values private.

Native record checks parsed all **821 discovery containers**, all **223 comparison
containers**, and **1,012 script.rpf metadata containers**. They emitted
**732,614 / 94,289 / 230,622** supported record leaves respectively, each checked
by encoding it back to its exact source bytes. All resources remain partial.
These are byte/structure consistency results, not independent confirmation of
type semantics. The script sample is additional cross-archive evidence.

**Low-ID pools:** `--instances` also provides a `pool` view for these block IDs
when no local structure definition exists:

| Block ID | View | Interpretation |
|---|---|---|
| `0x4a` | Four-byte hash values with original bits/name candidates | Reuses inferred hash32 meaning; no new LSCH type mapping |
| `0x10` | NUL-terminated printable ASCII strings, including empty entries | Inferred storage profile; other text profiles stay unresolved |
| `0x07` | Eight-byte words with candidate block ID/offset diagnostics | Candidate references only; targets are never followed |
| `0x14`, `0x16`, `0x33` | Opaque groups of 4, 8, 16 bytes respectively | Meaning unknown; no integer signedness, hash64 or vector interpretation |

Each element retains its absolute container offset, byte length and original
bits. Opaque `view_bytes` is a grouping for inspection, not a proven scalar
width. Candidate references use a measured low-20-bit one-based block ID and
byte offset in the remaining bits; zero words, invalid IDs and out-of-bounds
offsets are explicit. These pool diagnostics alone do not resolve pointer fields,
array headers, map storage, fixups or an object graph. The limited hash32-array
profile below is handled separately. Local schema ambiguity and
stride failures never fall back to a primitive pool.

Hash/ASCII entries count toward `decoded_values` and `pool_values_decoded`.
Candidate/opaque entries remain unresolved and count separately. Every entry
consumes the shared node budget. Non-multiple lengths and unvalidated text
profiles leave the whole pool unresolved; no prefix decode, byte replacement
or silent truncation is used. The supported text profile requires a final NUL
and only bytes `0x20..0x7e` between NULs; UTF-8 and control characters are not
assumed from these observations. A complete pool means only that storage view
was decoded, not that its gameplay meaning or references are confirmed.

Game-data pool checks add **1,071 / 8,913 / 0** supported values to the
821-data-discovery / 223-data-comparison / 1,012-script samples: **9,984** total
(9,931 hashes and 53 strings). All **1,057,525** existing record leaves are
unchanged; all **1,067,509** record/pool observations re-encode exactly to source bytes.
Another **69,363** candidate/opaque entries retain raw bits without decoded
values. All resources remain partial. The reference candidate fits all
**55,884 nonzero pool words**, including their local target-stride alignment;
wrong target order and other bit partitions fail that consistency check.
ASCII has discovery evidence only; no text-pool examples occur in comparison
or script. These previously examined samples provide consistency evidence,
not a fresh blind holdout or independent semantic oracle.

**Bounded hash32 arrays:** `--instances` resolves one inferred dynamic-array
profile and attaches its hash values to the owning field's `array` object.
No extra flag is required. Resolution requires a local owning schema, a
synthetic element descriptor at offset zero with exact hash32 type/attributes,
and a bounded 16-byte header. The two stored u16 words must be equal and the
trailing u32 must be zero. Both words and all original header bits are retained;
their distinct count/capacity roles remain unknown. The common u16 value is
used as the element count for this profile only.

An empty array requires both words and the reference to be zero. A nonempty
array must reference an intrinsic `0x4a` pool using the measured one-based
low-20-bit block ID and upper byte offset. The whole target pool and offset
must align to four bytes, and the entire `count * 4` span must fit inside that
block. Local structure definitions for the target ID prevent an intrinsic
pool interpretation. Imported registry schemas cannot authorize this local-only
array profile. No references inside elements are followed.

Unequal header words, nonzero tail attributes, allocated-empty profiles,
other element types, wrong/missing targets, misalignment and overrun remain
explicitly unresolved with no prefix of values. A resolved field has
`status: complete`; its `array` keeps the profile, header bits/words, target
block/span, count and element offsets/bits/hash values/name candidates.
Interpretation remains **inferred**, with no complete object-graph claim.

`hash32_arrays_resolved` includes empty arrays;
`hash32_array_values_decoded` counts attached hash observations. CLI reports
also aggregate these as `instance_hash32_arrays_resolved` and
`instance_hash32_array_values_decoded`. Every element consumes the same shared
node budget, including repeated references to the same bytes. `decoded_values`
counts array observations alongside scalar and standalone pool observations:
the same physical hash may appear in both views, so totals are not unique
bytes or unique values. Structure arrays, maps and general pointer traversal
remain unsupported.

The source split was frozen before implementation: **821 discovery resources**,
**223 separate-range validation resources**, and **1,012 script validation
resources**. Discovery/validation have zero payload-hash overlap; the validation
groups contain 1,092 distinct payloads across 1,235 observations. All groups
were examined in earlier PSIN work; this is not a fresh blind holdout. The
private audit checks the locked split digest and exact source membership and
never promotes validation inputs automatically.

Results: **2,445 / 743 / 0** resolved arrays, including **1,926 / 367 / 0**
empty arrays, with **1,011 / 997 / 0** attached hash observations. All
**1,067,509** prior record/pool observations are unchanged; all **1,069,517**
current observations round-trip to source bytes. Reversing element order fails
on all 470 spans with discriminating content. Other array profiles remain
unresolved and all 2,056 tested resources remain partial. These checks establish
bounded byte/shape consistency, not independently confirmed header semantics.

Schema JSON also exposes lossless `base_type_code` and `type_subcode` bytes
alongside the original 16-bit `type_code` and complete `type_word`. Structure
flags, layout-signature and alignment candidates retain their original unknown
words; they are not silently promoted to confirmed meanings.

**Cross-file schema registry:** collect definitions from your own verified PSIN
inputs, then load the registry when inspecting other resources:

```bash
mkdir -p work
python3 -m gta6x --root <pkg> psin --archive data --limit 8 \
        --registry-out work/psin-registry.json
python3 -m gta6x psin ./metadata.psin --registry work/psin-registry.json \
        --instances --out work/values.json

# extend into a new file; keep the original provider set for comparisons
python3 -m gta6x psin ./more.psin --registry work/psin-registry.json \
        --registry-out work/psin-registry-expanded.json
```

Both registry options imply schema mode. `--registry-out` alone builds the
registry and prints counts/refusals; add `--schema`, `--instances` or `--out`
to inspect the inputs using the completed registry. Builds use the same raw
file/joined archive recovery, checksum gate and scan limits as schema export.
Bad inputs are recorded as refusals with a nonzero exit status; accepted inputs
can still form a registry. Outputs cannot overwrite inputs or each other.

Definitions retain the name hash, raw signature candidate and full content
identity, including unknown words and all members. Identical definitions at
different section offsets deduplicate. Local definitions take precedence;
local ambiguity never falls back to a global guess. Automatic references carry
only a name hash, so differing signatures or conflicting content stay
unresolved. Matching sizes, frequency and source order never choose a version;
signatures do not alias different names. The raw header `+4` word is used as a
signature candidate, not promoted to a confirmed format meaning.

IDs below `0x10000` are conservatively restricted to local lookup, including
synthetic descriptor IDs. Dependencies inside an imported structure use global
lookup: they cannot borrow unrelated local definitions from the receiving file
or an arbitrarily chosen donor. Resolution metadata lists scope, status and
candidate fingerprints/signatures (at most eight candidates, with a full count).
Ambiguous, reserved and missing definitions stay explicit; all instance bounds,
depth/node limits and inferred-meaning caveats still apply.

Registry format `gta6x-psin-registry-v1` contains **game-derived LSCH/LENM section
bytes** and source hashes/offsets. Keep it private under ignored `work/`; it is
not a redistributable schema database. Registry files are written atomically
with owner-only permissions. Reload validates sections and identities but
cannot reverify original full-container checksums; the summary states that
limitation. Stored sections are capped at 64 MiB total, JSON files at 160 MiB,
with explicit schema/source count limits. No registry is bundled or loaded by
default; schema lookup remains local-only unless explicitly enabled.

Registry-only checks before the pool extension used **697 schema pairs from 1,976 provider
resources**, excluding the 223-container comparison range and script archive.
The registry preserves **38 structure-name / 12 enum-name conflicts**. It
enables **2,461 / 1 / 0** previously missing embedded-field annotations in the
821-provider-subset / 223-comparison / 1,012-script samples respectively
(repeated declarations counted). It adds **no decoded leaf values** in those
samples: unsupported pointers and file-local block IDs still limit instance
coverage. All **1,057,525** existing values are unchanged and round-trip to
source bytes. Comparison inputs have zero content-hash overlap with providers,
but were examined in earlier research; these are consistency checks, not blind
holdout accuracy or independent semantic confirmation.

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
joined). Joined files are written only after XML/PSIN structure validation.

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
# point to your backend executable (or pass --backend PATH)
export GTA6X_SIXNG=/path/to/sixng

# index one archive (resumable; typically 1–3 min for packs.rpf)
python3 -m gta6x --root <pkg> models index --archive packs

# list and export
python3 -m gta6x --root <pkg> models list --archive packs --kind dr \
        --name '^ankle' --max 20
python3 -m gta6x --root <pkg> models extract --archive packs \
        --name '^ankle_gorecap_low$' --max 1 --out ./models
```

Build the backend using its upstream instructions if a binary is unavailable.
Keep the working directory at the gta6x checkout when running the Python commands.

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

# also needed by data-based steps such as handling/meta/PSO
python3 -m gta6x --root <pkg> models index --archive data

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
as 32-bit Jenkins one-at-a-time (`joaat`) hashes. `names build` assembles
candidate strings from other plaintext parts of the package:

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
(seed 0), checked against known names in the package.

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

Measured on a local `GTA6.Xbox.v1.0.2.1` package (Xbox Series). Texture layout
and stored/compressed coverage counts were rechecked against all 57 pool
indexes. Other sample/export results below are recorded observations from
earlier checks. Metadata eligibility does not establish a successful full-corpus
decode, and external-adapter agreement does not establish confirmed ground truth.

| Check | Result |
|---|---|
| `info` | 108 files, 223,880,932,870 bytes (208.51 GiB), 22 RPF9 archives, 57 RDS5 pools, identity `RockstarGamesInc.28872443D20A7` v1.0.2.1 |
| `headers` | 22/22 show magic `0x52504639`, stamp `0x047A00`, the 32-byte constant block, and an encrypted index |
| `resources` | 57/57 TTPF pools validate: header, chunk table, sentinel, embedded ETPF 634 |
| `music` | audio-config table: 1,589 records / 272,442.8 s / 1,589 distinct ids, 20 s–2,000 s filter |
| `textures` metadata | **357,115** descriptors; **357,110** supported layouts; **305,954** with complete stored/zlib coverage; **47,695** BC1-only BCPack candidates; **3,461** other BCPack candidates; **5** unsupported descriptors, all DXGI format 11 |
| Texture shapes | Supported layouts for **567/567** cubemaps, **127/127** arrays and **3/3** single-mip volumes; complete stored/zlib coverage for 567 cubemaps, 120 arrays and 3 volumes |
| Native BCPack checks | BC3/BC4/BC5 DDS/PNG samples export; 16 retained BC3/BC5 chunks agree with the legacy provisional adapter; 75 BC4 UI chunks still refuse; six BC3/BC5 histories remain provisional |
| `textures` sample | 200 vehicle descriptors → 183 DDS exported; the rest BCPack-only or unmapped |
| `movies` | full `movies.rpf`: 515 Bink2 titles, 8.83 GB, 3.94 h total; 65 s scan |
| `awc` | 238 containers in the first 48 MiB of `audio.rpf`; a 100 MiB scan found 559 containers / 8,683 streams / 53 music-channel Ogg files; music descriptor block/channel parsing and `--music-out` verified with `ffprobe` (Opus 48 kHz mono, 42.03 s) |
| `psin` | 8 MiB `data.rpf`: 788 stream-local containers + 10 fragments, **788/788 checksums verified**; `structured` joins 821 complete; 817 bodies, 0–134 entries (avg 20.0), `0x70` fill |
| `models` | `packs.rpf` index: 80,424 entries, 75,135 model resources, 27,288 recovered names, ~40–60 s; sample GLBs 480 / 972 / 96 triangles |
| `shaders` | 9,089 validated DXBC shaders in the first 64 MiB of `shaders.rpf`; 2,174 in the first 16 MiB |
| `structured` | `common.rpf`: 259 complete XML (79 joined); 16 MiB of `data.rpf`: 1,048 complete PSIN (28 joined) |
| `textures --embedded` | native: 1,347 txd dictionaries / 3,167 descriptors in `textures.rpf`; 3,020 supported 2D descriptors; all 31 mipmapped 2D textures export 253 declared mips, including 144 tail levels; 147 depth/array descriptors refused |
| Native LSCH/LENM schemas | 821 discovery containers / 433 schema pairs; separate-range validation 223/223 containers, 34 additional pairs; 11,794/1,748 enum headers and 118,111/26,632 members respectively; inferred types and JSON v2 export |
| Native PSIN instances | 821 / 223 data containers and 1,012 script metadata containers; 734,696 / 104,199 / 230,622 scalar/pool/array observations round-trip exactly; all resources explicitly partial |
| Low-ID PSIN pools | 9,984 added hash/ASCII values; 55,898 candidate reference words and 13,465 opaque groups retain bits with unknown meanings; no pointer following |
| Bounded PSIN hash32 arrays | 3,188 resolved fields, including 2,293 empty arrays; 2,008 hash observations attached to owning fields, often also visible in pools; frozen source split, unsupported profiles remain explicit |
| Cross-file PSIN registry | 697 provider schema pairs; 2,462 missing embedded-field annotations resolved across the data samples; conflicts retained, no additional instance values in these samples |
| `selftest` | 95 checks, all passing (AWC, Ogg, RDS5, PSIN/LSCH/LENM/instances/registry/pools/hash32 arrays, XML, Gfx10, DDS, PNG, shaders, txd full mip chains/tail addresses/bounds, name hashes, animation, music, BCPack, BC2 layout, signed BC4/BC5/8-bit previews and BC6H/BC7); backend features are not self-tested |

The local SQLite catalogue used during development holds 176,971 checksum-
verified assets across 20 archives; that file is generated output, not part of
the repository.

## File formats, as verified

### RPF9 header and following index prefix

The plaintext base header occupies the first 32 bytes. The table also includes
observations from the following prefix, including the invariant block at 0x40.

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
+0x10  u32   bitmap word count, ceil(count / 32), +1 word also accepted
+0x14  u32   alignment word: high nibble * 256 = source padding
+0x18  8 * (count - 1) bytes: chunk table, last entry is a sentinel
...    align 256: "ETPF" 634 texture dictionary
```

A chunk entry packs source offset/256, codec, virtual offset/4096 and padding.
Codec 0 is stored and 8 is zlib. Observed BCPack profiles are 1/3/4/5/6/7;
native reconstruction supports 1/3/4/5 within the limits above. The sentinel
repeats the file length and virtual size.

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

* **No decryption.** The RPF9 index remains encrypted; this tool supplies or
  recovers no index key. `f2`, `f3`, `h1`/`h2`, `f4` and the `0x20..0x40`
  words remain unresolved. `f1` is verified because the payload boundary is visible.
* **BCPack** texture payloads: BC1 decodes natively from the vendored MIT
  `bcpack-rs` reference; BC3/BC4/BC5 decode natively within the independently
  fitted history coverage, with explicit refusal outside it; BC6H/BC7 BCPack
  reconstruction remains unsupported.
* **Texture tile coverage**: Gfx10 equations cover 1/2/4/8/16-byte elements
  (SW_4KB_S and SW_64KB_D); five descriptors using DXGI format 11 remain unsupported.
  All 567 measured cubemap layouts are supported. 3D volumes require one
  uncompressed mip and export as DDS only.
* **PNG previews**: signed 8-bit/SNORM values use the documented display mapping;
  BC6H uses tone mapping. Many higher-precision DDS formats have no PNG conversion.
  Previews use mip 0, slice/face 0; 3D volume previews remain unavailable.
* **Embedded textures**: full BCn 2D mip chains require validated S4K allocations.
  Depth/array resources, other swizzles and non-BC mip chains are refused;
  single-level non-BC 2D textures retain their existing export path.
* **Audio** payloads stay in their native codec; Opus/XMA2 → WAV is not
  implemented.
* **Models** depend on the external SixNG backend; no native model decoder is
  included.
* **Bink1** validation is experimental.
* **Scanning is capped** by `--limit` (defaults: 256 MiB for media, 64 MiB for
  zlib/catalog) for predictable runtime; `--full` reads whole archives. A
  209 GiB package takes roughly 80 minutes at ~43 MB/s.
* **Hashing is opt-in** (`report --hash`) because it reads whole payloads.
* **PSIN checksums**: complete supported containers are verified with JOOAT;
  incomplete stream-split fragments require reassembly before verification.
* **PSIN schemas**: native LSCH/LENM browsing preserves unknowns and marks
  supported type meanings as inferred. An optional private cross-file registry
  resolves unambiguous missing definitions; conflicting versions remain unknown.
  Instance reading covers scalars/enums/embedded structures and one bounded
  local hash32-array profile. Other pointers, fixups, bitsets and remaining types
  are unresolved. Low-ID hash/ASCII pool views add
  values; reference/opaque views preserve bits with explicit unknowns and no
  target following. Unrecoverable fragments are excluded.

## Layout

```
gta6x/
  rpf.py        RPF9 header, index size, fingerprint, encryption heuristics
  rds5.py       RDS5/TTPF index, chunk table, codecs, ETPF descriptors
  gfx10.py      AMD Gfx10 tiling: block equations, mip tails, array slices
  texture.py    TTPF texture catalog, virtual reader, DDS writer
  volume.py     single-mip uncompressed Gfx10 3D volumes
  embedded.py   native txd (embedded texture dictionary) decoder and DDS export
  media.py      Bink1/Bink2/AWC detection, validation, carving, stream metadata
  audio.py      Opus packet extraction and lossless Ogg remux
  music.py      audio-config music record metadata
  bc/           BC1-BC7 previews, BCPack reconstruction and runtime tables
  png.py        minimal PNG writer
  psin.py       PSIN containers, section bodies, stream-split fragments
  psin_schema.py native LSCH/LENM browser, inferred types and JSON records
  psin_instances.py bounded instance blocks and inferred member values
  psin_pools.py  low-ID hash/text pools, reference candidates and opaque views
  psin_arrays.py bounded local hash32-array spans; other profiles stay unknown
  psin_registry.py signature-aware private cross-file definitions/conflicts
  models.py     optional SixNG backend: index, list, glTF/GLB export
  world.py      optional SixNG world/map resource commands
  anim.py       animation stream classification and name recovery
  names.py      joaat/Murmur3 name dictionaries and lookup
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

Local `docs/`, `tests/`, `tools/` and `work/` directories are also ignored.
Required decoder constants under `gta6x/bc/` remain part of the runtime package.

## Development

`python3 -m gta6x selftest` runs 95 synthetic checks covering the AWC header and
tag table, Opus packet records and Ogg pages, RDS5/TTPF validation, PSIN
containers/fragments, LSCH/LENM schemas, bounded instance values and cross-file
registry resolution/conflicts, low-ID pools, bounded hash32 arrays and explicit
reference/opaque unknowns,
joined XML recovery,
Gfx10 2D/cube/array/volume layouts, DDS,
BC1/BC2/BC4/BC5/BC6H/BC7 decoder vectors, signed component conversion, PNG writing,
joaat/Murmur3 hashes, music records, the shader
wrapper/DXBC validator and embedded txd assembly — no game data required.
`python3 -m compileall gta6x` is a quick syntax check. These checks do not cover
every format variant or external backend behavior.

The parsers follow a simple rule: a field is only named when it has been
verified against the package; otherwise it keeps a measured placeholder and is
listed under [Limits and known unknowns](#limits-and-known-unknowns). The
verification table distinguishes metadata censuses from selected decode/export
checks.

## Block compression

All runtime block-compression code and tables live in `gta6x/bc/`:

```text
bc/
  __init__.py       decode_rgba and decode_bcpack entry points
  bcn.py            BC1-BC5/RGBA8 previews and BC6H/BC7 dispatch
  bc6h.py           BC6H HDR blocks and tone-mapped previews
  bc7.py            BC7 BPTC blocks and previews
  tables/           BC6H/BC7 mode, partition and interpolation constants
  bcpack/
    decoder.py      shared entropy layer and BC1 reconstruction
    blocks.py       BC3/BC4/BC5 block reconstruction
    spec.py         codec ids, lane widths and request validation
    tables.py       public rANS model constants
    data/           required runtime history and index-codebook JSON tables
```

Python callers can use `from gta6x.bc import decode_bcpack, decode_rgba`.
`decode_bcpack(chunk, codec, out_size)` handles codecs 1/3/4/5 and returns BCn
blocks in stored Gfx10 tile order. `decode_rgba(dxgi_format, data, width, height)`
expects ordinary row-major BCn blocks and returns RGBA8 preview pixels.
The texture exporter handles detiling between these steps. BC6H previews are
tone-mapped; DDS preserves the original HDR blocks. Existing imports such as
`gta6x.bcpack` and `gta6x.bcn` remain compatibility aliases to the same modules.

BCPack BC3/BC4/BC5 reconstruction uses independently fitted tables. Coverage
is 35/256 BC3, 55/256 BC4 and 214/256 BC5 entries. BC3 histories 29/37/71/166
and BC5 histories 16/112 remain provisional; native use emits a warning.
Unknown entries fail explicitly. Runtime tables retain fitting provenance and
source-evidence limits; the legacy oracle establishes consistency only, not
confirmed ground truth. All 75 recorded BC4 UI cases still refuse because of
missing histories. Native BC6H/BC7 BCPack reconstruction remains unsupported.

BC1 retains its vendored 254/256-entry preset window and zero-predictor fallback
for unfitted presets. The strict unknown-history refusal described above applies
to BC3/BC4/BC5.

Runtime code and constants are self-contained. Local research tools, reports,
observations and test fixtures stay in ignored directories. No GPL decoder or
tables were read or copied, and no game payloads are bundled. License attribution
is retained in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

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
  clean-room BCPack entropy/BC1 decoder; vendored in `gta6x/bc/bcpack/decoder.py` and
  `gta6x/bc/bcpack/tables.py` with
  notices (see `THIRD_PARTY_NOTICES.md`).
* [bc7decomp](https://github.com/richgel999/bc7enc_rdo) — MIT/public-domain BC7
  decoder (Richard Geldreich, Jr.); ported under `gta6x/bc/bc7.py` and `gta6x/bc/tables/bc7.py`.
* [bcdec](https://github.com/iOrange/bcdec) — MIT/public-domain BC6H decoder
  (Sergii "iOrange" Kudlai); ported under `gta6x/bc/bc6h.py` and `gta6x/bc/tables/bc6h.py`.
* The RPF format references maintained by the GTA modding community.
