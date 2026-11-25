"""Exercise live consensus, simplification and review using a disposable local Git remote.

With no role options this qualifies the default pairing on a machine with both
harnesses. Pass role specs to qualify another assignment.
"""

import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from unittest.mock import patch

FACTORY = str(Path(__file__).resolve().parents[1] / "factory")
REQUIREMENT = "Preserve price and total for integer cents and finite iterables of integer cents. Keep the existing rounding rule, iteration order, and ValueError message for negative input."


def check_auto_shell(out):
    """Measure the interpreter environment inside a real Claude Code Bash child."""
    sys.path.insert(0, str(Path(FACTORY).resolve().parent))
    from harness import run_turn

    repo = out / "shell-probe"
    repo.mkdir()
    (repo / "sample.py").write_text("VALUE = 17\n")
    (repo / "check.py").write_text(
        "import json, os, pathlib, sample\n"
        "assert sample.VALUE == 17\n"
        "keys = ['PYTHONDONTWRITEBYTECODE', 'FACTORY_PROBE_CONTROL']\n"
        "pathlib.Path('observed').write_text(json.dumps([os.getenv(k) for k in keys]))\n"
    )
    # A conflicting preference distinguishes Factory's setting from inheritance.
    control = os.urandom(8).hex()
    with patch.dict(os.environ, PYTHONDONTWRITEBYTECODE="0", FACTORY_PROBE_CONTROL=control):
        run_turn(
            "claude", model="opus", repo=repo, edit=True, local_shell=True,
            output_dir=out / "shell-probe-call",
            prompt="Use Bash to run exactly python3 check.py once in this directory. "
                   "Leave files and environment settings as supplied. Report the result.",
        )
    observed = json.loads((repo / "observed").read_text())
    if observed != ["1", control] or list(repo.glob("__pycache__/*.pyc")):
        raise RuntimeError("Real Auto Bash did not preserve the Python cache setting")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        type=Path,
        help="New directory for a disposable checkout, remote and receipts",
    )
    role_flags = ("reviewer", "simplifier", "a", "b")
    for role in role_flags:
        parser.add_argument(f"--{role}", metavar="SPEC", help=f"role spec for {role}")
    args = parser.parse_args()
    chosen = {
        role: [f"--{role}", spec]
        for role in role_flags
        if (spec := getattr(args, role))
    }
    if not chosen and subprocess.run([FACTORY, "doctor", "--profile", "paired"]).returncode:
        return 2
    out = args.output.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    if (args.simplifier or "claude").startswith("claude"):
        check_auto_shell(out)
    repo = out / "checkout"
    repo.mkdir()
    env = {**os.environ, "FACTORY_STATE_DIR": str(out / "state")}

    def git(*args):
        return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()

    def factory(name, *args, allowed=(0,)):
        proc = subprocess.run(
            [FACTORY, *args], cwd=repo, env=env, text=True, stdout=subprocess.PIPE
        )
        (out / (name + ".json")).write_text(proc.stdout)
        if proc.returncode not in allowed:
            print(proc.stdout, file=sys.stderr)
            raise SystemExit(proc.returncode)
        return json.loads(proc.stdout)

    git("init", "-q", "-b", "trunk")
    git("config", "user.email", "fixture@example.invalid")
    git("config", "user.name", "Factory fixture")
    (repo / "prices.py").write_text(
        "def price(cents):\n    if cents < 0:\n        raise ValueError('negative')\n    return (cents + 5) // 10\n"
    )
    (repo / ".gitignore").write_text("__pycache__/\n")
    git("add", "prices.py", ".gitignore")
    git("commit", "-qm", "baseline")
    base = git("rev-parse", "HEAD")
    git("switch", "-qc", "change")
    with (repo / "prices.py").open("a") as file:
        file.write(
            "\ndef total(values):\n    amounts = []\n    for cents in values:\n"
            "        if cents < 0:\n            raise ValueError('negative')\n"
            "        amounts.append((cents + 5) // 10)\n    return sum(amounts)\n"
        )
    git("commit", "-qam", "implement totals")
    first = git("rev-parse", "HEAD")
    remote = out / "origin.git"
    git("init", "--bare", "-q", str(remote))
    git("remote", "add", "fixture", str(remote))
    oracle = out / "consumer.py"
    oracle.write_text(
        "import sys,os\nsys.path.insert(0,os.getcwd())\nfrom prices import price,total\n"
        "assert [price(x) for x in (4,5,14,15)]==[0,1,1,2]\n"
        "assert total(iter([4,5,14,15]))==4 and total([])==0\n"
        "assert total([10**50]) == (10**50 + 5) // 10\n"
        "def with_negative():\n    yield 10\n    yield -1\n    raise AssertionError('consumed past negative')\n"
        "try: total(with_negative())\nexcept ValueError as e: assert str(e)=='negative'\nelse: raise AssertionError('accepted negative')\n"
        "print('Passed rounding boundaries, one-shot iteration, empty input, large integers, first negative and exact error.')\n"
    )
    contract = out / "contract.json"
    contract.write_text(
        json.dumps([dict(id="consumer", expect=REQUIREMENT, oracle=str(oracle))])
    )
    run = factory(
        "start",
        "start",
        "--task",
        REQUIREMENT,
        "--contract",
        str(contract),
        "--require-review",
        "--base",
        base,
    )["run"]
    factory(
        "design",
        "consensus",
        "design",
        *chosen.get("a", []),
        *chosen.get("b", []),
        "--task",
        REQUIREMENT + " Choose the simplest maintainable shared calculation.",
    )
    diagnosis = factory(
        "diagnosis",
        "consensus",
        "diagnosis",
        *chosen.get("a", []),
        *chosen.get("b", []),
        "--task",
        "A customer reports a sporadic slow checkout. No request, timing, workload or trace is available. Determine what cause the evidence supports.",
    )
    if diagnosis.get("disposition") != "INCONCLUSIVE":
        raise RuntimeError(
            "Diagnosis asserted a cause without the required observation"
        )
    result = factory(
        "rounds",
        "simplify",
        *chosen.get("simplifier", []),
        "--base",
        base,
        "--task",
        REQUIREMENT,
        "--check",
        shlex.join([sys.executable, "-E", "-B", str(oracle)]),
        "--push",
        "fixture",
    )
    rounds = result["rounds"]
    head = git("rev-parse", "HEAD")
    if (
        len(rounds) != 3
        or len({r["session_id"] for r in rounds}) != 3
        or any(r["remote_head"] != r["output"] for r in rounds)
        or git("--git-dir", str(remote), "rev-parse", "change") != head
    ):
        raise RuntimeError("Missing distinct sessions or remote checkpoints")
    factory("checks", "check", run, allowed=(2,))
    gate = factory("gate", "review", run, *chosen.get("reviewer", []))
    if gate["status"] != "VERIFIED" or gate["review"] != "CLEAR":
        raise RuntimeError("Final behavior or review gate is incomplete")
    if first == head:
        print(
            "Three no-change rounds completed; actual edit capability remains unobserved.",
            file=sys.stderr,
        )
        return 2
    print(
        f"Verified live roles, three checkpoints and reviewed consumer behavior at {head}. "
        f"Reviewer: {gate['review_receipt']['reviewer']['harness']}. "
        f"Simplifier: {result['simplifier']['harness']}. Evidence in {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
