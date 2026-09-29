"""`fleet config` — print every resolved setting and where it came from."""

from __future__ import annotations

import argparse
from dataclasses import fields

from fleet.context import Context


def run(ctx: Context, args: argparse.Namespace) -> int:
    cfg = ctx.config
    for f in fields(cfg):
        if f.name == "sources":
            continue
        value = getattr(cfg, f.name)
        shown = ", ".join(value) if isinstance(value, tuple) else value
        ctx.say(f"{f.name:<20} {str(shown) or '(unset)':<45} {cfg.sources.get(f.name, '')}")
    if cfg.base_needs_confirmation:
        ctx.warn(
            f"base `{cfg.base}` is just the current branch; confirm it or set `base` in .fleet.toml"
        )
    return 0
