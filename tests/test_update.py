"""Exercise the installed updater from an unrelated repo against a real Git remote."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


class UpdateTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.source = self.home / "factory source"
        self.source.mkdir()
        self.remote = self.home / "personal.git"
        self.remote.mkdir()
        git(self.remote, "init", "-q", "--bare", "-b", "main")
        git(self.source, "init", "-q", "-b", "main")
        git(self.source, "config", "user.name", "Fixture")
        git(self.source, "config", "user.email", "fixture@example.invalid")
        git(self.source, "remote", "add", "origin", "../personal.git")
        shutil.copytree(
            ROOT / "skills",
            self.source / "skills",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        shutil.copyfile(ROOT / "install.py", self.source / "install.py")
        git(self.source, "add", ".")
        git(self.source, "commit", "-qm", "Initial release")
        git(self.source, "push", "-q", "origin", "main")

        self.prefix = self.home / "custom prefix"
        self.skill_dir = self.home / "custom skills"
        self.skill = self.skill_dir / "software-factory"
        self.exe = self.prefix / "bin/factory"
        self.installer = [
            sys.executable,
            str(self.source / "install.py"),
            "--prefix",
            str(self.prefix),
            "--skill-dir",
            str(self.skill_dir),
        ]
        subprocess.run(self.installer, capture_output=True, check=True)
        self.original = self.skill.resolve()
        self.caller = self.home / "other"
        self.caller.mkdir()
        git(self.caller, "init", "-q", "-b", "feature")
        git(self.caller, "remote", "add", "origin", str(self.home / "nonexistent"))
        (self.caller / "wip").write_text("in progress")
        git(self.caller, "add", "wip")

    def update(self, code=0):
        result = subprocess.run(
            [str(self.exe), "update"],
            cwd=self.caller,
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_DIR": str(self.caller / ".git"),
                "GIT_WORK_TREE": str(self.caller),
            },
        )
        self.assertEqual(result.returncode, code, (result.stdout, result.stderr))
        return json.loads(result.stdout or result.stderr)

    def test_updates_from_recorded_main_and_preserves_local_work_and_rollback(self):
        spec = self.source / "skills/software-factory/SKILL.md"
        spec.write_text("new main release")
        git(self.source, "commit", "-qam", "Updated release")
        sha = git(self.source, "rev-parse", "HEAD")
        git(self.source, "push", "-q", "origin", "main")
        git(self.source, "switch", "-qc", "local-work")
        spec.write_text("unpublished work")
        source_status = git(self.source, "status", "--porcelain")
        caller_status = git(self.caller, "status", "--porcelain")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.update(), range(2)))
        self.assertCountEqual([r["status"] for r in results], ["updated", "up_to_date"])
        self.assertEqual({r["commit"] for r in results}, {sha})
        self.assertEqual({r["release"] for r in results}, {str(self.skill.resolve())})
        self.assertEqual(self.exe.resolve(), self.skill.resolve() / "scripts/factory")
        self.assertEqual((self.skill / "SKILL.md").read_text(), "new main release")
        self.assertEqual(spec.read_text(), "unpublished work")
        self.assertEqual(source_status, git(self.source, "status", "--porcelain"))
        self.assertEqual(git(self.source, "branch", "--show-current"), "local-work")
        self.assertEqual(caller_status, git(self.caller, "status", "--porcelain"))
        self.assertEqual((self.caller / "wip").read_text(), "in progress")
        subprocess.run(self.installer + ["--rollback"], capture_output=True, check=True)
        self.assertEqual(self.skill.resolve(), self.original)

    def test_missing_main_and_invalid_release_leave_installation_intact(self):
        git(self.remote, "tag", "main", "refs/heads/main")
        git(self.remote, "update-ref", "-d", "refs/heads/main")
        self.assertEqual(self.update(code=2)["status"], "BLOCKED")
        self.assertEqual(self.original, self.skill.resolve())
        git(self.source, "rm", "-q", "skills/software-factory/scripts/factory")
        git(self.source, "commit", "-qm", "Incomplete release")
        git(self.source, "push", "-q", "origin", "refs/heads/main:refs/heads/main")
        self.assertIn("missing", self.update(code=2)["error"])
        self.assertEqual(self.original, self.skill.resolve())
        git(
            self.source,
            "restore",
            "--source=HEAD~",
            "--staged",
            "--worktree",
            "skills/software-factory/scripts/factory",
        )
        git(self.source, "rm", "-q", "skills/software-factory/scripts/workspace.py")
        git(self.source, "commit", "-qm", "Missing CLI dependency")
        git(self.source, "push", "-q", "origin", "refs/heads/main:refs/heads/main")
        self.assertIn("failed to start", self.update(code=2)["error"])
        self.assertEqual(self.original, self.skill.resolve())
        subprocess.run([self.exe, "--version"], check=True, capture_output=True)
