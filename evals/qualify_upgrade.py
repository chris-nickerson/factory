"""Exercise a real older Factory install and its records across an upgrade."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
PROVIDER = """#!/usr/bin/env python3
import json, os, sys, uuid
from pathlib import Path
args = sys.argv[1:]
prompt = sys.stdin.read()
with Path(os.environ["FACTORY_QUALIFICATION_CALLS"]).open("a") as log:
    log.write(Path(sys.argv[0]).name + "\\n")
proposal = "Keep the local contract.\\nSTATUS: RESOLUTION_PROPOSED"
accept = "ACCEPT: turn_001_a.md\\nSTATUS: CONFIRMED"
if Path(sys.argv[0]).name == "claude":
    key = "--resume" if "--resume" in args else "--session-id"
    print(json.dumps(dict(
        subtype="success", session_id=args[args.index(key) + 1],
        result=accept if key == "--resume" else proposal,
        modelUsage={"claude-opus-fixture": {}},
    )))
else:
    resume = "resume" in args
    session = args[args.index("resume") + 1] if resume else str(uuid.uuid4())
    for event in (
        dict(type="thread.started", thread_id=session),
        dict(type="item.completed", item=dict(type="agent_message", text=accept if resume else proposal)),
        dict(type="turn.completed"),
    ):
        print(json.dumps(event))
"""


def qualify(baseline, home):
    prefix = home / ".local"
    cli = prefix / "bin/factory"
    skill = home / ".agents/skills/software-factory"
    calls = home / "calls"
    tools = home / "fixture-tools"
    tools.mkdir()
    for name in ("codex", "claude"):
        executable = tools / name
        executable.write_text(PROVIDER)
        executable.chmod(0o700)
    env = {
        **os.environ,
        "HOME": str(home),
        "FACTORY_STATE_DIR": str(home / "state"),
        "FACTORY_QUALIFICATION_CALLS": str(calls),
        "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
    }

    def run(*argv, expected=0):
        result = subprocess.run(argv, env=env, text=True, capture_output=True)
        if result.returncode != expected:
            raise RuntimeError(f"{argv} exited {result.returncode}: {result.stdout} {result.stderr}")
        return json.loads(result.stdout)

    target = home / "project"
    target.mkdir()
    contract = home / "contract.json"
    source = target / "answer.txt"
    source.write_text("ready\n")
    contract.write_text(json.dumps([
        dict(id="ready", expect="answer is ready", argv=["grep", "-Fx", "ready", "answer.txt"])
    ]))

    def check_with_installed_cli():
        started = run(cli, "start", "--repo", target, "--task", "Check readiness", "--contract", contract)
        return run(cli, "check", started["run"])

    old_install = run(sys.executable, baseline / "install.py")
    old_entry = (skill / "SKILL.md").read_bytes()
    old_evidence = check_with_installed_cli()
    old_dialogue = run(cli, "consensus", "design", "--repo", target, "--task", "Choose a contract")
    if old_dialogue["status"] != "confirmed":
        raise RuntimeError(old_dialogue)
    before_upgrade = calls.read_bytes()

    new_install = run(sys.executable, ROOT / "install.py")
    if old_install["release"] == new_install["release"]:
        raise RuntimeError("Choose a baseline with a different installable payload")
    replayed = run(cli, "consensus", "resume", old_dialogue["run"])
    if replayed != old_dialogue or calls.read_bytes() != before_upgrade:
        raise RuntimeError("Resuming the old decision changed its result or dispatched a provider")
    if run(cli, "status", old_evidence["run"]) != old_evidence:
        raise RuntimeError("The upgrade changed the old evidence result")
    source.write_text("changed\n")
    stale = run(cli, "status", old_evidence["run"], expected=2)
    if stale["claims"]["ready"]["status"] != "STALE":
        raise RuntimeError(stale)
    source.write_text("ready\n")
    new_evidence = check_with_installed_cli()

    rollback = run(sys.executable, ROOT / "install.py", "--rollback")
    if rollback["release"] != old_install["release"] or (skill / "SKILL.md").read_bytes() != old_entry:
        raise RuntimeError("Rollback did not restore the old release and skill entry")
    if run(cli, "status", new_evidence["run"]) != new_evidence:
        raise RuntimeError("The rollback executable could not read candidate-written evidence")
    print("Verified old evidence, old consensus resume without redispatch, and installed rollback.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path, help="Checkout of an earlier Factory revision")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="factory-qualify-upgrade-") as directory:
        qualify(args.baseline.resolve(strict=True), Path(directory).resolve())


if __name__ == "__main__":
    main()
