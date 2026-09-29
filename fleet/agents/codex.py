"""OpenAI Codex CLI. Flags from its documentation; not yet verified against a local install."""

from __future__ import annotations

from dataclasses import dataclass

from fleet.errors import UsageError

# fleet permission mode -> (sandbox, approval policy). danger-full-access is deliberately absent.
_MODES = {
    "auto": ("workspace-write", "never"),
    "edits": ("workspace-write", "on-request"),
    "readonly": ("read-only", "on-request"),
}


@dataclass(frozen=True)
class CodexAdapter:
    kind: str = "codex"

    def launch_args(
        self, model: str, permission_mode: str, allowlist: tuple[str, ...]
    ) -> list[str]:
        if allowlist:
            raise UsageError(
                "codex: tool allowlist is not supported",
                why="codex has no per-tool allowlist; `allowlist` would be silently ignored",
                fix="remove `allowlist` for this worker, or use --agent claude",
            )
        sandbox, approval = _MODES[permission_mode]
        args = ["--sandbox", sandbox, "--ask-for-approval", approval]
        if model:
            args += ["--model", model]
        return args
