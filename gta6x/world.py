"""World/map extraction through the optional SixNG backend.

The native parsers cover containers, textures, audio, shaders and XML/PSIN;
the world data (placements, collision, navmesh, road graph, lights, interiors,
meta/PSO and vehicles) is decoded by SixNG's readers. This module maps a stable
`gta6x world --kind ...` surface onto those backend commands.

Every command is read-only and writes derived files to ``--out``. The backend
must be built and the source archive indexed first (see the README).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import models

__all__ = ["KINDS", "WorldError", "run"]


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
    "meta": Kind("meta", "data"),
    "pso": Kind("pso", "data"),
    "shaders": Kind("shaders", "levels"),
    "vehicles": Kind("vehicles", "packs", filters=False),
    "handling": Kind("handling", "data", filters=False),
    "surfaces": Kind("surfaces", "levels", filters=False),
    "all": Kind("world", None, filters=False),
}


def run(backend: str, game: str, work: str, kind: str, archive: str | None,
        out: str, filters: dict | None = None, options: dict | None = None,
        navmeshes: str | None = None) -> tuple[str, dict]:
    """Run one world step; returns (archive label, result payload)."""
    spec = KINDS.get(kind)
    if spec is None:
        raise WorldError(f"unknown world kind {kind!r}")
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
    return label, result
