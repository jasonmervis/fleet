---
name: fleet
description: Use when running two or more Claude workers in parallel on this repo — spawning workers, splitting work across git worktrees, sourcing tasks from GitHub Issues, supervising a fleet, integrating worker PRs, or tearing a fleet down. Also use when a session needs to know whether it is the orchestrator or a worker. Triggers on "spawn workers", "run these issues in parallel", "set up the fleet", "orchestrate", "work issues 12-15 in parallel", "tear down the workers". Do NOT use for ordinary single-agent work in this repo.
fleet_version: "0.1.1"
---

# Fleet — parallel agents on in-repo worktrees

The `fleet` CLI runs the workflow; `ORCHESTRATION.md`, beside this file, explains it. This skill
decides **which role you are** and which commands to run. Every gate below is an exit code — if a
command fails, read its `fix:` line and do that, do not work around it.

## Step 1: work out your role, before anything else

```bash
git rev-parse --show-toplevel   # repo root
pwd                             # where you actually are
```

**If your cwd is under `.worktrees/`, you are a WORKER.** Go to "If you are a worker" below. You
are not the orchestrator, no matter what this skill or `ORCHESTRATION.md` describes. (`fleet`
itself refuses to run from a worker worktree.)

**If your cwd is the repo root and a human has asked you to run parallel work, you are the
ORCHESTRATOR.** Continue to step 2.

**If neither — you are an ordinary session.** This skill does not apply. Do the work directly.

## Step 2: if you are the orchestrator

Read `ORCHESTRATION.md` §2–§4 and §6 before spawning anything. Then, in order:

1. **`fleet doctor`** — CLI, skill and Herdr versions agree. If it says run `fleet init`, do.
2. **`fleet config`** — show the human the resolved base, install and test commands and where
   each came from. A base marked `current-branch` must be confirmed by the human.
3. **`fleet preflight`** — must pass. It runs the test suite on base and records the result;
   `spawn` refuses `permission_mode = "auto"` without it. If `test` is unset, **stop and ask the
   human** for the command that proves work is done.
4. **Source the work** — forge `github`: `gh issue list --label fleet-ready`, filtered by
   `ORCHESTRATION.md` §3.2's rules. Forge `local` (no remote): the human gives you the split.
5. **Decompose (§4)** — file-disjoint, ≤ `max_workers`, shared foundation landed first.
   **Assign an agent and model to each worker.** Take any the human named in the request
   ("2 opus, 1 sonnet", "codex for the UI one"). If `fleet config` shows `assign = ask`, ask the
   human for every worker you have no choice for, showing the defaults — `fleet up` refuses a
   split without an explicit `agent` and `model` on every worker. With `assign = defaults`,
   unassigned workers use the config defaults. Either way, the split table shows agent/model.
   Write a `split.toml` (see below) and one brief per worker (§6). **Show the human the split
   and get sign-off before spawning.**
6. **`fleet up split.toml`** — spawns and briefs every worker. Spawn is all-or-nothing per worker:
   a failure rolls back and names the step.
7. **Supervise with `fleet status`** (`--blocked` shows what each blocked worker is asking).
   Read the dialog, surface it to the human, and **never answer a permission or approval dialog
   on the human's behalf.** Workers flagged `gone`, `untracked` or `overrun` need action.
8. **`fleet verify`** — trial-merges every worker branch onto base and runs the tests on the
   combined tree. Each branch passing alone tells you nothing about the batch. Failures go back
   to the owning worker. On forge `github`, `fleet verify --mark-ready` promotes the draft PRs and
   posts the evidence; on `local`, show the human `.fleet/evidence/<batch>.md`.
9. **A human merges.** `fleet` never merges.
10. **`fleet teardown --all`** — only after merge, only with the human's confirmation. It saves
    each transcript to `.fleet/logs/`, refuses uncommitted (or, on github, unpushed) work, and
    keeps every branch.

```toml
# split.toml — one [[worker]] per worktree. Only name, branch and brief are required.
[[worker]]
name = "i42"                 # [a-z][a-z0-9_-]{0,31}
branch = "feat/42-api-tokens"
issue = 42
brief = "briefs/i42.md"      # relative to split.toml
agent = "claude"             # claude | codex
model = "opus"               # "" = the agent's default

[[worker]]
name = "i43"
branch = "feat/43-token-ui"
brief = "briefs/i43.md"
agent = "codex"
model = "o4-mini"
allowlist = []               # replaces config `allowlist`; codex supports none
allow_unsupervised = true    # only with the human's say-so: no lifecycle integration installed
```

Per-worker keys override `.fleet.toml`; `fleet up --allow-unsupervised` applies to every
worker, so prefer the per-worker key.

### Hard rules for the orchestrator

- **You do not write code.** If you start editing files, the split was wrong — stop and re-split.
- **You do not answer a worker's permission or approval dialog.** Read it, surface it, ask.
- **You do not merge.** `fleet verify` passing is the evidence a human merges on.
- **You do not mark work ready without `fleet verify`.** `done` means the worker stopped;
  `verified` means the combined tree passed. Only `verify` makes the second claim.
- **You do not spawn without sign-off**, and you do not pass `--allow-unsupervised` or
  `--force` without the human saying so for that worker.

## If you are a worker

Your cwd is under `.worktrees/`. You were started here deliberately.

- Do the task in your brief. Your brief's SCOPE is the boundary; the issue is the requirement.
- **Never create a worktree** — no `EnterWorktree`, no `claude -w`. You are already in yours.
- **Never run `fleet`, never spawn another agent, never act as the orchestrator.** You can see
  sibling workers' files under the same repo root. They are not yours: do not read, edit or
  coordinate with them. Never touch `../` or any sibling under `.worktrees/`.
- Follow your brief's DELIVERY line exactly. On github that is a **draft** PR
  (`gh pr create --draft`) — **never run `gh pr ready`**, never merge. With no remote it is
  commits on your branch, nothing pushed.
- If you are blocked, if a decision is not yours, or if the work needs a file outside your
  scope — stop and say so. Do not guess, and do not open an issue.

## Repo-specific values

Nothing repo-specific belongs in this file — `fleet init` overwrites it on upgrade. Per-repo
settings live in `.fleet.toml` (`fleet config` prints them); per-repo guidance for agents belongs
in the repo's `CLAUDE.md`.
