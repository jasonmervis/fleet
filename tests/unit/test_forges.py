import json
from pathlib import Path

import pytest

from fleet.errors import FleetError
from fleet.forges import GitHubForge, LocalForge, select_forge
from tests.unit.fakes import FakeRunner, fail, ok


def github(responses=None) -> tuple[GitHubForge, FakeRunner]:
    runner = FakeRunner(responses or {})
    return GitHubForge(reader=runner, actor=runner, root=Path(".")), runner


def test_select_forge_auto_without_remote_is_local():
    runner = FakeRunner({("gh",): fail()})
    assert select_forge("auto", Path("."), runner, runner).name == "local"


def test_select_forge_auto_with_repo_is_github():
    runner = FakeRunner({("gh", "repo", "view"): ok('{"nameWithOwner":"o/r"}')})
    assert select_forge("auto", Path("."), runner, runner).name == "github"


def test_github_delivery_requires_draft_and_closes_issue():
    rules = github()[0].delivery_rules("main", 42)
    assert "--draft" in rules and "Closes #42" in rules and "never merge" in rules


def test_local_delivery_forbids_push():
    assert "Do not push" in LocalForge().delivery_rules("main", None)


def test_github_claim_goes_through_the_workflow_gate_not_a_label_edit():
    forge, runner = github({("gh",): fail("stop after dispatch")})
    with pytest.raises(FleetError):
        forge.claim(42, "i42", "feat/42-x")
    assert runner.calls[0][:4] == ["gh", "workflow", "run", "fleet-claim.yml"]


def test_github_mark_ready_comments_before_promoting():
    forge, runner = github(
        {
            ("gh", "pr", "list"): ok(json.dumps([{"number": 9, "isDraft": True}])),
            ("gh", "pr"): ok(),
        }
    )
    forge.mark_ready("feat/x", "evidence")
    assert [c[:3] for c in runner.calls[1:]] == [["gh", "pr", "comment"], ["gh", "pr", "ready"]]


def test_github_mark_ready_without_pr_is_actionable_error():
    forge, _ = github({("gh", "pr", "list"): ok("[]")})
    with pytest.raises(FleetError, match="no open PR"):
        forge.mark_ready("feat/x", "evidence")
