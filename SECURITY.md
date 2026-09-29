# Security model

`fleet` launches several coding agents that act without a human approving each step. This file
states what that exposes, what `fleet` enforces, and what it does not.

## What a worker can do

Each worker is an agent process in its own Herdr tab, started from the orchestrator's shell. It
**inherits the orchestrator's environment and credentials**:

- **Filesystem** — read/write as your user. The worktree is a working directory, not a sandbox:
  nothing stops a worker reading `../`, sibling worktrees, or your home directory except the
  agent's own permission system and the brief's SCOPE rules.
- **Git and GitHub** — the same `gh` auth and SSH keys as you. A worker that can run `gh` can
  push any branch and, where you are allowed to, merge.
- **Network and secrets** — any env var in your shell, and `.env`/`.env.local`, which the
  provisioning hook copies into every worktree.

`N` workers in `auto` permission mode are `N` unsupervised shells with all of the above.

## What `fleet` enforces

| Control | Where |
|---|---|
| `auto` spawns refused unless `fleet preflight` passed on the current base commit | `spawn` |
| No unrestricted modes: `bypassPermissions` (Claude) and `danger-full-access` (Codex) are not reachable from config or flags | `fleet/agents/` |
| `allowlist` passed to Claude as `--allowedTools`; Codex refuses a non-empty allowlist rather than ignoring it | `fleet/agents/` |
| Agents without a lifecycle integration refused unless `--allow-unsupervised` | `spawn` |
| Worker names restricted to `[a-z][a-z0-9_-]{0,31}` — no path traversal out of `.worktrees/` | everywhere |
| `fleet` refuses to run from inside a worker worktree | every command |
| Briefs always end with scope rules and a delivery line forbidding merge and `gh pr ready` | `brief`, `up` |
| Nothing is merged by `fleet`; PRs are only promoted after `verify` passes, and only with `--mark-ready` | `verify` |
| Teardown refuses uncommitted work (and unpushed work on github); branches are never deleted | `teardown` |

## What it does not enforce

- **Scope is advisory.** The brief tells a worker to stay in its worktree; only the agent's own
  permission system can stop it. For untrusted tasks use `permission_mode = "edits"` or a tight
  `allowlist`, and review every PR.
- **Credentials are shared.** For stronger isolation, run the orchestrator's shell with a
  fine-grained GitHub token scoped to the one repo, without admin or merge rights.
- **`install` and `test` are shell commands from `.fleet.toml`** and run with your privileges.
  Review changes to `.fleet.toml` as you would a CI config.
- **Transcripts in `.fleet/logs/` may contain secrets** the agent printed. `.fleet/` is
  gitignored by `fleet init`; keep it that way.

## Reporting

Report vulnerabilities privately to the maintainers (Jason Mervis), not in a public issue.
