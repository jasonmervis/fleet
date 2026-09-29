"""Orchestrator state in `.fleet/state.json`, and the lock that serialises spawn/teardown."""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path

from fleet.errors import FleetError

STATE_DIR = ".fleet"
STATE_FILE = "state.json"
LOCK_FILE = "lock"
LOCK_STALE_S = 600
SCHEMA_VERSION = 1


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Worker:
    name: str
    branch: str
    base: str
    base_sha: str
    agent: str
    model: str
    worktree: str
    tab_id: str
    pane_id: str
    started_at: str
    issue: int | None = None
    supervised: bool = True
    status: str = "running"
    last_settled: str = ""


@dataclass(frozen=True)
class Preflight:
    base: str
    base_sha: str
    at: str


@dataclass(frozen=True)
class FleetState:
    workers: tuple[Worker, ...] = ()
    preflight: Preflight | None = None
    version: int = SCHEMA_VERSION

    def get(self, name: str) -> Worker | None:
        return next((w for w in self.workers if w.name == name), None)

    def with_worker(self, worker: Worker) -> FleetState:
        others = tuple(w for w in self.workers if w.name != worker.name)
        return replace(self, workers=(*others, worker))

    def without_worker(self, name: str) -> FleetState:
        return replace(self, workers=tuple(w for w in self.workers if w.name != name))

    def updated(self, name: str, **changes: object) -> FleetState:
        worker = self.get(name)
        if worker is None:
            return self
        return self.with_worker(replace(worker, **changes))

    def with_preflight(self, preflight: Preflight) -> FleetState:
        return replace(self, preflight=preflight)


@dataclass(frozen=True)
class StateStore:
    root: Path
    _dir: Path = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_dir", self.root / STATE_DIR)

    @property
    def dir(self) -> Path:
        return self._dir

    def load(self) -> FleetState:
        path = self._dir / STATE_FILE
        if not path.is_file():
            return FleetState()
        try:
            raw = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise FleetError(
                f"corrupt state file: {path}",
                why=str(exc),
                fix="inspect it; `fleet status` rebuilds nothing, so fix or delete it by hand",
            ) from exc
        pre = raw.get("preflight")
        return FleetState(
            workers=tuple(Worker(**w) for w in raw.get("workers", [])),
            preflight=Preflight(**pre) if pre else None,
            version=raw.get("version", SCHEMA_VERSION),
        )

    def save(self, state: FleetState) -> None:
        self._dir.mkdir(exist_ok=True)
        path = self._dir / STATE_FILE
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(state), indent=2) + "\n")
        os.replace(tmp, path)

    @contextlib.contextmanager
    def lock(self, command: str) -> Iterator[None]:
        """Exclusive lock. A lock older than LOCK_STALE_S, or whose pid is dead, is taken over."""
        self._dir.mkdir(exist_ok=True)
        path = self._dir / LOCK_FILE
        for _ in range(2):
            try:
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                holder = _read_lock(path)
                if _is_stale(holder):
                    path.unlink(missing_ok=True)
                    continue
                raise FleetError(
                    f"locked by pid {holder.get('pid', '?')} ({holder.get('command', '?')})",
                    why="another fleet command is spawning or tearing down",
                    fix=f"wait for it, or delete {path} if that process is gone",
                ) from None
            with os.fdopen(fd, "w") as fh:
                json.dump({"pid": os.getpid(), "command": command, "at": time.time()}, fh)
            break
        try:
            yield
        finally:
            path.unlink(missing_ok=True)


def _read_lock(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _is_stale(holder: dict) -> bool:
    if time.time() - float(holder.get("at", 0)) > LOCK_STALE_S:
        return True
    pid = holder.get("pid")
    if not isinstance(pid, int):
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False
