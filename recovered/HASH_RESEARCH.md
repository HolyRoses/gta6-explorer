# Hash-family research log (local)

Status: **64-bit solved**; 29-bit algorithm known but names unresolved; 128-bit
and 15-bit still open. This file records both the verified result and the
negative experiments.

## Datasets

| Family | Data | Count |
|---|---|---:|
| 64-bit texture hashes | ETPF descriptor hashes across all 57 TTPF pools | 357,067 unique (357,115 descriptors) |
| 64-bit entity hashes | `placements` entities in `levels.rpf` | 987,499 entities sampled |
| 128-bit IDs | `LSNS` (16-byte records after a 16-byte header) | 147,122 records / 145,297 unique |
| 128-bit IDs | `LGID` (count + 16-byte records) | 3,052 records / 3,011 unique |
| 29-bit IDs | AWC stream ids in the first 48 MiB of `audio.rpf` | 4,668 streams / 4,662 unique |
| 15-bit IDs | Collision surface ids from a 400-entry `levels.rpf` sample | 49 ids |
| Candidates | recovered names (joaat dictionary) | 50,901 |
| Candidates | material `<name>` values in recovered XML | 1,063 |

## 64-bit texture hashes — SOLVED

Algorithm: **low 64 bits of MurmurHash3 x64 128 (seed 0) over the exact UTF-8
name bytes**. Confirmed against the latest upstream trees:

- Leonida `tools/world_names.py` documents the per-archetype/map 64-bit key as
  exactly this function.
- Independently reproduced in `gta6x/names.py` (`murmur3_x64_128`, `hash64`).

Verification against this package:

- 13 TTPF texture hashes resolve through recovered names: `temp`,
  `veh_detail_atlas_control`, `rope`, `mapdetail_atlas`, `sclera`,
  `veh_detail_atlas_n`, `veh_detail_atlas_aniso`, `iris`, `test`, plus four
  `ky.._bespoke`/`le_screen` names.
- 6 embedded-txd names also match TTPF hashes: `blank_dirt`, `blank_mb2x1`,
  `blank_nm`, `blank_midgrey`, `blank_mb`, `blank_black`.
- `textures` now resolves names with `--names names.json` (default
  `names.json` when present) and writes the name into the manifest.

Why the earlier probe failed: it tested joaat64, FNV-1a64, xxHash64, xxHash3,
CityHash64, MurmurHash64A, MD5/SHA slices and 32-bit halves — but **not
MurmurHash3 x64 128**, the actual function.

The same function explains the per-archetype 64-bit keys in placements; the
per-entity `hash64` in placement JSON is a separate entity GUID and must not be
resolved as a name.

## 128-bit `LSNS` / `LGID` IDs — OPEN

Tested MD5, SHA-1[:16], SHA-256[:16], BLAKE2b/2s (16-byte), xxHash128,
xxHash3-128 and CityHash128 over the recovered names.

Result: **0 matches** for all families.

Structural observations:

- IDs repeat: 947 repeated `LSNS` IDs (max 34 occurrences) and 22 repeated
  `LGID` IDs. That is consistent with reference IDs/GUIDs used by several
  records, not a per-name hash where duplicates would need identical names.
- The UUID version nibble (byte 6 high nibble) is uniform across 0–15; UUIDv4
  would concentrate on 4, so these are raw 128-bit IDs, not UUIDv4.
- `LSNS` and `LGID` have no overlap.
- `LSNS` header observed as `01 00 00 00 | 01 01 00 00 | size` followed by
  16-byte records; `LGID` is `count` followed by 16-byte records.

Hypothesis: opaque 128-bit asset/string IDs, not a standard name hash. A string
table would be needed to map them.

Next experiments: byte-reversed/complemented IDs, MD5 with prefixes/suffixes,
and locating the string table that references these IDs.

## 29-bit audio stream ids — algorithm known, names open

Leonida `docs/audio_config.md` identifies the relation: the AWC stream id is
`joaat(normalized track name) & 0x1FFFFFFF`, where the normalized name is
lower-cased with runs of spaces/punctuation collapsed to `_`. The audio config
stores the same hash as `hash B`, plus duration.

- 4,668 AWC stream ids from the first 48 MiB of `audio.rpf`.
- No stream names are recovered by gta6x/SixNG/rpf9-explorer yet, so the
  dictionary still cannot name them.
- The 1,589 audio-config records and their durations are a separate extraction
  target (Leonida `tools/audio_config.py`); this would give record-level music
  metadata even without names.

## 15-bit collision surface ids — OPEN

49 observed ids from a collision sample; 2 known rail/gravel ids (2287, 4180)
from SixNG's inference. Tested over 1,063 material names:

- joaat32 (original/lower), with and without seed `0x3FAC7125`
- CRC32 (original/lower), FNV-1a, xxHash32
- MD5/SHA-1 slices
- every 15-bit shift window 0–17 of each 32-bit result

Best result was 6 hits across 49 ids, approximately the random rate
(1,063 × 49 / 32,768 ≈ 1.6; max 6 is plausible noise). No candidate maps the
known rail ids either. The hash likely uses a seed, a name transform (prefix or
case form), or a different family.

Next experiments: obtain more verified name→id pairs, test `atDataHash`-style
word hashing and seeded variants, and try prefixes such as `MATERIAL_`/`SURF_`.

## LSCH schema observation

LSCH has 32-byte struct headers (`hash u32`, second u32, flags, `0xAA` fill,
size, field count in the high 16 bits) followed by variable descriptors. The
field layout does not match the older GTA V PSO 16-byte descriptor; a naive
walk produces `0x100` pseudo-hashes and is wrong for this build. A correct
walker is needed before the 32-bit struct hashes can be paired with names.

## Reproduce

- Names: `python3 -m gta6x --root <pkg> names build --out names.json`
- Placements/entity sample: `sixng placements levels --bbox ... --out ...`
- Collision ids: `sixng collision levels --limit 400 --out ...` then
  `surfaces.json`
- This log used `xxhash` and `cityhash` installed under the gitignored
  `work/hashdeps` only for the research probes; the tool itself stays
  dependency-free.
