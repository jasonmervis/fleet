"""`fleet spawn` — worktree + install + tab + agent, all or nothing."""

from __future__ import annotations

import argparse
import os
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fleet.agents import get_adapter, probe
from fleet.config import FleetConfig, with_overrides
from fleet.context import Context, validate_name
from fleet.errors import FleetError, UsageError
from fleet.forges import select_forge
from fleet.herdr import SHELL_PROMPT_TIMEOUT_MS, pane_busy, require_inside
from fleet.state import FleetState, Worker, now_iso

# `agent start` right after `tab create` races the shell's startup; the prompt wait catches most
# of it, but the wait regex is prompt-dependent, so a busy pane gets a few more tries.
AGENT_START_ATTEMPTS = 3


@dataclass(frozen=True)
class SpawnRequest:
    name: str
    branch: str
    issue: int | None = None
    allow_unsupervised: bool = False


def resolve(ctx: Context, args: argparse.Namespace) -> tuple[SpawnRequest, FleetConfig]:
    req = SpawnRequest(
        name=validate_name(args.name),
        branch=args.branch,
        issue=args.issue,
        allow_unsupervised=args.allow_unsupervised,
    )
    cfg = with_overrides(
        ctx.config,
        base=args.base,
        agent=args.agent,
        model=args.model,
        permission_mode=args.permission_mode,
        # None = not given (keep config); [] = explicitly none, e.g. a codex worker.
        allowlist=None if args.allowlist is None else tuple(args.allowlist),
    )
    if not cfg.base:
        raise UsageError(
            "cannot resolve the base branch", fix="pass --base or set `base` in .fleet.toml"
        )
    return req, cfg


def _launch_args(cfg: FleetConfig) -> list[str]:
    return get_adapter(cfg.agent).launch_args(cfg.model, cfg.permission_mode, cfg.allowlist)


def _dry_run(ctx: Context, req: SpawnRequest, cfg: FleetConfig) -> int:
    path = ctx.worktree(req.name)
    args = _launch_args(cfg)
    if req.issue is not None:
        forge = select_forge(cfg.forge, ctx.root, ctx.reader, ctx.actor, cfg.base)
        forge.claim(req.issue, req.name, req.branch)
    ctx.git.worktree_add(path, req.branch, cfg.base)
    if cfg.install and cfg.install != ":":
        ctx.actor.shell(f"cd {shlex.quote(str(path))} && {cfg.install}", cwd=ctx.root)
    workspace = os.environ.get("HERDR_WORKSPACE_ID") or "<workspace_id>"
    tab = ctx.herdr.tab_create(workspace, str(path), req.name)
    ctx.herdr.pane_wait_output(tab.pane_id, cfg.shell_prompt_regex, SHELL_PROMPT_TIMEOUT_MS)
    ctx.herdr.agent_start(req.name, cfg.agent, tab.pane_id, args)
    return 0


def _gate(ctx: Context, state: FleetState, req: SpawnRequest, cfg: FleetConfig) -> str:
    """Refuse anything that must not be spawned. Returns the base sha."""
    path = ctx.worktree(req.name)
    if state.get(req.name) or path.exists():
        raise FleetError(
            f"worker {req.name} already exists",
            fix=f"pick another name, or `fleet teardown --name {req.name}`",
        )
    if ctx.git_read.branch_exists(req.branch):
        raise FleetError(f"branch {req.branch} already exists", fix="pick another --branch")
    if len(state.workers) >= cfg.max_workers:
        raise FleetError(
            f"max_workers reached ({cfg.max_workers})",
            why="more parallel workers means more merge conflicts, not more throughput (§4)",
            fix="tear one down, or raise `max_workers` in .fleet.toml",
        )
    base_sha = ctx.git_read.rev(cfg.base)
    if cfg.permission_mode == "auto":
        pre = state.preflight
        if pre is None or pre.base_sha != base_sha:
            raise FleetError(
                f"permission mode `auto` needs a passing preflight on {cfg.base}@{base_sha[:8]}",
                why="unsupervised agents are only safe when the test suite can prove their work",
                fix="run `fleet preflight`, or pass --permission-mode edits",
            )
    return base_sha


def _transaction(
    ctx: Context, steps: list[tuple[str, Callable[[], Callable[[], None] | None]]]
) -> None:
    """Run steps in order; each may return an undo. On failure, undo completed steps in reverse."""
    undos: list[Callable[[], None]] = []
    for label, step in steps:
        try:
            undo = step()
        except FleetError as exc:
            for rollback in reversed(undos):
                try:
                    rollback()
                except FleetError as undo_exc:
                    ctx.warn(f"rollback incomplete: {undo_exc.what}")
            raise FleetError(
                f"spawn failed at step `{label}`: {exc.what}",
                why=exc.why or "every completed step was rolled back",
                fix=exc.fix,
            ) from exc
        if undo:
            undos.append(undo)


def run(ctx: Context, args: argparse.Namespace) -> int:
    req, cfg = resolve(ctx, args)
    if ctx.is_dry:
        return _dry_run(ctx, req, cfg)

    launch_args = _launch_args(cfg)
    workspace = require_inside()
    herdr, git = ctx.herdr, ctx.git
    cap = probe(cfg.agent, ctx.herdr_read)
    if not cap.has_lifecycle and not req.allow_unsupervised:
        raise FleetError(
            f"{cfg.agent}: lifecycle integration missing ({cap.integration})",
            why="without it fleet cannot tell working from blocked or done",
            fix=f"`{cap.install_hint}`, or pass --allow-unsupervised",
        )

    store = ctx.store
    path: Path = ctx.worktree(req.name)
    with store.lock("spawn"):
        state = store.load()
        base_sha = _gate(ctx, state, req, cfg)
        forge = select_forge(cfg.forge, ctx.root, ctx.reader, ctx.actor, cfg.base)
        ids: dict[str, str] = {}

        def claim():
            # Before any local state exists: a denied claim leaves nothing to undo (§3.4).
            if req.issue is None:
                return None
            forge.claim(req.issue, req.name, req.branch)
            return lambda: forge.release(req.issue)

        def add_worktree():
            git.worktree_add(path, req.branch, cfg.base)
            return lambda: (git.worktree_remove(path, force=True), git.branch_delete(req.branch))

        def install():
            if not cfg.install or cfg.install == ":":
                return None
            res = ctx.reader.shell(cfg.install, cwd=path, timeout_s=cfg.install_timeout_ms / 1000)
            if not res.ok:
                tail = (res.stderr or res.stdout).strip()[-400:]
                raise FleetError(f"install failed: {cfg.install}", why=tail)
            return None

        def create_tab():
            tab = herdr.tab_create(workspace, str(path), req.name)
            ids.update(tab=tab.tab_id, pane=tab.pane_id)
            return lambda: herdr.tab_close(tab.tab_id)

        def wait_shell():
            herdr.pane_wait_output(ids["pane"], cfg.shell_prompt_regex, SHELL_PROMPT_TIMEOUT_MS)
            return None

        def start_agent():
            for attempt in range(1, AGENT_START_ATTEMPTS + 1):
                try:
                    herdr.agent_start(req.name, cfg.agent, ids["pane"], launch_args)
                    return None
                except FleetError as exc:
                    if not pane_busy(exc) or attempt == AGENT_START_ATTEMPTS:
                        raise
                    ctx.warn(
                        f"pane {ids['pane']} busy; waiting for its shell again "
                        f"(attempt {attempt + 1}/{AGENT_START_ATTEMPTS})"
                    )
                    wait_shell()
            return None

        _transaction(
            ctx,
            [
                ("claim", claim),
                ("worktree", add_worktree),
                ("install", install),
                ("tab", create_tab),
                ("shell", wait_shell),
                ("agent", start_agent),
            ],
        )
        worker = Worker(
            name=req.name,
            branch=req.branch,
            base=cfg.base,
            base_sha=base_sha,
            agent=cfg.agent,
            model=cfg.model,
            worktree=str(path),
            tab_id=ids["tab"],
            pane_id=ids["pane"],
            started_at=now_iso(),
            issue=req.issue,
            supervised=cap.has_lifecycle,
        )
        store.save(state.with_worker(worker))

    ctx.say(f"{req.name}  {ids['tab']}  {ids['pane']}  {path}")
    return 0
