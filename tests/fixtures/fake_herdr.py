#!/usr/bin/env python3
"""Stand-in for `herdr` 0.9.0. Keeps tabs/agents in $FAKE_HERDR_STATE, logs argv to $FAKE_HERDR_LOG.

Failure injection: $FAKE_HERDR_FAIL="tab create" makes that subcommand exit 1.
Integrations: $FAKE_HERDR_INTEGRATIONS="claude=current (v9),codex=not installed".
Agent status override: $FAKE_HERDR_STATUS="blocked".
Shell readiness: a pane is "at a shell prompt" once `pane wait-output` has been called on it
$FAKE_HERDR_SHELL_AFTER_WAITS times (default 1); `agent start` on a not-ready pane exits 1 with
herdr's `agent_pane_busy` error.
"""

import json
import os
import sys
from pathlib import Path

STATE = Path(os.environ["FAKE_HERDR_STATE"])
LOG = Path(os.environ["FAKE_HERDR_LOG"])


def load():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {"tabs": [], "agents": [], "n": 0, "waits": {}}


def save(s):
    STATE.write_text(json.dumps(s))


def emit(kind, result):
    print(json.dumps({"id": f"cli:{kind}", "result": result}))


def main(argv):
    with LOG.open("a") as fh:
        fh.write(json.dumps(argv) + "\n")
    cmd = " ".join(argv[:2])
    if os.environ.get("FAKE_HERDR_FAIL") == cmd:
        print(f"fake failure: {cmd}", file=sys.stderr)
        return 1
    s = load()
    ws = os.environ.get("HERDR_WORKSPACE_ID", "w1")
    if argv[:1] == ["--version"]:
        print(os.environ.get("FAKE_HERDR_VERSION", "herdr 0.9.0"))
    elif cmd == "integration status":
        raw = os.environ.get("FAKE_HERDR_INTEGRATIONS", "claude=current (v9),codex=not installed")
        for pair in raw.split(","):
            k, _, v = pair.partition("=")
            print(f"{k}: {v} (/home/x/.{k}/hook.sh)")
    elif cmd == "tab create":
        s["n"] += 1
        opts = dict(zip(argv[2::2], argv[3::2], strict=False))
        tab = {
            "tab_id": f"{ws}:t{s['n']}",
            "label": opts.get("--label"),
            "workspace_id": ws,
            "cwd": opts.get("--cwd"),
        }
        s["tabs"].append(tab)
        save(s)
        emit("tab:create", {"tab": tab, "root_pane": {"pane_id": f"{ws}:p{s['n']}"}})
    elif cmd == "tab list":
        emit("tab:list", {"tabs": s["tabs"]})
    elif cmd == "tab close":
        before = len(s["tabs"])
        s["tabs"] = [t for t in s["tabs"] if t["tab_id"] != argv[2]]
        pane = argv[2].replace(":t", ":p")
        s["agents"] = [a for a in s["agents"] if a["pane_id"] != pane]
        save(s)
        if len(s["tabs"]) == before:
            print("no such tab", file=sys.stderr)
            return 1
    elif cmd == "pane wait-output":
        waits = s.setdefault("waits", {})
        waits[argv[2]] = waits.get(argv[2], 0) + 1
        save(s)
        emit("pane:wait-output", {"matched": True})
    elif cmd == "agent start":
        name, kind, pane = argv[2], argv[argv.index("--kind") + 1], argv[argv.index("--pane") + 1]
        needed = int(os.environ.get("FAKE_HERDR_SHELL_AFTER_WAITS", "1"))
        if s.get("waits", {}).get(pane, 0) < needed:
            err = {
                "code": "agent_pane_busy",
                "message": f"agent target pane {pane} is not an available shell",
            }
            print(json.dumps({"error": err, "id": "cli:agent:start"}), file=sys.stderr)
            return 1
        tab = next(t for t in s["tabs"] if t["tab_id"] == pane.replace(":p", ":t"))
        s["agents"].append(
            {
                "name": name,
                "agent": kind,
                "pane_id": pane,
                "workspace_id": ws,
                "cwd": tab["cwd"],
                "agent_status": "idle",
            }
        )
        save(s)
    elif cmd == "agent list":
        status = os.environ.get("FAKE_HERDR_STATUS")
        agents = [{**a, "agent_status": status or a["agent_status"]} for a in s["agents"]]
        emit("agent:list", {"agents": agents})
    elif cmd == "agent get":
        a = next((a for a in s["agents"] if argv[2] in (a["name"], a["pane_id"])), None)
        if a is None:
            return 1
        emit(
            "agent:get",
            {"agent": {**a, "agent_status": os.environ.get("FAKE_HERDR_STATUS", "idle")}},
        )
    elif cmd == "agent prompt":
        pass
    elif cmd == "agent read":
        print(f"transcript of {argv[2]}\nWould you like to proceed? 1. Yes 2. No")
    else:
        print(f"fake herdr: unhandled {argv}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
