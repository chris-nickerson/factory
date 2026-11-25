"""Sample how a host agent selects Factory procedures from a fresh project session."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import re
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
# A request that names a model has no tier to choose. Its role spec is scored.
MODEL_NAMED_BY_USER = "opus"
CASES = {
    "existing-pr-round-limit": (
        "Use Software Factory to babysit this existing PR for exactly one round and publish its fixes. You fixed failed CI, "
        "pushed the fix and read back the new head, approval, open threads and replacement checks. "
        "Those checks are running. I only asked for this round.",
        "PR review workflow", True,
    ),
    "delivery-start": (
        "Use Factory to agree on a design with a second model, implement a new button, "
        "and give me a PR ready for human review with a screenshot. The implementation agent "
        "may only edit locally; you own publication. Nothing has run yet.",
        "full delivery", True,
    ),
    "delivery-local": (
        "Use two models to agree on a design, implement it, simplify it and run the "
        "independent review and final checks. Keep everything local. Nothing has started.",
        "full delivery", False,
    ),
    "delivery-pending": (
        "Use Factory to deliver the review-ready PR we agreed on. The design consensus was "
        "confirmed. A simplification session has just started. Unit tests pass, but browser "
        "sign-in failed before reaching the new screen. You inspected an image of the generated PDF. "
        "The draft PR links to it. What has run, and do we have a screenshot?",
        "full delivery", True,
    ),
    "delivery-local-recording": (
        "Deliver the agreed PR with a recording reviewers can watch. Design, simplification, "
        "final checks, independent review and CI finished. The PR is ready. You inspected "
        "the screen recording locally and saw the requested action succeed. Reviewers confirmed the laptop link does not open.",
        "full delivery", True,
    ),
    "delivery-ready": (
        "Deliver the agreed review-ready PR and stop for human review. Design was confirmed; "
        "all simplification rounds finished. The checks and independent review passed on the "
        "pushed head. The forge shows a ready PR with green CI and a recording of the new "
        "screen in use. You have opened the recording. Only human approval remains.",
        "full delivery", True,
    ),
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
        "Have fresh model sessions simplify this branch. Keep the result local.",
        "simplify",
        False,
    ),
    "narrowed": (
        "Simplify this branch with Opus and push each round. One correction before you start: keep every round local.",
        "simplify",
        False,
        MODEL_NAMED_BY_USER,
    ),
    "review": (
        "Use Software Factory to get an independent review of this change from a model that didn't write it. Don't change any files.",
        "local",
        False,
    ),
    "publish": (
        "Have fresh Opus sessions simplify this branch. Push every checked checkpoint to origin.",
        "simplify",
        True,
        MODEL_NAMED_BY_USER,
    ),
    "hard-design": (
        "We have to move billing from the monolith to its own service while three other services "
        "keep writing to the same tables, and we can't undo the cutover once customers are invoiced. "
        "Have two models work out the migration design independently. Stay read-only.",
        "consensus design",
        False,
        "frontier",
    ),
    "routine-design": (
        "Have two models decide whether this small helper should return None or raise on a missing key. Stay read-only.",
        "consensus design",
        False,
    ),
}
SCHEMA = {
    "type": "object",
    "properties": {
        "skill": {"type": "string"},
        "procedure": {
            "enum": ["local", "consensus design", "consensus diagnosis", "simplify", "full delivery", "PR review workflow", "other"],
        },
        "publish": {"type": "boolean"},
        "tier": {
            "enum": ["role default", "frontier", "standard"],
            "description": "The model tier you would pass to the procedure's command.",
        },
        "role_spec": {
            "type": "string",
            "description": "The role flag and value you would pass to choose a "
            "harness or model, such as --simplifier claude:opus. Empty if none.",
        },
    },
    "required": ["skill", "procedure", "publish", "tier", "role_spec"],
    "additionalProperties": False,
}

DELIVERY_DECISIONS = {
    "existing-pr-round-limit": ("report round limit", False),
    "delivery-start": ("obtain design consensus", False),
    "delivery-pending": ("continue verification", False),
    "delivery-local": ("obtain design consensus", False),
    "delivery-local-recording": ("publish UI evidence", True),
    "delivery-ready": ("hand off to human", True),
}
DELIVERY_SCHEMA = {
    **SCHEMA,
    "properties": {
        **{key: SCHEMA["properties"][key] for key in ("skill", "procedure", "publish")},
        "next_action": {"enum": ["report round limit", "obtain design consensus", "implement", "continue verification", "publish UI evidence", "end before the requested stopping point", "hand off to human"]},
        "inspected_screen_capture": {"type": "boolean", "description": "You inspected a capture showing the requested screen and action, wherever it is stored."},
    },
    "required": ["skill", "procedure", "publish", "next_action", "inspected_screen_capture"],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="New directory for traces and the report")
    parser.add_argument("--case", choices=CASES, action="append")
    parser.add_argument("--model")
    parser.add_argument(
        "--host", choices=("codex", "claude"), default="codex",
        help="agent CLI that reads the skill and selects the procedure",
    )
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
    delivery_schema = out / "delivery-schema.json"
    delivery_schema.write_text(json.dumps(DELIVERY_SCHEMA))
    version = subprocess.check_output([args.host, "--version"], text=True).strip()
    if args.host == "claude":
        # Claude Code discovers project skills in .claude/skills.
        (repo / ".claude").mkdir()
        (repo / ".claude/skills").symlink_to(repo / ".agents/skills")
    revision = subprocess.check_output(
        ["git", "-C", ROOT, "rev-parse", "HEAD"], text=True
    ).strip()

    def sample(job):
        name, trial = job
        prompt, route, publish, *tier = CASES[name]
        prefix = out / f"{name}-{trial}"
        if name in DELIVERY_DECISIONS:
            selected_schema = delivery_schema
            question = "What should you do next? Have you inspected a capture of the requested screen and action?"
        else:
            selected_schema = schema
            question = "Which model tier and role flag would you pass?"
        argv = [
            "codex", "--no-daemon", "-a", "never", "exec", "--ephemeral",
            "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check",
            "--sandbox", "read-only", "--disable", "apps", "--disable", "plugins",
            "--disable", "hooks", "--disable", "multi_agent", "--disable",
            "multi_agent_v2", "-c", "mcp_servers={}", "--json", "--output-schema",
            selected_schema, "-o", prefix.with_suffix(".json"),
        ]
        if args.host == "claude":
            argv = [
                "claude", "--print", "--strict-mcp-config", "--mcp-config",
                '{"mcpServers":{}}', "--tools", "Read,Glob,Grep,Skill",
                "--permission-mode", "dontAsk", "--output-format", "json",
                "--json-schema", selected_schema.read_text(),
            ]
        if args.model:
            argv.extend(["--model", args.model])
        with prefix.with_suffix(".jsonl").open("w") as events, prefix.with_suffix(".stderr").open("w") as errors:
            result = subprocess.run(
                argv if args.host == "claude" else [*argv, "-"],
                cwd=repo,
                text=True,
                stdout=events,
                stderr=errors,
                input=(
                    "Read the request as a coding agent in this project. Select the installed skill and procedure "
                    "you would use. Report whether the latest request authorizes publication. "
                    f"{question} "
                    "Read any guidance you need, and stop before running the selected procedure.\n\n"
                    + prompt
                ),
            )
        observed = None
        if result.returncode == 0 and args.host == "claude":
            observed = json.loads(prefix.with_suffix(".jsonl").read_text()).get("structured_output")
        elif result.returncode == 0:
            observed = json.loads(prefix.with_suffix(".json").read_text())
        tier = tier[0] if tier else "role default"
        expected = dict(skill="software-factory", procedure=route, publish=publish)
        if name in DELIVERY_DECISIONS:
            expected["next_action"], expected["inspected_screen_capture"] = DELIVERY_DECISIONS[name]
        elif tier != MODEL_NAMED_BY_USER:
            expected["tier"] = tier
        else:
            (observed or {}).pop("tier", None)
        role_spec = (observed or {}).pop("role_spec", "")
        named_model_kept = tier != MODEL_NAMED_BY_USER or bool(
            re.fullmatch(rf"--simplifier[ =](claude)?:{MODEL_NAMED_BY_USER}", role_spec.strip())
        )
        return dict(case=name, trial=trial, observed=observed, expected=expected,
                    role_spec=role_spec, cli_exit=result.returncode,
                    passed=observed == expected and named_model_kept)

    cases = dict.fromkeys(args.case or CASES)
    jobs = [(name, trial) for name in cases for trial in range(1, args.trials + 1)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        samples = list(pool.map(sample, jobs))
    report = dict(host=args.host, host_version=version, model_requested=args.model, checkout_head=revision, samples=samples)
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return int(not all(sample["passed"] for sample in samples))


if __name__ == "__main__":
    sys.exit(main())
