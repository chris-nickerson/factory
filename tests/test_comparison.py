import json
from statistics import median
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

    def compare(self, code, *argv, options=()):
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
                *options,
                "--",
                *argv,
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, code, result.stderr)
        return json.loads(result.stdout)

    def test_replay_measures_only_matching_successful_work(self):
        caller = "import os; os.write(1, open('output','rb').read()); os.lseek(1, 0, 0)"
        report = self.compare(0, sys.executable, "-c", caller)
        self.assertEqual(report["status"], "MATCH")
        self.assertEqual(
            [s["side"] for s in report["samples"]],
            ["before", "after", "after", "before"],
        )
        self.assertTrue(all(s["stdout_bytes"] == 2 for s in report["samples"]))
        for side, summary in report["elapsed_ms"].items():
            samples = [r["elapsed_ms"] for r in report["samples"] if r["side"] == side]
            self.assertEqual(
                summary,
                dict(min=min(samples), median=median(samples), max=max(samples)),
            )
        self.assertEqual(set(report["elapsed_ms"]), {"before", "after"})
        caller = "import sys; sys.stdout.buffer.write(open('output','rb').read())"
        (self.after / "output").write_bytes(b"\xfe\x00")
        report = self.compare(1, sys.executable, "-c", caller)
        self.assertEqual(report["status"], "OUTPUT_CHANGED")
        self.assertNotIn("elapsed_ms", report)
        (self.after / "output").unlink()
        report = self.compare(1, sys.executable, "-c", caller)
        self.assertEqual(report["status"], "COMMAND_FAILED")
        self.assertIn("FileNotFoundError", report["samples"][-1]["stderr_tail"])

    def test_missing_candidate_entry_point_preserves_baseline(self):
        driver = self.before / "driver"
        driver.write_text("#!/bin/sh\necho ready\n")
        driver.chmod(0o755)
        report = self.compare(2, "./driver")
        self.assertEqual(
            (report["status"], report["side"], report["trial"]), ("BLOCKED", "after", 1)
        )
        self.assertEqual([s["side"] for s in report["samples"]], ["before"])

    def test_deadline_stops_before_the_other_checkout(self):
        report = self.compare(
            2,
            sys.executable,
            "-c",
            "import time; time.sleep(30)",
            options=["--timeout", "1"],
        )
        self.assertEqual(
            (report["status"], report["side"], report["samples"]),
            ("BLOCKED", "before", []),
        )
        self.assertIn("timed out", report["error"])
