import pytest

from fleet.errors import FleetError, UsageError
from fleet.herdr import Herdr, parse_version
from fleet.skill_files import read_stamp, stamp
from tests.unit.fakes import FakeRunner, ok

SKILL = "---\nname: fleet\ndescription: x\n---\n\n# body\n---\nnot frontmatter\n"


def test_parse_version_reads_semver():
    assert parse_version("herdr 0.10.2") == (0, 10, 2)


def test_parse_version_without_version_is_empty():
    assert parse_version("command not found") == ()


def test_version_comparison_is_numeric_not_lexical():
    assert parse_version("herdr 0.10.0") >= (0, 9, 0)


def test_stamp_inserts_into_frontmatter_only():
    stamped = stamp(SKILL, "1.2.3")
    assert read_stamp(stamped) == "1.2.3" and stamped.endswith("---\nnot frontmatter\n")


def test_stamp_replaces_existing_version():
    assert read_stamp(stamp(stamp(SKILL, "1.0.0"), "2.0.0")) == "2.0.0"


def test_stamp_is_idempotent():
    once = stamp(SKILL, "1.0.0")
    assert stamp(once, "1.0.0") == once


def test_read_stamp_missing_is_empty():
    assert read_stamp(SKILL) == ""


def test_stamp_without_frontmatter_raises():
    with pytest.raises(ValueError):
        stamp("# no frontmatter", "1.0.0")


def test_error_render_includes_what_why_fix():
    text = FleetError("broke", why="because", fix="do this").render()
    assert text == "error: broke\n  why: because\n  fix: do this"


def test_usage_error_exits_2():
    assert UsageError("x").exit_code == 2


def test_herdr_tab_create_without_ids_raises():
    herdr = Herdr(FakeRunner({("herdr", "tab", "create"): ok('{"result": {}}')}))
    with pytest.raises(FleetError, match="no tab/pane id"):
        herdr.tab_create("w1", "/x", "a")


def test_herdr_non_json_output_raises_actionable_error():
    herdr = Herdr(FakeRunner({("herdr", "agent", "list"): ok("Usage: nope")}))
    with pytest.raises(FleetError, match="unexpected output"):
        herdr.agent_list()


def test_herdr_pane_wait_output_runs_wait_with_regex_and_timeout():
    runner = FakeRunner({("herdr", "pane", "wait-output"): ok('{"result": {"matched": true}}')})
    Herdr(runner).pane_wait_output("w1:p1", "[$%] *$", 15000)
    assert runner.calls == [
        ["herdr", "pane", "wait-output", "w1:p1", "--regex", "[$%] *$", "--timeout", "15000"]
    ]


def test_herdr_pane_wait_output_timeout_names_the_pane_in_fix():
    runner = FakeRunner()  # unscripted -> exit 1, like a herdr timeout
    with pytest.raises(FleetError) as info:
        Herdr(runner).pane_wait_output("w1:p1", "[$%] *$", 15000)
    err = info.value
    assert "w1:p1" in err.what and "w1:p1" in err.fix and "shell_prompt_regex" in err.fix


def test_herdr_pane_busy_detects_the_agent_pane_busy_code():
    from fleet.herdr import pane_busy

    busy = FleetError("command failed (1): herdr agent start", why='{"code":"agent_pane_busy"}')
    assert pane_busy(busy) and not pane_busy(FleetError("x", why="agent_not_ready"))
