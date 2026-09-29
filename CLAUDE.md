# MultiTest

This repo builds the `fleet` CLI (Python package `fleet/`) and its skill
(`.claude/skills/fleet/`). Contract: `SPEC.md`. Plan and status: `docs/ROADMAP.md`.

- Dev: `uv sync`; run as `uv run fleet …`; test with `uv run pytest --cov`; lint with
  `uv run ruff check fleet tests && uv run ruff format --check fleet tests`.
- Tests fake Herdr with `tests/fixtures/fake_herdr.py` on `PATH`; never call the real one.
- `.claude/skills/fleet/` is the canonical, generic skill shipped in the wheel. Keep anything
  specific to this repo out of it — put it here.
- No git remote yet, so the fleet forge is `local`: workers commit to branches, nothing is pushed.

## Running a fleet on this repo

Workers edit the tool the orchestrator is running. Split by module under `fleet/`, and never put
`fleet/context.py`, `fleet/proc.py` or `fleet/errors.py` — imported by every command — in the
same batch as a command that consumes them.
