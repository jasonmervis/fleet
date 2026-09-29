"""Claude Code. Flags verified against `claude --help` (2.1.x)."""

from __future__ import annotations

from dataclasses import dataclass

# fleet permission mode -> Claude --permission-mode. bypassPermissions is deliberately absent.
_MODES = {"auto": "auto", "edits": "acceptEdits", "readonly": "plan"}


@dataclass(frozen=True)
class ClaudeAdapter:
    kind: str = "claude"

    def launch_args(
        self, model: str, permission_mode: str, allowlist: tuple[str, ...]
    ) -> list[str]:
        args = ["--permission-mode", _MODES[permission_mode]]
        if model:
            args += ["--model", model]
        if allowlist:
            args += ["--allowedTools", *allowlist]
        return args
