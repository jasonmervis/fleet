"""Command execution behind one seam, so commands can be dry-run and tests can fake it."""

from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from fleet.errors import FleetError


@dataclass(frozen=True)
class Result:
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class Runner(Protocol):
    is_dry: bool

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        timeout_s: float | None = None,
    ) -> Result: ...

    def shell(self, command: str, cwd: Path, timeout_s: float | None = None) -> Result: ...


class SubprocessRunner:
    """Runs commands for real."""

    is_dry = False

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        timeout_s: float | None = None,
    ) -> Result:
        try:
            proc = subprocess.run(
                argv, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, check=False
            )
        except FileNotFoundError as exc:
            raise FleetError(
                f"missing dependency: {argv[0]}",
                why=f"`{argv[0]}` is not on PATH",
                fix=f"install {argv[0]} and retry",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise FleetError(
                f"timed out after {timeout_s:.0f}s: {shlex.join(argv)}",
                fix="raise the timeout in .fleet.toml or investigate the hang",
            ) from exc
        result = Result(proc.returncode, proc.stdout, proc.stderr)
        if check and not result.ok:
            raise FleetError(
                f"command failed ({result.returncode}): {shlex.join(argv)}",
                why=(result.stderr or result.stdout).strip()[:500],
            )
        return result

    def shell(self, command: str, cwd: Path, timeout_s: float | None = None) -> Result:
        # `command` comes from the repo's own committed config (install/test), never from input.
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise FleetError(f"timed out after {timeout_s:.0f}s: {command}") from exc
        return Result(proc.returncode, proc.stdout, proc.stderr)


class DryRunner:
    """Prints what would run. Executes nothing."""

    is_dry = True

    def __init__(self, out=None) -> None:
        self._out = out or sys.stdout

    def run(
        self,
        argv: list[str],
        cwd: Path | None = None,
        check: bool = True,
        timeout_s: float | None = None,
    ) -> Result:
        print(shlex.join(argv), file=self._out)
        return Result(0, "", "")

    def shell(self, command: str, cwd: Path, timeout_s: float | None = None) -> Result:
        print(command, file=self._out)
        return Result(0, "", "")
