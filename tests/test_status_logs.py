import json

from fleet.commands.status import elapsed_minutes


def spawn(fleet, name="a1"):
    code, _, err = fleet("spawn", "--name", name, "--branch", f"feat/{name}")
    assert code == 0, err


def test_status_dry_run_prints_agent_list(fleet):
    code, out, _ = fleet("status", "--dry-run")
    assert code == 0 and out.startswith("herdr agent list")


def test_status_with_no_workers_says_so(fleet):
    assert fleet("status")[1].strip() == "no workers"


def test_status_shows_worker_row(ready_fleet):
    spawn(ready_fleet)
    _, out, _ = ready_fleet("status")
    row = out.splitlines()[1]
    assert row.startswith("a1") and "claude/default" in row and "feat/a1" in row and "idle" in row


def test_status_json_is_machine_readable(ready_fleet):
    spawn(ready_fleet)
    rows = json.loads(ready_fleet("status", "--json")[1])
    assert (rows[0]["name"], rows[0]["diff"]) == ("a1", "+0/-0")


def test_status_flags_gone_worker(ready_fleet):
    spawn(ready_fleet)
    ready_fleet.herdr_state.write_text(json.dumps({"tabs": [], "agents": [], "n": 1}))
    rows = json.loads(ready_fleet("status", "--json")[1])
    assert rows[0]["state"] == "gone" and "gone" in rows[0]["flags"]


def test_status_flags_untracked_agent_in_worktrees(ready_fleet):
    cwd = str(ready_fleet.repo / ".worktrees" / "stray")
    ready_fleet.herdr_state.write_text(
        json.dumps(
            {
                "tabs": [],
                "n": 0,
                "agents": [
                    {
                        "name": "stray",
                        "agent": "claude",
                        "pane_id": "w1:p9",
                        "workspace_id": "w1",
                        "cwd": cwd,
                        "agent_status": "working",
                    }
                ],
            }
        )
    )
    rows = json.loads(ready_fleet("status", "--json")[1])
    assert rows[0]["flags"] == ["untracked"]


def test_status_ignores_other_workspaces(ready_fleet):
    spawn(ready_fleet)
    assert json.loads(ready_fleet("status", "--json", "--workspace", "w9")[1])[0]["state"] == "gone"


def test_status_blocked_includes_screen_text(ready_fleet):
    spawn(ready_fleet)
    ready_fleet.env(FAKE_HERDR_STATUS="blocked")
    _, out, _ = ready_fleet("status", "--blocked")
    assert "| Would you like to proceed?" in out


def test_status_blocked_with_none_blocked(ready_fleet):
    spawn(ready_fleet)
    assert ready_fleet("status", "--blocked")[1].strip() == "no blocked workers"


def test_status_flags_overrun(ready_fleet):
    ready_fleet.config('base = "main"\ntest = "true"\nmax_minutes = 0\n')
    ready_fleet("preflight")
    spawn(ready_fleet)
    state = ready_fleet.state()
    state["workers"][0]["started_at"] = "2000-01-01T00:00:00+00:00"
    (ready_fleet.repo / ".fleet" / "state.json").write_text(json.dumps(state))
    assert "overrun" in json.loads(ready_fleet("status", "--json")[1])[0]["flags"]


def test_elapsed_minutes_bad_timestamp_is_zero():
    assert elapsed_minutes("not-a-date") == 0


def test_logs_writes_transcript(ready_fleet):
    spawn(ready_fleet)
    code, out, _ = ready_fleet("logs", "a1")
    assert (
        code == 0 and "transcript of w1:p1" in (ready_fleet.repo / ".fleet/logs/a1.log").read_text()
    )
