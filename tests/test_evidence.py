"""Exercise the installed command boundary, with real repos and independent oracles."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "factory"


class FactoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve()
        self.repo = self.home / "target"
        self.repo.mkdir()
        self.env = dict(os.environ, FACTORY_STATE_DIR=str(self.home / "state"))
        self.git("init", "-q", "-b", "trunk")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "user.name", "fixture")
        (self.repo / "maths.py").write_text("def add(a,b): return a-b\n")
        self.git("add", "maths.py")
        self.git("commit", "-qm", "fixture")

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.repo), *args])

    def cli(self, *args, code=0):
        p = subprocess.run(
            [str(CLI), *map(str, args)],
            cwd=self.repo,
            env=self.env,
            text=True,
            capture_output=True,
        )
        self.assertEqual(p.returncode, code, (p.stdout, p.stderr))
        return json.loads(p.stdout or p.stderr)

    def start(self, claims=None, extra=()):
        (self.home / "consumer.py").write_text(
            "import os,sys\nsys.path.insert(0,os.getcwd())\nfrom maths import add\nassert add(2,3)==5 and add(-3,2)==-1\n"
        )
        path = self.home / "contract.json"
        path.write_text(
            json.dumps(
                claims
                or [dict(id="sum", expect="correct addition", oracle="consumer.py")]
            )
        )
        return self.cli(
            "start",
            "--repo",
            self.repo,
            "--task",
            "repair addition",
            "--contract",
            path,
            *extra,
        )["run"]

    def test_wrong_behavior_fixed_oracle_and_stale_evidence(self):
        run = self.start()
        self.cli("status", run, code=2)
        self.assertEqual(
            self.cli("check", run, code=1)["claims"]["sum"]["status"], "FAIL"
        )
        (self.home / "consumer.py").write_text("pass")
        self.cli("check", run, code=1)
        (self.repo / "maths.py").write_text("def add(a,b): return a+b\n")
        result = self.cli("check", run)
        self.assertEqual(result["status"], "VERIFIED")
        log = Path(result["artifacts"]) / result["claims"]["sum"]["latest"]["log"]
        log.write_text("replaced")
        self.assertEqual(
            self.cli("status", run, code=2)["claims"]["sum"]["status"], "BLOCKED"
        )
        self.cli("check", run)
        (self.repo / "new.py").write_text("pass")
        self.assertEqual(
            self.cli("status", run, code=2)["claims"]["sum"]["status"], "STALE"
        )

    def test_outcomes_bind_to_checked_subject_and_preserve_the_gate(self):
        run = self.start()
        args = (
            "outcome",
            run,
            "--note",
            "Keyboard activation failed",
            "--evidence",
            "issue-7",
        )
        self.assertEqual(self.cli("outcome", run)["outcomes"], [])
        self.cli(*args, code=2)
        failed = self.cli("check", run, code=1)
        (self.repo / "maths.py").write_text("def add(a,b): return a+b\n")
        verified = self.cli("check", run)
        self.cli(*args, code=2)
        self.cli(*args, "--subject", "unknown", code=2)
        selected = (*args, "--subject", verified["subject"])
        stored = self.cli(*selected)["outcome"]
        self.assertEqual(stored["checks"], [verified["claims"]["sum"]["latest"]["log"]])
        self.assertEqual(self.cli(*selected)["outcome"], stored)
        self.assertEqual(self.cli("status", run), verified)
        self.cli(
            "outcome",
            run,
            "--subject",
            failed["subject"],
            "--note",
            "Original failure confirmed",
        )
        result = self.cli("outcome", run)
        self.assertEqual(len(result["outcomes"]), 2)
        self.assertEqual(
            set(result["subjects"]), {verified["subject"], failed["subject"]}
        )

    def test_feedback_survives_checkout_removal(self):
        run = self.start()
        failed = self.cli("check", run, code=1)
        self.repo.rename(self.home / "archived-checkout")
        result = subprocess.check_output(
            [str(CLI), "outcome", run, "--note", "Issue later reopened"],
            cwd=self.home,
            env=self.env,
        )
        self.assertEqual(json.loads(result)["outcome"]["subject"], failed["subject"])

    def test_frozen_oracle_assertions_survive_ambient_optimization(self):
        self.env["PYTHONOPTIMIZE"] = "1"
        run = self.start()
        self.assertEqual(self.cli("check", run, code=1)["status"], "FAILED")

    def test_external_file_symlink_invalidates_verified_subject(self):
        source = self.repo / "maths.py"
        dependency = self.home / "linked.py"
        source.unlink()
        dependency.write_text("def add(a,b): return a+b\n")
        source.symlink_to(dependency)
        run = self.start()
        self.cli("check", run)
        dependency.write_text("def add(a,b): return a-b\n")
        self.assertEqual(
            self.cli("status", run, code=2)["claims"]["sum"]["status"], "STALE"
        )
        self.cli("check", run, code=1)

    def test_review_rejects_hidden_index_flags(self):
        run = self.start(extra=("--require-review",))
        self.git("update-index", "--assume-unchanged", "maths.py")
        self.assertIn("assume-unchanged", self.cli("review", run, code=2)["error"])

    def test_unrelated_dirty_file_does_not_create_a_scoped_review(self):
        run = self.start(extra=("--require-review", "--path", "maths.py"))
        (self.repo / "notes.md").write_text("user work")
        self.assertIn("Empty change", self.cli("review", run, code=2)["error"])
        self.assertEqual((self.repo / "notes.md").read_text(), "user work")

    def test_healthy_service_running_wrong_revision_fails_build_bound_oracle(self):
        class Healthy(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("X-Build", self.server.build)
                self.end_headers()
                self.wfile.write(b"ready")

            def log_message(self, *args):
                pass

        with ThreadingHTTPServer(("127.0.0.1", 0), Healthy) as server:
            server.build = "old-build"
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                oracle = self.home / "served.py"
                oracle.write_text(
                    "from urllib.request import urlopen\n"
                    f"with urlopen('http://127.0.0.1:{server.server_port}/',timeout=3) as r:\n"
                    "    assert r.read()==b'ready' and r.headers['X-Build']=='candidate'\n"
                )
                run = self.start(
                    [
                        dict(
                            id="served",
                            expect="candidate build responds ready",
                            oracle="served.py",
                        )
                    ]
                )
                self.cli("check", run, code=1)
                server.build = "candidate"
                self.assertEqual(self.cli("check", run)["status"], "VERIFIED")
            finally:
                server.shutdown()
                thread.join()

    def test_review_includes_index_even_when_worktree_matches_base(self):
        run = self.start(extra=("--require-review",))
        target = self.repo / "maths.py"
        original = target.read_bytes()
        target.write_text("def add(a,b): return 123\n")
        self.git("add", "maths.py")
        target.write_bytes(original)
        self.assertEqual(self.git("diff", "HEAD"), b"")
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        fake = bin_dir / "codex"
        fake.write_text(
            "#!/usr/bin/env python3\nimport sys,json,time,uuid\ns=sys.stdin.read()\ntime.sleep(1.2)\n"
            "assert '--cached' in s and 'Index to working tree:' in s and s.count('maths.py')>=2\n"
            "for event in [{'type':'thread.started','thread_id':str(uuid.uuid4())},"
            "{'type':'item.completed','item':{'type':'agent_message','text':'Staged wrong value.\\nVERDICT: FINDINGS'}},"
            "{'type':'turn.completed'}]: print(json.dumps(event))\n"
        )
        fake.chmod(0o755)
        self.env["PATH"] = str(bin_dir) + os.pathsep + self.env["PATH"]
        report = self.cli("review", run, "--timeout", "1", code=1)
        self.assertEqual(report["review"], "FINDINGS")

    def test_failure_modes(self):
        run = self.start(
            [
                dict(
                    id="missing",
                    expect="required tool",
                    argv=[str(self.home / "absent")],
                ),
                dict(
                    id="timeout",
                    expect="bounded",
                    argv=[sys.executable, "-c", "import time;time.sleep(4)"],
                ),
                dict(
                    id="mutation",
                    expect="read only",
                    argv=[sys.executable, "-c", "open('leak','w').close()"],
                ),
            ]
        )
        for key in ("missing", "timeout", "mutation"):
            result = self.cli("check", run, "--claim", key, "--timeout", "1", code=2)
            self.assertEqual(result["claims"][key]["latest"]["status"], "BLOCKED")

    def test_required_review_stays_pending(self):
        run = self.start(
            [dict(id="test", expect="fixture executes", argv=[sys.executable, "-V"])],
            extra=("--require-review",),
        )
        self.assertEqual(self.cli("check", run, code=2)["review"], "PENDING")
        self.assertIn("Empty change", self.cli("review", run, code=2)["error"])

    def test_plain_folder_and_discovery_scope(self):
        plain = self.home / "plain"
        plain.mkdir()
        (plain / "AGENTS.md").write_text("Root guide.")
        (plain / "CLAUDE.md").symlink_to("AGENTS.md")
        pkg = plain / "component"
        pkg.mkdir()
        (pkg / "AGENTS.md").write_text("Component guide.")
        (pkg / "package.json").write_text(
            json.dumps(dict(scripts=dict(check="node check.js")))
        )
        (plain / "pnpm-lock.yaml").write_text("")
        (pkg / "software-factory.toml").write_text('[checks]\nsmoke=["python3","-V"]\n')
        report = self.cli("inspect", "--repo", plain, "--path", "component/file.js")
        self.assertEqual(report["instructions"], ["AGENTS.md", "component/AGENTS.md"])
        self.assertEqual(report["commands"][0]["argv"], ["pnpm", "run", "check"])
        self.assertEqual(report["commands"][1]["cwd"], "component")
        self.assertIn(
            "outside",
            self.cli("inspect", "--repo", plain, "--path", "../oops", code=2)["error"],
        )
        self.repo = plain
        run = self.start(
            [
                dict(
                    id="check",
                    expect="interpreter executes",
                    argv=[sys.executable, "-V"],
                )
            ]
        )
        self.cli("check", run)

    def test_submodule_working_files_without_git_metadata_invalidate_receipts(self):
        # A gitlink with a populated directory and no inner .git metadata can
        # occur when someone restores just the files of a deinitialized module.
        self.git(
            "update-index",
            "--add",
            "--cacheinfo",
            "160000",
            self.git("rev-parse", "HEAD").decode().strip(),
            "engine",
        )
        self.git("commit", "-qm", "record submodule")
        engine = self.repo / "engine"
        engine.mkdir()
        run = self.start(
            [
                dict(
                    id="healthy",
                    expect="engine returns ready",
                    argv=[
                        sys.executable,
                        "-c",
                        "from engine import value; assert value.state=='ready'",
                    ],
                )
            ]
        )
        (engine / "value.py").write_text("state = 'ready'")
        self.cli("check", run)
        (engine / "value.py").write_text("state = 'broken'")
        self.assertEqual(
            self.cli("status", run, code=2)["claims"]["healthy"]["status"], "STALE"
        )
        self.cli("check", run, code=1)

    def test_project_local_skill_install_verifies_release_contents(self):
        prefix = self.home / "local"
        skills = self.repo / ".agents/skills"
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "install.py"),
                "--prefix",
                str(prefix),
                "--skill-dir",
                str(skills),
            ],
            check=True,
            capture_output=True,
        )
        executable = skills / "software-factory/scripts/factory"
        contract = self.home / "contract.json"
        contract.write_text(
            json.dumps(
                [
                    dict(
                        id="python",
                        expect="python available",
                        argv=[sys.executable, "-V"],
                    )
                ]
            )
        )

        def installed(*args, code=0):
            result = subprocess.run(
                [executable, *args],
                cwd=self.repo,
                env=self.env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, code, (result.stdout, result.stderr))
            return json.loads(result.stdout or result.stderr)

        run = installed(
            "start", "--task", "verify local installation", "--contract", str(contract)
        )["run"]
        self.assertEqual(installed("check", run)["status"], "VERIFIED")
        # Losing owner execute changes the usable CLI even while Git-style
        # "any executable bit" stays true. Directory access also affects use.
        for target, bit in [(executable, 0o100), (executable.parent, 0o040)]:
            with self.subTest(target=target):
                original = target.stat().st_mode
                target.chmod(original ^ bit)
                try:
                    status = self.cli("status", run, code=2)
                    self.assertEqual(status["claims"]["python"]["status"], "STALE")
                finally:
                    target.chmod(original)
                self.assertEqual(installed("status", run)["status"], "VERIFIED")
        (skills / "software-factory/SKILL.md").write_text("changed after verification")
        self.assertIn("release", installed("status", run, code=2)["error"].lower())
        foreign = self.home / "unmanaged"
        foreign.mkdir()
        link = skills / "software-factory"
        link.unlink()
        link.symlink_to(foreign, target_is_directory=True)
        self.assertEqual(self.cli("status", run, code=2)["status"], "BLOCKED")

    def test_release_upgrade_and_rollback(self):
        clone = self.home / "factory-source"
        shutil.copytree(ROOT / "skills", clone / "skills")
        shutil.copy(ROOT / "install.py", clone / "install.py")
        real_prefix = self.home / "real-prefix"
        real_prefix.mkdir()
        prefix = self.home / "prefix"
        prefix.symlink_to(real_prefix, target_is_directory=True)
        cmd = [
            sys.executable,
            str(clone / "install.py"),
            "--prefix",
            str(prefix),
            "--skill-dir",
            str(self.home / "skills"),
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        current = prefix / "lib/software-factory/current"
        first = current.resolve()
        (clone / "skills/software-factory/SKILL.md").write_text("updated fixture")
        subprocess.run(cmd, check=True, capture_output=True)
        self.assertNotEqual(first, current.resolve())
        subprocess.run(cmd + ["--rollback"], check=True, capture_output=True)
        self.assertEqual(first, current.resolve())
        self.assertIn(
            "0.1.0",
            subprocess.check_output([prefix / "bin/factory", "--version"], text=True),
        )

    def test_install_and_foreign_file_preservation(self):
        prefix = self.home / "user"
        skills = self.home / "agent/skills"
        cmd = [
            sys.executable,
            str(ROOT / "install.py"),
            "--prefix",
            str(prefix),
            "--skill-dir",
            str(skills),
        ]
        subprocess.run(cmd + ["--dry-run"], check=True, capture_output=True)
        self.assertFalse(prefix.exists())
        for attempt in range(2):
            subprocess.run(cmd, check=True, capture_output=True)
        version = subprocess.check_output(
            [prefix / "bin/factory", "--version"], text=True
        )
        self.assertIn("0.1.0", version)
        self.assertTrue((skills / "software-factory/SKILL.md").is_file())
        (prefix / "bin/factory").unlink()
        (prefix / "bin/factory").write_text("user-owned")
        self.assertNotEqual(
            subprocess.run(cmd + ["--remove"], capture_output=True).returncode, 0
        )
        self.assertEqual((prefix / "bin/factory").read_text(), "user-owned")
        (prefix / "bin/factory").unlink()
        subprocess.run(cmd + ["--remove"], check=True, capture_output=True)
        self.assertFalse((skills / "software-factory").is_symlink())
