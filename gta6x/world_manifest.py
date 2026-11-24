"""Inspect confined complete-PSIN exports selected by a native export manifest.

Manifest labels do not authenticate source payloads. Each selected file is
rehashed and then checked by the existing direct native reader. Original archive
paths in export metadata are never opened, and separate files are never joined.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from . import world_resources

MAX_MANIFEST_BYTES = 8 * 1024 * 1024
MAX_FILES = 100000
MAX_BYTES = world_resources.MAX_INFLATED_BYTES
_SHA = re.compile(r'[0-9a-f]{64}\Z')


def _uint(value, maximum, label, minimum=0):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('invalid native manifest ' + label)
    return value


def _plain(path):
    """Permit OS temporary aliases, never user-created source symlinks."""
    path = Path(os.path.abspath(os.fspath(path)))
    aliases = {Path('/var'):Path('/private/var'), Path('/tmp'):Path('/private/tmp')}
    if any(p.is_symlink() and aliases.get(p) != p.resolve() for p in (path, *path.parents)):
        raise ValueError('native manifest input cannot traverse a symlink')
    return path.resolve()


def _regular(path):
    details = path.stat()
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise ValueError('native manifest inputs must be regular files without hardlink aliases')
    return details


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('native manifest has duplicate JSON keys')
        result[key] = value
    return result


def preflight(manifest_path, *, protected_outputs=(), consume=None):
    """Read bounded manifest metadata and stat confined files, without payload reads.

    Returned metadata is an inspection plan, not a persistent authenticated cache.
    ``inspect`` always builds and verifies its own plan. Output aliases are checked
    before any selected payload is opened. All exported rows, including those past
    a later resource limit, must have safe confined paths and bounded sizes.
    """
    charge = consume or (lambda n=1: None)
    if not isinstance(protected_outputs,(list,tuple)) or len(protected_outputs)>1024:
        raise ValueError('native manifest protected outputs must be a bounded path list')
    for output in protected_outputs:
        try: name=os.fspath(output)
        except TypeError as exc: raise ValueError('invalid native manifest protected output path')from exc
        if not isinstance(name,str)or not name or '\0'in name:
            raise ValueError('invalid native manifest protected output path')
    manifest = _plain(manifest_path)
    details = _regular(manifest)
    if not 1 <= details.st_size <= MAX_MANIFEST_BYTES:
        raise ValueError('native manifest JSON exceeds its byte limit or is empty')
    for output in protected_outputs:
        if os.path.realpath(output) == str(manifest) or (os.path.exists(output) and os.path.samefile(output, manifest)):
            raise ValueError('native manifest output aliases its manifest input')
    charge(1 + (details.st_size + 4095)//4096)
    with manifest.open('rb') as handle:
        encoded = handle.read(details.st_size + 1)
    if len(encoded) != details.st_size:
        raise ValueError('native manifest changed while reading')
    try:
        document = json.loads(encoded, object_pairs_hook=_object)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('invalid native manifest JSON') from exc
    if (not isinstance(document, dict) or document.get('format') != 'gta6x-native-world-export-v1'
            or document.get('status') != 'complete' or not isinstance(document.get('resources'), list)
            or len(document['resources']) > MAX_FILES):
        raise ValueError('native manifest requires a bounded complete native export manifest')
    charge(1 + len(document['resources']))
    files = []; skipped = []; paths = set(); identities = set(); total = 0
    for index, row in enumerate(document['resources']):
        if not isinstance(row, dict):
            raise ValueError('invalid native manifest resource row')
        if row.get('status') == 'skipped':
            reason = row.get('reason')
            if not isinstance(reason, str) or not reason or len(reason) > 4096 or '\0' in reason:
                raise ValueError('native manifest skipped entry requires a bounded reason')
            charge(1 + (len(reason)+63)//64)
            item = dict(manifest_index=index, status='skipped', reason=reason)
            if 'format' in row:
                if not isinstance(row['format'], str) or len(row['format']) > 32:
                    raise ValueError('invalid native manifest skipped format')
                item['format'] = row['format']
            skipped.append(item)
            continue
        if (row.get('status') != 'exported' or row.get('format') != 'psin'
                or row.get('checksum_verified') is not True or row.get('complete_format') is not True):
            raise ValueError('native manifest exported row must declare a complete checked PSIN')
        name = row.get('file')
        if (not isinstance(name, str) or not name or len(name) > 4096 or '\0' in name or '\\' in name
                or ':' in name or PurePosixPath(name).is_absolute() or
                any(part in ('', '.', '..') for part in name.split('/')) or PurePosixPath(name).suffix != '.psin'):
            raise ValueError('native manifest export path must be confined and relative')
        charge(1 + (len(name)+63)//64)
        path = _plain(manifest.parent/name)
        if not path.is_relative_to(manifest.parent):
            raise ValueError('native manifest export escapes its directory')
        info = _regular(path)
        if str(path) in paths or (info.st_dev, info.st_ino) in identities:
            raise ValueError('native manifest repeats an exported source')
        paths.add(str(path)); identities.add((info.st_dev, info.st_ino))
        size = _uint(row.get('bytes'), world_resources.MAX_RESOURCE_BYTES, 'resource size', 1)
        digest = row.get('sha256')
        if not isinstance(digest, str) or not _SHA.fullmatch(digest):
            raise ValueError('invalid native manifest source SHA-256')
        if info.st_size != size:
            raise ValueError('native manifest source size differs from its record')
        if size > MAX_BYTES-total:
            raise ValueError('native manifest source set exceeds its byte limit')
        total += size
        for output in protected_outputs:
            if os.path.realpath(output) == str(path) or (os.path.exists(output) and os.path.samefile(output, path)):
                raise ValueError('native manifest output aliases an exported input')
        files.append(dict(manifest_index=index, file=str(path), relative_file=name, bytes=size, sha256=digest))
    summary = document.get('summary')
    expected = dict(resources_exported=len(files), resources_skipped=len(skipped), resources_refused=0, exported_bytes=total)
    if not isinstance(summary, dict) or any(type(summary.get(k)) is not int or summary[k] != v for k,v in expected.items()):
        raise ValueError('native manifest summary differs from its resource rows')
    return dict(file=str(manifest), sha256=hashlib.sha256(encoded).hexdigest(), bytes=len(encoded),
                files=files, skipped=skipped, exported_bytes=total)


def inspect(manifest_path, *, max_nodes=100000, scan_bytes=8*1024*1024,
            max_resources=0, max_inflated_bytes=MAX_BYTES, protected_outputs=(), **native_options):
    """Rehash selected exports and invoke the unchanged bounded raw native reader.

    The resource limit selects a leading subset of exported rows; uninspected rows
    and skipped declarations remain visible. Budget or source-change failure returns
    no catalogue. Hash verification adds one bounded read per selected file; both
    that allowance and native reader work share ``max_nodes``. Source sizes share
    the native 64-MiB cap, with at most 64 MiB of additional verification reads.
    """
    _uint(max_nodes, 2_000_000, 'node limit', 1)
    _uint(scan_bytes, world_resources.MAX_SCAN_BYTES, 'scan byte limit', 1)
    _uint(max_resources, 1_000_000, 'resource limit')
    _uint(max_inflated_bytes, MAX_BYTES, 'decoded byte limit', 1)
    # Reject unknown/unsafe options before manifest or source reads. The delegated
    # reader validates the remaining view-specific values before payload reads.
    allowed = {'with_schemas','dictionary','structure_hash','field_hash','type_word','with_links','with_value_words',
               'with_extent_diagnostics','with_primitive_layouts','with_reference_context','context_records'}
    if set(native_options)-allowed:
        raise ValueError('unsupported native manifest inspection option')
    if type(native_options.get('with_value_words', False)) is not bool:
        raise ValueError('native manifest with_value_words must be boolean')
    for key in ('structure_hash','field_hash','type_word'):
        if native_options.get(key) is not None:
            _uint(native_options[key],0xffffffff,key)
    dictionary = native_options.get('dictionary')
    if dictionary is not None and (not isinstance(dictionary,dict) or any(
            not isinstance(dictionary.get(key,{}),dict) for key in ('hashes','exact'))):
        raise ValueError('native manifest names require hash/exact dictionary objects')
    queries = native_options.get('context_records',())
    if (not isinstance(queries,(list,tuple)) or len(queries)>32 or any(
            not isinstance(pair,(list,tuple)) or len(pair)!=2 or any(
                type(value)is not int or not 0<=value<=0xffffffff for value in pair) for pair in queries)):
        raise ValueError('native manifest context queries require at most 32 unsigned block/record pairs')
    used = 0
    def charge(amount=1):
        nonlocal used
        if type(amount) is not int or amount < 0 or amount > max_nodes-used:
            raise world_resources.WorldResourceLimitError('native manifest inspection exceeds shared node budget')
        used += amount
    plan = preflight(manifest_path, protected_outputs=protected_outputs, consume=charge)
    selected = plan['files'][:max_resources] if max_resources else plan['files']
    uninspected = plan['files'][len(selected):]
    if not selected:
        raise ValueError(f"manifest contains no complete PSIN exports ({len(plan['skipped'])} skipped entries)")
    total = sum(row['bytes'] for row in selected)
    if total > max_inflated_bytes or total > world_resources.MAX_SCAN_BYTES or any(row['bytes'] > scan_bytes for row in selected):
        raise world_resources.WorldResourceLimitError('native manifest selected inputs exceed shared source/decoded byte limits')
    # Charge all verification reads before accessing the first selected payload.
    charge(sum(1 + (row['bytes']+4095)//4096 for row in selected))
    for row in selected:
        digest = hashlib.sha256()
        with open(row['file'],'rb') as handle:
            left = row['bytes']
            while left:
                chunk = handle.read(min(left,1024*1024))
                if not chunk: raise ValueError('native manifest source was truncated during verification')
                digest.update(chunk);left -= len(chunk)
            if handle.read(1): raise ValueError('native manifest source grew during verification')
        if digest.hexdigest() != row['sha256']:
            raise ValueError('native manifest source hash differs from its record')
    overhead = used
    if used >= max_nodes:
        raise world_resources.WorldResourceLimitError('native manifest has no remaining native-reader work budget')
    report = world_resources.inspect_sources([row['file'] for row in selected],raw_resources=True,
        max_nodes=max_nodes-used,scan_bytes=scan_bytes,max_resources=0,
        max_inflated_bytes=max_inflated_bytes,**native_options)
    used += report['summary']['metadata_nodes']
    if (len(report['resources']) != len(selected) or report['summary']['resources_refused'] or
            report['summary']['unclassified_streams']):
        raise ValueError('native manifest file is not a complete supported PSIN source')
    for expected, actual in zip(selected,report['resources']):
        if (actual['sha256'] != expected['sha256'] or actual['format'] != 'psin'
                or not actual.get('complete_format') or not actual.get('checksum_verified')):
            raise ValueError('native manifest source changed or failed native PSIN verification')
    report['manifest_input'] = dict(format='gta6x-native-world-manifest-input-v1',file=plan['file'],
        sha256=plan['sha256'], status='partial' if uninspected else 'complete',
        coverage_complete=not uninspected, selected=selected, skipped=plan['skipped'], uninspected=uninspected,
        source_archive_metadata_reopened=False,
        interpretation='Manifest-selected file hashes and fresh native parsing only; no archive allocation, world or asset ownership claim.',
        summary=dict(exported_rows=len(plan['files']),selected_files=len(selected),skipped_rows=len(plan['skipped']),
                     uninspected_files=len(uninspected),verified_bytes=total,verification_nodes=overhead))
    report['summary'].update(metadata_nodes=used,manifest_verification_nodes=overhead,manifest_verification_bytes=total)
    if uninspected:
        report['status'] = 'partial'
        if report['archives']: report['archives'][-1]['resource_limit_reached'] = True
    return report
