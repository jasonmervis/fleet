# MultiTest — `fleet`

Run parallel coding agents (Claude, Codex) on in-repo git worktrees, driven through
[Herdr](https://herdr.dev). One CLI enforces the playbook: preflight gates, all-or-nothing spawns,
supervision, trial-merge verification, safe teardown.

- Playbook: [.claude/skills/fleet/ORCHESTRATION.md](.claude/skills/fleet/ORCHESTRATION.md)
- Skill (role router): [.claude/skills/fleet/SKILL.md](.claude/skills/fleet/SKILL.md)
- Contract: [SPEC.md](SPEC.md) · Security: [SECURITY.md](SECURITY.md) · Plan: [docs/ROADMAP.md](docs/ROADMAP.md)

## Install

```sh
uv tool install git+ssh://git@github.com/<org>/MultiTest@v0.1.1   # adopting repos
cd your-repo && fleet init && fleet doctor
```

## Use

```sh
fleet config                 # resolved settings and where each came from
fleet preflight              # must pass before auto-permission spawns
fleet up split.toml          # spawn + brief a reviewed batch
fleet status [--blocked]     # who is working, blocked, gone, overrun
fleet verify [--mark-ready]  # trial-merge the batch, run tests on the combined tree
fleet teardown --all         # after a human merges; branches are kept
```

## Develop

```sh
uv sync
uv run pytest --cov          # Herdr is faked in tests; no Herdr needed
uv run ruff check fleet tests && uv run ruff format --check fleet tests
```
