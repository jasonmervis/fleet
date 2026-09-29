"""Agent adapters: how to launch, configure and supervise each supported coding agent."""

from __future__ import annotations

from fleet.agents.base import AgentAdapter, Capability, probe
from fleet.agents.claude import ClaudeAdapter
from fleet.agents.codex import CodexAdapter
from fleet.errors import UsageError
from fleet.herdr import LAUNCHABLE_KINDS

ADAPTERS: dict[str, AgentAdapter] = {a.kind: a for a in (ClaudeAdapter(), CodexAdapter())}


def get_adapter(kind: str) -> AgentAdapter:
    adapter = ADAPTERS.get(kind)
    if adapter:
        return adapter
    supported = ", ".join(sorted(ADAPTERS))
    if kind in LAUNCHABLE_KINDS:
        raise UsageError(
            f"{kind}: no fleet adapter",
            why=f"herdr can launch {kind}, but fleet cannot set its model or permissions",
            fix=f"use one of: {supported}",
        )
    raise UsageError(f"unknown agent: {kind}", fix=f"use one of: {supported}")


__all__ = ["ADAPTERS", "AgentAdapter", "Capability", "get_adapter", "probe"]
