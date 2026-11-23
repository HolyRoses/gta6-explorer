"""Optional supplied music-credit hypotheses, matched by the complete hash B.

Catalog text is external metadata, never native playlist evidence. No public
track list is bundled. Truncated AWC stream IDs are never sufficient to match.
"""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from . import names

MAX_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 100000
MAX_ALIASES = 256


class CatalogLimitError(ValueError):
    pass


def budget(limit=100000):
    if type(limit) is not int or not 1<=limit<=1000000:
        raise ValueError('catalog max_nodes must be an integer from 1 to 1000000')
    used=0
    def consume(n=1):
        nonlocal used
        if used+n>limit:raise CatalogLimitError('music catalog annotations exceed node limit')
        used+=n
    return consume


def _text(value, label, limit):
    if not isinstance(value,str) or not 1<=len(value)<=limit or not value.isprintable():
        raise ValueError(f'invalid music catalog {label}')
    return value


def parse_catalog(data):
    """Validate explicit spelling hypotheses; preserve all distinct credits."""
    if not isinstance(data,dict) or data.get('format')!='gta6x-music-catalog-v1':
        raise ValueError('unsupported music catalog format')
    source=_text(data.get('source'),'source',2048)
    rows=data.get('entries')
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_ENTRIES:
        raise ValueError('music catalog entry count exceeds supported bounds')
    index={};seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('invalid music catalog entry')
        spelling=_text(row.get('normalized_name'),'normalized_name',256)
        if not spelling.isascii():raise ValueError('music catalog normalized_name must be explicit ASCII')
        title=_text(row.get('title'),'title',512)
        artist=_text(row.get('artist'),'artist',512)
        station=_text(row.get('station'),'station',256)
        key=names.joaat(spelling)
        identity=key,spelling,title,artist,station
        if identity in seen:continue
        seen.add(identity)
        index.setdefault(key,[]).append(dict(normalized_name=spelling,title=title,
            artist=artist,station=station,source=source))
        if len(index[key])>MAX_ALIASES:
            raise ValueError('music catalog has too many aliases for one hash')
    return dict(source=source,index=index,entry_count=len(seen))


def load_catalog(path):
    with Path(path).open('rb') as fh:raw=fh.read(MAX_BYTES+1)
    if len(raw)>MAX_BYTES:raise ValueError('music catalog input exceeds byte limit')
    try:data=json.loads(raw)
    except (ValueError,UnicodeError,RecursionError) as exc:raise ValueError('invalid music catalog JSON') from exc
    result=parse_catalog(data)
    result['sha256']=hashlib.sha256(raw).hexdigest()
    return result


def annotate(record, catalog, *, consume=None):
    """Add opt-in candidate metadata; never select one ambiguous credit."""
    if consume is None:consume=budget()
    consume()
    value=record['hash_b']
    if isinstance(value,str):
        try:key=int(value,16)
        except ValueError as exc:raise ValueError('invalid music record hash B') from exc
    else:key=value
    if type(key) is not int or not 0<=key<=0xffffffff:
        raise ValueError('music record hash B must be a complete 32-bit value')
    grouped={}
    for row in catalog['index'].get(key,[]):
        consume(2)
        identity=row['title'],row['artist'],row['station'],row['source']
        item=grouped.setdefault(identity,dict(title=row['title'],artist=row['artist'],
            station=row['station'],source=row['source'],normalized_names=[]))
        if row['normalized_name'] not in item['normalized_names']:item['normalized_names'].append(row['normalized_name'])
    matches=sorted(grouped.values(),key=lambda r:(r['station'],r['title'],r['artist']))
    for row in matches:row['normalized_names'].sort()
    status='unmatched' if not matches else 'ambiguous' if len(matches)>1 else 'hash_match'
    return dict(record,catalog_match_status=status,catalog_matches=matches,
        catalog_evidence='matching rule: complete 32-bit hash B equality with supplied spelling; external song/station hypotheses only; native membership and playback order unproven')
