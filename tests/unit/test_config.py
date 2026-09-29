from pathlib import Path

import pytest

from fleet.config import detect_base, detect_toolchain, load_config, with_overrides
from fleet.errors import UsageError
from tests.unit.fakes import FakeRunner, fail, ok

NO_REMOTE = {
    ("gh",): fail("no git remotes found"),
    ("git", "symbolic-ref"): fail("not a symbolic ref"),
    ("git", "rev-parse", "--abbrev-ref", "HEAD"): ok("feature/x\n"),
}


def test_detect_base_prefers_gh_default_branch(tmp_path: Path):
    runner = FakeRunner({("gh",): ok("develop\n")})
    assert detect_base(tmp_path, runner) == ("develop", "gh")


def test_detect_base_strips_origin_prefix_from_origin_head(tmp_path: Path):
    runner = FakeRunner({("gh",): fail(), ("git", "symbolic-ref"): ok("origin/trunk\n")})
    assert detect_base(tmp_path, runner) == ("trunk", "origin/HEAD")


def test_detect_base_falls_back_to_current_branch_when_origin_head_unset(tmp_path: Path):
    # The §1.2 pipe bug: a failing symbolic-ref must still reach the third source.
    assert detect_base(tmp_path, FakeRunner(NO_REMOTE)) == ("feature/x", "current-branch")


def test_detect_base_on_detached_head_is_unresolved(tmp_path: Path):
    runner = FakeRunner({**NO_REMOTE, ("git", "rev-parse", "--abbrev-ref", "HEAD"): ok("HEAD\n")})
    assert detect_base(tmp_path, runner) == ("", "unresolved")


@pytest.mark.parametrize(
    ("marker", "install", "test"),
    [
        ("pnpm-lock.yaml", "pnpm install --frozen-lockfile", "pnpm test"),
        ("package-lock.json", "npm ci", "npm test"),
        ("uv.lock", "uv sync --frozen", "uv run pytest"),
        ("go.mod", "go mod download", "go test ./..."),
        ("Cargo.toml", "cargo fetch", "cargo test"),
        ("App.csproj", "dotnet restore", "dotnet test"),
        ("pkg.cabal", "cabal build --only-dependencies --enable-tests", "cabal test"),
    ],
)
def test_detect_toolchain_maps_marker_to_commands(tmp_path: Path, marker, install, test):
    (tmp_path / marker).write_text("")
    assert detect_toolchain(tmp_path)[1:] == (install, test)


def test_detect_toolchain_without_marker_returns_none(tmp_path: Path):
    assert detect_toolchain(tmp_path) is None


def test_load_config_without_marker_leaves_test_unset(tmp_path: Path):
    cfg = load_config(tmp_path, FakeRunner(NO_REMOTE))
    assert (cfg.test, cfg.install) == ("", ":")


def test_load_config_flags_current_branch_base_for_confirmation(tmp_path: Path):
    assert load_config(tmp_path, FakeRunner(NO_REMOTE)).base_needs_confirmation


def test_load_config_toml_overrides_detection_and_records_source(tmp_path: Path):
    (tmp_path / "uv.lock").write_text("")
    (tmp_path / ".fleet.toml").write_text('base = "develop"\ntest = "make test"\n')
    cfg = load_config(tmp_path, FakeRunner(NO_REMOTE))
    assert (cfg.base, cfg.test, cfg.install, cfg.sources["test"]) == (
        "develop",
        "make test",
        "uv sync --frozen",
        ".fleet.toml",
    )


def test_load_config_toml_override_skips_base_detection(tmp_path: Path):
    (tmp_path / ".fleet.toml").write_text('base = "develop"\n')
    runner = FakeRunner(NO_REMOTE)
    load_config(tmp_path, runner)
    assert not any(c[0] == "gh" for c in runner.calls)


def test_load_config_unknown_key_is_usage_error(tmp_path: Path):
    (tmp_path / ".fleet.toml").write_text('tset = "typo"\n')
    with pytest.raises(UsageError, match="unknown key.*tset"):
        load_config(tmp_path, FakeRunner(NO_REMOTE))


def test_load_config_wrong_type_is_usage_error(tmp_path: Path):
    (tmp_path / ".fleet.toml").write_text('max_workers = "four"\n')
    with pytest.raises(UsageError, match="max_workers.*int"):
        load_config(tmp_path, FakeRunner(NO_REMOTE))


def test_load_config_bool_for_int_is_usage_error(tmp_path: Path):
    (tmp_path / ".fleet.toml").write_text("max_workers = true\n")
    with pytest.raises(UsageError):
        load_config(tmp_path, FakeRunner(NO_REMOTE))


def test_load_config_invalid_toml_is_usage_error(tmp_path: Path):
    (tmp_path / ".fleet.toml").write_text("base = \n")
    with pytest.raises(UsageError, match="invalid"):
        load_config(tmp_path, FakeRunner(NO_REMOTE))


def test_load_config_invalid_permission_mode_is_usage_error(tmp_path: Path):
    (tmp_path / ".fleet.toml").write_text('permission_mode = "bypassPermissions"\n')
    with pytest.raises(UsageError, match="permission_mode"):
        load_config(tmp_path, FakeRunner(NO_REMOTE))


def test_load_config_allowlist_becomes_tuple(tmp_path: Path):
    (tmp_path / ".fleet.toml").write_text('allowlist = ["Bash(git:*)"]\n')
    assert load_config(tmp_path, FakeRunner(NO_REMOTE)).allowlist == ("Bash(git:*)",)


def test_with_overrides_ignores_none_and_returns_new_object(tmp_path: Path):
    cfg = load_config(tmp_path, FakeRunner(NO_REMOTE))
    new = with_overrides(cfg, model="opus", agent=None)
    assert (new.model, new.agent, cfg.model, new.sources["model"]) == ("opus", "claude", "", "flag")


def test_load_config_default_shell_prompt_regex_matches_common_prompts(tmp_path: Path):
    import re

    cfg = load_config(tmp_path, FakeRunner(NO_REMOTE))
    pattern = re.compile(cfg.shell_prompt_regex)
    assert all(
        pattern.search(prompt)
        for prompt in ("user@host repo %", "user@host repo % ", "bash-5.2$ ", "~/repo ❯ ")
    )
    assert not pattern.search("uv sync --frozen\nResolved 12 packages")


def test_load_config_invalid_shell_prompt_regex_is_usage_error(tmp_path: Path):
    (tmp_path / ".fleet.toml").write_text('shell_prompt_regex = "[unclosed"\n')
    with pytest.raises(UsageError, match="shell_prompt_regex"):
        load_config(tmp_path, FakeRunner(NO_REMOTE))
