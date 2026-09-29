"""`fleet status` — reconcile recorded workers with live Herdr agents."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from fleet.context import WORKTREES_DIR, Context
from fleet.herdr import require_inside
from fleet.state import Worker


@dataclass(frozen=True)
class Row:
    name: str
    agent: str
    branch: str
    issue: str
    state: str
    elapsed_min: int
    diff: str
    flags: tuple[str, ...]
    pane_id: str
    screen: str = ""


def elapsed_minutes(started_at: str, now: datetime | None = None) -> int:
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return 0
    return int(((now or datetime.now(UTC)) - started).total_seconds() // 60)


def build_rows(ctx: Context, workers: tuple[Worker, ...], agents: list[dict]) -> list[Row]:
    by_pane = {a.get("pane_id"): a for a in agents}
    rows = []
    for w in workers:
        live = by_pane.get(w.pane_id)
        minutes = elapsed_minutes(w.started_at)
        flags = []
        if live is None:
            flags.append("gone")
        if not w.supervised:
            flags.append("unsupervised")
        if minutes > ctx.config.max_minutes:
            flags.append("overrun")
        added, removed = ctx.git_read.diff_numstat(w.base, w.branch)
        rows.append(
            Row(
                name=w.name,
                agent=f"{w.agent}/{w.model or 'default'}",
                branch=w.branch,
                issue=f"#{w.issue}" if w.issue else "-",
                state=str(live.get("agent_status", "unknown")) if live else "gone",
                elapsed_min=minutes,
                diff=f"+{added}/-{removed}",
                flags=tuple(flags),
                pane_id=w.pane_id,
            )
        )
    known = {w.pane_id for w in workers}
    worktrees = str(ctx.root / WORKTREES_DIR) + "/"
    for a in agents:
        if a.get("pane_id") not in known and str(a.get("cwd", "")).startswith(worktrees):
            rows.append(
                Row(
                    name=str(a.get("name") or a.get("pane_id")),
                    agent=str(a.get("agent", "?")),
                    branch="-",
                    issue="-",
                    state=str(a.get("agent_status", "unknown")),
                    elapsed_min=0,
                    diff="-",
                    flags=("untracked",),
                    pane_id=str(a.get("pane_id")),
                )
            )
    return rows


def render(rows: list[Row]) -> str:
    header = (
        f"{'NAME':<14}{'AGENT':<22}{'BRANCH':<28}{'ISSUE':<7}{'STATE':<9}{'MIN':>5}  "
        f"{'DIFF':<12}FLAGS"
    )
    lines = [header]
    for r in rows:
        lines.append(
            f"{r.name:<14}{r.agent:<22}{r.branch:<28}{r.issue:<7}{r.state:<9}{r.elapsed_min:>5}  "
            f"{r.diff:<12}{','.join(r.flags)}"
        )
        if r.screen:
            lines += [f"    | {line}" for line in r.screen.strip().splitlines()[-15:]]
    return "\n".join(lines)


def run(ctx: Context, args: argparse.Namespace) -> int:
    if ctx.is_dry:
        ctx.herdr.agent_list()
        return 0
    workspace = args.workspace or require_inside()
    herdr = ctx.herdr_read
    agents = [a for a in herdr.agent_list() if a.get("workspace_id") == workspace]
    rows = build_rows(ctx, ctx.store.load().workers, agents)
    if args.blocked:
        rows = [
            Row(**{**asdict(r), "screen": herdr.agent_read(r.pane_id, 40, "visible")})
            for r in rows
            if r.state == "blocked"
        ]
    if args.json:
        ctx.say(json.dumps([asdict(r) for r in rows], indent=2))
    elif rows:
        ctx.say(render(rows))
    else:
        ctx.say("no blocked workers" if args.blocked else "no workers")
    return 0
