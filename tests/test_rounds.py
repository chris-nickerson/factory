import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import argparse

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/software-factory/scripts"
sys.path.insert(0, str(SCRIPTS))
rounds = importlib.import_module("rounds")
checkpoints = importlib.import_module("checkpoints")


# A deterministic CLI exercises actual harness subprocess and session transport.
# The checker and git remote execute independently of these model responses.
CLAUDE = """#!/usr/bin/env python3
from pathlib import Path
import json, os, sys
args = sys.argv[1:]
fresh = "--session-id" in args
session = args[args.index("--session-id" if fresh else "--resume")+1]
prompt = sys.stdin.buffer.read()
log = Path(os.environ["FIXTURE_TURNS"])
mode = os.environ.get("FIXTURE_MODE", "")
if mode == "unavailable":
    sys.exit(1)
history = log.read_text().splitlines() if log.exists() else []
if fresh and mode == "edits" and not history:
    Path("calc.py").write_text("def add(a, b):\\\\n    return a + b\\\\n".replace("\\\\n", "\\n"))
if fresh and mode == "regression":
    Path("calc.py").write_text("def add(a,b): return a - b\\n")
if fresh and mode == "outside":
    Path("untouched").write_text("unexpected change")
if fresh and mode == "replace-file":
    Path("pkg").unlink()
    Path("pkg").mkdir()
    Path("pkg/entry.txt").write_text("ready")
with log.open("a") as stream:
    print(json.dumps({"session":session,"fresh":fresh,"mode":args[args.index("--permission-mode")+1],"prompt":prompt.decode()}),file=stream)
print(json.dumps({"subtype":"success","session_id":session,"modelUsage":{"claude-opus-fixture":{}},
                  "result":"Candidate inspected." if fresh or b"Implement the scoped repair" in prompt else "Observed results.\\nSTATUS: VERIFIED"}))
"""


FAKE_CODEX_NAMING_ITS_SESSION = r"""#!/usr/bin/env python3
from pathlib import Path
import json, os, sys, uuid
args = sys.argv[1:]
fresh = "resume" not in args
session = str(uuid.uuid4()) if fresh else args[args.index("resume") + 1]
if fresh:
    Path("calc.py").write_text("def add(a, b):\n    return a + b\n")
with open(os.environ["FIXTURE_TURNS"], "a") as stream:
    print(json.dumps({"sandbox": args[args.index("--sandbox") + 1],
                      "model": args[args.index("--model") + 1]}), file=stream)
text = "Candidate inspected." if fresh else "Observed results.\nSTATUS: VERIFIED"
for event in ({"type": "thread.started", "thread_id": session},
              {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
              {"type": "turn.completed"}):
    print(json.dumps(event))
"""


class RoundsTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.folder = Path(self.scratch.name)
        self.repo = self.folder / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "trunk")
        self.git("config", "user.name", "Factory Tests")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "-q", "--allow-empty", "-m", "base")
        self.git("switch", "-q", "-c", "feature")
        (self.repo / "calc.py").write_text(
            "def add(a, b):\n    result = a + b\n    return result\n"
        )
        self.git("add", ".")
        self.git("commit", "-q", "-m", "candidate")
        remote = self.folder / "upstream.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        self.git("remote", "add", "fixture", str(remote))
        self.turns = self.folder / "turns"
        fake = self.folder / "claude"
        fake.write_text(CLAUDE)
        fake.chmod(0o755)
        self.env = patch.dict(
            os.environ,
            PATH=str(self.folder) + os.pathsep + os.environ["PATH"],
            FACTORY_STATE_DIR=str(self.folder / "state"),
            XDG_CONFIG_HOME=str(self.folder / "config"),
            FIXTURE_TURNS=str(self.turns),
            FIXTURE_MODE="edits",
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        self.parser = argparse.ArgumentParser()
        rounds.register(self.parser.add_subparsers())
        self.start = [
            "--repo",
            str(self.repo),
            "--simplifier",
            "claude",
            "--base",
            "trunk",
            "--task",
            "preserve addition",
            "--check",
            'python3 -B -c "from calc import add; assert add(-2, 1) == -1"',
        ]

    def git(self, *args):
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True).strip()

    def invoke(self, *args):
        a = self.parser.parse_args(["simplify", *args])
        with contextlib.redirect_stdout(io.StringIO()) as capture:
            code = a.func(a)
        return code, json.loads(capture.getvalue())

    def test_sized_rounds_and_repository_checkpoint_subject(self):
        subject = "refactor: simplify calculation [DEMO-12]"
        for count in (1, 2):
            with self.subTest(count=count):
                code, result = self.invoke(
                    *self.start, "--rounds", str(count), "--commit-subject", subject
                )
                self.assertEqual(code, 0, result)
                self.assertEqual(result["target_rounds"], count)
                self.assertEqual(
                    len({r["session_id"] for r in result["rounds"]}), count
                )
                self.assertEqual(self.git("log", "-1", "--format=%s"), subject)
                self.assertEqual(
                    self.invoke("--resume", result["id"], "--rounds", "3")[0], 2
                )

    def test_codex_simplifier_edits_then_assesses_read_only(self):
        fake = self.folder / "codex"
        fake.write_text(FAKE_CODEX_NAMING_ITS_SESSION)
        fake.chmod(0o755)
        start = [
            "codex:gpt-fixture" if arg == "claude" else arg for arg in self.start
        ]
        code, result = self.invoke(*start, "--rounds", "1")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["profile"], "simplify/3")
        self.assertEqual(result["simplifier"]["harness"], "codex")
        self.assertIsNone(result["rounds"][0]["model_reported"])
        turns = [json.loads(row) for row in self.turns.read_text().splitlines()]
        self.assertEqual(
            turns,
            [
                {"sandbox": "workspace-write", "model": "gpt-fixture"},
                {"sandbox": "read-only", "model": "gpt-fixture"},
            ],
        )
        self.assertIn("return a + b", self.git("show", "HEAD:calc.py"))
        self.assertEqual(rounds.last_writer(self.repo), ("codex", result["id"]))

    def test_run_saved_by_the_previous_release_reports_and_resumes(self):
        with patch.object(
            rounds, "run_turn", side_effect=rounds.Pending("interrupted before launch")
        ):
            code, result = self.invoke(*self.start, "--rounds", "1")
        self.assertEqual(code, 2)
        saved = rounds.work_root() / result["run"] / "state.json"
        data = json.loads(saved.read_text())
        data["profile"] = "codex-opus-simplify/2"
        del data["simplifier"]
        rounds.save(saved, data)
        code, status = self.invoke("--resume", result["run"], "--status")
        self.assertEqual(status["simplifier"]["model"], "opus")
        code, complete = self.invoke("--resume", result["run"], "--recover")
        self.assertEqual(code, 0, complete)
        self.assertEqual(complete["profile"], "codex-opus-simplify/2")
        records = [json.loads(row) for row in self.turns.read_text().splitlines()]
        self.assertEqual([r["mode"] for r in records], ["auto", "dontAsk"])
        self.assertEqual(rounds.last_writer(self.repo), ("claude", result["run"]))

    def test_resume_refuses_an_old_receipt_whose_reported_model_differs(self):
        code, result = self.invoke(*self.start, "--rounds", "1")
        self.assertEqual(code, 0, result)
        folder = rounds.work_root() / result["id"]
        run = json.loads((folder / "state.json").read_text())
        record = run["rounds"][0]
        receipt = folder / record["calls"][-1]["name"] / "receipt.json"
        saved = json.loads(receipt.read_text())
        del saved["model_identity"]
        saved["model_usage"] = ["claude-sonnet-fixture"]
        receipt.write_text(json.dumps(saved))
        record["phase"] = "calling"
        with self.assertRaisesRegex(RuntimeError, "not the requested opus"):
            rounds.consume_call(run, record, folder, recover=False)

    def test_recover_rejected_subject_with_rewriting_hook_and_trailer(self):
        hook = self.repo / ".git/hooks/commit-msg"
        hook.write_text(
            '#!/bin/sh\ngrep -q "^refactor:" "$1" || exit 1\n'
            'sed -n "1{s/^/DEMO-12 /;p;}" "$1" > "$1.new" && mv "$1.new" "$1"\n'
            'printf "\\nChange-Id: I123\\n" >> "$1"\n'
        )
        hook.chmod(0o755)
        code, pending = self.invoke(*self.start, "--rounds", "1", "--push", "fixture")
        self.assertEqual(code, 2, pending)
        subject = "refactor: simplify calculation"
        code, result = self.invoke(
            "--resume", pending["run"], "--recover", "--commit-subject", subject
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(len(self.turns.read_text().splitlines()), 2)
        body = self.git("log", "-1", "--format=%B").splitlines()
        self.assertEqual(body[0], "DEMO-12 " + subject)
        self.assertNotIn(f"Factory simplify round 1 [{result['id']}]", body)
        self.assertIn("Change-Id: I123", body)
        self.assertEqual(
            result["rounds"][0]["remote_head"], self.git("rev-parse", "HEAD")
        )
        for bad in ("", " padded", "two\nlines"):
            self.assertEqual(self.invoke(*self.start, "--commit-subject", bad)[0], 2)

    def test_lost_checkpoint_with_replaced_message_requires_explicit_recovery(self):
        hook = self.repo / ".git/hooks/commit-msg"
        hook.write_text('#!/bin/sh\nprintf "project-approved subject\\n" > "$1"\n')
        hook.chmod(0o755)
        original = rounds.save

        def interrupt(path, state):
            if state["rounds"] and state["rounds"][-1]["phase"] == "publish":
                raise rounds.Pending("interrupted before receipt")
            return original(path, state)

        with patch.object(rounds, "save", interrupt):
            code, pending = self.invoke(*self.start, "--rounds", "1")
        self.assertEqual(code, 2, pending)
        code, refused = self.invoke("--resume", pending["run"])
        self.assertEqual(code, 2, refused)
        self.assertIn("no run marker", refused["error"])
        for recovery in (
            ("--recover",),
            ("--accept-checkpoint", "wrong"),
            ("--accept-checkpoint", ""),
        ):
            self.assertEqual(self.invoke("--resume", pending["run"], *recovery)[0], 2)
        code, complete = self.invoke(
            "--resume",
            pending["run"],
            "--accept-checkpoint",
            self.git("rev-parse", "HEAD"),
        )
        self.assertEqual(code, 0, complete)
        self.assertEqual(len(self.turns.read_text().splitlines()), 2)

    def test_custom_subject_survives_git_comment_cleanup(self):
        self.git("config", "commit.cleanup", "strip")
        subject = "#123 simplify calculation"
        code, result = self.invoke(
            *self.start, "--rounds", "1", "--commit-subject", subject
        )
        self.assertEqual(code, 0, result)
        self.assertEqual(self.git("log", "-1", "--format=%B"), subject)

    def test_exact_three_real_commits_push_readback_and_resume(self):
        code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 0, result)
        records = [json.loads(row) for row in self.turns.read_text().splitlines()]
        self.assertEqual([r["fresh"] for r in records], [True, False] * 3)
        self.assertEqual([r["mode"] for r in records], ["auto", "dontAsk"] * 3)
        self.assertEqual(
            {r["prompt"] for r in records[::2]}, {rounds.PROMPT.read_text()}
        )
        self.assertEqual(len({r["session"] for r in records[::2]}), 3)
        self.assertEqual(
            [r["session"] for r in records[::2]], [r["session"] for r in records[1::2]]
        )
        outputs = [r["output"] for r in result["rounds"]]
        self.assertEqual(
            len(set(outputs)), 1
        )  # one improvement, then two no-change rounds
        self.assertEqual(self.git("rev-list", "--count", "trunk..HEAD"), "2")
        self.assertEqual(
            outputs[-1],
            self.git("ls-remote", "fixture", "refs/heads/feature").split()[0],
        )
        self.assertEqual(self.invoke("--resume", result["id"])[0], 0)
        self.assertEqual(len(self.turns.read_text().splitlines()), 6)

    def test_recover_lost_remote_receipt_without_replaying_agents(self):
        real_push = rounds.push_checkpoint

        def lost(s, prior, head):
            real_push(s, prior, head)
            raise rounds.Pending("lost reply")

        with patch.object(rounds, "push_checkpoint", lost):
            code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 2)
        self.assertEqual(len(self.turns.read_text().splitlines()), 2)
        code, complete = self.invoke("--resume", result["run"])
        self.assertEqual(code, 0, complete)
        self.assertEqual(len(self.turns.read_text().splitlines()), 6)

    def test_no_change_before_first_remote_publication(self):
        with patch.dict(os.environ, FIXTURE_MODE="noop"):
            head = self.git("rev-parse", "HEAD")
            code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 0, result)
        self.assertEqual([r["remote_head"] for r in result["rounds"]], [head] * 3)

    def destination_state(self):
        return {
            "repo": str(self.repo),
            "remote": "fixture",
            "branch": "feature",
            "destination": checkpoints.digest(
                os.fsencode(checkpoints.push_destination(self.repo, "fixture"))
            ),
        }

    def new_remote(self):
        other = self.folder / "other.git"
        subprocess.run(["git", "init", "-q", "--bare", str(other)], check=True)
        return other

    def refs_in(self, dest):
        return subprocess.check_output(
            ["git", "--git-dir", str(dest), "for-each-ref", "--format=%(refname)"],
            text=True,
        ).splitlines()

    def test_tag_sharing_branch_name_publishes_to_exact_branch(self):
        self.git("tag", "feature", "trunk")
        self.assertEqual(self.git("symbolic-ref", "--short", "HEAD"), "heads/feature")
        code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["branch"], "feature")
        self.assertEqual(
            self.refs_in(self.folder / "upstream.git"), ["refs/heads/feature"]
        )

    def test_remote_reconfiguration_between_observation_and_push(self):
        original = self.folder / "upstream.git"
        other = self.new_remote()
        state = self.destination_state()
        wanted = self.git("rev-parse", "HEAD")
        run_git = checkpoints.git

        def reconfigure(repo, *args, **kwargs):
            if args[0] == "push":
                self.git("remote", "set-url", "--push", "fixture", str(other))
            return run_git(repo, *args, **kwargs)

        with patch.object(checkpoints, "git", reconfigure):
            self.assertEqual(checkpoints.push_checkpoint(state, None, wanted), wanted)
        self.assertEqual(self.refs_in(original), ["refs/heads/feature"])
        self.assertEqual(self.refs_in(other), [])
        with self.assertRaisesRegex(checkpoints.Pending, "destination changed"):
            checkpoints.published(state)

    def test_chained_url_rewrites_resolve_once_for_read_and_write(self):
        original = self.folder / "upstream.git"
        other = self.new_remote()
        self.git("config", f"url.{original}.insteadOf", "fixture-source:")
        self.git("config", f"url.{other}.insteadOf", str(original))
        self.git("config", f"url.{other}.pushInsteadOf", str(original))
        self.git("remote", "set-url", "fixture", "fixture-source:")
        self.assertEqual(checkpoints.push_destination(self.repo, "fixture"), str(original))
        state = self.destination_state()
        wanted = self.git("rev-parse", "HEAD")
        self.assertEqual(checkpoints.push_checkpoint(state, None, wanted), wanted)
        self.assertEqual(checkpoints.published(state), wanted)
        self.assertEqual(self.refs_in(original), ["refs/heads/feature"])
        self.assertEqual(self.refs_in(other), [])

    def test_diverged_remote_keeps_its_history(self):
        self.git("push", "-q", "fixture", "HEAD:feature")

        def advance(s, prior, wanted):
            self.git("push", "-q", "fixture", f"+{s['base']}:refs/heads/feature")
            return real(s, prior, wanted)

        real = rounds.push_checkpoint
        with patch.object(rounds, "push_checkpoint", advance):
            code, report = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 2)
        self.assertIn("moved independently", report["error"])
        self.assertEqual(
            self.git("ls-remote", "fixture", "refs/heads/feature").split()[0],
            self.git("rev-parse", "trunk"),
        )

    def test_unavailable_model_never_counts_a_round(self):
        with patch.dict(os.environ, FIXTURE_MODE="unavailable"):
            code, result = self.invoke(*self.start)
        self.assertEqual(code, 2)
        code, pending = self.invoke("--resume", result["run"])
        self.assertEqual(code, 2)
        self.assertIn("Interrupted", pending["error"])
        self.assertFalse(self.turns.exists())
        code, complete = self.invoke("--resume", result["run"], "--recover")
        self.assertEqual(code, 0, complete)

    def test_incorrect_result_stops_despite_verified_claim(self):
        with patch.dict(os.environ, FIXTURE_MODE="regression"):
            start = self.git("rev-parse", "HEAD")
            code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 2)
        self.assertIn("repair attempts exhausted", result["error"])
        self.assertEqual(start, self.git("rev-parse", "HEAD"))
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))

    def test_final_receipt_persists_when_remote_tip_moves(self):
        code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 0, result)
        self.git("push", "-q", "fixture", "+trunk:refs/heads/feature")
        code, stale = self.invoke("--resume", result["id"], "--status")
        self.assertEqual(code, 2)
        self.assertEqual(stale["status"], "stale")
        self.assertEqual(stale["recorded_status"], "complete")
        self.assertEqual(stale["current_remote_head"], self.git("rev-parse", "trunk"))

    def test_crash_after_intent_before_harness_launch(self):
        with patch.object(
            rounds, "run_turn", side_effect=rounds.Pending("interrupted before launch")
        ):
            code, result = self.invoke(*self.start)
        self.assertEqual(code, 2)
        self.assertFalse(self.turns.exists())
        code, blocked = self.invoke("--resume", result["run"])
        self.assertEqual(code, 2)
        self.assertIn("no launch receipt", blocked["error"])
        # A partially completed run from the file-only release keeps its authority.
        saved = rounds.work_root() / result["run"] / "state.json"
        data = json.loads(saved.read_text())
        data["profile"] = rounds.LEGACY_PROFILE
        del data["simplifier"]
        rounds.save(saved, data)
        code, complete = self.invoke("--resume", result["run"], "--recover")
        self.assertEqual(code, 0, complete)
        records = [json.loads(row) for row in self.turns.read_text().splitlines()]
        self.assertEqual([r["mode"] for r in records], ["dontAsk"] * 6)

    def test_dead_prelaunch_supervisor_allows_release(self):
        def call(*args, output_dir, **kwargs):
            output_dir.mkdir()
            with subprocess.Popen([sys.executable, "-c", "pass"]) as supervisor:
                supervisor.wait(timeout=3)
            rounds.save(
                output_dir / "receipt.json",
                {
                    "status": "starting",
                    "coordinator_pid": os.getpid(),
                    "supervisor_pid": supervisor.pid,
                },
            )
            raise rounds.Pending("interrupted before group publication")

        with patch.object(rounds, "run_turn", side_effect=call):
            code, result = self.invoke(*self.start)
        self.assertEqual(code, 2)
        code, released = self.invoke("--resume", result["run"], "--release")
        self.assertEqual((code, released["status"]), (2, "released"))
        self.assertFalse(self.turns.exists())

    def test_unavailable_supervisor_status_blocks_release(self):
        def call(*args, output_dir, **kwargs):
            output_dir.mkdir()
            rounds.save(
                output_dir / "receipt.json",
                {"status": "starting", "supervisor_pid": os.getpid()},
            )
            raise rounds.Pending("simulated interruption")

        with patch.object(rounds, "run_turn", side_effect=call):
            code, result = self.invoke(*self.start)
        self.assertEqual(code, 2)
        code, blocked = self.invoke("--resume", result["run"], "--release")
        self.assertEqual(code, 2)
        self.assertIn("writer may still be active", blocked["error"])
        code, active = self.invoke("--resume", result["run"], "--status")
        self.assertEqual(active["status"], "active")

    def test_hidden_index_flags_block_even_on_no_change(self):
        for flag in ("assume-unchanged", "skip-worktree"):
            with self.subTest(flag=flag):
                self.git("update-index", "--" + flag, "calc.py")
                with (self.repo / "calc.py").open("a") as fh:
                    fh.write("# local copy")
                self.assertEqual(self.git("diff", "--name-only", "HEAD"), "")
                code, result = self.invoke(*self.start, "--push", "fixture")
                self.assertEqual(code, 2, result)
                self.assertFalse(self.turns.exists())
                self.git("update-index", "--no-" + flag, "calc.py")
                self.git("restore", "calc.py")

    def test_hidden_index_created_by_check_cannot_receive_checkpoint(self):
        code, result = self.invoke(
            *self.start,
            "--check",
            "git update-index --assume-unchanged calc.py",
            "--push",
            "fixture",
        )
        self.assertEqual(code, 2, result)
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))
        self.assertEqual(len(self.turns.read_text().splitlines()), 1)

    def test_hidden_index_after_completion_blocks_current_verdict(self):
        code, result = self.invoke(*self.start)
        self.assertEqual(code, 0, result)
        self.git("update-index", "--skip-worktree", "calc.py")
        code, current = self.invoke("--resume", result["id"], "--status")
        self.assertEqual(code, 2, current)
        self.assertEqual(current["recorded_status"], "complete")

    def test_check_cannot_deinitialize_nested_submodule_between_commands(self):
        child = self.folder / "child"
        outer = self.folder / "outer"
        for path in (child, outer):
            self.git("clone", "-q", str(self.repo), str(path))
        add = ["-c", "protocol.file.allow=always", "submodule", "add", "-q"]
        self.git("-C", str(outer), *add, str(child), "inner")
        self.git(
            "-C",
            str(outer),
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Nested dependency",
        )
        self.git(*add, str(outer), "deps")
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
            "--recursive",
        )
        self.git("commit", "-qm", "Initialized dependencies")
        self.assertTrue((self.repo / "deps/inner/calc.py").exists())
        marker = self.folder / "later-check"
        code, result = self.invoke(
            *self.start,
            "--check",
            "git -C deps submodule deinit -f -- inner",
            "--check",
            f"touch {marker}",
            "--push",
            "fixture",
        )
        self.assertEqual(code, 2, result)
        self.assertFalse((self.repo / "deps/inner/calc.py").exists())
        self.assertFalse(marker.exists())
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))
        self.assertEqual(self.git("diff", "--name-only", "HEAD"), "calc.py")

    def test_unchanged_uninitialized_submodule_is_supported_until_checkout_changes(
        self,
    ):
        source = self.folder / "dependency"
        self.git("clone", "-q", str(self.repo), str(source))
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(source),
            "deps",
        )
        self.git("commit", "-qm", "Optional dependency")
        self.git("submodule", "deinit", "-f", "--", "deps")
        code, result = self.invoke(*self.start)
        self.assertEqual(code, 0, result)
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "-q",
            "--init",
            "--",
            "deps",
        )
        self.assertEqual(self.git("diff", "--name-only", "HEAD"), "")
        code, current = self.invoke("--resume", result["id"], "--status")
        self.assertEqual(code, 2, current)
        self.assertEqual(current["recorded_status"], "complete")
        self.assertIn("Submodule checkouts changed", current["error"])

    def test_legacy_active_gitlink_run_can_release_and_restart(self):
        source = self.folder / "dependency"
        self.git("clone", "-q", str(self.repo), str(source))
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(source),
            "deps",
        )
        self.git("commit", "-qm", "Dependency")
        with patch.object(
            rounds, "run_turn", side_effect=rounds.Pending("interrupted before launch")
        ):
            code, record = self.invoke(*self.start)
        self.assertEqual(code, 2)
        run = record["run"]
        state_file = rounds.work_root() / run / "state.json"
        before = json.loads(state_file.read_text())
        del before["submodule_checkouts"]
        rounds.save(state_file, before)
        for action in (["--status"], ["--recover"]):
            code, result = self.invoke("--resume", run, *action)
            self.assertEqual(code, 2)
            self.assertIn(f"--resume {run} --release", result["error"])
        self.assertEqual(json.loads(state_file.read_text()), before)
        code, released = self.invoke("--resume", run, "--release")
        self.assertEqual(released["status"], "released")
        code, fresh = self.invoke(*self.start)
        self.assertEqual(code, 0, fresh)
        self.assertNotEqual(fresh["id"], run)
        state_file = Path(fresh["state"])
        historical = json.loads(state_file.read_text())
        del historical["submodule_checkouts"]
        rounds.save(state_file, historical)
        code, current = self.invoke("--resume", fresh["id"], "--status")
        self.assertEqual(code, 2)
        self.assertEqual(current["recorded_status"], "complete")
        self.assertIn("fresh run", current["error"])
        self.assertNotIn("--release", current["error"])
        self.assertEqual(json.loads(state_file.read_text()), historical)

    def test_legacy_plain_run_can_resume(self):
        with patch.object(
            rounds, "run_turn", side_effect=rounds.Pending("before launch")
        ):
            _, record = self.invoke(*self.start)
        path = rounds.work_root() / record["run"] / "state.json"
        saved = json.loads(path.read_text())
        del saved["target_rounds"]
        del saved["commit_subject"]
        del saved["submodule_checkouts"]
        rounds.save(path, saved)
        code, result = self.invoke("--resume", record["run"], "--recover")
        self.assertEqual(code, 0, result)
        self.assertEqual(result["target_rounds"], 3)
        self.assertEqual(len(result["rounds"]), 3)
        self.assertEqual(json.loads(path.read_text())["submodule_checkouts"], {})

    def test_submodule_dirty_and_hidden_content_blocks_publication(self):
        module = self.folder / "module"
        subprocess.run(["git", "clone", "-q", str(self.repo), str(module)], check=True)
        self.git(
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            "-q",
            str(module),
            "deps/library",
        )
        self.git("commit", "-qm", "Add dependency")
        nested = self.repo / "deps/library"
        with (nested / "calc.py").open("a") as fh:
            fh.write("# local module edits")
        code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 2)
        self.assertIn("Submodule contains local changes", result["error"])
        self.git("-C", str(nested), "update-index", "--assume-unchanged", "calc.py")
        self.assertEqual(self.git("diff", "--name-only", "HEAD"), "")
        code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 2, result)
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))

    def test_staged_change_hidden_by_unstaged_reversion(self):
        original = (self.repo / "calc.py").read_text()
        (self.repo / "calc.py").write_text("user staging area")
        self.git("add", "calc.py")
        (self.repo / "calc.py").write_text(original)
        code, result = self.invoke(*self.start)
        self.assertEqual(code, 2)
        self.assertIn("clean", result["error"])
        self.assertEqual(self.git("show", ":calc.py"), "user staging area")
        self.assertFalse(self.turns.exists())

    def test_lost_commit_receipt_does_not_repeat_commit_or_call(self):
        original = rounds.save

        def crash(path, state):
            if state["rounds"] and state["rounds"][-1]["phase"] == "publish":
                raise rounds.Pending("interrupted before recording commit")
            return original(path, state)

        with patch.object(rounds, "save", crash):
            code, pending = self.invoke(*self.start)
        self.assertEqual(code, 2)
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(len(self.turns.read_text().splitlines()), 2)
        code, complete = self.invoke("--resume", pending["run"])
        self.assertEqual(code, 0, complete)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertEqual(len(self.turns.read_text().splitlines()), 6)

    def test_later_check_cannot_restore_an_intermediate_mutation(self):
        marker = self.folder / "restorer-ran"
        mutate = """python3 -c "from pathlib import Path; p=Path('calc.py'); p.write_bytes(p.read_bytes()+b'# temporary')" """
        restore = f"""python3 -c "from pathlib import Path; p=Path('calc.py'); p.write_bytes(p.read_bytes().removesuffix(b'# temporary')); Path('{marker}').touch()" """
        code, result = self.invoke(
            *self.start, "--check", mutate, "--check", restore, "--push", "fixture"
        )
        self.assertEqual(code, 2, result)
        self.assertFalse(marker.exists())
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))

    def test_filemode_config_cannot_hide_executable_drift(self):
        self.git("config", "core.fileMode", "false")
        script = self.repo / "calc.py"
        script.chmod(0o755)
        self.assertEqual(self.git("status", "--porcelain"), "")
        code, result = self.invoke(*self.start, "--push", "fixture")
        self.assertEqual(code, 2, result)
        self.assertFalse(self.turns.exists())
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))

    def test_checks_that_modify_the_tree_cannot_qualify(self):
        code, report = self.invoke(
            *self.start,
            "--check",
            """python3 -c "open('calc.py', 'a').write('# unchecked')" """,
        )
        self.assertEqual(code, 2)
        self.assertIn("Checks changed", report["error"])
        self.assertEqual(self.git("rev-list", "--count", "trunk..HEAD"), "1")

    def test_checks_cannot_change_bytes_git_normalizes(self):
        (self.repo / ".gitattributes").write_text("calc.py text eol=lf\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-qm", "Normalize source line endings")
        before = self.git("rev-parse", "HEAD")
        convert = shlex.join(
            [
                sys.executable,
                "-c",
                "from pathlib import Path; p = Path('calc.py'); "
                "p.write_bytes(p.read_bytes().replace(b'\\n', b'\\r\\n'))",
            ]
        )
        with patch.dict(os.environ, FIXTURE_MODE="noop"):
            code, report = self.invoke(
                *self.start, "--rounds", "1", "--check", convert, "--push", "fixture"
            )
        self.assertEqual(code, 2, report)
        self.assertIn("Checks changed", report["error"])
        self.assertEqual(self.git("diff", "--", "calc.py"), "")
        self.assertIn(b"\r\n", (self.repo / "calc.py").read_bytes())
        self.assertEqual(self.git("rev-parse", "HEAD"), before)
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))
        self.assertEqual(len(self.turns.read_text().splitlines()), 1)

    def test_checkpoint_accepts_replacing_a_tracked_file_with_a_directory(self):
        (self.repo / "pkg").write_text("old layout")
        self.git("add", "pkg")
        self.git("commit", "-qm", "Record the original layout")
        with patch.dict(os.environ, FIXTURE_MODE="replace-file"):
            code, report = self.invoke(*self.start, "--rounds", "1", "--push", "fixture")
        self.assertEqual(code, 0, report)
        self.assertEqual(self.git("show", "HEAD:pkg/entry.txt"), "ready")
        self.assertEqual(report["rounds"][0]["remote_head"], self.git("rev-parse", "HEAD"))

    def test_checks_stop_if_head_moves_before_working_input_snapshot(self):
        self.assert_head_move_blocks_checks(snapshot_number=1, first_runs=False)

    def test_checks_stop_if_head_moves_during_post_check_snapshot(self):
        self.assert_head_move_blocks_checks(snapshot_number=2, first_runs=True)

    def assert_head_move_blocks_checks(self, *, snapshot_number, first_runs):
        first = self.folder / "first-check-ran"
        later = self.folder / "later-check-ran"
        snapshot = rounds.snapshot
        before = self.git("rev-parse", "HEAD")
        observed_snapshots = 0

        def move_head_during_snapshot(*args, **kwargs):
            nonlocal observed_snapshots
            observed_snapshots += 1
            if observed_snapshots == snapshot_number:
                self.git("commit", "--allow-empty", "-qm", "Independent same-tree commit")
            return snapshot(*args, **kwargs)

        with (
            patch.dict(os.environ, FIXTURE_MODE="noop"),
            patch.object(rounds, "snapshot", side_effect=move_head_during_snapshot),
        ):
            code, report = self.invoke(
                *self.start[:-1], shlex.join(["touch", str(first)]),
                "--rounds", "1", "--check", shlex.join(["touch", str(later)])
            )
        self.assertEqual(code, 2, report)
        self.assertIn("revision changed", report["error"])
        self.assertNotEqual(self.git("rev-parse", "HEAD"), before)
        self.assertEqual(first.exists(), first_runs)
        self.assertFalse(later.exists())
        self.assertEqual(len(self.turns.read_text().splitlines()), 1)

    def test_head_move_during_assessment_fingerprint_blocks_provider(self):
        state, moved = self.move_head_during_fingerprint("assess")
        self.assertEqual(state["phase"], "assess")
        self.assertEqual(self.git("rev-parse", "HEAD"), moved)
        self.assertEqual(len(self.turns.read_text().splitlines()), 1)

    def test_head_move_during_pre_push_fingerprint_blocks_push(self):
        state, moved = self.move_head_during_fingerprint("publish")
        self.assertEqual(state["phase"], "publish")
        self.assertEqual(self.git("rev-parse", "HEAD"), moved)
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))

    def test_head_move_during_post_push_fingerprint_blocks_confirmation(self):
        state, moved = self.move_head_during_fingerprint("publish", after_push=True)
        self.assertEqual(state["phase"], "publish")
        self.assertEqual(self.git("rev-parse", "HEAD"), moved)
        remote = self.git("ls-remote", "fixture", "refs/heads/feature")
        self.assertEqual(remote.split()[0], state["output"])

    def move_head_during_fingerprint(self, phase, *, after_push=False):
        check = rounds.ensure_checked_working_inputs
        moved = None

        def check_with_head_move(run, record):
            nonlocal moved
            check(run, record)
            if record["phase"] == phase and moved is None:
                published = bool(record.get("remote_head"))
                if published == after_push:
                    self.git("commit", "--allow-empty", "-qm", "Independent same-tree commit")
                    moved = self.git("rev-parse", "HEAD")

        with patch.object(rounds, "ensure_checked_working_inputs", check_with_head_move):
            code, report = self.invoke(*self.start, "--rounds", "1", "--push", "fixture")
        self.assertEqual(code, 2, report)
        self.assertIsNotNone(moved)
        saved = rounds.work_root() / report["run"] / "state.json"
        return json.loads(saved.read_text())["rounds"][0], moved

    def test_resume_rejects_git_hidden_drift_after_checks(self):
        (self.repo / ".gitattributes").write_text("calc.py text eol=lf\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-qm", "Normalize source line endings")
        source = self.repo / "calc.py"
        original = source.read_bytes()
        contact = rounds.contact

        def interrupt_assessment(run, record, folder, kind, *args):
            if kind == "assess":
                raise rounds.Pending("Interrupted before assessment")
            return contact(run, record, folder, kind, *args)

        with (
            patch.dict(os.environ, FIXTURE_MODE="noop"),
            patch.object(rounds, "contact", side_effect=interrupt_assessment),
        ):
            code, pending = self.invoke(*self.start, "--rounds", "1", "--push", "fixture")
        self.assertEqual(code, 2, pending)
        source.write_bytes(original.replace(b"\n", b"\r\n"))
        code, blocked = self.invoke("--resume", pending["run"])
        self.assertEqual(code, 2, blocked)
        self.assertEqual(self.git("diff", "--", "calc.py"), "")
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))
        self.assertEqual(len(self.turns.read_text().splitlines()), 1)

        source.write_bytes(original)
        code, complete = self.invoke("--resume", pending["run"])
        self.assertEqual(code, 0, complete)
        self.assertEqual(complete["rounds"][0]["remote_head"], self.git("rev-parse", "HEAD"))

    def test_resume_does_not_push_when_checked_bytes_change_after_commit(self):
        (self.repo / ".gitattributes").write_text("calc.py text eol=lf\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-qm", "Normalize source line endings")
        before = self.git("rev-parse", "HEAD")
        with patch.object(
            rounds, "push_checkpoint", side_effect=rounds.Pending("Interrupted before push")
        ):
            code, pending = self.invoke(*self.start, "--rounds", "1", "--push", "fixture")
        self.assertEqual(code, 2, pending)
        checkpoint = self.git("rev-parse", "HEAD")
        self.assertNotEqual(checkpoint, before)

        source = self.repo / "calc.py"
        original = source.read_bytes()
        source.write_bytes(original.replace(b"\n", b"\r\n"))
        self.assertEqual(self.git("diff", "--", "calc.py"), "")
        code, blocked = self.invoke("--resume", pending["run"])
        self.assertEqual(code, 2, blocked)
        self.assertFalse(self.git("ls-remote", "fixture", "refs/heads/feature"))

        source.write_bytes(original)
        code, complete = self.invoke("--resume", pending["run"])
        self.assertEqual(code, 0, complete)
        self.assertEqual(complete["rounds"][0]["remote_head"], checkpoint)
        self.assertEqual(len(self.turns.read_text().splitlines()), 2)

    def test_push_hook_raw_drift_leaves_checkpoint_pending(self):
        (self.repo / ".gitattributes").write_text("calc.py text eol=lf\n")
        self.git("add", ".gitattributes")
        self.git("commit", "-qm", "Normalize source line endings")
        hook = self.repo / ".git/hooks/pre-push"
        convert = shlex.join(
            [
                sys.executable, "-c",
                "from pathlib import Path; p = Path('calc.py'); "
                "p.write_bytes(p.read_bytes().replace(b'\\n', b'\\r\\n'))",
            ]
        )
        hook.write_text(f"#!/bin/sh\nexec {convert}\n")
        hook.chmod(0o755)
        code, pending = self.invoke(*self.start, "--rounds", "1", "--push", "fixture")
        self.assertEqual(code, 2, pending)
        self.assertIn("Working inputs changed", pending["error"])
        checkpoint = self.git("rev-parse", "HEAD")
        remote = self.git("ls-remote", "fixture", "refs/heads/feature")
        self.assertEqual(remote.split()[0], checkpoint)

        source = self.repo / "calc.py"
        self.assertIn(b"\r\n", source.read_bytes())
        source.write_bytes(source.read_bytes().replace(b"\r\n", b"\n"))
        code, complete = self.invoke("--resume", pending["run"])
        self.assertEqual(code, 0, complete)
        self.assertEqual(complete["rounds"][0]["remote_head"], checkpoint)
        self.assertEqual(len(self.turns.read_text().splitlines()), 2)

    def test_scope_and_dirty_tree_preserve_work(self):
        with patch.dict(os.environ, FIXTURE_MODE="outside"):
            code, result = self.invoke(*self.start)
        self.assertEqual(code, 2)
        self.assertIn("Unexpected paths", result["error"])
        self.assertEqual((self.repo / "untouched").read_text(), "unexpected change")
        code, result = self.invoke(*self.start)
        self.assertEqual(code, 2)
        self.assertIn("clean", result["error"])


if __name__ == "__main__":
    unittest.main()
