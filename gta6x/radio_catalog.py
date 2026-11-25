"""Portable radio research metadata, distinct from native station authority."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import unicodedata

from . import names

DEFAULT_CATALOG = Path(__file__).with_name('data') / 'radio_catalog.json'
MAX_BYTES = 16 * 1024 * 1024


def _text(value, label, maximum=1024, empty=False):
    if (not isinstance(value, str) or len(value) > maximum
            or not empty and not value.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('invalid radio catalog ' + label)
    return value


def _uint(value, label, maximum=2**63-1):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ValueError('invalid radio catalog ' + label)
    return value


def _context_alias(value):
    return 'vcrr' if value == 'vice city rap radio' else value


def _credit_alternatives(credit):
    if type(credit.get('credit_conflicts', False)) is not bool:
        raise ValueError('invalid radio credit conflict flag')
    alternatives = credit.get('alternatives', [])
    if not isinstance(alternatives, list) or len(alternatives) > 16:
        raise ValueError('invalid radio credit alternatives')
    for alternative in alternatives:
        if not isinstance(alternative, dict):
            raise ValueError('invalid radio credit alternative')
        for key in ('title', 'artist', 'source', 'credit_context'):
            _text(alternative.get(key), 'credit alternative ' + key, 2048)


def parse(data):
    if not isinstance(data, dict) or data.get('format') != 'gta6x-radio-catalog-v1':
        raise ValueError('unsupported radio catalog format')
    if not isinstance(data.get('provenance'), dict):
        raise ValueError('radio catalog requires provenance')
    _text(data['provenance'].get('station_membership'), 'station membership evidence', 4096)
    stations, recordings, spellings = (data.get(k) for k in ('stations', 'recordings', 'names'))
    if (not isinstance(stations, list) or not 1 <= len(stations) <= 256
            or not isinstance(recordings, list) or len(recordings) > 20000
            or not isinstance(spellings, list) or len(spellings) > 20000):
        raise ValueError('radio catalog tables exceed supported counts')
    by_offset = {}
    for row in recordings:
        if not isinstance(row, dict):
            raise ValueError('invalid radio recording')
        offset = _uint(row.get('offset'), 'recording offset')
        if offset in by_offset:
            raise ValueError('duplicate radio recording offset')
        archive = _text(row.get('archive'), 'archive', 255)
        if Path(archive).name != archive or '/' in archive or '\\' in archive or archive in ('.', '..'):
            raise ValueError('radio archive must be a basename')
        if row.get('role') not in ('music', 'non-song', 'premixed', 'unclassified'):
            raise ValueError('unsupported radio recording role')
        text = _text(row.get('native_name'), 'native name', 512, empty=True)
        hint = row.get('duration_hint_s')
        if hint is not None and (type(hint) not in (int, float) or not math.isfinite(hint) or not 0 < hint <= 86400):
            raise ValueError('invalid radio duration hint')
        if 'hash_b' in row:
            if row['hash_b'] != f'0x{names.joaat(text):08x}' or not text:
                raise ValueError('radio native name differs from its full hash')
        chapters = row.get('reference_chapters', [])
        if not isinstance(chapters, list) or len(chapters) > 10000:
            raise ValueError('invalid radio reference chapters')
        previous = -1
        for chapter in chapters:
            if not isinstance(chapter, dict):
                raise ValueError('invalid radio reference chapter')
            start = _uint(chapter.get('start_frames'), 'chapter start', 0xffffffff)
            end = _uint(chapter.get('end_frames'), 'chapter end', 0xffffffff)
            _uint(chapter.get('track_id'), 'chapter TRACKID', 0xffffffff)
            if start < previous or end < start:
                raise ValueError('radio reference chapter intervals overlap or descend')
            for key in ('title', 'artist'):
                if key in chapter:
                    _text(chapter[key], 'reference chapter ' + key, 512, empty=key == 'artist')
            previous = end
        credits = row.get('chapter_credits', [])
        if not isinstance(credits, list) or len(credits) > 10000:
            raise ValueError('invalid radio chapter credits')
        seen_credits = set()
        for credit in credits:
            if not isinstance(credit, dict) or credit.get('method') not in ('audio_fingerprint', 'user_reported_fingerprint', 'user_supplied_label'):
                raise ValueError('unsupported radio chapter credit method')
            identity = tuple(_uint(credit.get(k), 'chapter credit ' + k, 0xffffffff)
                             for k in ('stream_index', 'channel_index', 'index'))
            if identity in seen_credits:
                raise ValueError('duplicate radio chapter credit')
            seen_credits.add(identity)
            for key in ('track_id', 'start_frames', 'end_frames'):
                _uint(credit.get(key), 'chapter credit ' + key, 0xffffffff)
            if credit['end_frames'] <= credit['start_frames']:
                raise ValueError('invalid radio chapter credit interval')
            for key in ('title', 'artist', 'source', 'evidence'):
                _text(credit.get(key), 'chapter credit ' + key, 4096 if key == 'evidence' else 2048 if key == 'source' else 512)
            if not isinstance(credit.get('source_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', credit['source_sha256']):
                raise ValueError('invalid radio chapter credit source hash')
            _credit_alternatives(credit)
            if credit.get('reference_credit_method', 'audio_fingerprint') not in (
                    'audio_fingerprint', 'native_config_hash', 'local_fingerprint', 'backend_fingerprint'):
                raise ValueError('unsupported radio chapter reference credit method')
        credit = row.get('recording_credit')
        if credit is not None:
            if (not isinstance(credit, dict) or credit.get('method') not in ('audio_fingerprint', 'native_config_hash')
                    or credit.get('status') != 'provisional'):
                raise ValueError('unsupported radio recording credit')
            for key in ('stream_index', 'channel_index', 'channel_id'):
                _uint(credit.get(key), 'recording credit ' + key, 0xffffffff)
            for key in ('title', 'artist', 'source', 'evidence'):
                _text(credit.get(key), 'recording credit ' + key,
                      2048 if key in ('source', 'evidence') else 512)
            if 'composer' in credit:
                _text(credit['composer'], 'recording credit composer', 512)
            if not isinstance(credit.get('source_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', credit['source_sha256']):
                raise ValueError('invalid radio recording credit source hash')
            if credit['method'] == 'native_config_hash':
                _uint(credit.get('config_id'), 'recording config ID', 0xffffffff)
                duration_ms = _uint(credit.get('duration_ms'), 'recording config duration', 86400000)
                if (not row.get('hash_b') or credit.get('config_hash32') != row['hash_b']
                        or credit['channel_id'] != (int(row['hash_b'], 16) & 0x1fffffff)
                        or hint is None or abs(hint-duration_ms/1000) > .05):
                    raise ValueError('recording config hash/channel/duration lead is inconsistent')
            _credit_alternatives(credit)
        by_offset[offset] = row
        observations = row.get('acoustic_matches', [])
        if not isinstance(observations, list) or len(observations) > 10000:
            raise ValueError('invalid radio acoustic match list')
        seen_observations = set()
        for observation in observations:
            if (not isinstance(observation, dict) or observation.get('status') != 'provisional'
                    or observation.get('method') not in ('local_fingerprint', 'backend_fingerprint')):
                raise ValueError('invalid radio acoustic match')
            identity = tuple(_uint(observation.get(k), 'acoustic match '+k, 0xffffffff)
                             for k in ('stream_index', 'channel_index', 'channel_id', 'start_frames', 'end_frames'))
            if identity in seen_observations or not 0 < identity[-1]-identity[-2] <= 30*48000:
                raise ValueError('invalid or duplicate radio acoustic sample bounds')
            seen_observations.add(identity)
            if (not isinstance(observation.get('source_sha256'), str)
                    or not re.fullmatch('[0-9a-f]{64}', observation['source_sha256'])):
                raise ValueError('invalid radio acoustic source hash')
            for key in ('title', 'artist', 'source', 'evidence'):
                _text(observation.get(key), 'acoustic match '+key, 2048 if key in ('source', 'evidence') else 512)
            if 'track_id' in observation:
                raise ValueError('acoustic windows cannot assign native TRACKIDs')
            if credit and any(observation[key] != credit[key] for key in
                    ('source_sha256', 'stream_index', 'channel_index', 'channel_id')):
                raise ValueError('acoustic match differs from the selected recording source/channel')
            _credit_alternatives(observation)
        cuts = row.get('broadcast_cuts', [])
        if (not isinstance(cuts, list) or len(cuts) > 10000
                or cuts and row['role'] not in ('premixed', 'non-song')):
            raise ValueError('invalid radio broadcast cuts')
        seen_cuts = set()
        for cut in cuts:
            if (not isinstance(cut, dict) or cut.get('status') != 'provisional'
                    or cut.get('method') not in ('fingerprint_interval', 'transcription_interval', 'listening_interval')
                    or 'track_id' in cut):
                raise ValueError('invalid radio broadcast cut provenance')
            identity = tuple(_uint(cut.get(k), 'broadcast cut '+k, 0xffffffff)
                             for k in ('stream_index', 'channel_index', 'channel_id', 'start_frames', 'end_frames'))
            if identity in seen_cuts or not 0 < identity[-1]-identity[-2] <= 1800*48000:
                raise ValueError('invalid or duplicate radio broadcast cut bounds')
            seen_cuts.add(identity)
            if not isinstance(cut.get('source_sha256'), str) or not re.fullmatch('[0-9a-f]{64}', cut['source_sha256']):
                raise ValueError('invalid radio broadcast cut source hash')
            for key in ('title', 'artist', 'source', 'evidence'):
                _text(cut.get(key), 'broadcast cut '+key, 2048 if key in ('source', 'evidence') else 512)
            if 'artist_role' in cut:
                _text(cut['artist_role'], 'broadcast cut artist role', 512)
            ranges = []
            for key in ('start_range_frames', 'end_range_frames'):
                value = cut.get(key)
                if not isinstance(value, list) or len(value) != 2:
                    raise ValueError('invalid radio broadcast boundary range')
                ranges.extend(_uint(n, 'broadcast boundary range', 0xffffffff) for n in value)
            start_lo, start_hi, end_lo, end_hi = ranges
            if not start_lo <= cut['start_frames'] <= start_hi < end_lo <= cut['end_frames'] <= end_hi:
                raise ValueError('inconsistent radio broadcast boundary ranges')
            keys = ('source_sha256', 'stream_index', 'channel_index', 'channel_id')
            if credit and any(cut[k] != credit[k] for k in keys):
                raise ValueError('broadcast cut differs from the selected recording source/channel')
            confirmation = cut.get('user_confirmation')
            if confirmation is not None:
                if (not isinstance(confirmation, dict)
                        or confirmation.get('method') != 'user_reported_listening_comparison'
                        or confirmation.get('scope') != 'song_identity'
                        or confirmation.get('title') != cut['title']):
                    raise ValueError('invalid broadcast song listening confirmation')
                _text(confirmation.get('evidence'), 'listening confirmation evidence', 2048)
            if cut['method'] == 'fingerprint_interval':
                if not any(all(o[k] == cut[k] for k in keys + ('title', 'artist'))
                           and start_hi <= o['start_frames'] < o['end_frames'] <= end_lo for o in observations):
                    raise ValueError('broadcast cut requires an enclosed source-bound acoustic sample')
            elif cut['method'] == 'listening_interval':
                if confirmation is None:
                    raise ValueError('listening interval requires a song identity confirmation')
            else:
                evidence = cut.get('title_evidence')
                if (not isinstance(evidence, dict) or evidence.get('method') != 'local_transcription'
                        or set(evidence) != {'method', 'phrase_role', 'start_frames', 'end_frames', 'matched_phrase'}
                        or evidence.get('phrase_role') not in ('sung_title', 'spoken_introduction', 'spoken_segment_title')):
                    raise ValueError('broadcast cut requires local title transcription evidence')
                a, b = (_uint(evidence.get(k), 'title evidence '+k, 0xffffffff)
                        for k in ('start_frames', 'end_frames'))
                if not start_hi <= a < b <= end_lo or b-a > 30*48000:
                    raise ValueError('broadcast title evidence exceeds the enclosed interval')
                _text(evidence.get('matched_phrase'), 'transcribed title phrase', 128)
            _credit_alternatives(cut)
    keys, display_names = set(), set()
    for station in stations:
        if not isinstance(station, dict):
            raise ValueError('invalid radio station')
        key = _text(station.get('key'), 'station key', 256)
        name = _text(station.get('name'), 'station name', 256)
        if key.casefold() in keys or name.casefold() in display_names:
            raise ValueError('duplicate radio station key/name')
        keys.add(key.casefold()); display_names.add(name.casefold())
        if station.get('kind') not in ('music', 'talk', 'premixed', 'unassigned'):
            raise ValueError('unsupported radio station kind')
        if station.get('context_type', 'station') not in ('station', 'public_show', 'public_playlist', 'collection'):
            raise ValueError('unsupported radio context type')
        members = station.get('members')
        if not isinstance(members, list) or len(members) > 20000:
            raise ValueError('invalid radio station member list')
        for offset in members:
            _uint(offset, 'station member')
            if offset not in by_offset:
                raise ValueError('radio station references missing recording')
        if len(set(members)) != len(members):
            raise ValueError('duplicate radio station member')
    for row in recordings:
        assignment = row.get('station_assignment')
        if assignment is None:
            continue
        if (not isinstance(assignment, dict) or assignment.get('method') not in ('audio_fingerprint', 'public_tracklist')
                or assignment.get('status') != 'provisional'):
            raise ValueError('unsupported radio station assignment')
        for field in ('station_key', 'source', 'evidence'):
            _text(assignment.get(field), 'station assignment ' + field, 2048)
        if not any(s['key'] == assignment['station_key'] and row['offset'] in s['members']
                   for s in stations):
            raise ValueError('radio station assignment differs from membership')
    credit_index, work_index, alias_index = {}, {}, {}
    for row in spellings:
        if not isinstance(row, dict):
            raise ValueError('invalid radio name entry')
        text = _text(row.get('text'), 'spelling', 512)
        hashed = names.joaat(text)
        if row.get('hash32') != f'0x{hashed:08x}' or row.get('hash29') != f'0x{hashed & 0x1fffffff:08x}':
            raise ValueError('radio name hash does not match its spelling')
        if row.get('kind') not in ('credit_song_name', 'observed_song_name', 'station_key', 'research_work_alias', 'research_title_alias'):
            raise ValueError('unsupported radio spelling kind')
        _text(row.get('title'), 'display title', 512)
        _text(row.get('source'), 'source', 2048)
        preferred = row.get('preferred_for', [])
        if not isinstance(preferred, list) or len(preferred) > 256:
            raise ValueError('invalid preferred radio credit contexts')
        for context in preferred:
            _text(context, 'preferred credit context', 256)
            if context.casefold() not in display_names:
                raise ValueError('preferred radio credit references missing station')
        if len({s.casefold() for s in preferred}) != len(preferred):
            raise ValueError('duplicate preferred radio credit context')
        if preferred:
            if row['kind'] not in ('credit_song_name', 'research_work_alias', 'research_title_alias'):
                raise ValueError('preferred radio spelling has no artist credit')
            _text(row.get('selection_evidence'), 'preferred credit evidence', 2048)
        if row['kind'] in ('credit_song_name', 'research_work_alias', 'research_title_alias'):
            _text(row.get('artist'), 'credit artist', 512)
            _text(row.get('credit_context'), 'credit context', 512)
            if row['kind'] == 'research_title_alias':
                if row.get('status') != 'provisional':
                    raise ValueError('radio title aliases must remain provisional')
                _text(row.get('evidence'), 'title alias evidence', 2048)
            index = {'credit_song_name': credit_index, 'research_work_alias': work_index,
                     'research_title_alias': alias_index}[row['kind']]
            bucket = index.setdefault(hashed, [])
            if len(bucket) >= 256:
                raise ValueError('too many radio credits for one hash')
            bucket.append(row)
    unknown = data.get('unassigned_offsets', [])
    if not isinstance(unknown, list) or len(unknown) > 20000:
        raise ValueError('invalid unassigned radio table')
    for offset in unknown:
        _uint(offset, 'unassigned offset')
    public = data.get('public_tracks', [])
    if not isinstance(public, list) or len(public) > 20000:
        raise ValueError('invalid public radio track list')
    for row in public:
        if not isinstance(row, dict) or row.get('status') != 'public_list_only':
            raise ValueError('public radio tracks must remain unlinked list entries')
        for key in ('context', 'title', 'artist', 'source'):
            _text(row.get(key), 'public track ' + key, 2048 if key == 'source' else 512,
                  empty=key == 'artist' and row.get('artist_role') == 'performer unknown')
        if row.get('artist_role') not in ('credited artist', 'credited composer; performer unknown', 'performer unknown'):
            raise ValueError('invalid public radio artist role')
        sources = row.get('additional_sources', [])
        if not isinstance(sources, list) or len(sources) > 16:
            raise ValueError('invalid public radio additional sources')
        for source in sources:
            _text(source, 'public track additional source', 2048)
        if len(set(sources)) != len(sources) or row['source'] in sources:
            raise ValueError('duplicate public radio source')
        if any(key in row for key in ('offset', 'track_id', 'hash_b')):
            raise ValueError('public radio lists cannot assign native identities')
    return dict(data=data, by_offset=by_offset, credit_index=credit_index,
                work_index=work_index, alias_index=alias_index)


def load(path=None):
    with Path(DEFAULT_CATALOG if path is None else path).open('rb') as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('radio catalog exceeds byte limit')
    try:
        result = parse(json.loads(raw))
    except (UnicodeError, RecursionError) as exc:
        raise ValueError('invalid radio catalog JSON') from exc
    result['sha256'] = hashlib.sha256(raw).hexdigest()
    result['source_bytes'] = raw
    return result


def _artist_key(text):
    text = unicodedata.normalize('NFKD', text.casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'\b(?:feat|ft|featuring)\b', '', text)
    return re.sub(r'[\W_]', '', text)


def label(catalog, recording, station=None):
    """Display credit research with explicit context/variant/conflict evidence."""
    raw_name = recording['native_name']
    bucket = catalog['credit_index'].get(int(recording.get('hash_b', '0'), 16), [])
    work_alias = False
    title_alias = False
    if not bucket:
        bucket = catalog['work_index'].get(int(recording.get('hash_b', '0'), 16), [])
        work_alias = bool(bucket)
    if not bucket:
        bucket = catalog['alias_index'].get(int(recording.get('hash_b', '0'), 16), [])
        title_alias = bool(bucket)
    identities = {(r['title'], r['artist']) for r in bucket}
    preferred = [r for r in bucket if station and station.casefold() in
                 [s.casefold() for s in r.get('preferred_for', [])]]
    contexts = [r for r in bucket if station and r['credit_context'].casefold() == station.casefold()]
    choices = preferred or contexts or bucket
    artists = {_artist_key(r['artist']) for r in choices}
    chosen = None
    selection = 'single credited title'
    if choices and (preferred or len(artists) > 1):
        # A usable public credit is preferable to suppressing every artist.
        # Curated station choices win; otherwise prefer direct public sources
        # and fuller credits, with stable text ordering as the final tie break.
        def priority(row):
            source = row['source'].lower()
            public = 0 if 'vice.com/' in source else 1 if 'rockstargames.com/' in source else 2
            return public, -len(row['artist']), -len(row['title']), row['artist'], row['title']
        chosen = min(choices, key=priority)
        title, artist = chosen['title'], chosen['artist']
        status = 'preferred_public_credit' if preferred else 'selected_credit'
        selection = chosen.get('selection_evidence', 'public source priority, then fuller credit; alternatives retained')
    elif len(artists) == 1:
        chosen = min(choices, key=lambda r: (len(r['title']), r['title'].isupper(), r['title'], r['artist']))
        title, artist = chosen['title'], chosen['artist']
        status = ('research_title_alias' if title_alias else 'research_work_alias' if work_alias else 'station_context_credit'
                  if contexts and len({_artist_key(r['artist']) for r in bucket}) > 1 else
                  'unique_full_hash_credit' if len(identities) == 1 else 'credit_spelling_variants')
        selection = 'shortest credited title; variants/versions remain alternatives' if len(identities)>1 else selection
    else:
        title = raw_name.replace('_', ' ').title() or 'Unidentified segment'
        artist = ('Various Artists' if recording['role'] == 'premixed' else
                  station if recording['role'] == 'non-song' and station else 'Unknown Artist')
        status = 'unmatched_credit'
    result = dict(title=title, artist=artist, native_name=raw_name,
                credit_status=status, credit_alternatives=bucket,
                credit_conflicts=len({_artist_key(r['artist']) for r in bucket}) > 1,
                title_selection=selection,
                selected_credit=chosen,
                artist_role='credited composer; performer unknown' if work_alias else
                    'supplied credit artist' if chosen else 'station/program credit'
                    if artist != 'Unknown Artist' else 'unidentified performer',
                provisional=title_alias or bool(preferred) or len(artists)>1,
                evidence='Research labels and complete name-hash equality; recording identity unconfirmed')
    observation = recording.get('recording_credit')
    if observation:
        result.update(title=observation['title'], artist=observation['artist'],
                      credit_status='audio_fingerprint_match' if observation['method']=='audio_fingerprint'
                          else 'native_config_hash_match', provisional=True,
                      selected_credit=observation, artist_role='supplied credit artist',
                      title_selection='source-bound '+('acoustic observation' if observation['method']=='audio_fingerprint'
                                                       else 'native config hash lead'),
                      evidence=observation['evidence'])
        result['credit_conflicts'] |= observation.get('credit_conflicts', False)
        result['credit_alternatives'] = bucket + observation.get('alternatives', [])
        if 'composer' in observation:
            result.update(composer=observation['composer'], artist_role='credited performer')
    return result


def public_credits(catalog, contexts=(), songs=(), *, maximum=None, order='catalog'):
    """Unordered public lists, including titles without a native identity link."""
    if order not in ('catalog', 'title', 'artist'):
        raise ValueError('unsupported radio ordering')
    if maximum is not None and (type(maximum) is not int or maximum < 1):
        raise ValueError('radio --max must be positive')
    rows = catalog['data'].get('public_tracks', [])
    if contexts:
        available = {r['context'] for r in rows}
        chosen = set()
        for query in contexts:
            query = _text(query, 'public context filter', 512).strip().casefold()
            matches = {c for c in available if c.casefold() == query}
            matches = matches or {c for c in available if _context_alias(c.casefold()) == _context_alias(query)}
            matches = matches or {c for c in available if query in c.casefold()}
            if not matches:
                raise ValueError('no public radio context matches ' + repr(query))
            chosen.update(matches)
        rows = [r for r in rows if r['context'] in chosen]
    queries = [_text(q, 'song filter', 512).strip().casefold() for q in songs]
    if queries:
        rows = [r for r in rows if any(q in (r['title'] + ' ' + r['artist']).casefold() for q in queries)]
        if not rows:
            raise ValueError('no public radio credits match the song filter')
    if order != 'catalog':
        rows = sorted(rows, key=lambda r: (r['context'], r[order].casefold(), r['title']))
    if maximum is not None:
        counts, limited = {}, []
        for row in rows:
            count = counts.get(row['context'], 0)
            if count < maximum:
                limited.append(row)
            counts[row['context']] = count + 1
        rows = limited
    return rows


def name_dictionary(catalog):
    """Compatibility with the existing names lookup command; aliases stay plural."""
    hashes = {}
    for row in catalog['data']['names']:
        source = row['kind'] + ': ' + row['source']
        pair = [row['text'], source]
        bucket = hashes.setdefault(row['hash32'][2:], [])
        if pair not in bucket:
            bucket.append(pair)
    return dict(format='gta6x-radio-name-dictionary-v1', hashes=hashes, exact={}, hashes64={},
                catalog_sha256=catalog['sha256'], evidence='Name preimages only; native meanings unconfirmed')


def credit_catalog(catalog):
    return dict(format='gta6x-music-catalog-v1',
        source='Bundled public-credit research; external labels, not native station membership',
        entries=[dict(normalized_name=r['text'], title=r['title'], artist=r['artist'],
                      station=r['credit_context'], source=r['source'])
                 for r in catalog['data']['names'] if r['kind'] == 'credit_song_name'])


def select(catalog, stations=(), *, include_imaging=False, include_unassigned=False,
           maximum=None, order='catalog', songs=()):
    if order not in ('catalog', 'title', 'artist'):
        raise ValueError('unsupported radio ordering')
    if maximum is not None and (type(maximum) is not int or maximum < 1):
        raise ValueError('radio --max must be positive')
    selected = catalog['data']['stations']
    song_queries = [_text(q, 'song filter', 512).strip().casefold() for q in songs]
    if stations:
        chosen = set()
        for query in stations:
            query = _text(query, 'station filter', 256).strip().casefold()
            exact = [s for s in selected if query in (s['key'].casefold(), s['name'].casefold())]
            exact = exact or [s for s in selected if _context_alias(s['name'].casefold()) == _context_alias(query)]
            matches = exact or [s for s in selected if query in s['key'].casefold() or query in s['name'].casefold()]
            if not matches:
                raise ValueError('no radio station matches ' + repr(query))
            chosen.update(s['key'] for s in matches)
        selected = [s for s in selected if s['key'] in chosen]
    result = []
    for station in selected:
        items = []
        for offset in station['members']:
            row = catalog['by_offset'][offset]
            if (not include_imaging and station['kind'] == 'music'
                    and row['role'] not in ('music', 'premixed') and not row.get('broadcast_cuts')):
                continue
            items.append(dict(row, **label(catalog, row, station['name'])))
            if station.get('context_type', 'station') != 'station':
                items[-1]['provisional'] = True
        if song_queries:
            matching = []
            for row in items:
                alternatives = [c for c in row['credit_alternatives']
                    if row['credit_status'] == 'ambiguous_credits'
                    or row.get('recording_credit') and row['credit_conflicts']
                    or _artist_key(c['artist']) == _artist_key(row['artist'])]
                text = ' '.join([row['title'], row['artist'], row.get('composer', ''), row['native_name'], row.get('hash_b', '')]
                    + [v for c in alternatives for v in (c['title'], c['artist'])]
                    + [v for c in row.get('broadcast_cuts', []) for v in (c['title'], c['artist'])]).casefold()
                if any(q in text for q in song_queries):
                    matching.append(row)
            items = matching
        if order != 'catalog':
            items.sort(key=lambda r: (r[order].casefold(), r['title'].casefold(), r['offset']))
        if maximum is not None:
            items = items[:maximum]
        result.append(dict(station, recordings=items))
    if song_queries:
        result = [s for s in result if s['recordings']]
        if not result:
            raise ValueError('no radio recordings match the song filter')
    if include_unassigned and not song_queries:
        rows = [catalog['by_offset'].get(o, dict(archive='audio.rpf', offset=o, role='unclassified', native_name=''))
                for o in catalog['data'].get('unassigned_offsets', [])]
        if maximum is not None:
            rows = rows[:maximum]
        result.append(dict(key='unassigned', name='Unassigned', kind='unassigned',
                           recordings=[dict(r, **label(catalog, r)) for r in rows]))
    return result
