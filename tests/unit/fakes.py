"""An in-memory Runner: scripted responses keyed by argv prefix, every call recorded."""

from __future__ import annotations

from pathlib import Path

from fleet.proc import Result


class FakeRunner:
    is_dry = False

    def __init__(self, responses: dict[tuple[str, ...], Result] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def run(self, argv, cwd: Path | None = None, check: bool = True, timeout_s=None) -> Result:
        self.calls.append(list(argv))
        for prefix in sorted(self.responses, key=len, reverse=True):
            if tuple(argv[: len(prefix)]) == prefix:
                return self.responses[prefix]
        return Result(1, "", "unscripted")

    def shell(self, command: str, cwd: Path, timeout_s=None) -> Result:
        self.calls.append(["sh", "-c", command])
        return self.responses.get(("sh", command), Result(0, "", ""))


def ok(stdout: str = "") -> Result:
    return Result(0, stdout, "")


def fail(stderr: str = "") -> Result:
    return Result(1, "", stderr)
