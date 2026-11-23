"""Optional exact archive/offset/stream/channel naming map for AWC exports.

Supplied labels are external context, never a recovered native station graph.
Multiple contexts stay explicit and use the original offset-based filename.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def _text(value, label, limit):
    if not isinstance(value,str) or not value.strip() or len(value)>limit or not value.isprintable():
        raise ValueError('invalid AWC naming '+label)
    return value


def load(path):
    with Path(path).open('rb') as fh:raw=fh.read(8*1024*1024+1)
    if len(raw)>8*1024*1024:raise ValueError('AWC naming map exceeds byte limit')
    try:data=json.loads(raw)
    except (ValueError,UnicodeError,RecursionError) as exc:raise ValueError('invalid AWC naming JSON') from exc
    if not isinstance(data,dict) or data.get('format')!='gta6x-awc-names-v1':
        raise ValueError('unsupported AWC naming map format')
    source=_text(data.get('source'),'source',2048);entries=data.get('entries')
    if not isinstance(entries,list) or len(entries)>100000:
        raise ValueError('AWC naming entry count exceeds limit')
    index={}
    for row in entries:
        if not isinstance(row,dict):raise ValueError('invalid AWC naming entry')
        archive=_text(row.get('archive'),'archive',255)
        if archive in ('.','..') or '/' in archive or '\\' in archive:
            raise ValueError('AWC naming archive must be a basename')
        values=[row.get(k) for k in ('awc_offset','stream_index','channel_index')]
        for value,maximum in zip(values,(2**63-1,8191,31)):
            if type(value) is not int or not 0<=value<=maximum:raise ValueError('invalid AWC naming source address')
        item=dict(station=_text(row.get('station'),'station',512),
                  title=_text(row.get('title'),'title',512))
        bucket=index.setdefault((archive,*values),[])
        if item not in bucket:bucket.append(item)
        if len(bucket)>256:raise ValueError('AWC naming source has too many supplied contexts')
    for bucket in index.values():bucket.sort(key=lambda r:(r['station'],r['title']))
    return dict(index=index,source=source,sha256=hashlib.sha256(raw).hexdigest())


def _safe(text):
    return re.sub(r'[\\/:*?"<>|]','_',text).strip(' .') or 'unnamed'


def _short(text, limit):
    return text.encode('utf-8')[:limit].decode('utf-8','ignore').rstrip(' .')


def filename(mapping, archive, offset, stream_index, channel_index, extension):
    if extension not in ('opus','wav'):raise ValueError('unsupported AWC naming extension')
    stem=_short(_safe(Path(archive).stem),64) or 'archive'
    identity=f'{stem}_{offset:09x}_s{stream_index}_c{channel_index}'
    contexts=mapping['index'].get((archive,offset,stream_index,channel_index),[]) if mapping else []
    metadata=dict(status='unmapped',contexts=contexts,
        evidence='supplied external exact-source labels; native membership and recording identity unproven')
    if len(contexts)==1:
        label=_safe(contexts[0]['station'])+' - '+_safe(contexts[0]['title'])
        suffix=f' [{identity}].{extension}'
        name=_short(label,255-len(suffix.encode('utf-8')))+suffix
        metadata['status']='supplied_context'
    else:
        name=identity+'.'+extension
        if contexts:metadata['status']='ambiguous_supplied_contexts'
    if mapping:metadata.update(source=mapping['source'],map_sha256=mapping['sha256'])
    return name,metadata
