from tests.conftest import git


def spawn(fleet, name="a1"):
    code, _, err = fleet("spawn", "--name", name, "--branch", f"feat/{name}")
    assert code == 0, err


def test_teardown_dry_run_contract(fleet):
    code, out, _ = fleet("teardown", "--name", "demo", "--dry-run", "--force")
    assert code == 0 and "herdr tab close" in out and "git worktree remove --force" in out


def test_teardown_dry_run_without_state_looks_tab_up(fleet):
    _, out, _ = fleet("teardown", "--name", "demo", "--dry-run")
    assert out.splitlines()[0].startswith("herdr tab list")


def test_teardown_removes_worktree_tab_and_state_but_keeps_branch(ready_fleet):
    spawn(ready_fleet)
    code, out, err = ready_fleet("teardown", "--name", "a1")
    assert code == 0, err
    assert not (ready_fleet.repo / ".worktrees" / "a1").exists()
    assert ready_fleet.state()["workers"] == []
    assert git(ready_fleet.repo, "branch", "--list", "feat/a1").strip().endswith("feat/a1")


def test_teardown_saves_transcript_first(ready_fleet):
    spawn(ready_fleet)
    ready_fleet("teardown", "--name", "a1")
    assert (ready_fleet.repo / ".fleet" / "logs" / "a1.log").is_file()


def test_teardown_refuses_uncommitted_changes_listing_files(ready_fleet):
    spawn(ready_fleet)
    (ready_fleet.repo / ".worktrees" / "a1" / "wip.txt").write_text("x")
    code, _, err = ready_fleet("teardown", "--name", "a1")
    assert code == 1 and "wip.txt" in err and (ready_fleet.repo / ".worktrees/a1").is_dir()


def test_teardown_force_discards_uncommitted_changes(ready_fleet):
    spawn(ready_fleet)
    (ready_fleet.repo / ".worktrees" / "a1" / "wip.txt").write_text("x")
    code, _, err = ready_fleet("teardown", "--name", "a1", "--force")
    assert code == 0, err


def test_teardown_all(ready_fleet):
    spawn(ready_fleet, "a1")
    spawn(ready_fleet, "b1")
    ready_fleet("teardown", "--all")
    assert ready_fleet.state()["workers"] == []


def test_teardown_requires_exactly_one_target(fleet):
    code, _, err = fleet("teardown")
    assert code == 2 and "exactly one" in err


def test_teardown_unknown_worker_errors(fleet):
    code, _, err = fleet("teardown", "--name", "ghost")
    assert code == 1 and "no worker, tab or worktree named ghost" in err


def test_teardown_github_refuses_unpushed_commits(ready_fleet):
    ready_fleet.config('base = "main"\ntest = "true"\nforge = "github"\n')
    ready_fleet("preflight")
    spawn(ready_fleet)
    wt = ready_fleet.repo / ".worktrees" / "a1"
    (wt / "f").write_text("x")
    git(wt, "add", "f")
    git(wt, "commit", "-qm", "work")
    code, _, err = ready_fleet("teardown", "--name", "a1")
    assert code == 1 and "1 commit(s) not pushed anywhere" in err


def test_teardown_local_forge_allows_unpushed_commits_since_branch_is_kept(ready_fleet):
    spawn(ready_fleet)
    wt = ready_fleet.repo / ".worktrees" / "a1"
    (wt / "f").write_text("x")
    git(wt, "add", "f")
    git(wt, "commit", "-qm", "work")
    assert ready_fleet("teardown", "--name", "a1")[0] == 0
