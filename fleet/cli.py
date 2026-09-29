"""`fleet` command-line entry point."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from fleet import __version__
from fleet.commands import (
    brief,
    config_cmd,
    doctor,
    init,
    logs,
    preflight,
    spawn,
    status,
    teardown,
    up,
    verify,
)
from fleet.config import PERMISSION_MODES
from fleet.context import Context, build_context
from fleet.errors import FleetError


class _Formatter(argparse.HelpFormatter):
    def add_usage(self, usage, actions, groups, prefix=None):
        # argparse passes prefix="" when computing a subcommand's prog; keep that intact.
        super().add_usage(usage, actions, groups, "Usage: " if prefix is None else prefix)


def _sub(
    subs, name: str, fn: Callable[[Context, argparse.Namespace], int], help_: str, dry: bool = True
) -> argparse.ArgumentParser:
    p = subs.add_parser(name, help=help_, description=help_, formatter_class=_Formatter)
    p.set_defaults(fn=fn, dry_run=False)
    if dry:
        p.add_argument("--dry-run", action="store_true", help="print commands; change nothing")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fleet",
        formatter_class=_Formatter,
        description="Parallel coding agents on in-repo worktrees.",
    )
    parser.add_argument("--version", action="version", version=f"fleet {__version__}")
    subs = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    _sub(subs, "config", config_cmd.run, "print resolved settings and their sources", dry=False)
    _sub(subs, "preflight", preflight.run, "check everything a spawn relies on", dry=False)

    p = _sub(subs, "spawn", spawn.run, "create one worker: worktree + tab + agent")
    p.add_argument("--name", required=True, help="worker name: [a-z][a-z0-9_-]{0,31}")
    p.add_argument("--branch", required=True, help="branch to create for the worktree")
    p.add_argument("--base", help="ref to branch from (default: config `base`)")
    p.add_argument("--agent", help="agent kind (default: config `agent`)")
    p.add_argument("--model", help="model for the agent (default: config `model`)")
    p.add_argument("--permission-mode", choices=PERMISSION_MODES)
    p.add_argument("--issue", type=int, help="issue number this worker owns")
    p.add_argument(
        "--allowlist",
        nargs="*",
        metavar="TOOL",
        help="replace config `allowlist` for this worker; no values = none (needed for codex)",
    )
    p.add_argument(
        "--allow-unsupervised",
        action="store_true",
        help="spawn even without a lifecycle integration",
    )

    p = _sub(subs, "brief", brief.run, "send a worker its brief")
    p.add_argument("name")
    p.add_argument("--file", required=True, help="markdown brief (playbook §6)")
    p.add_argument("--no-wait", action="store_true", help="return without waiting to settle")
    p.add_argument("--timeout-ms", type=int, default=brief.DEFAULT_TIMEOUT_MS)

    p = _sub(subs, "up", up.run, "spawn and brief every worker in a split file")
    p.add_argument("split", help="split.toml with [[worker]] entries")
    p.add_argument(
        "--allow-unsupervised",
        action="store_true",
        help="every worker; prefer per-worker `allow_unsupervised = true` in the split",
    )

    p = _sub(subs, "status", status.run, "show every worker and its state")
    p.add_argument("--workspace", help="herdr workspace (default: $HERDR_WORKSPACE_ID)")
    p.add_argument("--blocked", action="store_true", help="only blocked workers, with screen text")
    p.add_argument("--json", action="store_true")

    p = _sub(subs, "logs", logs.run, "save a worker's transcript to .fleet/logs/")
    p.add_argument("name")
    p.add_argument("--lines", type=int, default=logs.DEFAULT_LINES)

    p = _sub(subs, "verify", verify.run, "trial-merge workers onto base and run the tests")
    p.add_argument("names", nargs="*", help="workers to verify (default: all)")
    p.add_argument("--batch", help="evidence id (default: UTC timestamp)")
    p.add_argument(
        "--mark-ready",
        action="store_true",
        help="on success, mark PRs ready and post evidence (github forge)",
    )

    p = _sub(subs, "teardown", teardown.run, "remove workers; branches are kept")
    p.add_argument("--name")
    p.add_argument("--all", action="store_true")
    p.add_argument("--overrun", action="store_true", help="workers past `max_minutes`")
    p.add_argument("--tab", help="tab id to close (default: from state, else by label)")
    p.add_argument("--force", action="store_true", help="discard uncommitted/unpushed work")

    _sub(subs, "init", init.run, "adopt fleet in this repo (idempotent)")
    _sub(subs, "doctor", doctor.run, "check CLI, skill and herdr versions agree", dry=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ctx = build_context(dry_run=args.dry_run)
        return args.fn(ctx, args)
    except FleetError as exc:
        sys.stdout.flush()  # keep command output ahead of the error when both go to a terminal
        print(exc.render(), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
