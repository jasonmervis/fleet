# Parallel Agents on In-Repo Worktrees (Herdr)

Portable playbook. Copy into any git repo root. No repo-specific values are hardcoded.

**Topology:** one Herdr workspace = one repo. The orchestrator holds tab 1. Each worker gets
its own **tab** in that same workspace, rooted in its own **in-repo git worktree** under
`.worktrees/`, on its own branch, ending in its own PR.

```
workspace "MyRepo"  (w3)
├── t1  orchestrator   cwd <repo>                     ← you
├── t2  api            cwd <repo>/.worktrees/api      branch feat/api-tokens
├── t3  ui             cwd <repo>/.worktrees/ui       branch feat/token-settings
└── t4  docs           cwd <repo>/.worktrees/docs     branch feat/token-docs
```

Switch workers with Herdr's tab keys. Every worker's files are under your repo root, so your
editor and file tree see all of them.

Verified against Herdr 0.9.0 + Claude Code, and **validated end-to-end by a two-worker dry
run**: worktree + tab + agent spawn, parallel briefs, scope adherence, merge, teardown. The only
untested step is `gh pr create` (the dry run used a local remote, not GitHub).

---

## 1. Preconditions

The orchestrator runs this first and stops on any failure:

```bash
test "${HERDR_ENV:-}" = 1 || { echo "not inside Herdr — abort"; exit 1; }
REPO_ROOT=$(git rev-parse --show-toplevel)     # must succeed
git rev-parse HEAD >/dev/null                  # repo must have >=1 commit
git status --porcelain                         # must be empty, or commit/stash first
command -v jq gh >/dev/null && gh auth status  # jq for JSON, gh for PRs
herdr integration status | grep '^claude:'     # must say "current", not "not installed"
```

`herdr integration install claude` fixes the last one. Without it Herdr cannot read worker
lifecycle state and every `--wait` degrades to guessing.

**One-time per repo: accept the workspace trust dialog.** The first Claude agent launched in a
brand-new repo blocks at startup with `agent_not_ready`:

```
Quick safety check: Is this a project you created or one you trust?
❯ No, exit / Yes, I trust this folder
```

Trust is recorded against the **git repo root**, and covers every worktree — including ones
created later. Verified: after accepting once inside one worktree, a brand-new worktree started
`idle` with no prompt. So a human must accept once, before the first spawn; never again for that
repo. **The orchestrator must not answer this dialog on the human's behalf.**

One-time repo setup (§Appendix C explains the excludes):

```bash
grep -qxF '.worktrees/' .gitignore || echo '.worktrees/' >> .gitignore
git config core.hooksPath .githooks             # if using the provisioning hook (Appendix B)
```

---

## 2. Roles

| | Orchestrator | Worker |
|---|---|---|
| Location | tab 1, at `$REPO_ROOT` | its own tab, at `.worktrees/<name>` |
| Branch | stays on the base branch | its own `feat/<slug>` |
| Writes code | **no** | yes, only inside its worktree |
| Knows the whole plan | yes | only its own brief |
| Ends with | merged PRs, clean teardown | one PR, then idle |

The orchestrator does not edit files. If it starts editing, the split was wrong — stop and
re-split.

---

## 2b. Who creates the worktree

Three mechanisms exist. **This playbook uses plain `git worktree add`, driven by the
orchestrator.** Measured differences:

| | `git worktree add` (**used here**) | `claude -w` / `EnterWorktree` | `herdr worktree create` |
|---|---|---|---|
| Location | anywhere — `.worktrees/<name>` | `<repo>/.claude/worktrees/<name>` | `~/.herdr/worktrees/<repo>/<slug>` (outside repo) |
| Branch name | exactly what you pass | auto-prefixed `worktree-<name>` | exactly what you pass |
| Git lock | none | **`locked`** (unlock/`--force` to remove) | none |
| Base ref | explicit `-b <br> <base>` | `worktree.baseRef`; `fresh` = `origin/<default>` | explicit `--base` |
| Unattended spawn | yes | **no — trust dialog first** | yes |
| Herdr surface | none (we add the tab) | none | a whole workspace |

`git worktree add` is the only one that gives in-repo placement, exact branch names, no lock,
and cold unattended spawning at once.

Rejected for this topology:
- **`claude -w`** puts worktrees in `.claude/worktrees/`, a directory Claude Code manages and
  garbage-collects, prefixes your branch, locks the checkout, and refuses to run until a human
  has accepted the workspace trust dialog in that repo:
  `Error creating worktree: Workspace trust not yet accepted.`
- **`herdr worktree create`** puts the checkout *outside* the repo and creates a whole workspace
  per worker, which is the opposite of the one-workspace-many-tabs layout you want.

**Workers must never create a worktree of their own** — no `EnterWorktree`, no `claude -w`.
They are started already inside theirs. This goes in the brief (§5).

---

## 3. Decompose before you spawn

This is the step that decides whether parallelism helps or costs you a day.

1. **File-disjoint.** Two workers must not need to edit the same file. Overlapping tasks are
   not parallel tasks — they are one sequential task.
2. **Shared foundation goes first, alone.** Schema, shared types, migrations, config, a new
   base class: land that on the base branch *before* spawning anyone. Workers branching off a
   missing foundation will each invent their own.
3. **Cap at 3–4 workers.** Beyond that, merge-conflict resolution and supervision cost more
   than the parallelism returns.
4. **Each task must be independently testable.** If a worker cannot run a test to prove it is
   done, it will report done wrongly.
5. **Write the split down and get human sign-off before spawning.** Spawning is cheap;
   unwinding four half-done conflicting branches is not.

**Anti-patterns:** splitting one feature into "frontend worker" + "backend worker" that share a
contract file; a "refactor everything" worker running alongside anyone; two workers that both
touch the dependency manifest.

**Split template** — fill in and show the human before §4:

```
base branch:  main @ <sha>
worker  api      branch feat/api-tokens      owns  src/api/**, tests/api/**
worker  ui       branch feat/token-settings  owns  src/ui/settings/**
worker  docs     branch feat/token-docs      owns  docs/**, README.md
shared, pre-landed: src/types/token.ts  (commit <sha> on main)
```

---

## 4. Spin up one worker

Run per worker, from the orchestrator's tab. Every ID comes from JSON — never predict `w3:t2`.

```bash
NAME=api                                  # [a-z][a-z0-9_-]{0,31}, unique among live agents
BRANCH=feat/api-tokens
BASE=main
DIR="$REPO_ROOT/.worktrees/$NAME"

# 1. in-repo worktree, exact branch, no lock
git -C "$REPO_ROOT" worktree add "$DIR" -b "$BRANCH" "$BASE"

# 2. a tab in THIS workspace, rooted in the worktree
TAB_JSON=$(herdr tab create \
             --workspace "$HERDR_WORKSPACE_ID" \
             --cwd "$DIR" \
             --label "$NAME" \
             --no-focus)

TAB=$(jq -r '.result.tab.tab_id'       <<<"$TAB_JSON")   # e.g. w3:t2
PANE=$(jq -r '.result.root_pane.pane_id' <<<"$TAB_JSON") # e.g. w3:p2
```

`--cwd` starts the tab's root pane **already inside the worktree** — no `cd`, and nothing for
the agent to get wrong. `--no-focus` keeps you in the orchestrator tab.

Install dependencies before the agent starts. A new worktree has tracked files only:

```bash
herdr pane run "$PANE" "npm ci"
herdr pane wait-output "$PANE" --regex 'added [0-9]+ packages|up to date|npm ERR' --timeout 300000
```

(Fast file provisioning — `.env` and friends — is automatic via the hook in Appendix B. Slow
installs stay here; never in the hook.) The pane must be back at its shell prompt or the next
step fails.

```bash
herdr agent start "$NAME" --kind claude --pane "$PANE" -- \
  --permission-mode auto --model opus
```

**`acceptEdits` is not sufficient for an autonomous worker.** Measured in the dry run: it
auto-accepts file writes, but *every Bash command still prompts*, so a worker blocks on its test
run, then its commit, then its push:

```
Bash command:  sh tests/add.test.sh
 This command requires approval  →  agent_status: blocked
```

Use `auto`, which handles these prompts (validated: a blocked worker switched to auto mode ran
to completion unattended). The principled alternative — better for a repo you run this on often —
is a committed allowlist, which keeps approval explicit and reviewable:

```jsonc
// .claude/settings.json
{ "permissions": { "allow": ["Bash(npm test:*)", "Bash(git add:*)",
                             "Bash(git commit:*)", "Bash(git push:*)"] } }
```

Do **not** use `bypassPermissions` unless the human explicitly asks and understands the worktree
is not sandboxed.

`agent start` returns only once Herdr sees the agent ready. `agent_not_ready` means it came up
blocked — read it, clear it, then prompt.

---

## 5. The worker brief

A worker starts with **zero context**: it has not seen the plan, this conversation, or the other
workers. The brief is the entire contract. Six mandatory parts:

```
1. GOAL        One paragraph. What must be true when you are done.
2. SCOPE       Files/dirs you own. Explicit: "Do not edit anything outside <paths>.
               If the task seems to require it, stop and report instead."
               Also: "You are already in a git worktree on branch <branch>, and your
               cwd is its root. Do not create another worktree — no EnterWorktree,
               no `claude -w`. Do not touch ../ or any sibling under .worktrees/."
3. CONTEXT     The shared decisions already made — API shape, types, naming, the base
               commit. Paste them; do not make the worker re-derive them.
4. DONE-WHEN   Concrete acceptance criteria plus the exact command that proves it
               (e.g. `npm test -- tests/api`).
5. DELIVERY    "Commit to <branch>, push, and open a PR with `gh pr create`. Put your
               summary, decisions, and anything you could not do in the PR body."
6. ESCALATE    "If blocked, if a decision is not yours to make, or if the work needs a
               file outside your scope — stop and say so. Do not guess."
```

Submit it:

```bash
herdr agent prompt "$NAME" "$BRIEF" --wait --timeout 1800000
```

> This repo's global standards make every agent look for a spec first. Give workers the spec (or
> the relevant slice) in CONTEXT, or all N will separately stop and ask the human to write one.

**Sibling worktrees are visible to every worker** — they are all under the same repo root. That
is the cost of in-repo placement, and SCOPE is what contains it. Be explicit that `.worktrees/`
is off-limits.

**The PR body is the deliverable, not the terminal.** Scraping a worker's transcript is fragile;
`gh pr view` is not. Design every brief so the answer lands in the PR.

---

## 6. Supervise

`--wait` returns on the first settled state: `idle`, `done`, `blocked`, or an error.

| Result | Meaning | Do |
|---|---|---|
| `done` / `idle` | Ready for input. Not proof of success. | Verify via PR + tests, §7 |
| `blocked` | Herdr sees an approval or question dialog | `agent read`, decide, then `agent send-keys` |
| `unknown` | Agent present, state unclassifiable | Read before concluding anything |
| `agent_blocked` | Was already blocked; **nothing was sent** | Clear the dialog, then re-prompt |
| `agent_prompt_stalled` | No activity within 5s of submit | Read first — the prompt may have landed. Never blind-resend |
| `timeout` | Your timeout expired | Read; the work is probably still running |

```bash
herdr agent list                                               # all workers + states
herdr agent read "$NAME" --source recent-unwrapped --lines 200 # needs idle for deep history
herdr agent wait "$NAME" --until blocked --timeout 600000
herdr agent send-keys "$NAME" esc
herdr tab list --workspace "$HERDR_WORKSPACE_ID"               # who is where
```

**`agent wait` matches the *current* state, not a transition.** After clearing a dialog, a bare
`agent wait` returns `blocked` instantly because that is still the state at call time. To wait
for the worker to move on, name the states you want:

```bash
herdr agent wait "$NAME" --until idle --until done --timeout 300000
```

**Never answer a worker's permission or approval dialog on the human's behalf.** Read it,
surface it, ask. That is the one thing the orchestrator is not allowed to decide.

Ping the human when the fleet needs attention:

```bash
herdr notification show "api needs input" --body "approval dialog in tab $TAB" --sound request
```

---

## 7. Integrate — one PR per worktree

Never merge on a worker's say-so:

```bash
gh pr view "$BRANCH" --json title,body,statusCheckRollup,files
git -C "$DIR" status --porcelain     # must be clean
git -C "$DIR" log --oneline "$BASE".."$BRANCH"
git diff "$BASE...$BRANCH"           # works from the orchestrator tab, any branch
```

Per PR: confirm the diff stays inside that worker's declared scope; run the test command
yourself; read the PR body for what the worker could not do.

**Run the thing, not just its tests.** A worker optimises for the acceptance criteria you gave
it, so a test that only exercises a mocked or `--dry-run` path will pass over a tool that is
broken in real use. Observed on a real run: all three contract tests passed, but `status.sh`
died the moment it was invoked for real, because it passed an option the underlying CLI does not
accept — a path no test covered. Invoke each deliverable the way a user would before you merge,
and send failures back to the worker that owns the file rather than fixing them yourself.

**Merge order:** smallest diff first, most-depended-on first. After each merge, every remaining
worker is stale:

```bash
herdr agent prompt "$NAME" "main moved. Run: git fetch origin && git rebase origin/main.
Resolve conflicts in your own files only. Re-run <test cmd>. Report the result." --wait --timeout 900000
```

**Conflicts are the orchestrator's problem, not a worker's.** A worker resolving a conflict in a
file it does not own will silently undo another worker's work. If two branches conflict outside
one worker's scope, merge one, then hand the rebase back with an explicit instruction about
which side wins.

---

## 8. Teardown

Only after PRs are merged and the human confirms. Per worker:

```bash
herdr tab close "$TAB"                                  # kills the pane and its agent
git -C "$REPO_ROOT" worktree remove "$DIR"              # add --force if dirty
```

`worktree remove` never deletes the branch. Then once, at the end:

```bash
git -C "$REPO_ROOT" worktree prune
rmdir "$REPO_ROOT/.worktrees" 2>/dev/null
```

**Closing a workspace's last tab closes the workspace** — so close worker tabs, never the
orchestrator's, and never a tab you did not create.

---

## 9. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `agent start` fails | Pane not at a shell prompt | Finish/kill the foreground process, retry |
| `agent_pane_busy` right after `tab create` | Shell still initialising | `herdr pane wait-output "$PANE" --regex '\$\|%' --timeout 15000` first |
| `agent_not_ready` on the very first worker | Workspace trust dialog | A human accepts once per repo (§1) |
| Worker blocks on every command | `acceptEdits` instead of `auto` | §4 permission mode |
| `agent wait` returns `blocked` instantly | Bare wait matches current state | `--until idle --until done` (§6) |
| Worker "done" but nothing changed | It hit an unanswered question and idled | `agent read`; check `git -C "$DIR" log` |
| Tests pass but the tool is broken | Test only covered a dry-run/mocked path | Run the deliverable for real (§7); send it back to its owner |
| Worker edits a sibling worktree | SCOPE did not forbid `.worktrees/` | §5.2; revert the stray files |
| Test runner picks up other workers' tests | Tooling not excluded from `.worktrees/` | Appendix C |
| Every worker asks for a spec | No CONTEXT given | Put the spec slice in the brief |
| Tests pass per-worktree, fail on merge | Tasks were not file-disjoint | Re-split; serialize the overlap |
| `worktree add` fails: already exists | Stale worktree from a killed run | `git worktree prune`, retry |
| `agent_not_idle` on read | Deep read while working | Wait for idle, or `--source visible` |

---

## 10. Manual mode (no orchestrator)

```bash
git worktree add .worktrees/x -b feat/x main
herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$PWD/.worktrees/x" --label x --focus
# then in the new tab:
claude --permission-mode acceptEdits
```

Sections 3, 5, 7 and 8 still apply — the decomposition rules and PR-per-worktree integration are
what make this work, not the automation.

---

## Appendix A: spawn helper

```bash
# usage: spawn <name> <branch> <base> <brief-file>
spawn() {
  local name=$1 branch=$2 base=$3 brief_file=$4
  local root dir tab_json tab pane
  root=$(git rev-parse --show-toplevel) || return 1
  dir="$root/.worktrees/$name"

  git -C "$root" worktree add "$dir" -b "$branch" "$base" || return 1

  tab_json=$(herdr tab create --workspace "$HERDR_WORKSPACE_ID" \
               --cwd "$dir" --label "$name" --no-focus) || return 1
  tab=$(jq -r '.result.tab.tab_id'         <<<"$tab_json")
  pane=$(jq -r '.result.root_pane.pane_id' <<<"$tab_json")
  printf 'worker %-8s tab=%s pane=%s dir=%s\n' "$name" "$tab" "$pane" "$dir"

  herdr agent start "$name" --kind claude --pane "$pane" -- --permission-mode acceptEdits || return 1
  herdr agent prompt "$name" "$(cat "$brief_file")" --wait --timeout 1800000
}
```

---

## Appendix B: worktree provisioning hook

Git's `post-checkout` hook runs on `git worktree add` with the working directory set to the
*new* worktree and `$3 = 1`. One committed hook provisions every worktree.

```bash
# .githooks/post-checkout  (chmod +x, commit it)
#!/bin/sh
[ "$3" = "1" ] || exit 0                          # branch checkouts only
COMMON=$(git rev-parse --git-common-dir)
MAIN=$(cd "$COMMON/.." && pwd)
[ "$(pwd)" = "$MAIN" ] && exit 0                  # skip the primary checkout

for f in .env .env.local; do
  [ -f "$MAIN/$f" ] && cp "$MAIN/$f" .
done
# Large, immutable caches are better symlinked than copied:
# [ -d "$MAIN/node_modules" ] && ln -sfn "$MAIN/node_modules" node_modules

exit 0                                            # never fail worktree creation
```

Enable once per clone — `core.hooksPath` is local config and is not committed:

```bash
git config core.hooksPath .githooks
```

Keep it fast (it blocks `worktree add`), always `exit 0`, and never put `npm ci` in it.

---

## Appendix C: keeping tooling out of `.worktrees/`

In-repo worktrees mean N copies of your codebase under the repo root. Measured behaviour:

| Tool | Sees `.worktrees/`? | Action |
|---|---|---|
| `git status` / `git add` | **no**, once `.gitignore` has `.worktrees/` | nothing |
| `ripgrep`, `git grep` | **no** — respects `.gitignore` | nothing |
| `find`, `ls **` | **yes** | scope your globs |
| tsc, jest, eslint, pytest, webpack | **yes** — they ignore `.gitignore` | exclude explicitly |

A worktree does **not** nest: `.worktrees/api/` contains only the branch's tracked files, so
there is no recursion to worry about.

Add the exclude your toolchain needs, once:

```jsonc
// tsconfig.json
"exclude": [".worktrees"]
// jest.config.js
testPathIgnorePatterns: ["/.worktrees/"]
// .eslintignore        →  .worktrees/
// pytest.ini           →  norecursedirs = .worktrees
```

Skipping this is the single most likely way this setup bites you: a worker runs the suite and
silently executes three other workers' tests.
