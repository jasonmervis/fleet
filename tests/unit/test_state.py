import json
import os
import time
from pathlib import Path

import pytest

from fleet.errors import FleetError
from fleet.state import FleetState, Preflight, StateStore, Worker


def worker(name: str = "a", **kw) -> Worker:
    base = dict(
        name=name,
        branch=f"feat/{name}",
        base="main",
        base_sha="abc",
        agent="claude",
        model="",
        worktree=f"/r/.worktrees/{name}",
        tab_id="w1:t1",
        pane_id="w1:p1",
        started_at="2026-01-01T00:00:00+00:00",
    )
    return Worker(**{**base, **kw})


def test_state_round_trips_through_disk(tmp_path: Path):
    store = StateStore(tmp_path)
    state = FleetState().with_worker(worker(issue=7)).with_preflight(Preflight("main", "abc", "t"))
    store.save(state)
    assert store.load() == state


def test_missing_state_file_loads_empty(tmp_path: Path):
    assert StateStore(tmp_path).load() == FleetState()


def test_with_worker_does_not_mutate_original():
    original = FleetState()
    original.with_worker(worker())
    assert original.workers == ()


def test_with_worker_replaces_same_name():
    state = FleetState().with_worker(worker(model="a")).with_worker(worker(model="b"))
    assert [w.model for w in state.workers] == ["b"]


def test_updated_unknown_worker_is_noop():
    state = FleetState()
    assert state.updated("nope", status="x") is state


def test_corrupt_state_file_raises_actionable_error(tmp_path: Path):
    (tmp_path / ".fleet").mkdir()
    (tmp_path / ".fleet" / "state.json").write_text("{not json")
    with pytest.raises(FleetError, match="corrupt state"):
        StateStore(tmp_path).load()


def test_save_leaves_no_temp_file(tmp_path: Path):
    StateStore(tmp_path).save(FleetState())
    assert sorted(p.name for p in (tmp_path / ".fleet").iterdir()) == ["state.json"]


def test_lock_is_exclusive(tmp_path: Path):
    store = StateStore(tmp_path)
    with (
        store.lock("spawn"),
        pytest.raises(FleetError, match=f"locked by pid {os.getpid()}"),
        store.lock("spawn"),
    ):
        pass


def test_lock_released_after_exception(tmp_path: Path):
    store = StateStore(tmp_path)
    with pytest.raises(RuntimeError), store.lock("spawn"):
        raise RuntimeError
    with store.lock("spawn"):
        pass


def test_lock_held_by_dead_pid_is_taken_over(tmp_path: Path):
    (tmp_path / ".fleet").mkdir()
    (tmp_path / ".fleet" / "lock").write_text(json.dumps({"pid": 2**22 + 7, "at": time.time()}))
    with StateStore(tmp_path).lock("spawn"):
        pass


def test_lock_older_than_stale_window_is_taken_over(tmp_path: Path):
    (tmp_path / ".fleet").mkdir()
    (tmp_path / ".fleet" / "lock").write_text(json.dumps({"pid": os.getpid(), "at": 0}))
    with StateStore(tmp_path).lock("spawn"):
        pass
