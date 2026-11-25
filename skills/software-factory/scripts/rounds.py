"""Run checkpointed simplification rounds in a clean Git worktree."""

import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
import uuid

from checkpoints import (
    Pending,
    branch_ref,
    candidate,
    changed,
    check_branch,
    commit_checked_tree,
    digest,
    git,
    published,
    push_checkpoint,
    push_destination,
    qualify_legacy_checkouts,
    rev,
)
from harness import run_turn
import roles
from supervision import captured_check, turn_stopped
from workspace import (
    snapshot,
    state_root,
    workspace_lock,
    write_json as save,
)


PROMPT = (
    Path(__file__).resolve().parents[1]
    / "references/reconsider-from-first-principles.v1.txt"
)
# In this profile the simplifier has file tools and no shell.
LEGACY_PROFILE = "codex-opus-simplify/1"
PROFILES = (LEGACY_PROFILE, "codex-opus-simplify/2", "simplify/3")
PROFILE = PROFILES[-1]
SIMPLIFIER_BEFORE_ROLES = {
    "role": "simplifier",
    "harness": "claude",
    "selector": "opus",
    "model": "opus",
    "source": "saved run",
    "reductions": [],
}


def work_root():
    return state_root() / "simplify"


def owner_path(repo):
    return work_root() / "owners" / digest(os.fsencode(repo))


def last_writer(repo):
    """Name the simplifier whose completed run produced the checked-out commit."""
    try:
        run = json.loads(
            (
                work_root()
                / owner_path(str(Path(repo).resolve())).read_text().strip()
                / "state.json"
            ).read_text()
        )
        rounds = run["rounds"]
        if (
            run["status"] != "complete"
            or rounds[-1]["output"] != rev(repo, "HEAD")
            or all(r["output"] == r["input"] for r in rounds)
            or git(repo, "status", "--porcelain").strip()
        ):
            return None
    except (OSError, ValueError, KeyError, IndexError, RuntimeError, subprocess.SubprocessError):
        return None
    return saved_simplifier(run)["harness"], run["id"]


def saved_simplifier(run):
    return run.get("simplifier") or SIMPLIFIER_BEFORE_ROLES


def create_run(args, repo):
    if not args.base or not (args.task and args.task.strip()) or not args.check:
        raise Pending(
            "Starting a run requires --base, --task and at least one --check."
        )
    if args.timeout <= 0:
        raise Pending("--timeout must be greater than zero.")
    check_commands = [shlex.split(c) for c in args.check]
    if any(not c for c in check_commands):
        raise Pending("A check command must contain an executable.")
    ref = branch_ref(repo)
    binding = roles.simplifier(roles.Policy(repo), explicit=args.simplifier)
    print(roles.describe(binding), file=sys.stderr, flush=True)
    run = {
        "profile": PROFILE,
        "simplifier": binding,
        "id": str(uuid.uuid4()),
        "repo": str(repo),
        "branch_ref": ref,
        "branch": ref.removeprefix("refs/heads/"),
        "task": args.task,
        "checks": check_commands,
        "timeout": args.timeout,
        "remote": args.push,
        "rounds": [],
        "target_rounds": args.rounds or 3,
        "commit_subject": args.commit_subject,
        "status": "active",
    }
    check_branch(run)
    if changed(run, establish=True):
        raise Pending(
            "Start from a clean committed work branch, or use a separate clean worktree."
        )
    run["start"] = rev(repo, "HEAD")
    base_ref = rev(repo, args.base + "^{commit}")
    run["base"] = os.fsdecode(git(repo, "merge-base", base_ref, run["start"])).strip()
    original = git(
        repo, "diff", "--name-only", "--no-renames", "-z", run["base"], run["start"]
    )
    run["allow"] = sorted({os.fsdecode(p) for p in original.split(b"\0") if p})
    for name in args.allow or []:
        path = Path(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or ".git" in path.parts
        ):
            raise Pending("--allow expects a repository-relative file or subdirectory.")
        run["allow"].append(path.as_posix())
    if run["remote"]:
        if run["base"] == run["start"] and not run["allow"]:
            raise Pending("The selected branch has no scoped changes to publish.")
        url = push_destination(repo, run["remote"])
        run["destination"] = digest(os.fsencode(url))
        run["original_remote"] = published(run)
        if run["original_remote"]:
            git(
                repo,
                "merge-base",
                "--is-ancestor",
                run["original_remote"],
                run["start"],
            )
    owner = owner_path(str(repo))
    owner.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if owner.exists():
        old = owner.read_text().strip()
        prior = json.loads((work_root() / old / "state.json").read_text())
        if prior["status"] not in {"complete", "released"}:
            raise Pending(f"Run {old} owns this worktree. Resume or release it first.")
    folder = work_root() / run["id"]
    folder.mkdir(mode=0o700)
    prompt = PROMPT.read_bytes()
    (folder / "prompt.txt").write_bytes(prompt)
    run["prompt_sha256"] = digest(prompt)
    save(folder / "state.json", run)
    pointer = owner.with_name(owner.name + ".tmp")
    pointer.write_text(run["id"])
    pointer.replace(owner)
    return folder, run


def call_context(run, record, folder):
    diff = folder / f"round-{record['number']}-input.diff"
    if not diff.exists():
        diff.write_bytes(
            git(
                run["repo"],
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--full-index",
                run["base"],
                record["input"],
            )
        )
    # The restricted file tools cannot read our private state directory. The
    # harness delivers this separate context as a file with no argv size limit.
    delta = diff.read_text(encoding="utf-8", errors="replace")
    tools = (
        "Use local Bash for inspection and repository tests as needed. Keep temporary test output "
        "outside the source tree or in its existing ignored build paths. Leave Git mutations, "
        "publication, external graders and the independent checks to the coordinator."
        if run["profile"] != LEGACY_PROFILE
        else "The coordinator owns shell, Git and validation."
    )
    return (
        f"You are the sole product-code writer for round {record['number']}. Worktree: {run['repo']}. "
        f"Frozen acceptance contract: {run['task']}\nBase: {run['base']}. Input commit: {record['input']}. "
        f"Permitted file paths/subtrees: {json.dumps(run['allow'])}. "
        "Read applicable AGENTS.md and repository instructions. Edit only when you can explain "
        "how a change preserves the contract and reduces complexity. Keeping the design is valid. "
        "Review comments and docstrings in the branch delta. Remove narration. If a comment "
        "justifies an internal workaround, inspect the symbol and simplify it within scope. "
        "For a recurring mistake, prefer a clearer API or a focused executable check, reusing "
        "existing checks before adding a regression test. Keep distinct observable guarantees "
        "when simplifying tests, and keep one-time probes outside the suite. "
        "Preserve public contracts, legal notices, required directives and verified external constraints. "
        f"{tools} End this turn with an explanation of "
        "what changed and what needs verification. The actual check results follow in this session.\n"
        f"Branch delta:\n{delta}"
    )


def assess_prompt(record, folder):
    records = []
    for check in record["checks"]:
        with (folder / check["log"]).open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 4000))
            tail = f.read().decode(errors="replace")
        records.append(
            f"{check['argv']!r} exited {check['exit']}. Output tail:\n{tail}"
        )
    return (
        "Assess the coordinator's check results for your changes. State the behavior covered, "
        "what became simpler, and limitations. If satisfied, end with exactly STATUS: VERIFIED. "
        "If a repair is needed, explain why and end with exactly STATUS: REPAIR. "
        "Use the reported exit codes and output below as your test evidence. Check scripts and logs "
        "can be outside the worktree. Do not open those paths. When the output does not identify "
        "the cases exercised, say which coverage is unknown. This assessment turn is read-only.\n"
        + "\n".join(records)
    )


def stopped(path):
    # run_turn records its intent before it can launch a supervisor.
    return not path.exists() or turn_stopped(json.loads(path.read_text()))


def contact(run, record, folder, kind, prompt, context):
    session = record.get("session_id")
    call_name = f"r{record['number']}-call-{len(record['calls']) + 1}"
    record["calls"].append(
        {
            "name": call_name,
            "kind": kind,
            "prompt_sha256": digest(prompt.encode()),
            "resume": session,
        }
    )
    record["phase"] = "calling"
    save(folder / "state.json", run)
    binding = saved_simplifier(run)
    run_turn(
        binding["harness"],
        repo=Path(run["repo"]),
        prompt=prompt,
        context=context,
        model=binding["model"],
        selector=binding["selector"],
        session_id=session,
        edit=kind != "assess",
        local_shell=run["profile"] != LEGACY_PROFILE and kind != "assess",
        output_dir=folder / call_name,
    )


def consume_call(run, record, folder, recover):
    call = record["calls"][-1]
    receipt_path = folder / call["name"] / "receipt.json"
    if not receipt_path.exists():
        # The adapter persists its starting receipt before spawning a provider.
        if not recover:
            raise Pending(
                "This call has no launch receipt. Inspect the workspace and use --recover to retry."
            )
        record["phase"] = call["kind"]
        save(folder / "state.json", run)
        return
    receipt = json.loads(receipt_path.read_text())
    binding = saved_simplifier(run)
    if receipt.get("status") != "success":
        if not recover or not stopped(receipt_path):
            raise Pending(
                f"Interrupted {call['kind']} turn. Inspect {receipt_path} and the worktree; "
                "use --recover only after reconciling the stopped call."
            )
        if call["kind"] == "initial" and not record.get("session_id"):
            if changed(run):
                raise Pending(
                    "Preserve the interrupted edits and reconcile back to the clean round input before a fresh attempt."
                )
            record["phase"] = "initial"
        else:
            record["phase"] = "checks" if call["kind"] == "repair" else "assess"
        save(folder / "state.json", run)
        return
    if (
        receipt["prompt_sha256"] != call["prompt_sha256"]
        or receipt.get("provider") != binding["harness"]
        or receipt.get("model_requested") != binding["model"]
    ):
        raise Pending("The saved harness response does not match this request.")
    session = receipt["session_id"]
    if not session or (record.get("session_id") and session != record["session_id"]):
        raise Pending("The simplifier session changed within a round.")
    if any(old.get("session_id") == session for old in run["rounds"][:-1]):
        raise Pending("The simplifier reused a previous round's context.")
    reported = receipt.get("model_reported")
    harness_compared = "model_identity" in receipt
    if (
        not harness_compared
        and reported
        and binding["model"]
        and binding["model"].lower() not in reported.lower()
    ):
        raise Pending(f"The harness reported a different model: {reported}.")
    record.update(session_id=session, model_reported=reported)
    text = receipt["text"].strip()
    if call["kind"] == "assess":
        last = text.splitlines()[-1] if text else ""
        if last == "STATUS: VERIFIED" and all(c["exit"] == 0 for c in record["checks"]):
            record["phase"] = "commit"
        elif last in {"STATUS: REPAIR", "STATUS: VERIFIED"}:
            record["phase"] = "repair"
        else:
            if not recover:
                raise Pending(
                    "The simplifier returned no valid final assessment. Inspect the receipt and use "
                    "--recover to request a corrected assessment."
                )
            record["phase"] = "assess"
    else:
        record["phase"] = "checks"
    save(folder / "state.json", run)


def check_candidate(run, record, folder):
    before, _ = candidate(run, folder)
    working_inputs = snapshot(run["repo"], worktree_only=True)
    record["checks"] = []
    n = uuid.uuid4().hex[:10]
    attempt = {"tree": before, "checks": record["checks"]}
    record.setdefault("check_history", []).append(attempt)
    save(folder / "state.json", run)
    for i, cmd in enumerate(run["checks"], 1):
        if rev(run["repo"], "HEAD") != record["input"]:
            raise Pending("The checked-out revision changed before the next check.")
        path = folder / f"r{record['number']}-{n}-check-{i}.log"
        outcome, code, reason = captured_check(cmd, run["repo"], path, run["timeout"])
        record["checks"].append(
            {
                "argv": cmd,
                "exit": code,
                "outcome": outcome,
                "reason": reason,
                "log": path.name,
            }
        )
        save(folder / "state.json", run)
        if outcome == "BLOCKED":
            raise Pending(
                f"Could not complete {cmd!r}: {reason}. Inspect {path} and resume."
            )
        after, _ = candidate(run, folder)
        if before != after or rev(run["repo"], "HEAD") != record["input"]:
            raise Pending(
                "Checks changed the candidate or its revision. Inspect the changes and resume."
            )
        if snapshot(run["repo"], worktree_only=True) != working_inputs:
            raise Pending(
                "Checks changed the working inputs. Inspect the changes and resume."
            )
    record.update(tree=before, working_inputs=working_inputs, phase="assess")
    save(folder / "state.json", run)


def ensure_checked_working_inputs(run, record):
    if "working_inputs" in record and (
        snapshot(run["repo"], worktree_only=True) != record["working_inputs"]
    ):
        raise Pending("Working inputs changed after checks. Restore the checked candidate before resuming.")


def ensure_publishable_checkpoint(run, record):
    if changed(run):
        raise Pending("Worktree or branch moved before the checkpoint was confirmed.")
    ensure_checked_working_inputs(run, record)
    check_branch(run)
    if rev(run["repo"], "HEAD") != record["output"]:
        raise Pending("Worktree or branch moved before the checkpoint was confirmed.")


def execute(run, folder, recover=False, accepted_head=None):
    prompt_bytes = (folder / "prompt.txt").read_bytes()
    if digest(prompt_bytes) != run["prompt_sha256"]:
        raise Pending("The pinned simplification prompt has changed.")
    prompt = prompt_bytes.decode()
    while True:
        check_branch(run)
        if not run["rounds"] or run["rounds"][-1]["phase"] == "done":
            previous = run["rounds"][-1]["output"] if run["rounds"] else run["start"]
            if rev(run["repo"], "HEAD") != previous or changed(run):
                raise Pending("The worktree no longer matches the last checkpoint.")
            if len(run["rounds"]) == run.get("target_rounds", 3):
                run["status"] = "complete"
                save(folder / "state.json", run)
                return
            run["rounds"].append(
                {
                    "number": len(run["rounds"]) + 1,
                    "input": previous,
                    "phase": "initial",
                    "calls": [],
                }
            )
            save(folder / "state.json", run)
        record = run["rounds"][-1]
        phase = record["phase"]
        if (
            phase not in {"commit", "publish"}
            and rev(run["repo"], "HEAD") != record["input"]
        ):
            raise Pending("The checked-out revision changed mid-round.")
        if phase == "initial":
            if changed(run):
                raise Pending("A fresh round needs its clean input revision.")
            contact(
                run,
                record,
                folder,
                "initial",
                prompt,
                call_context(run, record, folder),
            )
        elif phase == "calling":
            consume_call(run, record, folder, recover)
            recover = False
        elif phase == "checks":
            check_candidate(run, record, folder)
        elif phase == "assess":
            if candidate(run, folder)[0] != record["tree"]:
                raise Pending(
                    "Candidate changed after checks. Inspect it before continuing."
                )
            ensure_checked_working_inputs(run, record)
            assessment = assess_prompt(record, folder)
            check_branch(run)
            if rev(run["repo"], "HEAD") != record["input"]:
                raise Pending("The checked-out revision changed before assessment.")
            contact(run, record, folder, "assess", assessment, "")
        elif phase == "repair":
            repairs = sum(c["kind"] == "repair" for c in record["calls"])
            if repairs >= 2:
                raise Pending(
                    "Two repair attempts exhausted for this round. Inspect its checks and report."
                )
            contact(
                run,
                record,
                folder,
                "repair",
                "Implement the scoped repair you identified from the check results. "
                "The coordinator will rerun validation in this session.",
                "",
            )
        elif phase == "commit":
            if rev(run["repo"], "HEAD") == record["input"]:
                ensure_checked_working_inputs(run, record)
            output = commit_checked_tree(run, record, folder, accepted_head)
            record.update(output=output, phase="publish")
            save(folder / "state.json", run)
            accepted_head = None
        elif phase == "publish":
            ensure_publishable_checkpoint(run, record)
            if run["remote"]:
                expected = (
                    run["original_remote"]
                    if record["number"] == 1
                    else run["rounds"][-2]["remote_head"]
                )
                record["remote_head"] = push_checkpoint(run, expected, record["output"])
                ensure_publishable_checkpoint(run, record)
            record["phase"] = "done"
            record["finished"] = time.time()
            save(folder / "state.json", run)
        else:
            raise Pending(f"Unknown phase {phase!r}.")


def report(run, folder):
    return {
        "id": run["id"],
        "status": run["status"],
        "branch": run["branch"],
        "profile": run["profile"],
        "simplifier": saved_simplifier(run),
        "state": str(folder / "state.json"),
        "target_rounds": run.get("target_rounds", 3),
        "rounds": [
            {
                k: record[k]
                for k in (
                    "number",
                    "phase",
                    "session_id",
                    "model_reported",
                    "input",
                    "output",
                    "remote_head",
                )
                if k in record
            }
            for record in run["rounds"]
        ],
    }


def emit_status(run, folder):
    result = report(run, folder)
    if run["status"] in {"complete", "active"}:
        try:
            qualify_legacy_checkouts(run)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            result.update(
                status="pending", recorded_status=run["status"], error=str(exc)
            )
            print(json.dumps(result))
            return 2
    if run["status"] == "complete":
        wanted = run["rounds"][-1]["output"]
        try:
            check_branch(run)
            observed = rev(run["repo"], "HEAD")
            result["current_head"] = observed
            current = observed == wanted and not changed(run)
            if run["remote"]:
                result["current_remote_head"] = published(run)
                current = current and result["current_remote_head"] == wanted
            if not current:
                result.update(status="stale", recorded_status="complete")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            result.update(status="pending", recorded_status="complete", error=str(exc))
    print(json.dumps(result))
    return 0 if result["status"] == "complete" else 2


def validate_arguments(args):
    """Reject flag combinations before any state is read or locked."""
    subject = args.commit_subject
    if subject is not None and (
        len(subject.splitlines()) != 1 or subject != subject.strip()
    ):
        raise Pending("--commit-subject must be a single nonempty trimmed line.")
    sha = args.accept_checkpoint
    if sha is not None and (
        len(sha) not in (40, 64) or any(c not in "0123456789abcdef" for c in sha)
    ):
        raise Pending(
            "--accept-checkpoint requires a full lowercase hexadecimal commit SHA."
        )
    if not args.resume:
        if args.recover or args.release or args.status or sha:
            raise Pending("--recover, --release and --status need --resume RUN_ID.")
        return
    if sha and (args.status or args.release or subject is not None):
        raise Pending("Use --accept-checkpoint only to reconcile an existing commit.")
    if subject is not None and not args.recover:
        raise Pending("Changing a rejected checkpoint subject requires --recover.")
    saved = (args.repo, args.base, args.task, args.check, args.allow, args.push)
    if any(saved) or args.rounds or args.simplifier:
        raise Pending(
            "A resumed run uses its saved contract, commands, simplifier and "
            "publication target."
        )


def release(run, folder):
    if run["rounds"] and run["rounds"][-1]["phase"] == "calling":
        last = run["rounds"][-1]["calls"][-1]
        if not stopped(folder / last["name"] / "receipt.json"):
            raise Pending(
                "A harness writer may still be active. Verify its process first."
            )
    run["status"] = "released"
    save(folder / "state.json", run)


def apply_resume_options(run, folder, args, repo):
    """Validate explicit checkpoint recovery against the active run's current round."""
    current = run["rounds"][-1] if run["rounds"] else {}
    if args.accept_checkpoint:
        head = rev(repo, "HEAD")
        if (
            current.get("phase") != "commit"
            or head == current.get("input")
            or args.accept_checkpoint != head
        ):
            raise Pending(
                "--accept-checkpoint must name the full current SHA of the pending checkpoint."
            )
    if args.commit_subject is not None:
        check_branch(run)
        expected = current.get("output") or current.get("input") or run["start"]
        if current.get("phase") == "publish" or rev(repo, "HEAD") != expected:
            raise Pending(
                "A new subject applies only before the checkpoint is committed."
            )
        run["commit_subject"] = args.commit_subject
        save(folder / "state.json", run)


def handle(args):
    folder = None
    try:
        validate_arguments(args)
        if args.resume:
            folder = work_root() / str(uuid.UUID(args.resume))
            run = json.loads((folder / "state.json").read_text())
            if args.status:
                return emit_status(run, folder)
            repo = Path(run["repo"])
        else:
            repo = Path(
                os.fsdecode(
                    git(args.repo or ".", "rev-parse", "--show-toplevel")
                ).strip()
            ).resolve()
        with workspace_lock(repo):
            if folder:
                # Reread under the lock; another coordinator may have advanced it.
                run = json.loads((folder / "state.json").read_text())
                if run["profile"] not in PROFILES:
                    raise Pending("Unsupported run profile.")
                if run["status"] != "active":
                    return emit_status(run, folder)
                if owner_path(run["repo"]).read_text().strip() != run["id"]:
                    raise Pending("This worktree belongs to another run.")
                if args.release:
                    release(run, folder)
                    print(json.dumps(report(run, folder)))
                    return 2
                qualify_legacy_checkouts(run)
                apply_resume_options(run, folder, args, repo)
            else:
                folder, run = create_run(args, repo)
            execute(run, folder, args.recover, args.accept_checkpoint)
            print(json.dumps(report(run, folder)))
            return 0
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
        print(
            json.dumps(
                {
                    "status": "pending",
                    "error": str(exc),
                    "run": folder.name if folder else None,
                }
            )
        )
        return 2


def register(subparsers):
    p = subparsers.add_parser("simplify", description=__doc__)
    p.add_argument(
        "--rounds", type=int, choices=(1, 2, 3), help="fresh simplifier rounds (default 3)"
    )
    p.add_argument(
        "--simplifier",
        metavar="SPEC",
        help="HARNESS[:MODEL] or :MODEL for this run, such as claude:frontier",
    )
    p.add_argument(
        "--commit-subject", help="checkpoint subject required by the target repository"
    )
    p.add_argument("--repo", help="target worktree (default current directory)")
    p.add_argument("--base", help="starting branch base or SHA")
    p.add_argument("--task", help="frozen requirements and relevant facts")
    p.add_argument(
        "--check",
        action="append",
        help="required check as quoted argv; repeat to add checks",
    )
    p.add_argument(
        "--allow",
        action="append",
        help="additional repository-relative path or subtree allowed for edits",
    )
    p.add_argument(
        "--push",
        metavar="REMOTE",
        help="push each completed round to this named remote",
    )
    p.add_argument(
        "--timeout", type=int, default=300, help="seconds per verification command"
    )
    p.add_argument(
        "--accept-checkpoint",
        metavar="FULL_SHA",
        help="resume after inspecting an unmarked checkpoint commit",
    )
    p.add_argument("--resume", metavar="RUN_ID")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="inspect a saved run")
    group.add_argument(
        "--recover",
        action="store_true",
        help="acknowledge and reconcile an interrupted turn",
    )
    group.add_argument(
        "--release",
        action="store_true",
        help="retire a stopped run, preserving its edits",
    )
    p.set_defaults(func=handle)
