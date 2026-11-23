import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"
sys.path.insert(0, str(SCRIPTS))
from harness import HarnessError, run_turn  # noqa: E402


# An actual subprocess exercises stdin, executable lookup, process groups,
# CLI argument separation and the persisted failure/success boundary.
FAKE = """#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time, uuid
args=sys.argv[1:]
def option(key): return args[args.index(key)+1]
text=sys.stdin.read()
root=pathlib.Path(os.environ['HARNESS_FIXTURE'])
case=os.environ.get('HARNESS_CASE')
item={'argv': args, 'prompt': text, 'cwd': os.getcwd()}
if '--append-system-prompt-file' in args:
    item['context']=pathlib.Path(option('--append-system-prompt-file')).read_text()
(root/'observed.json').write_text(json.dumps(item))
if case=='slow-success': time.sleep(1.2)
if case=='slow':
    subprocess.Popen([sys.executable, '-c',
        "import time,pathlib; time.sleep(1.4); pathlib.Path('surviving-child').touch()"])
    time.sleep(30)
if pathlib.Path(sys.argv[0]).name=='claude':
    sid=option('--resume' if '--resume' in args else '--session-id')
    response={'type':'result','subtype':'success','is_error':False,'session_id':sid,
              'result':text, 'modelUsage':{'claude-opus-fixture':{}}}
    if case=='auth': response.update(is_error=True,result='Failed to authenticate')
    if case=='denied': response['permission_denials']=[{'tool_name':'Edit'}]
    if case=='swapped': response['session_id']=str(uuid.uuid4())
    if case=='empty': response['result']=''
    if case=='model': response['modelUsage']={'claude-sonnet-fixture':{}}
    print(json.dumps(response))
else:
    sid=option('resume') if 'resume' in args else str(uuid.uuid4())
    print(json.dumps({'type':'thread.started','thread_id':sid}))
    print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}))
    if case!='partial': print(json.dumps({'type':'turn.completed'}))
sys.exit(9 if case=='exit' else 0)
"""


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        for cli in ("codex", "claude"):
            executable = self.root / cli
            executable.write_text(FAKE)
            executable.chmod(0o700)
        environ = patch.dict(
            os.environ,
            {
                "PATH": f"{self.root}:{os.environ['PATH']}",
                "HARNESS_FIXTURE": str(self.root),
                "HARNESS_CASE": "",
            },
        )
        environ.start()
        self.addCleanup(environ.stop)

    def turn(self, provider="claude", prompt="hello", **kwargs):
        directory = self.root / str(uuid.uuid4())
        self.output = directory
        return run_turn(
            provider, repo=self.repo, prompt=prompt, output_dir=directory, **kwargs
        )

    def observed(self):
        return json.loads((self.root / "observed.json").read_text())

    def receipt(self):
        return json.loads((self.output / "receipt.json").read_text())

    def test_exact_prompt_and_separate_context(self):
        prompt = (
            SCRIPTS.parent / "references" / "reconsider-from-first-principles.v1.txt"
        )
        payload = prompt.read_bytes()
        self.assertEqual(
            hashlib.sha256(payload).hexdigest(),
            "cc4605f2ca257e313a5e7ee05e619a224a933c80986b798cbbf30a0a81956acc",
        )
        response = self.turn(
            prompt=payload.decode(),
            context="Frozen base and acceptance checks",
            edit=True,
            local_shell=True,
        )
        observed = self.observed()
        self.assertEqual(observed["prompt"].encode(), payload)
        self.assertEqual(observed["context"], "Frozen base and acceptance checks")
        self.assertNotIn(observed["context"], observed["prompt"])
        self.assertEqual(response["prompt_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(response["model_reported"], "claude-opus-fixture")
        argv = observed["argv"]
        self.assertIn("Read,Glob,Grep,Edit,Write,Bash", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "auto")
        self.assertNotIn("--allowedTools", argv)
        settings = json.loads(argv[argv.index("--settings") + 1])
        self.assertEqual(settings["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertTrue(settings["sandbox"]["enabled"])
        self.assertFalse(settings["sandbox"]["allowUnsandboxedCommands"])
        self.assertIn("Bash(git push *)", settings["permissions"]["deny"])
        self.assertIn("--restricted", observed["argv"])
        self.assertEqual(response, self.receipt())

    def test_sessions_are_fresh_unless_explicitly_resumed(self):
        for provider in ("claude", "codex"):
            first = self.turn(provider)
            self.assertNotEqual(first["session_id"], self.turn(provider)["session_id"])
            resumed = self.turn(provider, session_id=first["session_id"])
            self.assertEqual(first["session_id"], resumed["session_id"])
            args = self.observed()["argv"]
            if provider == "claude":
                self.assertIn("--resume", args)
                self.assertIn("Read,Glob,Grep", args)
                self.assertEqual(args[args.index("--permission-mode") + 1], "dontAsk")
                self.assertFalse(any("Bash" in arg for arg in args))
            else:
                self.assertIn("read-only", args)
                self.assertIn("--ignore-user-config", args)
                self.assertIn("resume", args)
            self.assertNotIn("--last", args)

    def test_bad_results_cannot_acquire_success_receipt(self):
        for case in ("swapped", "denied", "empty", "auth", "exit", "model", "partial"):
            with (
                self.subTest(case=case),
                patch.dict(os.environ, {"HARNESS_CASE": case}),
            ):
                with self.assertRaises(HarnessError):
                    self.turn("codex" if case == "partial" else "claude")
                receipt = self.receipt()
                self.assertEqual(receipt["status"], "failed")
                self.assertNotIn("text", receipt)

    def test_quiet_agent_finishes_without_a_deadline(self):
        with patch.dict(os.environ, {"HARNESS_CASE": "slow-success"}):
            result = self.turn()
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["elapsed_seconds"], 1)
        self.assertNotIn("timeout", result)

    def test_crashing_coordinator_ends_edit_attempt(self):
        directory = self.root / "abandoned"
        source = (
            "from harness import run_turn; import sys; "
            "run_turn('claude',repo=sys.argv[1],prompt='hello',edit=True,"
            "output_dir=sys.argv[2])"
        )
        with patch.dict(
            os.environ, {"HARNESS_CASE": "slow", "PYTHONPATH": str(SCRIPTS)}
        ):
            caller = subprocess.Popen(
                [sys.executable, "-c", source, str(self.repo), str(directory)]
            )
            try:
                marker = self.root / "observed.json"
                deadline = time.monotonic() + 6
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(marker.exists())
                os.kill(caller.pid, signal.SIGKILL)
            finally:
                caller.kill()
                caller.wait(timeout=5)
        receipt = directory / "receipt.json"
        deadline = time.monotonic() + 4
        while (
            json.loads(receipt.read_text())["status"] == "running"
            and time.monotonic() < deadline
        ):
            time.sleep(0.03)
        self.assertEqual(json.loads(receipt.read_text())["status"], "failed")
        time.sleep(1.5)
        self.assertFalse((self.repo / "surviving-child").exists())

    def test_directory_cannot_be_reused_or_pollute_repo(self):
        self.turn()
        for path in [self.output, self.repo / "inside"]:
            with self.assertRaises(HarnessError):
                run_turn("claude", repo=self.repo, prompt="hello", output_dir=path)


if __name__ == "__main__":
    unittest.main()
