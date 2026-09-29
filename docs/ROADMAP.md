# Fleet — Production Roadmap

Status: **phases 0–6 implemented** on `feat/fleet-cli` (2026-09-23) · Owner: Jason Mervis

## Where it stands

| Phase | State | Notes |
|---|---|---|
| P0 foundations | done | `fleet` CLI; sh scripts and sh tests deleted; fake-`herdr` test harness; CI workflow written (needs a remote to run) |
| P1 config | done | `.fleet.toml`, detection table, `fleet config` with sources |
| P2 state / transactions | done | `.fleet/state.json`, all-or-nothing spawn, `.fleet/lock`, safe teardown, `max_workers` |
| P3 gates | done | `preflight`, `brief`, `verify` (evidence JSON + MD) |
| P4 adapters | done | claude, codex; github (+ serialized claim gate), local |
| P5 ops + security | done | `status --blocked/--json`, gone/untracked/unsupervised/overrun, `logs`, `up`, `SECURITY.md` |
| P6 distribution | done | `init`, `doctor`, `fleet_version` stamp, skill bundled in the wheel |

177 tests, 94% coverage, green on Python 3.11 and 3.14. Smoke-tested read-only against real
Herdr 0.9.0 (`doctor`, `status`, `spawn --dry-run`, `preflight`).

### Deviations from the plan below

- **`fleet` never merges.** §8.3's opt-in orchestrator merge was removed from the playbook, not
  implemented (resolves the "merge authority" open question).
- **`--agent kiro` fails on "no fleet adapter"**, not "lifecycle missing": fleet can't set
  kiro's model or permissions at all, so the lifecycle check never gets a say.
  `--allow-unsupervised` applies to agents that *have* an adapter but no integration (codex, today).
- **Teardown's unpushed-commit refusal applies to forge `github` only.** With `local`, the
  branch is kept, so committed work survives teardown and refusing would only get in the way.
- **Issue claims go through the serialized workflow gate** (ported from the hackathon repo's
  `fleet-claim.yml`), claimed *before* the worktree exists and released on rollback. A plain
  label edit is racy and the playbook forbids it.
- **The skill is machine-level, not per-repo** (decided 2026-09-23). `fleet skill install` writes
  the bundled skill to `~/.claude/skills/fleet/`; `init` no longer copies it into repos and `doctor`
  checks the machine copy. Update path: `uv tool upgrade fleet && fleet skill install && fleet doctor`.
  Spec'd in `SPEC.md` (Skill install); not yet implemented. Until then the skill is symlinked from this
  checkout and the CLI is an editable `uv tool install`.
- **Permission modes are fleet-level** (`auto | edits | readonly`), mapped per agent, so one
  config works for claude and codex. No mode maps to `bypassPermissions`/`danger-full-access`.

### Not yet verified — needs a human

- [ ] **No remote**: CI and the `github` forge (claims, draft PRs, `--mark-ready`) are tested
  against fakes only. Push this repo and run one supervised issue-driven batch.
- [ ] **Codex flags** (`--sandbox`, `--ask-for-approval`, `--model`) are from docs; `codex` isn't
  installed here. Install it, `herdr integration install codex`, and spawn one worker.
- [ ] **No live spawn has been run** with the new CLI — only dry-runs and the fake. First real
  `fleet up` should be watched.
- [ ] Install URL in README (`git+ssh://…/<org>/MultiTest`) is a placeholder until the remote exists.


Turns the `fleet` skill (playbook + three `sh` scripts) into a supported tool that Synthesis
repos can adopt, run unattended, and upgrade without drift.

Each phase is delivered as: **extend `SPEC.md` → write `docs/superpowers/plans/<date>-<phase>.md`
→ TDD → review → merge**. This document is the *what and why*; the per-phase plans are the *how*.

---

## Decisions taken (2026-09-22)

| Question | Decision | Why |
|---|---|---|
| Language | **Python 3.11+, stdlib only** (`tomllib`, `json`, `argparse`, `subprocess`); `uv` for dev, pytest for tests | State, JSON, adapters and polling are hostile to POSIX sh; `jq` was already a hard dep |
| Agents in v1 | **Claude + Codex** | Two implementations prove the seam. Herdr can *launch* 23 kinds, but only these two have a lifecycle integration we can install and verify |
| Terminal backend | **Herdr only**, version-checked | One backend; abstracting tmux now doubles the work before any hardening lands |
| Forge | **GitHub (`gh`) + `local`** (branches, no PRs) | `local` is what this repo needs today and is the second forge implementation that proves the seam |
| Audience | **Synthesis internal repos** | Installer, versioned releases, documented threat model, enforced allowlists |
| Config format | **`.fleet.toml`** replaces `.fleet.conf` | Python can't source sh declarations; `tomllib` is stdlib. Playbook §1.3 updated in Phase 1 |
| The `sh` scripts | **Retired** in Phase 0; `SPEC.md` contracts (`--dry-run`, exit `2`, `Usage:`) carry over to `fleet <cmd>` | One implementation, not two |

### Verified facts the plan relies on

- `herdr agent start --kind` accepts: `pi claude codex gemini cursor devin agy cline omp mastracode
  opencode copilot kimi kiro droid amp grok hermes kilo qodercli qwen maki muse`.
- `herdr integration status` lists lifecycle integrations for `claude codex copilot devin droid
  kimi opencode kilo hermes qodercli qwen cursor mastracode grok pi omp antigravity-cli`.
  **Not `kiro`, not `gemini`** — those launch but `--wait` degrades to guessing (§1.1).
- Locally: `claude: current (v9)`, `codex: not installed` (fixable with `herdr integration install codex`).
- The current scripts hardcode `--kind claude`, `--model opus`, `--permission-mode auto`, `BASE=main`
  (`scripts/spawn.sh:27,58,88`) and read no config at all.

---

## Target shape

```
fleet/                      # python package, `fleet` console script
├── cli.py                  # argparse: init preflight config spawn brief status verify teardown logs
├── config.py               # .fleet.toml + §1.2 detection → FleetConfig (frozen dataclass)
├── state.py                # .fleet/state.json — workers: name→{branch,issue,tab,pane,base_sha,agent,model,started}
├── herdr.py                # thin typed wrapper over `herdr … --json`; version check
├── git.py                  # worktree add/remove/prune, trial-merge, unpushed check
├── agents/{base,claude,codex}.py     # launch argv, permission/model flags, settled states, unblock keys, capability probe
├── forges/{base,github,local}.py     # list_issues claim open_pr mark_ready evidence_comment merge
└── errors.py               # FleetError(exit_code, what, why, fix)
tests/                      # pytest; fixtures/fake_herdr.py on PATH records calls, replays canned JSON
.claude/skills/fleet/       # SKILL.md + ORCHESTRATION.md — playbook calls `fleet …`, not raw herdr
```

Immutability rule from BASE.md applies: `FleetConfig` and `WorkerState` are frozen dataclasses;
state file writes are atomic (write temp, `os.replace`).

---

## Phase 0 — Foundations (port, no new behaviour)

**Goal:** `fleet spawn|status|teardown` pass the existing `SPEC.md` contracts; `sh` scripts deleted.

Deliverables
- `pyproject.toml` (`uv`, `requires-python >= 3.11`, pytest + ruff dev-only), `fleet` entry point.
- `herdr.py` wrapper + `tests/fixtures/fake_herdr.py`: an executable on `PATH` that logs argv and
  returns canned JSON for `tab create`, `tab list`, `agent list`, `agent start`.
- Three subcommands ported 1:1, including the dry-run output lines the current tests assert.
- `errors.py`: every user-facing failure is *what / why / fix* on stderr, exit `2` for usage, `1` for runtime.
- `SPEC.md` rewritten: "Three POSIX sh scripts" → "one CLI, these subcommands", same contracts.
- GitHub remote added to this repo; CI (`uv run pytest`, `ruff check`) on PR.

Exit criteria
- `uv run pytest` green; the fake-herdr integration test shows spawn issues `git worktree add` →
  `herdr tab create` → `herdr agent start` in order.
- `git grep -l 'scripts/' -- README.md SPEC.md .claude` returns nothing.

Size: ~2 days.

---

## Phase 1 — Config resolution

**Goal:** the playbook's §1.2–§1.3 become code; nothing is hardcoded.

Deliverables
- `config.py`: detection table (lockfile → install/test), base-branch chain (gh → `origin/HEAD` → current,
  with the §1.2 non-pipe fix), `.fleet.toml` overrides, defaults for `branch_prefix`, `permission_mode`,
  `install_timeout_ms`, `issue_filter`, `agent`, `model`, `max_workers`, `shell_prompt_regex`.
- `fleet config` prints the resolved values and their source (`detected` / `.fleet.toml` / `default`).
- `spawn` takes `--base` from config; `--base` flag still overrides.
- Playbook §1.3 rewritten for `.fleet.toml`; `fleet config` referenced in SKILL.md step 1.

Exit criteria
- Test matrix: each lockfile marker resolves the documented install/test pair; a repo with no
  `origin/HEAD` and a feature branch checked out resolves base to the current branch **and** flags it.
- `.fleet.toml` with `base = "develop"` makes `fleet spawn --dry-run` emit `git worktree add … develop`.

Size: ~1.5 days.

---

## Phase 2 — State, transactions, safe teardown

**Goal:** a killed orchestrator or a failed spawn leaves nothing you have to clean up by hand.

Deliverables
- `state.py`: `.fleet/state.json` written on spawn, updated on every command, `fleet status` reconciles
  it against `herdr agent list` and reports drift (`in state, no agent` / `agent, not in state`).
- Transactional `spawn`: worktree → tab → agent, with rollback of every completed step on failure.
- `.fleet/lock` (`O_EXCL`, pid + timestamp, stale after 10 min) around spawn/teardown.
- `teardown`: refuse when the branch has unpushed commits unless `--force`; `--all`; `git worktree prune`.
- `spawn` refuses beyond `max_workers` (default 4, per §4).

Exit criteria
- Fake herdr fails at `tab create` → no worktree, no branch, no state entry, exit `1`, message names the step.
- Two concurrent `fleet spawn --name x` → exactly one succeeds; the other exits `1` with `locked by pid N`.
- `teardown` on a worktree with an unpushed commit exits `1` with the commit sha in the message.

Size: ~2 days.

---

## Phase 3 — Gates that emit exit codes, not prose

**Goal:** the two claims that currently rest on orchestrator honesty become commands.

Deliverables
- `fleet preflight` (§1.1): inside Herdr, clean tree, ≥1 commit, `herdr` version ≥ 0.9.0, integration
  for the configured agent is `current`, `$FLEET_TEST` proven green on base. Exit `1` per failure, all listed.
- `fleet brief <name> --file <brief.md>`: `herdr agent prompt … --wait --timeout`, records the
  settled state in `state.json`.
- `fleet verify [names…]` (§8.1): trial-merge every worker branch onto base in a temp worktree, run
  `$FLEET_TEST`, write `.fleet/evidence/<batch>.json` (base sha, head shas, exit code, duration) plus
  the §8.2 markdown; exit `1` if merge conflicts or tests fail, naming the offending branch.
- `SKILL.md` step 2 rewritten: steps 1–2 → `fleet preflight`, step 6 → `fleet verify`.

Exit criteria
- `preflight` on this repo with `FLEET_TEST` unset exits `1` with `set test in .fleet.toml`.
- Two fixture branches that each pass alone but conflict together → `verify` exits `1` naming both.

Size: ~2.5 days.

---

## Phase 4 — Agent and forge adapters

**Goal:** `--agent codex --model gpt-5` works; a repo with no remote can run a fleet end to end.

Deliverables
- `agents/base.py` protocol: `launch_args(model, permission_mode, allowlist) -> list[str]`,
  `settled_states`, `unblock_keys`, `probe() -> Capability{launch, lifecycle}`.
  `claude.py` (`--permission-mode`, `--model`, `--allowedTools`) and `codex.py` (sandbox/approval flags, `-m`).
- Capability probe parses `herdr integration status`; a kind with `launch` but no `lifecycle` is
  refused unless `--allow-unsupervised`, and `status` marks such workers `unsupervised`.
- `--agent`, `--model` on `spawn`; `agent`/`model` in `.fleet.toml`; per-worker override in the split
  file (Phase 5's `fleet up`).
- `forges/base.py`: `list_issues(filter)`, `claim(issue)`, `open_pr(draft=True)`, `mark_ready`,
  `post_evidence`, `merge_gate` (§8.3 rules). `github.py` via `gh --json`; `local.py` where issues
  come from the split file, "PR" is a branch, evidence goes to `.fleet/evidence/`.
- Forge auto-selected: `gh repo view` succeeds → github, else local. Overridable.

Exit criteria
- `spawn --agent kiro --dry-run` exits `1`: `kiro: launch supported, lifecycle integration missing;
  pass --allow-unsupervised`.
- `spawn --agent codex --model o4-mini --dry-run` emits `--kind codex` and the codex model flag.
- On this repo (no remote): `preflight` → `spawn` → `brief` → `verify` → `teardown` completes against
  fake herdr with forge `local`.

Size: ~3 days.

---

## Phase 5 — Operability and security

**Goal:** an operator can see what four workers are doing from one command, and the security
posture is written down and enforced.

Deliverables
- `fleet status` columns: name, agent/model, branch, issue, state, elapsed, `+/-` diff vs base, last
  activity. `--blocked` appends each blocked worker's dialog text via `herdr agent read`. `--json`.
- Transcript capture: `teardown` and `fleet logs <name>` dump `herdr agent read` to `.fleet/logs/<name>.log`.
- `fleet up <split.toml>`: spawn + brief N workers from one file (name, branch, issue, agent, model,
  scope, brief path). This is how a batch becomes reproducible.
- Dead-worker detection: `status` flags an agent gone from `herdr agent list` while state says running.
- `--max-minutes` per worker; `status` marks overrun; `fleet teardown --overrun`.
- `SECURITY.md`: threat model — N agents with `auto` permissions share the orchestrator's env, `gh`
  auth and network. Enforced: `permission_mode = "auto"` refused when `preflight` hasn't proven the
  test suite this session; allowlist from config passed to every spawn; workers' `gh` scope documented.

Exit criteria
- Fixture with one `blocked` agent → `status --blocked` shows the question text.
- `spawn` with `auto` and no preflight record in `state.json` exits `1`.

Size: ~3 days.

---

## Phase 6 — Distribution and versioning

**Goal:** another Synthesis repo adopts in one command and can tell when it's behind.

Deliverables
- `fleet init`: stamps `.gitignore` (`.worktrees/`, `.fleet/`), `core.hooksPath` + `.githooks/post-checkout`,
  `.fleet.toml` from detection, GitHub labels (`fleet-ready`, `fleet-wip`) when forge is github, copies
  `.claude/skills/fleet/` and writes `fleet_version` into `SKILL.md` frontmatter. Idempotent.
- `fleet --version`; `fleet doctor` compares installed CLI vs the skill copy's `fleet_version` and
  vs `herdr --version`.
- Install: `uv tool install git+ssh://…/MultiTest@vX.Y.Z`; tagged releases; CHANGELOG.
- Playbook §0 replaced by `fleet init`; Appendix A/B/C become "what `init` does".

Exit criteria
- Fresh empty repo: `fleet init && fleet preflight` succeeds up to the "test unproven" gate.
- Bump the CLI, don't re-init → `fleet doctor` exits `1` naming both versions.

Size: ~2 days.

---

## Dependency graph

```
P0 foundations ─► P1 config ─► P2 state/transactions ─► P3 gates ─► P4 adapters ─► P5 ops+security ─► P6 distribution
```

P4 (the agent-agnostic work) is deliberately fourth: retrofitting adapters onto a system that
cannot yet tell you what its workers are doing means building it twice.

Total: ~16 dev-days; rough, single implementer plus agents.

---

## Open questions

- [ ] **Remote for this repo.** Phase 0 CI and the github forge's own tests need one. Owner: Jason. Target: before P0 merges.
- [ ] **Codex CLI locally.** P4 needs `codex` installed and `herdr integration install codex` run to test the
  real integration, not just the fake. Owner: Jason. Target: before P4.
- [ ] **Which Claude models are valid** for `--model` validation — hardcode a list, or pass through
  and let the agent fail early with a captured message? Leaning pass-through + probe. Decide in P4 spec.
- [ ] **Does the hackathon repo track this** via `fleet init`/`doctor`, or keep its hand-copied skill?
  Decide by P6.
- [ ] **Merge authority** (§8.3 opt-in merging by the orchestrator) — keep as an explicit
  `--allow-merge` flag on `verify`, or drop it entirely for internal use? Decide in P3 spec.
