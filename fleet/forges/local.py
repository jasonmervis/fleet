"""No remote: workers commit to their branch; evidence stays in `.fleet/evidence/`."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LocalForge:
    name: str = "local"

    def delivery_rules(self, base: str, issue: int | None) -> str:
        return (
            "DELIVERY: commit your work to your current branch with clear messages. "
            "Do not push, do not open a PR, do not merge, do not switch branches. "
            "End with a short summary: what you did, decisions you made, anything left undone."
        )

    def claim(self, issue: int, worker: str, branch: str) -> None:
        return None

    def release(self, issue: int) -> None:
        return None

    def mark_ready(self, branch: str, evidence_md: str) -> str:
        return f"branch {branch} (local; evidence in .fleet/evidence/)"
