# Spec: fleet CLI

---
spec_type: system
status: draft
created: 2026-09-17
updated: 2026-09-23
author: Jason Mervis
---

## Purpose

The `fleet` skill's playbook (`.claude/skills/fleet/ORCHESTRATION.md`) describes a parallel-agent
workflow that the old `sh` scripts only partly implemented: config, gates, state and supervision
lived in prose and relied on the orchestrator's diligence. `fleet` makes them one CLI whose exit
codes enforce the playbook, so Synthesis repos can adopt it, run it unattended and upgrade it.

## Scope

**In scope**
- One Python 3.11+ CLI, stdlib only at runtime: `fleet config | preflight | spawn | brief | up |
  status | logs | verify | teardown | init | doctor | skill install`.
- The skill is machine-level: one stamped copy in the user's Claude config dir, owned by the CLI.
- Config resolution: detection (playbook §1.2) overridden by `.fleet.toml`.
- Orchestrator state in `.fleet/state.json`; transactional spawn; a spawn/teardown lock.
- Agent adapters: `claude`, `codex`. Forges: `github` (via `gh`), `local` (branches, no PRs).
- Herdr ≥ 0.9.0 as the only terminal backend.
- Installer and version check for adopting repos.

**Out of scope**
- Other terminal backends (tmux, zellij), other forges (GitLab, Bitbucket).
- Agent adapters beyond `claude` and `codex`.
- Merging. `fleet` promotes verified work; a human merges (playbook §8.3 stays manual).
- Windows outside WSL.

## Functional Requirements

### Common contract (every subcommand)
- **Must**: `--help` prints usage containing `Usage:` (argparse prints `usage:`; `fleet` prints `Usage:`) to stdout, exit `0`.
- **Must**: a missing or invalid argument exits `2`, naming the option on stderr.
- **Must**: a runtime failure exits `1` with stderr lines `error: <what>`, `  why: <why>`, `  fix: <fix>`.
- **Must**: `--dry-run` (where offered) prints each command that would run, one per line, executes
  nothing, needs no Herdr, and exits `0`.
- **Must Not**: print secrets from the environment or config.

### Config
- **Must**: resolve `base` from `gh` default branch → `origin/HEAD` → current branch, and flag the
  last source as needing confirmation.
- **Must**: resolve `install`/`test` from the playbook §1.2 lockfile table; no marker → `test` unset.
- **Must**: let every key in `.fleet.toml` override detection; unknown keys exit `2`.
- **Must**: `fleet config` print every resolved value with its source.

### Preflight
- **Must**: check, and report every failure (not just the first): inside Herdr, git repo with ≥1
  commit, clean tree, Herdr ≥ 0.9.0, lifecycle integration current for the configured agent,
  `test` set, `test` passes on the current base commit.
- **Must**: on success record the base sha and time in state; on failure exit `1`.

### Spawn
- **Must**: create worktree `.worktrees/<name>` on `<branch>` from base, run `install` in it, create a
  Herdr tab, start the agent — and on any step's failure undo every completed step.
- **Must**: wait for the new tab's shell prompt (`shell_prompt_regex`, 15 s) before starting the
  agent; retry a pane herdr reports busy up to 3 times; a step that gives up names the pane.
- **Must**: take agent, model, permission mode and allowlist from flags, else config.
- **Must**: refuse an agent with no fleet adapter, and an agent with no lifecycle integration unless
  `--allow-unsupervised`.
- **Must**: refuse permission mode `auto` unless a preflight for the current base sha is recorded.
- **Must**: refuse beyond `max_workers` live workers, and when another fleet command holds the lock.
- **Should**: when forge is `github` and `--issue` is given, label the issue `fleet-wip` and comment.

### Brief / up
- **Must**: `brief` send the brief file plus the forge's delivery rules and the worker scope rules,
  and by default wait for a settled state and record it.
- **Must**: `up <split.toml>` spawn every listed worker, then brief each without waiting.

### Status / logs
- **Must**: show per worker: name, agent/model, branch, issue, state, elapsed, diff vs base.
- **Must**: mark workers `gone` (in state, no agent), `untracked` (agent under `.worktrees/`, not in
  state), `unsupervised`, and `overrun` (elapsed > `max_minutes`).
- **Must**: `--blocked` include each blocked worker's recent screen text; `--json` emit JSON.
- **Must**: `logs <name>` write the transcript to `.fleet/logs/<name>.log`.

### Verify
- **Must**: merge every selected worker branch onto base in a throwaway worktree, run `test` there,
  write `.fleet/evidence/<batch>.json` and `.md` (base sha, head shas, exit code, duration).
- **Must**: exit `1` naming the branch on the first merge conflict, or on a test failure.
- **Should**: with `--mark-ready` on forge `github`, mark each worker's draft PR ready and post the
  evidence as a comment — only when verification passed.

### Teardown
- **Must**: save the transcript, close the tab, remove the worktree, drop the state entry, prune.
- **Must**: refuse a worktree with uncommitted changes, listing them, unless `--force`.
- **Must**: refuse when forge is `github` and the branch has commits not on its upstream, unless `--force`.
- **Must Not**: delete the branch.
- **Should**: support `--all` and `--overrun`.

### Skill install
The skill is generic (nothing repo-specific may live in it), so it lives once per machine, next to
the CLI that owns it, rather than once per repo. `SKILL_DIR` = `$CLAUDE_CONFIG_DIR/skills/fleet`,
defaulting to `~/.claude/skills/fleet`.
- **Must**: `skill install` copy the bundled skill to `SKILL_DIR`, stamp `fleet_version` with the
  CLI version, and print each file written. Idempotent: a second run changes nothing and says so.
- **Must**: when `SKILL_DIR` is a symlink, write nothing. Exit `0` if it resolves to the bundled
  skill directory (a source checkout in development); otherwise exit `1` naming the target, with
  `fix:` remove the symlink to install a managed copy.
- **Must**: `--dry-run` list the files that would be written; `--dest DIR` override `SKILL_DIR`.
- **Must**: the `SKILL.md` description trigger in any repo that has a `.fleet.toml`, not "this repo".
- **Must Not**: write anywhere else under the config dir, or touch `settings.json`.

### Init / doctor
- **Must**: `init` idempotently add `.worktrees/` and `.fleet/` to `.gitignore`, install the
  post-checkout provisioning hook, write `.fleet.toml` from detection if absent, and create forge
  labels when forge is github.
- **Must**: `init` not copy the skill into the repo. When `SKILL_DIR` has no stamped skill, its
  `next:` line says to run `fleet skill install`.
- **Should**: `init` and `doctor` warn when a legacy copy exists at `.claude/skills/fleet/` in the
  repo — two skills with one name — with `fix:` delete it.
- **Must**: `doctor` exit `1` when `SKILL_DIR` has no stamped skill, when the installed CLI version
  differs from its stamp, or Herdr is below the minimum. A symlinked `SKILL_DIR` is reported as such
  and its resolved `SKILL.md` stamp is what is compared.

## Non-Functional Requirements

- Python ≥ 3.11, zero runtime dependencies. Dev: `uv`, `pytest`, `ruff`.
- State writes atomic (temp file + `os.replace`); config and state objects immutable.
- Test coverage ≥ 80%; Herdr is replaced in tests by a fake executable on `PATH`.
- A worker name matches `^[a-z][a-z0-9_-]{0,31}$` everywhere it is accepted.
- Security posture documented in `SECURITY.md`; `bypassPermissions`-equivalent modes are not offered.

## Acceptance Criteria

- Given fake Herdr failing `tab create`, when `fleet spawn` runs, then no worktree, branch or state
  entry remains and stderr names the failed step.
- Given two concurrent `fleet spawn` calls, when both run, then one exits `1` naming the lock holder.
- Given `.fleet.toml` with `base = "develop"`, when `fleet spawn --dry-run` runs, then the worktree
  command ends in `develop`.
- Given `test` is unset, when `fleet preflight` runs, then it exits `1` telling the user to set `test`.
- Given two branches that pass alone but conflict together, when `fleet verify` runs, then it exits
  `1` naming the conflicting branch.
- Given `--agent kiro`, when `fleet spawn` runs, then it exits `1` stating kiro has no fleet adapter.
- Given codex without a lifecycle integration, when `fleet spawn --agent codex` runs without
  `--allow-unsupervised`, then it exits `1` telling the user to install the integration.
- Given a worktree with uncommitted changes, when `fleet teardown` runs without `--force`, then it
  exits `1` listing the files.
- Given a stamped skill version older than the CLI, when `fleet doctor` runs, then it exits `1`
  naming both versions.
- Given an empty `CLAUDE_CONFIG_DIR`, when `fleet skill install` runs twice, then the first run
  lists `SKILL.md` and `ORCHESTRATION.md` as written and stamped, and the second writes nothing.
- Given `SKILL_DIR` is a symlink to an unrelated directory, when `fleet skill install` runs, then it
  exits `1` naming the target and writes nothing.
- Given a fresh repo and an installed skill, when `fleet init` runs, then `.claude/skills/fleet/`
  is not created and `fleet doctor` exits `0`.
- Given a legacy repo copy at `.claude/skills/fleet/`, when `fleet doctor` runs, then it warns and
  names the path to delete.

## Open Questions

- [ ] **Upgrade path for the hackathon repo and this one**, which carry a repo-level skill copy:
  delete on first `fleet init` after upgrade, or warn only? Spec says warn — Owner: Jason.
- [ ] **Split-check hook** (`UserPromptSubmit` in user settings): separate feature; `skill install`
  must not write hooks. Spec when the skill is machine-level and has run live — Owner: Jason.

- [ ] GitHub remote for this repo (CI, live `github` forge test) — Owner: Jason, Target: before merge.
- [ ] Codex CLI flags (`--sandbox`, `--ask-for-approval`, `--model`) are from its docs, not verified
  locally — Owner: Jason, Target: when codex is installed.
