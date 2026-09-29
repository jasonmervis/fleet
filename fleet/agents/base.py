"""The adapter contract every agent implements, and the Herdr capability probe."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fleet.herdr import LAUNCHABLE_KINDS, Herdr


@dataclass(frozen=True)
class Capability:
    kind: str
    can_launch: bool
    has_lifecycle: bool
    integration: str

    @property
    def install_hint(self) -> str:
        return f"herdr integration install {self.kind}"


class AgentAdapter(Protocol):
    kind: str

    def launch_args(
        self, model: str, permission_mode: str, allowlist: tuple[str, ...]
    ) -> list[str]:
        """CLI args passed to the agent after `herdr agent start … --`."""
        ...


def probe(kind: str, herdr: Herdr) -> Capability:
    """Can herdr launch this kind, and does it have a lifecycle integration installed?"""
    status = herdr.integrations().get(kind, "no integration")
    return Capability(
        kind=kind,
        can_launch=kind in LAUNCHABLE_KINDS,
        has_lifecycle=status.startswith("current"),
        integration=status,
    )
