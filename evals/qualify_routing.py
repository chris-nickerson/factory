"""Sample how Codex selects Factory procedures from a fresh project session."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CASES = {
    "checks": (
        "Use Software Factory to check the parser behavior I specify. I only want local checks and no review.",
        "local",
        False,
    ),
    "diagnosis": (
        "Find the root cause with a second model that investigates independently. Stay read-only.",
        "consensus diagnosis",
        False,
    ),
    "simplify": (
        "Have fresh Opus sessions simplify this branch. Keep the result local.",
        "simplify",
        False,
    ),
    "narrowed": (
        "Simplify this branch with Opus and push each round. One correction before you start: keep every round local.",
        "simplify",
        False,
    ),
    "publish": (
        "Have fresh Opus sessions simplify this branch. Push every checked checkpoint to origin.",
        "simplify",
        True,
    ),
}
SCHEMA = {
    "type": "object",
    "properties": {
        "skill": {"type": "string"},
        "procedure": {
            "enum": ["local", "consensus diagnosis", "simplify", "other"],
        },
        "publish": {"type": "boolean"},
    },
    "required": ["skill", "procedure", "publish"],
    "additionalProperties": False,
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory for traces and the report")
    parser.add_argument("--case", choices=CASES, action="append")
    parser.add_argument("--model")
    parser.add_argument("--trials", type=int, default=1)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("--trials must be positive")
    out = args.output.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    repo = out / "project"
    repo.mkdir()
    subprocess.run(
        [sys.executable, ROOT / "install.py", "--prefix", out / "tools",
         "--skill-dir", repo / ".agents/skills"],
        check=True, capture_output=True,
    )
    schema = out / "result-schema.json"
    schema.write_text(json.dumps(SCHEMA))
    version = subprocess.check_output(["codex", "--version"], text=True).strip()
    revision = subprocess.check_output(
        ["git", "-C", ROOT, "rev-parse", "HEAD"], text=True
    ).strip()

    def sample(job):
        name, trial = job
        prompt, route, publish = CASES[name]
        prefix = out / f"{name}-{trial}"
        argv = [
            "codex", "--no-daemon", "-a", "never", "exec", "--ephemeral",
            "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            "--sandbox", "read-only", "--disable", "apps", "--disable", "plugins",
            "--disable", "hooks", "--disable", "multi_agent", "--disable",
            "multi_agent_v2", "-c", "mcp_servers={}", "--json", "--output-schema",
            schema, "-o", prefix.with_suffix(".json"),
        ]
        if args.model:
            argv.extend(["--model", args.model])
        with prefix.with_suffix(".jsonl").open("w") as events, prefix.with_suffix(".stderr").open("w") as errors:
            result = subprocess.run(
                [*argv, "-"],
                cwd=repo,
                text=True,
                stdout=events,
                stderr=errors,
                input=(
                    "Read the request as a coding agent in this project. Select the installed skill and procedure "
                    "you would use. Report whether the latest request authorizes publication. "
                    "Read any guidance you need, and stop before running the selected procedure.\n\n"
                    + prompt
                ),
            )
        observed = json.loads(prefix.with_suffix(".json").read_text()) if result.returncode == 0 else None
        expected = dict(skill="software-factory", procedure=route, publish=publish)
        return dict(case=name, trial=trial, observed=observed, expected=expected,
                    cli_exit=result.returncode, passed=observed == expected)

    cases = dict.fromkeys(args.case or CASES)
    jobs = [(name, trial) for name in cases for trial in range(1, args.trials + 1)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        samples = list(pool.map(sample, jobs))
    report = dict(codex=version, model_requested=args.model, checkout_head=revision, samples=samples)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(not all(sample["passed"] for sample in samples))


if __name__ == "__main__":
    sys.exit(main())
