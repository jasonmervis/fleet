"""Serialized issue claims (playbook §3.4).

Labels have no compare-and-swap, so two clients running `gh issue edit --add-label fleet-wip`
can both succeed. The `fleet-claim.yml` workflow is the lock: GitHub serialises its runs per
issue, the run re-checks eligibility, then records a unique token on the issue. Ownership is
granted only when this client finds its own token there afterwards.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from fleet.errors import FleetError
from fleet.proc import Runner

WORKFLOW = "fleet-claim.yml"
_RUN_URL = re.compile(r"/actions/runs/(?P<run_id>[0-9]+)(?:/|$)")


class ClaimDenied(FleetError):
    pass


def _gh(runner: Runner, root: Path, *args: str) -> str:
    res = runner.run(["gh", *args], cwd=root, check=False)
    if not res.ok:
        raise ClaimDenied(
            f"claim failed: gh {' '.join(args[:2])}",
            why=(res.stderr or res.stdout).strip()[:300],
            fix=f"check `{WORKFLOW}` exists on the default branch (`fleet init`) and gh auth",
        )
    return res.stdout.strip()


def _find_run(runner: Runner, root: Path, title: str) -> int | None:
    listing = _gh(
        runner,
        root,
        "run",
        "list",
        "--workflow",
        WORKFLOW,
        "--event",
        "workflow_dispatch",
        "--limit",
        "100",
        "--json",
        "databaseId,displayTitle",
    )
    for run in json.loads(listing or "[]"):
        if run.get("displayTitle") == title and isinstance(run.get("databaseId"), int):
            return run["databaseId"]
    return None


def verify_grant(issue_json: str, token: str) -> None:
    """Require the label transition and this request's marker comment."""
    issue = json.loads(issue_json)
    labels = {lbl.get("name") for lbl in issue.get("labels", []) if isinstance(lbl, dict)}
    if issue.get("state") != "OPEN":
        raise ClaimDenied("claim denied: the issue is no longer open")
    if "fleet-wip" not in labels or "fleet-ready" in labels:
        raise ClaimDenied("claim denied: labels do not show an active fleet claim")
    marker = f"<!-- fleet-claim-token:{token} -->"
    if not any(marker in (c.get("body") or "") for c in issue.get("comments", [])):
        raise ClaimDenied(
            "claim denied: another worker holds this issue",
            fix="pick another issue",
        )


def claim_issue(
    runner: Runner,
    root: Path,
    issue: int,
    worker: str,
    branch: str,
    ref: str,
    sleep: Callable[[float], None] = time.sleep,
    lookup_attempts: int = 30,
) -> str:
    """Dispatch, await and verify a claim. Returns the token. Raises ClaimDenied."""
    token = str(uuid.uuid4())
    title = f"claim-issue-{issue}-{token}"
    out = _gh(
        runner,
        root,
        "workflow",
        "run",
        WORKFLOW,
        "--ref",
        ref,
        "-f",
        f"issue={issue}",
        "-f",
        f"worker={worker}",
        "-f",
        f"branch={branch}",
        "-f",
        f"token={token}",
    )
    match = _RUN_URL.search(out)
    run_id = int(match.group("run_id")) if match else None
    for attempt in range(lookup_attempts):
        if run_id is not None:
            break
        run_id = _find_run(runner, root, title)
        if run_id is None and attempt + 1 < lookup_attempts:
            sleep(2)
    if run_id is None:
        raise ClaimDenied(f"claim failed: could not find workflow run {title}")
    _gh(runner, root, "run", "watch", str(run_id), "--exit-status", "--compact")
    verify_grant(
        _gh(runner, root, "issue", "view", str(issue), "--json", "state,labels,comments"), token
    )
    return token


def release_issue(runner: Runner, root: Path, issue: int) -> None:
    """Undo our own granted claim (spawn rollback). Safe: only the holder calls it."""
    runner.run(
        [
            "gh",
            "issue",
            "edit",
            str(issue),
            "--remove-label",
            "fleet-wip",
            "--add-label",
            "fleet-ready",
        ],
        cwd=root,
        check=False,
    )
