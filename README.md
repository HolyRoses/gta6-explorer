# gta6x — GTA VI (Xbox 1.0.2.1) package explorer

A read-only Python toolkit for inspecting and extracting from
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
| List TTPF textures and export **DDS** files | **yes**, 305,959 descriptors have complete stored/zlib coverage; native BCPack adds partial coverage |
| **PNG previews** for streamed/embedded textures | **yes**, BC1–BC7, byte components and selected 16/32-bit/packed formats; explicit mip/slice/Z selection; raw floats are clipped numerically, BC6H is tone-mapped |
| Export TTPF texture arrays, cubemaps and 3D volumes | **yes**, DDS; 127 array / 567 cube / 3 volume layouts supported; volumes require a single uncompressed mip |
| List and export embedded **txd** textures (DDS) | **yes**, native BCn 2D/array mip chains and single-mip uncompressed 3D volumes; optional SixNG backend |
| Find and extract **Bink2** video | **yes**, exact lengths |
| Browse movie metadata (resolution, fps, duration, bitrate) | **yes**, `movies`; 515 titles in `movies.rpf` |
| Find and extract **AWC** audio; list/extract streams and music channels | **yes**, exact lengths, native payloads |
| Remux Opus streams into playable **Ogg Opus** | **yes**, lossless, no re-encode |
| Extract audio-config **music records** | **yes**, durations, config ids, hashes and stream ids; optional supplied credit candidates; native station membership/order unresolved |
| Browse indexed **audio config** | **partial**, bounded records, checked name tables and wave-slot references; unknown families/tails explicit |
| Bink1 video | **experimental** |
| PSIN containers, section bodies, stream-split fragments | **yes**, complete-container checksums verified (JOOAT) |
| Browse native **LSCH/LENM schemas** and export JSON | **yes**, enum records, nine inferred type meanings and optional name candidates; unknowns preserved |
| Resolve **cross-file PSIN schemas** | **partial**, private signature-aware registry; local definitions win and conflicting versions remain unresolved |
| Read native **PSIN instance blocks** | **partial**, scalar/enum/embedded values, bounded local enum bitsets, local hash32 arrays, local reference-field, structure/reference-array, map-entry and ASCII-pool entry links, hash/text pools and opaque/reference diagnostics with `psin --instances`; optional checked-link record graphs; unknowns remain explicit |
| Recover **DXBC shaders** from `shaders.rpf` | **yes**, 9,089 in the first 64 MiB; optional native stage/model and signature metadata |
| Browse native **MoVE motion metadata** | **partial**, bounded version-19 envelopes, reference/descriptor prefixes and optional kind-3/kind-12/kind-11/kind-28 tail storage; motion bodies remain opaque |
| Browse native **RBF0 metadata** | **partial**, bounded token trees and searchable literal rig-set/entry inventories; raw Priority bits, no script or runtime rig semantics |
| Recover complete **XML/PSIN** resources split across zlib pages | **yes**, 259 XML / 1,048 PSIN in 16 MiB samples |
| Carve zlib streams; catalogue; browser; reports; TUI | **yes** |
| List/extract **models** to glTF/GLB | **yes**, via optional SixNG backend |
| Browse **animation resources**, names and clip-record links | **yes**, `anim --resources` exports bounded `0DRP` metadata; `--clip-records` binds names/record prefixes; `--clip-components` follows animation/buffer links; `--packed-layout` inspects bounded headers/raw channel rows; `--channel-layout` adds slot directories; `--storage-layout` adds opaque fixed-stride rows; `--payload-layout` adds a narrow raw-word inventory; `--bit-layout` checks width tables/raw rows; `--lookup-candidates` inspects bounded indexed-payload candidates; `--prefix-layout` inventories mixed raw prefix storage; curves remain unknown |
| Extract **world/map data** (placements, collision, navmesh, paths, lights, interiors, vehicles, meta/PSO) | **yes**, via optional SixNG backend |
| Build a local **joaat name dictionary** and resolve 32-bit hashes | **yes**, ~50k names from XML/text, shaders and paths |
| Decrypt the RPF9 index | **no** — no index key is supplied or recovered |
| Decode BCPack texture payloads | **partial** — native BC1/BC3/BC4/BC5; BC3/4/5 unfitted history is refused and provisional history warns; optional external fallback |
| Decode supported AWC Opus to **WAV** | **partial**, mono declared-duration or opt-in mono/stereo packet-sequence export at 48 kHz, plus supported music channels using optional libopus; original timing and unverified skip profiles remain unresolved; XMA2 unsupported |
| Native model decoding (no external tool) | **no** — use the backend |

## Requirements

* Python **3.10+** (uses `int | None` annotations and dataclasses).
* No third-party Python packages.
* Optional system libopus for PCM WAV export; raw/Ogg export remains self-contained.
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
| `anim` | Index streams/names, browse resource metadata and named record links | `--archive`, `--start`, `--limit`, `--full`, `--clips`, `--resources`, `--clip-records`, `--clip-components`, `--packed-layout`, `--channel-layout`, `--storage-layout`, `--payload-layout`, `--bit-layout`, `--lookup-candidates`, `--prefix-layout`, `--max-nodes`, `--out`, `--max` |
| `textures` | TTPF pools and embedded txd dictionaries; export DDS/PNG | `--pool`, `--embedded`, `--archive`, `--via`, `--out`, `--png`, `--png-mip`, `--png-slice`, `--png-z`, `--bcpack`, `--bcpack-helper`, `--max`, `--all`, `--hash-prefix`, `--min-size` |
| `scan` | Find validated Bink2/Bink1/AWC carriers | `--kind`, `--limit`, `--full`, `--spread`, `--no-padding`, `--no-align`, `--max` |
| `movies` | Movie metadata browser; optional extraction | `--archive`, `--limit`, `--full`, `--min/max-duration`, `--min-width/height`, `--sort`, `--out` |
| `extract` | Carve carriers; writes `extract-index.json` | `--out`, `--max-hits`, plus `scan` options |
| `music` | Extract music records, annotate supplied credit candidates or browse indexed audio config | `--archive`, `--limit`, `--full`, `--min-ms`, `--max-ms`, `--out`, `--max`, `--catalog`, `--trackids`, `--config`, `--index-sections`, `--start`, `--name`, `--max-nodes` |
| `awc` | AWC streams, radio markers/chapters and native/Ogg/WAV export | `--archive`, `--limit`, `--full`, `--offset`, `--max`, `--max-containers`, `--radio`, `--radio-max-records`, `--chapters-out`, `--music-names`, `--raw-out`, `--ogg-out`, `--ogg-policy`, `--ogg-pre-skip`, `--music-out`, `--wav-out`, `--wav-policy`, `--music-wav-out`, `--music-skip-policy`, `--opus-library`, `--wav-pre-skip` |
| `models` | Index, list or export drawables/fragments (SixNG backend) | `info\|index\|list\|extract`, `--archive`, `--kind`, `--name`, `--max`, `--out`, `--backend`, `--work` |
| `world` | Export world/map resources through SixNG | `--kind`, `--archive`, `--out`, `--name`, `--bbox`, `--limit`, `--backend`, `--work` |
| `names` | Build or query 32-bit joaat and 64-bit Murmur3 name dictionaries | `build\|lookup`, `--out`, `--index`, `--paths`, `--no-shaders` |
| `zlib` | Carve non-overlapping zlib streams and classify them | `--archive`, `--limit`, `--full`, `--out`, `--max` |
| `catalog` | Carve + verify + index assets into JSON or SQLite | `--out`, `--db`, `--limit`, `--full`, `--skip-done`, `--archive` |
| `browse` | Render a searchable HTML browser from a catalogue | `--catalog`/`--db`, `--out`, `--chunk`, `--paths` |
| `get` | Re-read one catalogued asset by hash or `archive:offset` | `--catalog`/`--db`, `--out` |
| `move` | Browse MoVE envelopes and supported payload storage | `--objects`, `--children`, `--tail-forms`, `--raw`, `--archive`, `--start`, `--limit`, `--full`, `--max-nodes`, `--out` |
| `rbf` | Browse RBF0 trees and literal rig-set/entry inventories | `--rig-sets`, `--name`, `--rig`, `--raw`, `--archive`, `--start`, `--limit`, `--full`, `--max-nodes`, `--max-depth`, `--max-string-bytes`, `--out` |
| `psin` | Inspect PSIN containers, LSCH/LENM schemas and bounded instance blocks | `--archive`, `--limit`, `--full`, `--max`, `--schema`, `--instances`, `--resource-header`, `--record-graph`, `--bucket-maps`, `--max-nodes`, `--max-depth`, `--names`, `--registry`, `--registry-out`, `--out` |
| `shaders` | Recover DXBC binaries and inspect bounded program/signature metadata | `--archive`, `--limit`, `--full`, `--out`, `--metadata`, `--max-records`, `--max` |
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
handles BC1–BC7, RGBA8/BGRA8/RG8/R8-style formats and the precision formats
below. BC6H previews are tone-mapped; DDS preserves the original compressed HDR
blocks. PNG defaults to mip 0 and slice/face/Z 0. DDS retains the supported
mip chain and every slice/face/plane. Without `--out` the command lists descriptors.

Arrays and cubemaps export as DDS. The native 3D path exports single-mip,
uncompressed volumes using the measured Gfx10 volume layout, with selectable
PNG depth planes. Native streamed export is capped at a 64 MiB
tiled footprint. DDS retains original precision independently of PNG conversion.

**Select a PNG subresource:** `--png-mip N` chooses a mip level,
`--png-slice N` chooses an array layer or stored cube-face index, and
`--png-z N` chooses a volume depth plane. Selectors require `--png --out`
and the native path; slice and Z selectors are mutually exclusive. Supported
volumes have only mip 0. Cube indices do not establish original face orientation.

```bash
python3 -m gta6x --root <pkg> textures --pool graphics --out ./textures \
        --png --png-mip 2 --png-slice 1
python3 -m gta6x --root <pkg> textures --embedded --archive textures \
        --out ./embedded --png --png-z 1
```

Nondefault PNG names end in `_mN_sN_zN.png`, preserving the default preview.
Manifests record selected indices and `png_width`/`png_height`. Invalid explicit
selections return nonzero with a preview reason while retaining any valid DDS;
they never substitute another mip or plane. A full DDS layout refusal occurs
before either file is written. The complete source allocation is required even
when selecting a small subresource.

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

Additional PNG formats are **RGBA16_FLOAT (10), RGBA16_UNORM (11),
R10G10B10A2_UNORM (24), RG16_FLOAT (34), R16_FLOAT (54), R16_UNORM (56),
RGBA32_FLOAT (2), R11G11B10_FLOAT (26) and R32_FLOAT (41)**.
UNORM channels scale to RGBA8 with nearest/half-up rounding. Raw float channels
use a clipped numeric preview: values below zero become zero, above one become
255, NaN/negative infinity become zero and positive infinity becomes 255. No
exposure or gamma is inferred. Single-channel formats use opaque grayscale;
RG uses red/green, blue zero and opaque alpha. `png_conversion` records the
policy in streamed and embedded manifests. DDS preserves every source bit.

The signed raw-format IDs follow the public DXGI enumeration: SNORM is
31/51/63 and SINT is 32/52/64 for RGBA/RG/R respectively. Earlier releases had
those labels and preview paths reversed. BGRX 88/93 now forces opaque alpha;
BGRA retains stored alpha and refuses truncated input. These fixes intentionally
correct affected PNG output while leaving DDS payloads and format IDs unchanged.

All five real format-11 textures now export DDS and PNG. Frozen public-rule
checks preserve 72 earlier DDS and 65 earlier PNG sample hashes; 12 new previews
match 3,953 reference pixels. Natural selected examples cover 10/11/24/54;
34/56 and the corrected signed/BGRX cases have exact authored vectors. These
are public-format and reused-source consistency checks, not game-shader parity.

The three newer float formats (2/26/41) have authored public-standard tests,
including exhaustive packed-component encodings and float32 boundary cases.
None occurs in the 357,115 streamed or 3,167 embedded descriptor censuses;
no natural new-format accuracy is claimed. All 73 selected existing PNG
regression hashes remain identical.

**DDS serialization:** arrays and cube faces contain a complete mip chain per
element, and DX10 cube `arraySize` counts cubes, following
[Microsoft's DDS layout](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dx-graphics-dds-pguide)
and [DX10 header specification](https://learn.microsoft.com/en-us/windows/win32/direct3ddds/dds-header-dxt10).
BC linear size now describes the complete first mip, and mipmapped textures
set the complex-surface flag. These correct older header/order output; earlier
DDS hash-parity milestones below describe their original implementation stage.
Unsupported logical BC mip grids are refused rather than padded or guessed.

Frozen source checks verify 16 selected subresources, with all 16 deliberately
wrong selections producing different bytes. All 48 invalid-index and 16
truncated-allocation controls refuse. Eleven prior streamed PNG files/manifests
and three embedded default views remain exact; header/order repairs intentionally
change the affected DDS files. The full metadata census finds no incomplete
logical grids in the measured package; the authored NPOT counterexample remains
refused. Native commands also verify a nonzero cube mip/face and volume plane 31.

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
**all 357,115** have supported layouts and **305,959 (85.7%)** have complete
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
export. Gfx10 2D addressing covers 1/2/4/8/16-byte elements; adding public
DXGI format 11 closed the five remaining layout gaps.

## Embedded textures (txd)

Not every texture lives in a TTPF pool. RAGE **texture dictionaries** inside RPF
resources hold a small system page of 0x70-byte descriptors plus one or more
compressed graphics pages. `textures --embedded` extracts them without a key.

**Native decoder (default)** — recognises a system page by its texture structs
and name pointer, appends the contiguous graphics streams (16-byte boundaries,
zero padding), and validates complete graphics allocations. Supported BCn 2D
textures and explicitly tagged 2D arrays use Gfx10 S4K addressing and export **every declared mip**, including
the packed 4 KiB tail. Hardware mip dimensions are rounded up for addressing;
DDS payloads retain the logical dimensions. Single-level tiny textures start
at offset zero. Each array layer stores a complete hardware mip chain; DDS
exports retain every layer in layer-major order. A depth of six alone does
not identify a cubemap. The allocation footprint must match the descriptor exactly.

```bash
# list embedded textures
python3 -m gta6x --root <pkg> textures --embedded --archive textures --limit 64 --max 20

# export DDS files
python3 -m gta6x --root <pkg> textures --embedded --archive textures \
        --limit 64 --out ./embedded --all
```

Measured on 1.0.2.1: a full `textures.rpf` scan yields **1,347 dictionaries /
3,167 texture descriptors**, including **3,020 supported 2D descriptors and 34 BCn arrays** (155 layers /
169 layer-mip subresources), plus **113 single-mip volumes** (1,966 depth planes).
All **3,167 observed descriptors** now export through the native path.
All **31 mipmapped 2D textures** exported complete DDS chains: **253 levels**,
including **144 tail levels**, across BC1/BC3/BC7 formats. In the sample
`non_break_glass_decals` dictionary, the 512² BC3 texture exports all eight
declared mips and the 1024² BC3 texture all eleven.

Validation combines public S4K address rules, authored address vectors, exact
allocation/DDS byte counts and real-image consistency checks. All 141 measured
adjacent-mip comparisons beat a deliberately wrong tail-origin control; this
is consistency evidence, not byte confirmation from an independent decoder.
Truncated allocations, mismatched footprints and unknown swizzle modes are
refused. The array resource split was frozen before payload research: five
resources contain 33 single-mip BC3 arrays for discovery; one untouched resource
contains a two-layer, eight-mip BC7 array for validation. Of its 14 adjacent-mip
comparisons, ten beat a deliberately wrong level-major order and four tied;
none were worse. Discovery spatial checks beat wrong-linear block order in
148/153 layers, with five worse results. These image checks support consistency,
not independent byte accuracy. All 3,020 previous 2D DDS hashes are unchanged.

Explicit shape-tag-3, single-mip uncompressed volumes now use the existing
public Gfx10 3D S4K equations. DDS retains every Z plane, with a true 3D header
and array size one. The volume footprint must match exactly, and the complete
allocation, including unused padding, must be present even for a preview.
All 113 measured volumes export: 110 RGBA16F 17³, two R10G10B10A2 32³ and one
RGBA8 32³. All 3,054 earlier 2D/array DDS hashes remain unchanged; all 339
truncation/allocation-size controls refuse. All 113 neighbor-continuity checks
beat deliberately wrong linear storage. Both source resources were already
in discovery, so there is **no independent volume holdout or byte oracle**.
The public algorithm and authored vectors were frozen before pixel evaluation.

Cubemaps, unknown shape tags, BC/multi-mip volumes, non-BC arrays/chains and
other swizzles remain explicit refusals. Single-level non-BC 2D export remains
available. PNG previews use mip 0, array layer 0 (`png_slice_index`) or volume
Z plane 0 (`png_z_index`) by default where the format has native conversion.
The same PNG selectors choose other supported subresources; metadata includes
the selected dimensions. A preview refusal records `png_skip_reason` and
preserves the complete valid DDS. Explicit selection failures exit nonzero.

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
# inspect one container and export TRACKID chapter metadata
python3 -m gta6x --root <pkg> --json awc --archive audio \
        --offset 0x264d72000 --radio --chapters-out ./chapters
python3 -m gta6x --root <pkg> music --archive audio --out ./music-config
```

`awc --max` limits displayed table rows only. JSON and exports process every
container within the selected scan range; `--max-containers N` is the explicit
processing cap. `--limit` still bounds scanning, and `--full` scans the entire
archive. Repeatable `--offset DEC|HEX` inspects exact container addresses without
scanning. Music banks extend well beyond the archive head.

**Radio markers and chapters:** `--radio` exposes bounded `0xBD` records with
raw tag/value bits, known tag names, frame positions and TRACKID intervals.
Unknown values stay explicit. `--chapters-out DIR` also writes exact-frame JSON
and `h:mm:ss<TAB>0xb2<TAB>id` text, a tool export convention. Repeated ids are
retained; intervals remain unclassified and can contain imaging or repeated
material. This does not identify every song, split audio or recover station
membership. `0xA3` tables require one ascending u32 per music block; their units
remain unknown and are never used as file offsets. `--radio-max-records` bounds
a shared table/marker/chapter budget. Refused tables retain reasons and emit no
partial records. Radio-only inspection reads metadata without decoding audio.

The frozen first implementation reproduces **41 intervals / 40 distinct ids**
in the supplied Worldwide example and **25 / 23** in the Vault example. A
supplied-location audit validates **3,008 containers / 3,116 music records**,
**13,035 raw seek entries** and **1,042 TRACKID intervals**. Of 905 banks with
one interval, only 828 ids are distinct. Locations came from an external list;
these are native-byte consistency checks, not an exhaustive independent archive
census or native song/station mapping. The stricter export regression preserves
the original frozen reports and source roles. Complete Worldwide/Vault stereo
Ogg remuxes also pass source framing and output-granule checks; their full PCM
was not decoded.

**TRACKID/title candidates:** `music --trackids FILE` consumes the JSON array
from `awc --radio` and joins whole-channel marker observations to music-record
candidates. A source needs a unique exact local marker/channel id, one TRACKID
at frame zero, and an integral 48 kHz frame count; record candidates also need
low29-id equality and duration agreement within one millisecond, compared
without display rounding. Premixed intervals remain queries; they are never
paired to records by ordinal or approximate chapter length.

```bash
# Native marker metadata for one known container; add more --offset values
# to include whole-channel reference banks and premixed queries together.
python3 -m gta6x --root <pkg> --json awc --archive audio \
        --offset 0x113d76000 --radio > awc-radio.json
python3 -m gta6x --root <pkg> music --trackids awc-radio.json \
        --catalog ./supplied-credits.json --out ./radio-links
```

The optional catalog adds external title/credited-station contexts by complete
32-bit hash B equality. Without it, the report contains numeric record candidates
only. `radio-trackids.json` preserves all candidate records, conflicts, source
addresses, marker intervals, exclusions and input hashes. `--max-nodes` bounds
work/output and `--max` caps human display only for this mode. Supplied metadata
is checked again, but the report does not authenticate its original game bytes.
No catalog, native mapping table or game data is bundled.

Reused native-data checks find **865 TRACKIDs / 1,042 intervals**, with record
candidates for **823 IDs**, including **12 conflicting IDs**. **667 IDs** have
external credit candidates (663 without a conflicting record hash). Worldwide
has candidates for 32/41 intervals and external titles for 24/41; Vault remains
0/25. Some IDs refer to many different hashes, and four hashes associate with
multiple IDs. Equal numeric IDs therefore remain a candidate cross-bank join,
not a globally unique song identifier. Native station membership and exact
recording identity remain unresolved; credited stations are external context.
Only premixed banks in an input report cannot supply their own whole-song
references. Existing frozen splits remain intact; these reused checks are not
independent semantic ground truth.

Native membership research has now located proposed station hashes in
schema-defined PSIN hash fields: five discovery observations and one reserved
validation observation share the same structure/field. Their owner/field meaning
and song references remain unknown, so they do not establish a playlist. A
fixed exact-packet reuse test of Vault's 25 midpoint windows against 2,519
non-reserved stereo banks finds no matches. This does not exclude re-encoded
versions; Vault remains unresolved. Existing candidate conflicts and frozen
splits are unchanged, and no speculative decoder or native station map is added.

**Optional music names:** `--music-names FILE` accepts supplied labels keyed by
archive basename, container offset, stream index and channel index. A unique
context produces `<Station> - <Title> [<archive>_<offset>_sN_cN].opus` or `.wav`.
Multiple contexts remain explicit in JSON and use the offset-based fallback.
Names are sanitized, bounded to 255 UTF-8 bytes and checked for collisions.
The map source/hash and external-evidence label accompany the output; no mapping
is bundled and native membership remains unresolved. Example input:

```json
{"format":"gta6x-awc-names-v1","source":"user-supplied labels","entries":[
  {"archive":"authored.rpf","awc_offset":4096,"stream_index":0,
   "channel_index":0,"station":"Example FM","title":"Example Song"}
]}
```

`--raw-out` keeps the native payloads (`<archive>_<offset>_s<index>.opus`,
`.xma`, `.pcm`, `.bin`). `--ogg-out` additionally remuxes Opus streams into
standard Ogg Opus files with the original packets, without re-encoding.
The default `--ogg-policy legacy` retains the existing pre-skip/final-granule
policy for compatibility. Its decoded duration differs from declared-length
PCM in all 16 audit samples. The explicit declared policy below corrects
container timing for a selected interval; original alignment stays unconfirmed.

**Declared-duration Ogg:** `--ogg-policy declared` uses cumulative packet
sample counts, monotonic granules and final EOS trimming. It retains unchanged
packet bytes through the first packet covering pre-skip plus declared mono
frames, then omits unused whole tail packets. All source packet framing is
checked, including omitted tails. This remux is pure Python and does not load
libopus; compressed codec frame bits are not decoded or semantically validated.

```bash
python3 -m gta6x --root <pkg> awc --archive audio --limit 48 --max 5 \
        --ogg-out ./declared-audio --ogg-policy declared
```

`--ogg-pre-skip N` explicitly overrides the inherited 312-frame assumption for
this policy; it requires declared mode. JSON `ogg_metadata` records retained
and dropped packet counts, frame counts, pre-skip and final granule. Unsupported
profiles retain `ogg_skipped` reasons. A malformed supported stream exits
nonzero without partial output; legacy behavior and bytes remain unchanged.

All **3,349 discovery / 1,310 validation** supported mono streams pass unchanged
after freezing this policy. Retained source prefixes match byte-for-byte;
**7,570** unused whole packets are omitted. All **308,537** page CRC checks and
**9,318** malformed-input controls pass. The 16 selected outputs decode to exact
requested lengths; FFmpeg using the same libopus backend agrees with direct
WAV within one PCM16 unit. This checks wrapper interoperability, not independent
codec accuracy or original in-game alignment.

Music banks use a separate `0x48` descriptor: block count, chunk size, then one
16-byte record per channel. `--music-out` walks each block's 24-byte channel
table, uses the per-channel subblock counts/start, and writes one
Ogg Opus file per descriptor record (which can itself be stereo). Raw sample
counts are interleaved; duration divides by channels-per-record. Unsupported
counts have no guessed duration. The stereo Ogg path validates complete block
allocations, counters, packet extents/framing and zero padding, then emits
monotonic granules with explicit final trimming. It refuses nonzero stereo
block skips. Long remuxes use encoded-data/frame/output bounds independently
of WAV PCM limits. Mono Ogg retains its previous bytes/timing policy.
A 100 MiB `audio.rpf` sample produced **559 AWC
containers, 8,683 streams and 53 music-channel Ogg files**; `ffprobe` reports
`opus`, 48 kHz, mono, 42.03 s for the first channel.

**PCM WAV export:** `--wav-out DIR` decodes supported standalone mono 48 kHz
Opus streams through an optional system **libopus** library. No decoder binary
is bundled; normal scanning and raw/Ogg export do not need it. The publisher
provides libopus under a [BSD license](https://opus-codec.org/license/).

```bash
python3 -m gta6x --root <pkg> awc --archive audio --limit 48 --max 5 \
        --wav-out ./wav
# select a compatible installed library explicitly when needed
python3 -m gta6x --root <pkg> awc --archive audio --max 5 \
        --wav-out ./wav --opus-library /path/to/libopus
```

WAV is PCM16 at 48 kHz. Complete 2 KiB blocks, packet extents and zero padding
are checked strictly. Every packet is decoded, including discarded tails;
malformed packets and insufficient samples fail without concealment, padding
or partial WAV output. Input is capped at 64 MiB and decoded processing/output
at 128 MiB per stream. This standalone path excludes music; use
`--music-wav-out` for its validated subset. Stereo requires the explicit
packet-sequence policy below. Other codecs/rates and unsupported profiles
retain a clear `wav_skipped` reason. Decoder/decode failures exit
nonzero; raw/Ogg exports requested alongside WAV continue independently.

The default trim skips **an assumed 312 frames**, inherited from the old Ogg
policy, and retains the declared mono sample count. It is not a recovered
encoder-delay field or confirmed original alignment. `--wav-pre-skip N` selects
an explicit value. JSON `wav_files`/`wav_metadata` records output/decoded frame
counts, pre-skip, discarded tail, library version and the timing limitation.

A content-hash-grouped 171/67-container split was frozen before packet research.
All 3,349/1,310 supported mono streams pass strict framing; nine validation
stereo streams remain refused under the default declared policy. Sixteen selected real decodes produce the
requested 1,561,860 frames in total. FFmpeg using the **same libopus backend**
agrees within one PCM16 unit, with three byte-identical outputs; this validates
wrapper/trimming interoperability, not an independent codec. FFmpeg's separate
native Opus decoder differs substantially on these samples, and original
in-game sample alignment remains unconfirmed. Earlier archive exposure and
all comparison limitations are recorded in local provenance.

**Complete packet-sequence WAV:** `--wav-policy packet-sequence` exports every
decoded frame from a supported standalone mono/stereo 48 kHz stream, with zero
pre-skip by default. `--wav-pre-skip N` selects a different leading trim; there
is no trailing trim based on the AWC sample-count word. This makes the decoded
sequence available without claiming the game's original playback interval.
The stream's declared channel count selects the fixed libopus output layout;
legal mono/stereo packet switching is supported. PCM remains interleaved PCM16.

```bash
python3 -m gta6x --root <pkg> awc --archive audio --limit 48 --max 5 \
        --wav-out ./packet-wav --wav-policy packet-sequence
```

The unchanged split supplies eight discovery and 17 validation sequence checks,
including nine stereo streams from **one previously exposed validation bank**.
Those stereo checks establish consistency, not independent held-out accuracy
or recovered timing. All 16 earlier selected default WAV hashes and full
metadata remain identical. Authored native-libopus tests exercise channel
switching and distinct stereo output. A native command check exports all 13
streams in the selected bank, including all nine stereo streams. Music export
retains its existing default 312-frame pre-skip independently of this policy.

**Music-channel WAV:** `--music-wav-out DIR` validates complete channel/block
allocations, channel descriptors, packet records, seek-counter relations and
zero header/tail padding before decoding eligible channels to separate files:

```bash
python3 -m gta6x --root <pkg> awc --archive audio --limit 100 --max 1000 \
        --music-wav-out ./music-wav
```

The default `--music-skip-policy zero` supports 48 kHz Opus channels with
**zero block skips**, including validated mono/stereo descriptor counts.
One native stereo discovery export produces **12,676,400 frames per channel /
264.092 seconds** at 48 kHz. Nonzero stereo skips remain refused. The opt-in
mono overlap policy below supports a measured
subset of nonzero skips after exact compressed-packet identity checks. `--opus-library`
and `--wav-pre-skip` also apply here. Output uses the same explicit assumed
pre-skip/declared-duration policy as standalone WAV. `music_wav_metadata` records
channel identity, block skips, frame counts and decoder version;
`music_wav_skipped` records unsupported profiles or failures. Existing music
mono Ogg export remains unchanged; stereo uses the corrected path above.
Missing dependencies and malformed/decode errors
exit nonzero while independent requested exports continue.

A separate music split was frozen before block research: **16 discovery /
15 validation containers**, covering **35 / 18 channels**, with no overlap with
the earlier standalone cohort. All **35 eligible zero-skip channels** decode
successfully in the post-freeze regression, totaling **127,030,977 frames**;
**18 nonzero-skip channels** are refused by the default policy. All 155 corruption controls
refuse. Packet-reorder controls discriminate 26/35 eligible channels; nine
same-duration cases do not, so structural counters are not integrity proof.
Eight selected same-libopus FFmpeg comparisons agree within one PCM16 unit.
These are reused archive observations with unconfirmed skip/alignment semantics,
not an independent original-audio oracle.

**Verified music packet overlaps:** add `--music-skip-policy verified-overlap`
to `--music-wav-out` to remove a block prefix only when its whole compressed
packets exactly repeat both the preceding block suffix and the reconstructed
packet history. The skip must also use a discovery-observed size; all original
allocation, padding, packet and seek-counter checks still apply. No partial
packet removal, silence insertion, concealment or re-encoding is used.

```bash
python3 -m gta6x --root <pkg> awc --archive audio --limit 100 --max 1000 \
        --music-wav-out ./music-wav --music-skip-policy verified-overlap
```

On the unchanged split this adds **16/16 discovery** and **1/2 validation**
nonzero channels: **52/53** music channels supported in total. One held-out
25,920-frame skip remains refused because its size was absent from discovery;
its later exact-overlap observation did not extend the frozen profile. The
30 supported overlap events remove 277 repeated packets / 265,920 frames.
All 35 earlier zero-skip WAV hashes and metadata remain identical. Thirty
same-duration wrong-byte controls refuse. Three selected same-libopus FFmpeg
comparisons have exact output lengths and maximum PCM16 difference one;
this is wrapper agreement, not an independent audio oracle. Per-block
`packet_overlap` evidence and removed packet/frame totals are included for
nonzero channels. The assumed global pre-skip, original alignment and engine
decoder reset/pre-roll behavior remain unconfirmed. Legacy music Ogg is unchanged.

`music` extracts the separate audio-config record table: **1,589 records**,
**1,589 distinct config ids**, **272,442.8 s** total, each with duration, hash A,
hash B and the AWC stream id (`hash B & 0x1FFFFFFF`). Records are found by the
46-byte record layout, fixed markers and duration range (20 s to 2,000 s).
It does not infer playback order or native station membership.

`--min-ms` and `--max-ms` apply while scanning, so an explicit wider range can
include shorter or longer marker records. The defaults still produce the
same 1,589 rows. With `--limit 18 --min-ms 0 --max-ms 4294967295`, the measured
prefix yields **2,406 marker observations** (812 additional short / five long).
Those extra observations are not automatically identified songs; invalid
duration ranges are rejected before export.

**Indexed config:** `music --config` joins only immediate aligned compressed
pages through a short terminal page, then checks the complete bounded index.
Record spans are storage upper bounds, not proven object sizes. Raw families,
kinds and opaque tails remain explicit. Separate name tables are accepted only
when every encoded string offset and full name hash agrees; proximity is
insufficient. `WaveSlotsList` references must exhaust the local kind-8 index.
Their stored order is a wave-slot listing, not a radio playlist.

```bash
python3 -m gta6x --root <pkg> music --config --limit 8 --name Radio --max 30
python3 -m gta6x --root <pkg> music --config --limit 18 \
        --max-nodes 1000000 --out ./audio-config
```

`--name` filters the human display; JSON and `audio-config.json` retain the
complete bounded report. Unsupported/incomplete resources have explicit
reasons and a nonzero exit status; supported resources remain inspectable.
Discovery produced **4,781 checked names and 740 wave-slot links**. A parser
frozen before the reserved config window reproduced **3,020 index records**
there; that window contained no eligible checked name tables or slot lists.
No natural music-record ownership or station/playlist graph was established.

Add `--index-sections` to inspect the independently measured length-section
index profile for raw family 581:

```bash
python3 -m gta6x --root <pkg> music --config --index-sections --limit 8 \
        --max-nodes 1000000 --out ./audio-config-sections
```

This opt-in view adds **115,183 discovery index records**, taking the same
window to **131,523 records**, plus **2,040 counted groups / 7,305 raw u32
values**. Group boundaries and original byte offsets are checked; group roles,
value targets and ordering semantics remain unknown. These are not recovered
station memberships or playlists. The original strict parser is unchanged.
Fresh discovery ranges in `common.rpf` and later `audio.rpf` supplied no
station-definition evidence. The separately frozen later-audio validation
window had no eligible config indexes, so the new layout has **no positive
held-out examples**. Existing protected station-name candidates were not used
for fitting; a truncated final resource still produces an explicit refusal.

**External credit candidates:** supply `--catalog ./credits.json` to annotate
music records using full 32-bit hash B. The catalog contains explicit spelling
hypotheses, for example this authored input:

```json
{
  "format": "gta6x-music-catalog-v1",
  "source": "authored example",
  "entries": [
    {"normalized_name": "authored_song", "title": "Authored Song",
     "artist": "Authored Artist", "station": "Authored Station"}
  ]
}
```

```bash
python3 -m gta6x --root <pkg> music --limit 18 --catalog ./credits.json \
        --out ./music-credits
```

No track catalog is bundled. Supplied spelling is hashed as written using the
existing case-insensitive JOOAT function; normalization is the catalog author's
choice. Every distinct matching title/artist/station is retained, including
ambiguities; a shared 29-bit stream id alone cannot match. Reports label these
as external hypotheses and retain the original record fields. In a local
catalog derived from [Rockstar's public credits](https://www.rockstargames.com/VI/credits),
**673/1,589 records** matched supplied full-hash spellings; **seven** retained
multiple credit candidates. The expanded catalog adds 74 records over the
initial pass. This is hash agreement with external facts on
reused observations, not held-out song-identification accuracy. The credited
station label does not prove a native station link, an AWC bank association or
playlist order. The name dictionary is unchanged.

The public-source comparison retains all **743 entries across 20 music
stations** in the supplied GameSpot paste, alongside Rockstar's credit
sections. Primary credit labels are preserved when sources differ; shortened
titles, artist-credit differences and multiple versions remain visible.
Additional Rockstar music/program credits bring name-candidate coverage to
**737 records**, with their station context left unassigned. The main catalog
still has **99 unmatched credit rows**, including eight original compositions
whose performers are unspecified. No full station or playlist extraction is
claimed, and no song list or generated catalog is bundled.

A focused Symphony/Vault follow-up found six provisional candidates in other
sections using documented title/remix excerpts and a consistent `_dsc` station
suffix. Each full hash was checked against fresh original record bytes. No new
Symphony or Vault credit was resolved: they remain **0/16 and 1/24 candidate
rows**, respectively. The Vault row uses a shared title excerpt and does not
confirm a recording. A generic classical movement fragment matching another
artist's title was rejected. Existing source splits and earlier results were
preserved; the wider duration scan added no song matches.

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

The ordinary body summary and instance reader share this exact block model,
including the first type/length pair at `+8`. Historical `field_a`/`field_b`
keys retain those raw words; `entries` and `record_count` count table blocks,
not typed records. JSON adds `status`, `reason`, `table_complete`, `block_count`,
block extents and logical/padding byte counts. Missing terminators leave
payload bounds null. Unsupported bodies remain unresolved even inside a
checksum-verified container. All 2,056 frozen-source summaries match the strict
reader (15,217 / 2,232 / 4,901 blocks across discovery/comparison/script groups);
this is reused-source structural regression, not semantic-oracle validation.

Some PSIN resources are larger than one zlib page and are stream-split; a page
then starts with `PSIN` but declares a section longer than the page. Those are
reported as **fragments** (declared size, missing bytes, partial body), not as
a separate format.

`CHKS` is now verified: the stored checksum is RAGE **JOOAT** (signed bytes,
seed `0x3FAC7125`) over the entire container with the `CHKS` length and checksum
fields zeroed, stored big-endian. All **821/821** complete containers in an
8 MiB `data.rpf` sample verify (and the `psin` command reports 788/788 for its stream-local sample). The platform word in the sample is ASCII
`zppp`; other archives may use another tag.

**PSIN resource headers:** `psin --resource-header` adds a bounded LRSC view
without decoding instances. The measured 80-byte payload carries `0DRP`,
version 122, checked zero/sentinel words, and counts that must match the local
LSCH structure, LENM enum and PSIN block tables. Its full selector word must
choose a block containing exactly one uniquely defined local typed record.
The result is a **record candidate**, with its source span and schema identity;
its role as a root object is unconfirmed. LRSC is not treated as a fixup list.

```bash
python3 -m gta6x psin ./metadata.psin --resource-header --out ./header.json
python3 -m gta6x psin ./metadata.psin --resource-header --instances \
        --max-nodes 100000 --out ./metadata.json
```

The flag implies schema mode. `resource_header` retains all header bits, checked
counts and one candidate association, without expanding its fields or following
a graph. Imported registry definitions cannot authorize it. Unsupported profiles
keep a reason and no header/candidate prefix; requested failures exit nonzero
while verified schemas and independent instance output remain available.
Header and instance views share `--max-nodes`, with separate node counters.
A complete header costs six nodes; an unresolved view costs one. Discovery
matches **821/821** distinct source containers; frozen validation matches all
**2,390 observations / 2,228 distinct payloads**, with no cross-role source-hash
overlap. All 19,266 malformed controls and 3,211 under-budget controls refuse;
opaque-target changes intentionally preserve the view. Prior instance readers
and value/binding modules are unchanged. These are reused structural cohorts,
not root-object or pointer-relocation ground truth.

**PSIN bucket owners:** `psin --bucket-maps` adds a guarded local bucket/reference
view and checks the existing LRSC record candidate. One measured profile links
opaque-key entries to bounded, locally typed records. Exact schemas, counts,
occupancy markers, complete allocations and every reference must agree before a
map emits links. Duplicate key storage retains every target; missing/conflicting
schemas and unsupported layouts remain explicit. The field type is not assigned
a general primitive or gameplay meaning.

```bash
python3 -m gta6x psin ./metadata.psin --bucket-maps \
        --max-nodes 100000 --out ./bucket-owners.json
```

JSON retains owner/field paths, physical slots, opaque key bytes, target record
identities and exact agreement with the LRSC **candidate**, when present. This
view shares `--max-nodes`; `--max-depth` bounds embedded-owner scanning. Partial
or refused requested inspection exits nonzero while preserving independent valid
results. Existing instance values and ordinary record-graph edges are unchanged;
bucket links are a separate view and are not merged into graph reachability.

Native role-preserving checks trace owners for **47 discovery / seven validation**
queried hash-bearing records across **28 / seven** complete resources, including
four resources recovered from two pages each. The broader bucket view validates
**171 / 57 local reference links**. The seed resources include five proposed Dirty
South Classics hash values and one Cocoteo value, among other record types. The
container, field and key roles remain unknown; these references do **not** establish
song-to-station membership or a playlist. Vault titles remain unresolved and the
existing TRACKID conflicts remain intact.

**PSIN record associations:** `psin --record-graph` indexes only existing
checked local field, structure/reference/enum-array and map-entry record links.
It implies instance decoding and independently checks LRSC for an optional
candidate anchor. Nodes refer to `blocks[block_index].records[record_index]`;
edges retain source field-index paths, kind and optional element index. Scalar
values, embedded records and target fields are not copied or expanded. References
inside embedded structures attach to their owning top-level node. Aliases and
cycles remain finite indexed links; nulls are counted without invented nodes.
Text/pool associations and unknown raw words do not become record edges.

```bash
python3 -m gta6x psin ./metadata.psin --record-graph --max-depth 16 \
        --max-nodes 1000000 --out ./record-associations.json
```

`record_graph.reachability` reports bounded distances from the **LRSC candidate**,
not a proven root. `--max-depth` limits both embedded instance decoding and
candidate reachability. Nodes outside the checked horizon remain present;
depth-frontier counts are explicit and a missing distance does not prove a
record is unreachable. Missing header support yields an unanchored partial
graph. Partial graphs are normal output; adding explicit `--resource-header`
still requests strict header validation. Graph budget/malformed-view refusals
exit nonzero while independent verified schema/header/instance views remain.
All three views share `--max-nodes` with separate node accounting.

Unknown fields, unrepresented blocks and excluded associations remain counted.
A complete graph view describes only the supplied checked associations, never
a complete object graph or gameplay meaning. Across the unchanged cohorts,
3,208 graphs index **590,492 record observations / 264,745 checked edges**, with
190,222 candidate-reachable record observations after the opaque-key map extension
below. Aliases and reused sources are included; these are not independent
semantic trials. All 2,142,630 earlier values and prior complete fields and
associations are preserved. The same three large instance-
budget refusals remain unavailable; 293 text links are explicitly excluded.
The original graph audit refused all 5,660 tampered-link/candidate controls and
3,208 budget controls. Its discovery CLI check indexes five records / two edges /
three candidate-reachable records, explicitly partial because one field remains
unknown.

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
no examples in that range; map-entry validation uses the supplementary cohort
described below. Enum_bitset64 still has discovery evidence only. These are consistency
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
missing schemas and unsupported array/map/bitset profiles produce explicit unresolved
fields instead of fabricated values. Nonfinite floats and invalid Boolean/enum
values keep their bits and a reason. JSON contains no NaN/Infinity numbers.
Block/record offsets refer to the decompressed PSIN container; field offsets
are relative to the owning record.

The body reader includes the first block-table entry at +8, checks AA padding,
the PP terminator, every block extent, zero alignment padding and exact EOF.
Bad bodies refuse instance output while retaining any verified schema. A
resource/block/record status of `partial` is expected when fields are unresolved;
`complete` means its listed fields were handled, not a confirmed object graph.
A complete structure-array field means its record links were validated; linked
records may still be partial and retain their own unresolved fields.
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
by encoding it back to its exact source bytes. Most resources remain partial.
These are byte/structure consistency results, not independent confirmation of
type semantics. The script sample is additional cross-archive evidence.

**Bounded enum bitsets:** `--instances` also reads a narrow local `0x65`/`0x68`
profile. The stored bit count must match a dense LENM index domain; the rounded
32- or 64-bit storage extent must exactly reach the next field or owner end.
The owner and enum must each have one local definition, preceding fields must
have known nonoverlapping extents, and unused high bits must be zero. Gaps,
ambiguous definitions, sparse enums and `0x63` remain unresolved.

Supported fields retain exact `value_bits` and decimal-string `value_unsigned`,
with set-bit indices in `value` and all LENM aliases in `set_bit_members`.
Little-endian bit positions and enum annotations remain explicitly **inferred**;
no game flag semantics are assigned. Each set index and alias consumes the
existing node budget.

The frozen discovery/comparison/script cohorts add **297 / 6 / 0** bitset
values, respectively; every value round-trips and all **1,069,517** prior
decoded leaves persist. The comparison additions come from one container.
These reused sources provide structural consistency, not an independent flag
oracle. Enum_bitset64 still has discovery evidence only; most bitset fields
remain unresolved under the exact-extent rule.

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
values. Most resources remain partial. The reference candidate fits all
**55,884 nonzero pool words**, including their local target-stride alignment;
wrong target order and other bit partitions fail that consistency check.
ASCII has discovery evidence only; no text-pool examples occur in comparison
or script. These previously examined samples provide consistency evidence,
not a fresh blind holdout or independent semantic oracle.

**Nested-map entry links:** `psin --instances` supports two additional
nonempty local map descriptor trees: hash32 → (opaque `0x15` → (hash32 →
hash32)), and opaque `0x15` → (hash32 → hash32). Owning and target schemas
must agree as bounded descriptor trees even when their synthetic descriptor
indices differ. Exact 32-byte entry rows, named field offsets, whole local
slots, equal count words and full reference/stride bounds are checked.

The map links already present typed entry rows; it does not recursively expand
them, decode opaque keys or assign `0x15` a scalar width or meaning. Targets
can remain partial. Empty, cyclic, imported, mismatched or other trees remain
unresolved with no prefix links. Existing map counters include these results.
Discovery adds **13 maps / 60 links from one source**, including 12 opaque-key
maps and 48 links to partial rows. Frozen comparison/script/supplementary
validation has no eligible candidates reaching the new resolver, so there is
**no held-out profile confirmation**. All prior values, complete bindings and 293 text links are
preserved; the same three existing budget refusals remain. This is bounded
structural support from discovery, not independently confirmed map semantics.

**Opaque-key map entry links:** an additional exact local `0x054f`/zero-auxiliary
key descriptor can associate existing entry rows when local key/value descriptors,
whole header slots, count words, reference bounds and declared entry strides
agree. Supported values are a locally declared 12-byte structure, enum32 or
float32, with measured entry strides of 24/16/16 bytes respectively. The key
stays unknown: its bytes are not read, and no key width, value or pointer meaning
is inferred. Empty and other layouts remain unresolved without prefix links.

One discovery source adds **four maps / 18 existing-row links**, all to partial
records. `--record-graph` includes exactly 18 additional edges; scalar counts
are unchanged. The unchanged 2,390 validation observations contain **zero
eligible examples**, so there is **no held-out profile confirmation**. Prior
values, complete fields and associations persist, including the three earlier
budget refusals. All 32 new discovery mutation controls refuse. Unsupported
attempts can acquire a more specific refusal reason. These are contextual
structural associations, not confirmed key types or map lookup semantics.
A native discovery CLI check includes all four maps and adds 18 edges to the
same 895 record nodes; candidate reachability rises from 744 to 762 records.

**Contextual ASCII-pool links:** `psin --instances` also links measured named
field profiles with exact type word `0x42` or `0x44` and zero auxiliary word
to existing nonempty `0x10` pool entries. These are contextual storage profiles;
the schema's `type_name` remains unknown. The full local owning slot must fit
without another named field start inside it. Targets use the full reference word
and must start exactly at an existing complete printable-ASCII/NUL entry.
The 24-byte `0x44` slot additionally requires matching length words, marker
one and zero reserved bits. Null, empty, imported, ambiguous, interior-string,
other text and mismatched-header cases remain explicitly unresolved.

The field's `text_reference` links `blocks[block_index].pool.elements[pool_element_index]`
with source spans and original bits, without copying text or adding scalar
observations. Pools are decoded and budgeted once even for forward/aliased links.
Summary keys `text_reference_fields_attempted/resolved/unresolved` and
`text_reference_pool_entries_linked` aggregate with the `instance_` prefix.
Discovery adds **53 links** (4 word / 49 header); the frozen supplementary
cohort adds **240** (231 / 9) and leaves **10,920** attempts unresolved.
The comparison, script and earlier supplementary groups contain no candidates,
so they provide regression evidence rather than text-link accuracy estimates.
All **2,142,630** previous value observations and earlier bindings are preserved.
These reused frozen cohorts establish byte/shape consistency, not independent
confirmation of application meanings. Exact `0x07` and `0x054f` profiles did
not supply discovery text links and were left unchanged.

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
bytes or unique values. Structure arrays use the bounded record links described
below; map entries use a separate bounded profile. General pointer traversal
remains unsupported.

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
unresolved outside the supported profiles; most resources remain partial. These checks establish
bounded byte/shape consistency, not independently confirmed header semantics.

**Structure-array record links:** `--instances` also resolves a local structure
element descriptor (exact code `0x05`, synthetic ID `0x100`, offset zero) when
its referenced structure hash has exactly one local definition with positive
size. The same equal-u16/zero-tail and null-empty header restrictions apply.
Nonempty targets must match that exact structure hash, with block length and
offset divisible by its declared stride and the entire array span bounded
inside the block. Matching sizes/signatures do not substitute for an exact
local type match. Nonempty arrays with missing/duplicate definitions or imported
registry owners/targets remain unresolved. A missing-definition null-empty
exception is described below.

The field's `array.mode` is `record_links`. Its `elements` contain
`status: record_reference`, `block_index`, `record_index`, offsets, lengths and
structure hashes. Follow a link in the exported JSON using
`blocks[block_index].records[record_index]`. Records are already decoded by the
normal block reader; the array does not copy or recursively expand them.
Aliases and cycles stay finite links. A valid link does not claim that the
referenced record's fields or gameplay meaning are understood; inspect that
record's own status. All interpretations remain inferred.

`structure_arrays_resolved` includes empty arrays;
`structure_array_records_linked` counts each link, including aliases. Report
aggregates use the `instance_` prefix. Each link consumes the shared node
budget; records are decoded once in their existing rows. Link creation adds
neither duplicate scalar values nor extra `decoded_values` observations.
Reference arrays use the bounded two-hop links below. Other pointer/array
profiles and recursive graph expansion remain open; map-entry links are
described below.

The same frozen source split was preserved without promotions or registry
refitting. Discovery / data-validation / script resolve **25,526 / 130 / 0**
arrays, including **16,745 / 31 / 0** empty arrays, linking **15,392 / 293 / 0**
existing records. All **1,069,517** prior value observations are preserved and
byte-round-trip. At that milestone, **788** links led to partial records and
missing/ambiguous local schemas left **15,059** structure-array fields unresolved.
Wrong-record-order controls discriminate 2,278 spans;
2,277 also have discriminating byte content. These are bounds/type/association
consistency checks on previously examined sources, not a fresh blind holdout
or independently confirmed pointer semantics.

**Null-empty arrays with missing element schemas:** an exact local structure
descriptor and a whole, nonoverlapping 16-byte all-zero header now identify an
empty array without requiring the unused element definition. Its JSON keeps
`element_schema_status: missing`, `stride: null`, `target: null` and no elements.
Only the header is recognized; the schema is not resolved. Nonempty headers,
ambiguous definitions and invalid descriptors remain refused. Known-schema
empty arrays retain their earlier output exactly.

The frozen original plus newly recovered stored-tail cohorts recognize **19,357
headers**: **15,641 discovery / 3,716 validation**. All 2,296,998 previously
decoded values and checked links in those cohorts persist, with no new scalar
observations or edges from this profile. That total includes 154,368 existing
values in the 14 newly recoverable containers. The same three instance-budget
refusals remain. All 58,071 source mutation controls refuse, and graph checks
reject contradictory null-header metadata. These are structural consistency
checks; bitset meanings and missing definitions remain unknown.

**Reference-array record links:** `--instances` resolves one inferred profile
for local synthetic element descriptors with exact code `0x07`, offset zero
and zero auxiliary attributes. The usual equal-u16/zero-tail/null-empty header
rules apply. A nonempty header must select a complete, eight-byte-aligned span
in an intrinsic `0x07` word pool, with no conflicting local structure definition.
Each word is retained and independently checked: zero becomes an explicit
`null_reference`; a nonzero word must select a whole record under exactly one
positive-size local definition for its target block's declared type. No common
base class, inheritance relationship, global fallback or recursive reference
chain is inferred.

`array.mode` is `reference_record_links`. Elements retain `reference_bits`,
`reference_data_offset`, `reference_byte_length` and `pool_element_index`.
Nonnull entries use the same block/record links as structure arrays; null
entries have `target: null` and no invented record. Any invalid/ambiguous member
leaves the whole array unresolved with an explicit failed slot/word diagnostic
and **no prefix links**. Shared node limits count every slot, including nulls
and aliases, plus the standalone pool view. Targets are not expanded and
`decoded_values` is not inflated. Bare reference pools retain their candidate interpretation. Named `0x07` fields
can use the bounded contextual profile below; no global primitive meaning is assigned.

Counters `reference_arrays_resolved`, `reference_array_records_linked` and
`reference_array_null_entries` also appear in reports with an `instance_`
prefix. With the unchanged frozen split, discovery / validation / script
resolve **31,390 / 2,795 / 0** arrays, link **51,779 / 4,040 / 0** records and
retain **14 / 0 / 0** null slots. **7,336** arrays have mixed target types;
**23,183** links led to partial records before map-entry support. All **28,844** previous hash32/structure
array associations and **1,069,517** value observations are preserved and
byte-check successfully. Wrong slot order discriminates 12,608 spans.
Before map-entry support, 2,055 of 2,056 resources remained partial and one
had all listed fields handled; `complete` still does not establish full byte coverage or gameplay
semantics. **15,090** recognized array fields remain unresolved. These are
consistency results on reused sources, not blind accuracy or semantic ground truth.

**Standalone reference fields:** `--instances` also binds exact named `0x07` /
zero-auxiliary fields in local schemas. The full eight-byte word must fit its
owning record/block and cannot contain another named field's start; synthetic
`0x100` descriptors are excluded. Zero words become explicit null references.
Nonzero words must select a whole record under the target block's unique,
positive-size local definition, with full block/offset stride and span checks.
Imported owners/targets, unsupported attributes, short/overlapping slots and
invalid targets remain unresolved with a reason. Original bits are retained
when the slot is safe to read.

The field's `reference` object records the inferred profile, original word and
absolute decompressed-container source offset, plus a `record_reference` link or `null_reference`.
Target lookup uses the same block/record indices as array links, without
recursive expansion or copied values. The raw schema type and `type_name: null`
remain unchanged: this is a contextual binding, not a globally confirmed LSCH
primitive. A complete field means its association was handled, not that the
target's fields or gameplay semantics are understood. Each attempt/binding/null
consumes the shared output budget. `decoded_values` is unchanged.

Counters `reference_fields_resolved`, `reference_fields_linked`,
`reference_fields_null` and `reference_fields_unresolved` also appear with an
`instance_` report prefix. Discovery / frozen validation / script resolve
**102,280 / 11,633 / 0** field observations: **31,691 / 2,130 / 0** record links
and **70,589 / 9,503 / 0** nulls. All **63,029** previous array associations and
**1,069,517** value observations remain identical and byte-check successfully.
Wrong-endian words fail every one of the 33,821 nonzero field-target checks.
**20,013** links targeted partial records before map-entry support. At that
milestone, 2,055 resources were partial and one had all listed fields handled. The split and registry remain
frozen; results are consistency evidence on reused sources, not blind accuracy
or independent semantic confirmation. Fixups and other profiles stay open;
bounded map-entry associations are now supported as follows.

**Bounded map-entry links:** `psin --instances` recognizes a local map
field with distinct synthetic key/value descriptors at offset zero. The key
is exact hash32 with hash32, bool8, or a uniquely local structure value. A
separate nonempty enum32-key/structure-value profile is also supported when
one representable local LENM definition contains every stored key. The 24-byte header requires a leading
64-bit word of one, an entry reference, two equal u16 words, and a zero u32
tail. All words retain their bits; the leading word's meaning and the u16
count/capacity roles remain unknown. An empty map requires a zero reference.

A nonempty reference selects a block with exactly one positive-size local
entry schema. Its two named fields must match the descriptors: the supported
key at zero and value at a declared offset of at least four, fully inside the entry
stride. Structure values are **not** assumed to start at eight. The block and
reference offset must contain whole record strides, and the complete entry
span must fit the logical block. Imported registry owners/entry/value schemas,
ambiguous definitions, unsupported descriptors and header variants stay
unresolved, with a reason and no prefix entries.

The field's `map.mode` is `entry_record_links`. Its `entries` retain stored
order and duplicates, with `block_index`/`record_index` links to existing rows.
Use `blocks[block_index].records[record_index]` to inspect each key/value pair.
No dictionary conversion, hash lookup, bucket, insertion-order, inheritance or
complete object-graph semantics are claimed. Entry fields may still be
partial. Header associations and links share the node budget; linking adds no
new scalar observations. Counters `maps_resolved`, `maps_unresolved` and
`map_entries_linked` also appear with the report-level `instance_` prefix.

Discovery resolves **15,274 / 15,293** map fields, including **11,256** empty
maps, and links **29,366** entry records; **19** descriptor profiles remain
unresolved. The original 223 data / 1,012 script validation observations have
no maps. Their frozen source lists were preserved, and a separate map split
adds **1,155 validation observations** selected by archive offsets before
examining their map headers. These supplementary sources were already schema
registry providers; this is **not a fresh blind holdout**. The combined
validation split contains 2,390 observations / 2,228 distinct payloads, with
zero discovery-payload overlap. No validation input was promoted, no profile
was tuned from validation results, and the registry remains frozen.

Supplementary validation parses **1,152 / 1,155** resources and resolves
**3,782 / 7,829** map fields, including **1,645** empty maps, linking **22,469**
entry records. It explicitly refuses **4,047** map fields: 2,220 unsupported
value descriptors, 1,269 unsupported keys and 558 unvalidated headers. Three
resources exceed the same 250,000-node per-resource audit budget they exceeded
before implementation; their maps are excluded from these counts. Across all
five cohorts, **2,142,630** prior values round-trip unchanged, as do **110,056**
array and **196,274** standalone-reference associations. Reversed key order
discriminates 4,393 spans, and nine maps retain duplicate stored keys. Of 3,208
parsed resources, 3,183 remain partial and 25 have every listed field handled;
that status does not establish byte coverage or gameplay semantics. These
results establish bounded structural consistency, not semantic ground truth.

Schema JSON also exposes lossless `base_type_code` and `type_subcode` bytes
alongside the original 16-bit `type_code` and complete `type_word`. Structure
flags, layout-signature and alignment candidates retain their original unknown
words; they are not silently promoted to confirmed meanings.

The enum-key extension adds **61 maps / 182 entry links**: two/nine in discovery
and 59/173 in the frozen supplementary validation cohort. All 61 bad-key
controls refuse before emitting links. Targets remain ordinary typed rows;
136 linked rows are still partial. All 2,142,630 previous value observations,
110,056 array bindings, 196,274 reference-field bindings and 19,056 earlier map
bindings are unchanged. Three pre-existing source budget refusals are retained,
with no new source refusals. Empty enum-key maps, missing/ambiguous/imported
LENM definitions and other key/value profiles remain unresolved. No validation
promotion or fitting changes were made; these reused structural cohorts are
not independent semantic ground truth.

**Enum-record arrays:** native `psin --instances` also handles one nonempty
local enum32-array profile. The exact synthetic descriptor and one local LENM
definition must match a unique four-byte target schema containing one named,
offset-zero enum32 field. The full referenced span must fit whole local rows,
and every word must match LENM before links are emitted. Values, signedness
and aliases remain in the existing typed rows; no scalar values are duplicated.
Empty arrays, untyped storage, ambiguous/imported definitions and other layouts
remain unresolved.

Frozen discovery/supplementary validation adds **41 arrays / 260 links**
(19/27 discovery, 22/233 validation). All previous 2,142,630 value observations
and earlier array/reference/map bindings remain unchanged. All 41 bad-member
and 41 misaligned-offset controls refuse; wrong-endian checks discriminate
244/260 words, with 16 nondiscriminatory cases retained. The same three source
budget refusals remain. These are reused structural cohorts, not an independent
semantic oracle. No global meaning is assigned to the observed low-ID target.

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
closed root (DTDs rejected), PSIN must have all seven sections and a verified
CHKS checksum. Supported PSIN chains may also end in a short stored tail after
one or more full compressed pages. Exact section lengths and CHKS authorize
its extent; a failed inflate alone does not establish stored bytes. Wholly
stored containers, interior stored pages and alternate PMAP schemas remain
unsupported.

```bash
# list complete XML/PSIN resources
python3 -m gta6x --root <pkg> structured --archive common --limit 16 --max 20

# extract them
python3 -m gta6x --root <pkg> structured --archive common --out ./structured
python3 -m gta6x --root <pkg> structured --archive data --limit 16 --out ./structured
```

Output is `xml_<root>_at_<offset>.xml` or `metadata_PSIN_at_<offset>.psin`,
plus `structured.json` (page segments, sizes, roots). Mixed chains include
`segment_storage` labels in structured and schema JSON. Stored segment byte
counts are exact; alignment padding and unrelated trailing bytes are excluded.
Measured with `--limit 16` on 1.0.2.1:
`common.rpf` yields 259 complete XML documents (79 joined from multiple pages)
and `data.rpf` yields **1,049 complete PSIN containers (32 joined)**, including
four stored-tail additions. Joined files are written only after validation.

Across the unchanged research ranges, stored tails add **four discovery / ten
validation containers**, preserving all **3,211** prior payloads and hit
dictionaries exactly. The 14 distinct additions contribute 2,989,236 decoded
bytes, including 302,260 stored bytes. All 84 malformed/bounds controls refuse.
These are recovered checksum-valid additions, not an exhaustive coverage rate.
New discoveries are kept separate from the frozen schema/provider manifests;
no validation source was promoted or used to retune the implementation.

A separate discovery search across data/common/levels windows examined 1,167
compressed streams and 833 PSIN starts. It found standard LSCH containers and
known stored-tail partials, with no bounded PMAP/PSCH container example. No
alternate-container parser or schema meaning was added.

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

Add `--metadata` for native program stage/model and input, output and patch
signature inspection:

```bash
python3 -m gta6x --root <pkg> --json shaders --archive shaders --limit 4 \
        --metadata --max 10
python3 -m gta6x --root <pkg> shaders --archive shaders --limit 4 \
        --metadata --out ./shaders
```

With `--out`, metadata is attached to each `shaders.json` record and the `.cso`
bytes are unchanged. Without `--out`, `--json` returns a summary and up to
`--max` full records; the ordinary listing retains its original format when
`--metadata` is absent. `--max-records` bounds metadata output per shader
(default 4,096). Requested incomplete metadata returns a nonzero exit code
with reasons, while preserving valid shader extraction.

This reads public DXBC/DXIL container metadata, not shader instructions or
game material bindings. Unsupported signature versions and unknown numeric
values remain explicit; other chunks retain their tags, spans and hashes.
Declared DXIL spans are bounded and hashed, with no disassembly or
integrity-digest verification. Their measured contents are not ordinary LLVM
bitcode and remain opaque. The format reference is LLVM's
[DirectX Container documentation](https://llvm.org/docs/DirectX/DXContainer.html).

Frozen disjoint windows contain **742 discovery / 380 validation** wrappers,
with **4,012 / 3,645** signature parameters that round-trip to their source
bytes. All **1,122** prior extraction results persist; 4,488 corruption and
1,122 budget controls refuse. There is no cross-role payload hash overlap or
validation-driven profile change. SHDR/SHEX and patch signatures have authored
coverage only. These are public-format/source consistency checks on a previously
indexed package, not an independent reflection or runtime shader oracle.

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

Texture names are candidates recovered by matching observed strings to stored
64-bit hashes. A blank name means the selected dictionary has no match; it does
not imply a texture decode failure. The default dictionary is `names.json` in
the current working directory; `--names PATH` selects another one.

A local source-string investigation added 117 previously unresolved texture
hashes, increasing named streamed records from 671 to 788 in the measured
package. Each addition reproduces original source bytes and the texture's raw
hash-table entry. Existing names and lookup order were preserved. These are
hash/source agreements, not independent proof of asset associations. The first
200 default rows still have 112 names; the additions occur elsewhere. Recovered
strings and source observations stay in the private dictionary/research files,
not a bundled game-name list. `names build` creates a fresh dictionary rather
than merging existing enrichments; use a different `--out` to preserve one.

The original build on 1.0.2.1 produced **50,864 lower-case hashes**, **36,943 case-sensitive
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

Earlier full `anim.rpf` index scan (about 3.4 minutes in Python): **130,771 streams** and
**2,327 names**:

| Signature | Count | Meaning |
|---|---:|---|
| zero-prefix | 78,809 | zero-prefixed pages, often with pointers/name data |
| raw | 25,273 | unclassified payloads |
| page-directory | 22,904 | `0DRP` at +0x10 |
| clip-stream | 1,788 | legacy label for `u32 2/3` + `01 01 00 00` candidate packed headers; clip identity unverified |
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
binding and keyframe values remain open; those upstream record interpretations
have not been established by the native resource browser below.

**Native resource metadata:** `--resources` also reconstructs the observed
version-122 `0DRP` resource chains and includes a `resources` list and
`resource_summary` in `anim.json`. For example:

```bash
python3 -m gta6x --root <pkg> anim --limit 1 --resources --out ./anim-resources
```

The reader exports local structure headers and raw field descriptors,
enum headers and full-width member bits, and data-block types/offsets/lengths.
Header words with unknown roles remain named `unknown_*`; field type meanings
remain explicitly unknown in this format. No PSIN registry definitions or
inferred PSIN primitive labels are silently imported. Duplicate definitions
and enum aliases remain separate observations. Decompressed offsets refer to
the joined resource; each `segments` entry records its archive offset,
compressed size and inflated size.

Only immediately adjacent zlib streams across zero alignment padding may join.
A page whose inflated size is a multiple of 64 KiB can continue; a shorter
terminal page is required. Independent resource starts, gaps, nonzero padding,
scan cuts, unsupported headers/versions, unsafe pointers and incomplete spans
produce explicit refusals. Virtual addresses use full-width subtraction from
the observed base, without masking high bits. Every metadata table and block
span must fit the assembled resource. This framing has no verified checksum
or declared total resource length: a parsed result deliberately stays
`partial`, without claiming complete byte coverage, clip identity or curve
values. Unknown header references are recorded without following them.

Resource assembly is capped at 16 MiB / 256 segments. The existing zlib carver
retains its separate capped-stream policy. `--max-nodes` defaults to 100,000
metadata nodes across all selected archives; increase it for larger surveys.
Refused resources include a reason and no prefix tables. The CLI returns
nonzero if any candidate is refused; JSON or `--out` retains every refusal.
`--max` caps displayed rows, while an output manifest retains the budgeted
results. Without `--resources` or `--clip-records`, the original index shape
is preserved; the legacy `clip-stream` diagnostic clarifies its unverified identity.

Frozen discovery / validation ranges contain **618 / 377** resource candidates,
all structurally parsed: **27,089 / 16,957** structure observations,
**218,458 / 126,912** field descriptors, **399,769 / 247,432** enum-member
observations and **13,904 / 8,765** bounded data-block spans. Joining was needed
for **175 / 271** resources; reversed-page controls fail for all 446. All table
words round-trip to source bytes, and all 2,985 wrong-endian table-pointer
controls fail. Validation contains 377 distinct resource payloads with zero
discovery overlap. This is structural consistency on an already indexed
archive, not blind semantic accuracy or an independent decoder oracle.
No rules were fitted to validation outcomes; PSIN validation inputs and the
BCPack tables/provisional labels remain unchanged.

All **47** legacy `clip-stream` matches in these two ranges are continuation
streams inside the reconstructed resources. A header match therefore does
not identify an independently named clip. Named record-prefix links now cover
a separate observed dictionary profile, as described below; packed payload
roles and keyframe/quantization decoding remain open.

**Named clip-record links:** `--clip-records` follows supported animation
name dictionaries and adds `clip_dictionaries` / `clip_record_summary` to
`anim.json`. It works independently of `--resources`, and the two modes share
`--max-nodes` across all selected archives. Linked paths also enrich the names
and clip lists. For a full survey:

```bash
python3 -m gta6x --root <pkg> anim --full --clip-records --out ./named-clips
```

For a smaller scan, `--start OFFSET --limit N` selects a compressed-byte
window: the offset accepts decimal or `0x` hexadecimal, and N is MiB. The
scanner starts at that offset directly. This is useful when clip dictionaries
are far beyond the archive's initial `0DRP` metadata. A window beginning inside
a dictionary may omit its prefix; this is a candidate census, not a complete
archive-member listing.

The supported dictionary profile checks its identifier string, local slot
array, complete acyclic node chains and declared member count. Each kind-2
record link requires a bounded **144-byte prefix**, exact local node/record
tag equality, a referenced `pack:/…clip` string with checked length/NUL/ASCII,
and a stored key matching the lowercase JOOAT hash of its filename stem.
There are no title-specific class/field tables or imported schema guesses.
Slot/chain order and duplicate keys/record aliases are preserved; no
hash-to-slot formula, insertion/play order or full object size is inferred.

Each successful entry has `status: record_reference`, its original key/tag/
reference words, `record_data_offset`, `record_prefix_byte_length`, and a
`name` with its source location/header bits. Header roles and class tags remain
unknown. The f32 at prefix `+0x78` is exposed as a **duration candidate**, with
original bits and an unconfirmed semantic role. Nonfinite/negative candidates
retain bits and an unresolved reason. No packed payload, track, bone or curve
values are decoded.

Only checked adjacent streams across zero padding may join when required
references lie beyond the current page. If all naming references already fit
a whole-page prefix, `framing: bounded_metadata_prefix` records that fact and
stops before reading unrelated neighbors. It does **not** establish the full
resource endpoint; status remains `partial`. Otherwise a short terminal page
is required. `0DRP` framing retains its stricter terminal-page requirement.
The same 16-MiB / 256-segment limits apply. Slots, members, strings and each
64-byte string chunk share the output budget. A malformed dictionary refuses
all its entries; unsupported/invalid individual record bindings retain raw node
words and explicit reasons, without invented names. Either case gives a
nonzero CLI exit. JSON/`--out` retains all diagnostics.

A separately frozen split of eight 8-MiB archive windows resolves **1,277**
record links in **191 discovery dictionaries**, then **1,432** links in **170
validation dictionaries**, with no refusals or unresolved members at the audit
budget. All 393 / 384 source streams and 191 / 170 metadata-prefix payloads
have zero cross-role hash overlap; the archive was previously indexed, so
these are structural consistency checks, not blind semantic confirmation.
All 2,709 full-path-hash and wrong-endian-key controls discriminate the stored
stem keys. No rules changed in response to validation results. All **995**
previous `0DRP` resource outputs remain identical after sharing the framing
helper. Existing PSIN/BCPack frozen inputs and provisional labels are unchanged.
Component/animation-record and opaque-buffer associations are now supported
by the additional mode below. Curve/keyframe formats remain open.

**Animation components and opaque buffers:** `--clip-components` implies
`--clip-records` and follows the next checked association:

```text
named clip → 24-byte groups → 56-byte segments → .anim prefix → buffer spans
```

```bash
python3 -m gta6x --root <pkg> anim --full --clip-components \
        --max-nodes 1000000 --out ./clip-components
```

The full-archive scan still obeys the output budget and supported profiles;
use `--start OFFSET --limit N` for smaller compressed-byte windows. This mode
adds a `components` view to each successfully bound named clip. Its groups and
segments retain source order and aliases. Each segment selects a bounded
112-byte animation prefix and an exact ASCII/NUL `pack:/…anim` name whose stem
JOOAT matches the segment key. Name/type tags, timing fields and other
references remain unconfirmed. Verified animation paths also enrich the
manifest's `anims` and name lists.

Each animation references an array of opaque packed buffers. A buffer's
observed span is its 32-byte header plus the body-byte count at header `+4`;
the observed reserved word at `+8` must be zero. The animation's size word
must equal the **largest** referenced buffer span. It is not a sum or a
pointer-table stride. Every buffer exports its checked source offset/length,
original reference/header bits and SHA-256, without copying buffer contents
into JSON. No codec, channel, bone, track, float timing or keyframe values
are decoded from these buffers.

Every followed array requires equal u16 header words, zero tail, and a whole
bounded span at its observed stride. Explicit null-empty group/segment arrays
stay empty; an animation without validated buffers remains unresolved.
Full-width pointer checks, ASCII name limits, node/segment/resource limits and
shared output budgets apply. Strings, aliases and buffer-hash work all consume
budget. Duplicate references are observations, not claims of unique animations
or unique bytes. A failed component graph yields its reason and no prefix
of groups or buffers. A parsed dictionary keeps its independently verified
clip names; framing or budget failures discard dictionary output. Such failures
produce a nonzero CLI exit and preserved diagnostics.

A naming prefix may need additional adjacent pages for component/buffer spans.
The scanner waits for those bytes in this mode; it stops early only when all
required associations fit. Existing `--clip-records` output is unchanged.
`clip_record_summary` adds `component_clips_attempted`, `component_clips_resolved`,
`component_clips_unresolved`, `component_groups`, `animation_links` and
`payload_spans`. A complete component view means its supported associations
were handled; the containing dictionary remains `partial`.

The same frozen discovery / validation windows resolve **1,277 / 1,432** clip
component views, **3,794 / 3,946** animation links and **4,956 / 5,617** buffer
references, without refusals or validation-driven profile changes. These are
**879 / 908** distinct buffer-content hashes, with zero cross-role overlap.
All emitted fields/spans/hashes round-trip to source; full-path-hash and
wrong-endian-key controls discriminate all 7,740 animation links, and the
incorrect summed-length rule fails all 1,872 multi-buffer cases. The cohorts
were previously examined, so this is reused-source structural consistency,
not independent confirmation of animation or timing semantics. All prior
named-clip outputs remain identical in default mode. Existing `0DRP`, PSIN,
BCPack splits/tables and provisional labels remain unchanged. Bounded packed
header/channel-candidate inspection is now available as follows; compressed
stream semantics and keyframe quantization remain open.

**Packed headers and channel-layout candidates:** `--packed-layout` implies
`--clip-components` and adds `animation.packed_layout` under each supported
component segment. Use a compressed-byte window or a full scan with an explicit
metadata budget:

```bash
python3 -m gta6x --root <pkg> anim --full --packed-layout \
        --max-nodes 1000000 --out ./packed-layout
```

The supported profile retains the entire 32-byte header as bits and raw LE
fields, requires the observed `u16_14=2` / `u8_1e=11` markers, and checks its
body length/reserved word. Two ordered relative offsets partition the buffer
into the header, `section_0`, `section_1` and an auxiliary tail, with no gaps or
out-of-buffer reads. The sections' compressed meanings remain unknown; offset
alignment and scalar formats are not guessed.

The last header byte's high and low nibbles sum to the number of six-byte
auxiliary rows in the tail. Rows retain their source order and raw
`u8/u8/u16/u16` fields. No codec, axis, bone, channel assignment or nibble-group
ordering is inferred. The animation prefix's checked 12-byte table is exported
as `bindings`, retaining all three raw u32 words per row. These are **channel-
binding candidates**: identifiers and type-like words stay unknown, including
values familiar from other formats. Duplicate rows and aliases are preserved.

Buffer sample-count candidates reconcile with the animation total when adjacent
chunks overlap by one sample. The stored step defines inferred index windows;
nonfinal chunks require `step + 1` samples, and the final chunk must fit. These
are metadata indices, **not decoded frames, sample values, rates or durations**.
Header words without verified roles remain numeric/raw. The overall dictionary
remains `partial`, even when this structural view is complete.

An invalid or unsupported layout returns a reason and no prefix layout rows;
its independently verified opaque-buffer associations remain available in a
parsed dictionary. Framing or budget exhaustion can refuse the dictionary.
`--max-nodes` covers header/region, binding, auxiliary and index-window output
alongside the parent modes. Larger windows may need a higher budget. Text/JSON
retain diagnostics and the CLI exits nonzero for unresolved layouts. Existing
`--clip-components` and `--clip-records` outputs remain unchanged.

Frozen discovery / validation resolve **3,794 / 3,946** animation-layout views,
**4,956 / 5,617** buffer-header layouts, **223,879 / 236,886** raw binding-row
observations and **11,030 / 16,423** auxiliary rows without profile changes or
refusals. Source bits and region partitions round-trip exactly. The incorrect
no-overlap rule fails all 1,872 multi-buffer controls; reversed sample-count
order discriminates 1,775 applicable cases. All prior component-mode outputs
remain identical. These are structural checks on reused cohorts, not blind
accuracy or semantic decoder confirmation. Frozen splits, `0DRP` framing,
PSIN/BCPack data and provisional labels remain intact. Next: establish channel
identifiers, codec selection and compressed section grammar before decoding
sample values or keyframes.

**Channel slot directories:** `--channel-layout` implies `--packed-layout` and
adds a separate `channel_layout` view to each supported packed buffer:

```bash
python3 -m gta6x --root <pkg> anim --full --channel-layout \
        --max-nodes 1000000 --out ./channel-layout
```

The observed `section_1` suffix contains eleven little-endian u16 counts,
followed by eleven groups of strictly increasing u16 slot indices. Each group
is padded to four entries using sentinel `4 * binding_count`. A unique bounded
suffix must satisfy every count, range and padding check. Exported
`binding_index = slot_index // 4` and `sub_index = slot_index % 4` are arithmetic
associations only. The same index may occur in several groups; group meanings,
channel IDs, codecs and compressed sample values remain unknown. Bytes before
the directory remain opaque. Header words at `+0x18/+0x1a/+0x1c` remain raw in this view; the optional
storage and bit-row views below test their bounded relationships.

The profile was frozen before validation. All **879 discovery / 908 validation**
distinct buffers resolve, with zero content-hash overlap; aliased output counts
are **4,956 / 5,617** buffer views. All malformed-count and bad-padding controls
refuse. These are previously exposed structural cohorts, not blind semantic
validation. Existing packed output is unchanged without this option. Search is
capped at 65,536 bytes per buffer; emitted groups and slots consume the shared
node budget. Unsupported directories retain their own reason and empty groups
while preserving parent packed metadata. The CLI exits nonzero for unresolved
requested directories.

**Opaque animation storage:** `--storage-layout` implies `--channel-layout`
and adds a separate `storage_layout` per packed buffer:

```bash
python3 -m gta6x --root <pkg> anim --full --storage-layout \
        --max-nodes 1000000 --out ./storage-layout
```

The inferred directory-start relationship is
`32 + raw_u32_0c + row_count * row_stride`, using header u16 words at `+0x16`
and `+0x18` for count and byte stride. The new view treats `+0x0c` as relative
to the end of the 32-byte header and partitions the whole buffer into header,
body prefix, fixed-stride rows, slot directory and auxiliary tail. This refines
the earlier raw-offset partition; existing `--packed-layout` output is retained
for compatibility. It does not establish the prefix's sample or codec meaning.

When raw `u16_1a == 0`, stride must equal `4 * ceil(raw_u16_1c / 32)` and every
high padding bit above that candidate bit width must be zero. Other `u16_1a`
values retain a separate unresolved bit-grammar reason in this compatibility
view; the opt-in bit-table view below refines them. Independently
bounded byte rows remain available. No numeric samples, quantization, channel
semantics, codec or time units are decoded.

Frozen discovery/validation: all **879/908 distinct buffers** resolve exact
partitions (4,956/5,617 aliased views). The conditional bit-row profile resolves
**496/497 distinct buffers**; the remaining **383/411** retain unknown bit
grammars. All wrong-origin and applicable high-padding controls refuse; prior
packed/channel outputs remain unchanged. These are reused structural cohorts,
with no validation-driven rule changes. Unsupported base layouts return empty
regions and a reason, preserve parent views and produce a nonzero CLI exit.

**Counted animation bit tables:** `--bit-layout` implies `--storage-layout`
and adds `bitrow_layout` without changing earlier modes. Directory counts locate
a fixed table of 12-byte records and a variable table of counted opaque words.
Fixed widths must sum to the stored `u16_1c`; variable records must exactly
exhaust the independent `4 * u16_1a` extent. Each stored width is 1..32 bits.
Their combined width must reproduce the four-byte-rounded row stride, with
all remaining high bits zero.

```bash
python3 -m gta6x --root <pkg> anim --bit-layout --limit 8 \
        --max-nodes 1000000 --out ./bit-layout
```

JSON retains raw table parameters, opaque payload hashes and complete source-order
row bits/spans. It does **not** assign per-channel bit offsets, scalar types,
quantizers, transforms, codecs or timing. Slot/table ordering remains unconfirmed;
row reordering intentionally passes these structural checks. Empty-stride
buffers retain their header row count and emit no invented rows. Tables and
rows share the existing node budget; malformed/unsupported views retain
reasons and empty deeper lists, and requested failures exit nonzero.

The unchanged frozen discovery/validation split resolves **879/879 and
908/908 distinct buffers**, including **383/411 nonzero-table cases** that the
earlier bit grammar left unknown. This describes all **4,956/5,617 aliased
buffer views**; aliases are not independent trials. The view exposes
38,733/44,669 fixed records, 2,274/2,327 variable records and 241,126/253,666
nonempty raw rows. All 7,740 earlier packed/channel/storage view comparisons
agree; all **10,313 malformed controls** refuse. No rule changed after the
first validation run. These reused structural cohorts have zero cross-role
buffer-hash overlap and supply no semantic animation oracle. A native 1 MiB
discovery CLI check resolves 70 buffer views, including eight nonzero cases.

**Indexed-payload candidates:** `--lookup-candidates` implies `--bit-layout`
and adds `lookup_layout` for buffers with a variable table. Under a candidate
source-order partition after the opaque fixed-width prefix, observed indices
must densely cover zero through their maximum. A separate 1..32-bit entry
width must explain the exact packed payload word allocation, with zero high
padding. The view retains candidate bit spans, raw packed-entry bits and an
index-sequence SHA-256, without duplicating per-row code arrays.

```bash
python3 -m gta6x --root <pkg> anim --lookup-candidates --limit 8 \
        --max-nodes 1000000 --out ./lookup-candidates
```

This is **not a proven channel or sample decode**. Alternative record orders
and bit origins pass on some discovery buffers; no slot/binding assignment,
unique bit partition, scalar type, quantizer or codec is claimed. Entry counts
are observed candidate counts, not independently proven codebook cardinality.
Whole-row/table ordering remains unconfirmed. Empty variable tables are outside
this profile and retain an explicit reason; mixed requested results exit
nonzero while supported candidates and parent views remain available.

The frozen rules check **383 discovery / 411 validation distinct buffers**,
covering all nonzero-variable cases in these cohorts. The remaining 496/497
have no variable-table candidate. Results include 2,274/2,327 candidate records,
78,068/82,036 raw entry observations and 546,544/517,797 index observations.
All 7,740 prior parent-view comparisons agree. All 2,358 malformed controls
refuse; 794 row-reorder controls deliberately pass. No validation-driven rule
change occurred. A real discovery CLI check yields 15 candidate views from
five clips; aliases and reused source exposure are not independent trials.

**Mixed animation prefix storage:** `--prefix-layout` implies `--bit-layout`
and adds a separate `prefix_layout` without changing earlier views. Counts and
the independently checked width-table origin bound leading raw triplet/word
groupings. The combined group-0/group-1 triplets are not assigned individually
to either group or to slots. After the width tables, exactly the stored group-10
count of length-prefixed opaque records must exhaust the pre-row span; each
record stores its total length in words and must fit the measured minimum.
Bodies retain bounded spans and hashes. Groups 7/8 remain unassigned counts.

```bash
python3 -m gta6x --root <pkg> anim --prefix-layout --limit 8 \
        --max-nodes 1000000 --out ./prefix-layout
```

The frozen profile supports all **879 discovery / 908 validation buffers**,
inventorying **215,213 raw words / 72,751 opaque records** across distinct
buffers. All 7,740 previous full parent views compare exactly. All 5,708
malformed controls refuse; triplet reordering and opaque-body changes
intentionally pass. This is storage consistency, not scalar/slot/codec decoding
or integrity proof. Old `--payload-layout` retains its narrow group-zero-only
profile. A native 1 MiB discovery scan yields 70 prefix views without failures.

A discovery-only follow-up examined all **36,365 counted records / 8,518,656
body bytes** in the frozen discovery cohort. Candidate fixed-size subrecords
and sorted offset tables failed counterexamples; no inner-body grammar or
decoder was added. Those bodies remain opaque, and the 908 validation buffers
were not opened for this follow-up. Establishing an independent count/extent
constraint is the next step before testing a body grammar against the holdout.

A discovery-only follow-up tested stronger variable-count table/trailer and
parent-width assignments across **36,365 records** in the same 879 buffers.
Each proposed general layout has counterexamples; 634 zero-width and 22
work-limit cases were excluded explicitly. No successful subset was promoted
to a decoder, and no validation buffers were inspected for this follow-up.
Independently known entry counts/boundaries or controlled samples are still
needed before body decoding can advance.

**Narrow raw payload inventory:** `--payload-layout` implies `--storage-layout`
and adds a separate `payload_layout` per buffer. The supported shape has only
group zero active, one sub-index-zero slot per binding, no stored sample rows
or auxiliary bytes, and exactly twelve prefix bytes per slot. It exports raw
little-endian word triplets in source order and a **separate, unconfirmed** list
of same-ordinal directory-slot candidates. It decodes no numeric constants,
transforms, samples, channel identifiers or codec meanings.

Only **12/879 discovery buffers and 9/908 validation buffers** match this profile
(26/4,956 and 12/5,617 aliased views). Mixed-group and other layouts retain a
reason and empty inventory lists while parent metadata remains available;
requested unsupported layouts cause a nonzero CLI exit. Generalized group-zero
word associations disagreed across repeated observations, so they were not
implemented. Swapping raw triplets still passes the structural checks by design:
there is no semantic ordering oracle. Previous packed/channel/storage output
remains identical without the option. Use a bounded window and an explicit
node allowance when researching these partial inventories.

**Native MoVE browser:** `move` reads raw MoVE files or checked adjacent archive
pages and exports bounded envelope metadata:

```bash
python3 -m gta6x move motion.move --out ./motion-metadata.json
python3 -m gta6x --root <pkg> move --archive anim --full --out ./motions.json
```

The supported version-word-19 profile has two counted u32 tables, a counted
five-byte `(u32, u8)` table, raw control/prelude fields and an opaque payload
span/hash. Counts, the redundant total-length equation and all bounds must
agree before rows are emitted. Regions cover the complete input. Table words,
tags and payloads retain unknown names/reference, motion, pose and timing
semantics; successful reports remain `partial`. Raw files are detected by magic;
`--raw` forces raw parsing. `--start OFFSET --limit N` bounds archive scans.
Input is capped at 16 MiB and all rows/regions share `--max-nodes`.

A content-hash-grouped split was frozen before grammar inspection, excluding
all original animation validation intervals. The previously indexed archive
supplies **212 discovery / 112 validation resources** with zero cross-role
content-hash overlap. All parse unchanged after the profile freeze; one validation
resource joins two pages. All 324 raw/scan comparisons agree and 1,620 corruption
controls refuse. This supports the envelope structure, not decoded motion
semantics or independent runtime accuracy. Unsupported versions, corrupt
counts, truncation and bad inter-page padding retain explicit refusals and a
nonzero CLI exit.

**MoVE payload storage:** `move --objects` adds a separate `object_layout`
without changing the default envelope view. The supported root forms expose
immediate field-relative targets or length-prefixed descriptor storage:

```bash
python3 -m gta6x move motion.move --objects --out ./motion-storage.json
python3 -m gta6x --root <pkg> move --archive anim --full --objects --out ./motion-storage.json
```

Root kind 1 has a counted hash/offset table whose immediate target headers
repeat the stored ordinal and hash. Root kind 22 has bounded descriptors with
four counted fixed-cell groups and length-prefixed subblocks. Offsets, sizes,
source order, counts and all region bounds are checked; shared node limits
apply. Complete storage metadata retains opaque child bodies/tails and raw
numeric bits. Recursive interpretation failed on 25 discovery resources and
was not enabled. Motion, pose, numeric types and timing meanings remain unknown.

All **212 discovery / 112 validation** root views pass unchanged: **179 immediate
references, 288 descriptors, 820 raw cells and 21 subblocks**. All prior envelope
outputs compare exactly. The 1,884 malformed-structure controls refuse, while
324 opaque-tail mutations intentionally remain undetected. This is structural
metadata inspection rather than payload integrity or semantic validation.
Unsupported views retain the envelope, an explicit reason and empty deeper
lists; requested unresolved object profiles exit nonzero. Frozen source
assignments remain unchanged.

**MoVE child prefixes:** `move --children` implies `--objects` and inspects one
additional bounded prefix level. Low/high bytes at header `+18/+19` constrain
row and extension counts in supported forms. Extension-record lengths agree
with independently bounded table extents; additional reference headers retain
hash/ordinal checks. No arbitrary recursive traversal, numeric sample or motion
decoding is enabled. Child bodies, extension bodies and other tails stay opaque.

Across the unchanged 212/112 resource split, **266/440 candidate prefixes**
resolve and **174** remain explicitly unknown, including one unfitted short
held-out prefix. The view adds 138 extension records, 387 next-level references,
376 descriptors, 685 raw cells and 193 subblocks. All 324 prior parent views and
raw/archive comparisons are preserved; all 1,362 malformed controls refuse.
Opaque mutations intentionally remain undetected. Unknown siblings keep their
own reasons and empty deeper lists while supported siblings remain available;
requested partial/unresolved child inspection exits nonzero.

**Additional MoVE tail forms:** `move --tail-forms` implies children/objects
and adds `tail_form_layout` while preserving their earlier views. The kind-3
form checks an 84-byte header, counted hash/relative rows, redundant selected
and tail pointers, repeated target hashes/ordinals, and counted opaque records.
It describes 56 additional profiles, with 146 checked references and 50 records.

The kind-12 form checks a measured 52-byte header and exactly five counted
groups. Each nonempty group has at most 16 eight-byte opaque cells and a
selector word whose used two-bit fields are all two and unused bits zero.
Groups must exhaust a terminal candidate or end at the measured opaque-tail
prefix. Header variants outside discovery evidence remain refused. Cells
appear once in `groups[].cells`, with raw bits and spans; their numeric and
application meanings are unknown. Dedicated counters distinguish groups,
selector words and cells from kind-3 references/records.

Kind-12 adds **18 discovery / 6 validation forms**, with **120 groups / 18
selector words / 96 opaque cells**. One header variant in each role remains
unsupported. The kind-11 extension adds **22 discovery / 8 validation forms**:
its measured selector word constrains a 44/48/52-byte prefix, checked zero/sparse
slots and a terminal boundary or opaque remainder header. Ten raw two-bit
selector fields and all prefix bits are retained. No scalar or selector meaning
is inferred. Two unobserved held-out selector profiles remain refused.

With kind-3/kind-12/kind-11, immediate coverage is **376/440**, with **64** explicit unknowns,
including the earlier short held-out case; **260/324** resources have every
immediate candidate described. All 324 previous parent-mode and raw/archive
comparisons agree; all 80 prior kind-3/kind-12 form dictionaries are exact.
Kind-11 adds 300 raw selector fields / 1,412 header bytes. All 104 new malformed
controls refuse; 54 opaque mutations deliberately pass. Earlier kind-3/kind-12
audits retain their separately documented 644/104 refused controls.

The kind-28 extension adds **8 discovery / 3 validation forms**, using seven
complete observed selector words to choose measured 32..64-byte prefixes.
Zero/repeated-word checks and exact terminal or opaque-header boundaries apply.
Individual field widths remain ambiguous, so no general selector-width formula
or pointer interpretation is enabled. Unfitted variants stay refused.
It adds 176 raw selector fields / 468 prefix bytes, bringing coverage to
**387/440** immediate candidates, with **53 unknowns**; **271/324** resources
have all immediate storage candidates described. All 110 earlier complete
forms and 324 parent/raw-archive comparisons agree. All 26 new malformed and
11 under-budget controls refuse; 12 opaque mutations deliberately pass.

The kind-4 extension adds **6 discovery / 3 validation forms** through five
exact whole-word profiles, measured zero slots, a marker equality and a bounded
next-header ordinal witness. It retains **364 prefix bytes** with zero inferred
selector fields or pointers. Immediate coverage reached **396/440**, with **44
unknowns**; **280/324** resources have every immediate storage candidate
described. All 121 prior complete forms and 324 parent/raw-archive comparisons
agree. All 47 new malformed and nine under-budget controls refuse; 36 opaque
parameter/body mutations deliberately pass. Other kind-4 variants stay refused.

An extended kind-12 profile adds one discovery form with a **60-byte header**
and the same five counted groups, two selector words and ten opaque cells.
Its exact measured word is `0x1155`; a following opaque ordinal witness is
required. No terminal profile or generalized header-width formula is enabled.
Coverage is now **397/440**, with **43 unknowns**; **281/324** resources have
all immediate candidates described. All 130 prior complete forms and 324
parent/raw-archive comparisons agree. Frozen validation has no eligible new
profile examples; its 112 prior views remain identical, and `0x115a` stays
refused. Kind-9/15 pointer and body meanings remain unproven.

The reused 212/112 split remains unchanged. Runtime/tests were frozen before
each new validation run; these checks measure storage consistency, not motion
semantics. Referenced bodies and tails stay opaque, with no recursive graph
expansion. Remaining unsupported requested forms retain reasons and exit nonzero.

**Native RBF0 browser:** the `rbf` command reads the observed self-describing
RBF0 profile from raw files or checked adjacent archive pages:

```bash
python3 -m gta6x rbf metadata.rbf --out ./rbf.json
python3 -m gta6x --root <pkg> rbf --archive anim --full --out ./rig-metadata.json
```

Use `--start OFFSET --limit N` to bound an archive scan. Raw files are detected
by magic; `--raw` forces raw parsing. The JSON contains a flat indexed tree,
reusable name descriptors, source spans, object attributes/children, text and
opaque byte/64-bit values. Byte leaves expose a text candidate only when they
are valid NUL-terminated UTF-8. Names and raw token codes do not establish
application types, rig relationships, signedness or script opcodes.

The eligible animation discovery resource joins **21 pages / 1,348,436 bytes**
and parses exactly: **56,796 token nodes and nine name descriptors**, including
28,962 objects, 1,126 inline text values, 20,031 byte leaves and 6,677 opaque
64-bit values. Its observed rig-set manager hierarchy contains 1,126 top-level
items and 6,677 nested entry items. Only one eligible container exists, so
these are discovery/structural regression results with no independent-container
holdout or semantic accuracy claim. Existing validation windows remain frozen.

Unsupported token kinds, malformed names, descriptor mismatches, nonzero
reserved object words, unbalanced trees, truncation and extra bytes refuse the
whole candidate. Input is capped at 16 MiB; node, text and nesting budgets apply
(default nesting 32, maximum 128). JSON uses indices to avoid nested serialization.
Archive framing requires checked zero alignment padding and a short terminal
page. Refused candidates keep reasons and produce a nonzero CLI exit.

**Searchable rig-set entries:** `rbf --rig-sets` adds a separate `rig_set_view`
with literal key/entry fields and an exact Rig-string reverse index:

```bash
python3 -m gta6x rbf metadata.rbf --rig-sets --out ./rig-sets.json
python3 -m gta6x rbf metadata.rbf --name 'key-fragment' --out ./selected.json
python3 -m gta6x rbf metadata.rbf --rig 'literal-rig-string' --out ./rig-uses.json
```

`--name` is a case-sensitive literal key substring; `--rig` is an exact literal
Rig value. Either implies `--rig-sets`. The entire source profile is validated
before filtering, including graph ownership, spans, descriptors, exact required
field order and byte/text correspondence. Unsupported or ambiguous profiles
retain the generic tree and an unresolved reason with no normalized prefix.
Source node indices preserve duplicates and repeated occurrences. `Dictionary`,
`Rig` and `Group` are literal tree labels, and `Priority_bits` retains all eight
bytes without signedness, ordering or runtime interpretation.

The discovery inventory contains **1,126 sets / 6,677 entries / 3,669 distinct
Rig strings**. The extra view uses 18,150 budget nodes alongside the generic
tree; `--max-nodes` covers both. There is still one reused discovery container
and no independent held-out rig-schema confirmation. Generic output is unchanged
without the option. Profile/budget failures are explicit and exit nonzero.

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
| `textures` metadata | **357,115** descriptors and supported layouts; **305,959** with complete stored/zlib coverage; **47,695** BC1-only BCPack candidates; **3,461** other BCPack candidates |
| Texture shapes | Supported layouts for **567/567** cubemaps, **127/127** arrays and **3/3** single-mip volumes; complete stored/zlib coverage for 567 cubemaps, 120 arrays and 3 volumes |
| Native BCPack checks | BC3/BC4/BC5 DDS/PNG samples export; 16 retained BC3/BC5 chunks agree with the legacy provisional adapter; 75 BC4 UI chunks still refuse; six BC3/BC5 histories remain provisional |
| `textures` sample | 200 vehicle descriptors → 183 DDS exported; the rest BCPack-only or unmapped |
| `movies` | full `movies.rpf`: 515 Bink2 titles, 8.83 GB, 3.94 h total; 65 s scan |
| `awc` | 238 containers in the first 48 MiB of `audio.rpf`; a 100 MiB scan found 559 containers / 8,683 streams / 53 music-channel Ogg files; music descriptor block/channel parsing and `--music-out` verified with `ffprobe` (Opus 48 kHz mono, 42.03 s) |
| `psin` | Original 8 MiB `data.rpf` cohort: 788 stream-local containers + 10 fragments, 821 joined bodies / 15,217 verified blocks; stored-tail recovery adds four discovery containers outside the frozen membership |
| `models` | `packs.rpf` index: 80,424 entries, 75,135 model resources, 27,288 recovered names, ~40–60 s; sample GLBs 480 / 972 / 96 triangles |
| `shaders` | 9,089 validated DXBC shaders in the first 64 MiB of `shaders.rpf`; 2,174 in the first 16 MiB |
| `structured` | With `--limit 16`: `common.rpf` has 259 complete XML (79 joined); `data.rpf` has 1,049 complete PSIN (32 joined), including four stored tails |
| `textures --embedded` | native: 1,347 txd dictionaries / 3,167 descriptors in `textures.rpf`; 3,020 2D descriptors plus 34 BCn arrays supported; arrays retain 155 layers / 169 subresources; all 113 single-mip volumes supported; all 31 mipmapped 2D textures export 253 declared mips, including 144 tail levels |
| Native LSCH/LENM schemas | 821 discovery containers / 433 schema pairs; separate-range validation 223/223 containers, 34 additional pairs; 11,794/1,748 enum headers and 118,111/26,632 members respectively; inferred types and JSON v2 export |
| Native PSIN instances | 821 / 223 data containers and 1,012 script metadata containers; 734,696 / 104,199 / 230,622 scalar/pool/array observations round-trip exactly; 2,044 partial and 12 with all listed fields handled after map-entry support |
| Low-ID PSIN pools | 9,984 added hash/ASCII values; 55,898 candidate reference words and 13,465 opaque groups retain bits with unknown meanings; no pointer following |
| Bounded PSIN hash32 arrays | 3,188 resolved fields, including 2,293 empty arrays; 2,008 hash observations attached to owning fields, often also visible in pools; frozen source split, unsupported profiles remain explicit |
| PSIN structure-array links | 25,656 resolved fields / 15,685 links to existing local typed records; targets may remain partial; no recursive expansion or duplicate value observations |
| Cross-file PSIN registry | 697 provider schema pairs; 2,462 missing embedded-field annotations resolved across the data samples; conflicts retained, no additional instance values in these samples |
| PSIN reference-array links | 34,185 resolved fields / 55,819 local record links / 14 explicit null slots; both pointer levels bounded; invalid members yield no prefix |
| PSIN standalone reference fields | 113,913 resolved field observations: 33,821 bounded local record links / 80,092 explicit nulls; original schema type remains unknown outside the contextual profile |
| PSIN map-entry links | 15,274 discovery / 3,782 supplementary-validation fields resolved; 29,366 / 22,469 entry links; unsupported profiles explicit, reused-source consistency evidence |
| Animation resource metadata | 618 discovery / 377 validation `0DRP` candidates parsed; 446 joined resources; all local schema/member/block spans bounded; no clip/curve semantics claimed |
| Named animation clip records | 191 discovery / 170 validation dictionaries; 1,277 / 1,432 bounded name/record-prefix links; duration meanings and packed curves remain unconfirmed |
| Animation component/buffer links | 1,277/1,432 discovery/validation clip views; 3,794/3,946 animation links; 4,956/5,617 opaque buffer references; packed contents undecoded |
| Packed animation metadata | 3,794/3,946 discovery/validation animation layouts; 223,879/236,886 raw binding rows and 11,030/16,423 auxiliary rows; one-sample chunk overlap checked; values/codec meanings unknown |
| Animation storage rows | All 879/908 discovery/validation distinct buffers partition exactly; 496/497 conditional bit-row profiles, other bit grammars unknown; no decoded samples |
| RBF rig-set inventory | One discovery resource: 1,126 sets, 6,677 entries, 3,669 exact Rig strings; literal source associations, no independent holdout |
| Enum-key PSIN maps | 61 additional maps/182 bounded entry links; local LENM key membership required, earlier values/bindings unchanged |
| MoVE envelopes | 212 discovery/112 validation resources; all envelopes parse, 1,620 malformed controls refuse; motion payloads remain opaque |
| Raw animation payload words | Narrow profile in 12/879 discovery and 9/908 validation buffers; raw bits only, ordinal slot associations unconfirmed |
| Enum-record PSIN arrays | 41 additional arrays/260 local record links; no new scalar values; prior bindings unchanged |
| MoVE root storage | All 212/112 discovery/validation views pass; 179 references, 288 descriptors, opaque child bodies |
| Opus WAV | 3,349/1,310 mono streams pass strict framing; 16 selected real decodes have exact requested lengths under explicit assumed trim |
| Opus packet-sequence WAV | Opt-in mono/stereo output; nine stereo sequences from one previously exposed validation bank; no recovered game timing claim |
| Declared-duration Ogg | All 4,659 supported mono streams; retained packets unchanged, 7,570 unused tail packets omitted; original alignment unconfirmed |
| Music WAV | Existing mono profiles retained; stereo zero-skip discovery export validates per-channel frames; nonzero stereo skips refused |
| AWC radio metadata | 3,008 supplied locations / 13,035 raw table entries / 1,042 TRACKID intervals; Worldwide 41 chapters and Vault 25; native song/station links unresolved |
| MoVE child prefixes | 266/440 candidates supported; 174 unknowns retained; all 324 parent views unchanged |
| PSIN contextual text links | 53 discovery / 240 supplementary links to existing pool entries; 10,920 supplementary attempts unresolved; no extra scalar observations |
| MoVE tail forms | Kind-3/12/11/28/4 add 131 profiles; immediate coverage 397/440, with 43 unknowns; motion meanings unknown |
| PSIN nested maps | 13 maps / 60 existing-row links from one discovery source; zero supported held-out examples; opaque keys remain unknown |
| PSIN opaque-key maps | Four maps / 18 existing-row links from one discovery source; zero eligible validation examples; keys and lookup meanings unknown |
| PSIN null-empty arrays | 19,357 all-zero headers recognized despite missing unused element definitions; no guessed stride, scalar value or record edge |
| Animation bit tables | 879/908 distinct buffers resolve, including 383/411 nonzero profiles; raw tables/rows only, no numeric samples or channel partition |
| PSIN LRSC headers | 821 discovery / 2,390 validation observations match counts and one bounded local-record candidate; root/fixup semantics unknown |
| Animation lookup candidates | 383/411 distinct nonzero-variable buffers pass candidate bounds; 160,104 raw entry observations; channel/order/numeric meanings unconfirmed |
| Mixed animation prefixes | 879/908 distinct buffers; 215,213 raw words / 72,751 opaque records; numeric and slot meanings unconfirmed |
| PSIN record associations | 3,208 graph views / 264,745 checked edges; bounded LRSC-candidate reachability, unknowns explicit; three existing instance-budget refusals |
| `selftest` | 265 checks, all passing (AWC, Ogg, strict packet/WAV/music framing, verified overlaps and declared Ogg timing, RDS5, PSIN/LSCH/LENM/instances/registry/pools/hash32 arrays/structure/reference links/fields/map entries/text links/record associations, XML, Gfx10, DDS, PNG, shaders, txd full mip chains/arrays/volumes/tail addresses/bounds, name hashes, animation/0DRP metadata, named clip/component/buffer links, packed header/channel candidates, slot directories/storage rows/raw payload inventories/counted width tables/indexed-payload candidates/mixed prefixes, MoVE envelopes/root/child/tail storage, RBF0 trees/rig-set inventories and bounds, music, BCPack, BC2 layout, signed BC4/BC5/8-bit previews and BC6H/BC7); backend features are not self-tested |

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
  (SW_4KB_S and SW_64KB_D); all 357,115 measured descriptor layouts are supported.
  All 567 measured cubemap layouts are supported. Streamed 3D volumes require
  one uncompressed mip; DDS retains every plane and PNG can select one plane.
* **PNG previews**: signed 8-bit/SNORM values use the documented display mapping;
  BC6H uses tone mapping. Selected raw 16/32-bit/packed formats have numeric
  previews; other formats remain unsupported, and raw floats are clipped.
  Previews default to mip/slice/face/Z 0; explicit selectors choose another
  validated subresource in streamed or embedded textures.
* **Embedded textures**: full BCn 2D/array mip chains require validated S4K allocations.
  Single-mip uncompressed volumes use exact 3D S4K allocations. Cubemaps,
  BC/multi-mip volumes, unknown shape tags, other swizzles and non-BC chains are refused;
  single-level non-BC 2D textures retain their existing export path.
* **Audio**: optional libopus WAV export covers mono declared-duration or opt-in
  mono/stereo packet sequences at 48 kHz. Music supports zero skips and the
  separately verified whole-packet overlap subset; other skips and XMA2 remain
  unsupported. Original sample alignment is unconfirmed. Legacy Ogg remains
  the default; declared mode corrects granules for the selected interval.
* **Models** depend on the external SixNG backend; no native model decoder is
  included. A discovery-only native investigation examined 445 compressed
  streams / 350 unique payloads without establishing model identity or vertex/
  index declarations. No speculative decoder was added; its validation window
  remains untouched.
* **Bink1** validation is experimental.
* **Scanning is capped** by `--limit` (defaults: 256 MiB for media, 64 MiB for
  zlib/catalog) for predictable runtime; `--full` reads whole archives. A
  209 GiB package takes roughly 80 minutes at ~43 MB/s.
* **Hashing is opt-in** (`report --hash`) because it reads whole payloads.
* **RBF0**: the native browser covers the observed token profile, with exact
  structural checks. Application/rig meanings, other kinds and script bytecode
  remain unresolved; there is no independent-container holdout.
* **PSIN checksums**: complete supported containers are verified with JOOAT;
  incomplete stream-split fragments require reassembly before verification.
* **PSIN schemas**: native LSCH/LENM browsing preserves unknowns and marks
  supported type meanings as inferred. An optional private cross-file registry
  resolves unambiguous missing definitions; conflicting versions remain unknown.
  Instance reading covers scalars/enums/embedded structures and one bounded
  local hash32-array profile plus local reference-field, structure/reference-array
  and hash32/enum-key map-entry links to existing typed rows.
  Other pointers, fixups, unsupported bitset profiles and remaining types
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
  audio_pcm.py  strict AWC packet framing and optional libopus PCM16/WAV export
  audio_ogg.py  explicit declared-duration Opus Ogg granules and tail trimming
  audio_music_pcm.py strict zero-skip channel framing and optional music WAV
  audio_music_skips.py opt-in exact compressed-packet overlap reconstruction
  awc_radio.py  bounded markers, TRACKID intervals and raw per-block tables
  awc_names.py  optional external exact-source naming map
  music.py      audio-config music record metadata
  audio_config.py bounded config index, offset/hash name tables and wave-slot lists
  audio_config_sections.py opt-in counted raw index groups; radio meaning unknown
  music_catalog.py supplied external credit hypotheses with full-hash matching
  radio_trackids.py bounded native-marker/record candidates; explicit ID conflicts
  bc/           BC1-BC7 previews, BCPack reconstruction and runtime tables
  png.py        minimal PNG writer
  psin.py       PSIN containers, section bodies, stream-split fragments
  psin_bucket_maps.py local schema-framed bucket/reference owner associations
  psin_schema.py native LSCH/LENM browser, inferred types and JSON records
  psin_instances.py bounded instance blocks and inferred member values
  psin_pools.py  low-ID hash/text pools, reference candidates and opaque views
  psin_arrays.py bounded hash32 spans and local structure/reference-array record links
  psin_references.py bounded local record bindings for fields/reference arrays
  psin_maps.py   bounded local map-entry record links, preserving duplicates
  psin_nested_maps.py measured nested descriptor trees and bounded entry links
  psin_opaque_maps.py measured local entry-row links with uninterpreted keys
  psin_enum_arrays.py bounded local enum-array links to existing typed rows
  psin_text_references.py contextual links to existing local ASCII pool entries
  psin_resource_header.py checked LRSC counts and a bounded local-record candidate
  psin_record_graph.py finite checked record associations and candidate reachability
  psin_registry.py signature-aware private cross-file definitions/conflicts
  models.py     optional SixNG backend: index, list, glTF/GLB export
  world.py      optional SixNG world/map resource commands
  anim.py       animation stream classification and name recovery
  anim_resources.py bounded resource framing and raw 0DRP schema/block metadata
  anim_clips.py supported named clip-record prefixes, raw tags and duration candidates
  anim_components.py bounded group/segment/animation and opaque buffer associations
  anim_packed.py packed header partitions, raw channel/auxiliary rows and sample-index candidates
  anim_channels.py bounded optional slot-directory associations; group meanings unknown
  anim_storage.py body-relative opaque row spans and conditional bit-padding checks
  anim_payloads.py narrow source-word inventories; slot associations unconfirmed
  anim_bitrows.py counted width tables and complete opaque bit-row spans
  anim_lookups.py checked source-order indexed-payload candidates; assignments unknown
  anim_prefix.py mixed raw prefix groupings and counted opaque record storage
  move.py       bounded MoVE envelope tables, raw controls and opaque payload spans
  move_cli.py   raw-file/archive MoVE metadata browser command
  move_objects.py nonrecursive relative targets and descriptor-prefix storage
  move_children.py one additional bounded child-prefix/extension layer
  move_tail_forms.py optional kind-3 tables and additional bounded tail forms
  move_more_forms.py kind-12 counted groups, selector bits and opaque cells
  move_extra_forms.py measured kind-11 selector-header storage
  move_selector_forms.py measured whole-word kind-28 selector-header profiles
  move_kind4_forms.py measured kind-4 header prefixes and opaque boundary witnesses
  rbf.py        bounded native RBF0 token trees and checked archive framing
  rbf_cli.py    RBF0 JSON browser command
  rbf_rigs.py   literal rig-set/entry inventories and exact Rig-string reverse index
  names.py      joaat/Murmur3 name dictionaries and lookup
  shaders.py    DXBC shader wrapper scanner and validator
  shader_metadata.py public program headers and bounded SG1 signatures
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

`python3 -m gta6x selftest` runs 265 synthetic checks covering the AWC header and
tag table, Opus packet records and Ogg pages, RDS5/TTPF validation, PSIN
containers/fragments, LSCH/LENM schemas, bounded instance values and cross-file
registry resolution/conflicts, low-ID pools, bounded hash32 arrays, structure/reference-array links, local reference fields and explicit
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
  bcn.py            BC1-BC5, byte/precision component previews and BC6H/BC7 dispatch
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
accepts ordinary row-major BCn blocks or supported raw component pixels and
returns RGBA8 preview pixels; unsupported formats or short spans return `None`.
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

Released under the [MIT License](LICENSE). Copyright (c) 2026 HolyRoses.
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the
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
