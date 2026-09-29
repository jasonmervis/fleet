import pytest

from fleet.agents import get_adapter, probe
from fleet.errors import UsageError
from fleet.herdr import Herdr
from tests.unit.fakes import FakeRunner, ok

STATUS = "claude: current (v9) (/x/.claude/h.sh)\ncodex: not installed (/x/.codex/h.sh)\n"


@pytest.mark.parametrize(
    ("mode", "expected"), [("auto", "auto"), ("edits", "acceptEdits"), ("readonly", "plan")]
)
def test_claude_maps_permission_modes(mode, expected):
    assert get_adapter("claude").launch_args("", mode, ())[:2] == ["--permission-mode", expected]


def test_claude_passes_model_and_allowlist():
    args = get_adapter("claude").launch_args("sonnet", "auto", ("Bash(git:*)", "Edit"))
    assert args[2:] == ["--model", "sonnet", "--allowedTools", "Bash(git:*)", "Edit"]


def test_claude_omits_model_when_unset():
    assert "--model" not in get_adapter("claude").launch_args("", "auto", ())


@pytest.mark.parametrize(
    ("mode", "sandbox", "approval"),
    [
        ("auto", "workspace-write", "never"),
        ("edits", "workspace-write", "on-request"),
        ("readonly", "read-only", "on-request"),
    ],
)
def test_codex_maps_permission_modes(mode, sandbox, approval):
    args = get_adapter("codex").launch_args("", mode, ())
    assert args == ["--sandbox", sandbox, "--ask-for-approval", approval]


def test_codex_passes_model():
    assert get_adapter("codex").launch_args("o4-mini", "auto", ())[-2:] == ["--model", "o4-mini"]


def test_codex_refuses_allowlist_rather_than_ignoring_it():
    with pytest.raises(UsageError, match="allowlist"):
        get_adapter("codex").launch_args("", "auto", ("Edit",))


def test_launchable_kind_without_adapter_says_so():
    with pytest.raises(UsageError, match="kiro: no fleet adapter"):
        get_adapter("kiro")


def test_unknown_kind_is_usage_error():
    with pytest.raises(UsageError, match="unknown agent"):
        get_adapter("clippy")


def test_probe_reports_lifecycle_from_integration_status():
    herdr = Herdr(FakeRunner({("herdr", "integration", "status"): ok(STATUS)}))
    assert (probe("claude", herdr).has_lifecycle, probe("codex", herdr).has_lifecycle) == (
        True,
        False,
    )


def test_probe_strips_hook_path_from_status():
    herdr = Herdr(FakeRunner({("herdr", "integration", "status"): ok(STATUS)}))
    assert probe("codex", herdr).integration == "not installed"
