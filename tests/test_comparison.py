import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


CLI = Path(__file__).resolve().parents[1] / "factory"


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.before = Path(directory.name) / "before"
        self.after = Path(directory.name) / "after"
        for checkout in (self.before, self.after):
            checkout.mkdir()
            (checkout / "output").write_bytes(b"\xff\x00")

    def compare(self, script, code):
        result = subprocess.run(
            [
                CLI,
                "compare",
                "--before",
                self.before,
                "--after",
                self.after,
                "--trials",
                "2",
                "--",
                sys.executable,
                "-c",
                script,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, code, result.stderr)
        return json.loads(result.stdout)

    def test_replay_measures_only_matching_successful_work(self):
        caller = "import sys; sys.stdout.buffer.write(open('output','rb').read())"
        report = self.compare(caller, 0)
        self.assertEqual(report["status"], "MATCH")
        self.assertEqual(
            [s["side"] for s in report["samples"]],
            ["before", "after", "after", "before"],
        )
        self.assertTrue(all(s["stdout_bytes"] == 2 for s in report["samples"]))
        (self.after / "output").write_bytes(b"\xfe\x00")
        report = self.compare(caller, 1)
        self.assertEqual(report["status"], "OUTPUT_CHANGED")
        self.assertNotIn("elapsed_ms", report)
        (self.after / "output").unlink()
        report = self.compare(caller, 1)
        self.assertEqual(report["status"], "COMMAND_FAILED")
        self.assertIn("FileNotFoundError", report["samples"][-1]["stderr_tail"])
