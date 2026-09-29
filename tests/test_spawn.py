import multiprocessing
import os
from pathlib import Path

from tests.conftest import git


def spawn(fleet, *extra):
    return fleet("spawn", "--name", "a1", "--branch", "feat/a1", *extra)


def test_spawn_dry_run_prints_commands_in_order_and_creates_nothing(fleet):
    fleet.config('base = "main"\n')
    code, out, _ = spawn(fleet, "--dry-run")
    lines = out.splitlines()
    assert (
        code == 0
        and lines[0].startswith("git worktree add")
        and lines[1].startswith("herdr tab create")
        and lines[2].startswith("herdr pane wait-output")
        and "--timeout 15000" in lines[2]
        and lines[3].startswith("herdr agent start")
        and not (fleet.repo / ".worktrees").exists()
        and fleet.herdr_calls() == []
    )


def test_spawn_dry_run_uses_config_base(fleet):
    fleet.config('base = "develop"\n')
    _, out, _ = spawn(fleet, "--dry-run")
    assert out.splitlines()[0].endswith(" develop")


def test_spawn_dry_run_passes_agent_and_model(fleet):
    fleet.config('base = "main"\n')
    _, out, _ = spawn(fleet, "--dry-run", "--agent", "codex", "--model", "o4-mini")
    assert "--kind codex" in out and "--model o4-mini" in out


def test_spawn_dry_run_runs_install_in_worktree(fleet):
    fleet.config('base = "main"\ninstall = "make deps"\n')
    _, out, _ = spawn(fleet, "--dry-run")
    assert ".worktrees/a1 && make deps" in out.splitlines()[1]


def test_spawn_creates_worktree_tab_agent_and_state(ready_fleet):
    code, out, err = spawn(ready_fleet)
    worker = ready_fleet.state()["workers"][0]
    assert code == 0, err
    assert (ready_fleet.repo / ".worktrees" / "a1").is_dir()
    assert (worker["tab_id"], worker["pane_id"], worker["supervised"]) == ("w1:t1", "w1:p1", True)


def test_spawn_passes_claude_launch_args(ready_fleet):
    spawn(ready_fleet, "--model", "sonnet")
    start = next(c for c in ready_fleet.herdr_calls() if c[:2] == ["agent", "start"])
    assert start[start.index("--") + 1 :] == ["--permission-mode", "auto", "--model", "sonnet"]


def test_spawn_failure_at_tab_rolls_back_everything(ready_fleet):
    ready_fleet.env(FAKE_HERDR_FAIL="tab create")
    code, _, err = spawn(ready_fleet)
    assert code == 1 and "step `tab`" in err
    assert not (ready_fleet.repo / ".worktrees" / "a1").exists()
    assert "feat/a1" not in git(ready_fleet.repo, "branch", "--list", "feat/a1")
    assert ready_fleet.state().get("workers") in (None, [])


def test_spawn_failure_at_agent_closes_the_tab(ready_fleet):
    ready_fleet.env(FAKE_HERDR_FAIL="agent start")
    code, _, err = spawn(ready_fleet)
    closes = [c for c in ready_fleet.herdr_calls() if c[:2] == ["tab", "close"]]
    assert code == 1 and "step `agent`" in err and closes == [["tab", "close", "w1:t1"]]


def _calls(fleet, *prefix):
    return [c for c in fleet.herdr_calls() if c[: len(prefix)] == list(prefix)]


def test_spawn_waits_for_shell_prompt_before_starting_agent(ready_fleet):
    code, _, err = spawn(ready_fleet)
    calls = ready_fleet.herdr_calls()
    wait = next(c for c in calls if c[:2] == ["pane", "wait-output"])
    start = next(c for c in calls if c[:2] == ["agent", "start"])
    assert code == 0, err
    assert calls.index(wait) < calls.index(start)
    assert wait[2] == "w1:p1" and wait[wait.index("--regex") + 1] == "[$%❯] *$"
    assert wait[wait.index("--timeout") + 1] == "15000"


def test_spawn_uses_configured_shell_prompt_regex(ready_fleet):
    ready_fleet.config('base = "main"\ntest = "true"\nshell_prompt_regex = "> $"\n')
    ready_fleet("preflight")
    code, _, err = spawn(ready_fleet)
    wait = _calls(ready_fleet, "pane", "wait-output")[0]
    assert code == 0, err
    assert wait[wait.index("--regex") + 1] == "> $"


def test_spawn_retries_agent_start_while_pane_is_busy(ready_fleet):
    ready_fleet.env(FAKE_HERDR_SHELL_AFTER_WAITS="2")
    code, _, err = spawn(ready_fleet)
    steps = [c[:2] for c in ready_fleet.herdr_calls() if c[0] in ("pane", "agent")]
    assert code == 0, err
    assert steps == [
        ["pane", "wait-output"],
        ["agent", "start"],
        ["pane", "wait-output"],
        ["agent", "start"],
    ]
    assert "pane w1:p1 busy" in err and ready_fleet.state()["workers"][0]["name"] == "a1"


def test_spawn_gives_up_after_three_busy_attempts_and_closes_tab(ready_fleet):
    ready_fleet.env(FAKE_HERDR_SHELL_AFTER_WAITS="9")
    code, _, err = spawn(ready_fleet)
    assert code == 1 and "step `agent`" in err and "agent_pane_busy" in err
    assert len(_calls(ready_fleet, "agent", "start")) == 3
    assert _calls(ready_fleet, "tab", "close") == [["tab", "close", "w1:t1"]]
    assert not (ready_fleet.repo / ".worktrees" / "a1").exists()


def test_spawn_shell_prompt_timeout_fails_named_step_and_rolls_back(ready_fleet):
    ready_fleet.env(FAKE_HERDR_FAIL="pane wait-output")
    code, _, err = spawn(ready_fleet)
    assert code == 1 and "step `shell`" in err
    assert "fix:" in err and "w1:p1" in err.split("fix:", 1)[1]
    assert _calls(ready_fleet, "agent", "start") == []
    assert _calls(ready_fleet, "tab", "close") == [["tab", "close", "w1:t1"]]
    assert not (ready_fleet.repo / ".worktrees" / "a1").exists()
    assert ready_fleet.state().get("workers") in (None, [])


def test_spawn_install_failure_rolls_back(ready_fleet):
    ready_fleet.config('base = "main"\ntest = "true"\ninstall = "exit 4"\n')
    ready_fleet("preflight")
    code, _, err = spawn(ready_fleet)
    assert (
        code == 1 and "step `install`" in err and not (ready_fleet.repo / ".worktrees/a1").exists()
    )


def test_spawn_auto_without_preflight_is_refused(fleet):
    fleet.config('base = "main"\ntest = "true"\n')
    code, _, err = spawn(fleet)
    assert code == 1 and "needs a passing preflight" in err


def test_spawn_auto_after_base_moved_is_refused(ready_fleet):
    (ready_fleet.repo / "new").write_text("x")
    git(ready_fleet.repo, "add", "new")
    git(ready_fleet.repo, "commit", "-qm", "move base")
    code, _, err = spawn(ready_fleet)
    assert code == 1 and "needs a passing preflight" in err


def test_spawn_edits_mode_does_not_need_preflight(fleet):
    fleet.config('base = "main"\n')
    code, _, err = spawn(fleet, "--permission-mode", "edits")
    assert code == 0, err


def test_spawn_duplicate_name_is_refused(ready_fleet):
    spawn(ready_fleet)
    code, _, err = ready_fleet("spawn", "--name", "a1", "--branch", "feat/other")
    assert code == 1 and "already exists" in err


def test_spawn_existing_branch_is_refused(ready_fleet):
    git(ready_fleet.repo, "branch", "feat/a1")
    code, _, err = spawn(ready_fleet)
    assert code == 1 and "branch feat/a1 already exists" in err


def test_spawn_beyond_max_workers_is_refused(ready_fleet):
    ready_fleet.config('base = "main"\ntest = "true"\nmax_workers = 1\n')
    ready_fleet("preflight")
    spawn(ready_fleet)
    code, _, err = ready_fleet("spawn", "--name", "b1", "--branch", "feat/b1")
    assert code == 1 and "max_workers reached (1)" in err


def test_spawn_kiro_has_no_adapter(ready_fleet):
    code, _, err = spawn(ready_fleet, "--agent", "kiro")
    assert code == 2 and "kiro: no fleet adapter" in err


def test_spawn_codex_without_integration_is_refused(ready_fleet):
    code, _, err = spawn(ready_fleet, "--agent", "codex")
    assert code == 1 and "herdr integration install codex" in err


def test_spawn_codex_allow_unsupervised_marks_worker(ready_fleet):
    code, _, err = spawn(ready_fleet, "--agent", "codex", "--allow-unsupervised")
    assert code == 0, err
    assert ready_fleet.state()["workers"][0]["supervised"] is False


def _spawn_in_child(repo: str, name: str, queue) -> None:
    os.chdir(repo)
    from fleet.cli import main

    queue.put(main(["spawn", "--name", name, "--branch", f"feat/{name}"]))


def test_concurrent_spawns_are_serialised_by_the_lock(ready_fleet):
    from fleet.state import StateStore

    with StateStore(Path(ready_fleet.repo)).lock("other"):
        q = multiprocessing.get_context("fork").Queue()
        p = multiprocessing.get_context("fork").Process(
            target=_spawn_in_child, args=(str(ready_fleet.repo), "c1", q)
        )
        p.start()
        p.join(30)
        assert q.get(timeout=5) == 1


def test_spawn_denied_claim_creates_nothing(ready_fleet):
    ready_fleet.config('base = "main"\ntest = "true"\nforge = "github"\n')
    ready_fleet("preflight")
    code, _, err = spawn(ready_fleet, "--issue", "42")
    assert code == 1 and "step `claim`" in err
    assert not (ready_fleet.repo / ".worktrees").exists() and ready_fleet.herdr_calls()[-1][:2] != [
        "tab",
        "create",
    ]


def test_spawn_dry_run_with_issue_shows_claim_first(fleet):
    fleet.config('base = "main"\nforge = "github"\n')
    _, out, _ = spawn(fleet, "--dry-run", "--issue", "42")
    assert out.splitlines()[0].startswith("gh workflow run fleet-claim.yml")


def test_spawn_empty_allowlist_flag_clears_global_allowlist_for_codex(ready_fleet):
    ready_fleet.config('base = "main"\ntest = "true"\nallowlist = ["Edit"]\n')
    ready_fleet("preflight")
    code, _, err = spawn(ready_fleet, "--agent", "codex", "--allow-unsupervised", "--allowlist")
    assert code == 0, err
