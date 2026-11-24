# gta6x — GTA VI package explorer

Explore a local **GTA VI Xbox 1.0.2.1** package, extract assets, and inspect its
metadata from the command line. Export textures, audio, video and shaders, or
build a searchable asset browser without decrypting the archive index.

The native toolkit uses Python's standard library and opens package data
read-only. No installation or build step is required. Optional tools add model
and world exports, and supported audio-to-WAV conversion.

## Capabilities

| Area | What you can do |
| --- | --- |
| **Textures** | List streamed and embedded textures; export supported mip chains, arrays and cubemaps to DDS; generate PNG previews, including BC1–BC7. Inspect supported DDS files and preview selected mips, slices and volume planes offline. |
| **Audio and music** | Inspect AWC streams and music channels; extract native payloads; remux supported Opus to playable Ogg; export supported WAV audio with libopus. Browse audio-config records and TRACKID chapter metadata. |
| **Video** | Find Bink2 movies, inspect dimensions and duration, and extract the original files. |
| **Metadata** | Browse PSIN schemas, enums, supported instance values and record links; compare extracted schema declarations; export JSON and recover complete XML/PSIN resources. |
| **Shaders** | Extract DXBC binaries; inspect signatures and features; query logical resource bindings by stage, register, space and type. |
| **Animation** | List names and clips; inspect extracted resource metadata, native bone tables, packed buffers, binding keys and raw code rows; trace supported key-holder chains; browse MoVE and RBF metadata. |
| **Native world inspection** | Browse level-resource schemas and blocks, inspect supported primitive storage, trace checked local references and export their DOT graphs. |
| **Asset browsing** | Build JSON or SQLite catalogs, generate a searchable HTML browser, retrieve individual assets and use an interactive terminal browser. |
| **3D exports** | Export models to glTF/GLB and world data such as placements, collision, navmeshes and paths through the optional SixNG backend. |

## Quick start

You need **Python 3.10+** and a local, readable package. Run commands from this
checkout's root directory; no third-party Python packages are required.

```bash
export GTA6_ROOT="/path/to/GTA6.Xbox.v1.0.2.1"

python3 -m gta6x info
python3 -m gta6x textures --max 20
python3 -m gta6x --help
```

You can pass `--root PATH` instead of setting `GTA6_ROOT`. Global options go
before the command:

```bash
python3 -m gta6x --root "$GTA6_ROOT" --json info
python3 -m gta6x textures --help
```

The general syntax is `python3 -m gta6x [--root PATH] [--json] COMMAND [OPTIONS]`.
Use `COMMAND --help` for its full options. Archive and pool filters usually
accept name fragments, such as `levels` or `vehicles`.

## Common workflows

### Textures

List a pool, export DDS files with PNG previews, or inspect embedded textures:

```bash
python3 -m gta6x textures --pool vehicles --max 20
python3 -m gta6x textures --pool vehicles --max 20 --out ./exports/textures --png
python3 -m gta6x textures --embedded --archive textures --max 20 --out ./exports/embedded --png
```

Add `--bcpack` to attempt native BC1/BC3/BC4/BC5 BCPack decoding, or `--all` to
remove the texture-count limit. Filter with `--hash-prefix` or `--min-size`.
`--png-mip`, `--png-slice` and `--png-z` select a supported preview subresource;
DDS retains the supported texture layout. `textures.json` records exports and
skip reasons. Textures without recovered names retain their hash identifiers.

### Audio and video

```bash
python3 -m gta6x awc --archive audio --limit 64 --max 10
python3 -m gta6x awc --archive audio --limit 64 --ogg-out ./exports/audio
python3 -m gta6x awc --archive audio --limit 64 --music-out ./exports/music
python3 -m gta6x movies --archive movies --limit 64 --out ./exports/movies
```

For supported PCM WAV export, install a compatible **libopus** system library
and use `--wav-out` or `--music-wav-out`. Raw and Ogg export need no audio library.
Use `music --config` for audio-config browsing and `awc --radio` for native
markers and TRACKID chapters.

### Metadata, shaders and animation

```bash
python3 -m gta6x psin --archive levels --schema --out schemas.json
python3 -m gta6x psin --archive levels --instances --record-graph --out instances.json
python3 -m gta6x shaders --metadata --out ./exports/shaders
python3 -m gta6x --json shaders --bindings --binding-type 3 --max 10
python3 -m gta6x anim --resources --clips --out ./exports/animations
python3 -m gta6x world --kind resources --schemas --extract-resources --out ./exports/world
```

PSIN supports local name dictionaries and cross-file schema registries.
Use `--find-field`, `--find-type` or `--same-layout`; add `--registry-only --registry FILE`
for offline queries. `--context-record BLOCK:RECORD` traces checked record links.
Inspect paths with `--context-field BLOCK:RECORD:FIELD[.FIELD...]` or `--field-tree`;
`--context-map` and `--context-enum` inspect selected map and enum evidence.
`--context-pool` and `--pool-incoming BLOCK:RECORD` trace storage and incoming evidence.
`--hash-use WORD` finds opaque-word usages; `--typed-hash-candidates --names names.json`
adds candidate names without asset bindings. `--graph-dot FILE` exports checked graphs;
`--type5c-spans` checks spans; `--type5c-graph` adds candidate links.
`--type5c-diagnostics` explains unresolved headers, coverage gaps and missing targets.
`--type5c-pool-context` compares candidate spans with existing reference-pool users.
`psin --manifest FILE` queries verified exports; `--manifest-limit` selects a prefix.

Native world inspection traces supported direct and fixed-embedded references
with `--links`, including supported container entries and counted-value pool
references. Pool grouping requires complete coverage; keys and value meanings
remain unknown. Use `--primitive-layouts`, `--reference-context`
and `--context-record BLOCK:RECORD` for the supported storage views. Bound scans with
`--start`, `--scan-mib` and `--max-nodes`; `--extent-diagnostics` reports gaps
and missing declared bytes. `--extract-resources` exports complete checked PSIN
files and skips unknown boundaries. To inspect an extracted file directly, use
`--raw-resources --archive FILE`; raw inputs are never carved or joined.
`--manifest FILE` verifies and inspects a batch from a native export manifest.
Add `--value-words` to inspect raw primitive bits and full key slots; it implies
`--links`. Use `--names FILE` for verified hash-preimage candidates whose native
meanings remain unconfirmed.
`--graph-dot FILE` exports checked reference ranges as a source-scoped graph;
it implies `--links`. Large graphs may need a higher `--max-nodes` budget.

For animation research, `anim --binding-layout` traces raw binding keys to
slot-directory entries and checks local animation-dictionary membership,
identifier hashes and member buckets.
`anim --sample-codes` exports conditional raw row codes
and packed entry bits; use `--out DIR` to save JSON and `--max-nodes N` to set
the output budget. Numeric samples, poses, timing and bone bindings remain
unresolved.

`anim --key-holders` inspects supported native key-holder and parent references
and implies `--resources`. Use `--max-nodes` to set the inspection budget;
bone and rig meanings remain unconfirmed.

For a decompressed native pack stream, `anim --raw-skeleton FILE` inspects bone
names, stored keys and parent/sibling/subtree relationships. Add `--bone-keys`
to compare alternate keys with the fitted name formula, or `--pose-layout` for
checked parallel records and raw numeric word views. `--out DIR` saves
`skeleton.json`. Unexplained keys, pose meanings and animation-to-skeleton
ownership remain explicit.
`--skeleton-context` adds local reference paths, active zero-key context and
quaternion/matrix consistency checks. Bound the expanded inspection with
`--max-nodes`; larger tables may need a higher budget.
Use `--provider-targets` to trace supported nested references, or `--bone-names`
to inspect the compact name-to-bone-index lookup.

Inspect selected rows from an extracted packed buffer using its parent metadata's
binding count:

```bash
python3 -m gta6x --json anim --raw-buffer packed.bin --binding-count 64 \
  --sample-source 0 --sample-rows 0:4
```

Shader `--binding-stage`, `--binding-space`, `--binding-register` and
`--binding-type` filter reported declarations. These describe logical registers;
game texture and material identities remain unknown.

### Work with extracted files

Inspect assets without scanning the game archives:

```bash
python3 -m gta6x dds texture.dds --png preview.png
python3 -m gta6x --json shaders --raw shader.cso --bindings
python3 -m gta6x psin-diff before.psin after.psin --out comparison.json
python3 -m gta6x --json anim --raw-resource extracted.0drp --out ./exports/metadata
python3 -m gta6x world --kind resources --raw-resources --archive level.bin \
  --out ./exports/world --graph-dot ./exports/world/links.dot --max-nodes 300000
```

DDS inspection supports tightly packed DX10 layouts and legacy DXT1/3/5 and
supported BC4/BC5 FourCC formats. Preview selectors are `--mip`, `--slice` and `--z`
where the layout permits them. Repeat `anim --raw-resource FILE` to inspect a
batch; `--expected-sha256` pins each input in order. This reads bounded native
0DRP metadata without scanning archives or joining files.
Raw shader mode accepts multiple files and writes inspection JSON
with `--out DIR`. PSIN comparison preserves unknowns and ambiguous declarations;
matching hashes do not establish semantic compatibility.

### Catalog and browse assets

```bash
python3 -m gta6x catalog --archive levels --limit 64 --db gta6.db
python3 -m gta6x browse --db gta6.db --out ./site
python3 -m gta6x tui --db gta6.db
```

Open `site/index.html` to browse the catalog. Use `get` to extract a cataloged
asset by hash or archive offset. Catalogs can also be written as JSON; `report`
generates Markdown or HTML inventories.

### Models and world exports with SixNG

Provide a [SixNG](https://github.com/holdmysocks/SixNG) executable, either through
`GTA6X_SIXNG` or `--backend PATH`. It is a separate optional dependency and is
not bundled; Rust is only needed if you build it yourself.

```bash
export GTA6X_SIXNG="/path/to/sixng"

python3 -m gta6x models index --archive packs
python3 -m gta6x models extract --archive packs --max 5 --out ./exports/models
python3 -m gta6x world --via sixng --kind placements --archive levels --out ./exports/placements
```

Backend indexes are cached in `.sixng-work/`. `models list` previews available
entries. Other world export kinds include `collision`, `navmesh`, `paths`,
`lights` and `interiors`. Backend results depend on SixNG's format support and
may be incomplete. `world --kind resources` uses the native reader instead.

## More commands

| Commands | Purpose |
| --- | --- |
| `info`, `headers`, `resources` | Inspect package identity, archive headers and texture-pool indexes. |
| `scan`, `extract`, `zlib` | Find media carriers or carve compressed resource streams. |
| `structured`, `rbf`, `move` | Recover XML/PSIN resources or inspect supported RBF and MoVE metadata. |
| `names build`, `names lookup` | Build or query a local name-hash dictionary. |
| `get`, `hunt` | Retrieve cataloged assets or identify geometry-like byte patterns. |
| `report`, `verify` | Generate inventories or check a SHA-256 manifest. |
| `selftest` | Run built-in parser checks without game data. |

For scan-based commands, `--limit` generally sets MiB per archive and `--full`
scans the whole archive where supported. Display limits such as `--max` do not
necessarily cap extraction. Native world uses `--scan-mib` for scan size and
`--limit` for resource count; check each command's help before a large export.

## Current limits

- **Archive access:** the RPF9 index is not decrypted. Resource scanning and
  carving do not provide a complete original filename tree.
- **Textures:** some formats and layouts remain unsupported, including native
  compressed or multi-mip volume export. BCPack coverage is partial: BC3/BC4/BC5
  reject unknown histories and warn on provisional entries; BC1 retains legacy
  preset fallbacks. BC6H/BC7 BCPack is unsupported.
- **Audio:** XMA2 decoding and some Opus timing/skip profiles are unsupported.
  Native song-title, station-membership and playlist links remain unresolved.
- **Animation and world:** native inspection exposes metadata and checked
  storage relationships, not decoded animation curves, placements or geometry.
  Asset bindings, transform meanings and semantic ownership remain unconfirmed.

Unsupported cases are reported with reasons. Exported data goes to the paths
you choose; no game data, keys or external executables are included here.

## License and credits

[MIT License](LICENSE). Copyright (c) 2026 HolyRoses. Third-party decoder
attributions and license details are in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Thanks to [SixNG](https://github.com/holdmysocks/SixNG),
[rpf9-explorer](https://github.com/breadbbbb/rpf9-explorer),
[Leonida](https://github.com/ItsNotRexed/Leonida), and the GTA modding community
for their tools and format research. SixNG and external BCPack helpers are
optional, separate tools; their code is not bundled.
