"""`fleet doctor` — is this repo's fleet install consistent with the CLI and Herdr?"""

from __future__ import annotations

import argparse

from fleet import __version__
from fleet.agents import probe
from fleet.context import Context
from fleet.errors import FleetError
from fleet.herdr import MIN_VERSION
from fleet.skill_files import SKILL_REL, read_stamp


def run(ctx: Context, args: argparse.Namespace) -> int:
    problems: list[str] = []
    skill_md = ctx.root / SKILL_REL / "SKILL.md"
    stamped = read_stamp(skill_md.read_text()) if skill_md.is_file() else ""
    if not stamped:
        problems.append(f"no stamped skill at {SKILL_REL} — run `fleet init`")
    elif stamped != __version__:
        problems.append(f"skill is {stamped}, CLI is {__version__} — run `fleet init` to upgrade")
    ctx.say(f"cli     {__version__}")
    ctx.say(f"skill   {stamped or 'missing'}")

    herdr = ctx.herdr_read
    version = herdr.version()
    shown = ".".join(map(str, version)) or "not found"
    ctx.say(f"herdr   {shown}")
    if not version or version < MIN_VERSION:
        problems.append(
            f"herdr {shown} is below {'.'.join(map(str, MIN_VERSION))} — `herdr update`"
        )
    else:
        cap = probe(ctx.config.agent, herdr)
        ctx.say(f"agent   {cap.kind}: {cap.integration}")
        if not cap.has_lifecycle:
            ctx.warn(f"{cap.kind} has no lifecycle integration — `{cap.install_hint}`")

    if problems:
        for p in problems:
            ctx.say(f"FAIL {p}")
        raise FleetError(f"doctor found {len(problems)} problem(s)")
    ctx.say("ok")
    return 0
