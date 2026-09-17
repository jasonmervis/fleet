# SPEC — fleet scripts

Three POSIX `sh` scripts that wrap the workflow in `ORCHESTRATION.md`. Each is independent and
owns exactly one file under `scripts/`.

## Shared rules (all three)

- POSIX `sh`, executable, shebang `#!/bin/sh`, `set -eu` near the top.
- Source the shared library relative to the script, then use its helpers:
  `. "$(dirname "$0")/lib/common.sh"` — available: `log die need repo_root require_herdr emit`.
- `--help` prints usage to **stdout** containing the literal word `Usage:` and exits `0`.
- A missing or invalid required argument exits `2` with a message on **stderr** naming the
  offending option.
- `--dry-run` prints the commands that would run, one per line, to **stdout**, executes nothing,
  and exits `0`. Dry-run must not require Herdr or touch the filesystem.
- Worktrees live at `<repo>/.worktrees/<name>`; tabs are created in `$HERDR_WORKSPACE_ID`.

## `scripts/spawn.sh` — create a worker

```
Usage: spawn.sh --name <name> --branch <branch> [--base <ref>] [--dry-run] [--help]
```

`--base` defaults to `main`. Dry-run output must contain, in this order, lines beginning:

1. `git worktree add` — including the worktree path and the branch
2. `herdr tab create` — including `--cwd` and `--label`
3. `herdr agent start` — including `--kind claude`

## `scripts/status.sh` — report the fleet

```
Usage: status.sh [--workspace <id>] [--dry-run] [--help]
```

Dry-run output must contain a line beginning `herdr agent list`. Non-dry-run prints one line per
live agent as `<pane_id>  <status>  <cwd>`; no agents is not an error.

## `scripts/teardown.sh` — remove a worker

```
Usage: teardown.sh --name <name> [--tab <tab_id>] [--force] [--dry-run] [--help]
```

Dry-run output must contain lines beginning `herdr tab close` and `git worktree remove`; with
`--force`, the `git worktree remove` line must include `--force`.

## Testing

`sh tests/run-all.sh` runs every `tests/*.test.sh`. Each prints `PASS <name>` or `FAIL <name>`
and exits non-zero on failure.
