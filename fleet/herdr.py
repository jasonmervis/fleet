"""Typed wrapper over the `herdr` CLI (verified against 0.9.0)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from fleet.errors import FleetError
from fleet.proc import Runner

MIN_VERSION = (0, 9, 0)
# A fresh tab's shell took ~2 s to print its prompt in practice; `agent start` before that fails.
SHELL_PROMPT_TIMEOUT_MS = 15_000
PANE_BUSY = "agent_pane_busy"
SETTLED_STATES = frozenset({"idle", "done", "blocked"})

# `herdr agent start --kind` choices in 0.9.0.
LAUNCHABLE_KINDS = frozenset(
    {
        "pi",
        "claude",
        "codex",
        "gemini",
        "cursor",
        "devin",
        "agy",
        "cline",
        "omp",
        "mastracode",
        "opencode",
        "copilot",
        "kimi",
        "kiro",
        "droid",
        "amp",
        "grok",
        "hermes",
        "kilo",
        "qodercli",
        "qwen",
        "maki",
        "muse",
    }
)


@dataclass(frozen=True)
class Tab:
    tab_id: str
    pane_id: str


def require_inside() -> str:
    """Return the current workspace id, or fail if not running inside Herdr."""
    if os.environ.get("HERDR_ENV") != "1":
        raise FleetError(
            "not running inside Herdr",
            why="fleet drives workers through Herdr tabs in the current workspace",
            fix="start herdr, open this repo in a workspace, and run fleet from its tab",
        )
    ws = os.environ.get("HERDR_WORKSPACE_ID", "")
    if not ws:
        raise FleetError("HERDR_WORKSPACE_ID is unset", fix="run fleet from inside a Herdr tab")
    return ws


def pane_busy(exc: FleetError) -> bool:
    """True when herdr refused `agent start` because the pane is not at a shell prompt yet."""
    return PANE_BUSY in exc.why


def parse_version(text: str) -> tuple[int, ...]:
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    return tuple(int(p) for p in match.groups()) if match else ()


class Herdr:
    def __init__(self, runner: Runner) -> None:
        self._run = runner

    def _json(self, argv: list[str]) -> dict:
        result = self._run.run(["herdr", *argv])
        if self._run.is_dry:
            return {}
        try:
            return json.loads(result.stdout).get("result", {})
        except json.JSONDecodeError as exc:
            raise FleetError(
                f"unexpected output from herdr {' '.join(argv[:2])}",
                why=result.stdout[:200],
                fix="check `herdr --version` meets the minimum (fleet doctor)",
            ) from exc

    def version(self) -> tuple[int, ...]:
        return parse_version(self._run.run(["herdr", "--version"], check=False).stdout)

    def integrations(self) -> dict[str, str]:
        """kind -> status text, e.g. {'claude': 'current (v9)', 'codex': 'not installed'}."""
        out = self._run.run(["herdr", "integration", "status"], check=False).stdout
        found: dict[str, str] = {}
        for line in out.splitlines():
            kind, sep, rest = line.partition(":")
            if sep:
                found[kind.strip()] = re.sub(r"\s*\(/.*\)\s*$", "", rest).strip()
        return found

    def tab_create(self, workspace: str, cwd: str, label: str) -> Tab:
        res = self._json(
            [
                "tab",
                "create",
                "--workspace",
                workspace,
                "--cwd",
                cwd,
                "--label",
                label,
                "--no-focus",
            ]
        )
        if self._run.is_dry:
            return Tab("<tab_id>", "<pane_id>")
        tab = (res.get("tab") or {}).get("tab_id")
        pane = (res.get("root_pane") or {}).get("pane_id")
        if not tab or not pane:
            raise FleetError(f"herdr tab create returned no tab/pane id for {label}")
        return Tab(tab, pane)

    def tab_list(self, workspace: str) -> list[dict]:
        return self._json(["tab", "list", "--workspace", workspace]).get("tabs", [])

    def tab_close(self, tab_id: str) -> None:
        self._run.run(["herdr", "tab", "close", tab_id])

    def pane_wait_output(self, pane_id: str, regex: str, timeout_ms: int) -> None:
        """Block until the pane shows text matching `regex` — a shell prompt — or fail."""
        res = self._run.run(
            [
                "herdr",
                "pane",
                "wait-output",
                pane_id,
                "--regex",
                regex,
                "--timeout",
                str(timeout_ms),
            ],
            check=False,
            timeout_s=timeout_ms / 1000 + 30,
        )
        if self._run.is_dry or res.ok:
            return
        raise FleetError(
            f"pane {pane_id} showed no shell prompt within {timeout_ms // 1000}s",
            why=(res.stderr or res.stdout).strip()[:300] or f"nothing matched {regex!r}",
            fix=f"look at what pane {pane_id} shows; if it is a prompt, set `shell_prompt_regex` "
            "in .fleet.toml to match it",
        )

    def agent_start(self, name: str, kind: str, pane: str, args: list[str]) -> None:
        self._run.run(
            ["herdr", "agent", "start", name, "--kind", kind, "--pane", pane, "--", *args]
        )

    def agent_list(self) -> list[dict]:
        return self._json(["agent", "list"]).get("agents", [])

    def agent_status(self, name: str) -> str:
        agent = self._json(["agent", "get", name]).get("agent", {})
        return str(agent.get("agent_status", "unknown")) if isinstance(agent, dict) else "unknown"

    def agent_prompt(self, name: str, text: str, wait: bool, timeout_ms: int) -> None:
        argv = ["herdr", "agent", "prompt", name, text]
        if wait:
            argv += ["--wait", "--timeout", str(timeout_ms)]
        self._run.run(argv, timeout_s=timeout_ms / 1000 + 30 if wait else None)

    def agent_read(self, name: str, lines: int, source: str = "recent-unwrapped") -> str:
        res = self._run.run(
            ["herdr", "agent", "read", name, "--source", source, "--lines", str(lines)],
            check=False,
        )
        return res.stdout if res.ok else ""
