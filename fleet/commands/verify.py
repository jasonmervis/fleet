"""`fleet verify` — trial-merge the batch onto base, run the tests on the combined tree (§8.1)."""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from fleet.context import Context
from fleet.errors import FleetError, UsageError
from fleet.forges import select_forge
from fleet.state import STATE_DIR, Worker, now_iso

TEST_TIMEOUT_S = 3600


@dataclass(frozen=True)
class Evidence:
    batch: str
    base: str
    base_sha: str
    workers: list[dict]
    conflict: str = ""
    test_command: str = ""
    test_exit: int | None = None
    test_seconds: float = 0.0
    test_tail: list[str] = field(default_factory=list)
    verified_at: str = ""

    @property
    def passed(self) -> bool:
        return not self.conflict and self.test_exit == 0

    def markdown(self) -> str:
        verdict = "PASSED" if self.passed else "FAILED"
        rows = "\n".join(
            f"| `{w['name']}` | `{w['branch']}` | `{w['head'][:10]}` |" for w in self.workers
        )
        test = (
            f"`{self.test_command}` exited **{self.test_exit}** in {self.test_seconds:.0f}s"
            if self.test_exit is not None
            else "not run"
        )
        conflict = f"\n**Merge conflict:** `{self.conflict}`\n" if self.conflict else ""
        return (
            f"## fleet verify — {verdict}\n\n"
            f"Batch `{self.batch}`, trial-merged onto `{self.base}` @ `{self.base_sha[:10]}` "
            f"at {self.verified_at}.\n{conflict}\n"
            f"| worker | branch | head |\n|---|---|---|\n{rows}\n\n"
            f"Tests on the combined tree: {test}.\n"
        )


def _select(ctx: Context, names: list[str]) -> list[Worker]:
    state = ctx.store.load()
    if not names:
        if not state.workers:
            raise UsageError("no workers to verify", fix="spawn some, or name branches explicitly")
        return list(state.workers)
    missing = [n for n in names if state.get(n) is None]
    if missing:
        raise UsageError(f"unknown worker(s): {', '.join(missing)}", fix="see `fleet status`")
    return [state.get(n) for n in names]  # type: ignore[misc]


def trial_merge(ctx: Context, workers: list[Worker], batch: str) -> Evidence:
    cfg, git = ctx.config, ctx.git_read
    base_sha = git.rev(cfg.base)
    heads = [{"name": w.name, "branch": w.branch, "head": git.rev(w.branch)} for w in workers]
    evidence = Evidence(batch=batch, base=cfg.base, base_sha=base_sha, workers=heads)
    tmp = ctx.root / STATE_DIR / "verify" / batch
    tmp.parent.mkdir(parents=True, exist_ok=True)
    ctx.reader.run(["git", "worktree", "add", "--detach", str(tmp), base_sha], cwd=ctx.root)
    try:
        for w in workers:
            res = ctx.reader.run(
                [
                    "git",
                    "-c",
                    "user.name=fleet",
                    "-c",
                    "user.email=fleet@localhost",
                    "merge",
                    "--no-ff",
                    "--no-edit",
                    w.branch,
                ],
                cwd=tmp,
                check=False,
            )
            if not res.ok:
                ctx.reader.run(["git", "merge", "--abort"], cwd=tmp, check=False)
                return _finish(evidence, conflict=w.branch)
        if cfg.install and cfg.install != ":":
            inst = ctx.reader.shell(cfg.install, cwd=tmp, timeout_s=cfg.install_timeout_ms / 1000)
            if not inst.ok:
                return _finish(
                    evidence,
                    test_command=cfg.install,
                    test_exit=inst.returncode,
                    test_tail=_tail(inst.stdout + inst.stderr),
                )
        started = time.monotonic()
        res = ctx.reader.shell(cfg.test, cwd=tmp, timeout_s=TEST_TIMEOUT_S)
        return _finish(
            evidence,
            test_command=cfg.test,
            test_exit=res.returncode,
            test_seconds=time.monotonic() - started,
            test_tail=_tail(res.stdout + res.stderr),
        )
    finally:
        ctx.reader.run(
            ["git", "worktree", "remove", "--force", str(tmp)], cwd=ctx.root, check=False
        )


def _tail(text: str) -> list[str]:
    return text.strip().splitlines()[-20:]


def _finish(evidence: Evidence, **changes: object) -> Evidence:
    return Evidence(**{**asdict(evidence), **changes, "verified_at": now_iso()})


def write_evidence(ctx: Context, evidence: Evidence) -> Path:
    out = ctx.root / STATE_DIR / "evidence"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{evidence.batch}.json").write_text(
        json.dumps({**asdict(evidence), "passed": evidence.passed}, indent=2) + "\n"
    )
    md = out / f"{evidence.batch}.md"
    md.write_text(evidence.markdown())
    return md


def _dry_run(ctx: Context, workers: list[Worker], batch: str) -> int:
    tmp = ctx.root / STATE_DIR / "verify" / batch
    ctx.actor.run(["git", "worktree", "add", "--detach", str(tmp), ctx.config.base])
    for w in workers:
        ctx.actor.run(["git", "-C", str(tmp), "merge", "--no-ff", "--no-edit", w.branch])
    ctx.actor.shell(ctx.config.test or "<test unset>", cwd=tmp)
    ctx.actor.run(["git", "worktree", "remove", "--force", str(tmp)])
    return 0


def run(ctx: Context, args: argparse.Namespace) -> int:
    workers = _select(ctx, args.names)
    batch = args.batch or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if ctx.is_dry:
        return _dry_run(ctx, workers, batch)
    if not ctx.config.test:
        raise UsageError("`test` is unset", fix='set `test = "..."` in .fleet.toml')
    for w in workers:
        dirty = ctx.git_read.dirty_files(Path(w.worktree)) if Path(w.worktree).is_dir() else []
        if dirty:
            ctx.warn(
                f"{w.name} has uncommitted changes that verify cannot see: {', '.join(dirty[:5])}"
            )

    evidence = trial_merge(ctx, workers, batch)
    md = write_evidence(ctx, evidence)
    ctx.say(evidence.markdown())
    ctx.say(f"evidence: {md}")
    if not evidence.passed:
        if evidence.conflict:
            raise FleetError(
                f"merge conflict on {evidence.conflict}",
                why="the batch is not file-disjoint; it may pass alone and still break together",
                fix=f"send {evidence.conflict} back to rebase on the others, or serialise them",
            )
        raise FleetError(
            f"tests failed on the combined tree (exit {evidence.test_exit})",
            fix="bisect by verifying subsets: `fleet verify <name> …`",
        )

    store = ctx.store
    state = store.load()
    for w in workers:
        state = state.updated(w.name, status="verified")
    store.save(state)
    if args.mark_ready:
        forge = select_forge(ctx.config.forge, ctx.root, ctx.reader, ctx.actor)
        for w in workers:
            ctx.say(f"ready: {w.name} → {forge.mark_ready(w.branch, evidence.markdown())}")
    return 0
