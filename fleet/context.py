"""Everything a command needs, built once per invocation and passed in (no globals)."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from fleet.config import FleetConfig, load_config
from fleet.errors import FleetError, UsageError
from fleet.git import Git
from fleet.herdr import Herdr
from fleet.proc import DryRunner, Runner, SubprocessRunner
from fleet.state import StateStore

WORKTREES_DIR = ".worktrees"
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def validate_name(name: str) -> str:
    if not NAME_RE.match(name):
        raise UsageError(
            f"invalid value for --name: {name!r}",
            why="the name becomes a path under .worktrees/ and a tab label",
            fix="use [a-z][a-z0-9_-]{0,31}",
        )
    return name


@dataclass(frozen=True)
class Context:
    root: Path
    reader: Runner  # always real: reads never change anything
    actor: Runner  # real, or DryRunner under --dry-run
    config: FleetConfig

    @property
    def is_dry(self) -> bool:
        return self.actor.is_dry

    @property
    def store(self) -> StateStore:
        return StateStore(self.root)

    @property
    def git(self) -> Git:
        return Git(self.actor, self.root)

    @property
    def git_read(self) -> Git:
        return Git(self.reader, self.root)

    @property
    def herdr(self) -> Herdr:
        return Herdr(self.actor)

    @property
    def herdr_read(self) -> Herdr:
        return Herdr(self.reader)

    def worktree(self, name: str) -> Path:
        return self.root / WORKTREES_DIR / name

    def say(self, text: str) -> None:
        print(text, file=sys.stdout)

    def warn(self, text: str) -> None:
        print(f"warning: {text}", file=sys.stderr)


def build_context(dry_run: bool, cwd: Path | None = None) -> Context:
    reader = SubprocessRunner()
    root = Git(reader, cwd or Path.cwd()).toplevel()
    if WORKTREES_DIR in root.parts:
        raise FleetError(
            "fleet was run from inside a worker worktree",
            why=f"{root} is a worker's checkout; only the orchestrator runs fleet",
            fix="run fleet from the repo root",
        )
    actor: Runner = DryRunner() if dry_run else reader
    return Context(root=root, reader=reader, actor=actor, config=load_config(root, reader))
