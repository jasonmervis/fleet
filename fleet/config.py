"""Resolve per-repo settings: detection (playbook §1.2), then `.fleet.toml` overrides (§1.3)."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

from fleet.errors import UsageError
from fleet.proc import Runner

CONFIG_FILE = ".fleet.toml"
PERMISSION_MODES = ("auto", "edits", "readonly")
FORGES = ("auto", "github", "local")
ASSIGN_MODES = ("defaults", "ask")
# Matches the tail of a ready shell prompt: `%`, `$`, or `❯` (starship/p10k), trailing space or not.
DEFAULT_SHELL_PROMPT_REGEX = "[$%❯] *$"

# First matching marker wins. Globs are matched against the repo root only.
TOOLCHAINS: tuple[tuple[str, str, str], ...] = (
    ("pnpm-lock.yaml", "pnpm install --frozen-lockfile", "pnpm test"),
    ("yarn.lock", "yarn install --immutable", "yarn test"),
    ("bun.lockb", "bun install --frozen-lockfile", "bun test"),
    ("bun.lock", "bun install --frozen-lockfile", "bun test"),
    ("package-lock.json", "npm ci", "npm test"),
    ("uv.lock", "uv sync --frozen", "uv run pytest"),
    ("poetry.lock", "poetry install --sync", "poetry run pytest"),
    ("requirements.txt", "pip install -r requirements.txt", "pytest"),
    ("go.mod", "go mod download", "go test ./..."),
    ("Cargo.toml", "cargo fetch", "cargo test"),
    ("*.sln", "dotnet restore", "dotnet test"),
    ("*.csproj", "dotnet restore", "dotnet test"),
    ("pubspec.yaml", "flutter pub get", "flutter test"),
    ("cabal.project", "cabal build --only-dependencies --enable-tests", "cabal test"),
    ("*.cabal", "cabal build --only-dependencies --enable-tests", "cabal test"),
    ("Gemfile.lock", "bundle install", "bundle exec rspec"),
    ("pom.xml", "mvn -B -q dependency:go-offline", "mvn -B test"),
    ("build.gradle", "./gradlew --no-daemon dependencies", "./gradlew --no-daemon test"),
    ("build.gradle.kts", "./gradlew --no-daemon dependencies", "./gradlew --no-daemon test"),
)

# key -> (type, default)
_SCHEMA: dict[str, tuple[type, object]] = {
    "base": (str, ""),
    "install": (str, ""),
    "test": (str, ""),
    "branch_prefix": (str, "feat"),
    "permission_mode": (str, "auto"),
    "install_timeout_ms": (int, 300_000),
    "issue_filter": (str, "--label fleet-ready --state open"),
    "agent": (str, "claude"),
    "model": (str, ""),
    "max_workers": (int, 4),
    "max_minutes": (int, 120),
    "allowlist": (list, []),
    "forge": (str, "auto"),
    "assign": (str, "defaults"),
    "shell_prompt_regex": (str, DEFAULT_SHELL_PROMPT_REGEX),
}


@dataclass(frozen=True)
class FleetConfig:
    base: str
    install: str
    test: str
    branch_prefix: str
    permission_mode: str
    install_timeout_ms: int
    issue_filter: str
    agent: str
    model: str
    max_workers: int
    max_minutes: int
    allowlist: tuple[str, ...]
    forge: str
    assign: str
    shell_prompt_regex: str
    sources: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def base_needs_confirmation(self) -> bool:
        return self.sources.get("base") == "current-branch"


def detect_base(root: Path, reader: Runner) -> tuple[str, str]:
    """Return (branch, source). Each source is tried independently — never through a pipe."""
    gh = reader.run(
        ["gh", "repo", "view", "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"],
        cwd=root,
        check=False,
    )
    if gh.ok and gh.stdout.strip():
        return gh.stdout.strip(), "gh"
    head = reader.run(
        ["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=root, check=False
    )
    if head.ok and head.stdout.strip():
        return head.stdout.strip().removeprefix("origin/"), "origin/HEAD"
    cur = reader.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root, check=False)
    if cur.ok and cur.stdout.strip() and cur.stdout.strip() != "HEAD":
        return cur.stdout.strip(), "current-branch"
    return "", "unresolved"


def detect_toolchain(root: Path) -> tuple[str, str, str] | None:
    """Return (marker, install, test) for the first marker present, else None."""
    for marker, install, test in TOOLCHAINS:
        if any(root.glob(marker)):
            return marker, install, test
    return None


def read_overrides(root: Path) -> dict[str, object]:
    path = root / CONFIG_FILE
    if not path.is_file():
        return {}
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise UsageError(f"invalid {CONFIG_FILE}: {exc}", fix=f"fix the syntax in {path}") from exc
    unknown = sorted(set(data) - set(_SCHEMA))
    if unknown:
        raise UsageError(
            f"unknown key in {CONFIG_FILE}: {', '.join(unknown)}",
            fix=f"valid keys: {', '.join(_SCHEMA)}",
        )
    for key, value in data.items():
        expected = _SCHEMA[key][0]
        if not isinstance(value, expected) or isinstance(value, bool):
            raise UsageError(
                f"{CONFIG_FILE}: `{key}` must be {expected.__name__}, got {type(value).__name__}"
            )
        if expected is list and not all(isinstance(v, str) for v in value):
            raise UsageError(f"{CONFIG_FILE}: `{key}` must be a list of strings")
    return data


def _validate(cfg: FleetConfig) -> FleetConfig:
    if cfg.permission_mode not in PERMISSION_MODES:
        raise UsageError(
            f"invalid permission_mode: {cfg.permission_mode}",
            fix=f"use one of: {', '.join(PERMISSION_MODES)}",
        )
    if cfg.forge not in FORGES:
        raise UsageError(f"invalid forge: {cfg.forge}", fix=f"use one of: {', '.join(FORGES)}")
    if cfg.assign not in ASSIGN_MODES:
        raise UsageError(
            f"invalid assign: {cfg.assign}", fix=f"use one of: {', '.join(ASSIGN_MODES)}"
        )
    if cfg.max_workers < 1:
        raise UsageError("max_workers must be at least 1")
    try:
        re.compile(cfg.shell_prompt_regex)
    except re.error as exc:
        raise UsageError(
            f"invalid shell_prompt_regex: {cfg.shell_prompt_regex!r} ({exc})",
            fix=f"use a regex for the end of your prompt, e.g. {DEFAULT_SHELL_PROMPT_REGEX!r}",
        ) from exc
    return cfg


def load_config(root: Path, reader: Runner) -> FleetConfig:
    values: dict[str, object] = {k: default for k, (_, default) in _SCHEMA.items()}
    sources = {k: "default" for k in _SCHEMA}

    overrides = read_overrides(root)

    if "base" not in overrides:
        values["base"], sources["base"] = detect_base(root, reader)
    chain = detect_toolchain(root)
    if chain:
        marker, values["install"], values["test"] = chain
        sources["install"] = sources["test"] = f"detected ({marker})"
    else:
        values["install"], sources["install"] = ":", "detected (no marker)"

    for key, value in overrides.items():
        values[key] = value
        sources[key] = CONFIG_FILE

    values["allowlist"] = tuple(values["allowlist"])  # type: ignore[arg-type]
    return _validate(FleetConfig(**values, sources=sources))  # type: ignore[arg-type]


def with_overrides(cfg: FleetConfig, **flags: object) -> FleetConfig:
    """Apply command-line flags that were actually given (None means not given)."""
    given = {k: v for k, v in flags.items() if v is not None}
    if not given:
        return cfg
    sources = {**cfg.sources, **{k: "flag" for k in given}}
    return _validate(replace(cfg, **given, sources=sources))
