"""`fleet teardown` — save the transcript, close the tab, remove the worktree. Never the branch."""

from __future__ import annotations

import argparse
import os

from fleet.commands.logs import save_transcript
from fleet.commands.status import elapsed_minutes
from fleet.context import Context, validate_name
from fleet.errors import FleetError, UsageError
from fleet.forges import select_forge
from fleet.herdr import require_inside
from fleet.state import Worker


def _targets(ctx: Context, args: argparse.Namespace) -> list[str]:
    chosen = sum(bool(x) for x in (args.name, args.all, args.overrun))
    if chosen != 1:
        raise UsageError("pass exactly one of --name, --all, --overrun")
    if args.tab and not args.name:
        raise UsageError("--tab only applies with --name")
    if args.name:
        return [validate_name(args.name)]
    workers = ctx.store.load().workers
    if args.overrun:
        workers = tuple(
            w for w in workers if elapsed_minutes(w.started_at) > ctx.config.max_minutes
        )
    return [w.name for w in workers]


def _refuse_unsafe(ctx: Context, worker: Worker | None, name: str) -> None:
    path = ctx.worktree(name)
    if path.is_dir():
        dirty = ctx.git_read.dirty_files(path)
        if dirty:
            raise FleetError(
                f"{name} has uncommitted changes: {', '.join(dirty[:10])}",
                why="removing the worktree would discard them",
                fix=f"have the worker commit, or `fleet teardown --name {name} --force`",
            )
    if worker is None:
        return
    forge = select_forge(ctx.config.forge, ctx.root, ctx.reader, ctx.reader)
    if forge.name != "github":
        return  # the branch is kept, so local commits survive teardown
    git = ctx.git_read
    upstream = git.upstream(worker.branch)
    unpushed = git.commits_not_on(worker.branch, upstream or worker.base)
    if unpushed:
        where = f"on {upstream}" if upstream else "pushed anywhere"
        raise FleetError(
            f"{name}: {len(unpushed)} commit(s) not {where} (newest {unpushed[0][:10]})",
            fix=f"push {worker.branch}, or pass --force",
        )


def _lookup_tab(ctx: Context, name: str, workspace: str) -> str:
    for tab in ctx.herdr_read.tab_list(workspace):
        if tab.get("label") == name:
            return str(tab["tab_id"])
    return ""


def _dry_run(ctx: Context, names: list[str], args: argparse.Namespace) -> int:
    state = ctx.store.load()
    for name in names:
        worker = state.get(name)
        tab = args.tab or (worker.tab_id if worker else "")
        if not tab:
            ctx.herdr.tab_list(os.environ.get("HERDR_WORKSPACE_ID") or "<workspace>")
            tab = f"<tab_id of label {name}>"
        if worker:
            ctx.herdr.agent_read(worker.pane_id, 5000)
        ctx.herdr.tab_close(tab)
        ctx.git.worktree_remove(ctx.worktree(name), force=args.force)
    return 0


def _teardown_one(ctx: Context, name: str, args: argparse.Namespace, workspace: str) -> None:
    store = ctx.store
    worker = store.load().get(name)
    if not args.force:
        _refuse_unsafe(ctx, worker, name)
    if worker:
        log = save_transcript(ctx, name, worker.pane_id)
        if log:
            ctx.say(f"{name}: transcript saved to {log}")
    tab = args.tab or (worker.tab_id if worker else "") or _lookup_tab(ctx, name, workspace)
    if tab:
        try:
            ctx.herdr.tab_close(tab)
        except FleetError as exc:
            ctx.warn(f"{name}: tab {tab} not closed ({exc.what}); it may already be gone")
    path = ctx.worktree(name)
    if path.is_dir():
        ctx.git.worktree_remove(path, force=args.force)
    elif worker is None and not tab:
        raise FleetError(f"no worker, tab or worktree named {name}", fix="see `fleet status`")
    store.save(store.load().without_worker(name))
    ctx.say(f"{name}: torn down (branch {worker.branch if worker else '?'} kept)")


def run(ctx: Context, args: argparse.Namespace) -> int:
    names = _targets(ctx, args)
    if ctx.is_dry:
        return _dry_run(ctx, names, args)
    if not names:
        ctx.say("nothing to tear down")
        return 0
    workspace = require_inside()
    with ctx.store.lock("teardown"):
        for name in names:
            _teardown_one(ctx, name, args, workspace)
    ctx.git.worktree_prune()
    return 0
