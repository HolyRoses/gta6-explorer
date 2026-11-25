# Radio catalog

`radio_catalog.json` supplies the labels and locators for `python3 -m gta6x radio`.
It contains metadata only, with no audio or decoded assets. Locators apply to the
catalogued package; other packages need a compatible catalog. Hash, channel,
duration and chapter-bound checks reject incompatible inputs.

Sources: [Rockstar credits](https://www.rockstargames.com/VI/credits),
[GameSpot](https://www.gamespot.com/articles/all-gta-6-radio-stations-and-songs/),
[VICE](https://www.vice.com/en/article/gta-6-radio-songs-list/) and
[The Tab](https://thetab.com/2026/11/19/the-full-gta-6-radio-song-list-every-single-track-broken-down-by-station).

| Field | Contents |
| --- | --- |
| `stations` | Stations, public show/playlist groups and curated collections with recording memberships. |
| `recordings` | Archive locators, native identifiers and source-bound recording/chapter credits. |
| `names` | Stored spellings, checked 32-bit joaat/29-bit hashes, display aliases and credit alternatives. |
| `public_tracks` | Unordered public credits, including songs without identified audio. |

Station memberships are research assignments, not a decoded native station
graph. Alias labels remain provisional; composer/work aliases do not identify
a performer. Explicit station preferences select display credits while retaining
alternatives. Confirmation methods distinguish acoustic matches, reported
identifications and supplied program labels; exact edits may remain unknown.
Premixed stations can also include standalone recordings. Exports keep them in
a separate folder and playlist from broadcast chapters. Acoustic recording
credits remain provisional and require the exact source hash and channel.
An optional recording-credit `composer` keeps composer metadata separate from
the matched performer and is included in tags and song searches.
Bonus groups use `context_type` to distinguish public playlists from station
groups. Backend credit disagreements remain explicit in recording alternatives.
Config-hash identifications use a separate method and remain provisional;
they are not acoustic confirmations of a performer or edit.
Bonus Tracks is a curated `collection` of identified recordings with unknown
station or usage, rather than a claimed native station.
Public lists retain source-specific title and artist variants. Matching credits
can carry `additional_sources`; a list entry alone does not identify audio.
`acoustic_matches` supplies provisional listening samples for programs without
native song boundaries. Each sample requires its exact source hash, channel and
bounded audio window. Separate identified-excerpt files and playlists preserve
the original program; these samples are not whole-track cuts or native chapters.
Stored channel roles and the game's final mix may remain unknown.
Identified-location playlists start at a matched sample and continue to the
stored program's end; they do not claim the song's start or end.

`broadcast_cuts` supplies longer, fingerprint-guided broadcast sections. Each
requires an enclosed acoustic sample, the exact source/channel, provisional
status and `start_range_frames` / `end_range_frames` uncertainty bounds.
Song cuts appear in the main station and All Stations playlists and retain their
separate song-cut playlists, original-speed audio and DJ transitions.
These estimates never become native chapters, TRACKIDs or studio-master claims.

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
