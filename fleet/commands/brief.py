"""`fleet brief` — send a worker its brief plus the non-negotiable scope and delivery rules."""

from __future__ import annotations

import argparse
from pathlib import Path

from fleet.context import Context
from fleet.errors import FleetError
from fleet.forges import select_forge
from fleet.state import Worker

DEFAULT_TIMEOUT_MS = 1_800_000


def scope_rules(worker: Worker) -> str:
    return (
        f"SCOPE: work only inside {worker.worktree}. You are a fleet worker, not the orchestrator. "
        "Never create a worktree, never spawn or message other agents, never read or edit `../` "
        "or any other directory under `.worktrees/`. If you are blocked, need a file outside your "
        "scope, or face a decision that is not yours: stop and say so. Do not open issues."
    )


def compose(ctx: Context, worker: Worker, brief: str) -> str:
    forge = select_forge(ctx.config.forge, ctx.root, ctx.reader, ctx.actor)
    rules = forge.delivery_rules(worker.base, worker.issue)
    return f"{brief.strip()}\n\n{scope_rules(worker)}\n\n{rules}"


def send(ctx: Context, worker: Worker, brief_path: Path, wait: bool, timeout_ms: int) -> str:
    try:
        brief = brief_path.read_text()
    except OSError as exc:
        raise FleetError(f"cannot read brief {brief_path}", why=str(exc)) from exc
    if not brief.strip():
        raise FleetError(f"brief {brief_path} is empty")
    ctx.herdr.agent_prompt(worker.name, compose(ctx, worker, brief), wait, timeout_ms)
    return "" if ctx.is_dry else ctx.herdr_read.agent_status(worker.name)


def run(ctx: Context, args: argparse.Namespace) -> int:
    store = ctx.store
    state = store.load()
    worker = state.get(args.name)
    if worker is None:
        raise FleetError(f"no worker named {args.name}", fix="`fleet status` lists workers")
    status = send(ctx, worker, Path(args.file), not args.no_wait, args.timeout_ms)
    if ctx.is_dry:
        return 0
    store.save(store.load().updated(worker.name, status="briefed", last_settled=status))
    ctx.say(f"{worker.name}: {status}")
    return 0
