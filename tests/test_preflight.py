from tests.conftest import git


def test_preflight_passes_and_records_base_sha(fleet):
    fleet.config('base = "main"\ntest = "true"\n')
    code, out, _ = fleet("preflight")
    assert code == 0 and fleet.state()["preflight"]["base_sha"] == git(
        fleet.repo, "rev-parse", "main"
    )


def test_preflight_without_test_tells_user_to_set_it(fleet):
    fleet.config('base = "main"\n')
    code, out, _ = fleet("preflight")
    assert code == 1 and "set `test" in out


def test_preflight_red_base_fails(fleet):
    fleet.config('base = "main"\ntest = "exit 3"\n')
    code, out, _ = fleet("preflight")
    assert code == 1 and "FAIL test passes on base" in out


def test_preflight_reports_every_failure_not_just_first(fleet):
    fleet.config('base = "main"\n')
    (fleet.repo / "dirty.txt").write_text("x")
    fleet.env(FAKE_HERDR_INTEGRATIONS="claude=not installed")
    _, out, _ = fleet("preflight")
    assert out.count("FAIL") == 3  # dirty tree, no integration, no test


def test_preflight_off_base_fails(fleet):
    fleet.config('base = "main"\ntest = "true"\n')
    git(fleet.repo, "switch", "-qc", "other")
    (fleet.repo / "f").write_text("x")
    git(fleet.repo, "add", "f")
    git(fleet.repo, "commit", "-qm", "diverge")
    code, out, _ = fleet("preflight")
    assert code == 1 and "on base `main`" in out


def test_preflight_old_herdr_fails(fleet):
    fleet.config('base = "main"\ntest = "true"\n')
    fleet.env(FAKE_HERDR_VERSION="herdr 0.8.9")
    code, out, _ = fleet("preflight")
    assert code == 1 and "found 0.8.9" in out


def test_preflight_does_not_run_tests_when_other_checks_fail(fleet):
    fleet.config('base = "main"\ntest = "touch ran"\n')
    (fleet.repo / "dirty.txt").write_text("x")
    fleet("preflight")
    assert not (fleet.repo / "ran").exists()
