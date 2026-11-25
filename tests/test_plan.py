import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).resolve().parents[1] / "factory"


class PlanTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.state = self.root / "state"
        self.contract = self.root / "contract.json"
        self.contract.write_text(json.dumps([{
            "id": "accepted", "expect": "acceptance marker contains yes",
            "argv": [sys.executable, "-c", "assert open('accepted').read() == 'yes'"],
        }]))

    def cli(self, *args, code=0):
        result = subprocess.run(
            [CLI, *args], cwd=self.root, text=True, capture_output=True,
            env=dict(os.environ, FACTORY_STATE_DIR=str(self.state)),
        )
        self.assertEqual(result.returncode, code, (result.stdout, result.stderr))
        return json.loads(result.stdout or result.stderr)

    def verified(self, task):
        repo = self.root / task
        repo.mkdir()
        (repo / "accepted").write_text("yes")
        run = self.cli("start", "--repo", repo, "--task", task, "--contract", self.contract)["run"]
        self.cli("check", run)
        return run

    def plan(self, items, code=0):
        manifest = self.root / "plan.json"
        manifest.write_text(json.dumps(items))
        return self.cli("plan", manifest, code=code)

    def assert_plan(self, items, expected, next_ids):
        report = self.plan(items)
        self.assertEqual({item["id"]: item["state"] for item in report["items"]}, expected)
        self.assertCountEqual(report["next"], next_ids)
        self.assertIs(report["complete"], all(state == "VERIFIED" for state in expected.values()))

    def test_verified_descendant_waits_again_when_ancestor_changes(self):
        api = {"id": "api", "task": "api", "run": self.verified("api")}
        client = {"id": "client", "task": "client", "needs": ["api"], "run": self.verified("client")}
        items = [
            {"id": "release", "task": "release", "needs": ["client"]}, client, api,
            {"id": "docs", "task": "docs"},
        ]
        stale_input = dict(api="VERIFIED", client="ATTENTION", release="WAITING", docs="READY")
        current = dict(api="VERIFIED", client="VERIFIED", release="READY", docs="READY")
        self.assert_plan(items, stale_input, ["client", "docs"])
        client["inputs"] = {"api": self.cli("status", api["run"])["subject"]}
        self.assert_plan(items, current, ["release", "docs"])

        api_schema = self.root / "api" / "schema"
        api_schema.write_text("v2")
        self.assert_plan(
            items, dict(api="ATTENTION", client="WAITING", release="WAITING", docs="READY"),
            ["api", "docs"],
        )
        new_subject = self.cli("check", api["run"])["subject"]
        self.assert_plan(items, stale_input, ["client", "docs"])

        (self.root / "client" / "schema").write_bytes(api_schema.read_bytes())
        self.cli("check", client["run"])
        client["inputs"]["api"] = new_subject
        self.assert_plan(items, current, ["release", "docs"])

    def test_unavailable_receipts_leave_independent_work_ready(self):
        run = self.verified("api")
        items = [
            {"id": "api", "task": "api", "run": run},
            {"id": "missing", "task": "missing", "run": "0" * 32},
            {"id": "release", "task": "release", "needs": ["api", "missing"]},
            {"id": "docs", "task": "docs"},
        ]
        lock, = (self.state / "locks").iterdir()
        with lock.open("a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            self.assert_plan(
                items, dict(api="ATTENTION", missing="ATTENTION", release="WAITING", docs="READY"),
                ["api", "missing", "docs"],
            )

    def test_matching_task_is_required_to_finish(self):
        item = {"id": "api", "task": "another task", "run": self.verified("api")}
        self.assert_plan([item], {"api": "ATTENTION"}, ["api"])
        item["task"] = "api"
        self.assert_plan([item], {"api": "VERIFIED"}, [])

    def test_rejects_ambiguous_and_impossible_plans(self):
        a = {"id": "a", "task": "Build A"}
        for items in (
            [{**a, "run": "a" * 32}, {"id": "b", "task": "B", "run": "a" * 32}],
            [], [a, a], [{**a, "needs": ["unknown"]}], [{**a, "needs": "b"}],
            [{**a, "needs": ["b", "b"]}, {"id": "b", "task": "Build B"}],
            [{**a, "inputs": {}}], [{**a, "run": "a" * 32, "inputs": {"b": "subject"}}],
            [{**a, "needs": ["b"]}, {"id": "b", "task": "Build B", "needs": ["a"]}],
        ):
            with self.subTest(items=items):
                self.assertEqual(self.plan(items, code=2)["status"], "BLOCKED")
