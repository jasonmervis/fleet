# Parallel Agents on In-Repo Worktrees (Herdr)

The playbook behind the `fleet` CLI. It lives beside its skill, at
`.claude/skills/fleet/ORCHESTRATION.md`, and `fleet init` installs both into a repo. **No
repo-specific values are hardcoded**: everything that varies per repo (base branch, install
command, test command, agent, model, issue filter) is detected in §1 or declared once in
`.fleet.toml`.

**This file explains; `fleet` enforces.** Where a section shows raw `git`/`herdr`/`gh` commands,
they document what the CLI does and are the fallback for §11's manual mode. Run the CLI:

| Section | Command |
|---|---|
| §0 adopt | `fleet init`, `fleet doctor` |
| §1 preconditions, detection, config | `fleet config`, `fleet preflight` |
| §5 spawn one worker | `fleet spawn --name … --branch … [--agent … --model …]` |
| §6 brief | `fleet brief <name> --file brief.md`; whole batch: `fleet up split.toml` |
| §7 supervise | `fleet status [--blocked] [--json]`, `fleet logs <name>` |
| §8.1–§8.2 verify, mark ready | `fleet verify [--mark-ready]` |
| §8.3 merge | a human — `fleet` never merges |
| §9 teardown | `fleet teardown --name … / --all / --overrun` |

In shell snippets, `$FLEET_BASE`, `$FLEET_INSTALL`, `$FLEET_TEST`, `$FLEET_BRANCH_PREFIX`,
`$FLEET_ISSUE_FILTER` and `$FLEET_PERMISSION_MODE` stand for the `.fleet.toml` keys `base`,
`install`, `test`, `branch_prefix`, `issue_filter` and `permission_mode`, as `fleet config` prints them.

**Topology:** one Herdr workspace = one repo. The orchestrator holds tab 1. Each worker gets
its own **tab** in that same workspace, rooted in its own **in-repo git worktree** under
`.worktrees/`, on its own branch, ending in its own PR.

```
workspace "MyRepo"  (w3)
├── t1  orchestrator   cwd <repo>                     ← you
├── t2  i42            cwd <repo>/.worktrees/i42      branch feat/42-api-tokens   issue #42
├── t3  i43            cwd <repo>/.worktrees/i43      branch feat/43-token-ui     issue #43
└── t4  i44            cwd <repo>/.worktrees/i44      branch feat/44-token-docs   issue #44
```

Switch workers with Herdr's tab keys. Every worker's files are under your repo root, so your
editor and file tree see all of them.

Work comes from one of two places: **GitHub Issues** (§3, the default) or a human-authored split
(§4). Either way it ends as one PR per worktree.

Verified against Herdr 0.9.0 + Claude Code, and **validated end-to-end by a two-worker dry run**:
worktree + tab + agent spawn, parallel briefs, scope adherence, merge, teardown. **Not yet
exercised against a live GitHub remote** — every `gh` step in §3, §6 and §8 is written from the
CLI contract, not from a real run. Treat the first issue-driven run as a supervised one.

---

## 0. Adopting this playbook in a new repo

```bash
uv tool install git+ssh://git@github.com/<org>/MultiTest@v<version>
cd /path/to/target-repo
fleet init        # idempotent; re-run to upgrade the skill after upgrading the CLI
fleet doctor      # CLI, skill stamp and herdr versions agree
fleet config      # check what was detected
```

`fleet init` does, and prints each change:

- adds `.worktrees/` and `.fleet/` to `.gitignore`;
- writes `.githooks/post-checkout` (Appendix B) if absent and sets `core.hooksPath` — **local
  config that does not travel through git**, so re-run `fleet init` in every clone. It leaves a
  foreign `core.hooksPath` (e.g. husky) alone and warns;
- writes `.fleet.toml` from detection if absent (never overwrites it);
- copies this skill into `.claude/skills/fleet/`, stamped with `fleet_version`;
- on forge `github`, creates the `fleet-ready` and `fleet-wip` labels. Without them
  `gh issue list --label fleet-ready` returns an empty list, not an error, which reads as "no
  work" when it means "misconfigured".

Two things it cannot do for you:

1. **The Appendix C exclude** for this repo's toolchain. Go and Cargo need none; anything with a
   glob-based file walker does.
2. **Workspace trust (§1.4).** A human accepts it once, in the target repo, before the first spawn.

---

## 1. Preconditions and per-repo bootstrap

### 1.1 Hard preconditions

The orchestrator runs this first and stops on any failure:

```bash
test "${HERDR_ENV:-}" = 1 || { echo "not inside Herdr — abort"; exit 1; }
REPO_ROOT=$(git rev-parse --show-toplevel)     # must succeed
git rev-parse HEAD >/dev/null                  # repo must have >=1 commit
git status --porcelain                         # must be empty, or commit/stash first
command -v jq >/dev/null                       # jq for JSON
herdr integration status | grep '^claude:'     # must say "current", not "not installed"
```

`herdr integration install claude` fixes the last one. Without it Herdr cannot read worker
lifecycle state and every `--wait` degrades to guessing.

`gh` is required only for the GitHub paths (issue sourcing §3, PR delivery §6/§8):

```bash
command -v gh >/dev/null && gh auth status && gh repo view --json nameWithOwner
```

If any of those fail, the repo has no usable GitHub remote: skip §3, author briefs by hand (§4),
and have workers deliver a branch + summary instead of a PR. Say so in the brief.

### 1.2 Detect what varies per repo

None of these are guesses the orchestrator should make silently — print the resolved values and
show them to the human alongside the split (§4).

**Base branch** — three sources, most authoritative first:

```bash
FLEET_BASE=$(gh repo view --json defaultBranchRef -q .defaultBranchRef.name 2>/dev/null) \
  || FLEET_BASE=$(git symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null) \
  || FLEET_BASE=$(git rev-parse --abbrev-ref HEAD)
FLEET_BASE=${FLEET_BASE#origin/}          # source 2 returns origin/<name>; strip after, not in a pipe
[ -n "$FLEET_BASE" ] || { echo "cannot resolve base branch — set FLEET_BASE"; exit 1; }
```

**Do not put the `origin/` strip in a pipe.** `git symbolic-ref ... | sed` exits with `sed`'s
status, which is `0` even when git failed, so the `||` chain never reaches the third source and
`FLEET_BASE` ends up empty. Verified: piped form returns `[]` where the form above returns
`[main]`.

`refs/remotes/origin/HEAD` is frequently unset on a fresh clone (`fatal: ref ... is not a
symbolic ref`) — that is why it is second, not first. `git remote set-head origin --auto` fixes
it permanently.

Source 3 is a last resort: it returns whatever branch the orchestrator happens to be on. Print
it and have the human confirm before spawning anything on it.

**Toolchain** — the lockfile decides. Pick the first that matches:

| Marker file | `FLEET_INSTALL` | `FLEET_TEST` |
|---|---|---|
| `pnpm-lock.yaml` | `pnpm install --frozen-lockfile` | `pnpm test` |
| `yarn.lock` | `yarn install --immutable` | `yarn test` |
| `bun.lockb` / `bun.lock` | `bun install --frozen-lockfile` | `bun test` |
| `package-lock.json` | `npm ci` | `npm test` |
| `uv.lock` | `uv sync --frozen` | `uv run pytest` |
| `poetry.lock` | `poetry install --sync` | `poetry run pytest` |
| `requirements.txt` | `pip install -r requirements.txt` | `pytest` |
| `go.mod` | `go mod download` | `go test ./...` |
| `Cargo.toml` | `cargo fetch` | `cargo test` |
| `*.sln` / `*.csproj` | `dotnet restore` | `dotnet test` |
| `pubspec.yaml` | `flutter pub get` (or `dart pub get`) | `flutter test` |
| `*.cabal` / `cabal.project` | `cabal build --only-dependencies --enable-tests` | `cabal test` |
| `Gemfile.lock` | `bundle install` | `bundle exec rspec` |
| `pom.xml` | `mvn -B -q dependency:go-offline` | `mvn -B test` |
| `build.gradle{,.kts}` | `./gradlew --no-daemon dependencies` | `./gradlew --no-daemon test` |
| none of the above | `:` (no-op) | **ask the human** |

Two repos in three will need an override — a monorepo package filter, a `make test`, a required
`--workspace` flag. Detection is a starting point, not an answer.

### 1.3 `.fleet.toml` — the per-repo override

Optional, committed, TOML. Every key wins over detection; an unknown key or a wrong type is an
error, not a silent default. Flags on `fleet spawn` win over the file.

```toml
# .fleet.toml
base = "develop"                          # not the GitHub default branch here
install = "pnpm install --frozen-lockfile --filter ./packages/..."
test = "pnpm -r test"
install_timeout_ms = 600000               # big monorepos need more than the 300000 default
branch_prefix = "feat"                    # branches become <prefix>/<issue>-<slug>
issue_filter = "--label fleet-ready --state open"
agent = "claude"                          # claude | codex
model = "sonnet"                          # empty = the agent's default
permission_mode = "auto"                  # auto | edits | readonly — see §5
allowlist = ["Bash(npm test:*)", "Bash(gh pr create:*)"]   # claude only
max_workers = 4
max_minutes = 120                         # `fleet status` flags workers past this
forge = "auto"                            # auto | github | local
assign = "defaults"                       # defaults | ask — see below
```

`assign` decides who picks each worker's agent and model. With `defaults`, a worker the human
did not assign gets `agent`/`model` from this file. With `ask`, the orchestrator must ask the
human for every worker, and `fleet up` refuses a split in which any `[[worker]]` lacks an
explicit `agent` and `model` (`model = ""` is an explicit choice of the agent's default). Each
`[[worker]]` can also set `base`, `permission_mode`, `allowlist` (replaces this file's) and
`allow_unsupervised`.

`fleet config` prints every resolved value and its source (`detected`, `.fleet.toml`, `default`,
`flag`).

**If `test` is empty or unproven, stop.** A worker with no command that proves it is done will
report done wrongly (§4.4). `fleet preflight` runs `test` on the base commit and records it;
`fleet spawn` refuses `permission_mode = "auto"` until it has passed on the current base — a
suite that is already red makes every worker's result meaningless.

### 1.4 One-time per repo: the workspace trust dialog

The first Claude agent launched in a brand-new repo blocks at startup with `agent_not_ready`:

```
Quick safety check: Is this a project you created or one you trust?
❯ No, exit / Yes, I trust this folder
```

Trust is recorded against the **git repo root**, and covers every worktree — including ones
created later. Verified: after accepting once inside one worktree, a brand-new worktree started
`idle` with no prompt. So a human must accept once, before the first spawn; never again for that
repo. **The orchestrator must not answer this dialog on the human's behalf.**

### 1.5 One-time repo setup

Done in §0.1 if you adopted this playbook by copying it. Verify rather than assume — the
`core.hooksPath` line is local config and is absent in a fresh clone even when everything else
is committed:

```bash
grep -qxF '.worktrees/' .gitignore || echo '.worktrees/' >> .gitignore
git config core.hooksPath .githooks             # if using the provisioning hook (Appendix B)
```

Then add your toolchain's exclude for `.worktrees/` — Appendix C, and skipping it is the single
most likely way this setup bites you.

---

## 2. Roles

| | Orchestrator | Worker |
|---|---|---|
| Location | tab 1, at `$REPO_ROOT` | its own tab, at `.worktrees/<name>` |
| Branch | stays on `$FLEET_BASE` | its own `$FLEET_BRANCH_PREFIX/<issue>-<slug>` |
| Writes code | **no** | yes, only inside its worktree |
| Knows the whole plan | yes | only its own brief and its own issue |
| Talks to GitHub | triages issues, reviews drafts, promotes them to ready | reads its own issue, opens its own draft PR |
| Marks a PR ready for review | **yes — only it** (§8.2) | **no, never** |
| Ends with | reviewed PRs marked ready, then merged by a human; closed issues; clean teardown | one draft PR, then idle |

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
They are started already inside theirs. This goes in the brief (§6).

---

## 3. Source the work from GitHub Issues

The Issue is the unit of work, the brief's anchor, and the thing the PR closes. The orchestrator
triages; each worker reads its own issue in full.

### 3.1 Pull the candidates

```bash
gh issue list $FLEET_ISSUE_FILTER --limit 50 \
  --json number,title,labels,assignees,milestone,body \
  --jq '.[] | [.number, (.assignees|length), (.labels|map(.name)|join(",")), .title] | @tsv'
```

Useful filters, all composable into `FLEET_ISSUE_FILTER`:

```bash
--label fleet-ready          # opt-in queue — recommended; humans decide what is agent-safe
--milestone "Sprint 14"      # everything in a milestone
--assignee "@me"             # what the human running this already owns
--search 'no:assignee'       # unclaimed only
--state open                 # always; never spawn on a closed issue
```

`--label fleet-ready` is the recommended gate. An unfiltered `gh issue list` will hand the fleet
bug reports, questions and duplicates, and a worker will dutifully try to implement a question.

### 3.2 Reject issues that cannot be worked in parallel

An issue is **fleet-ready** only if all of these hold. Check each candidate; drop the ones that
fail and tell the human why.

1. **It names an outcome, not a symptom.** "Tokens expire after 24h" is workable; "login is
   weird sometimes" is a debugging session, not a parallel task.
2. **Its file scope is knowable.** You must be able to write `owns <paths>` for it before
   spawning. If you cannot, neither can the worker, and it will wander.
3. **It is disjoint from every other issue in the batch** (§4.1). Two issues on the same file
   are one sequential task, whatever their numbers say.
4. **It has acceptance criteria, or you can write them.** They become DONE-WHEN (§6.4).
5. **It is unassigned, or assigned to the human running the fleet.** An issue someone else owns
   is not yours to take.
6. **It does not depend on another open issue in the batch.** Dependencies serialize. Land the
   dependency first, on the base branch, then spawn (§4.2).
7. **It is not already labelled `fleet-wip`.** That label means in progress — another agent has
   picked it up (§3.4). Drop it from the batch regardless of how untouched it looks; no
   assignee, no branch, and an old claim comment do not override the label.

Filter the claimed ones out rather than eyeballing the list:

```bash
gh issue list $FLEET_ISSUE_FILTER --json number,title,labels \
  --jq '.[] | select([.labels[].name] | index("fleet-wip") | not) | [.number, .title] | @tsv'
```

Issues failing 1, 2 or 4 are usually salvageable by a human adding a scope + criteria comment —
that is a cheaper fix than supervising a wandering worker.

### 3.3 Derive names and branches from the issue

Worker names are path components and tab labels, so keep them boring: `[a-z][a-z0-9_-]{0,31}`.

```bash
ISSUE=42
TITLE=$(gh issue view "$ISSUE" --json title -q .title)
SLUG=$(printf '%s' "$TITLE" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' \
        | cut -c1-40 | sed 's/^-//; s/-*$//')
NAME="i$ISSUE"                                   # i42 — short, unique, valid
BRANCH="$FLEET_BRANCH_PREFIX/$ISSUE-$SLUG"       # feat/42-add-api-tokens-to-settings-v2
```

`tr -cs 'a-z0-9' '-'` squeezes every run of non-alphanumerics into one `-`, which is portable
across BSD and GNU `tr`; `sed 's/[^a-z0-9]\+/-/g'` is not (BSD `sed` has no `\+`). Verified on
macOS: `Add API tokens to /settings (v2)` → `add-api-tokens-to-settings-v2`.

### 3.4 Claim the issue through the serialized gate before spawning

`fleet-wip` is the in-progress tag, and the only one — it says an agent owns this ticket. Claim
before the worker starts, not after: an issue being worked without the label is invisible to the
next agent sourcing work, and two agents on one ticket is two conflicting branches. It also means
a human looking at the board can see the fleet has it.

The issue list and the §3.2 checks are snapshots, not locks. `fleet spawn --issue N` claims
before it creates anything, as the first step of its transaction:

```bash
fleet spawn --name "i$ISSUE" --branch "$BRANCH" --issue "$ISSUE"
```

The claim dispatches `.github/workflows/fleet-claim.yml` (`fleet init` installs it on forge
`github`; it must be on the default branch to be dispatchable). GitHub serializes runs by issue
number; the workflow re-checks that the issue is open, `fleet-ready`, and not `fleet-wip`, then
records a unique claim token. The helper waits for that exact run and verifies its token on the
issue. **Only a verified token grants ownership.** A denied claim fails the spawn at step `claim`
with nothing created; pick another issue. If a later spawn step fails, the claim is released.

Never replace the gate with `gh issue edit --add-label fleet-wip`. Labels have no
compare-and-swap operation, so two racing clients can both report success. `fleet-wip` is the
visible projection of a granted claim, not the mutual-exclusion mechanism.

**`--add-assignee "@me"` assigns the human's GitHub account, not the agent.** Agents have no
GitHub identity here; they push as whoever `gh auth` is. Use a label to mark fleet ownership and
leave assignment to humans, or the board will lie about who is doing the work.

### 3.5 Issues the fleet creates

A worker that finds real work outside its scope must not do it. The brief (§6.6) tells it to
stop and report; the **orchestrator** files the follow-up so it lands with correct labels and
cross-links:

```bash
gh issue create --title "<what>" --body "Found while working #$ISSUE. Out of scope for that PR.

<worker's report>" --label needs-triage
```

Do not let workers file issues directly. Four workers each filing their own duplicates of the
same missing-migration finding is noise the human then has to clean up.

---

## 4. Decompose before you spawn

This is the step that decides whether parallelism helps or costs you a day. It applies to
issue-sourced batches (§3) exactly as it does to hand-written ones — **an issue tracker does not
decompose work for you**, it only stores work someone else split, possibly badly.

1. **File-disjoint.** Two workers must not need to edit the same file. Overlapping tasks are
   not parallel tasks — they are one sequential task.
2. **Shared foundation goes first, alone.** Schema, shared types, migrations, config, a new
   base class: land that on the base branch *before* spawning anyone. Workers branching off a
   missing foundation will each invent their own.
3. **Cap at 3–4 workers.** Beyond that, merge-conflict resolution and supervision cost more
   than the parallelism returns. A 20-issue milestone is five batches, not one fleet.
4. **Each task must be independently testable.** If a worker cannot run a command to prove it is
   done, it will report done wrongly.
5. **Write the split down and get human sign-off before spawning.** Spawning is cheap;
   unwinding four half-done conflicting branches is not.

**Anti-patterns:** splitting one feature into "frontend worker" + "backend worker" that share a
contract file; a "refactor everything" worker running alongside anyone; two workers that both
touch the dependency manifest; taking the top 4 issues off the queue without reading them.

**Split template** — fill in and show the human before §5:

```
repo:    <owner/name>            (gh repo view --json nameWithOwner)
base:    main @ <sha>            install: npm ci        test: npm test
source:  gh issue list --label fleet-ready

worker  i42  branch feat/42-api-tokens      issue #42  owns  src/api/**, tests/api/**
worker  i43  branch feat/43-token-settings  issue #43  owns  src/ui/settings/**
worker  i44  branch feat/44-token-docs      issue #44  owns  docs/**, README.md

shared, pre-landed:  src/types/token.ts  (commit <sha> on main, closes #41)
dropped:             #45 — scope overlaps #42 on src/api/auth.ts; run after #42 merges
                     #47 — no acceptance criteria; asked <human> to add them
```

---

## 5. Spin up one worker

Run per worker, from the orchestrator's tab. Every ID comes from JSON — never predict `w3:t2`.

```bash
DIR="$REPO_ROOT/.worktrees/$NAME"                # NAME/BRANCH from §3.3, or chosen by hand

# 1. in-repo worktree, exact branch, no lock
git -C "$REPO_ROOT" worktree add "$DIR" -b "$BRANCH" "$FLEET_BASE"

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
herdr pane run "$PANE" "$FLEET_INSTALL"
herdr pane wait-output "$PANE" \
  --regex "${FLEET_INSTALL_DONE:-added [0-9]+ packages|up to date|ERR|error|Error}" \
  --timeout "$FLEET_INSTALL_TIMEOUT"
```

The default regex is npm-shaped. **Set `FLEET_INSTALL_DONE` for anything else** — `go mod
download` and `cargo fetch` succeed silently and will sit there until your timeout expires.
Where the tool prints nothing useful, wait on the shell prompt instead
(`--regex '\$ $|% $'`). The pane must be back at its prompt or the next step fails.

(Fast file provisioning — `.env` and friends — is automatic via the hook in Appendix B. Slow
installs stay here; never in the hook.)

```bash
herdr agent start "$NAME" --kind claude --pane "$PANE" -- \
  --permission-mode "$FLEET_PERMISSION_MODE"     # fleet adds --model / --allowedTools from config
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
is a committed allowlist, which keeps approval explicit and reviewable. Note it must cover the
**GitHub** commands too, or the worker sails through its tests and then blocks on `gh pr create`:

```jsonc
// .claude/settings.json — adjust the test/install entries to this repo's toolchain
{ "permissions": { "allow": ["Bash(npm test:*)", "Bash(git add:*)",
                             "Bash(git commit:*)", "Bash(git push:*)",
                             "Bash(gh issue view:*)", "Bash(gh pr create:*)",
                             "Bash(gh pr view:*)"] } }
// Deliberately absent: Bash(gh pr ready:*). Promoting a draft is the orchestrator's
// gate (§8.2), so a worker should not have the command at all.
```

Do **not** use `bypassPermissions` unless the human explicitly asks and understands the worktree
is not sandboxed.

`agent start` returns only once Herdr sees the agent ready. `agent_not_ready` means it came up
blocked — read it, clear it, then prompt.

---

## 6. The worker brief

A worker starts with **zero context**: it has not seen the plan, this conversation, the other
workers, or the issue. The brief is the entire contract. Six mandatory parts:

```
1. GOAL        One paragraph. What must be true when you are done.
2. SCOPE       Files/dirs you own. Explicit: "Do not edit anything outside <paths>.
               If the task seems to require it, stop and report instead."
               Also: "You are already in a git worktree on branch <branch>, and your
               cwd is its root. Do not create another worktree — no EnterWorktree,
               no `claude -w`. Do not touch ../ or any sibling under .worktrees/."
3. CONTEXT     "Your task is issue #<N>. Read it in full first:
                  gh issue view <N> --comments
               Treat the issue body and its comments as the requirement; treat this
               brief as the boundary. Where they disagree, this brief wins — and say
               so in your PR."
               Plus the shared decisions already made — API shape, types, naming, the
               base commit, the relevant spec slice. Paste them; do not make the
               worker re-derive them.
4. DONE-WHEN   Concrete acceptance criteria (from the issue) plus the exact command
               that proves it — $FLEET_TEST, scoped to this worker's paths.
5. DELIVERY    "Commit to <branch>, push, and open a DRAFT PR:
                  gh pr create --draft --base <FLEET_BASE> --fill --body '...Closes #<N>'
               It must be --draft. The orchestrator reviews it (§8) and marks it ready
               for review itself; a PR you mark ready has skipped that gate.
               Put your summary, your decisions, and anything you could not do in the
               PR body. Do not close the issue by hand; do not merge your own PR; do not
               run `gh pr ready`."
6. ESCALATE    "If blocked, if a decision is not yours to make, or if the work needs a
               file outside your scope — stop and say so. Do not guess, and do not
               open a new issue; report it and the orchestrator will file it."
```

Submit it:

```bash
herdr agent prompt "$NAME" "$BRIEF" --wait --timeout 1800000
```

> Global agent standards commonly make every agent look for a spec before writing code. Give
> workers the spec (or the relevant slice) in CONTEXT, or all N will separately stop and ask the
> human to write one.

**"Closes #N" only auto-closes on merge into the repository's default branch.** If
`FLEET_BASE` is a `develop`-style integration branch, the issue stays open after the PR merges
and the orchestrator closes it in §8. Do not brief the worker to close it either way — an issue
closed before the PR merges is a lie on the board.

**Sibling worktrees are visible to every worker** — they are all under the same repo root. That
is the cost of in-repo placement, and SCOPE is what contains it. Be explicit that `.worktrees/`
is off-limits.

**The PR body is the deliverable, not the terminal.** Scraping a worker's transcript is fragile;
`gh pr view` is not. Design every brief so the answer lands in the PR.

---

## 7. Supervise

`--wait` returns on the first settled state: `idle`, `done`, `blocked`, or an error.

| Result | Meaning | Do |
|---|---|---|
| `done` / `idle` | Ready for input. Not proof of success. | Verify via PR + tests, §8 |
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
gh pr list --state open --json number,headRefName,isDraft,title  # the fleet's output so far
# isDraft:true is the expected resting state for a worker PR. isDraft:false on one you have
# not promoted yourself (§8.2) means a worker marked its own work ready — check it before
# a reviewer does.
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
herdr notification show "i42 needs input" --body "approval dialog in tab $TAB" --sound request
```

---

## 8. Review, then integrate — one PR per worktree

Every worker PR arrives as a **draft** (§6.5). A draft is a claim, not a result. The
orchestrator's self-review is the gate between the two, and it has one exit:

```
worker opens draft PR  →  §8.1 orchestrator self-review  →  gh pr ready  →  human/external review
                                      │                                              │
                                      └─ fails? send back to the owning worker,       ↓
                                         stay draft                          approved → merge
                                                                    (a human, or §8.3 on their
                                                                     explicit opt-in for this batch)
```

Marking a PR ready is the orchestrator saying *"I checked this myself and it is worth a
reviewer's time."* Never mark ready to signal that a worker has finished — finishing is what
`done` means; ready means *verified*. A draft that fails review goes back to its worker and
stays draft; it does not accumulate a reviewer's comments while still broken.

### 8.1 Self-review, before marking anything ready

Never merge — or mark ready — on a worker's say-so:

```bash
gh pr view "$BRANCH" --json title,body,files,statusCheckRollup,closingIssuesReferences
git -C "$DIR" status --porcelain            # must be clean
git -C "$DIR" log --oneline "$FLEET_BASE".."$BRANCH"
git diff "$FLEET_BASE...$BRANCH"            # works from the orchestrator tab, any branch
```

Per PR: confirm the diff stays inside that worker's declared scope; run `$FLEET_TEST` yourself;
read the PR body for what the worker could not do; check `closingIssuesReferences` actually
names the issue you gave it — an empty array means the `Closes #N` never made it into the body
and the issue will not close on merge.

**Run the thing, not just its tests.** A worker optimises for the acceptance criteria you gave
it, so a test that only exercises a mocked or `--dry-run` path will pass over a tool that is
broken in real use. Observed on a real run: all three contract tests passed, but `status.sh`
died the moment it was invoked for real, because it passed an option the underlying CLI does not
accept — a path no test covered. Invoke each deliverable the way a user would before you merge,
and send failures back to the worker that owns the file rather than fixing them yourself.

**Trial-merge the batch before marking any of it ready.** Each PR passing alone says nothing
about the batch: workers cannot see each other, so a contract between two of them is two
independent guesses. Merge every branch into a throwaway branch off the current base, run
`$FLEET_TEST` on the combined tree, and run the deliverable for real there:

```bash
git -C "$REPO_ROOT" worktree add "$REPO_ROOT/.worktrees/_integ" -b tmp/integ "origin/$FLEET_BASE"
for B in $BRANCHES; do git -C "$REPO_ROOT/.worktrees/_integ" merge --no-edit "$B"; done
# run $FLEET_INSTALL, then $FLEET_TEST, then the deliverable itself, in _integ
git -C "$REPO_ROOT" worktree remove "$REPO_ROOT/.worktrees/_integ" --force
git -C "$REPO_ROOT" branch -D tmp/integ
```

Observed on a real run: two workers each passed their own suite, but one defaulted a seed path
to `fixtures/listings/listings.json` while the other committed `fixtures/listings/cape_town.json`
— the name its issue specified three times. Measured on the combined tree: **0 rows seeded
instead of 300**, silently, because a missing fixture was (correctly) non-fatal. Neither suite
could have caught it; each tested only its own half. Re-run this against the *current* base, not
the one you spawned from — the base moves while the fleet works.

### 8.2 Mark ready, once and only once it passes

When a draft clears §8.1 — scope clean, `$FLEET_TEST` green, deliverable exercised for real,
batch trial-merged, `closingIssuesReferences` correct — promote it:

```bash
gh pr ready "$PR"                                   # draft -> ready for review
gh pr comment "$PR" --body "Orchestrator self-review passed: scope clean, \`$FLEET_TEST\` green,
deliverable run for real, trial-merged with the batch against $FLEET_BASE @ <sha>. Ready for review."
```

That comment is the point of the gate. An external reviewer cannot see anything you ran in your
own terminal, so a PR that is merely *marked* ready looks identical to one nobody checked. Say
what you verified and against which base sha. **Where the repo has no CI, this comment is the
only evidence the review ever happened** — say that too, rather than letting a reviewer assume
a green checkmark exists somewhere.

Leave it draft, and say why, when any of these hold — a reviewer's time is the scarce thing:

| Leave as draft | Because |
|---|---|
| Any §8.1 check failed | It goes back to its worker, not to a reviewer |
| A dependency PR in the batch is still draft | Reviewing it in isolation reviews a fiction |
| The worker's PR body reports a blocker it could not resolve | The human decides before review, not after |
| A cross-worker contract was set unilaterally | Flag it *in the PR* so review starts at the real decision |

**Merge order:** smallest diff first, most-depended-on first. Humans merge; the orchestrator
does not merge its own fleet's PRs unless the human says so for that batch — §8.3 is how that
opt-in is exercised, and it merges only what a human has approved. After each merge, every
remaining worker is stale:

```bash
herdr agent prompt "$NAME" "$FLEET_BASE moved. Run: git fetch origin && git rebase origin/$FLEET_BASE.
Resolve conflicts in your own files only. Re-run $FLEET_TEST. Report the result." --wait --timeout 900000
```

**Conflicts are the orchestrator's problem, not a worker's.** A worker resolving a conflict in a
file it does not own will silently undo another worker's work. If two branches conflict outside
one worker's scope, merge one, then hand the rebase back with an explicit instruction about
which side wins.

Close the loop on the board, per merged PR:

```bash
gh issue edit "$ISSUE" --remove-label fleet-wip
gh issue view "$ISSUE" --json state -q .state        # OPEN here means it did not auto-close
gh issue close "$ISSUE" --comment "Merged in #<pr>."  # only if still OPEN (non-default base)
```

An issue whose PR was **not** merged goes back to the queue, not to the bin:
`gh issue edit "$ISSUE" --remove-label fleet-wip --add-label fleet-ready`, with a comment saying
what went wrong. Otherwise the next run silently drops that work.

### 8.3 Merge — a human does it

`fleet` does not merge, and the orchestrator does not either. `fleet verify` is the evidence; a
human reads it and merges. Earlier revisions of this playbook let the orchestrator merge approved
PRs on a poll after a per-batch opt-in. That was removed: every guard it needed (stale approvals
after a later push, pending checks read as success, `mergeable: UNKNOWN`, `--auto` merging on an
unprotected branch) was a way for an agent to merge unreviewed code, and the time it saved was
the human's review latency — which is the point of the review.

After each merge, every remaining worker is stale. Re-run `fleet verify` on what is left before
anything else is merged, and send conflicting workers back to rebase:

```bash
herdr agent prompt "$NAME" "$FLEET_BASE moved. Run: git fetch origin && git rebase origin/$FLEET_BASE.
Resolve conflicts in your own files only. Re-run the test command. Report the result." --wait --timeout 900000
```

---

## 9. Teardown

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

## 10. Failure modes

| Symptom | Cause | Fix |
|---|---|---|
| `agent start` fails | Pane not at a shell prompt | Finish/kill the foreground process, retry |
| `agent_pane_busy` right after `tab create` | Shell still initialising | `fleet spawn` ≥ 0.1.1 does this wait (step `shell`, `shell_prompt_regex`) and retries; by hand: `herdr pane wait-output "$PANE" --regex '[$%❯] *$' --timeout 15000` first |
| `agent_not_ready` on the very first worker | Workspace trust dialog | A human accepts once per repo (§1.4) |
| Worker blocks on every command | `acceptEdits` instead of `auto` | §5 permission mode |
| Worker blocks only at the end | Allowlist covers tests but not `gh` | Add `Bash(gh pr create:*)` (§5) |
| `agent wait` returns `blocked` instantly | Bare wait matches current state | `--until idle --until done` (§7) |
| Worker "done" but nothing changed | It hit an unanswered question and idled | `agent read`; check `git -C "$DIR" log` |
| Tests pass but the tool is broken | Test only covered a dry-run/mocked path | Run the deliverable for real (§8); send it back to its owner |
| Worker edits a sibling worktree | SCOPE did not forbid `.worktrees/` | §6.2; revert the stray files |
| Test runner picks up other workers' tests | Tooling not excluded from `.worktrees/` | Appendix C |
| Every worker asks for a spec | No CONTEXT given | Put the spec slice in the brief |
| Tests pass per-worktree, fail on merge | Tasks were not file-disjoint | Re-split; serialize the overlap |
| `worktree add` fails: already exists | Stale worktree from a killed run | `git worktree prune`, retry |
| `agent_not_idle` on read | Deep read while working | Wait for idle, or `--source visible` |
| `spawn failed at step install` | `install` failed or exceeded `install_timeout_ms` | Fix the command, or raise the timeout in `.fleet.toml` |
| Worker installs nothing, then fails on imports | `install` detected as `:` | Set `install` in `.fleet.toml` (§1.3) |
| `locked by pid N` | Another fleet spawn/teardown is running | Wait; if that pid is gone the lock is taken over after 10 min |
| `permission mode auto needs a passing preflight` | No preflight, or base moved since | `fleet preflight`, or `--permission-mode edits` |
| `<agent>: lifecycle integration missing` | Herdr can't report that agent's state | `herdr integration install <agent>`, or `--allow-unsupervised` |
| `<agent>: no fleet adapter` | Herdr can launch it; fleet can't configure it | Use `claude` or `codex` |
| `fleet status` shows `gone` | Agent exited or its tab was closed by hand | `fleet logs`, then `fleet teardown --name` |
| `fleet status` shows `untracked` | An agent in `.worktrees/` that fleet did not spawn | Find its owner before touching it |
| Base branch resolves to a feature branch | No `origin/HEAD`, orchestrator on a branch | `git remote set-head origin --auto`, or set `FLEET_BASE` |
| `gh` says `no git remotes found` | Repo has no GitHub remote | Skip §3; hand-author briefs; deliver branches not PRs |
| Merged PR left the issue open | `Closes #N` only fires on the default branch | Close it in §8; expected when `FLEET_BASE` is not default |
| `closingIssuesReferences` empty on a PR | Worker omitted `Closes #N` from the body | `gh pr edit <n> --body` to add it before merging |
| Fleet picks up a question or duplicate issue | Unfiltered `gh issue list` | Gate on `--label fleet-ready` (§3.1) |
| Reviewer starts on a PR that was still broken | It was opened ready, or promoted on a worker's say-so | Workers open `--draft`; only §8.2 promotes |
| Worker's PR is already `isDraft:false` | Brief omitted `--draft`, or worker ran `gh pr ready` | Fix the brief (§6.5); drop `gh pr ready` from the allowlist (§5) |
| Each PR green alone, batch broken together | Marked ready without the §8.1 trial-merge | Trial-merge the batch, re-run on the combined tree |
| Reviewer cannot tell what was verified | Promoted silently — nothing in-terminal is visible to them | Post the §8.2 evidence comment with the base sha |
| Approved PR merged with unreviewed commits on it | `reviewDecision` stays `APPROVED` after a later push | §8.3 gate compares newest approval against head commit date |
| Merged while CI was still running | Empty/`null` rollup read as success | §8.3 waits on `conclusion: null`; empty rollup means *no CI*, not passing |
| `--auto` merged instantly, before any review | `allow_auto_merge` on but branch unprotected — nothing to wait for | Protect the base with required reviews, or poll instead (§8.3) |
| Poll loop burns tokens finding nothing | Interval far shorter than human review latency | 10–30 min (§8.3); cancel the loop when the batch is empty |
| Orchestrator merges without being asked | Treated §8.3 as the default | Opt-in is per batch and explicit; silence is no |
| Two workers conflict on day one | Issues were not checked for disjointness | §3.2 rule 3; serialize them |
| Board shows nobody working | Agents have no GitHub identity | Label `fleet-wip`, don't rely on assignees (§3.4) |
| Duplicate follow-up issues after a run | Workers filed their own | Only the orchestrator files (§3.5) |

---

## 11. Manual mode (no orchestrator)

```bash
git worktree add .worktrees/i42 -b feat/42-api-tokens "$FLEET_BASE"
herdr tab create --workspace "$HERDR_WORKSPACE_ID" --cwd "$PWD/.worktrees/i42" --label i42 --focus
# then in the new tab:
claude --permission-mode acceptEdits
# and give it the issue yourself:  gh issue view 42 --comments
```

Sections 3, 4, 6 and 8–9 still apply — the triage rules, the decomposition rules and
PR-per-worktree integration are what make this work, not the automation.

---

## Appendix A: spawn helper

Superseded by `fleet spawn` (one worker) and `fleet up` (a batch). What `fleet spawn` does, in
order, undoing every completed step if a later one fails:

1. refuse if the name, worktree or branch exists, `max_workers` is reached, another fleet command
   holds `.fleet/lock`, the agent has no fleet adapter, the agent has no lifecycle integration
   (unless `--allow-unsupervised`), or the mode is `auto` without a preflight on the current base;
2. `git worktree add .worktrees/<name> -b <branch> <base>` — undo: remove it and delete the branch;
3. run `install` in the worktree, bounded by `install_timeout_ms`;
4. `herdr tab create --workspace $HERDR_WORKSPACE_ID --cwd <worktree> --label <name> --no-focus`
   — undo: close the tab;
5. `herdr agent start <name> --kind <agent> --pane <pane> -- <adapter args>`;
6. record the worker in `.fleet/state.json`; on forge `github` with `--issue`, claim it (§3.4).

Adapter args per agent (`fleet/agents/`):

| `permission_mode` | claude | codex |
|---|---|---|
| `auto` | `--permission-mode auto` | `--sandbox workspace-write --ask-for-approval never` |
| `edits` | `--permission-mode acceptEdits` | `--sandbox workspace-write --ask-for-approval on-request` |
| `readonly` | `--permission-mode plan` | `--sandbox read-only --ask-for-approval on-request` |
| `model` | `--model <m>` | `--model <m>` |
| `allowlist` | `--allowedTools …` | refused — codex has no per-tool allowlist |

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

# Untracked-but-required files. Add this repo's own; keep the list short and fast.
for f in .env .env.local; do
  [ -f "$MAIN/$f" ] && cp "$MAIN/$f" .
done
# Large, immutable caches are better symlinked than copied:
# [ -d "$MAIN/node_modules" ] && ln -sfn "$MAIN/node_modules" node_modules
# [ -d "$MAIN/.venv" ]       && ln -sfn "$MAIN/.venv" .venv

exit 0                                            # never fail worktree creation
```

`fleet init` writes this hook if absent and enables it. Enable once per clone —
`core.hooksPath` is local config and is not committed — by re-running `fleet init`, or:

```bash
git config core.hooksPath .githooks
```

Keep it fast (it blocks `worktree add`), always `exit 0`, and never put the install command in
it — `fleet spawn` runs `install` in the worktree after the hook, where it can fail the spawn.

---

## Appendix C: keeping tooling out of `.worktrees/`

In-repo worktrees mean N copies of your codebase under the repo root. Measured behaviour:

| Tool | Sees `.worktrees/`? | Action |
|---|---|---|
| `git status` / `git add` | **no**, once `.gitignore` has `.worktrees/` | nothing |
| `ripgrep`, `git grep` | **no** — respects `.gitignore` | nothing |
| `find`, `ls **` | **yes** | scope your globs |
| tsc, jest, eslint, pytest, webpack, go, cargo | **yes** — they ignore `.gitignore` | exclude explicitly |
| dev servers with a file watcher (uvicorn `--reload`, vite, nodemon, webpack `--watch`, air) | **yes** — the watcher's own default-ignore list covers `.git`/`.venv`/`node_modules`, not `.worktrees` | scope the watch root, don't blocklist |

A worktree does **not** nest: `.worktrees/api/` contains only the branch's tracked files, so
there is no recursion to worry about.

A file watcher is a sharper case than a one-shot linter: it fires on every save, forever, for
as long as it runs. Measured on this repo's pinned `uvicorn`/`watchfiles`: `uvicorn --reload`
with no `--reload-dir` watches the repo root, and watchfiles' default filter
(`__pycache__`, `.git`, `.venv`, `node_modules`, …) does not include `.worktrees`. A worker's
own commit — in its own worktree, editing only its own files — restarts every other agent's
(or human's) dev server on that machine. If the server also reseeds a database or holds
in-process session state, that restart is destructive, not just slow. Fix it with an
allowlist (`--reload-dir app` / vite's `server.watch.ignored` root scope), not a growing
blocklist — a positive scope can't be broken by whatever directory lands at the root next.

Add the exclude your toolchain needs, once:

```jsonc
// tsconfig.json     →  "exclude": [".worktrees"]
// jest.config.js    →  testPathIgnorePatterns: ["/.worktrees/"]
// vitest.config.ts  →  test: { exclude: ["**/.worktrees/**"] }
// eslint.config.js  →  { ignores: [".worktrees/**"] }
// pytest.ini        →  norecursedirs = .worktrees
// pyproject.toml    →  [tool.pytest.ini_options] norecursedirs = [".worktrees"]
// ruff/black        →  extend-exclude = ".worktrees"
// .dockerignore     →  .worktrees/
// uvicorn --reload  →  --reload-dir <your app package>   (scopes the watch root instead)
// vite/webpack/etc  →  scope `watch`/`server.watch` to the source root, same reasoning
```

Go and Cargo are the exceptions that need nothing: `go test ./...` and `cargo test` walk the
module/workspace, and a worktree is neither. Everything with a glob-based file walker does.

Skipping this is the single most likely way this setup bites you: a worker runs the suite and
silently executes three other workers' tests.
