"""`fleet logs` — save a worker's transcript before it is lost with its tab."""

from __future__ import annotations

import argparse
from pathlib import Path

from fleet.context import Context
from fleet.errors import FleetError
from fleet.state import STATE_DIR

DEFAULT_LINES = 5000


def save_transcript(
    ctx: Context, name: str, target: str, lines: int = DEFAULT_LINES
) -> Path | None:
    """Write the agent's scrollback to .fleet/logs/<name>.log. None if nothing could be read."""
    text = ctx.herdr_read.agent_read(target, lines)
    if not text.strip():
        return None
    path = ctx.root / STATE_DIR / "logs" / f"{name}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def run(ctx: Context, args: argparse.Namespace) -> int:
    worker = ctx.store.load().get(args.name)
    target = worker.pane_id if worker else args.name
    if ctx.is_dry:
        ctx.herdr.agent_read(target, args.lines)
        return 0
    path = save_transcript(ctx, args.name, target, args.lines)
    if path is None:
        raise FleetError(
            f"no transcript for {args.name}",
            why="herdr returned nothing: the agent is gone, or busy (deep reads need idle)",
            fix="wait for idle, or check `fleet status`",
        )
    ctx.say(str(path))
    return 0
