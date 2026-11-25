import argparse
import contextlib
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "skills/software-factory/scripts")
)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_machine import use_machine
import dialogue
import harness
from harness import HarnessError


OPEN = "The two observations discriminate different causes.\nSTATUS: OPEN"
PROPOSE_A = "Require an explicit unit and test old inputs.\nSTATUS: RESOLUTION_PROPOSED"
PROPOSE_B = "Keep the public API, document seconds, cover 0 and 59.\nSTATUS: RESOLUTION_PROPOSED"
ACCEPT_A = "ACCEPT: turn_001_a.md\nSTATUS: CONFIRMED"
ACCEPT_B = "ACCEPT: turn_002_b.md\nSTATUS: CONFIRMED"


class DialogueTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.repo = self.root / "checkout"
        self.repo.mkdir()
        self.data = self.root / "state"
        env = patch.dict(
            os.environ,
            {
                "FACTORY_STATE_DIR": str(self.data),
                "XDG_CONFIG_HOME": str(self.root / "config"),
            },
        )
        env.start()
        self.addCleanup(env.stop)
        use_machine(self, "codex", "claude")
        self.calls, self.script = [], []
        adapter = patch.object(dialogue, "run_turn", side_effect=self.turn)
        adapter.start()
        self.addCleanup(adapter.stop)
        self.parser = argparse.ArgumentParser()
        dialogue.register(self.parser.add_subparsers(required=True))

    def turn(self, provider, **call):
        self.calls.append((provider, call))
        folder = call["output_dir"]
        folder.mkdir()
        answer = self.script.pop(0)
        if isinstance(answer, Exception):
            (folder / "receipt.json").write_text('{"status": "failed"}')
            raise answer
        record = {
            "status": "success",
            "provider": provider,
            "text": answer,
            "session_id": call["session_id"] or f"initial-{provider}",
            "prompt_sha256": dialogue._digest(call["prompt"]),
            "context_sha256": dialogue._digest(call["context"]),
            "repo": str(call["repo"]),
        }
        (folder / "receipt.json").write_text(json.dumps(record))
        return record

    def invoke(self, *argv):
        args = self.parser.parse_args(["consensus", *argv])
        with (
            contextlib.redirect_stdout(io.StringIO()) as out,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = args.func(args)
        return code, json.loads(out.getvalue())

    def start(self, *extra):
        return self.invoke(
            "design",
            "--task",
            "Investigate the time unit",
            "--repo",
            str(self.repo),
            *extra,
        )

    def test_independent_openings_and_b_proposal_then_final_ack(self):
        self.script = [OPEN, "secret independent B report", PROPOSE_B, ACCEPT_B]
        code, out = self.start()
        self.assertEqual(0, code)
        self.assertEqual("turn_002_b.md", out["proposal"])
        self.assertEqual(PROPOSE_B.splitlines()[0], out["decision"])
        self.assertEqual(
            ["codex", "claude", "claude", "codex"], [p for p, _ in self.calls]
        )
        self.assertFalse(any(call["edit"] for _, call in self.calls))
        self.assertNotIn(OPEN, self.calls[1][1]["prompt"])
        self.assertIn("secret independent B report", self.calls[3][1]["prompt"])
        self.assertEqual(
            [None, None, "initial-claude", "initial-codex"],
            [call["session_id"] for _, call in self.calls],
        )
        self.assertEqual((0, out), self.invoke("resume", out["run"]))
        self.assertEqual(4, len(self.calls))

    def test_b_accepts_a_requires_a_final_confirmation(self):
        self.script = [PROPOSE_A, OPEN, ACCEPT_A, ACCEPT_A]
        code, out = self.start("--exchanges", "1")
        self.assertEqual((0, "turn_001_a.md", 3), (code, out["proposal"], out["turns"]))
        self.assertEqual(
            PROPOSE_A + "\n", (Path(out["artifacts"]) / "turn_001_a.md").read_text()
        )

    def test_participants_follow_flags_and_one_harness_is_reported(self):
        self.script = [OPEN, OPEN, PROPOSE_B, ACCEPT_B]
        code, out = self.start("--a", "claude:frontier", "--b", "codex")
        self.assertEqual(0, code)
        self.assertEqual(
            ["claude", "codex", "codex", "claude"], [p for p, _ in self.calls]
        )
        self.assertEqual(
            ["fable", "gpt-9.2-sol"], [c["model"] for _, c in self.calls[:2]]
        )
        self.assertEqual(out["reductions"], [])
        self.calls.clear()
        self.script = [OPEN, OPEN, PROPOSE_B, ACCEPT_B]
        code, out = self.start("--a", "claude", "--b", "claude")
        self.assertEqual(0, code)
        self.assertEqual({"claude"}, {p for p, _ in self.calls})
        self.assertEqual([None, None], [c["session_id"] for _, c in self.calls[:2]])
        self.assertIn("Same-model consensus", out["reductions"][0])
        self.assertEqual(out, self.invoke("status", out["run"])[1])

    def test_run_saved_before_participants_resumes_with_its_original_pair(self):
        self.script = [OPEN, HarnessError("offline")]
        code, out = self.start("--gpt-model", "gpt-9.1-astra", "--opus-model", "opus")
        self.assertEqual((2, "blocked"), (code, out["status"]))
        path = Path(out["artifacts"]) / "run.json"
        meta = json.loads(path.read_text())
        self.assertEqual(meta["models"], {"a": "gpt-9.1-astra", "b": "opus"})
        del meta["participants"]
        meta["version"] = 2
        path.write_text(json.dumps(meta))
        use_machine(self)
        self.script = [OPEN, PROPOSE_B, ACCEPT_B]
        code, resumed = self.invoke("resume", out["run"])
        self.assertEqual((0, "confirmed"), (code, resumed["status"]))
        self.assertNotIn("participants", resumed)
        self.assertEqual(
            [("codex", "gpt-9.1-astra"), ("claude", "opus"), ("claude", "opus"), ("claude", "opus"), ("codex", "gpt-9.1-astra")],
            [(p, c["model"]) for p, c in self.calls],
        )

    def test_wrong_ref_and_quoted_status_not_confirmation(self):
        self.script = [
            OPEN,
            OPEN,
            PROPOSE_B,
            ACCEPT_A,
            "> " + ACCEPT_B.replace("\n", "\n> "),
        ]
        code, out = self.start()
        self.assertEqual((2, "blocked", 2), (code, out["status"], out["turns"]))
        self.assertEqual(out, self.invoke("status", out["run"])[1])

    def test_crlf_transcript_survives_interruption_between_markdown_and_json(self):
        proposal = PROPOSE_B.replace("\n", "\r\n") + "\r\n"
        self.script = [OPEN, OPEN, proposal, ACCEPT_B]
        publish = dialogue._publish

        def interrupt(path, data):
            if path.name == "turn_002_b.json":
                raise KeyboardInterrupt
            publish(path, data)

        with (
            patch.object(dialogue, "_publish", side_effect=interrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.start()
        run = next((self.data / "consensus").iterdir())
        transcript = run / "turn_002_b.md"
        self.assertEqual(proposal.encode(), transcript.read_bytes())
        code, report = self.invoke("resume", run.name)
        self.assertEqual((0, "confirmed"), (code, report["status"]))
        self.assertEqual(report, self.invoke("status", run.name)[1])
        self.assertEqual(proposal.encode(), transcript.read_bytes())

    def test_unicode_line_separators_keep_diagnostic_disposition(self):
        proposal = "Missing timer trace.\u2028Probe both time units.\u2028DISPOSITION: INCONCLUSIVE  \u2028STATUS: RESOLUTION_PROPOSED"
        self.script = [OPEN, OPEN, proposal, ACCEPT_B]
        code, report = self.invoke(
            "diagnosis", "--repo", str(self.repo), "--task", "Find the cause"
        )
        self.assertEqual((0, "INCONCLUSIVE"), (code, report["disposition"]))
        self.assertEqual(
            "Missing timer trace.\u2028Probe both time units.", report["decision"]
        )
        transcript = Path(report["artifacts"]) / "turn_002_b.md"
        self.assertEqual((proposal + "\n").encode(), transcript.read_bytes())
        self.assertEqual(report, self.invoke("resume", report["run"])[1])

    def test_accepted_decision_preserves_indentation_hard_breaks_and_line_endings(self):
        body = "\tdef keep():  \r\n    return 1  \n\u2028  last line  "
        for mode in ("design", "diagnosis"):
            with self.subTest(mode=mode):
                disposition = (
                    "DISPOSITION: INCONCLUSIVE  \u2028" if mode == "diagnosis" else ""
                )
                proposal = (
                    body
                    + "\r\n"
                    + disposition
                    + "STATUS: RESOLUTION_PROPOSED  \r\n\r\n"
                )
                self.script = [OPEN, OPEN, proposal, ACCEPT_B]
                code, report = self.invoke(
                    mode, "--repo", str(self.repo), "--task", "Evaluate this decision"
                )
                self.assertEqual(0, code)
                self.assertEqual(body, report["decision"])

    def test_inconclusive_diagnosis_carries_distinct_disposition(self):
        self.script = [
            OPEN,
            OPEN,
            "Need timer arguments.\nDISPOSITION: INCONCLUSIVE  \nSTATUS: RESOLUTION_PROPOSED",
            ACCEPT_B,
        ]
        code, report = self.invoke(
            "diagnosis", "--repo", str(self.repo), "--task", "Find the actual cause"
        )
        self.assertEqual(
            (0, "confirmed", "INCONCLUSIVE"),
            (code, report["status"], report["disposition"]),
        )
        self.assertEqual("Need timer arguments.", report["decision"])

    def test_diagnosis_without_disposition_cannot_complete(self):
        self.script = [OPEN, OPEN, PROPOSE_B, PROPOSE_B]
        code, report = self.invoke(
            "diagnosis", "--repo", str(self.repo), "--task", "Find the actual cause"
        )
        self.assertEqual((2, "blocked", 1), (code, report["status"], report["turns"]))

    def test_budget_expiry_cannot_convert_proposal_to_consensus(self):
        self.script = [PROPOSE_A, OPEN, PROPOSE_B, PROPOSE_A]
        code, out = self.start("--exchanges", "1")
        self.assertEqual((2, "unresolved", 3), (code, out["status"], out["turns"]))
        self.assertNotIn("proposal", out)
        self.assertEqual((code, out), self.invoke("resume", out["run"]))

    def test_auth_failure_resume_reuses_successful_opening(self):
        self.script = [OPEN, HarnessError("authentication unavailable")]
        code, out = self.start()
        self.assertEqual("blocked", out["status"])
        self.script = [OPEN, PROPOSE_B, ACCEPT_B]
        code, resumed = self.invoke("resume", out["run"])
        self.assertEqual((0, "confirmed"), (code, resumed["status"]))
        self.assertEqual(
            1, sum(p == "codex" and c["session_id"] is None for p, c in self.calls)
        )

    def test_expired_legacy_run_reuses_completed_opening_without_agent_timers(self):
        self.script = [OPEN, HarnessError("Command timed out after 150s")]
        code, out = self.start("--timeout", "150", "--deadline", "720")
        self.assertEqual((code, out["status"]), (2, "blocked"))
        path = Path(out["artifacts"]) / "run.json"
        meta = json.loads(path.read_text())
        self.assertNotIn("expires", meta)
        self.assertNotIn("timeout", meta)
        meta.update(version=1, expires=1, timeout=150)
        path.write_text(json.dumps(meta))
        self.script = [OPEN, PROPOSE_B, ACCEPT_B]
        code, resumed = self.invoke("resume", out["run"])
        self.assertEqual((code, resumed["status"]), (0, "confirmed"))
        self.assertEqual(
            [p for p, c in self.calls if c["session_id"] is None],
            ["codex", "claude", "claude"],
        )
        self.assertTrue(all("timeout" not in c for _, c in self.calls))

    def test_resume_preserves_prelaunch_attempt_and_dispatches_in_new_directory(self):
        with (
            patch.object(dialogue, "run_turn", harness.run_turn),
            patch.object(harness, "_save", side_effect=KeyboardInterrupt),
            patch.object(harness, "run_worker") as launch,
            self.assertRaises(KeyboardInterrupt),
        ):
            self.start()
        launch.assert_not_called()
        run = next((self.data / "consensus").iterdir())
        orphan = run / "opening-a/attempt-0001/call"
        prompt = (orphan / "prompt.txt").read_bytes()
        self.assertFalse((orphan / "receipt.json").exists())
        self.script = [OPEN, OPEN, PROPOSE_B, ACCEPT_B]
        code, result = self.invoke("resume", run.name)
        self.assertEqual((0, "confirmed"), (code, result["status"]))
        self.assertEqual(prompt, (orphan / "prompt.txt").read_bytes())
        self.assertFalse((orphan / "receipt.json").exists())
        self.assertEqual(
            self.calls[0][1]["output_dir"],
            (run / "opening-a/attempt-0002/call").resolve(),
        )
        self.assertEqual(4, len(self.calls))

    def test_crash_between_starting_receipt_and_supervisor_launch_recovers(self):
        with (
            patch.object(dialogue, "run_turn", harness.run_turn),
            patch.object(harness, "run_worker", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.start()
        run = next((self.data / "consensus").iterdir())
        artifact = run / "opening-a/attempt-0001/call/receipt.json"
        original = artifact.read_bytes()
        self.assertEqual("starting", json.loads(original)["status"])
        self.script = [OPEN, OPEN, PROPOSE_B, ACCEPT_B]
        code, result = self.invoke("resume", run.name)
        self.assertEqual((0, "confirmed"), (code, result["status"]))
        self.assertEqual(original, artifact.read_bytes())

    def test_supervisor_dies_before_provider_group_publication(self):
        # Kill the actual watchdog after forking the gated child and before
        # publishing its PGID. The previous starting receipt survives intact.
        worker = """
import os, signal, sys
from pathlib import Path
import harness

publish = harness._save
def kill_before_group_publication(path, record):
    if record["status"] == "running":
        os.kill(os.getpid(), signal.SIGKILL)
    publish(path, record)
harness._save = kill_before_group_publication
harness._command = lambda *args: [sys.executable, "-c",
    "from pathlib import Path; import sys; Path(sys.argv[1]).touch()", sys.argv[2]]
harness._supervise(Path(sys.argv[1]))
"""
        provider_marker = self.root / "provider-launched"

        def interrupt(script, directory, timeout):
            from workspace import workspace_lock_fds

            env = dict(os.environ, PYTHONPATH=str(Path(script).parent))
            with subprocess.Popen(
                [
                    sys.executable,
                    "-B",
                    "-c",
                    worker,
                    str(directory),
                    str(provider_marker),
                ],
                env=env,
                stdin=subprocess.PIPE,
                start_new_session=True,
                pass_fds=workspace_lock_fds(),
            ) as child:
                self.assertEqual(child.wait(timeout=6), -signal.SIGKILL)

        with (
            patch.object(dialogue, "run_turn", harness.run_turn),
            patch.object(harness, "run_worker", interrupt),
        ):
            _, blocked = self.start()
        directory = Path(blocked["artifacts"])
        receipt = directory / "opening-a/attempt-0001/call/receipt.json"
        original = receipt.read_bytes()
        info = json.loads(original)
        self.assertEqual(info["status"], "starting")
        self.assertGreater(info["supervisor_pid"], 0)
        self.assertNotIn("pgid", info)
        self.script = [OPEN, OPEN, PROPOSE_B, ACCEPT_B]
        code, report = self.invoke("resume", blocked["run"])
        self.assertEqual((code, report["status"]), (0, "confirmed"), report)
        self.assertFalse(provider_marker.exists())
        self.assertEqual(original, receipt.read_bytes())
        self.assertTrue(
            (directory / "opening-a/attempt-0002/call/receipt.json").is_file()
        )

    def test_crash_after_reply_replays_receipt(self):
        self.script = [OPEN, OPEN, PROPOSE_B, ACCEPT_B]
        publish = dialogue._publish

        def crash(path, data):
            if path.name == "turn_002_b.json":
                raise KeyboardInterrupt
            publish(path, data)

        with (
            patch.object(dialogue, "_publish", side_effect=crash),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.start()
        run = next((self.data / "consensus").iterdir()).name
        code, result = self.invoke("resume", run)
        self.assertEqual((0, "confirmed"), (code, result["status"]))
        self.assertEqual(4, len(self.calls))

    def test_changed_repo_blocks_resume(self):
        self.script = [OPEN, HarnessError("timed out")]
        _, out = self.start()
        (self.repo / "new.txt").write_text("different candidate")
        code, resumed = self.invoke("resume", out["run"])
        self.assertEqual((2, "blocked"), (code, resumed["status"]))
        self.assertIn("frozen subject", resumed["reason"])
        self.assertEqual(2, len(self.calls))

    def test_completed_status_is_blocked_on_new_source(self):
        self.script = [OPEN, OPEN, PROPOSE_B, ACCEPT_B]
        _, out = self.start()
        (self.repo / "new").touch()
        for action in ("status", "resume"):
            code, result = self.invoke(action, out["run"])
            self.assertEqual((2, "blocked"), (code, result["status"]))
            self.assertIn("subject", result["reason"])

    def test_write_workflow_prevents_consensus_launch(self):
        with dialogue.workspace_lock(self.repo):
            code, report = self.start()
        self.assertEqual((2, "blocked"), (code, report["status"]))
        self.assertIn("owns", report["reason"])
        self.assertFalse(self.calls)

    def test_locked_coordinator_cannot_race(self):
        self.script = [OPEN, HarnessError("offline")]
        _, out = self.start()
        with dialogue._exclusive(Path(out["artifacts"])):
            code, res = self.invoke("resume", out["run"])
        self.assertIn("coordinator", res["reason"])
        self.assertEqual(2, code)
        self.assertEqual(2, len(self.calls))

    def test_live_old_session_cannot_be_reissued(self):
        self.script = [OPEN, HarnessError("unavailable")]
        _, out = self.start()
        receipt = Path(out["artifacts"]) / "opening-b/attempt-0001/call/receipt.json"
        with subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            start_new_session=True,
        ) as child:
            try:
                receipt.write_text(json.dumps({"status": "running", "pgid": child.pid}))
                _, res = self.invoke("resume", out["run"])
            finally:
                child.terminate()
        self.assertIn("still be active", res["reason"])
        self.assertEqual(2, len(self.calls))


if __name__ == "__main__":
    unittest.main()
