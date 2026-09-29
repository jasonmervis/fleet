"""`fleet init` — adopt fleet in a repo. Idempotent; never overwrites `.fleet.toml`."""

from __future__ import annotations

import argparse
import json
import shutil
import stat
from pathlib import Path

from fleet import __version__
from fleet.config import CONFIG_FILE
from fleet.context import Context
from fleet.forges import GitHubForge, select_forge
from fleet.forges.claim import WORKFLOW as CLAIM_WORKFLOW
from fleet.skill_files import SKILL_REL, bundled_skill_dir, stamp

IGNORES = (".worktrees/", ".fleet/")
TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
HOOK = """#!/bin/sh
# fleet: provision a new worktree with files git does not carry. Must stay fast; never fail.
[ "$3" = "1" ] || exit 0
COMMON=$(git rev-parse --git-common-dir); MAIN=$(cd "$COMMON/.." && pwd)
[ "$(pwd)" = "$MAIN" ] && exit 0
for f in .env .env.local; do [ -f "$MAIN/$f" ] && cp "$MAIN/$f" .; done
exit 0
"""


def _gitignore(root: Path) -> list[str]:
    path = root / ".gitignore"
    lines = path.read_text().splitlines() if path.exists() else []
    missing = [i for i in IGNORES if i not in lines]
    if missing:
        path.write_text("\n".join([*lines, *missing]) + "\n")
    return [f".gitignore += {m}" for m in missing]


def _hook(ctx: Context) -> list[str]:
    changes = []
    hook = ctx.root / ".githooks" / "post-checkout"
    if not hook.exists():
        hook.parent.mkdir(exist_ok=True)
        hook.write_text(HOOK)
        changes.append("wrote .githooks/post-checkout")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    current = ctx.reader.run(
        ["git", "config", "--get", "core.hooksPath"], cwd=ctx.root, check=False
    )
    value = current.stdout.strip()
    if value and value != ".githooks":
        ctx.warn(f"core.hooksPath is {value}; not changed — worktree provisioning hook inactive")
    elif not value:
        ctx.reader.run(["git", "config", "core.hooksPath", ".githooks"], cwd=ctx.root)
        changes.append("git config core.hooksPath .githooks")
    return changes


def _config_file(ctx: Context) -> list[str]:
    path = ctx.root / CONFIG_FILE
    if path.exists():
        return []
    cfg = ctx.config
    q = json.dumps  # a JSON string is a valid TOML basic string
    test_line = (
        f"test = {q(cfg.test)}" if cfg.test else '# test = "..."  # REQUIRED before spawning'
    )
    path.write_text(
        "# fleet config — committed, read by `fleet`. See `fleet config` for resolved values.\n"
        f"base = {q(cfg.base)}\n"
        f"install = {q(cfg.install)}\n"
        f"{test_line}\n"
        f"agent = {q(cfg.agent)}\n"
        '# model = ""  # agent default when empty\n'
        f"permission_mode = {q(cfg.permission_mode)}  # auto | edits | readonly\n"
        f"max_workers = {cfg.max_workers}\n"
        f"assign = {q(cfg.assign)}  # defaults | ask — ask: human picks agent/model per worker\n"
        f"# shell_prompt_regex = {q(cfg.shell_prompt_regex)}  # how a ready shell prompt ends\n"
    )
    return [f"wrote {CONFIG_FILE}" + ("" if cfg.test else " (set `test` before spawning)")]


def _skill(ctx: Context) -> list[str]:
    src = bundled_skill_dir()
    dest = ctx.root / SKILL_REL
    if src.resolve() != dest.resolve():
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, dest / f.name)
    skill_md = dest / "SKILL.md"
    before = skill_md.read_text()
    after = stamp(before, __version__)
    if after != before:
        skill_md.write_text(after)
    return [f"skill installed at {SKILL_REL} (fleet_version {__version__})"]


def _claim_workflow(root: Path) -> list[str]:
    """The serialized claim gate (§3.4). Must be on the default branch to be dispatchable."""
    dest = root / ".github" / "workflows" / CLAIM_WORKFLOW
    if dest.exists():
        return []
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TEMPLATES / CLAIM_WORKFLOW, dest)
    return [f"wrote .github/workflows/{CLAIM_WORKFLOW} — commit it to the default branch"]


def _dry_run(ctx: Context) -> int:
    for step in (
        f"append {', '.join(IGNORES)} to .gitignore if missing",
        "write .githooks/post-checkout if missing; git config core.hooksPath .githooks",
        f"write {CONFIG_FILE} from detection if missing",
        f"copy skill to {SKILL_REL} and stamp fleet_version {__version__}",
        "create labels fleet-ready, fleet-wip and the claim workflow (github forge only)",
    ):
        ctx.say(step)
    return 0


def run(ctx: Context, args: argparse.Namespace) -> int:
    if ctx.is_dry:
        return _dry_run(ctx)
    changes = _gitignore(ctx.root) + _hook(ctx) + _config_file(ctx) + _skill(ctx)
    forge = select_forge(ctx.config.forge, ctx.root, ctx.reader, ctx.reader)
    if isinstance(forge, GitHubForge):
        forge.create_labels()
        changes.append("labels fleet-ready, fleet-wip ensured")
        changes += _claim_workflow(ctx.root)
    for c in changes:
        ctx.say(c)
    ctx.say("next: `fleet config`, then `fleet preflight`")
    return 0
