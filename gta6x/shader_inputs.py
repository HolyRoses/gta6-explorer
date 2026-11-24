"""Bounded offline DXContainer inspection from immutable selected file bytes.

Files are explicit inputs, not archive hints or trusted saved metadata. Every
report is regenerated from the bytes actually read; source identity does not
establish original game provenance, integrity-digest validity or resource roles.
"""
from __future__ import annotations

import hashlib
import os
import stat

from . import shader_bindings, shaders

MAX_FILES = 4096
MAX_SOURCE_BYTES = shaders.MAX_SHADER
MAX_INPUT_BYTES = 256 * 1024 * 1024
DEFAULT_INPUT_BYTES = 64 * 1024 * 1024
MAX_TOTAL_RECORDS = 2_000_000


class ShaderInputLimitError(ValueError):
    """A complete raw-input query cannot fit its explicit processing limits."""


def _uint(value, upper, name, lower=1):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f'{name} must be an integer from {lower} to {upper}')


def _path(value):
    try:
        result = os.fspath(value)
    except TypeError as exc:
        raise ValueError('shader inputs and outputs must be filesystem paths') from exc
    if not isinstance(result, str) or not result or '\x00' in result:
        raise ValueError('shader inputs and outputs must be nonempty text paths')
    return result


def inspect_files(paths, *, with_bindings=False, stage_code=None, register_space=None,
                  register_index=None, type_code=None, with_psv_signatures=False,
                  with_psv_masks=False, with_features=False, max_records=4096,
                  max_total_records=100000, max_input_bytes=DEFAULT_INPUT_BYTES,
                  protected_outputs=(), expected_sha256=None):
    """Inspect selected raw files without carving, archive search or file writes.

    One whole-query budget includes input rows, bounded hashing/read allowances,
    and actual metadata/query records. An unresolved native reader does not
    expose its consumed work: conservatively charge its complete allocated cap.
    Aggregate exhaustion raises without a successful report prefix. Per-source
    malformed/unsupported metadata remains a labeled row, never a zero result.

    Optional expected hashes pin caller-known file bytes; they do not authorize
    parsed metadata. Output conflicts and all stat/byte preflights precede reads.
    """
    _uint(max_records, shader_bindings.MAX_RECORDS, 'per-source record limit')
    _uint(max_total_records, MAX_TOTAL_RECORDS, 'aggregate record limit')
    _uint(max_input_bytes, MAX_INPUT_BYTES, 'aggregate input byte limit')
    options = (with_bindings, with_psv_signatures, with_psv_masks, with_features)
    if any(type(value) is not bool for value in options):
        raise ValueError('shader inspection options must be booleans')
    query = dict(stage_code=stage_code, register_space=register_space,
                 register_index=register_index, type_code=type_code)
    if any(value is not None and (type(value) is not int or not 0 <= value <= 0xffffffff)
           for value in query.values()):
        raise ValueError('binding filters must be unsigned 32-bit integers')
    with_bindings = with_bindings or any(value is not None for value in query.values())
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_FILES:
        raise ValueError('select 1..4096 raw shader files')
    if not isinstance(protected_outputs, (list, tuple)):
        raise ValueError('protected outputs must be a path sequence')
    paths = tuple(_path(path) for path in paths)
    outputs = tuple(_path(path) for path in protected_outputs)
    if expected_sha256 is not None:
        if (not isinstance(expected_sha256, (list, tuple)) or len(expected_sha256) != len(paths)
                or any(not isinstance(value, str) or len(value) != 64
                       or any(c not in '0123456789abcdef' for c in value) for value in expected_sha256)):
            raise ValueError('expected hashes must be one lowercase SHA-256 per selected file')
        expected_sha256 = tuple(expected_sha256)
    else:
        expected_sha256 = (None,) * len(paths)

    output_paths = {os.path.realpath(path) for path in outputs}
    output_ids = set()
    for output in outputs:
        try:
            info = os.stat(output)
        except FileNotFoundError:
            continue
        output_ids.add((info.st_dev, info.st_ino))
    plan = []
    identities = set()
    total_bytes = 0
    for path, expected in zip(paths, expected_sha256):
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('raw shader input must be a regular file')
        identity = info.st_dev, info.st_ino
        if identity in identities:
            raise ValueError('duplicate or aliased raw shader input')
        if os.path.realpath(path) in output_paths or identity in output_ids:
            raise ValueError('shader inspection output would overwrite an input')
        if info.st_size > MAX_SOURCE_BYTES:
            raise ShaderInputLimitError('raw shader input exceeds the bounded container size')
        identities.add(identity)
        total_bytes += info.st_size
        plan.append((path, info.st_size, expected))
    if total_bytes > max_input_bytes:
        raise ShaderInputLimitError('raw shader inputs exceed aggregate byte limit')
    used = 1 + len(plan) + sum(max(1, (size + 4095) // 4096) for _, size, _ in plan)
    if used >= max_total_records:
        raise ShaderInputLimitError('raw shader input verification exceeds aggregate record budget')
    records = []
    metadata_options = dict(with_psv_signatures=with_psv_signatures,
                            with_psv_masks=with_psv_masks, with_features=with_features)
    declarations = matches = incomplete = conservative = 0
    for path, size, expected in plan:
        cap = min(max_records, max_total_records - used)
        if cap < 1:
            raise ShaderInputLimitError('raw shader inspection exceeds aggregate record budget')
        with open(path, 'rb') as source:
            data = source.read(size + 1)
        if len(data) != size:
            raise ValueError('raw shader source size changed after preflight')
        source_hash = hashlib.sha256(data).hexdigest()
        if expected is not None and source_hash != expected:
            raise ValueError('raw shader source differs from its expected SHA-256')
        if with_bindings:
            view = shader_bindings.inspect(data, max_records=cap, **query, **metadata_options)
            status, reasons, spent = view['status'], view['reasons'], view['record_count']
            metadata = view.pop('metadata')
            row = dict(file=path, bytes=size, sha256=source_hash, status=status,
                       metadata=metadata, bindings=view, reasons=list(reasons))
            declarations += view['summary'].get('declaration_count', 0)
            matches += view['summary'].get('matched_count', 0)
        else:
            metadata = shaders.metadata(data, max_records=cap, **metadata_options)
            status, reasons, spent = metadata['status'], metadata['reasons'], metadata['record_count']
            row = dict(file=path, bytes=size, sha256=source_hash, status=status,
                       metadata=metadata, reasons=list(reasons))
        if status == 'unresolved' and not spent:
            if any('budget exceeded' in reason for reason in reasons):
                raise ShaderInputLimitError('raw shader source inspection exceeds its record budget')
            # The old reader has no exposed failed-work counter. Charging its
            # whole allowance keeps aggregate work bounded without guessing it.
            spent = cap
            conservative += 1
        used += spent
        incomplete += status != 'complete'
        records.append(row)
    summary = dict(files=len(records), input_bytes=total_bytes, metadata_incomplete=incomplete,
                   record_count=used, conservative_failed_sources=conservative)
    if with_bindings:
        summary.update(binding_declarations=declarations, binding_matches=matches)
    return dict(format='gta6x-raw-shader-inspection-v1', status='partial' if incomplete else 'complete',
                files=records, summary=summary, archive_search_performed=False,
                saved_metadata_trusted=False, integrity_hash_verified=False,
                scope='Explicit raw DXContainer bytes only; no original game provenance or resource identity claim.')
