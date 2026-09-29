# fleet

This repo builds the `fleet` CLI (Python package `fleet/`) and its skill
(`.claude/skills/fleet/`). Contract: `SPEC.md`. Plan and status: `docs/ROADMAP.md`.

- Dev: `uv sync`; run as `uv run fleet …`; test with `uv run pytest --cov`; lint with
  `uv run ruff check fleet tests && uv run ruff format --check fleet tests`.
- Tests fake Herdr with `tests/fixtures/fake_herdr.py` on `PATH`; never call the real one.
- `.claude/skills/fleet/` is the canonical, generic skill shipped in the wheel. Keep anything
  specific to this repo out of it — put it here.
- Remote: `github.com/jasonmervis/fleet` (public). Forge is pinned to `local` in `.fleet.toml` because the
  active `gh` account is `jasonmervis-synth`, and with a public repo `auto` would pick `github` and act as the
  wrong user. Workers commit to branches, nothing is pushed. Unpin only while `gh` is switched to `jasonmervis`.
- `main` is protected by GitHub rulesets: PRs only, linear history, both `ci` jobs required. Tags are immutable.
  `.githooks/pre-push` mirrors this locally and also blocks tag pushes; `FLEET_ALLOW_PUSH=1 git push` overrides
  it for a release tag.

## Running a fleet on this repo

Workers edit the tool the orchestrator is running. Split by module under `fleet/`, and never put
`fleet/context.py`, `fleet/proc.py` or `fleet/errors.py` — imported by every command — in the
same batch as a command that consumes them.
