"""Local contracts, captured behavioral checks and revision-bound review."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import uuid

from harness import ADAPTERS, run_turn
import roles
from rounds import last_writer
from supervision import captured_check as run_command
from workspace import (
    ensure_visible_index,
    check_state_location,
    git,
    repo_root,
    snapshot,
    state_root,
    workspace_lock,
    write_json,
)


def file_digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run_path(run):
    if not re.fullmatch(r"[0-9a-f]{32}", run):
        raise ValueError("Expected the local run ID returned by start")
    return state_root() / "runs" / run


def load(path):
    data = json.loads((path / "state.json").read_text())
    if data["schema"] != 1:
        raise ValueError("Unsupported run format")
    return data


def checked_cwd(repo, name):
    directory = (repo / name).resolve(strict=True)
    if not directory.is_dir() or not directory.is_relative_to(repo):
        raise ValueError(f"Check directory outside workspace: {name}")
    return directory


def parse_contract(path, repo):
    raw = json.loads(path.read_text())
    if not isinstance(raw, list) or not raw:
        raise ValueError("Contract must be a nonempty JSON array")
    claims = {}
    for entry in raw:
        if not isinstance(entry, dict) or set(entry) - {
            "id",
            "expect",
            "argv",
            "cwd",
            "oracle",
        }:
            raise ValueError(
                "Invalid claim fields (use id, expect, argv or oracle, optional cwd)"
            )
        key = entry.get("id", "")
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[\w.-]+", key)
            or key in claims
        ):
            raise ValueError("Claim IDs must be unique nonempty identifiers")
        expected = entry.get("expect")
        if not isinstance(expected, str) or not expected.strip():
            raise ValueError(f"{key} needs an observable expectation")
        cwd = entry.get("cwd", ".")
        checked_cwd(repo, cwd)
        claim = dict(expect=expected, cwd=cwd)
        if ("argv" in entry) == ("oracle" in entry):
            raise ValueError(f"{key} needs exactly one of argv or oracle")
        if "argv" in entry:
            argv = entry["argv"]
            if (
                not isinstance(argv, list)
                or not argv
                or not all(isinstance(a, str) for a in argv)
                or not argv[0]
            ):
                raise ValueError(f"Invalid argv for {key}")
            claim["argv"] = argv
        else:
            oracle = (path.parent / entry["oracle"]).resolve(strict=True)
            claim["oracle"] = oracle.read_text()
            claim["source"] = str(oracle)
        claims[key] = claim
    return claims


def start(args):
    repo = repo_root(args.repo)
    check_state_location(repo)
    claims = parse_contract(args.contract.resolve(), repo)
    paths = []
    for value in args.path:
        item = Path(value)
        if (
            item.is_absolute()
            or ".." in item.parts
            or ".git" in item.parts
            or not item.parts
        ):
            raise ValueError(
                "Review paths must name a file or subtree relative to the workspace root"
            )
        paths.append(item.as_posix())
    base = None
    if args.base or args.require_review:
        base = (
            git(
                repo,
                "rev-parse",
                "--verify",
                "--end-of-options",
                (args.base or "HEAD") + "^{commit}",
            )
            .stdout.decode()
            .strip()
        )
    with workspace_lock(repo):
        identity = snapshot(repo)
        run = uuid.uuid4().hex
        folder = run_path(run)
        folder.mkdir(parents=True, mode=0o700)
        data = dict(
            schema=1,
            id=run,
            task=args.task,
            repo=str(repo),
            initial_subject=identity,
            base=base,
            paths=paths,
            claims=claims,
            require_review=args.require_review,
            attempts=[],
            reviews=[],
        )
        write_json(folder / "state.json", data)
    return dict(
        run=run,
        repo=str(repo),
        subject=identity,
        claims=list(claims),
        state=str(folder),
    ), 0


def check(args):
    folder = run_path(args.run)
    repo = Path(load(folder)["repo"])
    with workspace_lock(repo):
        data = load(folder)
        ids = args.claim or list(data["claims"])
        if set(ids) - data["claims"].keys() or args.timeout <= 0:
            raise ValueError("Unknown claim or nonpositive timeout")
        if args.remaining:
            report, code = summary(folder, data, snapshot(repo))
            ids = [key for key, row in report["claims"].items() if row["status"] != "PASS"]
            if not ids:
                return report, code
        for key in ids:
            claim = data["claims"][key]
            index = len(data["attempts"]) + 1
            subject = snapshot(repo)
            log = folder / f"check-{index}-{uuid.uuid4().hex[:8]}.log"
            cwd = checked_cwd(repo, claim["cwd"])
            if "oracle" in claim:
                script = folder / f"oracle-{key}.py"
                script.write_text(claim["oracle"])
                argv = [sys.executable, "-E", "-B", str(script)]
            else:
                argv = claim["argv"]
            entry = dict(
                id=key,
                subject=subject,
                argv=argv,
                cwd=str(cwd),
                log=log.name,
                started=time.time(),
                status="PENDING",
            )
            data["attempts"].append(entry)
            write_json(folder / "state.json", data)
            outcome, rc, reason = run_command(argv, cwd, log, args.timeout)
            if snapshot(repo) != subject:
                outcome, reason = (
                    "BLOCKED",
                    "Workspace changed during check. Inspect changes and rerun.",
                )
            entry.update(
                status=outcome,
                returncode=rc,
                reason=reason,
                finished=time.time(),
                sha256=file_digest(log),
            )
            write_json(folder / "state.json", data)
        return summary(folder, data, snapshot(repo))


def summary(folder, data, subject):
    rows = {}
    for key, claim in data["claims"].items():
        entry = next((e for e in reversed(data["attempts"]) if e["id"] == key), None)
        status = "PENDING"
        if entry:
            status = entry["status"] if entry["subject"] == subject else "STALE"
            log = folder / entry["log"]
            if status in {"PASS", "FAIL"} and (
                not log.is_file() or file_digest(log) != entry.get("sha256")
            ):
                status = "BLOCKED"
        rows[key] = dict(expect=claim["expect"], status=status, latest=entry)
    review = data["reviews"][-1] if data["reviews"] else None
    review_status = "PENDING" if data["require_review"] else "OPTIONAL"
    if review:
        review_status = review["status"] if review["subject"] == subject else "STALE"
        if review_status in {"CLEAR", "FINDINGS"}:
            receipt = folder / review["report"]
            if not receipt.is_file() or file_digest(receipt) != review["sha256"]:
                review_status = "BLOCKED"
    states = [r["status"] for r in rows.values()]
    if "FAIL" in states or review_status == "FINDINGS":
        result, code = "FAILED", 1
    elif any(s != "PASS" for s in states) or review_status not in {"CLEAR", "OPTIONAL"}:
        result, code = "INCOMPLETE", 2
    else:
        result, code = "VERIFIED", 0
    return dict(
        run=data["id"],
        task=data["task"],
        repo=data["repo"],
        subject=subject,
        status=result,
        claims=rows,
        review=review_status,
        review_reductions=(review or {}).get("reviewer", {}).get("reductions", []),
        review_receipt=review,
        artifacts=str(folder),
    ), code


def status(args):
    folder = run_path(args.run)
    repo = Path(load(folder)["repo"])
    with workspace_lock(repo):
        return summary(folder, load(folder), snapshot(repo))


def outcome(args):
    folder = run_path(args.run)
    with workspace_lock(load(folder)["repo"]):
        data = load(folder)
        outcomes = data.get("outcomes", [])
        attempts = [a for a in data["attempts"] if "finished" in a]
        reviews = [r for r in data["reviews"] if r.get("report")]
        subjects = sorted({r["subject"] for r in attempts + reviews})
        if args.note is None:
            if args.subject is not None or args.evidence is not None:
                raise ValueError(
                    "Use --note to attach feedback with a subject or evidence reference"
                )
            return dict(run=args.run, subjects=subjects, outcomes=outcomes), 0

        note = args.note.strip()
        if not note:
            raise ValueError("Describe the observed outcome in --note")
        if not subjects:
            raise ValueError("Record a check or review before attaching an outcome")
        subject = args.subject
        if subject is None:
            if len(subjects) != 1:
                raise ValueError(
                    "Several revisions have evidence. Choose --subject from: "
                    + ", ".join(subjects)
                )
            subject = subjects[0]
        if subject not in subjects:
            raise ValueError(
                "The selected subject has no recorded evidence in this run"
            )

        evidence = args.evidence.strip() if args.evidence is not None else None
        if evidence == "":
            raise ValueError("Supply a nonempty evidence reference")
        for entry in outcomes:
            if (entry["subject"], entry["note"], entry["evidence"]) == (
                subject,
                note,
                evidence,
            ):
                return dict(run=args.run, outcome=entry), 0
        entry = dict(
            id=uuid.uuid4().hex,
            subject=subject,
            note=note,
            evidence=evidence,
            recorded=time.time(),
            checks=[a["log"] for a in attempts if a["subject"] == subject],
            reviews=[r["report"] for r in reviews if r["subject"] == subject],
        )
        data.setdefault("outcomes", []).append(entry)
        write_json(folder / "state.json", data)
        return dict(run=args.run, outcome=entry), 0


EMBEDDED_DIFF_MAX_CHARS = 600_000
HARNESS_IMPLIED_BY_MODEL_FLAG = "codex"


def review_writer(repo, policy):
    """Describe who last changed the subject, so the reviewer can differ."""
    simplified = last_writer(repo)
    if simplified:
        harness, run = simplified
        return {
            "vendor": ADAPTERS[harness].vendor,
            "description": f"the simplifier that last changed this branch ({harness})",
            "evidence": f"simplification run {run}",
        }
    host = policy.host["harness"]
    if host:
        return {
            "vendor": ADAPTERS[host].vendor,
            "description": f"the hosting session ({host}), which probably wrote the change",
            "evidence": f"host detected from {policy.host['evidence']}",
        }
    return None


def review(args):
    if args.timeout is not None:
        print(
            "Factory ignores the legacy review time limit. Agent turns run until completion or cancellation.",
            file=sys.stderr,
        )

    folder = run_path(args.run)
    repo = Path(load(folder)["repo"])
    with workspace_lock(repo):
        data = load(folder)
        if not data["base"]:
            raise ValueError(
                "Start with --base or --require-review to freeze a review base"
            )
        subject = snapshot(repo)
        ensure_visible_index(repo)
        base = data["base"]
        paths = data.get("paths", [])

        def diff(form, *revisions):
            return git(
                repo,
                "--literal-pathspecs",
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                form,
                *revisions,
                "--",
                *paths,
            ).stdout.decode(errors="replace")

        staged = diff("--stat", "--cached", base)
        unstaged = diff("--stat")
        new = git(
            repo,
            "--literal-pathspecs",
            "ls-files",
            "--others",
            "--exclude-standard",
            "--",
            *paths,
        ).stdout.decode(errors="replace")
        if not (staged.strip() or unstaged.strip() or new.strip()):
            raise ValueError("Empty change from review base")

        spec = roles.at_tier(args.reviewer, args.tier)
        if args.model:
            harness, model = roles.parse_spec(spec or HARNESS_IMPLIED_BY_MODEL_FLAG)
            if model:
                raise ValueError("Give the reviewer's model once, in --reviewer.")
            spec = f"{harness or ''}:{args.model}"
        receipt = dict(subject=subject, base=base, paths=paths, status="PENDING")
        data["reviews"].append(receipt)
        write_json(folder / "state.json", data)
        try:
            policy = roles.Policy(repo)
            writer = review_writer(repo, policy)
            binding = roles.reviewer(policy, explicit=spec, writer=writer)
        except roles.RoleError as error:
            receipt.update(status="BLOCKED", reason=str(error))
            write_json(folder / "state.json", data)
            return summary(folder, data, snapshot(repo))
        receipt.update(reviewer=binding, writer=writer, host=policy.host)
        reviewer_runs_git = (
            "read_only_shell" in ADAPTERS[binding["harness"]].capabilities
        )
        if not reviewer_runs_git:
            staged = diff("--patch", "--cached", base)
            unstaged = diff("--patch")
        if (
            not reviewer_runs_git
            and len(staged) + len(unstaged) > EMBEDDED_DIFF_MAX_CHARS
        ):
            receipt.update(
                status="BLOCKED",
                reason=f"The change is too large to hand to {binding['harness']}, "
                "which has no shell to read it with. Narrow the review with "
                "--path at start, or choose a reviewer that has a read-only shell.",
            )
            write_json(folder / "state.json", data)
            return summary(folder, data, snapshot(repo))
        inspect = (
            "The complete diffs follow: base to index, then index to worktree, "
            "including staged hunks reversed by unstaged edits. You have no shell. "
            "Read the listed untracked files and the surrounding source with your file tools. "
            if not reviewer_runs_git
            else "Inspect both git diff --cached BASE (base to index) and git diff (index to worktree), "
            "including staged hunks reversed by unstaged edits. "
        )
        prompt = (
            "Perform a fresh read-only correctness and requirements review. Inspect the full git diff against "
            f"{base} scoped to {json.dumps(paths) if paths else 'the full checkout'} plus the listed untracked files. Read surrounding callers and applicable instructions. "
            f"{inspect}The runtime checks exercise the working tree. "
            "For changed tests, identify the observable failure each adds or the guarantee a deletion "
            "would lose. Flag redundant coverage or fragile assertions with a concrete example. "
            "If a change affects what a required check enforces, verify it still rejects a known "
            "violation and accepts valid input under the intended rule. "
            "Check whether a changed comment conceals a workaround or a dropped comment carried a "
            "public contract or external constraint. Report a concrete consequence at the affected symbol. "
            "Give concrete findings and triggers. If you cannot actually inspect the whole change, report BLOCKED. "
            "End with one line exactly VERDICT: CLEAR, VERDICT: FINDINGS, or VERDICT: BLOCKED.\n"
            f"Task: {data['task']}\nRequirements: "
            + json.dumps({k: c["expect"] for k, c in data["claims"].items()})
            + f"\nBase to index:\n{staged}\nIndex to working tree:\n{unstaged}\nUntracked:\n{new}"
        )
        output = folder / f"review-{uuid.uuid4().hex}"
        try:
            result = run_turn(
                binding["harness"],
                repo=repo,
                prompt=prompt,
                model=binding["model"],
                selector=binding["selector"],
                output_dir=output,
            )
            report = folder / f"{output.name}.md"
            report.write_text(result["text"])
            verdict = result["text"].strip().splitlines()[-1]
            value = {"VERDICT: CLEAR": "CLEAR", "VERDICT: FINDINGS": "FINDINGS"}.get(
                verdict, "BLOCKED"
            )
            if snapshot(repo) != subject:
                value = "BLOCKED"
            receipt.update(
                status=value,
                report=report.name,
                sha256=file_digest(report),
                session_id=result["session_id"],
                model_reported=result.get("model_reported"),
                model_identity=result.get("model_identity"),
            )
        except RuntimeError as exc:
            receipt.update(status="BLOCKED", reason=str(exc))
        write_json(folder / "state.json", data)
        return summary(folder, data, snapshot(repo))


def register(sub):
    feedback = sub.add_parser(
        "outcome", help="Read or attach a later observation to a local evidence run"
    )
    feedback.add_argument("run")
    feedback.add_argument("--note", help="Observed behavior, correction, or result")
    feedback.add_argument(
        "--subject", help="Checked subject fingerprint printed by Factory"
    )
    feedback.add_argument(
        "--evidence", help="Optional local artifact or ticket reference, stored as text"
    )
    feedback.set_defaults(action=outcome)

    parser = sub.add_parser("start", help="Freeze a local verification contract")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--task", required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--require-review", action="store_true")
    parser.add_argument("--base", help="Git ref for the full change under review")
    parser.add_argument(
        "--path",
        action="append",
        default=[],
        help="Limit review to this task-owned file or subtree; repeat for multiple paths",
    )
    parser.set_defaults(action=start)
    for name, handler, help_text in (
        ("check", check, "Execute frozen claims and capture results"),
        (
            "status",
            status,
            "Recompute candidate identity and inspect the evidence gate",
        ),
        (
            "review",
            review,
            "Run an independent read-only review of the frozen scope",
        ),
    ):
        parser = sub.add_parser(name, help=help_text)
        parser.add_argument("run")
        if name == "check":
            selection = parser.add_mutually_exclusive_group()
            selection.add_argument("--claim", action="append")
            selection.add_argument(
                "--remaining",
                action="store_true",
                help="Run only claims without a valid pass for the current workspace",
            )
            parser.add_argument(
                "--timeout",
                type=int,
                default=180,
                help="seconds per verification command",
            )
        if name == "review":
            parser.add_argument("--timeout", type=int, help=argparse.SUPPRESS)
            roles.add_tier_option(parser)
            parser.add_argument(
                "--reviewer",
                metavar="SPEC",
                help="HARNESS[:MODEL] or :MODEL for this review, such as claude or :standard",
            )
            parser.add_argument(
                "--model",
                help="reviewer model; without --reviewer, a Codex model as before",
            )
        parser.set_defaults(action=handler)
