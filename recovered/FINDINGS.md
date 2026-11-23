# Findings — GTA VI (Xbox 1.0.2.1)

Read-only analysis of a local `GTA6.Xbox.v1.0.2.1` package with `gta6x`.
Nothing here required a key: the table of contents is encrypted, but resource
payloads are zlib streams, media carriers are stored in the clear, and texture
pools carry their own indexes.

All numbers below were measured on this package with the parsers in `gta6x/`.
They are observations, not format guarantees; the tool's `selftest` (189 checks)
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
| Complete PSIN | `data.rpf --limit 16`: 1,049 containers, **32 joined**, including four stored tails | `structured` |
| Native LSCH/LENM schemas | 821 discovery / 223 comparison containers; nine inferred type labels; 118,111 / 26,632 enum members, unknowns preserved | `psin --schema` |
| Native PSIN instances | 821 / 223 data containers and 1,012 script metadata containers; 1,069,517 current value observations byte-round-trip; after map-entry support, 2,044 partial and 12 with all listed fields handled | `psin --instances` |
| Cross-file PSIN schemas | 697 provider pairs; 2,462 missing embedded-field annotations resolved across the two data samples; version conflicts retained, no additional instance values in these samples | `psin --registry` / `--registry-out` |
| Low-ID PSIN pools | 9,984 added hash/ASCII values; candidate references and opaque 4/8/16-byte views keep unknowns explicit; 1,067,509 total record/pool values byte-round-trip | `psin --instances` |
| Bounded PSIN hash32 arrays | 3,188 field arrays, 2,008 attached hash observations; all 1,069,517 current observations byte-round-trip; other profiles remain unresolved | `psin --instances` |
| PSIN structure-array links | 25,656 array fields / 15,685 bounded links to existing local typed rows; partial targets stay explicit; no duplicate value observations or recursive expansion | `psin --instances` |
| PSIN reference-array links | 34,185 array fields / 55,819 local record links / 14 explicit null slots; both pointer levels bounded; all prior values/array associations preserved | `psin --instances` |
| PSIN reference fields | 113,913 local field observations bound: 33,821 record links / 80,092 explicit nulls; all prior arrays/values preserved; no global primitive type claim | `psin --instances` |
| Enum-record PSIN arrays | 41 arrays/260 links to existing local enum rows; no duplicated values | `psin --instances` |
| Enum-key PSIN maps | 61 additional maps/182 links to existing records; local LENM membership, no duplicated values | `psin --instances` |
| PSIN map-entry links | 15,274 discovery / 3,782 supplementary-validation fields, linking 29,366 / 22,469 existing records; unsupported profiles and budget refusals explicit | `psin --instances` |
| Streamed textures | All 357,115 layouts supported: **305,959 zlib/raw complete** (+47,695 BC1 BCPack); selected raw 16/32-bit/packed PNG formats and mip/layer/Z selection; BC6H tone-mapped | `textures --png`, `--via sixng` |
| Embedded txd textures | **1,347 dictionaries / 3,167 descriptors**; 3,020 2D descriptors + 34 BCn arrays supported; arrays retain 155 layers/169 subresources; 113 volumes supported; all 31 mipmapped 2D textures export 253 levels including packed tails | `textures --embedded` |
| Movies | 515 Bink2 titles in `movies.rpf`: 8.83 GB, 3.94 h total | `movies` |
| Declared Ogg | All 4,659 supported mono streams remux; retained packets identical, 7,570 unused tails omitted, explicit timing assumption | `awc --ogg-policy declared` |
| Music PCM WAV | 35 zero-skip channels unchanged; opt-in exact overlaps add 17/18 nonzero channels, one unobserved skip size refused | `awc --music-wav-out --music-skip-policy verified-overlap` |
| Opus PCM WAV | Optional libopus, mono declared duration or opt-in mono/stereo packet sequences at 48 kHz; original interval unconfirmed, XMA2 unsupported; music has a separate path | `awc --wav-out --wav-policy` |
| AWC audio | 238 containers in the first 48 MiB; per-stream Opus metadata, native payloads and Ogg remux | `awc`, `scan` |
| DXBC shaders | **9,089** validated in the first 64 MiB of `shaders.rpf` | `shaders` |
| Models | `packs.rpf`: 80,424 entries, **75,135 model resources**, 27,288 named → glTF/GLB | `models` (SixNG backend) |
| Native RBF0 metadata | One 21-page resource, 56,796 tokens/nine descriptors; searchable 1,126 sets/6,677 entries/3,669 literal Rig strings, runtime meanings unknown | `rbf --rig-sets` |
| Animation resource metadata | 618/377 discovery/validation 0DRP candidates parsed; 175/271 joined, local raw schemas/enums/block spans exported with unknowns explicit | `anim --resources` |
| Named animation clip records | 191/170 discovery/validation dictionaries; 1,277/1,432 bounded name/node/record-prefix links, no curve decoding | `anim --clip-records` |
| Animation component/buffer links | 1,277/1,432 discovery/validation clips; 3,794/3,946 animation links and 4,956/5,617 opaque buffer references, all bounded/hashed; contents undecoded | `anim --clip-components` |
| Animation storage rows | 879/908 discovery/validation distinct buffers partition exactly; conditional bit rows in 496/497, other bit grammars unknown | `anim --storage-layout` |
| Raw animation word inventory | Narrow source-word profile in 12/879 discovery and 9/908 validation buffers; slot association/numeric meaning unknown | `anim --payload-layout` |
| MoVE child/tail prefixes | 266 earlier plus 131 kind-3/12/11/28/4 forms: 397/440 immediate candidates, 43 unknowns; bodies remain opaque | `move --children`, `--tail-forms` |
| MoVE root storage | All 212/112 discovery/validation views; 179 relative targets and 288 descriptors, opaque child bodies | `move --objects` |
| MoVE envelopes | 212/112 discovery/validation counted envelopes; all parse unchanged, payload motion meanings unknown | `move` |
| Animation slot directories | 879/908 discovery/validation distinct buffers; all 4,956/5,617 aliased directories resolve; eleven unknown slot groups, no sample decoding | `anim --channel-layout` |
| Packed animation metadata | 3,794/3,946 discovery/validation layouts; 223,879/236,886 raw channel-binding candidate rows; bounded header/auxiliary/sample-index views, no value decoding | `anim --packed-layout` |
| Animation | 130,771 streams / 2,327 names; `0DRP`, `MoVE`, 1,788 candidate packed-header matches, `RBF0`; clip identities/curves unverified | `anim` |
| World data | placements, collision, navmesh, paths, lights, interiors, vehicles, meta/PSO, shader census | `world` (SixNG backend) |
| Name hashes | 50,864 joaat hashes / 36,943 case-sensitive / 87,924 locally enriched Murmur3-64 hashes | `names` |

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

### Native model feasibility investigation

A fixed discovery-only `packs.rpf` window yielded 445 checksum-valid compressed
streams / 350 unique inflated payloads / 22,540,384 inflated bytes. Anonymous
headers have repeated length/offset equations, but those do not establish model
identity, complete resource boundaries, vertex/index formats, stored counts or
topology. Whole-span XYZ and integer-ramp interpretations fail counterexamples.

No native model runtime or command was added. Eight authored probe tests pass;
the separately assigned validation window was not read. This investigation used
only this project's own code and authorized game bytes; no upstream decoder or
external backend was consulted. A bounded owning declaration with redundant
geometry counts/formats is needed before implementing a native exporter.

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

### Optional Opus PCM/WAV export

`awc --wav-out` uses the installed BSD libopus public API for standalone mono
48 kHz Opus. Strict full-2-KiB framing validates every packet and trailing zero
padding; no truncated records, concealment or missing samples are substituted.
Input is capped at 64 MiB and decoded PCM processing/output at 128 MiB per stream.
Raw/Ogg/music exports retain their existing paths. Missing libraries and decode
failures produce explicit reasons/nonzero exit; unsupported codec profiles skip
with reasons. The CLI exported six real WAVs from the first selected container.

The trim policy skips an assumed 312 frames then keeps declared mono samples;
`--wav-pre-skip` makes overrides explicit. Metadata records actual decoded and
output frames, discarded tail and library version. This is not a recovered
encoder delay or confirmed in-game alignment. Stereo requires the packet-sequence
policy below; XMA2 remains unsupported. Music export is described below.
Selftests use authored framing/PCM without requiring libopus.

A content-hash 171/67-container split was frozen before packet research, on
previously indexed audio. All 3,349/1,310 supported mono streams pass framing;
nine validation stereo streams were not fitted/promoted. Eight selected streams
per role decode to 1,561,860 total requested frames. All 32 allocation/framing
controls refuse. FFmpeg forced to the same libopus backend agrees within one
PCM16 unit (three byte-identical cases); this is wrapper interoperability rather
than independent codec confirmation. The separate native FFmpeg decoder differs
substantially (held-out maximum 17,282 units), and all 16 legacy Ogg durations differ.
No runtime alignment tuning followed those comparisons. Legacy timing remains
unchanged and explicitly unconfirmed; further independent evidence is needed.

### Explicit standalone Opus packet sequences

`awc --wav-out DIR --wav-policy packet-sequence` now exports complete decoded
mono/stereo sequences at 48 kHz with zero leading trim by default. An explicit
`--wav-pre-skip` can remove leading frames. The AWC sample-count word is retained
as metadata but never used to infer a stereo duration or trailing trim. Fixed
output channels come from the stream declaration; legal packet mono/stereo
switching is handled by the public libopus API. No original game interval is
claimed, and no missing samples are concealed or padded.

The unchanged 171/67-container split provides eight discovery and 17 selected
validation sequence decodes. All nine stereo streams are from one previously
exposed validation bank; they were not discovery fitting or independent accuracy
evidence. Their 1,965,120 decoded frames include 1,964,172 with differing left
and right samples. Authored public-API tests separately exercise channel
switching, since no real mixed-TOC sequence occurs in these samples.

All 16 selected prior mono WAV hashes and complete metadata are identical;
default stereo refusals remain. All 50 new malformed controls refuse. A native
CLI check exports all 13 selected-bank streams, including nine stereo streams,
with per-file frame counts matching JSON metadata. Music defaults remain 312
pre-skip frames even when standalone packet-sequence export is also requested.
Runtime/tests/audit were frozen before validation; prior seals remain unchanged.

### Indexed audio config and external radio-credit candidates

`music --config` checks bounded indexed storage independently of record-kind
meanings. Family 26 records encode separate name-table byte offsets in the
upper 24 bits of the first word. Two discovery tables match all 238/4,543
index entries by complete string boundary and JOOAT hash. Their named
`WaveSlotsList` records exhaust 236/504 local kind-8 references. These are
wave-slot lists, not radio playlists. Unknown kinds, opaque tails, incomplete
resources and unsupported index prefixes remain explicit; record extents are
storage upper bounds, not proven complete objects. No checksum is claimed.

The config-only byte split was fixed before inspection and stops before the
first existing frozen AWC bank. The sealed index parser reproduces 16,340
discovery and 3,020 validation rows. Discovery yields 4,781 checked names and
740 slot links; validation has no eligible name/list examples. A combined
pass adds 86,715 rows from a crossing resource, classified as mixed/reused,
not independent validation. Six unsupported/incomplete groups stay refused.
Index extent/count, name-offset, list-count and budget controls discriminate
their damaged inputs. Reversing list order intentionally passes: only the
stored order is exposed. No natural indexed music-owner links were found.
All 1,589 legacy music observations lie in the reserved config validation
window; diagnostic counts did not retune the parser or consume it for fitting.

The shared GameSpot article led to public Rockstar credits as independent
spelling hypotheses. The article itself was inaccessible through the browser
tool. A private catalog retains all title/artist/station contexts from 764
song credits across 22 station credit sections, excluding three nonstation
performance sections. Fixed literal/transliterated/word-separated/compact
spellings of titles and artist-title pairs give 7,334 entries. Full hash B
matches 599/1,589 existing music observations: 593 with one credit candidate,
six with multiple candidates; 990 unmatched. `music --catalog` exposes these
optional external annotations without altering original record fields or the
name dictionary. Artist-only, station-only and truncated 29-bit matches cannot
assign songs. Duplicate credits remain ambiguous. This reused-data hash
agreement does not establish song identity, native station membership, AWC
bank links, playback order or independent semantic accuracy.

The index profile was sealed before validation. Later catalog annotations
are an additive CLI feature with a separate successor seal; the index parser,
names/list rules and original sealed CLI snapshot are unchanged. All 80
inherited frozen artifacts and BCPack labels remain unchanged. Authored tests
cover bounds, atomic refusals, ambiguity and wrong-full-hash negative controls;
no game/song catalog is bundled. No upstream implementation was consulted.

Follow-up native-radio investigation froze new source roles before inspection:
the unassigned common tail and audio bytes 128–160 MiB supply discovery;
160–176 MiB of audio is reserved validation. Discovery's 359 common zlib pages
inflate to 21,974,679 bytes, with no radio keyword strings or matches to 79
previously fixed public station-name hashes. The audio window has no zlib
config streams; descriptor inspection finds 35 AWC headers (34 containers
wholly inside the window), 1,203 streams and no music channels. This yields
no station/playlist rule. New validation has no eligible config indexes.

Separately, a permitted old discovery resource exposes the reason for its
earlier refusal: two length-prefixed sections precede its hash/offset pairs.
`music --config --index-sections` adds that opt-in family-581 profile without
changing the strict parser. It reproduces 115,183 distinct index rows and
2,040 partitioned groups / 7,305 raw values, bringing the discovery window to
131,523 rows. Extent, group-partition, index and budget controls discriminate
damaged data. Group value order/repetition is deliberately preserved without
playlist semantics; two incidental local hash equalities are not promoted
to references. Raw record kinds, group meaning and value targets remain
unresolved. The new profile was sealed before its new validation scan, but
there are no positive held-out examples of this layout. Station-name
candidates in the old crossing/protected resource were excluded from fitting.
All prior source roles, seals, catalog hypotheses and provisional BCPack
labels remain intact. No native station membership or playlist edge is claimed.

Public-source reconciliation used the user's unchanged GameSpot paste and a
fresh Rockstar credits download, byte-identical to the earlier snapshot.
All 743 pasted entries across 20 music stations are retained. Exact normalized
station/title/artist text agrees for 611 rows; 58 have matching titles but
different artist text, two put the same credit in another primary section,
15 point to unassigned DJ/program credits, and 57 lack exact primary-title
agreement. These are source-comparison categories, not identity verdicts;
shortened titles, versions and typography account for some differences.

Fixed punctuation/transliteration/apostrophe/ampersand and explicit title-
excerpt hypotheses increase primary-context full32 hash-B coverage from 599
to 664 records. Separately labeled internal-period/stylized-symbol hypotheses
add three, reaching **667 records / seven ambiguous** with no previous match
lost. Secondary spelling transfer requires agreement on normalized station,
artist and title; it cannot reassign a station or select a recording version.
The catalog includes 764 SONGS credits and eight explicitly named Liquid City
compositions with unspecified performer; 105 rows remain unmatched. All
matching spellings and original record fields are retained for audit.

Rockstar's separate Additional Music section adds 22 factual song credits to
the 74 previously retained nonstation DJ/program/band entries. These 96 rows
yield 72 candidate records; union with the primary contexts covers **731**
distinct existing music records. No station is assigned from those headings.
For example, the pasted station claim for Linkin Park's In The End is kept
separate from Rockstar's Additional Music credit. Including all independent
GameSpot spellings yields 733 candidate records, with the remaining extra
spellings/assignments explicitly uncorroborated by the primary hash catalog.
These are reused full-hash observations, not fresh held-out semantics or
native playlist links. Private per-section CSV/JSON reports retain all songs,
unmatched rows, ambiguous candidates and source differences. All runtime
modules, the name dictionary, 88 inherited frozen artifacts and provisional
BCPack labels are unchanged by this source-only follow-up; no game bytes were
used to fit new grammar. Ten authored research tests cover parsing, provenance,
ambiguity, full32 controls, work bounds and conservative alias transfer.

The next gap investigation tests 12,274 public work/file-style spellings and
26,936 movement/station-style spellings against the unchanged marker layout.
Symphony and Vault produce no new song-credit candidate. Extending those
same rules across all 105 unmatched credits finds six provisional preimages:
three literal/remix excerpts and three full-title `_dsc` suffixes. All six
are within the original default cohort; fresh compressed-page inflation and
46-byte record rereads reproduce durations, ids, markers and full32 hash B.
Recording/version identity and native membership remain unproven. A bare `I`
movement fragment maps to the existing Black Sabbath title and is rejected,
illustrating why hash equality and zero wrong-name controls cannot establish
the semantic association by themselves. No catalog entry is added for it.

Primary-context coverage increases 667→673, with seven ambiguous records;
99 public rows remain unmatched. All-Rockstar context coverage is 737 and
the all-source union is 739. Symphony remains 0/16 candidate credits, Vault
1/24; the latter is still a shared `Baby` excerpt. Earlier catalogs, profiles,
inputs and all 90 inherited frozen artifacts remain intact. New hypotheses
are external preimages on reused metadata, not independent held-out accuracy
or native grammar learned from reserved data.

An authored regression exposed a separate CLI issue: requested duration bounds
were applied after a scanner using its defaults. `scan_file` now accepts and
validates the caller's range, and `music` forwards it. Default output matches
all 1,589 original rows exactly. A wider 0..u32-max pass over the already-used
18 MiB compressed prefix yields 2,406 marker observations: 812 extra short
and five extra long, none adding a public song match. The serialized record
layout and markers are unchanged. Existing discovery-only AWC descriptor
inspection finds all 35 raw channel ids have their upper three bits clear;
these provide no additional complete32 name evidence. No long observation
or channel id is assigned a station or recording from duration/low bits alone.
Authored tests cover duration forwarding, early range rejection, public
movement/work labels, preserved ambiguity and work bounds. Bounds-only
research-helper updates retain exact archived versions and reproduce every
study spelling set, without retuning names after comparison.

### Declared Ogg granules and music WAV

`awc --ogg-policy declared --ogg-out DIR` uses cumulative packet sample counts,
valid monotonic granules and EOS trimming for an explicitly selected interval.
Retained compressed packets are unchanged; later whole packets are omitted.
AWC blocks and RFC 6716 packet framing are validated even for omitted tails,
without claiming compressed-frame integrity. The inherited 312-frame pre-skip
remains an assumption. Legacy stays default with unchanged bytes; optional
`--ogg-pre-skip` only applies to declared mode.

All 3,349/1,310 frozen mono streams remux, retaining 299,219 packets and omitting
7,570 whole tails. All 308,537 CRC pages and 9,318 malformed controls pass. Sixteen
selected outputs have the requested 1,561,860 frames; the same-libopus FFmpeg
wrapper comparison differs by at most one PCM16 unit. This is interoperability,
not independent codec or source-alignment confirmation.

`awc --music-wav-out` validates exact source/channel descriptors, whole block
and channel allocations, packet extents, seek-counter relations and zero
padding before decoding supported channels. The default policy enables only
zero block skips; the explicit overlap policy below extends that subset. Metadata records source
identity, channel, block skips, trimming and decoder version. Corrupt data or
missing dependencies fail explicitly while other requested exports continue.

The music cohort was frozen from full-container metadata before block research:
16/15 containers, 35/18 channels, no overlap with the standalone cohort. All 35
zero-skip channels decode in the separately labeled post-freeze full regression,
totaling 127,030,977 frames. The default policy refuses all 18 nonzero-skip
channels. All 155
corruption controls refuse; reorder controls discriminate 26/35, with nine same-duration
nondiscriminatory cases. Eight selected real same-libopus comparisons differ by
at most one PCM16 unit. Initial empty prefix-only metadata capture was retained
and superseded by the documented full-container v2 split before fitting. No
rule was fitted from validation. Original music alignment remains unconfirmed.

Native CLI checks exported six declared Ogg files and one real discovery music
WAV. The latter used an exact frozen AWC container with scanner alignment padding
in an ignored temporary file; no source bytes were modified or published.

### Guarded music packet-overlap reconstruction

`awc --music-wav-out DIR --music-skip-policy verified-overlap` accepts only
discovery-observed skip sizes that end on whole-packet boundaries and exactly
repeat both the preceding block suffix and reconstructed compressed history.
It keeps complete descriptor/allocation/seek/padding validation and performs
no partial-packet removal, silence insertion, concealment or re-encoding.
The original zero policy and existing music Ogg behavior remain unchanged.

Frozen discovery has 29 exact-overlap events across 16 nonzero channels; all
16 decode. Validation supports one of two nonzero channels. Its unseen
25,920-frame skip stays refused even though a later diagnostic found an exact
27-packet repeat; no validation-driven whitelist extension was made. Total
support is 52/53 channels, including all 35 original zero-skip WAVs with exact
old hashes and metadata. Thirty supported overlap events remove 277 duplicate
packets / 265,920 frames; all 30 same-duration wrong-byte controls refuse.
Three selected FFmpeg comparisons force the same libopus backend and differ
by at most one PCM16 unit with equal lengths. They are wrapper checks, not
independent ground truth. Global 312-frame pre-skip, original alignment and engine
reset/pre-roll behavior remain unconfirmed. Real CLI export produced four
WAVs, including three nonzero-overlap channels, from one frozen discovery bank.

### Alternate-container discovery investigation

Preassigned discovery windows in data/common/levels produced 1,167 compressed
streams and 833 PSIN starts: 829 complete checksum-valid standard LSCH chains
plus four known stored-tail partials. No PMAP literal was present. The sole
PSCH literal in common has an out-of-bounds declared extent and does not
authorize a section or container grammar. No runtime parser was added.

Eight authored tests validate bounded probe measurements. Existing assignments
remain unchanged and validation sections were not decoded or used for fitting.
Initial header setup accidentally read the entire data archive before slicing
its first 96 bytes; this raw-I/O overread is recorded in local provenance, so
the validation byte range is not described as literally unopened. There is no
alternate-format accuracy or exhaustive absence claim from these windows.

### Stored PSIN terminal tails

Complete seven-section PSIN resources can end in a short stored span after one
or more full compressed 64 KiB pages. The existing next-16-byte boundary and
zero-padding rules still apply. Section lengths plus CHKS independently bound
and validate the exact stored extent; no raw-first/interior-page or PMAP support
is inferred. Stored bytes may contain valid compressed signatures, which do not
become separate resources inside the authorized tail.

The frozen discovery ranges add four containers; validation adds ten distinct
containers without retuning. All 3,211 prior payloads/hit dictionaries remain
exact. The additions contain 302,260 stored bytes / 2,989,236 decoded bytes;
they are positive structural confirmations, not an exhaustive accuracy rate.
All 84 malformed/bounds controls refuse, and 14 raw/archive plus 14 unclaimed-
trailing-byte controls pass. Frozen schema/provider memberships remain unchanged.

Structured export and schema browsing both retain conditional storage labels.
A native CLI check reproduces an exact discovery payload hash with a 1,688-byte
stored tail. A fresh `--limit 16` scan reports 1,049 complete PSIN containers /
32 joined in `data.rpf`; the same scope on the immediately prior implementation
has 1,045 containers / 28 joined, all preserved. The older published 1,048 count
was stale. Pure compressed PSIN recovery now also explicitly enforces CHKS;
all original frozen outputs already meet that requirement.

### PSIN

Seven tagged sections (`PSIN`, `LSCH`, `LENM`, `LSNS`, `LGID`, `LRSC`, `CHKS`)
tile the blob exactly; `CHKS` is 20 bytes and repeats the total length, a stored
checksum and a platform tag. Section 1 is the instance-table body
(`PSIN | size | (type,length,AA8)* | PP8 | aligned blocks`). Pages that
declare a section longer than the available stream are stream-split fragments,
not a second format.

Ordinary body summaries now use the same verified parser as instance blocks,
including the first type/length pair at +8. Existing raw compatibility keys
remain; entries count blocks, not records. Missing table terminators leave
payload bounds unknown; exact lengths, AA/PP markers, zero padding and EOF
are checked. The 821/223/1,012 frozen discovery/comparison/script bodies all
match strict extents, with 15,217/2,232/4,901 blocks. All 2,056 extra-byte and
12 prefix controls pass. These are reused structural cohorts, not new semantic
ground truth. Schema checksum gates are unchanged.

Section roles from the observed layouts: `LSCH` schema headers/fields, `LENM`
enum name/value records, `LSNS` 128-bit name records, `LGID` global 128-bit id
records, `LRSC` resource-reference/fixup records. These roles do not establish
type/instance semantics; `CHKS` is verified below.

The `CHKS` checksum is RAGE JOOAT (signed bytes, seed `0x3FAC7125`) over the
whole container with the `CHKS` length and checksum fields zeroed, big-endian.
It verifies on **821/821** complete containers in the 8 MiB `data.rpf` sample (788/788 for the stream-local `psin` sample).

Native LSCH structural browsing is now implemented independently from observed
game bytes and the repository notes, without GPL sources or decoder tables.
The eight-byte tagged/BE-length prefix is followed by contiguous 32-byte LE
structure headers, then grouped 16-byte LE field descriptors. Header field
counts determine the table boundary and account for the entire section. Each
header has eight `AA` bytes at +0x10, structure size at +0x18 and descriptor
count at +0x1e. Field records preserve hash/id, data offset, numeric type word
and unresolved auxiliary word. Unknown header words and upper type bits remain
explicitly unknown; some ids such as `0x100` are synthetic. Field starts must
be inside the structure size; field widths are not inferred.

The discovery range contains 40,019 structure headers / 248,108 field records
across 821 verified containers, with 433 distinct LSCH byte sequences. The
unchanged parser validates a disjoint payload-relative 8..16 MiB range:
223 containers, 2,903 headers / 23,653 fields, 34 distinct sections all absent
from discovery, two joined resources, no refusals. These checks establish
structural consistency, not independently confirmed type meanings or instance
values. The browser exports all schemas to JSON, deduplicating by full LSCH+LENM
identity and preserving conflicting same-hash definitions. Optional dictionaries
annotate hashes with all matching name/source candidates.

LENM now parses independently: 24-byte contiguous LE headers after the section
prefix, followed by grouped 16-byte member records. Header +0x08 has eight EE
bytes, +0x10 is the member count; member +0x00 preserves a full 64-bit value,
+0x08 its hash/id, +0x0c an unknown word. Header counts account for every byte;
aliases, signed/unsigned views and unknown words are retained. Discovery parses
11,794 headers / 118,111 members (337 values have their sign bit set); comparison
parses 1,748 / 26,632 (217 sign-bit-set values), with no section refusals.

Inferred LSCH meanings are bool8, float32, hash32, embedded_structure,
dynamic_array, map, enum32 and enum_bitset32/64. Original words remain intact;
unsupported attributes, absent/ambiguous references or inconsistent extents
leave the type unknown. Code 0x63 is enum-associated but deliberately unlabelled.
In the separate range, all 13,004 checked enum32 payload values occur in LENM;
19,348 bool8 samples are 0/1 and all 21,682 float32 samples are finite. Distinct
hash32 samples yield 31 local name matches versus zero in a wrong-endian control.
Map and enum_bitset64 have discovery evidence only; this range contains none.
These are consistency observations rather than independent semantic confirmation.
The range was previously used for structural validation, so it is not a new
blind holdout. The research-only body probes do not enable instance export.

JSON format v2 includes separate LSCH/LENM hashes and a combined identity so
different enum sections cannot disappear behind a shared LSCH hash. BCPack
tables, provisional entries and frozen holdouts are unchanged. All game-derived
metadata and audit reports remain local and ignored.

The next milestone reads native instance blocks: the body table starts at +8,
with `(u32 type/hash, u32 bytes, AA x8)` entries and an eight-PP terminator.
Payload blocks follow in table order, padded to 16 bytes. All 15,217 discovery
entries account for the body exactly; 33,406 observed alignment bytes are zero.
The legacy body summary's first two fields are the first table entry; its
heuristic entry count omits it. Compatibility fields remain in that summary,
while the new reader retains every entry and checks all bounds/padding.

`psin --instances` exports inferred local Boolean, finite float32, hash32,
enum32 and embedded-structure values. Enum aliases and original bits survive;
unknown blocks/members are explicit. Only bounded hash32 spans and local
structure-array record links are supported; other array/map pointers and
bitsets remained unresolved at this initial milestone. Shared output-node
budgets, embedded depth/cycle guards and strict
JSON handling prevent silently truncated lists or NaN/Infinity output.

Native validation parses all 821 discovery containers (732,614 supported leaf
observations), 223 comparison containers (94,289) and 1,012 script metadata
containers (230,622). Every decoded leaf encodes back to its source bytes;
there are no block-profile refusals. All resources were partial at that milestone. Counts include
nested/repeated observations, not unique types or full graph coverage. The data
comparison range was used before; script is additional cross-archive evidence,
not an independent semantic oracle.

Schema metadata also exposes raw base type/sub-code bytes without changing the
legacy 16-bit type_code, plus header flags and alignment/signature candidates.
Public upstream documentation motivated these fields; independent checks on
the existing discovery cache found 40,019/40,019 compatible alignment candidates
and no conflicting size/offset/type patterns among 805 signature candidates.
No GPL implementation or mapping table was copied; all unresolved meanings and
the original numeric words are preserved.

The optional signature-aware cross-file registry now retains definitions by
name hash, raw `+4` signature candidate and full-content fingerprint. Identical
definitions at different offsets deduplicate; different signatures and
same-signature/different-content conflicts remain ambiguous. References have
no signature selector, so no size, frequency or source-order heuristic selects
a version. Local definitions take precedence, including local ambiguity. IDs
below `0x10000` remain file-local by conservative policy. Imported structures
use global-only dependency lookup, avoiding unrelated receiving-file or
arbitrary donor-file bindings. Registry files contain game-derived sections,
remain private, and are not shipped with the tool. Reload checks sections and
identities, not original source-container checksums.

Provider discovery covers data payload MiB 0..8 and 16..EOF; common.rpf adds no
recoverable PSIN. This supplies 1,976 sources / 697 schema pairs, 4,385 structure
variants under 3,807 names and 757 enum variants under 742 names. Thirty-eight
structure names and twelve enum names have conflicting versions; none of these
conflicts share a signature candidate. The registry is frozen before each final
comparison; the initial 433-pair registry and expanded registry produce the same
gains on the existing samples.

The 821 provider-subset, 223 comparison and 1,012 script samples gain
2,461 / 1 / 0 inferred embedded-field annotations (per-container declarations,
not unique fields). They gain no supported instance values. All 1,057,525 old
leaf values persist unchanged and re-encode to exact source bytes; no resources
are refused; all were partial at that milestone. Remaining unresolved typed blocks use low IDs
and stay reserved (862 / 379 / 1,010 blocks). Comparison and script resources
have zero provider-content overlap, but are previously examined samples, not
fresh blind holdouts. This is structural/byte consistency evidence, not a
semantic oracle. No type or signature meaning was promoted to confirmed.

Low-ID blocks without local definitions now have bounded pool views. Data
discovery contains 792 blocks of ID 0x07, 23 of 0x10, four of 0x14, one of 0x33
and 42 of 0x4a. Comparison has 220 of 0x07 and 159 of 0x4a. Script's 1,010
previously unresolved blocks all use ID 0x16. Synthetic/local structure IDs
such as 0x100 keep their existing local interpretation; ambiguity and stride
failure never authorize a primitive fallback.

0x4a reuses the inferred hash32 meaning. 0x10 is a measured NUL-terminated
printable ASCII pool, including empty strings; no other text profile is
assumed. Other profiles refuse the entire pool view with a reason. Native
output adds 1,071 / 8,913 / 0 values in discovery / comparison / script:
9,931 hashes and 53 strings total. All 1,057,525 pre-existing record leaves
are unchanged; all 1,067,509 current decoded values byte-round-trip. Every
pool element consumes the shared node budget; there is no silent truncation.

The candidate reference partition for 0x07 is a one-based block ID in the low
20 bits, with byte offset above it. All 51,844 / 4,040 nonzero pool words and
10,717 / 1,322 nonzero typed 0x07 field words land in local structure targets
at stride boundaries. Wrong bit partitions, byte order and target order do
not reproduce that complete consistency. This is candidate metadata only:
55,898 pool words retain original bits and unresolved status, with explicit
zero/bad-ID/out-of-bounds diagnostics. No target bytes are followed or decoded.
0x14, 0x16 and 0x33 expose 4/8/16-byte raw groups (13,465 total), with unknown
meaning and no signed-integer, hash64 or vector label. Group size is a viewing
choice, not a confirmed scalar width. All resources were partial at that milestone.

The partition and hash/ASCII rules were fixed using data discovery and authored
tests before applying them to comparison/script. The opaque 0x16 view was added
after exploratory script inspection. ASCII and 0x14/0x33 have discovery evidence
only; no compatible examples occur in comparison/script. These samples were
examined in earlier work and are not fresh blind holdouts or semantic oracles.
No additional upstream source/decoder was consulted and no type meaning was
promoted to confirmed. Game bytes, probes and audit outputs remain private.

Bounded hash32 arrays now attach intrinsic-pool hashes to their local owning
fields. Only exact local hash32 element descriptors, equal-u16/zero-tail
16-byte headers, null-empty profiles and aligned, wholly bounded 0x4a pool
spans are supported. Raw header bits/words remain; count/capacity roles are
not distinguished. Imported owners, other element/header profiles and target
schema conflicts stay unresolved. Every element shares the existing output
budget, including aliases and repeated standalone pool observations. Other
pointer profiles and recursive graph traversal remain unsupported outside the
bounded field/array/map-entry associations below. Structure
arrays now use the bounded record links described below.

The source split was locked before implementation: 821 discovery, 223 data
validation and 1,012 script validation observations, with zero cross-role
payload overlap. Validation has 1,092 distinct payloads. All sources had prior
research exposure, so this is frozen consistency evidence, not a fresh blind
holdout or semantic oracle. Membership changes fail; no inputs were promoted.

Discovery / data-validation / script resolve 2,445 / 743 / 0 array fields,
including 1,926 / 367 / 0 empty arrays, and attach 1,011 / 997 / 0 hashes.
All 1,067,509 prior scalar/pool observations remain unchanged; all 1,069,517
current observations byte-round-trip. These are field associations with already
decoded pool bytes, not new unique physical hashes. All 470 discriminating
reversed-order controls disagree with source spans. Other descriptor profiles
leave 72,000 / 2,931 / 0 recognized array fields unresolved; all resources stay
partial. No rule was tuned from validation results and no GPL source/table or
external decoder was used. Authored tests and private audit provenance record
the profile's limits and the unchanged frozen split.

Structure arrays now connect local fields to existing typed record rows.
Exact local 0x05 descriptors require one positive-size local target definition,
the equal-u16/zero-tail/null-empty header profile, exact target type and a whole
aligned bounded record span. Imported schemas, duplicate/missing definitions,
size-only matches and other profiles remain unresolved. Links contain block/
record indices, offsets, sizes and structure hashes; they never copy scalar
values or recursively expand targets. Cycles/aliases are finite metadata and
each link consumes the existing shared node budget. A complete array means
its links are validated; linked records may still be partial.

The unchanged frozen groups resolve 25,526 / 130 / 0 structure-array fields
(16,745 / 31 / 0 empty) and link 15,392 / 293 / 0 records. All 1,069,517 prior
values remain unchanged and byte-round-trip; all resources were partial at that milestone.
Of the links, 1,220 point to partial records. Missing/ambiguous local schemas
leave 15,059 structure-array fields unresolved. Reversing record order
discriminates 2,278 spans; 2,277 also discriminate byte content. No validation
sources were promoted, no rules were tuned from validation results, and the
provider registry remains frozen. These are consistency checks on reused
sources, not a fresh blind holdout or semantic oracle. No GPL source/table or
external decoder was consulted. Private provenance records authored tests,
source membership and the inference limits.

Reference arrays now resolve two bounded serialized steps: the local 0x07/zero-
aux element descriptor's equal-u16/zero-tail/null-empty header selects an
intrinsic reference-word pool span, and each nonzero word selects a whole
record under its target block's unique positive-size local schema. Zero words
are explicit null slots. Different target types are not treated as evidence
of inheritance. Local pool/schema ambiguity, bad spans or any invalid member
leave the entire array unresolved, with failed-slot bits and no prefix links.
Targets are never recursively expanded and no scalar values are duplicated.
Bare pool references keep their previous unknowns. Individual named 0x07
fields now have the bounded contextual binding profile described below.

With the unchanged frozen split, discovery / validation / script resolve
31,390 / 2,795 / 0 arrays and link 51,779 / 4,040 / 0 records, preserving
14 / 0 / 0 null slots. At the reference-array milestone there were 7,336
mixed-type arrays and 30,955 links to partial records. All 28,844 old hash32/structure-array associations are
byte-for-byte metadata matches; all 1,069,517 value observations persist and
byte-round-trip. Source-slot order discriminates 12,608 spans. Of 2,056
resources, 2,055 remained partial at that milestone; one had every listed field handled under
the inferred profiles, without a full-byte-coverage or gameplay-semantics claim.
15,090 recognized array fields remain unresolved. No validation sources were
promoted, no profiles tuned from validation results and no GPL source or
external decoder consulted. Results are consistency evidence on reused sources,
not independent semantic confirmation or fresh blind-holdout accuracy.

Standalone exact named 0x07/zero-aux fields now select existing local typed
record rows or preserve actual zero words as explicit nulls. Eight bytes must
fit the owning record/block without containing another named field start;
metadata descriptors are excluded. Nonzero targets require a unique positive
local schema and whole block/offset record strides and spans. Unsafe slots,
unsupported attributes, imported owners/targets and ambiguous definitions stay
unresolved. Raw bits are retained when safely readable. Bindings do not expand
targets or duplicate values. The schema type name remains unknown; only this
local profile is inferred. Reference arrays reuse the shared binding helper
without changing their prior association metadata.

Discovery / frozen validation / script resolve 102,280 / 11,633 / 0 fields:
31,691 / 2,130 / 0 record links and 70,589 / 9,503 / 0 nulls. All 63,029 old
array associations and 1,069,517 value observations remain identical and
byte-round-trip. No audit sources are refused; every wrong-endian nonzero
field word fails local target checks (33,821 controls). 20,013 new field links
targeted partial records before map-entry support. At that milestone, partial-target counts for prior structure/
reference-array links fall to 788 / 23,183 because more target fields are now
handled; their link metadata was unchanged. Resource statuses were 2,055
partial and one with all listed fields handled, not full gameplay semantics.
The split/registry remain frozen, no rule was tuned from validation results,
and no GPL source/table or external decoder was consulted. Evidence remains
bounded consistency on reused sources, not semantic-oracle or fresh blind
holdout accuracy. Private authored tests/provenance record the profile limits.

Bounded map-entry association is now implemented for local exact hash32 key
and hash32/bool8/locally defined structure value descriptors. Header layout is
24 bytes: unknown u64 (observed one), entry reference u64, equal u16 words,
zero u32 tail. The prefix is not treated as the entry pointer, and its meaning
and the u16 roles stay unknown. Empty maps require a zero entry reference.
Nonempty maps select the referenced block's unique positive-stride local
schema, with two named fields matching the descriptors: key at zero and value
at its declared offset >=4 within the stride. Observed structure values begin
at 4, 8 or 16; no fixed alignment/field hashes are hard-coded. Complete spans
must fit the logical block. Imported/ambiguous schemas and unobserved profiles
stay unresolved. Entries link existing records, retaining duplicates and stored
order; no hash-lookup/dictionary/inheritance semantics or recursive graph is
inferred. Partial targets remain partial, and no scalar values are duplicated.

Discovery resolves 15,274/15,293 fields (11,256 empty) with 29,366 links and 19
unsupported descriptors. Original frozen comparison/script groups contain no
maps. A separate locked map manifest preserves those groups and adds 1,155
supplementary validation observations selected by archive offsets before map
header analysis. These sources previously supplied schema-registry metadata;
this is reused-source consistency evidence, not a fresh blind holdout. Combined
validation is 2,390 observations / 2,228 distinct payloads, with zero discovery
payload overlap. No promotions, registry refit or validation-driven rule tuning.

The supplement parses 1,152/1,155 resources: 3,782/7,829 map fields resolve
(1,645 empty), linking 22,469 entries. It leaves 4,047 fields unresolved:
2,220 unsupported values, 1,269 unsupported keys and 558 unvalidated headers.
Three resources retain their pre-existing 250,000-node audit-budget refusals;
no maps are counted for these discarded outputs. Across all five groups,
2,142,630 prior values and 110,056 array / 196,274 reference-field associations
are unchanged and source-checked. Nine maps retain duplicate stored keys;
4,393 key-order controls discriminate reversed bytes. Of 3,208 parsed inputs,
3,183 remain partial and 25 have all listed fields handled, without a byte-
coverage or semantic-ground-truth claim. No GPL code/table/fixture or external
oracle was consulted. Authored tests and the private provenance preserve the
profile limits and exact split hashes. Validation cases remain validation;
broadening profiles requires separate discovery evidence.

### LRSC resource-header counts and record candidates

`psin --resource-header` independently validates a measured 80-byte LRSC
payload: `0DRP` / version 122, zero/BB sentinels, three counts repeating local
LSCH/LENM/PSIN table counts and a full-word block selector. The selected block
must contain exactly one uniquely defined local record. Its span/schema is
reported as a candidate association, never a proven root or decoded object.
No relocation/fixup list or recursive pointer traversal is inferred.

The optional view preserves schema and instance results, shares their global
metadata budget, and requires six nodes for a complete view or one for an
unsupported profile. Malformed/unsupported requested headers keep explicit
reasons without prefix metadata and exit nonzero. All 821 distinct discovery sources match, as do 2,390 frozen validation
observations / 2,228 distinct payloads, with zero cross-role hash overlap. All
19,266 malformed and 3,211 under-budget controls refuse. Opaque target changes
intentionally preserve the view, so target integrity/meaning is not proven.
The prior instance/value/binding modules are byte-identical to their baseline;
these reused-source checks supply no root-object or fixup semantic oracle.

### Null-empty structure arrays with missing definitions

An exact local synthetic structure descriptor plus a whole named 16-byte
all-zero array header can identify empty storage without the unused element
definition. Local slot/block bounds and nonoverlapping field starts are checked.
The result keeps the declared hash, missing-local-schema marker, null stride,
null target and empty elements. It does not resolve the element schema or add
values/edges. Ambiguous schemas, imported owners, nonempty and other profiles
remain refused; earlier known-schema empties are unchanged.

The four newly recovered discovery containers supply 588 examples. After
freezing implementation/tests/audit, the full original plus supplemental cohorts
yield 19,357 headers (15,641 discovery / 3,716 validation), including 2,661 in
the 14 stored-tail additions. All 3,222 decoded sources preserve 2,296,998 prior
values, 296,918 graph edges, 632,012 row identities and candidate reachability.
The larger totals include 154,368 existing values in newly recovered inputs;
this header profile adds none. The same three original budget refusals remain.

All 58,071 source mutation controls refuse. New graph invariants also reject
contradictory reference/count/tail diagnostics, targets or strides. Nine authored
tests and 278 PSIN tests pass. Existing source assignments/registries remain
unchanged; the supplemental four/ten split preserves prior roles and discloses
earlier recovery/schema exposure. No 0x63 example was found in discovery, and
bitset storage widths remain unproven. A native command recognizes 170 new
empty headers while retaining 5,472 values / 699 record nodes / 698 edges.

### Finite PSIN record-association graphs

`psin --record-graph` builds an index over already decoded top-level typed rows
and existing checked local field/array/map record links. Embedded source fields
retain bounded field-index paths; neither embedded nodes nor scalar values are
copied. Cycles, aliases, duplicate links and nulls remain finite. Raw candidate
words, text links and pool contents do not authorize graph edges.

An independently checked LRSC record candidate can anchor bounded reachability;
it is not labeled a root. Depth frontiers, missing anchors, unknown fields and
unrepresented blocks stay explicit. All record nodes remain indexed even when
not reached within the requested horizon. Partial graphs are normal, while
malformed/report-budget refusals preserve independent earlier views. Instance,
header and graph costs share the report budget with separate counters.

Across all frozen groups, 3,208 graphs now index 590,492 record observations /
264,745 checked edges / 190,222 candidate-reachable observations after the
opaque-key map extension below. The same three existing instance-budget
refusals remain; aliases/reused sources are not
independent semantic trials. All 2,142,630 prior values, complete fields and
associations are preserved, with 293 text links explicitly excluded. The original
graph audit refused all 5,660 tampered-link/candidate and 3,208 budget controls.
No new pointer interpretation or scalar decoding occurs. Its native discovery
CLI check retains five records / two edges / three candidate-reachable records
and an explicit unknown field. The same three earlier instance-budget
refusals remain unavailable, without relaxing their limits.

### Bounded PSIN nested-map links

Two discovery-observed descriptor trees now link existing local entry rows,
including map-valued fields and raw `0x15` key descriptors. Owning and target
schemas must have identical bounded descriptor trees after resolving their
local synthetic indices. Exact 32-byte entries, named fields at 0/8, whole local
slots, nonempty checked headers and logical record strides are required.
Raw `0x15` keys are neither read nor given scalar width or semantic labels;
linked rows may remain partial. Empty/cyclic/other/imported trees refuse.

One discovery source adds 13 maps / 60 links; 12 have opaque keys and 48 select
partial rows. Frozen validation has no eligible candidates reaching the new resolver,
so this supplies no held-out profile confirmation. All prior 2,142,630 values, complete bindings
and 293 text links persist, with the same three existing budget refusals.
All 91 discovery mutation controls refuse. The same splits/locks are unchanged,
with new runtime/tests/audit frozen before the validation run.

### Bounded opaque-key PSIN map links

An exact local synthetic key descriptor `0x054f`/zero auxiliary can now link
existing entry rows for three measured value layouts: a unique local 12-byte
structure, enum32 or float32. The independently declared entry strides are
24/16/16 bytes. Whole local header slots, exact descriptor equality, two named
entry fields at 0/8, redundant counts and complete reference/stride bounds must
agree. Offset eight does not establish a key width. Key bytes stay unread;
values remain in their existing rows, and empty/other layouts refuse atomically.

One discovery source supplies four maps / 18 links, all to partial target rows.
The graph adds exactly those 18 edges, retaining all prior row identities and
edges. All 2,142,630 values and 2,859,655 complete fields are preserved. The
unchanged 2,390 validation observations contain zero eligible examples, so no
held-out profile accuracy is claimed. The same three instance-budget refusals
persist; unsupported attempts can receive more specific refusal metadata.
All 32 new discovery mutation controls refuse. A discovery-stage correction
from assumed 16-byte to declared 12-byte structure values preceded the final
runtime/tests/audit seal and every validation execution; the retired preliminary
seal and result are preserved. No frozen split or earlier seal was changed.
A native discovery CLI check contains all four new maps, 895 existing record
nodes and 876 checked edges; candidate reachability grows from 744 to 762.

### Contextual PSIN ASCII-pool links

Named exact `0x42`/zero-auxiliary eight-byte slots and `0x44`/zero-auxiliary
24-byte slots can link existing nonempty printable-ASCII/NUL pool entries.
Whole local-owner slots, exact entry boundaries, full reference bits and
complete pool authority are required. The longer profile also validates two
entry-length words, marker one and zero reserved bits. Numeric type meanings
stay unknown. JSON `text_reference` links existing pool rows without copying
text or increasing scalar counts; forward/aliased pools share one node budget.

Discovery supplies 53 links (4 word / 49 header24); supplementary validation
adds 240 (231 / 9) from 11,160 attempts, leaving 10,920 explicit unknowns.
Zero-candidate comparison/script/small-supplement groups provide regression
coverage only. The frozen cohorts include aliases and earlier exposure; these
are structural consistency results, not independent semantic ground truth.
All 2,142,630 prior values, 110,056 non-enum-array associations, 196,274 field
references and 19,117 map associations are preserved, including the same three
existing budget refusals. All 1,465 pointer-mutation controls refuse. Earlier
`0x07`/`0x054f` profiles are unchanged. A real CLI check reports eight links.

### Native animation resource metadata

0DRP at +0x10 identifies a bounded resource-metadata profile in the animation
archive: version 122 at +0x14, three local table references at +0x28/+0x30/+0x38,
and u16 counts at +0x48/+0x4a/+0x4c. Table strides are 32-byte structure headers,
24-byte enum headers and 16-byte block entries. Structure fields and enum
members are separately referenced 16-byte rows. The fourth u16 at +0x4e and
header words +0x08/+0x20/+0x40 retain unknown roles. Schema/table interpretations
are inferred; no unverified reference is treated as a root or a clip payload.

The native resource browser follows only adjacent zlib pages at 16-byte
boundaries across zero padding. A multiple-of-64-KiB page may continue; a
short terminal page is required. Joined resources retain all source segment
offsets and sizes. Full-width virtual pointers are checked by subtracting the
observed 0x50000000 base, never by masking. All tables, field/member spans and
block lengths fit the joined bytes. Header/version/count/span failures, broken
chains and budgets return explicit refusals with no prefix metadata. Parsed
resources stay partial: there is no verified checksum/total-size framing,
complete byte-coverage claim, field-type/curve decoder or name binding.

Frozen discovery / validation ranges contain 794 / 648 carved streams and
618 / 377 candidates, all parsed with no profile tuning from validation.
175 / 271 resources require page joining; all 446 reversed-page controls fail.
27,089 / 16,957 structures, 218,458 / 126,912 fields, 399,769 / 247,432 enum
members and 13,904 / 8,765 data blocks round-trip/bound to the source; all
2,985 wrong-endian table-pointer controls fail. Validation's 377 resource
payloads are distinct and have zero discovery overlap; these already indexed
ranges are structural consistency evidence, not blind semantic accuracy.
All 47 legacy clip-stream signature matches in these ranges are continuation
pages inside 0DRP resources. The legacy signature is retained with an explicit
unverified-identity diagnostic, without counting independent clips.

`anim --resources --out` exports raw metadata in anim.json; limits are 16 MiB /
256 segments per resource and a shared user-set metadata node budget. Existing
stream/name lists remain available. No GPL implementation or external decoder
was consulted, no game fixture shipped, and PSIN/BCPack frozen inputs and
provisional labels remain unchanged. Next: establish named clip-record and
packed-payload associations from separately bounded evidence before decoding
curves. Private authored tests and provenance record the format/profile limits.

### Named animation clip-record prefixes

A separate observed animation dictionary profile now resolves names through
checked local slot tables and acyclic node chains into kind-2 record prefixes.
A record's raw key/tag must match its node, its bounded pack:/...clip string
must have exact printable-ASCII length/NUL, and the filename-stem JOOAT must
match the stored key. The verified prefix is 144 bytes; this does not establish
a complete object's extent or meaning for its class tag. A float at +0x78 is
retained as an unconfirmed duration candidate, with bits/reasons for nonfinite
or negative values. Node/record aliases and slot/chain order are preserved;
no hash-to-slot formula or play order is inferred. Unsafe/unsupported record
bindings retain raw node words and explicit reasons; graph/header/count/cycle
failures discard dictionary output. No packed payloads, bones or curves decoded.

Frozen quarter/half/three-quarter/tail discovery and validation windows cover
393/384 streams and 191/170 candidate dictionaries, with zero cross-role stream
or metadata-prefix hash overlap. All candidates parse and resolve 1,277/1,432
links without validation-driven profile changes. All name/header/node/key/
record/candidate-float observations round-trip to source bytes. Full-path
hashes and wrong-endian keys discriminate all 2,709 links. The archive was
previously indexed; these are structural consistency checks, not blind
semantic ground truth. Class tags and duration roles remain unknown.

29/27 candidates have all required naming spans in a whole-page prefix, which
is explicitly reported as bounded_metadata_prefix rather than a complete file.
Other candidates require short terminal pages; 109/103 need multiple segments.
Only physically adjacent zero-padded streams join. Shared framing code preserves
all 995 previous 0DRP metadata outputs exactly, including its stricter endpoint
policy. Assembly/output budgets still apply, including string-chunk costs.
Native --start scan windows work directly at compressed offsets. End-to-end
8-MiB CLI discovery scan: 51 dictionaries / 523 links / 286 distinct clip paths,
3,304 metadata nodes, no refusals. Names and diagnostics stay in private output.

No GPL implementation/fixture, external decoder or title-specific table was
consulted or embedded. Existing frozen animation/PSIN/BCPack artifacts and
provisional labels are unchanged. Component/animation-record and opaque-buffer
associations are now supported below; curve quantization remains open.

### Clip component / animation / packed-buffer associations

The named kind-2 clip prefix references 24-byte group records at +0x68 using
an equal-u16/zero-tail array header. Each group references 56-byte segment rows
using the same restricted header profile; its final u32 is observed zero and
its other scalar bits remain candidates. Segments reference bounded 112-byte
animation prefixes. The segment key matches the stem JOOAT of the animation's
referenced exact ASCII/NUL pack:/...anim name. Other segment references, timing
words, class tags and animation header roles remain unknown.

The animation prefix's +0x50 array references opaque buffer headers. Their
observed extent is 32 bytes plus the stored u32 at +4, with a zero u32 at +8.
The animation word at +0x48 matches the maximum referenced buffer span, not a
sum. No boundaries are guessed from neighboring addresses or silently padded.
Native output contains exact span/reference/header bits and SHA-256, not
buffer bytes or decoded curves. Array, string, prefix and full-width virtual
reference bounds are all enforced. Aliases/order remain separate observations.
Failures keep a reason and no partial component prefix; independently bound
clip names remain available after component failures in a parsed dictionary.
Framing/node-limit failures discard the whole dictionary output.

Discovery 191 dictionaries: 1,277 clip views / 3,794 animation links / 4,956
buffer references. Frozen validation 170 dictionaries: 1,432 / 3,946 / 5,617,
no failures and no validation-driven profile changes. There are 879/908
distinct buffer-content hashes, zero cross-role overlap. All source observations
round-trip; all 7,740 wrong-endian and full-path-name controls discriminate;
summed lengths fail all 1,872 multi-buffer controls. Reused cohorts establish
structural consistency, not independent semantic or curve-decoder confirmation.

Deeper reads extend 17/19 naming prefixes to include required adjacent buffer
bytes. Default named-clip outputs remain identical to the prior baselines;
0DRP framing, PSIN runtime and all frozen splits/tables/provisional labels are
unchanged. Shared limits also charge strings and buffer-hash work; hashing
aliases can reuse a per-dictionary digest while every observation stays charged.
Native 8-MiB CLI discovery check resolves 523 clip views / 1,556 animation links /
2,313 buffer spans with 17,922 nodes, no failures. No game fixture, GPL source/
table or external decoder was used. Bounded packed-header and raw channel
metadata is now supported below; timing, codec and bone/track roles stay unknown.

### Packed animation headers and channel-layout candidates

The observed packed profile has a 32-byte LE header with u16 marker 2 at +0x14
and byte marker 11 at +0x1e; no version/codec meaning is confirmed. Relative
offsets at +0x0c/+0x10 partition the buffer into header, section_0, section_1
and an auxiliary tail. They must be ordered within the independently bounded
buffer. No arbitrary alignment, scalar encoding or compressed section role is
assumed. Other header words remain raw, including the first u32: no checksum
algorithm is claimed.

The high/low nibbles of byte +0x1f sum to the number of six-byte tail rows;
their u8/u8/u16/u16 fields and order are retained without codec/channel/axis
assignment or a claimed split between nibble groups. A checked animation-prefix
array at +0x60 supplies candidate channel bindings: count * 12-byte raw rows,
three u32 words each. IDs/type-like words remain unknown. This does not map
individual compressed bits to bones or channels.

Animation +0x24/+0x26 and buffer +0x16 define an inferred sample-index layout:
nonfinal chunks have step+1 samples; adjacent chunks overlap one sample, and
all counts reconcile to the stored animation total. The final chunk fits the
step bound. No frame values, sample rate, duration or timing units are decoded.
Every emitted bit/span/row is bounded; failures return no prefix layout rows
and retain reasons, with parsed opaque-buffer associations independent.
The opt-in --packed-layout implies component/named modes, shares output limits
and leaves previous modes unchanged. Overall resource status stays partial.

Frozen discovery/validation: 3,794/3,946 animation layouts and 4,956/5,617 buffer
layouts pass, yielding 223,879/236,886 raw binding observations and 11,030/16,423
auxiliary rows. All source fields/partitions round-trip; no-overlap controls
fail all 1,872 multi-buffer cases, reversed counts discriminate 1,775 cases.
No validation-driven fitting, split changes or promoted inputs. Reused cohorts
are structural consistency evidence, not independent semantic confirmation.
All previous component-mode outputs remain identical; PSIN/BCPack artifacts,
0DRP framing and provisional labels remain unchanged. No GPL code/table/fixture
or external decoder consulted. Next: prove channel/codec/compressed-section
relationships before implementing values or keyframe quantization.

### Packed animation slot directories

`anim --channel-layout` adds an optional bounded suffix view without changing
prior packed output. The suffix starts with eleven u16 counts, then eleven
increasing slot-index groups padded to four with sentinel `4 * binding_count`.
A unique candidate must account for the entire suffix; duplicate candidates,
bad counts, active ranges/order and padding refuse with empty groups. The
arithmetic binding/sub-index association is exported; group meanings, channel
IDs, codecs, samples and preceding bytes remain unknown. Cross-group repeats
occur in 705/879 discovery and 715/908 validation distinct buffers, so groups
are not assumed to be exclusive codec assignments.

Frozen-profile results: 879/908 distinct buffers, 153,264/161,382 active slot
observations; all 4,956/5,617 alias views resolve. Zero content-hash overlap.
All 1,787 malformed-count and 1,787 bad-padding controls refuse. Previous packed
views compare exactly. Validation rules were not changed; cohorts had prior
structural exposure and do not supply independent semantic confirmation.
Output shares the node budget; candidate search is separately capped at 64 KiB.

### Enum-record array links

The nonempty enum32-array profile requires one exact local synthetic descriptor
and local LENM definition, equal u16 header words/zero tail, and a whole bounded
span in a unique local four-byte row schema. That schema has one named enum32
field at zero with the same enum hash. Every selected word must match LENM
before source-ordered links escape. Empty/untyped/ambiguous/imported layouts
refuse. Values and signed/alias annotations remain in their already decoded
rows, with no duplicated scalar output or global low-ID pool interpretation.

Frozen discovery/supplementary validation adds 41 arrays/260 links (19/27, 22/233).
All 2,142,630 previous values, 110,056 arrays, 196,274 reference fields and 19,117
previous maps remain unchanged; three pre-existing budget refusals persist.
All 41 bad-member and 41 misaligned-offset controls refuse. Wrong-endian controls
discriminate 244/260 words, with 16 nondiscriminatory cases. The initial raw-storage
hypothesis was rejected before implementation after checking target authority.
Existing source splits, registry and BCPack labels are unchanged; reused-source
structural regression supplies no independent semantic oracle.

### Enum-key map-entry extension

A separate nonempty enum32-key/local-structure map profile requires an exact
local key descriptor, one representable local LENM definition and membership
of every stored key. The target entry schema must match key/value descriptors
exactly; declared offsets and whole-stride spans remain authoritative. Unknown
keys refuse before links escape. Empty enum maps remain unsupported. Hash32
map behavior and all existing typed values remain unchanged.

The frozen extension adds 61 maps/182 links: 2/9 discovery, 59/173 supplementary
validation. 136 links target still-partial records. All 61 bad-key controls
refuse. All 2,142,630 earlier values, 110,056 array associations, 196,274 reference
fields and 19,056 previous maps are preserved. The same three pre-existing
250,000-node source budget refusals persist, with none added. There are 17 other
unsupported discovery maps. No registry borrowing, validation promotion or
semantic-oracle accuracy claim; all key checks use local authority.

### Packed-animation storage rows

`anim --storage-layout` adds a bounded byte-storage view. The exact directory
start is `32 + raw_u32_0c + row_count * row_stride`; count/stride come from
u16 words at +0x16/+0x18. This refines the earlier raw-offset partition by
using the end of the 32-byte header as origin. Prior generic packed/channel
views remain unchanged. Five regions account for the entire buffer: header,
body prefix, opaque fixed-stride sample rows, slot directory and auxiliary tail.

For raw u16+0x1a zero, stride equals four times ceil(u16+0x1c/32), and every
high padding bit is zero. Other +0x1a values retain unknown bit grammar with
bounded rows. There are no decoded floats, quantization, codec IDs, channel
meanings or time units. Base-profile failures yield no prefix regions.

Frozen discovery/validation: 879/908 distinct buffers, all 4,956/5,617 alias
views partition; conditional bit rows resolve in 496/497 distinct buffers,
with 383/411 opaque grammars. Wrong-origin controls refuse all 879/908 cases;
applicable bad-padding controls refuse all 443/442. Prior outputs compare
exactly for 3,794/3,946 animation views; source memberships/hashes and splits
are unchanged. These reused cohorts provide structural regression, not semantic
confirmation. Native eight-MiB discovery CLI: 857 storage views/451,610 aliased
sample rows, zero base-profile failures and 241 unknown bit grammars.

### Counted animation width tables and raw bit rows

`anim --bit-layout` adds a separate optional view over checked storage. A
12-byte fixed-width table is located by directory counts; its widths sum to
raw u16_1c. Variable records have five-word headers plus a counted opaque word
payload; their count and total extent must agree with directory group 5 and
4 * raw u16_1a. Summed fixed/variable widths reproduce the rounded row stride and
zero high padding. Whole raw rows and table bits/spans are retained, without
assigning per-channel offsets, numeric types, quantizers, poses or codecs.

The frozen 879/908 distinct buffers all resolve, including 383/411 previously
unknown nonzero-table cases; aliases remain 4,956/5,617 views. Discovery/validation
expose 38,733/44,669 fixed records, 2,274/2,327 variable records and 241,126/253,666
nonempty raw rows. Zero-stride buffers emit no invented rows. All 7,740 previous
packed/channel/storage comparisons agree. All 10,313 malformed controls refuse;
1,724 row-reorder controls intentionally pass, so row order/semantic accuracy
is not proven. No source promotion or validation-driven rule change occurred;
these are reused structural cohorts, with zero cross-role buffer-hash overlap.
A native discovery CLI check resolves 70 buffer views, including eight nonzero cases.

### Source-order indexed animation payload candidates

`anim --lookup-candidates` inspects a bounded candidate partition after the
opaque fixed-width prefix. Candidate indices must densely cover zero through
their observed maximum; a separate packed-entry width must explain the exact
word allocation and zero high padding. Raw candidate entry bits/spans and
index-sequence hashes are retained, without numeric/sample decoding or slot
assignment. Alternative bit origins/orderings also pass on some discovery
buffers; observed counts do not prove codebook cardinality or uniqueness.

Discovery/validation accept 383/411 distinct nonzero-variable buffers, with
2,274/2,327 candidate records, 78,068/82,036 raw entries and 546,544/517,797 index
observations. The 496/497 zero-variable buffers retain explicit out-of-profile
reasons. All 7,740 earlier parent-view comparisons agree. All 2,358 malformed
controls refuse; 794 row swaps intentionally pass. The unchanged profile was
sealed before validation; no channel/lane/quantizer/codec meaning is inferred.
A native frozen-discovery CLI check emits 15 candidate views from five clips.

### Mixed animation prefix storage

`anim --prefix-layout` bounds raw leading triplet/word groupings against the
independently checked width-table origin and parses a stored count of trailing
length-prefixed opaque records. Record word lengths must exhaust the exact
pre-row remainder. Combined group-0/group-1 triplets stay unassigned; group-7/8
counts have no separate byte or semantic interpretation. Bodies remain hashes
and spans, not decoded samples or codecs. Existing views are unchanged.

All 879/908 discovery/validation buffers pass, yielding 215,213 raw words and
72,751 opaque records across distinct buffers. Discovery has 629 nonempty / 250 empty
remainders; validation 678/230. All 7,740 old full parent views match. All 5,708
malformed controls refuse; 1,141 triplet swaps and 1,307 opaque-body mutations
intentionally pass. Native frozen-discovery CLI checks 70 views without failures.
Runtime/tests/audit were frozen before validation, with no fitted role changes.

### Counted animation-record body investigation

The follow-up used only the 879 discovery buffers, with original source pages,
hashes, aliases and 3,794 prior parent views rechecked. Their 36,365 counted
records contain 8,518,656 opaque body bytes. A proposed eight-entry sorted
offset table fails 16,490 nonvacuous cases; two candidate fixed-extent formulas
fail 36,097 and 31,046 cases. A low-bit zero correlation alone does not establish
widths, field roles, stream origin or a channel layout.

No inner-body grammar, runtime parser or CLI flag was added. The 908 validation
buffers were not read for this investigation. Eight authored probe tests check
the measurements and counterexamples; they do not establish decoder accuracy.
An independent stored count/extent constraint or controlled known samples are
needed before spending the holdout on a concrete grammar.

### Narrow raw animation payload inventory

`anim --payload-layout` adds source-ordered twelve-byte records with three raw
LE words and a separate list of same-ordinal slot candidates. The supported
profile requires only group zero, one sub-index-zero slot per binding, no
stored sample rows/auxiliary bytes, and prefix length 12 times the group count.
It does not decode constants, floats, transforms, samples or codecs. Candidate
slot associations remain unconfirmed; swapping records still passes structural
checks and is explicitly not semantic-order validation.

Frozen discovery/validation support 12/879 and 9/908 distinct buffers (26/4,956
and 12/5,617 alias views), with 456/342 distinct-buffer raw records. Other layouts
refuse with empty inventories while parent metadata survives. All previous
3,794/3,946 parent animation views compare exactly. Source memberships/hashes
and frozen cohorts are unchanged. Broader group-zero-first association guesses
agree for only 1,154/2,651 repeated observations, so were not generalized.

### Native MoVE envelopes

`move` browses raw files and checked archive pages. The version-word-19 profile
contains two counted u32 tables, one counted five-byte (u32,u8) table, raw
control/prelude fields and opaque payload metadata. Whole-region partitions,
counts and the redundant total-length equation must agree before emission.
Rows and regions share the output budget; input is capped at 16 MiB. Status remains
partial: names, references, motion, pose and timing semantics are unknown.
Unsupported headers/counts/framing produce reasons without prefix tables.

Before grammar inspection, 324 candidates outside every original animation
validation interval were content-hash grouped into 212 discovery and 112
validation resources. Zero cross-role content-hash overlap; prior full-archive
index exposure is recorded. All 212/112 envelopes pass unchanged after the
profile freeze, yielding 822/408 ordinary word rows and 170/102 tagged rows.
One validation resource joins two pages; raw/scan metadata agrees for all 324.
All 1,620 corruption controls refuse. These prove a bounded envelope profile,
not independently confirmed motion/object decoding. Existing splits unchanged.

### MoVE root storage

`move --objects` adds independent object_layout metadata while preserving default
envelope output. Root kind 1 has bounded immediate field-relative offsets; child
headers repeat each reference hash/ordinal. Root kind 22 has ordered, bounded
length-prefixed descriptors, four groups of raw 16-/8-byte cells, and counted
u16-length subblocks. Source spans, count/length redundancies and region bounds
are checked. Child bodies and tails stay opaque; no recursive motion tree or
numeric/pose/timing meaning is inferred. Unsupported deeper profiles retain
empty lists and reasons with independently parsed envelope metadata.

All 212/112 frozen resources pass unchanged: 44/19 immediate-reference roots
provide 122/57 targets; 168/93 descriptor roots provide 186/102 records, 536/284
fixed cells and 16/5 subblocks. All 324 raw/scan and old-envelope comparisons agree.
All 1,884 structural controls refuse. Opaque mutations 324/324 deliberately remain
undetected. Recursive interpretation failed 25 discovery resources and was not
enabled. A reporting-offset fix was recorded with preserved v1/v2 freezes and
unchanged grammar/counts; it does not adapt rules to held-out motion data.

### One additional MoVE child-prefix level

`move --children` implies objects and splits the two header bytes at +18/+19
into bounded row/extension counts in observed child forms. Declared extension
lengths agree with independent table extents. Supported reference prefixes
also verify immediate target hashes/ordinals. It follows one additional level;
extension bodies, grandchildren and other tails remain opaque. No arbitrary
recursive graph, numeric/pose values or timing semantics are inferred.

Frozen discovery supports 175/290 candidates, validation 91/150; 174 unknowns keep
reasons and empty deeper rows, including an unfitted short held-out prefix.
The layer adds 138 extensions, 387 references, 376 descriptors, 685 raw cells and
193 subblocks. All 324 old-parent/raw-scan comparisons agree. All 1,362 structural
controls refuse; 266 opaque mutations intentionally remain undetected. Supported
siblings remain available when others are unknown. Partial requested child
inspection exits nonzero without discarding independent parent metadata.

### Additional MoVE tail storage

`move --tail-forms` preserves existing child/object views and adds bounded
kind-3 reference/record storage plus a measured kind-12 profile. Kind-3 checks
selected/tail pointers, counted rows and repeated target hashes/ordinals;
its 56 forms retain 146 references / 50 counted opaque records.

Kind-12 checks a 52-byte header, exactly five counted groups and at most one
selector word per group. Every used two-bit selector equals two; unused bits
are zero. Whole eight-byte cells and the terminal extent or opaque-tail prefix
must fit. It adds 18 discovery / 6 validation forms, 120 groups, 18 selectors
and 96 opaque cells. The discovery header variant 0x1155 and held-out 0x115a
remain refused; no validation observation extended the frozen whitelist.

Combined immediate coverage is 346/440, with 94 explicit unknowns; 230/324
resources have all immediate storage candidates described. All 324 previous
parent-mode/raw-archive comparisons and all 56 kind-3 form dictionaries agree.
All 104 new malformed controls refuse; 11 opaque-cell and 11 opaque-tail controls
remain undetected intentionally. The earlier kind-3 audit refused 644 controls.
The same 212/112 source split is unchanged. Before validation, a discovery-only
audit correction distinguished kind-12 attempts from successes when comparing
old tail views; both historical and corrected seals are retained. Runtime/tests
were unchanged. Raw cells, target bodies and tail meanings remain opaque;
no motion, timing or recursive graph interpretation is claimed.

### Measured MoVE kind-11 selector headers

The existing `--tail-forms` view also supports a discovery-observed whitelist
of nine kind-11 selector words. Their raw bit fields determine bounded
44/48/52-byte prefixes, with checked zero/sparse slots and an exact terminal
extent or next opaque-header ordinal. Original header bits and ten two-bit
fields are retained; no scalar/channel/motion semantics are assigned.

Discovery adds 22 forms, validation 8; two unseen held-out selector profiles
stay refused. New metadata totals 300 raw selector fields/1,412 prefix bytes.
Combined immediate coverage is 376/440 with 64 unknowns; 260/324 resources have
all immediate storage candidates described. All 324 old parent/raw-archive
comparisons and 80 prior kind-3/kind-12 form dictionaries agree. All 104 new
malformed controls refuse; 54 opaque mutations intentionally pass. Runtime,
tests and audit were frozen before validation, with no whitelist extension.

### Measured MoVE kind-28 selector headers

Seven complete discovery-observed selector words select measured 32..64-byte
prefixes under `--tail-forms`. Exact terminal extents or an opaque next-header
ordinal, plus zero/repeated-word constraints, validate storage only. Individual
field widths are not independently determined in some combined cases; no
per-field width formula, pointer traversal or numeric meaning is implemented.

Discovery adds eight forms, validation three, leaving other kind-28 variants refused.
New metadata totals 176 raw selector fields / 468 prefix bytes. Immediate coverage
becomes 387/440 with 53 unknowns; 271/324 resources have all immediate candidates
supported. All 110 earlier complete forms and 324 parent/raw-archive comparisons
agree. All 26 malformed and 11 budget controls refuse; 12 opaque mutations remain
accepted intentionally. No frozen whitelist was extended from validation.

### Measured MoVE kind-4 header prefixes

Five discovery-observed whole profile words select bounded 36/40/44-byte
prefixes. A marker equality, measured zero slots and an independent next-header
ordinal witness constrain the boundary. Individual profile bits, raw parameter
words and the remainder stay uninterpreted. Bounds alone did not prove two
possible pointer words, so no pointer targets or graph edges are emitted.

The unchanged 212/112 split adds six discovery and three validation forms,
364 prefix bytes and zero selector fields. Coverage reached 396/440 immediate
candidates, with 44 unknowns; 280/324 resources have every immediate candidate
described. All 121 prior form dictionaries and 324 parent/raw-archive comparisons
agree. All 47 malformed and nine under-budget controls refuse; 36 opaque
parameter/body mutations intentionally pass. Runtime, authored tests and audit
were frozen before validation; no held-out profile enlarged the whitelist.

### Extended kind-12 counted storage

One discovery header word `0x1155` selects a measured 60-byte header and the
existing independently counted five-group grammar: two selector words, ten
opaque eight-byte cells and a required next-ordinal witness. The header's raw
word positions differ from the 52-byte profile. An initial discovery-only audit
safely refused the case because it reused the old zero slots; those slots,
fixtures and audit were corrected before validation, and the preliminary seal
was retained. No selector, pointer, scalar or motion meaning was inferred.

Current immediate coverage is 397/440 with 43 unknowns (23 discovery / 20
validation); 281/324 resources have every immediate candidate described. All
130 earlier form dictionaries and 324 parent/raw-archive checks match. All
13 malformed plus one budget control refuse; two opaque mutations deliberately
pass. Validation contains no eligible extended-header examples and all 112
earlier full views remain exact; the prior-only `0x115a` stays refused. Kind9/15
storage roles remain unproven. A repeated span within the same discovery source
is a correlated witness, not another independent sample.

### Native RBF0 structural browser

`rbf` reads raw files and checked contiguous archive pages into a bounded flat
indexed tree. The observed profile carries reusable name descriptors, object
attributes/children, inline text, opaque bytes and raw eight-byte values. Token
kinds outside this profile, unknown or mismatched descriptors, malformed text,
nonzero reserved object words, unbalanced/truncated trees and trailing bytes
refuse the whole candidate. Input/node/text/depth budgets apply; nesting is
capped at 128. Names and raw kinds do not prove application semantics.

The eligible animation discovery resource joins 21 pages/1,348,436 bytes and
consumes exactly: 56,796 tokens plus nine descriptors, 28,962 objects, 1,126
inline text values, 20,031 byte leaves and 6,677 raw64 values. Its observed
rig-set manager hierarchy contains 1,126 top-level and 6,677 entry items.
Only one eligible container exists; full-container grammar discovery supplies
no independent held-out accuracy. Existing animation validation windows and
all other frozen artifacts remain unchanged. No GPL implementation or upstream
game-decoder source was consulted.

### Literal RBF rig-set inventory

`rbf --rig-sets` adds a separately validated candidate view over the generic
tree: 1,126 key rows (56 empty), 6,677 entry rows, 3,669 exact Rig strings,
zero duplicate source keys. Dictionary/Rig/Group fields retain literal labels
and text; Priority is eight raw bytes without numeric or runtime meaning.
Source node identities retain duplicate/aliased occurrences, and the reverse
index maps each exact Rig string to its source entries. `--name` is literal
case-sensitive key-substring matching; `--rig` uses exact text. Whole-tree
ownership, ordering, descriptors, bounds and field correspondence are validated
before any filter. Unsupported profiles preserve the generic tree and return
no normalized prefix.

All 1,126 keys, 20,031 text fields and 6,677 Priority fields round-trip against
source bytes. All 6,677 reverse occurrences agree; 14 malformed controls and
one under-budget control refuse. Combined generic/normalized output uses
74,955 nodes. One discovery container was already exposed; there is no
independent holdout or runtime rig-schema claim. No source split changed.

### DXBC shader wrappers

`shaders.rpf` stores shaders as
`[u8 name_len+1][name][0x00][u8 name_len][u32 stored][magic 0x000DDCE7][u32 stored][u32 decoded][raw deflate]`.
The payload is a DXBC container with printable chunk tags (`SFI0`, `ISG1`,
`OSG1`, `PSV0`, `HASH`, `DXIL`, `PRIV` in sampled shaders). 9,089 wrappers pass
both the length and DXBC structure checks in the first 64 MiB.

### Local texture-name recovery

A bounded source-string search inspected 6,604,023,168 bytes of disjoint
eligible source windows across 17 archives, excluding existing validation
sources. The lookup target was only the metadata hash tables from all 57 TTPF
pools; no TTPF texture payload was decoded or used for fitting. Candidate rules
were fixed before the initial scan: bounded ASCII/ASCII-range UTF-16LE strings,
contiguous identifier/path substrings, known texture-file stems, and exact or
lowercase spelling. No guessed prefixes/suffixes, hash seeds or external names.
Additional source windows were assigned before reading their contents; the
same extraction rule remained unchanged. Native descriptor-only follow-up
retains only candidate system pages, without image interpretation.

The private dictionary gains 117 previously unresolved hashes across nine
pools: 107 names occur exactly in bounded embedded texture-name fields and ten
come from other observed strings. All 683 retained source observations were
reread, including existing-name evidence; all 117 new values independently
match their original TTPF hash-table bytes. Wrong-endian, wrong-seed and appended-
NUL controls discriminate all 117. These are hash/source agreements, not an
independent asset-binding or texture-image oracle.

Named streamed records increase from 671 to 788; the first 200 default rows
remain 112 named and 88 unresolved. Under the unchanged pool roles, training
coverage is 491→505 and validation coverage 180→283. These are lookup counts,
not learned-decoder or held-out semantic accuracy. All prior dictionary entries,
source labels, bucket order and 32-bit indexes persist. All 75 inherited frozen
artifacts, runtime modules and BCPack provisional labels are unchanged.
The search is not exhaustive: protected sources, unsupported encodings,
oversized/cross-window streams and non-descriptor regions in metadata-only
passes remain outside its coverage. Private names, observations, backups and
hash/count reports remain under ignored names.json/work paths. Eleven authored
scan/merge tests and native dictionary/texture CLI checks pass; no code or
tables from another decoder were consulted.

### Public shader metadata

`shaders --metadata` now reads bounded public DXIL/SHDR/SHEX stage/model
headers and ISG1/OSG1/PSG1 signature records. It preserves semantic strings,
indices, streams, registers, component masks and numeric enums. Unknown chunks
remain opaque inventories; legacy signature versions are explicitly unsupported.
Shared record limits refuse atomically, while one malformed known chunk retains
other independent views and valid `.cso` extraction. No instruction, resource
binding, integrity-digest or game-shader semantic decoder was added.

The public reference is LLVM's
[DirectX Container specification](https://llvm.org/docs/DirectX/DXContainer.html)
and Microsoft serialized format declarations. Previously indexed shader source
windows were assigned before content inspection, with the implementation sealed
before validation. Discovery/validation: 742/380 wrappers, 727/374 unique hashes,
zero cross-role overlap; 4,012/3,645 signature records round-trip. All 1,122 old
extraction results persist. Program-length, signature-count, name-offset and
truncation controls reject 4,488 damaged views; 1,122 budget controls refuse.
Every measured declared DXIL span has non-LLVM contents and stays opaque and
unverified. SHDR/SHEX and PSG1 have authored coverage only. These are structural
consistency checks, not independent reflection or runtime accuracy evidence.

### Exact-extent PSIN enum bitsets

The native instance reader now accepts a narrow local `0x65`/`0x68` profile:
one local owner and enum, dense LENM indices matching the stored bit count,
aligned rounded storage exactly reaching the next field/owner boundary, known
nonoverlapping preceding extents, and zero unused high bits. Original bits,
unsigned decimal, set indices and aliases survive; positions/annotations remain
inferred. Gapped/sparse/imported/ambiguous profiles and `0x63` stay unresolved.

Frozen discovery/comparison/script results add 297/6/0 values across 53/1/0
resources in the 821/223/1,012 cohorts. All 1,069,517 previous leaves and
1,940,736 other field/link/pool views remain identical, with no resource refusals
or validation-driven rule changes. All 303 additions byte-round-trip. The
comparison provides six `0x65` values from one source and no `0x68` example.
Literal enum-mask alternatives contradict 135 discovery and three comparison
observations; wrong-endian padding discriminates 82 discovery cases and is
inconclusive for 215 discovery plus all six comparison cases. This supports an
inferred convention, not confirmed flag semantics or an independent oracle.

### Packed animation body constraints

Discovery-only follow-up on all 879 hash-verified buffers examines 36,365
counted records. Variable-count monotone-code tables, nine-word-per-count
trailers and parent-row-width assignments have concrete counterexamples.
The stronger exact-extent/order/padding proposal has no candidate in 35,613
records and one candidate in 96; 634 zero-width and 22 work-limit cases are
excluded explicitly. A surviving arithmetic candidate is not a supported
grammar. Runtime readers and all 908 validation buffers remain unchanged by
this follow-up. Independent counts/entry boundaries or controlled samples are
needed before decoding these bodies. Private reproducible provenance and
hash/count reports remain under ignored docs/tools/work paths.

### Embedded txd descriptors

A system page contains 0x70-byte texture structs: `u16 8` at +0x0E, a graphics
pointer `0x6xxxxxxx` at +0x18, width/height/depth at +0x38/+0x3A/+0x3C, DXGI
format at +0x3F, mip count at +0x42, and a name pointer `0x5xxxxxxx` at +0x30.
Graphics pages follow the system stream at 16-byte boundaries with zero padding.
Descriptor +0x08 counts allocated format elements, including padding; +0x40
holds swizzle mode 5 (S4K) in the measured resources. Reading the complete
allocations recovers two dictionaries missed by the former mip-0-size heuristic.

BCn 2D resources match the public Gfx10 S4K macroblock/tail rules: hardware
element dimensions are ceil-shifted, non-tail levels are padded to 4 KiB blocks
and stored smallest-first, and up to eight small levels share one tail block.
Single-level resources start at zero without a tail. DDS uses logical pixel
dimensions and crops hardware padding. The public source consulted was AMD's
[MIT-licensed AddrLib](https://github.com/GPUOpen-Drivers/pal/blob/dev/src/core/imported/addrlib/src/gfx10/gfx10addrlib.cpp),
not a game decoder. Existing pool-layout defaults are unchanged.

All 31 mipmapped 2D textures in textures.rpf match their declared allocation
footprints and export all 253 levels (144 tail levels). Authored byte-address
vectors independently test tail slots, leading levels, portrait and NPOT
cropping. All 141 real adjacent-level RGB comparisons beat a deliberately
wrong zero-origin control (median MAE 4.217 vs 51.104). Image consistency is
not independent byte-level ground truth; an earlier comparison to the former
addressing won 92/95 tail comparisons in the original 22-texture subset, with
three ambiguous NPOT blank-image comparisons. No decoder oracle was used.
Bounds checks refuse truncated allocations and mismatched footprints rather
than filling missing elements with zero. BCPack data and holdouts are unchanged.

### Explicit texture subresources and standard DDS serialization

PNG export now accepts mip, array/cube-slice and volume-Z selectors in both
streamed and embedded native paths. Defaults retain mip/slice/Z zero; streamed
volumes newly gain a plane-zero preview. Nondefault filenames identify all
three indices, and manifests record selected dimensions. Out-of-range explicit
requests preserve valid DDS output, record the preview failure and exit nonzero.
Full allocations remain mandatory, and a missing logical grid is never padded.

Public Microsoft DDS rules corrected existing output: array/face-major complete
mip chains, cube counts in DX10 arraySize, full BC first-mip linear size and
the complex flag for mipmapped surfaces. These intentionally change affected
DDS headers/order, including embedded headers shared with the writer; they do
not change Gfx10 placement or stored component/BCn values. Earlier DDS-hash
parity reports refer to the implementation at those milestones.

Frozen discovery/validation checks cover 13 streamed and three embedded
selections. All 16 raw spans match prior-layout extraction and all 16 wrong-
selection controls discriminate. All 48 invalid-selector and 16 allocation-
truncation controls refuse; 13 streamed preview failures retain valid DDS.
Eleven prior streamed default PNG files/manifests and three embedded default
views remain exact. Nine streamed/two embedded header repairs and seven array/
cube order changes are expected. Two previous volume DDS files remain exact.
The 357,115-descriptor census has no logical-grid refusal; authored NPOT inputs
exercise that guard. Native commands verify a cube mip1/slice5 and volume Z31.

### Packed and 32-bit float previews

Public-format numeric conversion now supports DXGI2 RGBA32_FLOAT, 26
R11G11B10_FLOAT and 41 R32_FLOAT. Raw values follow the existing explicit clipped
display convention: finite [0,1] to RGBA8 nearest/half-up, NaN/-infinity to zero,
positive infinity to 255. R11/G11/B10 are unsigned components with separate
five-bit exponents and 6/6/5 fraction bits; opaque alpha is supplied for RGB/R,
while RGBA retains its converted alpha. DDS component bits remain intact.

Nine authored tests cover every packed component encoding, float32 rounding
boundaries, subnormals/special values, channel order and short spans. All 73
earlier sampled PNG hashes are exact. None of the three new formats occurs in
the streamed 357,115 or embedded 3,167 descriptor censuses; this support has
authored public-standard validation only, without a natural-image accuracy
claim. No new game-decoder implementation was consulted.

### Public DXGI precision previews and corrected raw formats

PNG conversion now covers DXGI10/11/24/34/54/56: RGBA16 float/UNORM,
R10G10B10A2 UNORM, RG16 float, R16 float and R16 UNORM. Normalized integers
scale to RGBA8 with nearest/half-up rounding. Raw half values are clipped
numerically to [0,1], with NaN/-infinity mapped to zero and +infinity to 255;
no exposure/gamma or game-shader meaning is inferred. Manifests describe this
with `png_conversion`. Every DDS format and source component bit is retained.

Public DXGI enumeration also corrected reversed signed IDs: SNORM31/51/63 and
SINT32/52/64 for RGBA/RG/R. BGRX88/93 forces opaque alpha, while BGRA preserves
alpha and now refuses short input rather than padding. Corrected signed/BGRX
PNG differences were declared before validation; other outputs remain exact.

All 357,115 streamed layouts are now supported, including five format11
textures (four discovery / one validation), each exported as DDS+PNG. Complete
stored/zlib coverage is 305,959. Bounded regression samples preserve 72 DDS and
65 PNG hashes; 12 new previews match 3,953 reference pixels. Real selected formats
are 10/11/24/54; 34/56 and signed/BGRX corrections use authored public vectors.
These are public-format/reused-source consistency checks, not an independent
image oracle. The implementation/tests/audit were frozen before validation;
the initial zero-pool discovery audit was retained and corrected before that
freeze. Embedded metadata remains 1,347 resources / 3,167 descriptors.

### Embedded BCn arrays

Descriptor byte +0x3e is retained as a shape tag: 1 for observed 2D/arrays, 3 for
volume-like resources. Tag 1 plus depth > 1 supplies a 2D array layer count; six
layers do not imply a cubemap. Each array layer uses a complete public non-XOR
S4K hardware chain, with its own tail. Native DDS retains every layer/mip;
PNG selects layer 0 and labels it. Preview failures preserve valid DDS output.

34 arrays (33 BC3 discovery, one BC7 validation) add 155 layers/169 subresources.
All 3,020 prior 2D full DDS hashes match. The resource-grouped shape split was frozen
before payload inspection and not rebalanced: five discovery resources and one validation
resource. The held-out two-layer/eight-mip array has 14 adjacent-level comparisons:
ten beat deliberately wrong level-major order, four tie, none are worse. Discovery
spatial controls improve 148/153 layers, with five worse; these content-dependent checks are
not independent byte ground truth. Cubemaps and non-BC arrays/chains remain
refused; single-mip volume support is described below. No oracle or upstream game-decoder implementation was consulted.

### Embedded single-mip volumes

Explicit shape 3, swizzle 5, uncompressed single-mip descriptors use the existing
public 3D S4K coordinate rules. Native DDS retains all depth planes with a 3D
header, correct depth/volume flags and array size one. Allocation footprints
must match exactly; full padding must exist even for a selected preview plane.
`volume_linear` returns x-fastest/y/z bytes; `volume_slice` selects an explicit
XY plane. Implicit 2D mip access and slice-only DDS mislabeling refuse.

All 113 measured volumes export: 110 RGBA16F 17³, two R10G10B10A2 and one RGBA8
32³. Totals: 1,966 planes, 638,734 voxels, 4,716,656 logical bytes. All 3,054
previous 2D/array DDS hashes are unchanged; all 3,167 observed descriptors now
export natively. All 339 truncated/size-change controls refuse. All 113 RGB
neighbor-continuity checks beat wrong linear storage (zero ties/worse), which
is content consistency rather than byte confirmation.

Both volume-bearing resources were already discovery and previously read in
array work; no independent volume holdout exists. The public algorithm/tests
were frozen before volume pixels were evaluated; no rule changed afterward.
BC/multi-mip volumes, unknown shapes/swizzles and non-BC arrays/chains remain
refused. Native PNG uses explicit Z=0 with png_z_index where format conversion
exists; missing preview support preserves the complete DDS.

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
* **Animation.** The archive/containers are indexed and named, and native 0DRP metadata
  spans are browsable with `anim --resources`; named record-prefix links are
  available with `--clip-records`, and bounded animation/buffer associations with
  `--clip-components`; `anim-clips.txt`
  lists `.clip` paths. Native component links now reach checked packed buffers,
  width tables, prefix storage and source-order lookup candidates. Channel/slot
  assignments, numeric samples, quantizers and keyframe curves remain undecoded.
* **Native model decoding.** Geometry is exported through the optional SixNG
  backend; no native mesh/meshlet decoder is included.
* **Embedded shapes.** Full BCn 2D/array chains and single-mip uncompressed
  volumes cover all 3,167 measured descriptors. Cubemaps, BC/multi-mip volumes,
  non-BC arrays/chains and other swizzles remain unvalidated and refused.
* **Texture layouts.** Cubemaps use six slice-major S4K faces: **567/567**
  export as six-face DDS; 127/127 2D arrays and 3/3 3D volumes are laid out
  natively. Gfx10 equations cover 1/2/4/8/16-byte elements and all measured
  layouts. PNG covers BC1-BC7, byte components and selected 16/32-bit/packed
  formats, with explicit mip/layer/Z selection. BC6H is tone-mapped and raw
  floats clipped. DDS preserves source values with corrected standard headers/order.
* **64-bit texture hashes.** Solved: low 64 bits of MurmurHash3 x64 128 (seed
  0) over the exact UTF-8 name. Initial algorithm checks used 19 real names
  (13 recovered + six embedded txd). The enriched local dictionary now names
  788 streamed records; recovered strings are not shipped. Remaining hash gaps are 128-bit `LSNS`/
  `LGID`, 29-bit audio ids and 15-bit surface ids.
* **Music record table.** The audio config holds **1,589** 46-byte music
  records, **1,589** distinct config ids and **272,442.8 s** total; `music`
  extracts duration/hash A/hash B/stream id. Optional external credit candidates
  match 673 records (seven ambiguous); native station links and play order remain
  unresolved. `music --config` separately browses bounded indexes/names/slots.
* **Audio decode.** Optional libopus supports standalone mono declared-duration
  or opt-in mono/stereo packet sequences, plus bounded music-channel PCM/WAV.
  Exact repeated music packets can be removed with an opt-in policy;
  unobserved skip sizes and XMA2 remain unsupported.
  Legacy Ogg stays the default; declared mode corrects granules for an explicit
  interval without confirming original alignment.
* **Shader semantics.** Optional native metadata reads bounded public program
  headers and signatures; there is no instruction disassembly, translation or
  inferred game-material binding.
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


## AWC radio metadata and interleaved stereo records

The supplied AWC notes were checked without external implementation source.
Descriptor byte 13 is channels-per-record (observed 1/2); sample counts and
subblock duration counters are interleaved. Corrected stereo duration and
zero-skip Ogg/WAV now use per-channel frames. Strict stereo remux validates
complete allocations, counters, packets and zero padding, with explicit encoded
bounds for long mixes. Legacy mono Ogg bytes and existing mono overlap profiles
remain intact. Nonzero stereo skips remain unsupported; pre-skip 312 and original
alignment are still assumptions. Native ACCUSE produces stereo 48 kHz WAV with
12,676,400 frames/channel (264.092 s); actual TRACKID is 1034.

`awc --radio` parses complete BD marker records, retaining unknown tag/value
bits and every TRACKID occurrence. `--chapters-out` writes exact-frame JSON and
a second-floored B2 text convention. Intervals are unclassified, not necessarily
songs. A3 tables require one ascending raw u32 per music block; units remain
unresolved. `--offset` addresses containers directly. `--max` now caps display
only; `--max-containers` caps processing. Optional supplied names require the
archive/offset/stream/channel tuple; shared contexts stay ambiguous and use the
fallback. No station map or native graph data is bundled.

The first parser was frozen before supplied Worldwide/Vault validation bytes:
41 intervals / 40 ids and 25 / 23 respectively. An offset-column-only native
consistency audit parses all 3,008 supplied locations, 3,116 descriptor records,
13,035 raw table entries, 938 marker banks and 1,042 TRACKID intervals. There are
905 single-interval banks / 828 distinct ids (1001–15102); all 905 have existing
low29/duration candidate joins within 0.001 s. These counts correct the supplied
notes and do not establish unique songs, full-name identity or native station
membership. An external locator list is not an independent archive census.

Post-validation review hardened stereo Ogg strict framing with authored
corruptions; the original sealed profile/reports remain local, and its successor
is rerun as reused regression. All 94 inherited frozen artifacts and the name
dictionary remain unchanged. The supplied `music.dat` attribution was retracted
after user correction; no native graph reader or rotation simulator was added.
See local `docs/awc_radio_format.md` and `docs/awc_radio_provenance.md`.


## Native TRACKID candidate joins and namespace conflicts

`music --trackids <awc-radio.json>` now builds a bounded candidate report from
the native marker metadata export. Raw marker words are rechecked; caller-supplied
chapter/title labels are ignored. A whole-channel observation requires exactly
one TRACKID at frame zero and a unique matching raw marker/channel id with the
same frame bound. Music-record candidates require low29 equality and rational
frame/duration agreement within one millisecond. No protected config layout was
fitted; the original fixed record reader and previous observations are reused.
Optional catalog contexts require complete 32-bit record hash B equality. Native
station membership remains unresolved, independent of credited station text.

The frozen candidate implementation rereads 3,008 supplied AWC metadata locations,
reproducing 1,042 intervals / 865 distinct IDs. Of 900 whole-channel observations,
823 IDs have record candidates, including 12 with conflicting hashes; 667 have
external credits, 663 without record-hash conflicts and 656 with one credit
context. Four full hashes associate with multiple IDs. For example, ID 2108 has
31 different candidate hashes and 3401 has nine; do not choose the first or a
majority. The supplied Worldwide example has record candidates for 32/41
intervals and external titles for 24/41; Vault remains 0/25. ID 1034 links locally
to raw channel 1AA8AC2F, candidate record hash DAA8AC2F and external Accuse credit.
These are candidate chains, not confirmed exact recordings or native playlists.

Controls: changing upper hash bits preserves native low29/duration candidates
but removes all external credits; wrong durations remove all record candidates;
changed raw channel ids remove all whole-channel associations. Marker corruption,
repeats, unmatched/duplicate channel ids, nonzero starts, source archive mismatch,
input/work limits and CLI overwrite/display behavior have authored tests.

Discovery-only probes of the five original strict-index resources and extended
family 581 find no ACCUSE full-hash/channel-id/float-TRACKID occurrences. Integer
1034 occurs in unrelated opaque fields and is not a reference. A wider exact
896-hash probe finds nine raw occurrences, including an index-name equality for
one hash, but no validated station/track reference encoding. No grammar or native
station edge is inferred from proximity/equality. Protected config bytes were
not used for fitting; prior discovery/validation roles, all 102 inherited frozen
artifacts and the name dictionary remain unchanged. Full package exposure means
all native checks are reused consistency, not fresh held-out semantic accuracy.
See `docs/radio_trackids_provenance.md`; private reports stay local and ignored.


## Native station-hash PSIN lead and Vault packet-reuse check

A bounded follow-up in `story000_script.rpf` preserves its original first-32-MiB
candidate discovery window, assigns the next 32 MiB to discovery and reserves
the final 10,914,176 bytes for validation before payload reads. No earlier
config, PSIN or AWC source is promoted. New discovery has 1,420 complete bounded
zlib pages / 44,469,912 inflated bytes; validation has 1,211 / 30,194,056. Neither
has complete matching ASCII/NUL radio literals. Thousands of raw integer/hash
query occurrences remain untyped, not station/track references.

One discovery page is a checksum-verified PSIN with five proposed Dirty South
Classics hash values in local-schema scalar hash32 fields: structure e6239fae,
field c91bff0d, record-relative +8. After freezing a generic schema-backed
classifier, the reserved tail has one Cocoteo FM hash candidate in the same
structure/field. The owner/field names, neighboring values and reference meanings
remain unknown. Schema type and exact-byte roundtrips support these six value
observations, not a native station definition or song-membership edge. A bounded
136-spelling field-name probe yields no matching preimage. Unknowns remain hashes.

A separate frozen exact-packet experiment uses the prior authenticated native
Vault remux as a reused validation query. All 25 intervals supply eight diverse
packets after the midpoint. Their length-prefixed first packets have zero
occurrences across 2,519 non-reserved stereo reference banks / 5,646,614,032
container bytes; no eight-packet reuse is found. This does not exclude re-encoded
or mixed audio, other points, other archives or excluded sources. Vault's 25
intervals / 23 IDs still have no title links. No playlist, public-credit ordering
or guessed duration pairing is substituted. Previous 12 candidate-ID conflicts
remain unchanged.

Research helpers validate role/window bounds, source identity, capped occurrence
positions, packet framing/diversity/exact sequences and complete local-schema
hash values. Nine authored tests were added; 956 tests (two optional skips) and
265 selftests pass. All 108 inherited frozen artifacts, previous runtime modules,
reports and names.json remain unchanged. No game bytes or extracted audio are
published. See `docs/radio_vault_provenance.md`; detailed reports remain ignored
under `work/radio_vault`. No commit or push.


## PSIN local bucket owners for the radio-hash field

Discovery-only tracing finds the five hash-bearing `e6239fae` records referenced
from a schema-framed bucket allocation. Exact local type-75 metadata selects
opaque type-1b4d keys and type-7 reference values. The 16-byte header selects 272-byte
bucket records: 16 control bytes plus sixteen local 16-byte key/reference entries.
Counts, low-seven-bit key/control witnesses, empty-slot storage, local schemas and
all target strides/bounds must agree; failed maps emit no entry prefix. This is
one contextual profile, not general primitive/key/lookup semantics.

`psin --bucket-maps` exposes owner paths, physical slots, opaque keys and existing
local target records. It checks LRSC independently and marks exact agreement with
its record candidate. The seed discovery owner `f4fc446b`, field `86c765cf`, selects
six entries: five query-hash records and a different sixth type. The frozen reader
accepts seven entries in the reserved resource, including its Cocoteo-hash record
and other record types. Three other map fields and one block remain unsupported
in each seed. Six count/control/late-reference corruption controls refuse without
partial entry lists. Duplicate storage/targets remain explicit; no first-match
selection, opaque-key decoding or pointer-chain expansion is added.

The frozen profile also applies across the existing script role windows. After
four initially incomplete starts are recovered using the unchanged native reader
in separate role-bounded windows, 28 discovery/seven validation complete resources
contain 47/seven queried record observations, all with traced container owners.
Their accepted bucket links total 171/57. Unknown values remain hashes, zero has
no assigned semantic meaning, and the heterogeneous lookup is not identified as
a playlist. Native song-to-station membership and Vault title links remain unknown.
All old candidate conflicts survive unchanged.

Schema/instance/ordinary record-graph defaults are exactly preserved in six native
before/after comparisons. The bucket view is separate and does not alter old graph
edges/reachability. All requested views share budgets; unresolved/partial bucket
inspection is explicit and exits nonzero. Eleven authored tests cover schemas,
counts, markers, late failures, duplicate storage/targets, ambiguity, aliases,
allocation bounds, shared budgets, CLI behavior and nested/cyclic owner paths.
967 tests (two optional skips) and 265 selftests pass. All 116 inherited frozen
artifacts and names.json are unchanged; no GPL implementation or game fixtures
were added. See `docs/radio_psin_owners_provenance.md`; audits remain local under
ignored `work/radio_owners`. No commit or push.


## Parallel metadata extensions: bucket values, auxiliary checkpoints and PSV0

Three isolated research tracks used only own code, public format facts and
eligible native bytes. No external decoder/oracle or GPL/unlicensed implementation
was read or copied; no game fixture/data is published. Old source roles/seals,
name dictionary, radio candidate conflicts and BCPack provisional labels remain.

Structure-valued local PSIN type75 buckets extend the prior reference profile
with exact 16/24/40-byte local value bounds. Discovery/validation yield 84/21
maps and 917/222 inline spans, while all 28/seven old reference dictionaries and
171/57 reference links remain exact. All 315 malformed-map and 35 budget controls
refuse. Inline spans are not standalone target rows; fields and nested pointers
remain undecoded. Opaque keys and duplicate spans survive. CLI/schema summaries
distinguish references from spans and explain unrepresented blocks/owner/depth
limits even if all inspected maps succeed. No song/station semantics follow.

Animation auxiliary selectors 0/1/2/4/5 redundantly select independently bounded
source record starts and stored row-bit offsets. Frozen discovery/validation:
879/908 buffers, 2,126/2,707 checked rows, 1,164/1,802 positive-width bit spans;
283/354 selector7/8 rows remain unsupported. Complete view counts include empty
tails. All 786/789 distinct earlier packed/prefix animation views remain exact;
2,805 malformed native controls refuse without checked prefix rows. The optional
`--aux-checkpoints` mode meters prerequisite work and preserves aliases, unknown
selectors, partial reasons and zero-width non-emission. Channel/bone/numeric/time
meanings and uncheckpointed order remain unknown. A 1-MiB discovery CLI check
has 70 views, 60 checked rows / three unsupported, no budget or supported-row
failures; a wider 8-MiB run preserves 16 explicit dictionary-budget refusals.

The MoVE kind9/15 thread found no independent grammar authority and enabled
no speculative runtime form. It moved to public PSV0 shader metadata, present
in all 742 discovery wrappers. The sealed reader accepts 742/380 runtime/resource
prefixes, exposing 7,505/7,510 register-binding records with exact source-word
roundtrips. All 1,122 previous extraction hashes and program/signature views are
unchanged. All 4,410 malformed and 1,122 under-budget controls refuse. Runtime
stage/thread/mesh data and public resource register ranges do not identify game
assets/materials or executable DXIL. PSV string/signature/mask suffixes and
entry-name offsets remain opaque/unresolved. Actual native versions are the
52-byte runtime / 24-byte binding profile; older/additive variants authored-only.

New source plans, per-agent seals, malformed controls and native reports remain
private under the parallel work directories. Provenance is in
`docs/psin_bucket_structures_provenance.md`, `docs/anim_auxiliary_provenance.md`
and `docs/shader_psv_provenance.md`. Root CLI tests cover parent dependencies,
partial/late failure, shared cross-archive budgets, inline/reference counts and
shader extraction preservation. No staging, commit or push in this round.


## Inline bucket fields, auxiliary boundaries and PSV signature tables

Three further isolated tracks preserve the existing source roles and all 133
inherited protected artifacts. They use own code, authored tests, public shader
format declarations and authorized native bytes; no GPL/unlicensed implementation,
external decoder source or game fixtures are added. Native checks reuse previously
exposed structural cohorts, not independent semantic ground truth.

`psin --bucket-values` implies bucket/header inspection and reads local fields
inside checked inline spans. Node/depth limits cover fields, structure-array
associations and nested type75 maps; targets are not expanded. Discovery/validation
in the same 28/seven resources produce 2,380/703 inline value observations,
2,228/675 checked fields and 2,275/669 explicit unresolved fields. Native supported
fields are enum32 values and bounded structure-array associations, yielding
306/102 record links. Of 152/28 nested-map attempts, 151/28 frame successfully
but retain partial values; one discovery empty map is refused. Counts include
repeated storage observations. All 35 default dictionaries remain exact and 140
array/enum/nested-map/budget controls refuse. Unknown field types and owner/key
semantics stay explicit; this does not establish station or playlist membership.

`anim --aux-checkpoints` now adds separate counted-prefix boundary/row-end cursor
metadata for selector7/8. Discovery/validation yield 283/354 pairs: 266/336
nonempty prefix starts and 17/18 empty-prefix boundaries. No source record, slot
or bit span is invented for these rows. The previous17 discovery failures remain
failures of a source-record claim; the new view checks only independently bounded
positions and an end cursor. All 1,911 origin/boundary/cursor controls refuse;
637 opaque-subindex controls preserve the view. All 1,787 previous auxiliary views
and 1,575 parent views remain exact after stripping new boundary metadata/counters.
Old unsupported selector rows, partial status, source-record counts and positive
bit spans are unchanged. Full channel/bone, sample, codec and timing meaning remains
unknown.

`shaders --psv-signatures` implies metadata inspection and reads public counted
string/index/signature tables, including bounded semantic and entry names. Default
metadata dictionaries and independent prefixes remain exact across all 742/380
wrappers. The cohorts yield 4,012/3,645 signature elements and 742/380 entry names;
5,610 malformed-table and 1,122 budget controls refuse. Native examples are
vertex/mesh 16-byte records. Dependency masks remain opaque hashed tails; raw
kind/type/interpolation values and additive bytes survive. A bad suffix preserves
the valid runtime/resource prefix and shader export, while requested metadata is
partial. This is not full reflection, executable verification or a game-resource
binding. Public string-padding prose differs from native declared sizes; the
reader honors checked declared extents and four-byte alignment, without claiming
a new general format revision.

Provenance is in `docs/psin_bucket_fields_provenance.md`,
`docs/anim_aux_boundaries_provenance.md` and
`docs/shader_psv_signatures_provenance.md`. Private seals, role reports and negative
controls remain ignored. Six additional command-level tests cover implied modes,
separate counts, shared report budgets, failed cursors and suffix/export isolation.
No staging, commit or push occurred.


## Contextual entry maps, checkpoint alternatives and PSV dependency grids

Three isolated follow-ups preserve all 143 inherited protected artifacts, existing
source roles, names.json and BCPack provisional labels. They use own code,
authored carriers, eligible native discovery bytes and public shader-format
facts. No GPL/unlicensed implementation, oracle source or game fixture is added.
The reserved evaluations reuse previously exposed structural cohorts; no blind
semantic ground-truth claim follows.

`psin --bucket-values` now matches an exact local type71 descriptor-tree profile
to whole declared 24-byte entry records. Across 28/seven discovery/reserved
resources, 152/28 contextual map fields include 49/25 null-empty maps and emit
301/three entry links. Empty maps have no fabricated target. All 35 default
bucket views and 2,903 previously complete value fields remain exact. There are
826 malformed header/allocation and 35 budget refusals; 106 opaque-entry mutations
intentionally preserve associations. Keys, type5c element widths/values and
lookup semantics remain unknown; the zero type75 bucket still refuses. These
links do not become ordinary graph edges or prove radio membership.

`anim --checkpoint-candidates` adds shared directory-slot sets conditional on
already checked source selector/subindex metadata. Discovery/reserved rows total
2,126/2,707, with 338/433 singleton-compatible and 1,788/2,274 ambiguous rows;
maximum alternatives 90/88. Even singleton rows remain unconfirmed and no slot
or channel is selected. All 1,787 earlier auxiliary views and 1,575 parent views
are preserved. All 1,787 underbudget and 935 bad-checkpoint controls refuse.
Swapping 1,801 distinct same-subindex source records preserves metadata; nine
all-equal controls are inconclusive. This exposes the limits of source ordering
checks rather than claiming a binding or sample decoder. Unsupported selectors,
partial statuses and boundary-only metadata remain unchanged.

`shaders --psv-masks` implies signature metadata and checks public packed
component dependency grids against exact suffix lengths. Discovery/reserved
have 147/17 nonempty vertex views, totaling 1,004/84 words and 2,115/289 set dependency
bits. The 595/363 empty mesh views are distinguished from nonempty coverage.
All 1,122 default and signature-only views remain exact. All 3,366 dimension/stage
and 1,122 budget controls refuse; 164 changed-mask-bit controls remain structurally
valid. Raw words, set components and unassigned padding bits are explicit.
Natural ViewID/pixel/geometry examples are absent; these have authored tests only.
Specialized stage masks stay unsupported. Mask failure preserves independent
signature/runtime views and exported shader bytes; no instruction behavior,
full reflection or native game-resource identity is established.

Provenance is in `docs/psin_inline_storage_provenance.md`,
`docs/anim_checkpoint_candidates_provenance.md` and
`docs/shader_psv_masks_provenance.md`. Seven command-level tests cover flag
implications, separate association counts, unknown selector preservation, shared
budgets, nested allocation failures and mask/export isolation. Native CLI checks
retain explicit partial PSIN/animation states and accept all 742 shader wrappers
in the exact discovery window. No staging, commit or push occurred.


## Opaque pool spans, SFI0 declarations and verified-overlap Ogg export

Three follow-ups preserve all 154 inherited protected artifacts, source roles,
name dictionary and BCPack provisional labels. Work uses own readers, authored
fixtures, authorized native discovery bytes and public shader/Opus format facts.
No GPL/unlicensed implementation, external decoder source or game fixture is
added. Reserved evaluations are reused source/structural consistency; no source
promotion or independent semantic-ground-truth claim is made.

`psin --bucket-pool-spans` adds storage associations for one exact local opaque
role of type5c. All eligible physical headers in bounded local records, embedded
values and framed buckets contribute to a complete untyped-pool coverage guard.
The stored counts and independently bounded interval distances corroborate a
four-byte storage stride; no primitive or array-element meaning is assigned.
Discovery/reserved authorize 27/seven pools and retain one discovery refusal
where an existing zero type75 owner prevents complete scanning. Requested views
are 1,971/613: 1,805/613 have checked storage (96 discovery null-empty headers),
166 discovery views refuse, and 6,001/2,293 raw groups round-trip. All fields stay
semantically unresolved. All 35 default and earlier value-mode outputs remain
exact. Bad count/alignment/nonoutput-header controls refuse in 102 cases, with
35 budget refusals; 34 opaque-content changes preserve coverage. Known ambiguous,
non-tiling or overlapping typed owners cannot authorize a pool.

`shaders --features` reads public SFI0 declaration words, preserving every known,
reserved and unknown bit. Discovery/reserved have 742/380 parts, with 197/23 zero
words and 920/543 set-bit observations. Missing parts differ from present zero
words, duplicates are retained without selecting an authoritative part, and
malformed components preserve independent program/PSV/signature views and shader
exports. All 1,122 outputs in each earlier metadata/signature/mask mode remain
exact. Short-component, overlapping-container and budget controls each refuse
1,122 cases; unknown-high-bit changes intentionally remain structurally valid.
Only five public bit positions occur naturally; other public names have authored
coverage. No RTS0 chunk occurs in these cohorts and no speculative root-signature
parser was added. Feature declarations do not verify executable use, hardware
compatibility or native game-resource identity.

Stereo nonzero skips still lack newly assigned discovery evidence for their units
and packet identities. Existing reserved examples were not reused for fitting.
The later non-reserved stereo support list is a possible future source-selection
input, not a newly promoted cohort. The implemented audio fallback extends the
already proved mono-overlap policy to strict Ogg export through
`--music-out --music-skip-policy verified-overlap`. It remuxes unchanged retained
packets, with explicit declared-duration granules and inherited 312-frame pre-skip;
no decoder is needed for export. Default legacy Ogg and existing WAV paths remain
unchanged. Discovery/reserved export 35/17 channels, with all 211,545 retained
packets exact and all 52 earlier supported WAV hashes preserved. The reserved
25,920-frame skip and nonzero stereo skips remain refused. Existing ACCUSE
zero-stereo Ogg remains byte-identical. Thirty wrong-byte identity, 31 node-limit,
31 input-limit and 17 zero-policy controls refuse. Three opaque FFmpeg comparisons
force the same libopus backend, agree on frame counts and differ by at most one
PCM16 unit; this is wrapper agreement, not original recording alignment or an
independent codec/game oracle.

Provenance is in `docs/psin_bucket_pools_provenance.md`,
`docs/shader_features_provenance.md` and
`docs/audio_music_overlap_ogg_provenance.md`. Eight command-level tests cover
implied modes, raw storage versus unresolved values, shared budgets, malformed
feature/export isolation, exact legacy Ogg bytes, verified packet removal without
a decoder, and retained stereo refusals. Native CLI checks accept all 742 shader
wrappers, expose 143 raw pool groups with semantic unknowns intact, and export
four music channels, removing 27 repeated packets across three channels. No
staging, commit or push occurred.


## Native world direction, bucket graph links and stereo discovery limits

World/level development now prioritizes this project's own native readers.
SixNG is an optional opaque comparison tool whose output may be incomplete or
incorrect; it is not implementation source or guaranteed format ground truth.
No GPL/unlicensed source was opened. The supplied compiled executable was used
only through help/info and isolated common-archive baseline commands, with no
inherited index changes. No new backend passthrough route was added.

`psin --bucket-graph` composes independently checked reference-valued buckets
with existing typed record graphs. Discovery/reserved add 171/57 edges to the
existing 114/nine, increasing candidate-reached observations from 35 to 375.
All 9,416 typed nodes and 35 default graphs remain exact. Source owners require
an exact existing field path, targets require exact existing typed identities,
and edges retain their intervening physical bucket/slot/reference provenance.
There are no fabricated nodes for the 105 excluded inline maps/1,139 spans.
One unresolved map remains explicit. All 210 malformed-report and 35 budget
controls refuse; all 35 unanchored edge sets remain exact. Reachability is from
an LRSC candidate, not a proven root, ownership rule or native station playlist.

A separately frozen stereo cohort uses only previously non-reserved support
sources, with older source roles and exclusions preserved. Before new payload
reads, 96 banks were assigned discovery and 32 reserved. All 97 discovery stereo
records have zero skips across 247 actual inter-block boundaries (343 blocks,
148,630,608 input bytes). No nonzero skip units or new decoder rule can be fitted
from them. All 32 reserved payloads remain unopened. The guarded research tool
has no reserved-read mode and verifies source roles/hashes/limits before use.
All 97 zero-stereo Ogg outputs match the existing exporter, with 432,626 retained
packets exact; 96 budget and 96 bad-seek controls refuse. The remaining unselected
and oversize eligible sources are future inputs, not silently promoted samples.
Audio runtime and the mono skip whitelist remain unchanged.

The native world catalog uses own checksum/stream/page/schema readers to join
PSIN pages only under established alignment, zero-padding and full-container
checks. Single-stream version122 0DRP views keep partial metadata/no resource
checksum status. Source segment offsets are compressed-archive positions;
block offsets remain within the inflated resource. Local stride/count matches
are storage associations, not entity/placement/geometry meanings. Schema hashes
remain namespace-qualified and conflicting layouts are retained separately.
Node, input, inflation and repeated block-hash work are bounded; budget failure
returns no catalog prefix. The native command never invokes a backend.

Private seals and source-role audits retain all 165 inherited artifact hashes,
previous source assignments, names.json and BCPack provisional labels. Authored
CLI tests cover graph source identity, implied modes, shared budgets, guarded
world requests, backend-free native output and input/output preservation. No game
fixtures or decoded media are published. No staging, commit or push occurred.

Native world discovery accounts for 34 compressed streams as eight complete
PSIN containers (including established checked page chains) and 13 single-stream
0DRP metadata views. There are 117 blocks, 99 local schema/stride associations,
2,554,468 count-only storage groups and two schema groups containing nine distinct
local structure definitions. No group is expanded into guessed entities. All
streams in that discovery window are accounted for. The reserved window accepts
eight 0DRP views with 67 blocks/53 associations and 1,717,366 storage groups;
three recognized starts refuse and three streams stay unclassified. It supplies
no PSIN positive. No decoder rule was retuned after reserved exposure. All 184
emitted block hashes and 152 storage associations match bounded source spans;
eight checksum, 21 pointer and four shared-budget controls refuse. A catalog
with local refusals remains explicit and the CLI exits nonzero; a whole-report
budget refusal leaves no new output. The two native selftests require no backend.

Provenance is in `docs/native_world_resources_provenance.md`,
`docs/world_preflight_provenance.md`, `docs/psin_bucket_graph_provenance.md` and
`docs/stereo_overlap_discovery_provenance.md`. Supplementary stereo selection is
preserved, with all 32 reserved payloads unopened. SixNG help/info and zero-result
common-archive commands were isolated interface observations, not validation of
native world layouts or evidence that its decoded values are correct. No new
passthrough was added following the user's native-tooling direction.

## Native world schema views, counted ranges and declared extents

Three separate investigations extended the native resource catalog without
external implementation source or a backend dependency. SixNG was not used to
derive or confirm any of these rules. Existing native metadata readers provide
the local declarations; raw source spans provide structural checks.

The schema view preserves canonical format-qualified group/variant IDs while
exposing complete raw fields, enum members, type-word usages and query matches.
Declaration words are checked against resource-local table positions. Shared
declarations are deduplicated; occurrences retain relocated pointers and source
offsets. Discovery has nine shared structures/23 fields across 21 resources;
the original reserved cohort has seven/15 across eight. All 2,820 checked u32
words reproduce source declarations. Natural enum positives are absent in these
cohorts; authored tests cover enum aliases/full-width value bits. Optional names
are only independently rehashed dictionary preimages, never confirmed meanings.

For the observed 0DRP structure-reference profile, a checked descriptor selects
a local structure. A counted field occupies exactly 16 source bytes: equal
positive u32 words and a nonnull u64 reference (or an all-zero empty header).
Independent fitting across partitions 8..32 admits only a low 20-bit local block
ID plus high byte offset when requiring the correct target type, whole target
stride, alignment and complete count bounds. Fixed embedded structure arrays
must exactly exhaust the independent owning field slot. Their paths remain
attached to the outer source row. Primitive descriptors and unknown fields are
not scanned for pointer-looking values.

There are 214,987 discovery headers (214,024 nonnull/963 null) and 146,591 in the
original reserved cohort (145,563 nonnull/1,028 null). Every retained range and
source path reproduces source bytes; only the frozen 20-bit partition fits all
ranges in both cohorts. 358,084 references use bits above bit 32. Sixty-three
malformed-input controls and 21 one-short helper budgets refuse. These are local
storage ranges, not world objects, placements, ownership, or proven graph roots.
All outputs retain unknown primitive fields and partial status.

The extent investigation froze a new disjoint 16-MiB discovery/reserved plan
before payload reads, preserving all earlier roles. Its discovery has 28 0DRP
starts: 24 bounded metadata observations and four incomplete ones. Across all
37 original/new bounded discovery observations, the maximum declared metadata
endpoint rounded to 64 KiB matches the stream length with zero tail. Four new
incomplete starts now report precisely which declared spans are absent. Neither
padding nor adjacent short-stream sizes prove resource ownership, so no joins
were enabled and complete resource endpoints stay null. The successor reserved
window remains unread. The original three refused starts still refuse.

The three helpers and their audits were sealed before their respective reused
reserved consistency runs. Original source cohorts were already exposed; these
results are not fresh blind semantic validation. All 180 inherited artifact
hashes, names.json, frozen assignments and BCPack provisional labels remain
unchanged. Optional CLI views share node/inflation limits; global exhaustion
returns no partial catalog, while malformed supported link views retain only a
reason and independent metadata. Default catalog output remains identical.
Provenance is recorded in `docs/native_world_schemas_provenance.md`,
`docs/world_links_provenance.md`, `docs/native_world_extent_provenance.md` and
`docs/native_world_views_provenance.md`. No game fixtures were added.

## Native opaque primitive pools and transform/boundary falsification

The observed primitive-descriptor profile selects raw type-hash `0x00000017`
blocks through the same independently fitted low20-bit local block ID/high byte
offset partition. Primitive group width was derived independently: total pool
bytes divided by independently stored counts proposes a width, then every range
must be aligned, bounded, nonoverlapping and exactly exhaust its target pool.
Only partition20 and width8 satisfy all discovery observations. Smaller widths
can fit bounds but leave gaps; they are not equivalent evidence. The helper
checks the full supported pool before emitting compact source/pool layouts.
Unsupported descriptors, unreferenced pools, scalar semantics and transforms
remain explicit. No opaque groups are expanded by default.

Discovery: 2,520,960 headers (1,000,598 nonnull/1,520,362 null), 18 pools,
1,759,794 eight-byte groups and 14,078,352 pool bytes. Original reserved under
the unchanged profile: 1,715,520 headers (746,911 nonnull/968,609 null), 14 pools,
1,253,065 groups and 10,024,520 bytes. Eight-byte type15 field slots have
2,626/1,787 source observations, with value width and meaning unconfirmed.
All 84 native malformed-profile controls and 21 one-short helper budgets refuse.
The original three metadata refusals and three unknown streams remain intact.
Full discovery helper work needs 4,522,963 aggregate nodes; per-resource runs stay
bounded and the catalog's shared cap is not raised. One discovery CLI observation
uses 319,045 nodes with schemas, structure links, extents and primitive layouts.

Transform research tested only uniquely declared whole16/48/64-byte rows and
independently bounded eight-byte slots, without concatenating records. There
are no whole48/64-byte owners in the measured family. The primitive header rows
alone produce 3,895/2,940 apparent unit-float4 fits, all surviving lane reversal.
Eight-byte slots yield 3/0 signed16x4 unit fits, while wrong byte order yields
11/6. These mathematical predicates do not identify quaternions, component order
or coordinate systems. No transform decoder/export was added.

Boundary research remains discovery-only. It checks 66 individual zlib envelopes
across original and successor discovery windows (41 0DRP starts, eight PSIN
starts, 17 other streams). All 41 0DRP streams begin at4096n+16 with zero16-byte
preambles; no checked resource length or allocation owner follows. Sixty-three
of64 interstream gaps are zero. The four successor incomplete starts have nearby
short opaque streams, but no independent ownership rule. A proposed header-word
rounded-extent interpretation fits34/41 and fails even on three fully bounded
metadata observations. All264 mutated envelope controls refuse; their individual
zlib checksums are not full-resource checksums. No joins enabled, and the
successor reserved window remains unopened.

All 211 protected artifacts, frozen roles, the dictionary and BCPack labels
remain unchanged. Original discovery/reserved results are reused structural
consistency, not fresh blind or semantic ground truth. Numerical/profile rules
were sealed before reused reserved evaluation. Review then strengthened audit
output aliases (including dictionary/frozen files and hardlinks); these safety
fixes have separate versioned seals and did not retune numerical rules. See
`docs/world_primitives_provenance.md`, `docs/world_transforms_provenance.md`,
`docs/world_boundaries_provenance.md` and
`docs/native_world_primitive_views_provenance.md`. No external implementation
source or SixNG output was used for these rules; no game fixtures were added.

## Native reference context, asset equalities and header-selected metadata

The native reference-context helper revalidates every supplied source path,
declared inline stride, count/header word and bounded target range against the
same resource. Interval sweeps compute incoming-reference multiplicity without
expanding target records. Equal multiplicities coalesce into compact spans.
Queries return selected complete source paths and raw header evidence even when
the separate link view is absent. Out-of-scope queries stay unresolved; multiple
incoming references, actual record cycles and depth limits remain explicit.
Block-graph cycles are reported separately because aggregating records into one
block can introduce a block cycle without any record cycle.

Discovery covers 83 typed blocks/2,523,662 records: 2,523,649 singly referenced,
13 unreferenced, none multiply referenced. The unchanged original-reserved
profile covers 53 blocks/1,717,366 records: 1,717,358 singly referenced and eight
unreferenced, none multiply referenced. All block aggregations are acyclic, with
one unreferenced record per accepted 0DRP. This is observed reference incidence,
not independent root, semantic ownership or transform authority. The original
three metadata refusals and three unknown streams remain unchanged. Selected
query paths round-trip 342/222 source headers across 166/106 query chains;
21 wrong-source and 21 one-short helper-budget controls refuse. Range-order
controls preserve incidence. Exact source-header deduplication prevents a
corrupted duplicate-path report from double-counting the same field.

Asset research independently rehashes dictionary candidates under whole64 and
split32 hypotheses. Original discovery has no whole64 preimage matches in
1,759,794 checked pool groups or 2,626 leading eight-byte slots. The slots all
have zero upper32 bits; that does not independently establish a 32-bit value
width, asset namespace or reference role. Split-word equalities remain only
mathematical coincidences/candidates. No asset resolver was added.

After auditing all 253 inherited artifacts for source exclusions, two disjoint
supplementary eight-MiB discovery windows and paired adjacent eight-MiB reserves
were frozen before new payload reads. Discovery carves 35 capped streams with
63,542,976 inflated bytes: 12 recognized 0DRP starts, of which 11 have bounded
metadata, plus 23 other binary streams. The accepted declarations match the
existing family, supplying no new asset-ID authority. The separate supplementary
reserves and earlier successor reserve remain unread. No source role is promoted.

Boundary research adds exact header relationships across all 41 original and
successor discovery starts. The full-width word at0x08 matches the declared
block-table end; the word at0x40 matches a final structure-field-list end. The
latter is below the maximum declared block extent in three incomplete starts,
so it cannot universally supply a resource endpoint. At the first candidate
offset, a zero u64 prefix and count-like word of one/two precede that many zero
u64 slots; a separately declared 16-byte block follows exactly in all41 cases.
Its structure hash matches the observed unreferenced record family. These
discovery observations corroborate local context only; they do not identify
root roles, page/stream counts, resource lengths or ownership of adjacent data.
205 source-word mutations break the intended hypotheses while unrelated metadata
remains available; 41 one-short budgets refuse. No resource joins were enabled.

The context and asset profiles are sealed before their own reused original-
reserved evaluations. Previously exposed cohorts provide structural consistency,
not fresh blind semantic validation. Tool output guards protect the dictionary,
frozen prerequisites, runtime/tool files and hardlink/symlink aliases before
source reads. Dictionary misses are not retained in an unbounded negative cache.
All 253 inherited artifacts, names.json and BCPack provisional labels remain
unchanged. Provenance is in `docs/world_owners_provenance.md`,
`docs/world_assets_provenance.md`, `docs/world_boundary_authority_provenance.md`
and `docs/native_world_reference_context_provenance.md`. No external source or
SixNG output was used to establish these rules, and no game fixtures were added.
