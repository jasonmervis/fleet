# fleet

Run parallel coding agents (Claude Code, Codex) on in-repo git worktrees, driven through
[Herdr](https://herdr.dev). One CLI enforces the playbook: preflight gates, all-or-nothing spawns,
supervision, trial-merge verification, safe teardown. A bundled Claude Code **skill** teaches an
orchestrator session how to drive it.

- Playbook: [.claude/skills/fleet/ORCHESTRATION.md](.claude/skills/fleet/ORCHESTRATION.md)
- Skill (role router): [.claude/skills/fleet/SKILL.md](.claude/skills/fleet/SKILL.md)
- Contract: [SPEC.md](SPEC.md) · Security: [SECURITY.md](SECURITY.md) · Plan: [docs/ROADMAP.md](docs/ROADMAP.md)

## Prerequisites

| Tool | Why |
|---|---|
| [Herdr](https://herdr.dev) ≥ 0.9.0 | The terminal backend. Every worker runs in its own Herdr tab. |
| [Claude Code](https://docs.claude.com/en/docs/claude-code) | The orchestrator and (by default) the workers. Codex is also supported. |
| Python ≥ 3.11 and [uv](https://docs.astral.sh/uv/) | `fleet` is a stdlib-only Python CLI; `uv tool` installs it. |
| `git` | Workers live in `.worktrees/<name>` inside your repo. |
| `gh` (optional) | Only if you source work from GitHub Issues. With no remote, `fleet` uses its `local` forge. |

## Install the CLI

```sh
uv tool install git+https://github.com/jasonmervis/fleet@v0.1.1
fleet --version
```

Use `git+ssh://git@github.com/jasonmervis/fleet@v0.1.1` if you clone over SSH. To upgrade later,
re-run the install with the new tag, then `fleet init` in each adopting repo to refresh the skill.

## Use the skill in your repo

`fleet init` copies the skill into your repo, so Claude Code picks it up automatically from
`.claude/skills/fleet/`.

```sh
cd /path/to/your-repo        # a git repo with at least one commit
fleet init                   # idempotent: .gitignore, .fleet.toml, .githooks, skill
fleet doctor                 # CLI, skill stamp and Herdr versions agree
fleet config                 # review detected base/install/test commands
```

Then:

1. **Set `test` in `.fleet.toml`** if `init` could not detect it. `fleet` refuses to spawn workers
   in `auto` permission mode without a command that proves work is done.
2. **Commit** `.fleet.toml`, `.githooks/`, `.claude/skills/fleet/` and, on GitHub,
   `.github/workflows/fleet-claim.yml`.
3. **Open the repo in Herdr** and start Claude Code in tab 1. That session is the orchestrator.
4. **Ask it to run work in parallel.** The skill triggers on phrases like
   "spawn workers", "run these issues in parallel", "set up the fleet",
   "work issues 12-15 in parallel". It will run `fleet preflight`, propose a split, ask for
   sign-off, then `fleet up` and supervise with `fleet status`.
5. **You merge.** `fleet verify` trial-merges every branch and runs the tests on the combined
   tree, but `fleet` never merges. Afterwards, `fleet teardown --all`.

The skill decides its own role: a session whose cwd is under `.worktrees/` is a worker and
will not orchestrate. See [SKILL.md](.claude/skills/fleet/SKILL.md) for the rules each role follows.

## CLI reference

```sh
fleet config                 # resolved settings and where each came from
fleet preflight              # must pass before auto-permission spawns
fleet spawn --name i42 --branch feat/42 [--agent claude --model opus]
fleet brief i42 --file briefs/i42.md
fleet up split.toml          # spawn + brief a reviewed batch (all-or-nothing per worker)
fleet status [--blocked] [--json]
fleet logs i42               # save a worker's transcript to .fleet/logs/
fleet verify [--mark-ready]  # trial-merge the batch, run tests on the combined tree
fleet teardown --name i42 | --all | --overrun   # branches are kept
fleet init | fleet doctor
```

Every command supports `--dry-run`, which prints what it would do and needs no Herdr.

## Configuration

`.fleet.toml` is committed and read by every command. `fleet config` prints the resolved values.

```toml
base = "main"                  # branch workers fork from
install = "uv sync --frozen"   # run in each new worktree
test = "uv run pytest"         # REQUIRED before spawning
agent = "claude"               # claude | codex
permission_mode = "auto"       # auto | edits | readonly
max_workers = 4
assign = "defaults"            # defaults | ask (human picks agent/model per worker)
```

A `split.toml` describes one batch: one `[[worker]]` per worktree with `name`, `branch`, `brief`,
and optional `issue`, `agent`, `model`. See [SKILL.md](.claude/skills/fleet/SKILL.md) for a full example.

## Develop

```sh
git clone https://github.com/jasonmervis/fleet.git && cd fleet
uv sync
uv run fleet --help
uv run pytest --cov          # Herdr is faked in tests; no Herdr needed
uv run ruff check fleet tests && uv run ruff format --check fleet tests
```

To try a local build in another repo: `uv tool install --editable .` then `fleet init` there.
Bump `__version__` in `fleet/__init__.py` and tag `v<version>` to release; `fleet doctor`
compares the stamp in each repo's skill against the installed CLI.
