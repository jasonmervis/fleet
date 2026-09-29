import tomllib

from fleet import __version__
from fleet.skill_files import SKILL_REL, read_stamp
from tests.conftest import git


def test_init_installs_skill_config_hook_and_ignores(fleet):
    (fleet.repo / ".gitignore").write_text("node_modules/\n")
    code, out, err = fleet("init")
    ignores = (fleet.repo / ".gitignore").read_text().splitlines()
    assert code == 0, err
    assert ignores == ["node_modules/", ".worktrees/", ".fleet/"]
    assert (fleet.repo / ".githooks" / "post-checkout").stat().st_mode & 0o111
    assert git(fleet.repo, "config", "core.hooksPath") == ".githooks"
    assert read_stamp((fleet.repo / SKILL_REL / "SKILL.md").read_text()) == __version__
    assert (fleet.repo / SKILL_REL / "ORCHESTRATION.md").is_file()


def test_init_writes_valid_toml_from_detection(fleet):
    (fleet.repo / "go.mod").write_text("module x\n")
    fleet("init")
    cfg = tomllib.loads((fleet.repo / ".fleet.toml").read_text())
    assert (cfg["install"], cfg["test"]) == ("go mod download", "go test ./...")


def test_init_without_test_tells_user_to_set_it(fleet):
    assert "set `test` before spawning" in fleet("init")[1]


def test_init_never_overwrites_fleet_toml(fleet):
    (fleet.repo / ".fleet.toml").write_text('test = "mine"\n')
    fleet("init")
    assert (fleet.repo / ".fleet.toml").read_text() == 'test = "mine"\n'


def test_init_is_idempotent(fleet):
    fleet("init")
    snapshot = (fleet.repo / ".gitignore").read_text()
    code, _, _ = fleet("init")
    assert code == 0 and (fleet.repo / ".gitignore").read_text() == snapshot


def test_init_leaves_foreign_hooks_path_alone(fleet):
    git(fleet.repo, "config", "core.hooksPath", ".husky")
    _, _, err = fleet("init")
    assert git(fleet.repo, "config", "core.hooksPath") == ".husky" and "not changed" in err


def test_init_dry_run_changes_nothing(fleet):
    fleet("init", "--dry-run")
    assert not (fleet.repo / ".fleet.toml").exists()


def test_doctor_passes_after_init(fleet):
    fleet("init")
    code, out, err = fleet("doctor")
    assert code == 0, out + err


def test_doctor_fails_on_stale_skill_naming_both_versions(fleet):
    fleet("init")
    skill = fleet.repo / SKILL_REL / "SKILL.md"
    skill.write_text(skill.read_text().replace(f'"{__version__}"', '"0.0.1"'))
    code, out, _ = fleet("doctor")
    assert code == 1 and "skill is 0.0.1, CLI is " + __version__ in out


def test_doctor_fails_without_skill(fleet):
    code, out, _ = fleet("doctor")
    assert code == 1 and "run `fleet init`" in out


def test_doctor_fails_on_old_herdr(fleet):
    fleet("init")
    fleet.env(FAKE_HERDR_VERSION="herdr 0.8.0")
    code, out, _ = fleet("doctor")
    assert code == 1 and "below 0.9.0" in out


def test_config_prints_values_with_sources(fleet):
    fleet.config('test = "make test"\n')
    _, out, _ = fleet("config")
    line = next(line for line in out.splitlines() if line.startswith("test "))
    assert "make test" in line and line.rstrip().endswith(".fleet.toml")


def test_config_shows_shell_prompt_regex_with_source(fleet):
    fleet.config('shell_prompt_regex = "> $"\n')
    _, out, _ = fleet("config")
    line = next(line for line in out.splitlines() if line.startswith("shell_prompt_regex"))
    assert "> $" in line and line.rstrip().endswith(".fleet.toml")


def test_config_warns_when_base_is_just_current_branch(fleet):
    assert "confirm it" in fleet("config")[2]


def test_init_github_forge_writes_claim_workflow(fleet):
    fleet.config('forge = "github"\n')
    fleet("init")
    assert (fleet.repo / ".github" / "workflows" / "fleet-claim.yml").is_file()


def test_init_local_forge_writes_no_workflow(fleet):
    fleet("init")
    assert not (fleet.repo / ".github").exists()
