"""Model listing and extraction through the optional SixNG backend.

Decoding RAGE 9 drawables/fragments (mesh blobs, meshlets, skeletons) is a
large research project of its own.  SixNG (`holdmysocks/SixNG`, GPL-3.0) already
implements it and exports glTF/GLB, so this module calls that program when it is
available instead of re-implementing it here.  Nothing from SixNG is bundled or
linked; it is an external, user-supplied executable.

Model discovery in our own code still works without the backend: the `index`
step is SixNG's carving index, and `list`/`extract` read its JSON output.

Backend resolution order:

1. ``--backend PATH`` / the ``GTA6X_SIXNG`` environment variable
2. a ``sixng`` executable on ``PATH``
3. ``<repo>/.cargo-target/release/sixng`` (the build used during development)

Building it (one time, needs Rust)::

    git clone https://github.com/holdmysocks/SixNG
    cd SixNG && cargo build --release -p sixng-cli
    export GTA6X_SIXNG=$PWD/target/release/sixng
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

BACKEND_ENV = "GTA6X_SIXNG"
BACKEND_NAME = "sixng"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

__all__ = ["BackendMissing", "find_backend", "run", "run_any", "info", "index",
           "list_models", "extract_models", "manifest_models"]


class BackendMissing(RuntimeError):
    """No SixNG executable was found."""


def find_backend(explicit: str | None = None) -> str | None:
    candidates = [
        explicit,
        os.environ.get(BACKEND_ENV),
        shutil.which(BACKEND_NAME),
        os.path.join(REPO_ROOT, ".cargo-target", "release", BACKEND_NAME),
        os.path.join(REPO_ROOT, "vendor", BACKEND_NAME),
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _run(backend: str, game: str, work: str, args: list[str],
         stream_progress: bool = False, timeout: int = 7200,
         require_ok: bool = True) -> dict:
    cmd = [backend, "--game", game, "--work", work, *args]
    if stream_progress:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True)
        payload = None
        while True:
            line = proc.stderr.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(line, file=__import__("sys").stderr)
                continue
            if event.get("event") == "progress" and event.get("pct") is not None:
                print(f"  {event.get('stage', '')} {event['pct']:.1f}%",
                      file=__import__("sys").stderr)
        stdout = proc.stdout.read()
        proc.wait()
        for line in reversed(stdout.strip().splitlines()):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    else:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        payload = None
        for line in reversed(proc.stdout.strip().splitlines()):
            try:
                payload = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
    ok = isinstance(payload, dict) and payload.get("ok", False)
    if proc.returncode != 0 or payload is None or (require_ok and not ok):
        error = None
        if isinstance(payload, dict):
            error = payload.get("error")
        if not error:
            error = (proc.stderr or "").strip().splitlines()[-1:] or ["backend failed"]
            error = error[0] if isinstance(error, list) else error
        raise RuntimeError(f"sixng backend: {error}")
    return payload


def run(backend: str, game: str, work: str, args: list[str],
        stream_progress: bool = False) -> dict:
    """Run an arbitrary sixng subcommand and return its final JSON payload."""
    return _run(backend, game, work, args, stream_progress=stream_progress)


def run_any(backend: str, game: str, work: str, args: list[str]) -> object:
    """Run a subcommand whose final JSON payload is not an ``ok`` envelope."""
    return _run(backend, game, work, args, require_ok=False)


def info(backend: str, game: str, work: str) -> dict:
    return _run(backend, game, work, ["info"])


def index(backend: str, game: str, work: str, archives: list[str],
          force: bool = False) -> dict:
    args = ["index", *archives]
    if force:
        args.append("--force")
    return _run(backend, game, work, args, stream_progress=True)


def list_models(backend: str, game: str, work: str, archive: str,
                rtype: str = "dr", name: str | None = None,
                limit: int = 20) -> list[dict]:
    args = ["list", archive, "--rtype", rtype, "--limit", str(limit)]
    if name:
        args += ["--name", name]
    return _run(backend, game, work, args).get("entries", [])


def extract_models(backend: str, game: str, work: str, archive: str, out: str,
                   rtype: str = "dr", name: str | None = None,
                   limit: int = 1, raw: bool = False,
                   textures: bool = False) -> dict:
    args = ["extract", archive, "--rtype", rtype, "--limit", str(limit), "-o", out]
    if name:
        args += ["--name", name]
    if raw:
        args.append("--raw")
    if textures:
        args += ["--tex", "both"]
    return _run(backend, game, work, args).get("result", {})


def manifest_models(out: str) -> list[dict]:
    """Read the manifest.jsonl written by an extraction run."""
    path = os.path.join(out, "manifest.jsonl")
    if not os.path.isfile(path):
        return []
    models: list[dict] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("glb") or record.get("kind") == "model":
                models.append(record)
    return models
