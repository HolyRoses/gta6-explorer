"""Inspect explicit native 0DRP metadata files without searching or joining.

Reports are regenerated from the exact immutable bytes read. A supported
metadata layout does not establish an animation identity, complete resource
endpoint, native integrity checksum, provider or decoded animation semantics.
"""
from __future__ import annotations

import hashlib
import os
import stat

from . import anim_resources

MAX_FILES = 256
DEFAULT_INPUT_BYTES = 64 * 1024 * 1024
MAX_INPUT_BYTES = 256 * 1024 * 1024
MAX_NODES = 2_000_000


class AnimationInputLimitError(anim_resources.ResourceLimitError):
    """An entire offline inspection cannot fit the selected work limits."""


def _limit(value, upper, label):
    if type(value) is not int or not 1 <= value <= upper:
        raise ValueError(f'{label} must be an integer from 1 to {upper}')


def _path(value):
    try:
        path = os.fspath(value)
    except TypeError as exc:
        raise ValueError('animation resource inputs/outputs require text paths') from exc
    if not isinstance(path, str) or not path or '\0' in path:
        raise ValueError('animation resource inputs/outputs require nonempty text paths')
    return path


def inspect_files(paths, *, max_nodes=100000, max_input_bytes=DEFAULT_INPUT_BYTES,
                  expected_sha256=None, protected_outputs=()):
    """Inspect one or more complete supplied byte sequences, or raise ValueError.

    All path, regular-file, alias and aggregate-size preflights precede payload
    reads. A malformed file, hash mismatch, changed input or budget exhaustion
    refuses the whole query rather than returning successful preceding files.
    Metadata's own ``partial`` status is retained: the supported 0DRP profile
    declares no total resource length or checksum. No source is carved, joined,
    scanned for an inner header, or written.

    ``max_nodes`` shares input rows, one verification unit per started 4 KiB,
    and the existing parser's exact metadata node counts across all sources.
    Optional hashes identify caller-known bytes, not their game provenance.
    ``protected_outputs`` lets a caller preflight its later report destination.
    """
    _limit(max_nodes, MAX_NODES, 'animation resource node limit')
    _limit(max_input_bytes, MAX_INPUT_BYTES, 'animation resource byte limit')
    if not isinstance(paths, (list, tuple)) or not 1 <= len(paths) <= MAX_FILES:
        raise ValueError('select 1..256 raw animation resource files')
    if not isinstance(protected_outputs, (list, tuple)):
        raise ValueError('protected animation outputs require a path sequence')
    paths = tuple(_path(path) for path in paths)
    outputs = tuple(_path(path) for path in protected_outputs)
    if expected_sha256 is None:
        expected = (None,) * len(paths)
    else:
        if (not isinstance(expected_sha256, (list, tuple))
                or len(expected_sha256) != len(paths)
                or any(not isinstance(h, str) or len(h) != 64
                       or any(c not in '0123456789abcdef' for c in h)
                       for h in expected_sha256)):
            raise ValueError('expected hashes require one lowercase SHA-256 per input')
        expected = tuple(expected_sha256)

    output_paths = {os.path.realpath(path) for path in outputs}
    output_ids = set()
    for path in outputs:
        try:
            info = os.stat(path)
        except FileNotFoundError:
            continue
        output_ids.add((info.st_dev, info.st_ino))
    plan, identities, total_bytes = [], set(), 0
    for path, digest in zip(paths, expected):
        info = os.stat(path)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('raw animation resource input must be a regular file')
        identity = info.st_dev, info.st_ino
        if identity in identities:
            raise ValueError('duplicate or aliased animation resource input')
        if identity in output_ids or os.path.realpath(path) in output_paths:
            raise ValueError('animation inspection output would overwrite an input')
        if info.st_size > anim_resources.MAX_RESOURCE:
            raise AnimationInputLimitError('raw animation resource exceeds source byte limit')
        total_bytes += info.st_size
        if total_bytes > max_input_bytes:
            raise AnimationInputLimitError('animation resource inputs exceed aggregate byte limit')
        identities.add(identity)
        plan.append((path, info.st_size, identity, digest))
    used = 1 + len(plan) + sum(max(1, (size + 4095) // 4096)
                               for _, size, _, _ in plan)
    if used >= max_nodes:
        raise AnimationInputLimitError('animation input verification exceeds node limit')

    rows = []
    metadata_nodes = 0
    for path, size, identity, expected_hash in plan:
        with open(path, 'rb') as stream:
            current = os.fstat(stream.fileno())
            if (not stat.S_ISREG(current.st_mode)
                    or (current.st_dev, current.st_ino) != identity
                    or current.st_size != size):
                raise ValueError('animation input identity or size changed after preflight')
            data = stream.read(size + 1)
        if len(data) != size:
            raise ValueError('animation input size changed during read')
        digest = hashlib.sha256(data).hexdigest()
        if expected_hash is not None and digest != expected_hash:
            raise ValueError('animation input differs from its expected SHA-256')
        remaining = max_nodes - used
        if remaining < 1:
            raise AnimationInputLimitError('animation resource inspection exceeds node limit')
        try:
            metadata = anim_resources.parse_resource(data, max_nodes=remaining)
        except anim_resources.ResourceLimitError as exc:
            raise AnimationInputLimitError(str(exc)) from exc
        used += metadata['summary']['nodes']
        metadata_nodes += metadata['summary']['nodes']
        rows.append(dict(file=path, bytes=size, sha256=digest,
                         expected_sha256_verified=expected_hash is not None,
                         status=metadata['status'], metadata=metadata,
                         allocation_end=None, complete_format=False))
    return dict(format='gta6x-raw-animation-resource-inspection-v1', status='partial',
                files=rows,
                summary=dict(files=len(rows), input_bytes=total_bytes,
                             work_nodes=used, metadata_nodes=metadata_nodes),
                archive_search_performed=False, sources_joined=False,
                saved_metadata_trusted=False, native_checksum_verified=False,
                interpretation='Bounded 0DRP metadata from explicit file bytes only; '
                'resource endpoints, animation identity, providers, field types and '
                'curves remain unconfirmed.')
