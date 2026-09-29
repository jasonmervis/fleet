"""`fleet preflight` — playbook §1.1 and §1.3 as a gate. Reports every failure, not the first."""

from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from dataclasses import dataclass

from fleet.agents import probe
from fleet.context import Context
from fleet.errors import FleetError
from fleet.herdr import MIN_VERSION, require_inside
from fleet.state import Preflight, now_iso

TEST_TIMEOUT_S = 1800


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""


def _guard(name: str, fn: Callable[[], Check]) -> Check:
    try:
        return fn()
    except FleetError as exc:
        return Check(name, False, exc.what, exc.fix)


def _inside_herdr() -> Check:
    require_inside()
    return Check("inside herdr", True)


def _herdr_checks(ctx: Context) -> list[Check]:
    checks = [_guard("inside herdr", _inside_herdr)]
    herdr = ctx.herdr_read
    version = herdr.version()
    shown = ".".join(map(str, version)) or "not found"
    checks.append(
        Check(
            f"herdr >= {'.'.join(map(str, MIN_VERSION))}",
            bool(version) and version >= MIN_VERSION,
            f"found {shown}",
            "herdr update",
        )
    )
    cap = probe(ctx.config.agent, herdr)
    checks.append(
        Check(
            f"{cap.kind} lifecycle integration",
            cap.has_lifecycle,
            cap.integration,
            cap.install_hint,
        )
    )
    return checks


def _repo_checks(ctx: Context) -> tuple[list[Check], str]:
    git = ctx.git_read
    cfg = ctx.config
    checks = [Check("repo has a commit", git.has_commits(), fix="make an initial commit")]
    dirty = [f for f in git.dirty_files() if not f.startswith(".fleet/")]
    checks.append(
        Check("clean working tree", not dirty, ", ".join(dirty[:5]), "commit or stash first")
    )
    base_sha = ""
    if cfg.base:
        base_sha = git.rev(cfg.base) if git.has_commits() else ""
        head = git.rev("HEAD") if git.has_commits() else ""
        checks.append(
            Check(
                f"on base `{cfg.base}`",
                bool(base_sha) and head == base_sha,
                f"HEAD {head[:8]} vs {cfg.base} {base_sha[:8]}",
                f"git switch {cfg.base} — the orchestrator stays on base",
            )
        )
    else:
        checks.append(Check("base resolved", False, fix="set `base` in .fleet.toml"))
    checks.append(
        Check("test command set", bool(cfg.test), fix='set `test = "..."` in .fleet.toml')
    )
    return checks, base_sha


def run(ctx: Context, args: argparse.Namespace) -> int:
    checks = _herdr_checks(ctx)
    repo_checks, base_sha = _repo_checks(ctx)
    checks += repo_checks

    if all(c.ok for c in checks):
        started = time.monotonic()
        res = ctx.reader.shell(ctx.config.test, cwd=ctx.root, timeout_s=TEST_TIMEOUT_S)
        tail = (res.stdout + res.stderr).strip().splitlines()[-3:]
        checks.append(
            Check(
                f"test passes on base ({time.monotonic() - started:.0f}s)",
                res.ok,
                " | ".join(tail),
                "a red base makes every worker's result meaningless — fix it first",
            )
        )

    for c in checks:
        detail = f" — {c.detail}" if c.detail and not c.ok else ""
        ctx.say(f"{'ok  ' if c.ok else 'FAIL'} {c.name}{detail}")
        if not c.ok and c.fix:
            ctx.say(f"       fix: {c.fix}")
    if ctx.config.base_needs_confirmation:
        ctx.warn(
            f"base `{ctx.config.base}` came from the current branch; confirm it with the human"
        )

    failed = [c for c in checks if not c.ok]
    if failed:
        raise FleetError(f"preflight failed: {len(failed)} check(s)")

    store = ctx.store
    store.save(store.load().with_preflight(Preflight(ctx.config.base, base_sha, now_iso())))
    ctx.say(f"preflight passed on {ctx.config.base}@{base_sha[:8]}")
    return 0
