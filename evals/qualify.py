"""Run a live local task against a disposable fixture and an external behavioral oracle."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FACTORY = ROOT / "factory"

WEB = """<!doctype html><html lang="en"><title>Release notes</title>
<a href="#details" id="open" role="button" aria-expanded="false">Show details</a>
<p id="details" hidden>Version 2</p>
<script>
const toggle = document.querySelector('#open');
toggle.onclick = e => {
  e.preventDefault();
  const details = document.querySelector('#details');
  details.hidden = !details.hidden;
  toggle.setAttribute('aria-expanded', String(!details.hidden));
};
</script></html>
"""
WEB_CHECK = """
const assert = require('node:assert/strict');
const {chromium} = require(process.env.FACTORY_PLAYWRIGHT || 'playwright');
const {pathToFileURL} = require('node:url');
(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  try {
    const page = await browser.newPage();
    await page.goto(pathToFileURL(process.cwd() + '/index.html').href);
    const toggle = page.getByRole('button', {name:'Show details'});
    const details = page.locator('#details');
    assert.equal(await details.isVisible(), false);
    await page.keyboard.press('Tab');
    assert.equal(await toggle.evaluate(el => el === document.activeElement), true);
    for (const key of ['Space','Enter']) {
      await page.keyboard.press(key);
      assert.equal(await details.isVisible(), true, key + ' expands');
      assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
      await page.keyboard.press(key);
      assert.equal(await details.isVisible(), false, key + ' collapses');
    }
    await toggle.click();
    assert.equal(await details.isVisible(), true, 'pointer expands');
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exitCode=1});
"""
LIB = '''def parse_duration(text):
    """Return total minutes for H:MM durations."""
    hours, minutes = text.split(":")
    if len(minutes) != 2 or not minutes.isascii() or not minutes.isdigit() or int(minutes) > 59:
        raise ValueError("expected H:MM")
    return int(hours) * 60 + int(minutes)
'''
LIB_CHECK = """
import itertools, os, sys
sys.path.insert(0, os.getcwd())
from duration import parse_duration
for h, m in itertools.product((0,1,12,72,111),(0,8,32,59)):
    assert parse_duration(f'{h}:{m:02d}') == 60*h+m
for value in ('-1:30','+1:05',' 1:23','1:60','1:0','１:00','1:１２',':20','2.5:00'):
    try:
        parse_duration(value)
    except ValueError:
        continue
    raise AssertionError(f'accepted invalid duration {value!r}')
"""


def call(args, cwd, **kwargs):
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", choices=("library", "web"))
    parser.add_argument(
        "output",
        type=Path,
        help="New directory for the checkout, evidence and transcript",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Run a comparison without invoking the Factory skill",
    )
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, mode=0o700, exist_ok=False)
    repo = out / "project"
    repo.mkdir()
    env = {
        **os.environ,
        "FACTORY_STATE_DIR": str(out / "state"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    call(["git", "init", "-qb", "fixture"], repo, check=True)
    (repo / ".gitignore").write_text(".agents/\n__pycache__/\n")
    if args.case == "library":
        (repo / "duration.py").write_text(LIB)
        oracle = out / "consumer.py"
        oracle.write_text(LIB_CHECK)
        command = [sys.executable, str(oracle)]
        task = "Fix parse_duration. Accept H:MM with one or more ASCII digits for hours and exactly two ASCII digits from 00 to 59 for minutes. Reject signs and whitespace with ValueError. Preserve valid durations including hours above 24."
    else:
        (repo / "index.html").write_text(WEB)
        oracle = out / "keyboard.cjs"
        oracle.write_text(WEB_CHECK)
        command = ["node", str(oracle)]
        task = "Fix the Show details control. A keyboard user should reach it with Tab and toggle it with Space or Enter. Preserve pointer behavior, the accessible name, and aria-expanded."
    call(["git", "add", "."], repo, check=True)
    call(
        [
            "git",
            "-c",
            "user.name=Factory fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "commit",
            "-qm",
            "baseline",
        ],
        repo,
        check=True,
    )
    before = call(command, repo, env=env)
    (out / "before.txt").write_text(before.stdout + before.stderr)
    if before.returncode == 0 or ("AssertionError" not in before.stderr):
        raise RuntimeError(
            f"Expected a behavioral baseline failure. Inspect {out / 'before.txt'}"
        )
    prompt = (
        task
        + " Work locally in this disposable repository. Verify the result. Do not commit or push."
    )
    run = None
    if not args.direct:
        skilldir = repo / ".agents/skills"
        call(
            [
                sys.executable,
                str(ROOT / "install.py"),
                "--prefix",
                str(out / "tools"),
                "--skill-dir",
                str(skilldir),
            ],
            repo,
            check=True,
        )
        contract = out / "contract.json"
        # Use the frozen Python oracle for the library. Node requires a command locator.
        claim = {"oracle": str(oracle)} if args.case == "library" else {"argv": command}
        contract.write_text(json.dumps([dict(id="consumer", expect=task, **claim)]))
        result = call(
            [
                str(FACTORY),
                "start",
                "--task",
                task,
                "--contract",
                str(contract),
                "--require-review",
                "--base",
                "HEAD",
            ],
            repo,
            env=env,
            check=True,
        )
        run = json.loads(result.stdout)["run"]
        baseline = call([str(FACTORY), "check", run], repo, env=env)
        if baseline.returncode != 1:
            raise RuntimeError("Factory missed the red baseline")
        prompt = (
            f"Use the software-factory skill in .agents/skills/software-factory. {prompt} "
            f"Continue the existing Factory run {run}. Set FACTORY_STATE_DIR={out / 'state'} for the CLI. "
            "A separate independent reviewer will run after your handoff; leave that step to the caller."
        )
    (out / "state").mkdir(exist_ok=True)
    cmd = [
        "codex",
        "--no-daemon",
        "-a",
        "never",
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "workspace-write",
        "--disable",
        "apps",
        "--disable",
        "plugins",
        "--disable",
        "hooks",
        "--disable",
        "multi_agent",
        "-c",
        "mcp_servers={}",
        "--ephemeral",
        "--json",
        "--add-dir",
        str(out / "state"),
        "-",
    ]
    started = time.monotonic()
    (out / "request.txt").write_text(prompt)
    with (
        (out / "events.jsonl").open("w") as events,
        (out / "stderr.txt").open("w") as errors,
    ):
        proc = subprocess.Popen(
            cmd,
            cwd=repo,
            env=env,
            text=True,
            stdin=subprocess.PIPE,
            stdout=events,
            stderr=errors,
            start_new_session=True,
        )
        try:
            proc.communicate(prompt, timeout=300)
        except BaseException:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            raise
    with tempfile.TemporaryDirectory() as private:
        held_back = Path(private) / oracle.name
        if args.case == "library":
            held_back.write_text(
                LIB_CHECK.replace("(0,1,12,72,111)", "(3,11,23,108,126)")
            )
        else:
            held_back.write_text(
                WEB_CHECK.replace("['Space','Enter']", "['Enter','Space','Space']")
            )
        after = call([command[0], str(held_back)], repo, env=env)
    (out / "after.txt").write_text(after.stdout + after.stderr)
    report = dict(
        case=args.case,
        profile="direct" if args.direct else "factory",
        implementation_seconds=round(time.monotonic() - started, 1),
        baseline_exit=before.returncode,
        agent_exit=proc.returncode,
        behavioral_exit=after.returncode,
    )
    if run:
        check = call([str(FACTORY), "check", run], repo, env=env)
        review = call([str(FACTORY), "review", run], repo, env=env)
        (out / "gate.json").write_text(review.stdout or review.stderr)
        report.update(
            run=run, pre_review_exit=check.returncode, final_exit=review.returncode
        )
    (out / "result.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))
    return int(
        any(report[k] for k in ("agent_exit", "behavioral_exit"))
        or report.get("final_exit", 0) != 0
    )


if __name__ == "__main__":
    sys.exit(main())
