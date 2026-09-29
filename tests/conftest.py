"""Shared fixtures: a throwaway git repo, a fake `herdr` and a `gh` that sees no remote."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

from fleet.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


@dataclass
class Fleet:
    repo: Path
    bin: Path
    herdr_log: Path
    herdr_state: Path
    monkeypatch: pytest.MonkeyPatch
    capsys: pytest.CaptureFixture[str]

    def __call__(self, *argv: str) -> tuple[int, str, str]:
        self.capsys.readouterr()
        code = main(list(argv))
        out, err = self.capsys.readouterr()
        return code, out, err

    def herdr_calls(self) -> list[list[str]]:
        if not self.herdr_log.exists():
            return []
        return [json.loads(line) for line in self.herdr_log.read_text().splitlines()]

    def config(self, text: str) -> None:
        (self.repo / ".fleet.toml").write_text(text)
        git(self.repo, "add", ".fleet.toml")
        git(self.repo, "commit", "-qm", "config")

    def state(self) -> dict:
        path = self.repo / ".fleet" / "state.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def env(self, **values: str) -> None:
        for k, v in values.items():
            self.monkeypatch.setenv(k, v)


def _write_exe(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[str], Path]:
    def make(name: str = "repo") -> Path:
        repo = tmp_path / name
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        git(repo, "config", "user.email", "t@example.com")
        git(repo, "config", "user.name", "Test")
        git(repo, "config", "commit.gpgsign", "false")
        (repo / ".gitignore").write_text(".worktrees/\n.fleet/\n")
        (repo / "README.md").write_text("hello\n")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "init")
        return repo

    return make


@pytest.fixture
def fleet(
    make_repo, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> Fleet:
    repo = make_repo()
    bindir = tmp_path / "bin"
    bindir.mkdir()
    _write_exe(
        bindir / "herdr",
        f'#!/bin/sh\nexec "{sys.executable}" "{FIXTURES / "fake_herdr.py"}" "$@"\n',
    )
    _write_exe(bindir / "gh", "#!/bin/sh\necho 'no git remotes found' >&2\nexit 1\n")
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.setenv("HERDR_WORKSPACE_ID", "w1")
    monkeypatch.setenv("FAKE_HERDR_LOG", str(tmp_path / "herdr.log"))
    monkeypatch.setenv("FAKE_HERDR_STATE", str(tmp_path / "herdr.json"))
    for var in (
        "FAKE_HERDR_FAIL",
        "FAKE_HERDR_STATUS",
        "FAKE_HERDR_INTEGRATIONS",
        "FAKE_HERDR_SHELL_AFTER_WAITS",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(repo)
    return Fleet(repo, bindir, tmp_path / "herdr.log", tmp_path / "herdr.json", monkeypatch, capsys)


@pytest.fixture
def ready_fleet(fleet: Fleet) -> Fleet:
    """A repo with a passing test command and a recorded preflight."""
    fleet.config('base = "main"\ntest = "true"\n')
    code, out, err = fleet("preflight")
    assert code == 0, out + err
    return fleet
