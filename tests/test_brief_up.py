def spawn(fleet, name="a1"):
    code, _, err = fleet("spawn", "--name", name, "--branch", f"feat/{name}")
    assert code == 0, err


def prompts(fleet):
    return [c for c in fleet.herdr_calls() if c[:2] == ["agent", "prompt"]]


def test_brief_sends_brief_with_scope_and_delivery_rules(ready_fleet, tmp_path):
    spawn(ready_fleet)
    brief = tmp_path / "b.md"
    brief.write_text("TASK: add a thing")
    code, out, err = ready_fleet("brief", "a1", "--file", str(brief))
    text = prompts(ready_fleet)[0][3]
    assert code == 0, err
    assert text.startswith("TASK: add a thing") and "SCOPE:" in text and "Do not push" in text


def test_brief_waits_by_default_and_records_settled_state(ready_fleet, tmp_path):
    spawn(ready_fleet)
    (tmp_path / "b.md").write_text("TASK")
    ready_fleet("brief", "a1", "--file", str(tmp_path / "b.md"))
    assert "--wait" in prompts(ready_fleet)[0]
    assert ready_fleet.state()["workers"][0]["last_settled"] == "idle"


def test_brief_unknown_worker_errors(ready_fleet, tmp_path):
    (tmp_path / "b.md").write_text("TASK")
    code, _, err = ready_fleet("brief", "nobody", "--file", str(tmp_path / "b.md"))
    assert code == 1 and "no worker named nobody" in err


def test_brief_empty_file_errors(ready_fleet, tmp_path):
    spawn(ready_fleet)
    (tmp_path / "b.md").write_text("  \n")
    assert "is empty" in ready_fleet("brief", "a1", "--file", str(tmp_path / "b.md"))[2]


SPLIT = """
[[worker]]
name = "a1"
branch = "feat/a1"
brief = "a.md"

[[worker]]
name = "b1"
branch = "feat/b1"
brief = "b.md"
model = "sonnet"
"""


def write_split(tmp_path, text=SPLIT):
    (tmp_path / "a.md").write_text("TASK A")
    (tmp_path / "b.md").write_text("TASK B")
    path = tmp_path / "split.toml"
    path.write_text(text)
    return str(path)


def test_up_spawns_and_briefs_every_worker_without_waiting(ready_fleet, tmp_path):
    code, out, err = ready_fleet("up", write_split(tmp_path))
    sent = prompts(ready_fleet)
    assert code == 0, err
    assert [w["name"] for w in ready_fleet.state()["workers"]] == ["a1", "b1"]
    assert len(sent) == 2 and not any("--wait" in c for c in sent)


def test_up_applies_per_worker_model(ready_fleet, tmp_path):
    ready_fleet("up", write_split(tmp_path))
    models = {w["name"]: w["model"] for w in ready_fleet.state()["workers"]}
    assert models == {"a1": "", "b1": "sonnet"}


def test_up_rejects_duplicate_names_before_spawning(ready_fleet, tmp_path):
    code, _, err = ready_fleet("up", write_split(tmp_path, SPLIT.replace('"b1"', '"a1"')))
    assert (
        code == 2 and "duplicate" in err and ready_fleet.herdr_calls()[-1][:2] != ["tab", "create"]
    )


def test_up_rejects_missing_brief(ready_fleet, tmp_path):
    code, _, err = ready_fleet("up", write_split(tmp_path, SPLIT.replace("b.md", "nope.md")))
    assert code == 2 and "brief not found" in err


def test_up_rejects_batch_over_max_workers(ready_fleet, tmp_path):
    ready_fleet.config('base = "main"\ntest = "true"\nmax_workers = 1\n')
    code, _, err = ready_fleet("up", write_split(tmp_path))
    assert code == 1 and "exceeds max_workers" in err


def test_up_dry_run_changes_nothing(ready_fleet, tmp_path):
    code, out, _ = ready_fleet("up", write_split(tmp_path), "--dry-run")
    assert code == 0 and out.count("git worktree add") == 2 and ready_fleet.state()["workers"] == []


MIXED = """
[[worker]]
name = "ui"
branch = "feat/ui"
brief = "a.md"
agent = "codex"
model = "o4-mini"
allowlist = []
allow_unsupervised = true

[[worker]]
name = "api"
branch = "feat/api"
brief = "b.md"
agent = "claude"
model = "opus"
"""


def test_up_mixes_agents_and_models_per_worker(ready_fleet, tmp_path):
    ready_fleet.config('base = "main"\ntest = "true"\nallowlist = ["Edit"]\n')
    ready_fleet("preflight")
    code, _, err = ready_fleet("up", write_split(tmp_path, MIXED))
    workers = {w["name"]: (w["agent"], w["model"]) for w in ready_fleet.state()["workers"]}
    assert code == 0, err
    assert workers == {"ui": ("codex", "o4-mini"), "api": ("claude", "opus")}


def test_up_per_worker_allow_unsupervised_applies_only_to_that_worker(ready_fleet, tmp_path):
    ready_fleet("up", write_split(tmp_path, MIXED))
    supervised = {w["name"]: w["supervised"] for w in ready_fleet.state()["workers"]}
    assert supervised == {"ui": False, "api": True}


def test_up_codex_without_per_worker_allow_unsupervised_is_refused(ready_fleet, tmp_path):
    code, _, err = ready_fleet(
        "up", write_split(tmp_path, MIXED.replace("allow_unsupervised = true", ""))
    )
    assert code == 1 and "herdr integration install codex" in err


def test_up_per_worker_empty_allowlist_overrides_global_for_codex(ready_fleet, tmp_path):
    ready_fleet.config('base = "main"\ntest = "true"\nallowlist = ["Edit"]\n')
    ready_fleet("preflight")
    code, _, err = ready_fleet("up", write_split(tmp_path, MIXED.replace("allowlist = []", "")))
    assert code == 2 and "codex: tool allowlist is not supported" in err


def test_up_per_worker_allowlist_reaches_claude(ready_fleet, tmp_path):
    split = MIXED.replace('model = "opus"', 'model = "opus"\nallowlist = ["Bash(git:*)"]')
    ready_fleet("up", write_split(tmp_path, split))
    start = next(c for c in ready_fleet.herdr_calls() if c[:3] == ["agent", "start", "api"])
    assert start[-2:] == ["--allowedTools", "Bash(git:*)"]


def test_up_rejects_wrong_type_in_split(ready_fleet, tmp_path):
    code, _, err = ready_fleet(
        "up",
        write_split(
            tmp_path, MIXED.replace("allow_unsupervised = true", 'allow_unsupervised = "yes"')
        ),
    )
    assert code == 2 and "`allow_unsupervised` must be bool" in err


def test_up_assign_ask_refuses_workers_without_explicit_choice(ready_fleet, tmp_path):
    ready_fleet.config('base = "main"\ntest = "true"\nassign = "ask"\n')
    ready_fleet("preflight")
    code, _, err = ready_fleet("up", write_split(tmp_path))
    assert code == 2 and "no agent/model chosen for a1, b1" in err
    assert ready_fleet.state().get("workers") == []


def test_up_assign_ask_accepts_explicit_choices_including_default_model(ready_fleet, tmp_path):
    ready_fleet.config('base = "main"\ntest = "true"\nassign = "ask"\n')
    ready_fleet("preflight")
    split = MIXED.replace('model = "opus"', 'model = ""')
    code, _, err = ready_fleet("up", write_split(tmp_path, split))
    assert code == 0, err


def test_assign_defaults_does_not_require_choices(ready_fleet, tmp_path):
    assert ready_fleet("up", write_split(tmp_path))[0] == 0


def test_invalid_assign_value_is_usage_error(fleet):
    fleet.config('assign = "sometimes"\n')
    code, _, err = fleet("config")
    assert code == 2 and "invalid assign" in err
