"""Named radio libraries from checked AWC audio and explicit research labels.

FFmpeg/ffprobe are opaque executables. Native extraction remains in gta6x;
tagging/conversion and packet-boundary chapter cuts are explicit output steps.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unicodedata
from urllib.parse import quote

from . import (audio_music_pcm, audio_music_skips, awc_inputs, awc_ogg_export,
               awc_radio, media, radio_catalog)

RATE = 48000
FORMATS = {'opus': ('opus', ['-c:a', 'copy'], 'opus'),
           'flac': ('flac', ['-c:a', 'flac'], 'flac'),
           'mp3': ('mp3', ['-c:a', 'libmp3lame', '-q:a', '2'], 'mp3'),
           'm4a': ('m4a', ['-c:a', 'aac', '-b:a', '256k'], 'ipod'),
           'wav': ('wav', ['-c:a', 'pcm_s16le'], 'wav')}


def safe_name(text, maximum=150):
    text = unicodedata.normalize('NFC', text)
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]', '_', text).strip(' .') or 'Unknown'
    text = text.encode('utf-8')[:maximum].decode('utf-8', 'ignore').rstrip(' .')
    if text.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)),
                                      *(f'LPT{i}' for i in range(1, 10))}:
        text = '_' + text
    return text or 'Unknown'


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _json(path, value):
    _atomic(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))


def _atomic(path, data):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def _target(root, relative, protected=()):
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('radio output escapes its output directory')
    for source in protected:
        source = Path(source)
        if path.resolve() == source.resolve() or (path.exists() and source.exists() and os.path.samefile(path, source)):
            raise ValueError('radio output would overwrite an input')
    return path


def _run(command, timeout):
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError('media tool timed out') from exc
    if result.returncode:
        raise ValueError('media tool failed: ' + result.stderr.decode('utf-8', 'replace')[-2000:])
    return result.stdout


def _tool(value, name):
    result = shutil.which(value or name)
    if result is None:
        raise ValueError(f'{name} is required for radio export; install it or supply --{name}')
    return str(Path(result).resolve())


def probe(path, executable, timeout):
    raw = _run([executable, '-v', 'error', '-show_format', '-show_streams', '-show_chapters',
                '-of', 'json', str(Path(path).resolve())], timeout)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('media probe exceeds metadata limit')
    info = json.loads(raw)
    if not isinstance(info, dict) or not isinstance(info.get('streams'), list):
        raise ValueError('invalid media probe report')
    streams = [s for s in info.get('streams', []) if s.get('codec_type') == 'audio']
    if len(streams) != 1:
        raise ValueError('radio output requires exactly one audio stream')
    tags = {k.casefold(): v for source in (info.get('format', {}), streams[0])
            for k, v in source.get('tags', {}).items()}
    try:
        duration = float(info.get('format', {}).get('duration', 0))
        start = float(info.get('format', {}).get('start_time', 0))
    except (TypeError, ValueError) as exc:
        raise ValueError('invalid media probe duration') from exc
    if not math.isfinite(duration) or not math.isfinite(start) or duration <= 0:
        raise ValueError('radio audio has no finite positive duration')
    playable = duration - max(0, start)
    if playable <= 0:
        raise ValueError('radio audio has no positive playable interval')
    return dict(duration_s=playable, codec=streams[0].get('codec_name'),
                channels=streams[0].get('channels'), tags=tags, chapters=info.get('chapters', []))


def _metadata_escape(text):
    return str(text).replace('\\', '\\\\').replace('=', '\\=').replace(';', '\\;').replace('#', '\\#').replace('\n', '\\\n')


def chapter_title(row):
    return row.get('title') or ('Opening interval' if row.get('track_id') is None
                                else f"TRACKID {row['track_id']}")


def chapter_display(row):
    title = chapter_title(row)
    return row['artist'] + ' - ' + title if row.get('artist') else title


def credited_chapters(recording, source):
    """Apply external credits only to the exact native source and occurrence."""
    rows = [dict(row) for row in source['chapters']]
    for credit in recording.get('chapter_credits', []):
        if (credit['stream_index'], credit['channel_index']) != (source['stream_index'], source['channel_index']):
            continue
        if source.get('supplied_audio') or source['source_sha256'] != credit['source_sha256']:
            raise ValueError('chapter credit requires its exact native source hash')
        matches = [row for row in rows if row['index'] == credit['index']]
        if len(matches) != 1 or any(matches[0].get(k) != credit[k]
                for k in ('track_id', 'start_frames', 'end_frames')):
            raise ValueError('chapter credit differs from native occurrence or bounds')
        matches[0].update(title=credit['title'], artist=credit['artist'],
            credit_status=('audio_fingerprint_match' if credit['method'] == 'audio_fingerprint'
                           else credit['method']), credit_source=credit['source'],
            credit_evidence=credit['evidence'], provisional=True)
        if 'credit_conflicts' in credit:
            matches[0]['credit_conflicts'] = credit['credit_conflicts']
        if 'alternatives' in credit:
            matches[0]['credit_alternatives'] = [dict(row) for row in credit['alternatives']]
        if 'reference_credit_method' in credit:
            matches[0]['reference_credit_method'] = credit['reference_credit_method']
    return rows


def check_recording_credit(recording, source):
    """Recording observations apply only to their checked native source/channel."""
    credit = recording.get('recording_credit')
    if credit and (source.get('supplied_audio') or any(source.get(key) != credit[key]
            for key in ('source_sha256', 'stream_index', 'channel_index', 'channel_id'))):
        raise ValueError('recording credit requires its exact native source and channel')


def acoustic_matches(recording, source):
    """Listening samples never replace native chapters or imply song boundaries."""
    matches = []
    for row in recording.get('acoustic_matches', []):
        if (row['stream_index'], row['channel_index']) != (source['stream_index'], source['channel_index']):
            continue
        if source.get('supplied_audio') or any(source.get(key) != row[key]
                for key in ('source_sha256', 'channel_id')):
            raise ValueError('acoustic match requires its exact native source and channel')
        frames = source.get('native_timing', {}).get('output_frames')
        if frames is None or not 0 <= row['start_frames'] < row['end_frames'] <= frames:
            raise ValueError('acoustic sample exceeds the native audio timeline')
        matches.append(dict(row))
    return sorted(matches, key=lambda r: (r['start_frames'], r['end_frames']))


def broadcast_cuts(recording, source):
    """Research intervals require native identity and retain boundary uncertainty."""
    cuts = []
    for row in recording.get('broadcast_cuts', []):
        if (row['stream_index'], row['channel_index']) != (source['stream_index'], source['channel_index']):
            continue
        if source.get('supplied_audio') or any(source.get(k) != row[k] for k in ('source_sha256', 'channel_id')):
            raise ValueError('broadcast cut requires its exact native source and channel')
        frames = source.get('native_timing', {}).get('output_frames')
        if (frames is None or not 0 <= row['start_frames'] < row['end_frames'] <= frames
                or not 0 <= row['start_range_frames'][0] <= row['end_range_frames'][1] <= frames):
            raise ValueError('broadcast cut uncertainty exceeds the native audio timeline')
        cuts.append(dict(row, start_range_frames=list(row['start_range_frames']),
                         end_range_frames=list(row['end_range_frames'])))
    return sorted(cuts, key=lambda r: (r['start_frames'], r['end_frames']))


def _clock(frames):
    milliseconds = frames * 1000 // RATE
    seconds, milliseconds = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60); hours, minutes = divmod(minutes, 60)
    return f'{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}'


def _ffmetadata(chapters):
    rows = [';FFMETADATA1']
    for row in chapters:
        rows += ['[CHAPTER]', 'TIMEBASE=1/48000', f"START={row['start_frames']}",
                 f"END={row['end_frames']}", 'title=' + _metadata_escape(chapter_title(row))]
        if row.get('artist'):
            rows.append('artist=' + _metadata_escape(row['artist']))
    return '\n'.join(rows) + '\n'


def cue_text(filename, station, chapters):
    """75 Hz CUE navigation; exact 48 kHz positions remain in the JSON sidecar."""
    quote = lambda s: str(s).replace('"', "'").replace('\r', ' ').replace('\n', ' ')
    lines = ['REM GENERATED_BY gta6x', 'REM SOURCE_TIMEBASE 48000',
             'REM CUE_TIMEBASE 75; positions truncated to CD frames',
             f'TITLE "{quote(station)}"', f'FILE "{quote(filename)}" WAVE']
    # CUE has a two-digit track namespace. Keep all intervals in JSON/M3U.
    for i, row in enumerate(chapters[:99], 1):
        frames = row['start_frames'] * 75 // RATE
        seconds, frame = divmod(frames, 75); minutes, seconds = divmod(seconds, 60)
        lines += [f'  TRACK {i:02} AUDIO', f'    TITLE "{quote(chapter_title(row))}"']
        if row.get('artist'):
            lines.append(f'    PERFORMER "{quote(row["artist"])}"')
        lines.append(f'    INDEX 01 {minutes:02}:{seconds:02}:{frame:02}')
    if len(chapters) > 99:
        lines.append('REM ADDITIONAL_INTERVALS_IN_JSON_AND_M3U ' + str(len(chapters)-99))
    return '\n'.join(lines) + '\n'


def playlist_text(name, entries, directory):
    lines = ['#EXTM3U', '#PLAYLIST:' + name]
    for entry in entries:
        label = (entry.get('artist', '') + ' - ' if entry.get('artist') else '') + entry['title']
        lines += [f"#EXTINF:{entry['duration_s']:.3f},{label}", '#EXTGRP:' + entry['station']]
        if 'start_frames' in entry:
            lines += [f"#EXTVLCOPT:start-time={entry['start_frames']/RATE:.9f}",
                      f"#EXTVLCOPT:stop-time={entry['end_frames']/RATE:.9f}"]
        # VLC resolves playlist locations as URI references: a literal # would
        # start a fragment and truncate the filename. Encode exactly once from
        # the filesystem path, including literal % characters and UTF-8 bytes.
        relative = Path(os.path.relpath(entry['path'], directory)).as_posix()
        lines.append(quote(relative, safe='/'))
    return '\n'.join(lines) + '\n'


def _radio_chapters(radio, channel_id, frames, channel_count):
    candidates = [t for t in radio.get('tables', []) if t.get('status') == 'parsed'
                  and 'chapters' in t and int(t['stream_id'], 16) == channel_id]
    if not candidates and channel_count == 1:
        candidates = [t for t in radio.get('tables', []) if t.get('status') == 'parsed'
                      and 'chapters' in t and t.get('bound_frames') == frames]
    if len(candidates) != 1:
        return [], 'no unique checked marker timeline for this channel'
    rows = [dict(r) for r in candidates[0]['chapters']]
    if rows and rows[0]['start_frames']:
        rows.insert(0, dict(index=-1, track_id=None, start_frames=0,
                            end_frames=rows[0]['start_frames'], role='unclassified_opening_interval'))
    return rows, candidates[0].get('bound_evidence', 'checked marker timeline')


def _extract(archive, recording, directory, pre_skip, skip_policy, max_records):
    offset = recording['offset']
    hit = media.awc_at(archive, offset)
    with Path(archive).open('rb') as handle:
        handle.seek(offset); data = handle.read(hit.size)
    if len(data) != hit.size:
        raise ValueError('truncated addressed AWC container')
    used = 0
    def consume(n=1):
        nonlocal used
        used += n
        if used > max_records:
            raise ValueError('radio AWC metadata exceeds work limit')
    awc_inputs._preflight(data, consume, True)
    metadata = media.validate_awc(data)
    if metadata is None or metadata['size'] != len(data) or not metadata['exact_length']:
        raise ValueError('radio source requires an exact complete AWC container')
    radio = awc_radio.inspect_bank(data, max_records=max_records)
    source_hash = hashlib.sha256(data).hexdigest()
    channels = []
    for stream in metadata['stream_list']:
        music = stream.get('music')
        if music and not music.get('error'):
            for channel in music['channels']:
                channels.append((stream, channel))
    expected_id = int(recording['hash_b'], 16) & 0x1fffffff if recording.get('hash_b') else None
    if expected_id is not None:
        selected = [(s, c) for s, c in channels if c['id'] == expected_id]
        if channels and not selected:
            raise ValueError('research song hash conflicts with native music channel IDs at this locator')
    else:
        selected = channels
    credit = recording.get('recording_credit')
    if credit and channels:
        selected = [(s, c) for s, c in selected
                    if (s['index'], c['index']) == (credit['stream_index'], credit['channel_index'])]
        if not selected:
            raise ValueError('recording credit channel is absent from its native source')
    results = []
    if channels:
        for stream, channel in selected:
            mode = channel.get('channels_per_record', 1)
            if mode not in (1, 2) or type(channel.get('frames')) is not int or channel['frames'] <= 0:
                results.append(dict(error='unsupported native channel mode/frame profile',
                                    stream_index=stream['index'], channel_index=channel['index']))
                continue
            try:
                raw, timing = audio_music_skips.extract_ogg(data, stream, channel['index'],
                    skip_policy=skip_policy, pre_skip=pre_skip, max_nodes=min(max_records, audio_music_pcm.MAX_NODES),
                    max_frames=0xffffffff // mode, max_input_bytes=media.MAX_AWC_SIZE)
            except ValueError as exc:
                results.append(dict(error=str(exc), stream_index=stream['index'], channel_index=channel['index']))
                continue
            file = directory / f"s{stream['index']}_c{channel['index']}.opus"; file.write_bytes(raw)
            chapters, association = _radio_chapters(radio, channel['id'], channel['frames'], len(channels))
            results.append(dict(path=file, stream_index=stream['index'], channel_index=channel['index'],
                channel_id=channel['id'], duration_s=channel['frames']/RATE, source_sha256=source_hash,
                native_timing=timing, awc_metadata=metadata, radio=radio, chapters=chapters, chapter_association=association))
    else:
        for stream in metadata['stream_list']:
            if credit and (stream['index'] != credit['stream_index'] or credit['channel_index'] != 0):
                continue
            if expected_id is not None and stream['id'] != expected_id:
                continue
            if not stream.get('data_bytes'):
                continue
            try:
                report, raw = awc_ogg_export.export_ogg(data, stream_index=stream['index'],
                    pre_skip=pre_skip, max_records=max_records, max_input_bytes=media.MAX_AWC_SIZE)
            except ValueError as exc:
                results.append(dict(error=str(exc), stream_index=stream['index'], channel_index=0))
                continue
            file = directory / f"s{stream['index']}_c0.opus"; file.write_bytes(raw)
            results.append(dict(path=file, stream_index=stream['index'], channel_index=0,
                channel_id=stream['id'], duration_s=report['ogg']['output_frames']/RATE,
                source_sha256=source_hash, native_timing=report['ogg'], radio=radio,
                awc_metadata=metadata, chapters=[], chapter_association='no blocked music timeline'))
    if not results:
        raise ValueError('no supported audio channel at this research locator')
    hint = recording.get('duration_hint_s')
    successful = [r for r in results if 'error' not in r]
    if hint is not None and successful and abs(successful[0]['duration_s'] - hint) > 2:
        raise ValueError('research duration conflicts with the addressed native descriptor')
    return results


def audio_index(directory):
    """Index explicit extraction identities, never infer identity from song text."""
    result = {}
    pattern = re.compile(r'(?:audio_)?(0x[0-9a-f]+|[0-9a-f]{9,})_s(\d+)_c(\d+)\]?\.(?:opus|ogg)$', re.I)
    for path in sorted(Path(directory).rglob('*')):
        if not path.is_file():
            continue
        match = pattern.search(path.name)
        if not match:
            continue
        key = int(match[1], 16), int(match[2]), int(match[3])
        if key in result:
            raise ValueError('ambiguous duplicate extraction identity in --audio-dir')
        result[key] = path.resolve()
        if len(result) > 100000:
            raise ValueError('supplied audio index exceeds file limit')
    return result


def _supplied(index, recording, executable, timeout):
    result = []
    for (offset, stream, channel), path in index.items():
        if offset != recording['offset']:
            continue
        info = probe(path, executable, timeout)
        if recording.get('duration_hint_s') is not None and abs(info['duration_s']-recording['duration_hint_s']) > 2:
            raise ValueError('supplied audio duration conflicts with this research locator')
        chapters = recording.get('reference_chapters', [])
        if any(c['end_frames']/RATE > info['duration_s']+2 for c in chapters):
            raise ValueError('supplied reference chapter exceeds the audio timeline')
        result.append(dict(path=path, stream_index=stream, channel_index=channel,
            source_sha256=_hash(path), duration_s=info['duration_s'],
            native_timing=None, radio=None, chapters=chapters,
            chapter_association='supplied rounded chapter survey; original AWC was not re-read',
            supplied_audio=True))
    if not result:
        raise ValueError('no exact source-address filename found in --audio-dir')
    return result


def _render(source, target, tags, chapters, *, format, ffmpeg, ffprobe, timeout,
            overwrite, start=None, end=None, exact_chapters=False):
    if target.exists() and not overwrite:
        info = probe(target, ffprobe, timeout)
        digest = _hash(target)
        try:
            with Path(str(target)+'.json').open('rb') as handle:
                raw = handle.read(8*1024*1024+1)
            cached = json.loads(raw) if len(raw) <= 8*1024*1024 else None
        except (OSError, ValueError, RecursionError):
            cached = None
        if (isinstance(cached, dict) and cached.get('export_identity') == tags
                and isinstance(cached.get('output'), dict) and cached['output'].get('sha256') == digest
                and all(info['tags'].get(k) == tags[k] for k in ('title', 'artist', 'album') if tags.get(k))):
            return dict(info, status='reused', sha256=digest)
        raise ValueError('output already exists with different metadata/provenance; use --overwrite')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.tag-', dir=target.parent) as tmp:
        temp = Path(tmp) / ('output.' + FORMATS[format][0])
        command = [ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error', '-y',
                   '-i', str(Path(source).resolve()), '-map', '0:a:0',
                   '-map_metadata', '-1', '-map_chapters', '-1']
        if start is not None:
            command += ['-ss', f'{start/RATE:.9f}', '-t', f'{(end-start)/RATE:.9f}']
        encoding = FORMATS[format][1]
        if format == 'opus' and exact_chapters and start is not None:
            encoding = ['-c:a', 'libopus', '-b:a', '192k']
        command += encoding
        if format in ('flac', 'mp3', 'm4a', 'wav'):
            command += ['-ar', '48000']
        for key, value in tags.items():
            for scope in ('-metadata', '-metadata:s:a:0'):
                command += [scope, f'{key}={value}']
        # Explicit Vorbis chapter tags avoid timestamp offsets introduced by
        # mapping a second ffmetadata input on some FFmpeg builds. Exact native
        # frame positions are also exported as a separate ffmetadata document.
        for i, row in enumerate(chapters, 1):
            for scope in ('-metadata', '-metadata:s:a:0'):
                command += [scope, f'CHAPTER{i:03}={_clock(row["start_frames"])}',
                            scope, f'CHAPTER{i:03}NAME={chapter_display(row)}']
        command += ['-f', FORMATS[format][2], str(temp)]
        _run(command, timeout)
        info = probe(temp, ffprobe, timeout)
        # Some containers have no arbitrary-tag namespace. Required display tags
        # are checked where the container supports them; JSON always retains all.
        for key in ('title', 'artist', 'album'):
            if tags.get(key) and info['tags'].get(key) != tags[key]:
                raise ValueError('tagged output does not reproduce required ' + key)
        if format == 'opus' and info['codec'] != 'opus':
            raise ValueError('radio Opus output codec mismatch')
        if format == 'opus' and chapters:
            embedded = info['chapters']
            if len(embedded) != len(chapters) or any(
                    abs(float(a['start_time']) - b['start_frames']/RATE) > .00101
                    or a.get('tags', {}).get('title') != chapter_display(b)
                    for a, b in zip(embedded, chapters)):
                raise ValueError('embedded Ogg chapters differ from the checked marker timeline')
        digest = _hash(temp)
        os.replace(temp, target)
    return dict(info, status='exported', sha256=digest)


def export(catalog, selected, output, *, archive=None, audio_dir=None, format='opus',
           premixed='both', pre_skip=312, skip_policy='verified-overlap', exact_chapters=False,
           overwrite=False, ffmpeg=None, ffprobe=None, timeout=1800, max_records=1000000,
           progress=None, catalog_path=None):
    try:
        output = os.fspath(output)
    except TypeError as exc:
        raise ValueError('radio output requires a directory path') from exc
    if not isinstance(output, str) or not output.strip() or '\0' in output:
        raise ValueError('radio output requires a nonempty directory path')
    if format not in FORMATS or premixed not in ('split', 'continuous', 'both'):
        raise ValueError('unsupported radio output format or premixed mode')
    if type(pre_skip) is not int or not 0 <= pre_skip <= 5760:
        raise ValueError('radio pre-skip must be 0..5760')
    if type(timeout) is not int or not 1 <= timeout <= 86400:
        raise ValueError('radio timeout must be 1..86400 seconds')
    if type(max_records) is not int or not 1 <= max_records <= 1000000:
        raise ValueError('radio per-bank work limit must be 1..1000000')
    if skip_policy not in ('zero', 'verified-overlap'):
        raise ValueError('unsupported radio skip policy')
    ffmpeg, ffprobe = _tool(ffmpeg, 'ffmpeg'), _tool(ffprobe, 'ffprobe')
    if bool(archive) == bool(audio_dir):
        raise ValueError('select one game audio archive or supplied --audio-dir')
    root = Path(output).resolve()
    if root.exists() and not root.is_dir():
        raise ValueError('radio --out must be a directory')
    protected = [p for p in (archive, catalog_path or radio_catalog.DEFAULT_CATALOG) if p]
    folders, playlist_names = set(), {'all stations'}
    if any(r.get('broadcast_cuts') for s in selected for r in s['recordings']):
        playlist_names.add('broadcast song cuts')
    for station in selected:
        folder = safe_name(station['name']).casefold()
        if folder in folders:
            raise ValueError('radio station names collide after filename normalization')
        folders.add(folder)
        labels = [station['name']]
        if any(r.get('acoustic_matches') for r in station['recordings']):
            labels.append(station['name'] + ' (identified excerpts)')
            labels.append(station['name'] + ' (identified locations)')
        if any(r.get('broadcast_cuts') for r in station['recordings']):
            labels.append(station['name'] + ' (broadcast song cuts)')
        if any(r['role'] == 'premixed' for r in station['recordings']):
            labels += [station['name'] + ' (continuous)', station['name'] + ' (chapter navigation)']
        if station['kind'] == 'premixed' and any(r['role'] != 'premixed' for r in station['recordings']):
            labels.append(station['name'] + ' (standalone tracks)')
        for label in labels:
            key = safe_name(label, 200).casefold()
            if key in playlist_names:
                raise ValueError('radio playlist names collide after filename normalization')
            playlist_names.add(key)
    if audio_dir and not Path(audio_dir).is_dir():
        raise ValueError('--audio-dir must be an existing directory')
    source_index = audio_index(audio_dir) if audio_dir else None
    report = dict(format='gta6x-radio-library-v1', catalog_sha256=catalog['sha256'],
        game_build=catalog['data'].get('game_build'), provenance=catalog['data']['provenance'],
        options=dict(format=format, premixed=premixed, pre_skip=pre_skip, skip_policy=skip_policy,
                     exact_chapters=exact_chapters), stations=[], failures=[],
        notes=['Station membership is supplied research, not independently decoded native membership.',
               'Playlist order is catalog/user order, not a recovered broadcast schedule.',
               'Unmatched TRACKIDs remain numeric; repeated IDs do not inherit names.',
               'Marker intervals may include overlapping songs; transition labels do not establish new musical cut points.',
               'Opus copy cuts follow packet boundaries; exact-chapters re-encodes splits.',
               'CUE indices use 75 Hz; exact marker positions are retained in JSON.',
               'chapters.txt uses the existing B2 text export convention, not a decoded native event type.'])
    report['tools'] = {name: _run([tool, '-version'], timeout).decode('utf-8', 'replace').splitlines()[0]
                       for name, tool in (('ffmpeg', ffmpeg), ('ffprobe', ffprobe))}
    def publish(path, data, failed=False):
        if failed and path.exists() and not overwrite:
            report.setdefault('preserved_outputs', []).append(path.relative_to(root).as_posix())
        else:
            _atomic(path, data)

    master, banks, naming, broadcast_master = [], {}, [], []
    # Reserve manifest paths before any media output. All output paths are derived
    # afresh from validated catalog text, never from an imported export report.
    for name in ('radio-library.json', 'radio-catalog.json', 'radio-names.json',
                 'credits-catalog.json', 'awc-names.json', 'awc-radio.json'):
        _target(root, name, protected)
    for station in selected:
        initial_failures = len(report['failures'])
        station_report = dict(key=station['key'], name=station['name'], kind=station['kind'],
                              context_type=station.get('context_type', 'station'),
                              requested=len(station['recordings']), files=[], playlists=[])
        report['stations'].append(station_report)
        playlist, continuous, virtual, standalone, identification_entries = [], [], [], [], []
        identification_locations = []
        broadcast_entries = []
        standalone_ordinal = 0
        # Named cuts join the playlist after ordinary tracks, irrespective of
        # requested source order. Process their spoken parents last so tags agree.
        recordings = sorted(station['recordings'], key=lambda r:
            r['role'] == 'non-song' and bool(r.get('broadcast_cuts')))
        for ordinal, recording in enumerate(recordings, 1):
            offset = recording['offset']
            is_mix = recording['role'] == 'premixed'
            is_standalone = station['kind'] == 'premixed' and not is_mix
            if is_standalone:
                standalone_ordinal += 1
            if progress:
                progress(f"{station['name']}: {ordinal}/{len(station['recordings'])} @0x{offset:x}")
            try:
                root.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(prefix='.gta6x-radio-', dir=root) as tmp:
                    sources = (_supplied(source_index, recording, ffprobe, timeout) if source_index is not None
                               else _extract(archive, recording, Path(tmp), pre_skip, skip_policy, max_records))
                    for source in sources:
                        if 'error' in source:
                            report['failures'].append(dict(station=station['name'], offset=offset,
                                stream_index=source['stream_index'], channel_index=source['channel_index'],
                                stage='channel', reason=source['error']))
                            continue
                        originals = protected + [source['path']]
                        check_recording_credit(recording, source)
                        observations = acoustic_matches(recording, source)
                        song_cuts = broadcast_cuts(recording, source)
                        ident = f"audio_{offset:09x}_s{source['stream_index']}_c{source['channel_index']}"
                        title = ('Continuous Broadcast' if is_mix and not recording.get('recording_credit')
                                 else recording['title'])
                        if recording['role'] == 'non-song':
                            title = f"Station segment {ordinal:03}"
                        artist = recording['artist']
                        stem = safe_name(station['name'] + ' - ' + (artist + ' - ' if artist else '') + title)
                        directory = Path('stations') / safe_name(station['name'])
                        if is_standalone:
                            directory /= 'standalone'
                        relative = directory / f'{stem} [{ident}].{FORMATS[format][0]}'
                        target = _target(root, relative, originals)
                        track = (len(standalone) + 1 if is_standalone else
                                 len(continuous) + 1 if is_mix and station['kind'] == 'premixed' else
                                 len(playlist) + 1)
                        tags = dict(title=title, artist=artist, album=station['name'],
                            album_artist=station['name'], genre='Radio',
                            track=str(track),
                            comment=f"gta6x research labels; audio.rpf @0x{offset:x}; source {source['source_sha256']}",
                            GTA6X_CATALOG_SHA256=catalog['sha256'], GTA6X_SOURCE_SHA256=source['source_sha256'],
                            GTA6X_AWC_OFFSET=f'0x{offset:x}', GTA6X_STREAM=str(source['stream_index']),
                            GTA6X_CHANNEL=str(source['channel_index']), GTA6X_LABEL_STATUS=recording['credit_status'],
                            GTA6X_ARTIST_ROLE=recording['artist_role'],
                            GTA6X_EXPORT_PROFILE='gta6x-radio-library-v1', GTA6X_OUTPUT_FORMAT=format,
                            GTA6X_PRE_SKIP='supplied audio timeline' if source.get('supplied_audio') else str(pre_skip),
                            GTA6X_SKIP_POLICY='supplied audio timeline' if source.get('supplied_audio') else skip_policy)
                        if recording.get('provisional'):
                            tags['GTA6X_CREDIT_PROVISIONAL'] = '1'
                        if recording.get('composer'):
                            tags['composer'] = recording['composer']
                        if observations:
                            tags['GTA6X_IDENTIFICATION_INDEX'] = 'fingerprint samples; not native song boundaries'
                        if recording.get('credit_conflicts'):
                            tags['GTA6X_CREDIT_CONFLICTS'] = '1'
                        if station.get('context_type', 'station') != 'station':
                            tags['GTA6X_CONTEXT_TYPE'] = station['context_type']
                        if recording.get('recording_credit'):
                            tags['GTA6X_CREDIT_SOURCE'] = recording['recording_credit']['source']
                        if recording.get('station_assignment'):
                            assignment = recording['station_assignment']
                            tags.update(GTA6X_STATION_STATUS=assignment['status'],
                                        GTA6X_STATION_METHOD=assignment['method'],
                                        GTA6X_STATION_SOURCE=assignment['source'])
                        if is_standalone:
                            tags['GTA6X_LIBRARY_VIEW'] = 'standalone'
                        if recording['credit_status'] == 'research_work_alias':
                            tags.update(composer=artist, GTA6X_ARTIST_ROLE=recording['artist_role'])
                        chapters = credited_chapters(recording, source)
                        if chapters != source['chapters']:
                            source = dict(source, raw_chapters=source['chapters'], chapters=chapters)
                        for ext in ('.json', '.cue', '.chapters.txt', '.ffmetadata'):
                            _target(root, str(relative) + ext, originals)
                        info = _render(source['path'], target, tags, chapters, format=format, ffmpeg=ffmpeg,
                            ffprobe=ffprobe, timeout=timeout, overwrite=overwrite)
                        entry = dict(path=str(target), station=station['name'], title=title, artist=artist,
                                     duration_s=info['duration_s'])
                        for observation in observations:
                            end = source['native_timing']['output_frames']
                            identification_locations.append(dict(entry,
                                title='Listen from: '+observation['title']+' (identified location)',
                                artist=observation['artist'], start_frames=observation['start_frames'],
                                end_frames=end, duration_s=(end-observation['start_frames'])/RATE))
                        detail = dict(recording, export_identity=tags,
                                      source={k: v for k, v in source.items() if k != 'path'},
                                      output=dict(path=relative.as_posix(), **info))
                        _json(str(target) + '.json', detail)
                        station_report['files'].append(detail)
                        naming.append(dict(archive=recording['archive'], awc_offset=offset,
                            stream_index=source['stream_index'], channel_index=source['channel_index'],
                            station=station['name'], title=title))
                        if source.get('awc_metadata') is not None:
                            banks[(recording['archive'], offset)] = dict(archive=recording['archive'], offset=offset,
                                size=source['awc_metadata']['size'], source_sha256=source['source_sha256'],
                                streams=source['awc_metadata']['stream_list'], radio=source['radio'])
                        if chapters:
                            detail['cue'] = dict(timebase_hz=75, intervals=min(99, len(chapters)),
                                omitted_intervals=max(0, len(chapters)-99),
                                evidence='Exact 48 kHz source positions remain in JSON/ffmetadata; CUE uses CD frames')
                            _atomic(str(target) + '.cue', cue_text(target.name, station['name'], chapters).encode('utf-8'))
                            _atomic(str(target) + '.ffmetadata', _ffmetadata(chapters).encode('utf-8'))
                            _atomic(str(target) + '.chapters.txt', awc_radio.chapter_text(
                                [c for c in chapters if c.get('track_id') is not None]).encode('utf-8'))
                        if observations and premixed != 'continuous':
                            for observation in observations:
                                number = len(identification_entries) + 1
                                excerpt_title = observation['title'] + ' (identified excerpt)'
                                excerpt_stem = safe_name(f"{number:03} - {station['name']} - {observation['artist']} - {excerpt_title}")
                                excerpt_rel = relative.parent / 'identified excerpts' / f'{excerpt_stem} [{ident}].{FORMATS[format][0]}'
                                excerpt_target = _target(root, excerpt_rel, originals)
                                excerpt_tags = dict(tags, title=excerpt_title, artist=observation['artist'], track=str(number),
                                    GTA6X_LABEL_STATUS=observation['method'], GTA6X_CREDIT_SOURCE=observation['source'],
                                    GTA6X_CREDIT_PROVISIONAL='1', GTA6X_LIBRARY_VIEW='identification_excerpt',
                                    GTA6X_INTERVAL=f"{observation['start_frames']}:{observation['end_frames']}",
                                    GTA6X_CUT_MODE='packet-copy' if format == 'opus' and not exact_chapters else 'decoded',
                                    GTA6X_BOUNDARY_SOURCE='fingerprint sample; not native song boundaries')
                                for key in ('GTA6X_ARTIST_ROLE', 'GTA6X_TRACKID', 'GTA6X_CREDIT_CONFLICTS'):
                                    excerpt_tags.pop(key, None)
                                if observation.get('credit_conflicts'):
                                    excerpt_tags['GTA6X_CREDIT_CONFLICTS'] = '1'
                                _target(root, str(excerpt_rel)+'.json', originals)
                                excerpt = _render(source['path'], excerpt_target, excerpt_tags, [], format=format,
                                    ffmpeg=ffmpeg, ffprobe=ffprobe, timeout=timeout, overwrite=overwrite,
                                    start=observation['start_frames'], end=observation['end_frames'], exact_chapters=exact_chapters)
                                excerpt_detail = dict(observation, title=excerpt_title, export_identity=excerpt_tags,
                                    provisional=True, credit_status=observation['method']+'_excerpt',
                                    boundary_source='fingerprint_sample', output=dict(path=excerpt_rel.as_posix(), **excerpt),
                                    timing_precision='packet-boundary copy' if format == 'opus' and not exact_chapters else 'decoded interval',
                                    requested_duration_s=(observation['end_frames']-observation['start_frames'])/RATE,
                                    duration_delta_s=excerpt['duration_s']-(observation['end_frames']-observation['start_frames'])/RATE)
                                _json(str(excerpt_target)+'.json', excerpt_detail)
                                detail.setdefault('identification_outputs', []).append(excerpt_detail)
                                identification_entries.append(dict(path=str(excerpt_target), station=station['name'],
                                    title=excerpt_title, artist=observation['artist'], duration_s=excerpt['duration_s']))
                            _json(str(target)+'.json', detail)
                        if song_cuts and premixed != 'continuous':
                            for song in song_cuts:
                                number = len(broadcast_entries) + 1
                                if recording['role'] == 'non-song':
                                    number += len(playlist)
                                boundary_source = ('transcription-guided estimate; not native song boundaries'
                                    if song['method'] == 'transcription_interval' else
                                    'listening-reviewed estimate; not native song boundaries'
                                    if song['method'] == 'listening_interval' else
                                    'fingerprint-guided estimate; not native song boundaries')
                                label = song['title'] + ' (broadcast cut)'
                                stem = safe_name(f"{number:03} - {station['name']} - {song['artist']} - {label}")
                                rel = relative.parent / 'broadcast song cuts' / f'{stem} [{ident}].{FORMATS[format][0]}'
                                cut_target = _target(root, rel, originals)
                                cut_tags = dict(tags, title=label, artist=song['artist'], track=str(number),
                                    GTA6X_LABEL_STATUS=song['method'], GTA6X_CREDIT_SOURCE=song['source'],
                                    GTA6X_CREDIT_PROVISIONAL='1', GTA6X_LIBRARY_VIEW='broadcast_song_cut',
                                    GTA6X_INTERVAL=f"{song['start_frames']}:{song['end_frames']}",
                                    GTA6X_BOUNDARY_SOURCE=boundary_source,
                                    GTA6X_BOUNDARY_STATUS='provisional',
                                    GTA6X_START_RANGE=':'.join(map(str, song['start_range_frames'])),
                                    GTA6X_END_RANGE=':'.join(map(str, song['end_range_frames'])),
                                    GTA6X_CUT_MODE='packet-copy' if format == 'opus' and not exact_chapters else 'decoded')
                                for key in ('GTA6X_ARTIST_ROLE', 'GTA6X_TRACKID', 'GTA6X_CREDIT_CONFLICTS'):
                                    cut_tags.pop(key, None)
                                if song.get('artist_role'):
                                    cut_tags['GTA6X_ARTIST_ROLE'] = song['artist_role']
                                if song.get('user_confirmation'):
                                    cut_tags['GTA6X_LISTENING_CONFIRMATION'] = 'song_identity'
                                if song.get('credit_conflicts'):
                                    cut_tags['GTA6X_CREDIT_CONFLICTS'] = '1'
                                _target(root, str(rel)+'.json', originals)
                                cut_info = _render(source['path'], cut_target, cut_tags, [], format=format,
                                    ffmpeg=ffmpeg, ffprobe=ffprobe, timeout=timeout, overwrite=overwrite,
                                    start=song['start_frames'], end=song['end_frames'], exact_chapters=exact_chapters)
                                cut_detail = dict(song, title=label, export_identity=cut_tags, provisional=True,
                                    credit_status=song['method'], boundary_source=song['method'],
                                    output=dict(path=rel.as_posix(), **cut_info),
                                    requested_duration_s=(song['end_frames']-song['start_frames'])/RATE,
                                    duration_delta_s=cut_info['duration_s']-(song['end_frames']-song['start_frames'])/RATE,
                                    timing_precision='packet-boundary copy' if format == 'opus' and not exact_chapters else 'decoded interval')
                                _json(str(cut_target)+'.json', cut_detail)
                                detail.setdefault('broadcast_cut_outputs', []).append(cut_detail)
                                broadcast_entries.append(dict(path=str(cut_target), station=station['name'], title=label,
                                    artist=song['artist'], duration_s=cut_info['duration_s']))
                            _json(str(target)+'.json', detail)
                        if recording['role'] == 'non-song' and recording.get('broadcast_cuts'):
                            # The original spoken program remains available separately.
                            # Only its named cuts join the normal listening playlist.
                            continuous.append(entry)
                            _json(str(target)+'.json', detail)
                            continue
                        if not is_mix:
                            (standalone if is_standalone else playlist).append(entry)
                            _json(str(target) + '.json', detail)
                            continue
                        continuous.append(entry)
                        if not chapters:
                            playlist.append(entry)
                            if observations:
                                detail['native_chapter_status'] = 'unavailable; identification samples are separate'
                            else:
                                report['failures'].append(dict(station=station['name'], offset=offset,
                                    stage='chapters', reason=source['chapter_association'], continuous_exported=True))
                        for i, chapter in enumerate(chapters, 1):
                            start, end = chapter['start_frames'], chapter['end_frames']
                            if end <= start:
                                report['failures'].append(dict(station=station['name'], offset=offset,
                                    stage='chapter', chapter=i, reason='zero-length marker interval'))
                                continue
                            label = chapter_title(chapter)
                            chapter_artist = chapter.get('artist', artist)
                            virtual.append(dict(entry, title=label, artist=chapter_artist, start_frames=start, end_frames=end,
                                                duration_s=(end-start)/RATE))
                            if premixed == 'continuous':
                                continue
                            chapter_rel = relative.parent / 'chapters' / f"{safe_name(f'{i:03} - '+station['name']+' - '+chapter_display(chapter))} [{ident}].{FORMATS[format][0]}"
                            chapter_target = _target(root, chapter_rel, originals)
                            chapter_tags = dict(tags, title=label, artist=chapter_artist, track=str(len(playlist) + 1), GTA6X_INTERVAL=f'{start}:{end}',
                                GTA6X_TRACKID=str(chapter.get('track_id', 'unknown')),
                                GTA6X_CUT_MODE='packet-copy' if format == 'opus' and not exact_chapters else 'decoded')
                            if chapter.get('credit_status'):
                                # A broadcast program credit does not describe a named track.
                                chapter_tags.pop('GTA6X_ARTIST_ROLE', None)
                                chapter_tags.pop('GTA6X_CREDIT_CONFLICTS', None)
                                chapter_tags.update(GTA6X_LABEL_STATUS=chapter['credit_status'],
                                    GTA6X_CREDIT_SOURCE=chapter['credit_source'], GTA6X_CREDIT_PROVISIONAL='1')
                            if chapter.get('credit_conflicts'):
                                chapter_tags['GTA6X_CREDIT_CONFLICTS'] = '1'
                            if chapter.get('reference_credit_method'):
                                chapter_tags['GTA6X_REFERENCE_CREDIT_METHOD'] = chapter['reference_credit_method']
                            _target(root, str(chapter_rel)+'.json', originals)
                            try:
                                cut = _render(source['path'], chapter_target, chapter_tags, [], format=format,
                                    ffmpeg=ffmpeg, ffprobe=ffprobe, timeout=timeout, overwrite=overwrite,
                                    start=start, end=end, exact_chapters=exact_chapters)
                            except (OSError, ValueError) as exc:
                                report['failures'].append(dict(station=station['name'], offset=offset,
                                    stage='chapter', chapter=i, reason=str(exc), continuous_exported=True))
                                continue
                            cut_detail = dict(chapter, export_identity=chapter_tags,
                                output=dict(path=chapter_rel.as_posix(), **cut),
                                timing_precision='packet-boundary copy' if format == 'opus' and not exact_chapters else 'decoded interval',
                                requested_duration_s=(end-start)/RATE,
                                duration_delta_s=cut['duration_s']-(end-start)/RATE)
                            _json(str(chapter_target)+'.json', cut_detail)
                            detail.setdefault('chapter_outputs', []).append(cut_detail)
                            playlist.append(dict(path=str(chapter_target), station=station['name'], title=label,
                                                 artist=chapter_artist, duration_s=cut['duration_s']))
                        _json(str(target) + '.json', detail)
            except (OSError, ValueError) as exc:
                report['failures'].append(dict(station=station['name'], offset=offset, reason=str(exc)))
                if progress:
                    progress(f"  skipped @0x{offset:x}: {exc}")
        if station['kind'] == 'premixed' and premixed == 'continuous':
            playlist = continuous
        playlist = playlist + broadcast_entries
        groups = [(station['name'], playlist)]
        if identification_entries:
            groups.append((station['name'] + ' (identified excerpts)', identification_entries))
        if broadcast_entries:
            groups.append((station['name'] + ' (broadcast song cuts)', broadcast_entries))
        if identification_locations:
            groups.append((station['name'] + ' (identified locations)', identification_locations))
        if continuous and (premixed == 'both' or premixed == 'continuous' and station['kind'] != 'premixed'):
            groups.append((station['name'] + ' (continuous)', continuous))
        if virtual:
            groups.append((station['name'] + ' (chapter navigation)', virtual))
        if standalone_ordinal:
            groups.append((station['name'] + ' (standalone tracks)', standalone))
        for label, entries in groups:
            for extension in ('.m3u8', '.m3u'):
                relative = Path('playlists') / (safe_name(label, 200) + extension)
                path = _target(root, relative, protected)
                publish(path, playlist_text(label, entries, path.parent).encode('utf-8'),
                        failed=len(report['failures']) > initial_failures)
                station_report['playlists'].append(relative.as_posix())
        master.extend(playlist)
        master.extend(standalone)
        broadcast_master.extend(broadcast_entries)
    for extension in ('.m3u8', '.m3u'):
        path = _target(root, 'playlists/All Stations' + extension, protected)
        publish(path, playlist_text('All Stations', master, path.parent).encode('utf-8'), failed=bool(report['failures']))
        if broadcast_master:
            path = _target(root, 'playlists/Broadcast Song Cuts' + extension, protected)
            publish(path, playlist_text('Broadcast Song Cuts', broadcast_master, path.parent).encode('utf-8'),
                    failed=bool(report['failures']))
    files = [f for s in report['stations'] for f in s['files']]
    cuts = [c for f in files for c in f.get('chapter_outputs', [])]
    excerpts = [c for f in files for c in f.get('identification_outputs', [])]
    broadcast = [c for f in files for c in f.get('broadcast_cut_outputs', [])]
    report['summary'] = dict(stations=len(selected), recordings=sum(s['requested'] for s in report['stations']),
        recording_exports=len(files), chapter_exports=len(cuts), exported_files=len(files)+len(cuts)+len(excerpts)+len(broadcast),
        reused_files=sum(f['output']['status'] == 'reused' for f in files+cuts+excerpts+broadcast),
        playlist_entries=len(master), failures=len(report['failures']))
    if excerpts:
        report['summary']['identification_exports'] = len(excerpts)
    if broadcast:
        report['summary']['broadcast_cut_exports'] = len(broadcast)
    report['status'] = 'partial' if report['failures'] else 'complete'
    metadata_outputs = {'radio-catalog.json': catalog['data'],
        'radio-names.json': radio_catalog.name_dictionary(catalog),
        'credits-catalog.json': radio_catalog.credit_catalog(catalog),
        'awc-names.json': dict(format='gta6x-awc-names-v1',
            source='Radio-library exact source labels from supplied research; native station membership unconfirmed', entries=naming),
        'awc-radio.json': list(banks.values())}
    for name, value in metadata_outputs.items():
        payload = (catalog['source_bytes'] if name == 'radio-catalog.json' and 'source_bytes' in catalog else
                   (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n').encode('utf-8'))
        publish(_target(root, name, protected),
                payload, failed=bool(report['failures']))
    _json(_target(root, 'radio-library.json', protected), report)
    return report
