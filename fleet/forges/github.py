"""GitHub via the `gh` CLI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fleet.errors import FleetError
from fleet.forges.claim import claim_issue, release_issue
from fleet.proc import Runner


@dataclass(frozen=True)
class GitHubForge:
    reader: Runner
    actor: Runner
    root: Path
    ref: str = "main"
    name: str = "github"

    def delivery_rules(self, base: str, issue: int | None) -> str:
        closes = f" Put `Closes #{issue}` in the body." if issue else ""
        return (
            f"DELIVERY: commit, push your branch, and open a DRAFT PR against `{base}`: "
            f"`gh pr create --draft --base {base} --fill`.{closes} "
            "Never run `gh pr ready`, never open a non-draft PR, never merge. "
            "Put your summary, decisions and anything left undone in the PR body."
        )

    def claim(self, issue: int, worker: str, branch: str) -> None:
        """Serialized claim through the workflow gate (§3.4). Raises ClaimDenied."""
        if self.actor.is_dry:
            self.actor.run(
                [
                    "gh",
                    "workflow",
                    "run",
                    "fleet-claim.yml",
                    "--ref",
                    self.ref,
                    "-f",
                    f"issue={issue}",
                    "-f",
                    f"worker={worker}",
                    "-f",
                    f"branch={branch}",
                    "-f",
                    "token=<uuid>",
                ]
            )
            return
        claim_issue(self.actor, self.root, issue, worker, branch, self.ref)

    def release(self, issue: int) -> None:
        release_issue(self.actor, self.root, issue)

    def _pr_number(self, branch: str) -> str:
        res = self.reader.run(
            ["gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number,isDraft"],
            cwd=self.root,
            check=False,
        )
        prs = json.loads(res.stdout or "[]") if res.ok else []
        if not prs:
            raise FleetError(
                f"no open PR for branch {branch}",
                fix="ask the worker to open its draft PR (see the brief's DELIVERY line)",
            )
        return str(prs[0]["number"])

    def mark_ready(self, branch: str, evidence_md: str) -> str:
        number = self._pr_number(branch)
        self.actor.run(["gh", "pr", "comment", number, "--body", evidence_md], cwd=self.root)
        self.actor.run(["gh", "pr", "ready", number], cwd=self.root)
        return f"PR #{number}"

    def create_labels(self) -> None:
        for label, desc in (
            ("fleet-ready", "Triaged and ready for a fleet worker"),
            ("fleet-wip", "Claimed by a fleet worker"),
        ):
            self.actor.run(
                ["gh", "label", "create", label, "--description", desc, "--force"],
                cwd=self.root,
                check=False,
            )
