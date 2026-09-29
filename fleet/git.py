"""Git operations fleet needs: worktrees, cleanliness, ahead counts, trial merges."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fleet.errors import FleetError
from fleet.proc import Runner


@dataclass(frozen=True)
class Git:
    runner: Runner
    root: Path

    def _git(self, *args: str, cwd: Path | None = None, check: bool = True):
        return self.runner.run(["git", *args], cwd=cwd or self.root, check=check)

    # --- reads (always safe) ---
    def toplevel(self) -> Path:
        res = self._git("rev-parse", "--show-toplevel", check=False)
        if not res.ok:
            raise FleetError("not a git repository", fix="run fleet from inside the repo")
        return Path(res.stdout.strip())

    def has_commits(self) -> bool:
        return self._git("rev-parse", "--verify", "HEAD", check=False).ok

    def rev(self, ref: str) -> str:
        res = self._git("rev-parse", "--verify", f"{ref}^{{commit}}", check=False)
        if not res.ok:
            raise FleetError(f"unknown ref: {ref}", fix="check the base branch (fleet config)")
        return res.stdout.strip()

    def branch_exists(self, branch: str) -> bool:
        return self._git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).ok

    def dirty_files(self, path: Path | None = None) -> list[str]:
        out = self._git("status", "--porcelain", cwd=path, check=False).stdout
        return [line[3:] for line in out.splitlines() if line.strip()]

    def upstream(self, branch: str) -> str:
        res = self._git(
            "rev-parse",
            "--abbrev-ref",
            "--symbolic-full-name",
            f"{branch}@{{upstream}}",
            check=False,
        )
        return res.stdout.strip() if res.ok else ""

    def commits_not_on(self, branch: str, other: str) -> list[str]:
        out = self._git("rev-list", f"{other}..{branch}", check=False).stdout
        return out.split()

    def diff_numstat(self, base: str, branch: str) -> tuple[int, int]:
        out = self._git("diff", "--numstat", f"{base}...{branch}", check=False).stdout
        added = removed = 0
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                added += int(parts[0])
                removed += int(parts[1])
        return added, removed

    # --- writes (routed through the runner, so dry-run prints them) ---
    def worktree_add(self, path: Path, branch: str, base: str) -> None:
        self._git("worktree", "add", str(path), "-b", branch, base)

    def worktree_remove(self, path: Path, force: bool = False) -> None:
        args = ["worktree", "remove", *(["--force"] if force else []), str(path)]
        self._git(*args)

    def worktree_prune(self) -> None:
        self._git("worktree", "prune", check=False)

    def branch_delete(self, branch: str) -> None:
        self._git("branch", "-D", branch, check=False)
