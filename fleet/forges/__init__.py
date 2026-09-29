"""Forges: where work comes from and how finished work is delivered."""

from __future__ import annotations

from pathlib import Path

from fleet.forges.base import Forge
from fleet.forges.github import GitHubForge
from fleet.forges.local import LocalForge
from fleet.proc import Runner


def select_forge(name: str, root: Path, reader: Runner, actor: Runner, base: str = "main") -> Forge:
    """`auto` picks github when `gh` can see a repo for this checkout, else local."""
    if name == "auto":
        seen = reader.run(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=root, check=False)
        name = "github" if seen.ok else "local"
    if name == "github":
        return GitHubForge(reader=reader, actor=actor, root=root, ref=base or "main")
    return LocalForge()


__all__ = ["Forge", "GitHubForge", "LocalForge", "select_forge"]
