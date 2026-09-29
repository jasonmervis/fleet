"""The forge contract."""

from __future__ import annotations

from typing import Protocol


class Forge(Protocol):
    name: str

    def delivery_rules(self, base: str, issue: int | None) -> str:
        """Instructions appended to every brief telling the worker how to hand work back."""
        ...

    def claim(self, issue: int, worker: str, branch: str) -> None:
        """Take exclusive ownership of an issue for a worker, or raise. Called before spawning."""
        ...

    def release(self, issue: int) -> None:
        """Give back an issue this fleet claimed (spawn rollback)."""
        ...

    def mark_ready(self, branch: str, evidence_md: str) -> str:
        """Promote a verified worker's delivery and attach the evidence. Returns a reference."""
        ...
