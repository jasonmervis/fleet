"""Errors that carry what went wrong, why, and how to fix it."""

from __future__ import annotations


class FleetError(Exception):
    """A runtime failure the user can act on. Exit code 1."""

    exit_code = 1

    def __init__(self, what: str, why: str = "", fix: str = "") -> None:
        super().__init__(what)
        self.what = what
        self.why = why
        self.fix = fix

    def render(self) -> str:
        lines = [f"error: {self.what}"]
        if self.why:
            lines.append(f"  why: {self.why}")
        if self.fix:
            lines.append(f"  fix: {self.fix}")
        return "\n".join(lines)


class UsageError(FleetError):
    """A missing or invalid argument or config key. Exit code 2."""

    exit_code = 2
