import fcntl
import hashlib
import json
import os
from pathlib import Path
import select
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
item={'argv': args, 'prompt': text, 'cwd': os.getcwd(), 'tmpdir': os.environ.get('TMPDIR')}
if '--append-system-prompt-file' in args:
    item['context']=pathlib.Path(option('--append-system-prompt-file')).read_text()
(root/'observed.json').write_text(json.dumps(item))
if case=='slow-success': time.sleep(1.2)
if case=='slow':
    child = '''import fcntl, os
from pathlib import Path
root = Path(os.environ["HARNESS_FIXTURE"])
with (root / "grandchild").open("wb", buffering=0) as channel:
    with (root / "release-child").open() as release:
        channel.write(b"x")
        fcntl.flock(release, fcntl.LOCK_SH)
'''
    subprocess.run([sys.executable, '-c', child], check=True)
if pathlib.Path(sys.argv[0]).name=='claude':
    sid=option('--resume' if '--resume' in args else '--session-id')
    response={'type':'result','subtype':'success','is_error':False,'session_id':sid,
              'result':text, 'modelUsage':{'claude-opus-fixture':{}}}
    if case=='auth': response.update(is_error=True,result='Failed to authenticate')
    if case=='denied': response['permission_denials']=[{'tool_name':'Edit'}]
    if case=='swapped': response['session_id']=str(uuid.uuid4())
    if case=='empty': response['result']=''
    if case=='model': response['modelUsage']={'claude-sonnet-fixture':{}}
    if case=='helper': response['modelUsage']={'claude-opus-fixture':{}, 'claude-haiku-fixture':{}}
    print(json.dumps(response))
else:
    sid=option('resume') if 'resume' in args else str(uuid.uuid4())
    print(json.dumps({'type':'thread.started','thread_id':sid}))
    print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}))
    if case=='rejected':
        print(json.dumps({'type':'turn.failed','error':{'message':'The model is not supported'}}))
    elif case!='partial': print(json.dumps({'type':'turn.completed'}))
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
        if provider == "claude":
            kwargs.setdefault("model", "opus")
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

    def test_receipt_says_how_far_model_identity_was_established(self):
        self.assertEqual(self.turn()["model_identity"], "matched")
        self.assertEqual(self.turn(model="opus[1m]")["model_identity"], "matched")
        from harness import model_identity

        bracketed = {"model_requested": "claude-opus-4[1m]"}
        self.assertEqual(
            model_identity(bracketed, {"model_usage": ["claude-opus-4[1m]"]}), "matched"
        )
        pinned = self.turn(model="claude-opus-fixture-20260101")
        self.assertEqual(pinned["model_identity"], "indeterminate")
        self.assertEqual(self.turn(selector="standard")["model_selector"], "standard")
        unrequested = self.turn(model=None)
        self.assertEqual(unrequested["model_identity"], "unrequested")
        self.assertEqual(unrequested["model_reported"], "claude-opus-fixture")
        self.assertNotIn("--model", self.observed()["argv"])
        with (
            patch.dict(os.environ, {"HARNESS_CASE": "model"}),
            self.assertRaisesRegex(HarnessError, "not the requested"),
        ):
            self.turn(model="claude-sonnet-fixtur")
        self.assertEqual(self.receipt()["model_reported"], "claude-sonnet-fixture")
        with patch.dict(os.environ, {"HARNESS_CASE": "helper"}):
            self.assertEqual(self.turn()["model_identity"], "indeterminate")
        silent = self.turn("codex", model="gpt-fixture")
        self.assertEqual(
            (silent["model_identity"], silent["model_reported"]), ("unreported", None)
        )
        with (
            patch.dict(os.environ, {"HARNESS_CASE": "rejected"}),
            self.assertRaisesRegex(HarnessError, "The model is not supported"),
        ):
            self.turn("codex", model="retired")

    def test_codex_edits_inside_the_worktree_and_a_private_scratch(self):
        first = self.turn("codex", edit=True, local_shell=True)
        observed = self.observed()
        argv = observed["argv"]
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        for setting in (
            "sandbox_workspace_write.network_access=false",
            "sandbox_workspace_write.exclude_slash_tmp=true",
            "sandbox_workspace_write.exclude_tmpdir_env_var=true",
        ):
            self.assertIn(setting, argv)
        scratch = Path(observed["tmpdir"])
        self.assertEqual(scratch, self.output.resolve() / "tmp")
        self.assertIn(
            "sandbox_workspace_write.writable_roots=" + json.dumps([str(scratch)]), argv
        )
        self.assertFalse(scratch.is_relative_to(self.repo))
        self.turn("codex", session_id=first["session_id"])
        argv = self.observed()["argv"]
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")
        self.assertFalse(any("workspace_write" in arg for arg in argv))

    def test_codex_reads_instructions_too_long_for_an_argument_from_their_file(self):
        self.turn("codex", context="short instructions")
        self.assertIn("short instructions", " ".join(self.observed()["argv"]))
        for long_context in ("branch delta line\n" * 20_000, "\x01" * 30_000):
            self.turn("codex", context=long_context)
            argv = self.observed()["argv"]
            self.assertLess(max(len(arg.encode()) for arg in argv), 60_000)
            instructions = next(arg for arg in argv if "developer_instructions" in arg)
            self.assertIn(str(self.output.resolve() / "context.txt"), instructions)
            self.assertEqual((self.output / "context.txt").read_text(), long_context)

    def test_turn_needs_a_harness_that_declares_it(self):
        for kwargs, missing in (
            (dict(edit=True), "file_only_edit"),
            (dict(local_shell=True), "editing turn"),
        ):
            with self.subTest(kwargs), self.assertRaisesRegex(HarnessError, missing):
                self.turn("codex", **kwargs)
        with self.assertRaisesRegex(HarnessError, "Unknown harness"):
            self.turn("gemini")
        self.assertFalse(self.output.exists())

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
        fifo = self.root / "grandchild"
        release = self.enterContext((self.root / "release-child").open("w"))
        fcntl.flock(release, fcntl.LOCK_EX)
        os.mkfifo(fifo)
        reader = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        self.addCleanup(os.close, reader)

        def read_byte():
            ready, _, _ = select.select([reader], [], [], 6)
            self.assertTrue(ready, "Timed out waiting for the grandchild's pipe")
            return os.read(reader, 1)

        caller = subprocess.Popen(
            [sys.executable, "-c", source, str(self.repo), str(directory)],
            env={
                **os.environ,
                "HARNESS_CASE": "slow",
                "PYTHONPATH": str(SCRIPTS),
            },
        )
        try:
            with fifo.open("wb", buffering=0):
                self.assertEqual(read_byte(), b"x")
            os.kill(caller.pid, signal.SIGKILL)
            self.assertEqual(read_byte(), b"")
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

    def test_directory_cannot_be_reused_or_pollute_repo(self):
        self.turn()
        for path in [self.output, self.repo / "inside"]:
            with self.assertRaises(HarnessError):
                run_turn("claude", repo=self.repo, prompt="hello", output_dir=path)


if __name__ == "__main__":
    unittest.main()
