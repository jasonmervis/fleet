"""`fleet up <split.toml>` — spawn and brief a whole batch from one reviewed file."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from fleet.commands import brief, spawn
from fleet.context import Context, validate_name
from fleet.errors import FleetError, UsageError

# key -> required type. `name`, `branch`, `brief` are also required to be present.
_KEYS: dict[str, type] = {
    "name": str,
    "branch": str,
    "brief": str,
    "issue": int,
    "agent": str,
    "model": str,
    "base": str,
    "permission_mode": str,
    "allow_unsupervised": bool,
    "allowlist": list,
}
_REQUIRED = ("name", "branch", "brief")


def _check_types(path: Path, i: int, w: dict) -> None:
    for key, value in w.items():
        expected = _KEYS[key]
        wrong_bool = isinstance(value, bool) and expected is not bool
        if not isinstance(value, expected) or wrong_bool:
            raise UsageError(f"{path} worker {i}: `{key}` must be {expected.__name__}")
        if expected is list and not all(isinstance(v, str) for v in value):
            raise UsageError(f"{path} worker {i}: `{key}` must be a list of strings")


def require_assignments(workers: list[dict]) -> None:
    """With `assign = "ask"`, every worker must carry an explicit agent and model."""
    missing = [w["name"] for w in workers if "agent" not in w or "model" not in w]
    if missing:
        raise UsageError(
            f'assign = "ask": no agent/model chosen for {", ".join(missing)}',
            why="this repo requires the human to choose each worker's agent and model",
            fix="ask the human, then set `agent` and `model` on each [[worker]] "
            '(model = "" means the agent\'s default)',
        )


def parse_split(path: Path) -> list[dict]:
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise UsageError(f"cannot read split file {path}", why=str(exc)) from exc
    workers = data.get("worker", [])
    if not workers:
        raise UsageError(f"{path} has no [[worker]] entries")
    names, branches = set(), set()
    for i, w in enumerate(workers, 1):
        unknown = set(w) - set(_KEYS)
        if unknown:
            raise UsageError(f"{path} worker {i}: unknown key(s) {', '.join(sorted(unknown))}")
        for key in _REQUIRED:
            if not w.get(key):
                raise UsageError(f"{path} worker {i}: `{key}` is required")
        _check_types(path, i, w)
        validate_name(w["name"])
        if w["name"] in names or w["branch"] in branches:
            raise UsageError(f"{path}: duplicate name or branch in worker {i} ({w['name']})")
        names.add(w["name"])
        branches.add(w["branch"])
        brief_path = (path.parent / w["brief"]).resolve()
        if not brief_path.is_file():
            raise UsageError(f"{path} worker {w['name']}: brief not found: {brief_path}")
        w["brief"] = brief_path
    return workers


def _spawn_args(w: dict, allow_unsupervised_all: bool) -> argparse.Namespace:
    return argparse.Namespace(
        name=w["name"],
        branch=w["branch"],
        issue=w.get("issue"),
        base=w.get("base"),
        agent=w.get("agent"),
        model=w.get("model"),
        permission_mode=w.get("permission_mode"),
        allowlist=w.get("allowlist"),
        allow_unsupervised=allow_unsupervised_all or w.get("allow_unsupervised", False),
    )


def run(ctx: Context, args: argparse.Namespace) -> int:
    workers = parse_split(Path(args.split))
    if ctx.config.assign == "ask":
        require_assignments(workers)
    live = len(ctx.store.load().workers)
    if live + len(workers) > ctx.config.max_workers:
        raise FleetError(
            f"{len(workers)} workers + {live} live exceeds max_workers ({ctx.config.max_workers})",
            fix="shrink the split, tear workers down, or raise `max_workers`",
        )
    spawned: list[str] = []
    for w in workers:
        try:
            spawn.run(ctx, _spawn_args(w, args.allow_unsupervised))
        except FleetError as exc:
            if spawned:
                exc.why = f"already spawned and left running: {', '.join(spawned)}. {exc.why}"
            raise
        spawned.append(w["name"])
    state = ctx.store.load()
    for w in workers:
        worker = state.get(w["name"])
        if worker is None:  # dry-run records nothing
            ctx.herdr.agent_prompt(w["name"], f"<brief from {w['brief']}>", False, 0)
            continue
        brief.send(ctx, worker, w["brief"], wait=False, timeout_ms=0)
        ctx.store.save(ctx.store.load().updated(worker.name, status="briefed"))
    if not ctx.is_dry:
        ctx.say(f"up: {len(workers)} worker(s) spawned and briefed; watch with `fleet status`")
    return 0
