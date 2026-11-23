"""Export complete PSIN sources from a native world catalogue.

Every encoded span is reread and checked; catalogue JSON alone is not source
identity or joining authority. 0DRP metadata and opaque streams have no known
complete resource endpoint and are explicitly skipped. No new joins are made.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import zlib

from . import psin, psin_blocks, psin_schema

MAX_BYTES = 64 * 1024 * 1024
MAX_RESOURCE = 16 * 1024 * 1024
MAX_NODES = 2_000_000
PAGE = 65536
_SHA = re.compile(r'[0-9a-f]{64}\Z')


class ExportLimitError(ValueError):
    """The complete export exceeds its shared work or byte budget."""


def _uint(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError('invalid native export ' + label)
    return value


def _digest(value):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError('invalid native export SHA-256')
    return value


def validate_output(output_dir, sources, protected=()):
    """Reject existing output and symlink/alias paths before source reads.

    Missing parents are allowed during preflight; the caller must create the
    parent before export. This function creates no directory or file.
    """
    destination = Path(os.path.abspath(os.fspath(output_dir)))
    aliases = {Path('/var'):Path('/private/var'), Path('/tmp'):Path('/private/tmp')}
    if any(path.is_symlink() and aliases.get(path) != path.resolve()
           for path in (destination, *destination.parents)):
        raise ValueError('native export output cannot traverse a symlink')
    if destination.exists():
        raise ValueError('native export output directory must not already exist')
    if any(parent.exists() and not parent.is_dir() for parent in destination.parents):
        raise ValueError('native export output parent must be a directory')
    for path in (*sources, *protected):
        source = Path(path)
        if destination == source.absolute() or destination.resolve() == source.resolve():
            raise ValueError('native export output aliases an input')
        if source.exists() and destination in source.resolve().parents:
            raise ValueError('native export output contains an input')
    return destination


def _inflate(encoded, expected):
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(encoded, expected + 1)
    except zlib.error as exc:
        raise ValueError('native export zlib checksum or body refused') from exc
    if (not decoder.eof or decoder.unconsumed_tail or decoder.unused_data
            or len(raw) != expected):
        raise ValueError('native export encoded span is cut, trailing or has wrong output size')
    return raw


def export_resources(report, output_dir, *, max_nodes=100000, max_bytes=MAX_BYTES,
                     max_compressed_bytes=MAX_BYTES, consume=None):
    """Reread and export complete PSINs; unsupported resources are skipped.

    Work is charged before reads/decompression/parsing. One shared byte budget
    bounds all retained output, another all compressed reads. Integrity, source
    changes and budget errors raise before output creation. A new directory is
    claimed exclusively; each file is published atomically without replacement,
    and the manifest is published last. Existing outputs are never overwritten.
    """
    _uint(max_nodes, 1, MAX_NODES, 'node limit')
    _uint(max_bytes, 1, MAX_BYTES, 'inflated byte limit')
    _uint(max_compressed_bytes, 1, MAX_BYTES, 'compressed byte limit')
    if (not isinstance(report, dict) or report.get('format') != 'gta6x-native-world-resources-v1'
            or not isinstance(report.get('resources'), list)
            or not isinstance(report.get('archives'), list)):
        raise ValueError('native export requires a fresh native world catalogue')
    callback = consume
    nodes = 0
    def charge(count=1):
        nonlocal nodes
        if count > max_nodes-nodes:
            raise ExportLimitError('native export exceeds shared node budget')
        if callback is not None:
            callback(count)
        nodes += count
    charge(1+len(report['archives'])+len(report['resources']))
    windows = {}
    for row in report['archives']:
        if not isinstance(row, dict) or not isinstance(row.get('file'), str):
            raise ValueError('invalid native export archive identity')
        file = os.path.realpath(row['file'])
        start = _uint(row.get('start'), 0, (1 << 63)-1, 'window start')
        end = _uint(row.get('end'), start, (1 << 63)-1, 'window end')
        windows.setdefault(file, []).append((start,end))
    destination = validate_output(output_dir, windows)
    rows = []; plans = []; compressed = total = 0; spans = {}
    for index, resource in enumerate(report['resources']):
        if not isinstance(resource, dict):
            raise ValueError('invalid native export resource row')
        row = dict(resource_index=index, format=resource.get('format'), status='skipped')
        rows.append(row)
        if resource.get('format') != 'psin':
            row['reason'] = 'complete resource endpoint unknown; metadata prefixes are not exported'
            continue
        file = resource.get('source_file')
        if not isinstance(file, str) or os.path.realpath(file) not in windows:
            raise ValueError('native export resource has no catalogued source window')
        file = os.path.realpath(file)
        if type(resource.get('checksum_verified')) is not bool or not resource['checksum_verified']:
            raise ValueError('native export requires a checked PSIN resource')
        digest = _digest(resource.get('sha256'))
        size = _uint(resource.get('inflated_bytes'), 1, MAX_RESOURCE, 'resource size')
        offset = _uint(resource.get('offset'), 0, (1 << 63)-1, 'resource offset')
        segments = resource.get('segments')
        if not isinstance(segments, list) or not segments or len(segments) > MAX_RESOURCE//PAGE+1:
            raise ValueError('invalid native export PSIN segments')
        charge(len(segments))
        selected = []; expected_total = 0; previous = None
        for segment in segments:
            if not isinstance(segment, dict) or not isinstance(segment.get('file'), str):
                raise ValueError('invalid native export segment identity')
            if os.path.realpath(segment['file']) != file:
                raise ValueError('native export PSIN segments cross source files')
            at = _uint(segment.get('offset'), 0, (1 << 63)-1, 'segment offset')
            length = _uint(segment.get('compressed_bytes'), 8, MAX_BYTES, 'compressed span')
            inflated = _uint(segment.get('inflated_bytes'), 1, MAX_RESOURCE, 'segment inflated size')
            sha = _digest(segment.get('sha256'))
            if not any(begin <= at < at+length <= end for begin,end in windows[file]):
                raise ValueError('native export encoded span escapes its source window')
            if previous is None:
                if at != offset:
                    raise ValueError('native export first segment offset differs')
            elif (previous['inflated_bytes'] != PAGE or inflated > PAGE
                    or at != ((previous['offset']+previous['compressed_bytes']+15)&~15)):
                raise ValueError('native export PSIN segments lack exact page framing')
            if length > max_compressed_bytes-compressed or inflated > max_bytes-total:
                raise ExportLimitError('native export exceeds shared byte budget')
            compressed += length; total += inflated; expected_total += inflated
            plan = dict(offset=at,compressed_bytes=length,inflated_bytes=inflated,sha256=sha)
            selected.append(plan); previous = plan
            spans.setdefault(file, []).append((at,at+length))
        if expected_total != size:
            raise ValueError('native export resource size differs from its segments')
        plans.append((file,size,digest,selected,row))
    for file, intervals in spans.items():
        ordered = sorted(intervals)
        if any(a[1] > b[0] for a,b in zip(ordered,ordered[1:])):
            raise ValueError('native export source spans overlap or are duplicated')
        if ordered[-1][1] > os.path.getsize(file):
            raise ValueError('native export source is truncated')
    # Charge all byte/hash/inflate work before the first payload read.
    charge(3*((total+4095)//4096)+(compressed+4095)//4096)
    payloads = []
    for file,size,digest,segments,row in plans:
        pieces = []; previous = None
        with open(file,'rb') as handle:
            for segment in segments:
                at = segment['offset']
                if previous is not None:
                    begin = previous['offset']+previous['compressed_bytes']
                    handle.seek(begin); padding = handle.read(at-begin)
                    if len(padding) != at-begin or any(padding):
                        raise ValueError('native export PSIN page padding is not zero')
                handle.seek(at); encoded = handle.read(segment['compressed_bytes'])
                if len(encoded) != segment['compressed_bytes']:
                    raise ValueError('native export encoded source was truncated')
                raw = _inflate(encoded,segment['inflated_bytes'])
                if hashlib.sha256(raw).hexdigest() != segment['sha256']:
                    raise ValueError('native export inflated segment identity changed')
                if previous is not None and (raw[:4] in (b'PSIN',b'RBF0',b'MoVE')
                        or raw[16:20] == b'0DRP' or raw.lstrip().startswith(b'<?xml')):
                    raise ValueError('native export continuation has an independent format marker')
                pieces.append(raw); previous = segment
        raw = b''.join(pieces)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('native export assembled resource identity changed')
        sections = psin._sections_tile(raw)
        if sections is None:
            raise ValueError('native export PSIN sections do not tile the exact source')
        charge(1+sum((s.length-8+15)//16 for s in sections if s.tag in ('LSCH','LENM')))
        # Charge actual table entries, not opaque block payload as descriptors.
        position = 8
        while position+8 <= sections[0].length and raw[position:position+8] != b'pppppppp':
            charge()
            if position+16 > sections[0].length or raw[position+8:position+16] != b'\xaa'*8:
                raise ValueError('native export PSIN block table is unsupported')
            position += 16
        charge()
        psin_schema.parse_schema(raw)
        psin_blocks.parse_blocks(raw[:sections[0].length])
        filename = f"{row['resource_index']:06d}-{digest[:16]}.psin"
        row.update(status='exported',file=filename,source_file=file,offset=segments[0]['offset'],
                   sha256=digest,bytes=len(raw),segments=segments,checksum_verified=True,
                   complete_format=True,archive_allocation_endpoint=None)
        payloads.append((filename,raw))
    for key in ('unclassified_streams','refused_streams'):
        extra = report.get(key, [])
        if not isinstance(extra, list):
            raise ValueError('invalid native export unsupported-stream inventory')
        charge(len(extra))
        for index, item in enumerate(extra):
            if not isinstance(item, dict):
                raise ValueError('invalid native export unsupported-stream row')
            rows.append(dict(catalog_section=key,catalog_index=index,status='skipped',
                             reason='no complete checked PSIN resource'))
    manifest = dict(format='gta6x-native-world-export-v1',status='complete',
        interpretation='Complete source-verified PSIN containers only; unknown allocation endpoints and unsupported streams remain explicit.',
        resources=rows,summary=dict(resources_exported=len(payloads),
            resources_skipped=sum(row['status']=='skipped' for row in rows),resources_refused=0,
            exported_bytes=total,compressed_bytes=compressed,nodes=nodes))
    encoded_manifest = (json.dumps(manifest,indent=2)+'\n').encode('utf-8')
    if len(encoded_manifest) > 8*1024*1024:
        raise ExportLimitError('native export manifest exceeds byte limit')
    validate_output(destination,windows)
    if not destination.parent.is_dir():
        raise ValueError('native export parent directory must exist before export')
    # Stage outside the final directory. Hardlink publication is atomic and
    # unlike rename never replaces a concurrently created destination file.
    published = []; created = False
    with tempfile.TemporaryDirectory(prefix='.native-world-',dir=destination.parent) as staging:
        stage = Path(staging)
        for filename,raw in [*payloads,('manifest.json',encoded_manifest)]:
            with (stage/filename).open('xb') as handle: handle.write(raw)
        try:
            destination.mkdir(); created = True
            for filename,_ in [*payloads,('manifest.json',encoded_manifest)]:
                os.link(stage/filename,destination/filename)
                published.append((destination/filename,(stage/filename).stat().st_ino))
        except OSError:
            for path,inode in reversed(published):
                try:
                    if path.lstat().st_ino == inode and not path.is_symlink(): path.unlink()
                except OSError: pass
            if created:
                try: destination.rmdir()
                except OSError: pass
            raise
    return manifest
