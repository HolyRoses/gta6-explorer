# Findings — GTA VI (Xbox 1.0.2.1)

Read-only analysis of a local `GTA6.Xbox.v1.0.2.1` package with `gta6x`.
Nothing here required a key: the table of contents is encrypted, but resource
payloads are zlib streams, media carriers are stored in the clear, and texture
pools carry their own indexes.

All numbers below were measured on this package with the parsers in `gta6x/`.
They are observations, not format guarantees; the tool's `selftest` (59 checks)
covers the structural rules without game data.

## Package profile

| Metric | Value |
|---|---|
| Files | 108 |
| Size | 223,880,932,870 bytes (208.51 GiB) |
| RPF9 archives | 22 |
| RDS5/TTPF pools | 57 |
| Identity | `RockstarGamesInc.28872443D20A7`, v1.0.2.1 |
| Composition | 150.23 GiB RPF9 (72.1%), 57.94 GiB RDS5 (27.8%), remainder DLLs/art/manifests |

## What the tooling recovers

| Area | Result | Command |
|---|---|---|
| Zlib payloads | 176,971 checksum-verified assets in one catalogue sweep; 4.12 GB packed → 26.34 GB inflated | `catalog --db`, `get` |
| Complete XML | `common.rpf`: 259 documents, **79 joined** from split pages | `structured` |
| Complete PSIN | 16 MiB of `data.rpf`: 1,048 containers, **28 joined** | `structured` |
| Streamed textures | 357,115 descriptors: **305,954 zlib/raw complete** (+47,695 BC1 BCPack); 127 arrays, 567 cubemaps, 3 volumes; native PNG covers BC1-BC7 (BC6H tone-mapped); backend only for models/world | `textures --png`, `--via sixng` |
| Embedded txd textures | **1,345 dictionaries / 3,155 textures** native; leading mip chains native (512² BC3 → 3 mips, 1024² BC3 → 4) | `textures --embedded` |
| Movies | 515 Bink2 titles in `movies.rpf`: 8.83 GB, 3.94 h total | `movies` |
| AWC audio | 238 containers in the first 48 MiB; per-stream Opus metadata, native payloads and Ogg remux | `awc`, `scan` |
| DXBC shaders | **9,089** validated in the first 64 MiB of `shaders.rpf` | `shaders` |
| Models | `packs.rpf`: 80,424 entries, **75,135 model resources**, 27,288 named → glTF/GLB | `models` (SixNG backend) |
| Animation | 130,771 streams / 2,327 names; `0DRP`, `MoVE`, 1,788 packed clips, `RBF0`; clips not decoded | `anim` |
| World data | placements, collision, navmesh, paths, lights, interiors, vehicles, meta/PSO, shader census | `world` (SixNG backend) |
| Name hashes | 50,864 joaat hashes / 36,943 case-sensitive / 87,807 Murmur3-64 hashes | `names` |

The catalogue sweep is not exhaustive: per-archive limits vary, and only
`common.rpf`, `script.rpf`, `textures.rpf`, `shaders.rpf` and the smaller archives
were swept in full. `--full` re-reads whole archives.

### Catalogue coverage by archive

From the local SQLite catalogue (20 archives; packed/inflated bytes):

| Archive | Assets | Packed | Inflated |
|---|---:|---:|---:|
| `core_bvh4.rpf` | 22,741 | 485,363,388 | 8,379,424,256 |
| `anim.rpf` | 44,389 | 484,684,926 | 4,670,238,256 |
| `story000.rpf` | 45,266 | 480,400,524 | 3,221,001,104 |
| `levels.rpf` | 657 | 503,619,619 | 3,016,851,744 |
| `navmeshes.rpf` | 8,333 | 520,485,932 | 1,923,343,328 |
| `data.rpf` | 28,473 | 401,259,881 | 1,338,350,417 |
| `shared_minigame000_bvh4.rpf` | 1,251 | 58,893,643 | 967,344,892 |
| `packs.rpf` | 7,032 | 407,502,009 | 964,808,164 |
| `shared_minigame000.rpf` | 4,884 | 413,562,064 | 869,368,023 |
| `textures.rpf` | 1,411 | 61,650,040 | 289,467,168 |
| `shaders.rpf` | 4,209 | 137,635,025 | 275,802,924 |
| `story000_restofworld.rpf` | 618 | 62,805,471 | 126,307,723 |
| `core_restofworld.rpf` | 2,203 | 51,394,954 | 113,959,769 |
| `story000_script.rpf` | 2,634 | 20,458,722 | 74,890,824 |
| `audio.rpf` | 836 | 19,250,467 | 54,208,887 |
| `common.rpf` | 938 | 5,644,694 | 50,227,019 |
| `script.rpf` | 1,057 | 2,581,192 | 6,180,256 |
| `core_restofworld001.rpf` | 33 | 734,650 | 1,575,059 |
| `story000_bvh4.rpf` | 4 | 1,795 | 16,677 |
| `core_licenses_data.rpf` | 2 | 811 | 1,549 |

Kind mix: binary 86,161 · sparse/binary 83,745 · PSIN page 6,061 · text 565 ·
XML 439. All assets were re-inflated with `zlib.decompress` (Adler-32 checked)
before being recorded, so `verified` means a byte-exact round trip.

## Recovered content

### File tree

`recovered/paths.txt` holds **3,301 unique paths** reconstructed from XML mount
manifests: `platform:` 2,667 · `$(common)` 585 · `common:` 28 · `$(target)` 19.

Extensions: `.rpf` 2,261 · `.bk2` 535 · `.ityp` 248 · `.xml` 56 · `.meta` 22 ·
`.dat` 2 · extensionless 177.

Top directories cluster under `platform:/levels/americas/...` (interiors,
props, vegetation) and `$(common)/movies/...`. `americas` is the internal region
codename; `platform:/levels/...` is the world-content tree.

### XML definitions

Most common roots in the catalogue:
`CDataFileMgr__ContentChangeSetDef` 61 · `timecycle_modifier_data` 48 ·
`CVehiclePoints` 31 · `timecycle_keyframe_data` 27 ·
`CDataFileMgr__ContentDef` 8 · `SSetupData` 7 · `CTuningFile` 7 ·
`CDamageDataManager` 5 · `GridAtlasInfo` 4 · `CCoverProcessorTuning` 3.

### Localisation

`data.rpf` payloads inflate to readable game text in several languages
(English and French samples included item descriptions, social-media posts and
place lore).

### Model names recovered from the package

Names in the catalogue and backend index include vehicle variants such as
`caracara4x4_cmp_industrial_weedgrow_preset6`,
`infernus2_streetracers_filler_preset1`, `thrax_used`, and train family names
(`FREIGHTCAR`, `freightgrain`, `metromule`, `metrotrain2`, `ARMYFLATBED`,
`tankercar`).

## Verified format semantics

### RPF9 header (22/22 archives)

| Offset | Field | Result |
|---|---|---|
| 0x00 | magic | `0x52504639`; on disk the bytes read `9FPR` |
| 0x04 | `f1` | **index size**; the payload area starts at this byte (15 archives pad with zeroes, 7 continue with resource bytes) |
| 0x08 | `f2` | unidentified 16-byte multiple; candidate table size |
| 0x0c | `f3` | unidentified 16-byte multiple; `f3 / 16` gives plausible entry counts |
| 0x10/0x14 | `h1`/`h2` | per-archive 64-bit value, most likely an index hash |
| 0x18 | stamp | `0x00047A00`, invariant |
| 0x1c | `f4` | `336`, invariant |
| 0x40..0x60 | — | **32 invariant bytes**, shared by every archive and nested archive |

`9FPR` headers inside payload areas (`anim.rpf` 0x5000, 0x7000) are nested RPF9
archives.

### RDS5 / TTPF pools (57/57 validate)

Header: entry count, u64 size word (bits 0–55 virtual size, top byte 22), bitmap
word count, alignment word (high nibble × 256 = source padding), then 8-byte
chunk entries and an `ETPF` 634 texture dictionary. Chunk entries pack source
offset/256, codec, virtual offset/4096 and padding. Codecs seen: 0 stored,
8 zlib, 1/5/7 BCPack. The sentinel repeats file and virtual sizes. A zlib chunk
inflates exactly to its virtual size.

### AWC audio (238 containers in the first 48 MiB of `audio.rpf`)

`ADAT`, u32 flag word (low 16 = version 1, high 16 = feature flags `0xFF21`,
`0xFF02`, `0xFF25`), u32 stream count, u32 header size, optional index/extra
tables, a per-stream u32 table and 64-bit tags `{type:8, size:28, rel:28}`.
Tag types `0x76`/`0x55`/`0x48` are format/data/music and give the exact
container length. The first four containers carry 58 Opus 48 kHz streams. Opus packets are `[u16 length][packet]` records inside 2 KiB blocks; `awc --ogg-out` remuxes them losslessly into Ogg Opus, which `ffprobe` reads as Opus 48 kHz with the expected duration. Music banks use a `0x48` descriptor (block count, chunk size, 16-byte channel records); `awc --music-out` walks per-block 24-byte channel tables and writes one Ogg per Opus channel. A 100 MiB scan found 559 containers / 8,683 streams / 53 music channels.

### PSIN

Seven tagged sections (`PSIN`, `LSCH`, `LENM`, `LSNS`, `LGID`, `LRSC`, `CHKS`)
tile the blob exactly; `CHKS` is 20 bytes and repeats the total length, a stored
checksum and a platform tag. Section 1 is the instance-table body
(`PSIN | size | fieldA | fieldB | AA-fill entries | pppp | payload`). Pages that
declare a section longer than the available stream are stream-split fragments,
not a second format.

Section roles from the observed layouts: `LSCH` schema headers/fields, `LENM`
enum name/value records, `LSNS` 128-bit name records, `LGID` global 128-bit id
records, `LRSC` resource-reference/fixup records. These roles are structural
inferences; only `CHKS` is cryptographically verified below.

The `CHKS` checksum is RAGE JOOAT (signed bytes, seed `0x3FAC7125`) over the
whole container with the `CHKS` length and checksum fields zeroed, big-endian.
It verifies on **821/821** complete containers in the 8 MiB `data.rpf` sample (788/788 for the stream-local `psin` sample).

### DXBC shader wrappers

`shaders.rpf` stores shaders as
`[u8 name_len+1][name][0x00][u8 name_len][u32 stored][magic 0x000DDCE7][u32 stored][u32 decoded][raw deflate]`.
The payload is a DXBC container with printable chunk tags (`SFI0`, `ISG1`,
`OSG1`, `PSV0`, `HASH`, `DXIL`, `PRIV` in sampled shaders). 9,089 wrappers pass
both the length and DXBC structure checks in the first 64 MiB.

### Embedded txd descriptors

A system page contains 0x70-byte texture structs: `u16 8` at +0x0E, a graphics
pointer `0x6xxxxxxx` at +0x18, width/height/depth at +0x38/+0x3A/+0x3C, DXGI
format at +0x3F, mip count at +0x42, and a name pointer `0x5xxxxxxx` at +0x30.
Graphics pages follow the system stream at 16-byte boundaries with zero padding.
Mips are stored smallest-first; mip 0 starts at the 4 KiB-aligned sum of the
smaller mips and is tiled in 16×16-element blocks.

## Open questions

* **RPF9 index key.** Deferred per project direction; archive members are
  obtained by carving, not through the TOC.
* **BCPack.** Native `--bcpack` supports BC1 plus independently fitted BC3/BC4/BC5
  reconstruction. BC3 stores alpha first; its colour block always uses four
  colours. BC3/BC5 reference nibbles interleave even/odd bits. All three codecs
  have distinct 64-entry index-pair tables. Fitted history coverage is
  35/256 BC3, 55/256 BC4, 214/256 BC5; unknown slots are refused. BC3 slots
  29/37/71/166 and BC5 16/112 are provisional and native use warns. Two source
  pools were explicitly promoted, consuming the prior holdout. The replacement
  retains three BC3 and 13 BC5 adapter agreements plus 75 BC4 oracle refusals.
  These are agreements with the legacy provisional adapter, not confirmed
  ground truth; it implements no strict/report interface. Eight plain-lower-mip
  wrong-order controls pass, with only one directly exercising two of the six
  provisional slots. Historical scores are archived. Black-box BC4 controls
  isolate the refusal to history references: 75/75 altered UI controls match,
  while all original UI inputs remain refused. No missing values were inferred
  from those controls and no natural held-out BC4 accuracy is claimed. The optional helper can follow a
  native refusal. BC6H/BC7 BCPack rebuilders remain unavailable. See the
  clean-room provenance record for sources, counts and limitations.
  The five promoted BC3/BC5 chunks now agree with their provisional fitting
  outputs, and are no longer validation cases. The fit has 293 distinct chunks;
  all prior constants/codebooks are unchanged apart from the six new entries.
  Replacement held-out outputs remain excluded from fitting. BC4 UI uses
  117 currently missing tuples; the smallest pilot
  needs six. Exact original-output and independent-pair requests are in
  `docs/bcpack_data_requests.md`. Sparse endpoint sidecars can now be
  ingested under the replacement lock. Provisional evidence currently requires
  explicitly labelled full pairs; independent confirmation remains outstanding.
  A further BC4 dependency audit checked all 77 original inputs: two training
  decodes and 75 UI history refusals. Unknown histories affect 123,605 of 193,536
  UI blocks and every compressed UI mip. Index-only searches of 7,543 plain BC4
  mips and compatible embedded channels found no counterpart. No new history
  value, provisional status or held-out score was added; see
  `docs/bcpack_bc4_investigation.md`.
* **Animation.** The archive/containers are indexed and named; `anim-clips.txt`
  lists `.clip` paths. Upstream followed two clips to page-0 records (duration
  and 0x48-byte track arrays), but the page→packed-stream join and keyframes
  are not decoded.
* **Native model decoding.** Geometry is exported through the optional SixNG
  backend; no native mesh/meshlet decoder is included.
* **Embedded mip tail.** The native txd path exports the leading mip chain; small mips in
  the packed tail are not untiled. The backend remains optional for comparison.
* **Texture layouts.** Cubemaps use six slice-major S4K faces: **567/567**
  export as six-face DDS; 127/127 2D arrays and 3/3 3D volumes are laid out
  natively. Gfx10 equations cover 1/2/4/8/16-byte elements; 5 descriptors use
  unsupported DXGI formats. Native PNG previews cover
  BC1-BC7 and RGBA8; BC6H previews are tone-mapped (DDS keeps exact half-float).
* **64-bit texture hashes.** Solved: low 64 bits of MurmurHash3 x64 128 (seed
  0) over the exact UTF-8 name. The dictionary resolves 19 real texture names
  (13 recovered + 6 embedded txd). Remaining hash gaps are 128-bit `LSNS`/
  `LGID`, 29-bit audio ids and 15-bit surface ids.
* **Music record table.** The audio config holds **1,589** 46-byte music
  records, **1,589** distinct config ids and **272,442.8 s** total; `music`
  extracts duration/hash A/hash B/stream id. Names and play order are absent.
* **Audio decode.** Streams and music channels are catalogued; native
  payloads are written and Opus (including per-channel music) is remuxed
  losslessly to Ogg. PCM/WAV decoding and XMA2 transcoding are not implemented
  in `gta6x`.
* **Shader semantics.** Extraction stops at valid DXBC containers; there is no
  disassembly or translation.
* **World data.** Placements, collision, navmesh, paths, lights, interiors,
  meta/PSO and vehicles are decoded by the SixNG backend and exposed through
  `gta6x world`; no native decoder for these formats is included.

## Reproduce

```bash
python3 -m gta6x --root <pkg> info
python3 -m gta6x --root <pkg> headers
python3 -m gta6x --root <pkg> resources
python3 -m gta6x --root <pkg> structured --archive common --out ./structured
python3 -m gta6x --root <pkg> shaders --archive shaders --limit 64 --out ./shaders
python3 -m gta6x --root <pkg> textures --archive textures --embedded --out ./embedded
python3 -m gta6x --root <pkg> textures --pool vehicles --out ./textures --png --all
python3 -m gta6x --root <pkg> textures --hash-prefix 19c12e6a --out ./cube
python3 -m gta6x --root <pkg> textures --via sixng --pool vehicles --max 20 --out ./textures-backend
python3 -m gta6x --root <pkg> movies --full --max 20
python3 -m gta6x --root <pkg> awc --archive audio --limit 64 --raw-out ./audio
python3 -m gta6x --root <pkg> awc --archive audio --limit 64 --ogg-out ./audio
python3 -m gta6x --root <pkg> catalog --db gta6.db --limit 64
python3 -m gta6x --root <pkg> models index --archive packs
python3 -m gta6x --root <pkg> models extract --archive packs --name '^ankle' --max 1 --out ./models
python3 -m gta6x --root <pkg> world --kind vehicles --archive packs --out ./world
python3 -m gta6x --root <pkg> world --kind placements --limit 2000 --out ./world
python3 -m gta6x --root <pkg> names build --out names.json
python3 -m gta6x names lookup bcf03fc1 --index names.json
```

## Provenance

This directory contains findings and a path list only: no game data, keys or
executables. `recovered/defs/` and `recovered/xml/` are bulk dumps and are
gitignored; `paths.txt` and this document are the tracked results. Every
extraction path is read-only with respect to the package. The optional SixNG
backend (GPL-3.0) is an external executable; nothing from it is bundled.
