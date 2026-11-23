"""World/map extraction through the optional SixNG backend.

The native parsers cover containers, textures, audio, shaders and XML/PSIN;
the world data (placements, collision, navmesh, road graph, lights, interiors,
meta/PSO and vehicles) is decoded by SixNG's readers. This module maps a stable
`gta6x world --kind ...` surface onto those backend commands.

Every command is read-only and writes derived files to ``--out``. The backend
must be built and the source archive indexed first (see the README).
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field

from . import models

__all__ = ["KINDS", "WorldError", "validate_request", "run"]


class WorldError(RuntimeError):
    """Raised when a world step cannot be prepared or run."""


@dataclass(frozen=True)
class Kind:
    backend: str                 # sixng subcommand
    archive: str | None = None   # default archive fragment
    filters: bool = True         # accepts --name/--limit/--min-size/--bbox
    options: tuple[str, ...] = field(default_factory=tuple)


KINDS: dict[str, Kind] = {
    "placements": Kind("placements", "levels", options=("batches", "batches-only")),
    "collision": Kind("collision", "levels"),
    "navmesh": Kind("navmesh", "navmeshes", options=("roads-only",)),
    "paths": Kind("paths", "levels"),
    "interiors": Kind("interiors", "levels"),
    "lights": Kind("lights", "levels"),
    "meta": Kind("meta", "data", options=("dump",)),
    "pso": Kind("pso", "data"),
    "shaders": Kind("shaders", "levels"),
    "vehicles": Kind("vehicles", "packs", filters=False),
    "handling": Kind("handling", "data", filters=False),
    "surfaces": Kind("surfaces", "levels", filters=False),
    "all": Kind("world", None, filters=False),
}


def _text(value, flag, *, empty=True):
    if not isinstance(value, str) or '\0' in value or (not empty and not value.strip()):
        raise WorldError(f"{flag} must be {'nonempty ' if not empty else ''}NUL-free text")
    return value


def _path(value, flag):
    try:
        value = os.fsdecode(os.fspath(value))
    except TypeError as exc:
        raise WorldError(f"{flag} must be a filesystem path") from exc
    _text(value, flag, empty=False)
    path = os.path.realpath(value)
    existing = path
    while not os.path.exists(existing):
        above = os.path.dirname(existing)
        if above == existing:
            raise WorldError(f"{flag} has no existing directory parent")
        existing = above
    if not os.path.isdir(existing):
        raise WorldError(f"{flag} must name a directory without file-valued parents")
    return path


def _contains(parent, child):
    try:
        if os.path.commonpath((parent, child)) == parent:
            return True
    except ValueError:
        return False  # Absolute paths on distinct drives cannot contain each other.
    # Detect existing filesystem aliases, including case aliases on a
    # case-insensitive volume. Nonexistent descendants still have real parents.
    if os.path.exists(parent):
        while True:
            if os.path.exists(child) and os.path.samefile(parent, child):
                return True
            above = os.path.dirname(child)
            if above == child:
                break
            child = above
    return False


def validate_request(game, work, kind, archive, out, filters=None, options=None,
                     navmeshes=None):
    """Reject unsafe or silently ignored requests before backend execution.

    Regexes remain opaque backend-dialect text. This validates only the wrapper's
    established interface, not backend availability, an index or native formats.
    No directory is created or game/index data opened by this preflight.
    """
    if not isinstance(kind, str) or kind not in KINDS:
        raise WorldError(f"unknown world kind {kind!r}")
    spec = KINDS[kind]
    if archive is not None:
        _text(archive, '--archive', empty=False)
        if kind == 'all':
            raise WorldError('--archive is not used by --kind all')
    if filters is None:
        filters = {}
    if options is None:
        options = {}
    if not isinstance(filters, dict) or not isinstance(options, dict):
        raise WorldError('world filters and options must be dictionaries')
    filter_keys = {'name', 'exclude_name', 'min_size', 'limit', 'bbox'}
    option_keys = {'dump', 'roads_only', 'batches', 'batches_only'}
    if set(filters) - filter_keys or set(options) - option_keys:
        raise WorldError('unknown world filter or option')
    for name in ('limit', 'min_size'):
        value = filters.get(name, 0)
        if type(value) is not int or value < 0:
            raise WorldError(f"--{name.replace('_', '-')} must be a nonnegative integer")
    for name in ('name', 'exclude_name', 'bbox'):
        value = filters.get(name)
        if value is not None:
            _text(value, '--' + name.replace('_', '-'))
    if not spec.filters:
        for name in sorted(filter_keys):
            if filters.get(name):
                raise WorldError(f"--{name.replace('_', '-')} is not supported by --kind {kind}")
    bbox = filters.get('bbox')
    if bbox:
        try:
            values = [float(part) for part in bbox.split(',')]
        except ValueError as exc:
            raise WorldError('--bbox requires four finite ordered coordinates') from exc
        if (len(values) != 4 or not all(math.isfinite(v) for v in values)
                or values[0] > values[2] or values[1] > values[3]):
            raise WorldError('--bbox requires four finite ordered coordinates')
    for name, value in options.items():
        if type(value) is not bool:
            raise WorldError(f"--{name.replace('_', '-')} must be Boolean")
        if value and name.replace('_', '-') not in spec.options:
            raise WorldError(f"--{name.replace('_', '-')} is not supported by --kind {kind}")
    if options.get('batches') and options.get('batches_only'):
        raise WorldError('--batches and --batches-only are mutually exclusive')
    if navmeshes is not None:
        _text(navmeshes, '--navmeshes', empty=False)
        if kind != 'surfaces' and navmeshes != 'navmeshes':
            raise WorldError('--navmeshes is only supported by --kind surfaces')
    paths = {'--root': _path(game, '--root'), '--work': _path(work, '--work'),
             '--out': _path(out, '--out')}
    for first, second in (('--root', '--work'), ('--root', '--out'), ('--work', '--out')):
        if _contains(paths[first], paths[second]) or _contains(paths[second], paths[first]):
            raise WorldError(f'{first} and {second} directories must not overlap')


def run(backend: str, game: str, work: str, kind: str, archive: str | None,
        out: str, filters: dict | None = None, options: dict | None = None,
        navmeshes: str | None = None) -> tuple[str, dict]:
    """Run one world step; returns (archive label, result payload)."""
    validate_request(game, work, kind, archive, out, filters, options, navmeshes)
    spec = KINDS[kind]
    filters = filters or {}
    options = options or {}
    label = archive or spec.archive or "levels"
    command = [spec.backend]
    if kind == "all":
        command += ["all"]
    else:
        command += [label]
    if spec.filters:
        if filters.get("name"):
            command += ["--name", filters["name"]]
        if filters.get("exclude_name"):
            command += ["--exclude-name", filters["exclude_name"]]
        if filters.get("min_size"):
            command += ["--min-size", str(filters["min_size"])]
        if filters.get("limit"):
            command += ["--limit", str(filters["limit"])]
        if filters.get("bbox"):
            command += ["--bbox", filters["bbox"]]
    if options.get("dump"):
        command += ["--dump"]
    if options.get("roads_only"):
        command += ["--roads-only"]
    if options.get("batches"):
        command += ["--batches"]
    if options.get("batches_only"):
        command += ["--batches-only"]
    if kind == "surfaces":
        command += ["--navmeshes", navmeshes or "navmeshes"]
    command += ["--out", os.path.abspath(out)]
    payload = models.run(backend, game, work, command)
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        raise WorldError('sixng backend: world result must be a JSON object')
    return label, result
