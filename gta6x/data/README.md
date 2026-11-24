# Radio catalog

`radio_catalog.json` supplies the labels and locators for `python3 -m gta6x radio`.
It contains metadata only, with no audio or decoded assets. Locators apply to the
catalogued package; other packages need a compatible catalog. Hash, channel,
duration and chapter-bound checks reject incompatible inputs.

Sources: [Rockstar credits](https://www.rockstargames.com/VI/credits),
[GameSpot](https://www.gamespot.com/articles/all-gta-6-radio-stations-and-songs/)
and [VICE](https://www.vice.com/en/article/gta-6-radio-songs-list/).

| Field | Contents |
| --- | --- |
| `stations` | Station names, types and recording memberships. |
| `recordings` | Archive locators, native identifiers and optional chapter credits. |
| `names` | Stored spellings, checked 32-bit joaat/29-bit hashes, display aliases and credit alternatives. |
| `public_tracks` | Unordered public credits, including songs without identified audio. |

Station memberships are research assignments, not a decoded native station
graph. Alias labels remain provisional; composer/work aliases do not identify
a performer. Explicit station preferences select display credits while retaining
alternatives. Confirmation methods distinguish acoustic matches, reported
identifications and supplied program labels; exact edits may remain unknown.

Chapter credits require the exact AWC SHA-256, stream/channel, occurrence,
TRACKID and native frame bounds. Repeated IDs do not inherit names. Intervals
can contain overlapping songs or DJ speech. Raw marker/seek tables and original
bounds are preserved in exports. `--audio-dir` cannot establish native source
identity and refuses credits requiring it; use archive input for those records.

Use `radio --catalog FILE` for a custom catalog. Export the name/hash dictionary
without reading audio:

```bash
python3 -m gta6x radio --names-out radio-names.json
python3 -m gta6x names lookup 0xdaa8ac2f --index radio-names.json
```

Each library includes its catalog snapshot, name dictionary and native metadata
sidecars. Normal exports need FFmpeg and game data, with no research exports,
fingerprinting packages or recognition-service access.
