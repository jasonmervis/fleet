"""The common contract every subcommand keeps (SPEC.md › Common contract)."""

import pytest

from fleet.cli import main

COMMANDS = [
    "config",
    "preflight",
    "spawn",
    "brief",
    "up",
    "status",
    "logs",
    "verify",
    "teardown",
    "init",
    "doctor",
]


@pytest.mark.parametrize("command", COMMANDS)
def test_help_prints_usage_and_exits_0(command, capsys):
    with pytest.raises(SystemExit) as exc:
        main([command, "--help"])
    assert exc.value.code == 0 and "Usage:" in capsys.readouterr().out


def test_version_prints_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert capsys.readouterr().out.startswith("fleet ")


def test_spawn_missing_name_exits_2_naming_option(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["spawn", "--branch", "feat/x", "--dry-run"])
    assert exc.value.code == 2 and "--name" in capsys.readouterr().err


def test_invalid_name_exits_2(fleet):
    code, _, err = fleet("spawn", "--name", "../evil", "--branch", "x", "--dry-run")
    assert code == 2 and "--name" in err


def test_runtime_error_renders_what_why_fix(fleet):
    fleet.monkeypatch.delenv("HERDR_ENV")
    code, _, err = fleet("status")
    assert code == 1 and err.startswith("error: not running inside Herdr") and "  fix:" in err


def test_fleet_refuses_to_run_inside_a_worker_worktree(fleet):
    wt = fleet.repo / ".worktrees" / "w"
    import subprocess

    subprocess.run(
        ["git", "worktree", "add", "-q", str(wt), "-b", "feat/w"], cwd=fleet.repo, check=True
    )
    fleet.monkeypatch.chdir(wt)
    code, _, err = fleet("status")
    assert code == 1 and "inside a worker worktree" in err
