import json
from pathlib import Path

import pytest

from fleet.forges.claim import ClaimDenied, claim_issue, verify_grant
from tests.unit.fakes import FakeRunner, fail, ok


def issue_json(token: str, labels=("fleet-wip",), state="OPEN") -> str:
    return json.dumps(
        {
            "state": state,
            "labels": [{"name": n} for n in labels],
            "comments": [{"body": f"<!-- fleet-claim-token:{token} -->\\nClaim granted"}],
        }
    )


class Scripted(FakeRunner):
    """Returns the dispatched token back in the issue view, as a granting workflow would."""

    def __init__(self, grant: bool = True, run_url: bool = True, **extra):
        super().__init__(extra)
        self.grant, self.run_url, self.token = grant, run_url, ""

    def run(self, argv, cwd=None, check=True, timeout_s=None):
        self.calls.append(list(argv))
        if argv[:3] == ["gh", "workflow", "run"]:
            self.token = next(a for a in argv if a.startswith("token=")).split("=", 1)[1]
            url = "https://github.com/o/r/actions/runs/77\n" if self.run_url else ""
            return ok(url)
        if argv[:3] == ["gh", "run", "list"]:
            return ok(
                json.dumps([{"databaseId": 88, "displayTitle": f"claim-issue-4-{self.token}"}])
            )
        if argv[:3] == ["gh", "run", "watch"]:
            return ok() if self.grant else fail("#4 is already claimed")
        if argv[:3] == ["gh", "issue", "view"]:
            return ok(issue_json(self.token))
        return fail()


def test_claim_granted_returns_token_and_watches_run():
    runner = Scripted()
    token = claim_issue(runner, Path("."), 4, "i4", "feat/4-x", "main", sleep=lambda s: None)
    assert token == runner.token and runner.calls[1][:4] == ["gh", "run", "watch", "77"]


def test_claim_finds_run_by_title_when_dispatch_prints_no_url():
    runner = Scripted(run_url=False)
    claim_issue(runner, Path("."), 4, "i4", "feat/4-x", "main", sleep=lambda s: None)
    assert any(c[:4] == ["gh", "run", "watch", "88"] for c in runner.calls)


def test_claim_denied_when_workflow_run_fails():
    with pytest.raises(ClaimDenied, match="gh run watch"):
        claim_issue(Scripted(grant=False), Path("."), 4, "i4", "feat/4-x", "main")


def test_claim_run_never_appears_is_denied():
    runner = FakeRunner({("gh", "workflow", "run"): ok(""), ("gh", "run", "list"): ok("[]")})
    with pytest.raises(ClaimDenied, match="could not find workflow run"):
        claim_issue(
            runner, Path("."), 4, "i4", "b", "main", sleep=lambda s: None, lookup_attempts=2
        )


def test_verify_grant_rejects_someone_elses_token():
    with pytest.raises(ClaimDenied, match="another worker"):
        verify_grant(issue_json("theirs"), "mine")


def test_verify_grant_rejects_closed_issue():
    with pytest.raises(ClaimDenied, match="no longer open"):
        verify_grant(issue_json("t", state="CLOSED"), "t")


def test_verify_grant_rejects_labels_without_wip():
    with pytest.raises(ClaimDenied, match="labels"):
        verify_grant(issue_json("t", labels=("fleet-ready",)), "t")
