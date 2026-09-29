import json

from tests.conftest import git


def worker_with_file(fleet, name, filename, content):
    code, _, err = fleet("spawn", "--name", name, "--branch", f"feat/{name}")
    assert code == 0, err
    wt = fleet.repo / ".worktrees" / name
    (wt / filename).write_text(content)
    git(wt, "add", filename)
    git(wt, "commit", "-qm", f"{name} work")


def test_verify_passes_disjoint_batch_and_writes_evidence(ready_fleet):
    worker_with_file(ready_fleet, "a1", "a.txt", "a\n")
    worker_with_file(ready_fleet, "b1", "b.txt", "b\n")
    code, out, err = ready_fleet("verify", "--batch", "t1")
    evidence = json.loads((ready_fleet.repo / ".fleet/evidence/t1.json").read_text())
    assert code == 0, err
    assert evidence["passed"] and [w["name"] for w in evidence["workers"]] == ["a1", "b1"]


def test_verify_runs_tests_on_the_combined_tree(ready_fleet):
    worker_with_file(ready_fleet, "a1", "a.txt", "a\n")
    worker_with_file(ready_fleet, "b1", "b.txt", "b\n")
    ready_fleet.config('base = "main"\ntest = "test -f a.txt && test -f b.txt"\n')
    assert ready_fleet("verify")[0] == 0


def test_verify_conflict_names_the_branch(ready_fleet):
    worker_with_file(ready_fleet, "a1", "same.txt", "from a\n")
    worker_with_file(ready_fleet, "b1", "same.txt", "from b\n")
    code, _, err = ready_fleet("verify", "--batch", "c1")
    evidence = json.loads((ready_fleet.repo / ".fleet/evidence/c1.json").read_text())
    assert code == 1 and "merge conflict on feat/b1" in err and evidence["conflict"] == "feat/b1"


def test_verify_test_failure_exits_1(ready_fleet):
    worker_with_file(ready_fleet, "a1", "a.txt", "a\n")
    ready_fleet.config('base = "main"\ntest = "exit 5"\n')
    code, _, err = ready_fleet("verify")
    assert code == 1 and "exit 5" in err


def test_verify_marks_workers_verified(ready_fleet):
    worker_with_file(ready_fleet, "a1", "a.txt", "a\n")
    ready_fleet("verify")
    assert ready_fleet.state()["workers"][0]["status"] == "verified"


def test_verify_cleans_up_its_worktree(ready_fleet):
    worker_with_file(ready_fleet, "a1", "a.txt", "a\n")
    ready_fleet("verify")
    assert "/.fleet/verify/" not in git(ready_fleet.repo, "worktree", "list")


def test_verify_does_not_touch_base(ready_fleet):
    before = git(ready_fleet.repo, "rev-parse", "main")
    worker_with_file(ready_fleet, "a1", "a.txt", "a\n")
    ready_fleet("verify")
    assert git(ready_fleet.repo, "rev-parse", "main") == before


def test_verify_warns_about_uncommitted_work(ready_fleet):
    worker_with_file(ready_fleet, "a1", "a.txt", "a\n")
    (ready_fleet.repo / ".worktrees/a1/wip.txt").write_text("x")
    _, _, err = ready_fleet("verify")
    assert "uncommitted changes that verify cannot see" in err


def test_verify_unknown_worker_is_usage_error(ready_fleet):
    code, _, err = ready_fleet("verify", "nobody")
    assert code == 2 and "unknown worker" in err


def test_verify_without_test_is_usage_error(fleet):
    fleet.config('base = "main"\n')
    fleet("spawn", "--name", "a1", "--branch", "feat/a1", "--permission-mode", "edits")
    code, _, err = fleet("verify")
    assert code == 2 and "`test` is unset" in err


def test_verify_dry_run_prints_plan(ready_fleet):
    worker_with_file(ready_fleet, "a1", "a.txt", "a\n")
    code, out, _ = ready_fleet("verify", "--dry-run")
    assert code == 0 and "merge --no-ff --no-edit feat/a1" in out
