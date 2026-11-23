"""End-to-end process ownership through the Factory verification CLI."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


FACTORY = Path(__file__).resolve().parents[1] / "factory"


def wait_for(predicate, seconds=5):
    deadline = time.monotonic() + seconds
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Process failed to reach the expected state")
        time.sleep(0.025)


class CommandSupervisionTests(unittest.TestCase):
    def test_signalled_coordinator_cleans_up_shell_and_descendant(self):
        for signum in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signum=signum), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                repo = root / "app"
                repo.mkdir()
                # The parent shell and background Python writer share the check's process group.
                script = repo / "verify.sh"
                script.write_text(
                    "set -eu\n"
                    '"$1" -c \'import pathlib,sys,time; p=pathlib.Path(sys.argv[1]); '
                    '(p/"started").touch(); time.sleep(1.4); (p/"survived").touch()\' "$2" &\n'
                    "wait\n"
                )
                contract = root / "contract.json"
                contract.write_text(
                    json.dumps(
                        [
                            {
                                "id": "test",
                                "expect": "completes",
                                "argv": ["sh", "verify.sh", sys.executable, str(root)],
                            }
                        ]
                    )
                )
                env = dict(os.environ, FACTORY_STATE_DIR=str(root / "state"))
                start = subprocess.check_output(
                    [
                        FACTORY,
                        "start",
                        "--repo",
                        repo,
                        "--task",
                        "check lifecycle",
                        "--contract",
                        contract,
                    ],
                    env=env,
                    text=True,
                )
                state = json.loads(start)
                process = subprocess.Popen([FACTORY, "check", state["run"]], env=env)
                supervisor = None
                try:
                    wait_for((root / "started").exists)
                    (receipt,) = Path(state["state"]).glob("*.log.process.json")
                    supervisor = json.loads(receipt.read_text())["supervisor_pid"]
                    os.kill(supervisor, signal.SIGSTOP)
                    process.send_signal(signum)
                    process.wait(timeout=4)
                    # Hold the watchdog momentarily to exercise the window
                    # between coordinator death and the watchdog seeing EOF.
                    attempt = subprocess.run(
                        [FACTORY, "status", state["run"]],
                        env=env,
                        text=True,
                        capture_output=True,
                        timeout=3,
                    )
                    self.assertEqual(attempt.returncode, 2)
                    self.assertIn("Another Factory operation owns", attempt.stderr)
                    os.kill(supervisor, signal.SIGCONT)
                    supervisor = None
                    wait_for(
                        lambda: json.loads(receipt.read_text())["status"] == "BLOCKED"
                    )
                    detail = json.loads(receipt.read_text())
                    self.assertIn("interrupted", detail["reason"])
                    self.assertTrue(detail["pgid"] > 0)
                    time.sleep(1.5)
                    self.assertFalse((root / "survived").exists())
                finally:
                    if supervisor:
                        try:
                            os.kill(supervisor, signal.SIGCONT)
                        except ProcessLookupError:
                            pass
                    process.kill()
                    process.wait(timeout=3)

    def test_git_checkpoint_stage_preserves_literal_binary_pathspec(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            repo, spool = root / "repo", root / "spool"
            repo.mkdir()
            spool.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            odd_name = "-cost[2] ☃\nquote'%.txt"
            (repo / odd_name).write_text("value")
            other_name = "unrelated"
            (repo / other_name).write_text("user work")
            python = """from pathlib import Path
import sys
from rounds import stage
from workspace import workspace_lock

repo = Path(sys.argv[1])
with workspace_lock(repo):
    stage(repo, [sys.argv[2]])
"""
            subprocess.run(
                [sys.executable, "-B", "-c", python, str(repo), odd_name],
                env=dict(
                    os.environ,
                    PYTHONPATH=str(FACTORY.resolve().parent),
                    TMPDIR=str(spool),
                    FACTORY_STATE_DIR=str(root / "state"),
                ),
                check=True,
            )
            staged = subprocess.check_output(["git", "-C", str(repo), "ls-files", "-z"])
            self.assertEqual(staged, os.fsencode(odd_name) + b"\0")
            self.assertEqual(list(spool.iterdir()), [])

    def test_kill_while_git_hook_runs_stops_checkpoint_before_release(self):
        for hook in ("pre-commit", "pre-push"):
            with self.subTest(hook=hook), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                repo, upstream = root / "app", root / "upstream.git"
                repo.mkdir()
                env = dict(
                    os.environ,
                    PATH=str(root) + os.pathsep + os.environ["PATH"],
                    FACTORY_STATE_DIR=str(root / "state"),
                    HOOK_DIR=str(root),
                )

                def git(*args, cwd=repo):
                    return subprocess.check_output(
                        ["git", *args], cwd=cwd, text=True, env=env
                    ).strip()

                git("init", "-qb", "trunk")
                git("config", "user.name", "test")
                git("config", "user.email", "test@example.invalid")
                git("config", "core.hooksPath", str(repo / ".git/hooks"))
                git("commit", "--allow-empty", "-qm", "base")
                git("switch", "-qc", "feature")
                (repo / "calc.py").write_text("value = 1 + 1")
                git("add", ".")
                git("commit", "-qm", "candidate")
                git("init", "--bare", "-q", str(upstream))
                git("remote", "add", "fixture", str(upstream))
                original = git("rev-parse", "HEAD")
                # Normal provider CLI boundary with a deterministic one-edit response.
                fake = root / "claude"
                fake.write_text(
                    f"#!{sys.executable}\n"
                    + """
import json, sys
from pathlib import Path
args = sys.argv
fresh = "--session-id" in args
session = args[args.index("--session-id" if fresh else "--resume")+1]
if fresh:
    Path("calc.py").write_text("value = 2")
print(json.dumps(dict(subtype="success", session_id=session, modelUsage={"claude-opus-fixture": {}},
                      result="Simplified." if fresh else "STATUS: VERIFIED")))
"""
                )
                fake.chmod(0o700)
                script = repo / ".git/hooks" / hook
                script.parent.mkdir(exist_ok=True)
                script.write_text(
                    '#!/bin/sh\nset -eu\ntouch "$HOOK_DIR/started"\nsleep 3\ntouch "$HOOK_DIR/survived"\n'
                )
                script.chmod(0o700)
                args = [
                    FACTORY,
                    "simplify",
                    "--repo",
                    repo,
                    "--base",
                    "trunk",
                    "--task",
                    "preserve value",
                    "--check",
                    "python3 -B -c 'from calc import value; assert value == 2'",
                ]
                if hook == "pre-push":
                    args += ["--push", "fixture"]
                process = subprocess.Popen(
                    args, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
                )
                try:
                    wait_for(
                        lambda: (
                            (root / "started").exists() or process.poll() is not None
                        ),
                        seconds=20,
                    )
                    if process.poll() is not None:
                        self.fail(
                            f"Workflow stopped before Git hook: {process.communicate()!r}"
                        )
                    (record,) = (root / "state/simplify").glob("*/state.json")
                    run = json.loads(record.read_text())["id"]
                    release = [FACTORY, "simplify", "--resume", run, "--release"]
                    active = subprocess.run(
                        release, env=env, capture_output=True, text=True, timeout=3
                    )
                    self.assertNotEqual(active.returncode, 0)
                    self.assertIn(
                        "Another Factory operation owns", active.stdout + active.stderr
                    )
                    process.kill()
                    process.communicate(timeout=3)

                    def released():
                        result = subprocess.run(
                            release, env=env, capture_output=True, text=True, timeout=3
                        )
                        return json.loads(result.stdout).get("status") == "released"

                    wait_for(released, seconds=4)
                    time.sleep(3.1)
                    self.assertFalse((root / "survived").exists())
                    if hook == "pre-commit":
                        self.assertEqual(git("rev-parse", "HEAD"), original)
                    else:
                        self.assertNotEqual(git("rev-parse", "HEAD"), original)
                        self.assertEqual(
                            git("for-each-ref", "refs/heads/feature", cwd=upstream), ""
                        )
                finally:
                    process.kill()
                    process.communicate(timeout=4)


if __name__ == "__main__":
    unittest.main()
