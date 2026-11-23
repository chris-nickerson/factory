"""Run three checkpointed simplification rounds in a clean Git worktree."""

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import time
import uuid

from evidence import run_command
from harness import run_turn
from supervision import captured_process, turn_stopped
from workspace import (
    ensure_visible_index,
    state_root,
    workspace_lock,
    write_json as save,
)


PROMPT = (
    Path(__file__).resolve().parents[1]
    / "references/reconsider-from-first-principles.v1.txt"
)
LEGACY_PROFILE = "codex-opus-simplify/1"
PROFILE = "codex-opus-simplify/2"


class Pending(RuntimeError):
    """Further action or reconciliation is required."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def git(repo, *args, input_data=None, env=None):
    # A checkpoint represents the Git tree's executable mode even if this
    # checkout ordinarily ignores chmod changes.
    command = ["git", "-c", "core.fileMode=true", "--literal-pathspecs", *args]
    if args[0] in {"add", "read-tree", "write-tree", "commit", "push", "ls-remote"}:
        result = captured_process(
            command, cwd=repo, input=input_data, timeout=120, env=env
        )
    else:
        result = subprocess.run(
            ["git", "--no-optional-locks", *command[1:]],
            cwd=repo,
            input=input_data,
            capture_output=True,
            timeout=120,
            env=env,
        )
    if result.returncode:
        # Remote diagnostics can contain credentialed URLs.
        if args[0] in {"remote", "ls-remote", "push"}:
            raise Pending(
                f"git {args[0]} failed (exit {result.returncode}). Check remote access and the target branch."
            )
        raise Pending(
            f"git {args[0]} failed: {os.fsdecode(result.stderr[-1500:]).strip()}"
        )
    return result.stdout


def rev(repo, ref):
    return os.fsdecode(
        git(repo, "rev-parse", "--verify", "--end-of-options", ref)
    ).strip()


def branch_ref(repo):
    ref = os.fsdecode(git(repo, "symbolic-ref", "HEAD")).rstrip("\n")
    if not ref.startswith("refs/heads/"):
        raise Pending("The current worktree is not on a named local branch.")
    return ref


def target_ref(s):
    # Earlier profile-v1 state recorded only the short name.
    return s.get("branch_ref", "refs/heads/" + s["branch"])


def verify_git_visibility(repo):
    """Require Git's tree identity to describe every initialized gitlink's checked-out source."""
    root = Path(repo)
    ensure_visible_index(root)
    entries = git(root, "ls-files", "--stage", "-z")
    initialized = {}
    for entry in entries.split(b"\0"):
        if not entry.startswith(b"160000 "):
            continue
        path = root / os.fsdecode(entry.split(b"\t", 1)[1])
        if path.is_symlink():
            raise Pending(f"Gitlink is replaced by a symlink: {path}")
        key = path.relative_to(root).as_posix()
        initialized[key] = (path / ".git").exists()
        if not initialized[key]:
            if path.exists() and (not path.is_dir() or any(path.iterdir())):
                raise Pending(
                    f"Gitlink has local content without an initialized submodule: {path}"
                )
            continue
        for nested, present in verify_git_visibility(path).items():
            initialized[f"{key}/{nested}"] = present
        if git(
            path,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--ignore-submodules=none",
        ):
            raise Pending(
                f"Submodule contains local changes outside its commit: {path}"
            )

    return initialized


def qualify_legacy_checkouts(s):
    if "submodule_checkouts" in s:
        return
    # A legacy run without gitlinks has a uniquely determined empty baseline.
    # Historical commits matter when a later round removed a dependency.
    repo = s["repo"]
    subjects = {s["start"]}
    for record in s["rounds"]:
        subjects.update(record[key] for key in ("input", "output") if key in record)
    listings = (git(repo, "ls-tree", "-r", "-z", subject) for subject in subjects)
    index = git(repo, "ls-files", "--stage", "-z")
    if any(row.startswith(b"160000 ") for row in index.split(b"\0")) or any(
        row.startswith(b"160000 ")
        for listing in listings
        for row in listing.split(b"\0")
    ):
        guidance = "Start a fresh run from a clean candidate to requalify its dependency checkouts."
        if s["status"] == "active":
            guidance = (
                f"Inspect and preserve pending edits, then run factory simplify --resume {s['id']} "
                f"--release after its writer has stopped. {guidance}"
            )
        raise Pending(
            f"This older run did not record submodule initialization state. {guidance}"
        )
    s["submodule_checkouts"] = {}


def changed(s, *, establish=False):
    repo = s["repo"]
    present = verify_git_visibility(repo)
    if establish:
        s["submodule_checkouts"] = present
    elif present != s.get("submodule_checkouts", {}):
        raise Pending(
            "Submodule checkouts changed. Restore their recorded initialization state before resuming."
        )
    tracked = git(
        repo,
        "diff",
        "--name-only",
        "--no-renames",
        "--ignore-submodules=none",
        "-z",
        "HEAD",
    )
    staged = git(repo, "diff", "--cached", "--name-only", "--no-renames", "-z", "HEAD")
    others = git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(
        {os.fsdecode(p) for p in (tracked + staged + others).split(b"\0") if p}
    )


def check_branch(s):
    repo = s["repo"]
    if branch_ref(repo) != target_ref(s):
        raise Pending(f"Restore work branch {s['branch']} before resuming.")
    gitdir = Path(os.fsdecode(git(repo, "rev-parse", "--absolute-git-dir")).strip())
    markers = (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
        "BISECT_START",
    )
    if any((gitdir / marker).exists() for marker in markers) or git(
        repo, "ls-files", "-u"
    ):
        raise Pending("Finish the active Git operation before simplification.")


def candidate(s, folder):
    repo = s["repo"]
    paths = changed(s)
    outside = [
        p
        for p in paths
        if not any(p == prefix or p.startswith(prefix + "/") for prefix in s["allow"])
    ]
    if outside:
        raise Pending(
            f"Unexpected paths were changed. Preserve and reconcile these edits: {outside!r}"
        )
    if not paths:
        return rev(repo, "HEAD^{tree}"), paths
    with tempfile.TemporaryDirectory(dir=folder) as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        git(repo, "read-tree", "HEAD", env=env)
        stage(repo, paths, env)
        return os.fsdecode(git(repo, "write-tree", env=env)).strip(), paths


def stage(repo, paths, env=None):
    pathspec = b"".join(os.fsencode(p) + b"\0" for p in paths)
    git(
        repo,
        "add",
        "-A",
        "--pathspec-from-file=-",
        "--pathspec-file-nul",
        input_data=pathspec,
        env=env,
    )


def push_destination(repo, remote):
    if (
        remote.startswith("-")
        or remote not in os.fsdecode(git(repo, "remote")).splitlines()
    ):
        raise Pending("Choose the name of an existing Git remote for --push.")
    urls = os.fsdecode(
        git(repo, "remote", "get-url", "--push", "--all", remote)
    ).splitlines()
    if len(urls) != 1 or urls[0].startswith("-"):
        raise Pending("The push profile needs exactly one identifiable push URL.")
    return urls[0]


def bound_destination(s):
    url = push_destination(s["repo"], s["remote"])
    if digest(os.fsencode(url)) != s["destination"]:
        raise Pending(
            "The configured push destination changed. Reconcile the original destination first."
        )
    # Git applies insteadOf to explicit URLs too. Resolve the configured remote
    # once, then bind a fresh remote through a unique single rewrite for both
    # directions. A second configured rewrite of the resolved URL cannot run.
    alias = "factory-" + uuid.uuid4().hex
    marker = "factory-checkpoint://" + alias
    env = os.environ.copy()
    offset = int(env.get("GIT_CONFIG_COUNT", 0))
    bindings = (
        (f"remote.{alias}.url", marker),
        (f"remote.{alias}.pushurl", marker),
        (f"url.{url}.insteadOf", marker),
    )
    for i, (key, value) in enumerate(bindings, offset):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    env["GIT_CONFIG_COUNT"] = str(offset + len(bindings))
    return alias, env


def published(s, destination=None):
    alias, env = destination or bound_destination(s)
    ref = target_ref(s)
    rows = git(s["repo"], "ls-remote", "--refs", alias, ref, env=env).splitlines()
    # ls-remote takes tail patterns; a ref literally named heads/refs/heads/X
    # can match the same pattern. Compare the returned full ref name as well.
    for row in rows:
        oid, name = row.split(b"\t", 1)
        if name == os.fsencode(ref):
            return os.fsdecode(oid)
    return None


def push_checkpoint(s, expected, wanted):
    destination = bound_destination(s)
    observed = published(s, destination)
    if observed == wanted:
        return observed
    if observed != expected:
        raise Pending("Remote head moved independently. Inspect before resuming.")
    if expected:
        git(s["repo"], "merge-base", "--is-ancestor", expected, wanted)
    target = target_ref(s)
    # The lease also protects the case where an unseen actor deletes or rewinds a branch.
    git(
        s["repo"],
        "push",
        "--no-follow-tags",
        f"--force-with-lease={target}:{expected or ''}",
        destination[0],
        f"{wanted}:{target}",
        env=destination[1],
    )
    if published(s, destination) != wanted:
        raise Pending(
            "The push did not confirm the expected remote head. Resume to reconcile."
        )
    return wanted


def work_root():
    return state_root() / "simplify"


def owner_path(repo):
    return work_root() / "owners" / digest(os.fsencode(repo))


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
    s = {
        "profile": PROFILE,
        "id": str(uuid.uuid4()),
        "repo": str(repo),
        "branch_ref": ref,
        "branch": ref.removeprefix("refs/heads/"),
        "task": args.task,
        "checks": check_commands,
        "timeout": args.timeout,
        "remote": args.push,
        "rounds": [],
        "status": "active",
    }
    check_branch(s)
    if changed(s, establish=True):
        raise Pending(
            "Start from a clean committed work branch, or use a separate clean worktree."
        )
    s["start"] = rev(repo, "HEAD")
    base_ref = rev(repo, args.base + "^{commit}")
    s["base"] = os.fsdecode(git(repo, "merge-base", base_ref, s["start"])).strip()
    original = git(
        repo, "diff", "--name-only", "--no-renames", "-z", s["base"], s["start"]
    )
    s["allow"] = sorted({os.fsdecode(p) for p in original.split(b"\0") if p})
    for name in args.allow or []:
        path = Path(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or ".git" in path.parts
        ):
            raise Pending("--allow expects a repository-relative file or subdirectory.")
        s["allow"].append(path.as_posix())
    if s["remote"]:
        if s["base"] == s["start"] and not s["allow"]:
            raise Pending("The selected branch has no scoped changes to publish.")
        url = push_destination(repo, s["remote"])
        s["destination"] = digest(os.fsencode(url))
        s["original_remote"] = published(s)
        if s["original_remote"]:
            git(repo, "merge-base", "--is-ancestor", s["original_remote"], s["start"])
    owner = owner_path(str(repo))
    owner.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if owner.exists():
        old = owner.read_text().strip()
        prior = json.loads((work_root() / old / "state.json").read_text())
        if prior["status"] not in {"complete", "released"}:
            raise Pending(f"Run {old} owns this worktree. Resume or release it first.")
    folder = work_root() / s["id"]
    folder.mkdir(mode=0o700)
    prompt = PROMPT.read_bytes()
    (folder / "prompt.txt").write_bytes(prompt)
    s["prompt_sha256"] = digest(prompt)
    save(folder / "state.json", s)
    pointer = owner.with_name(owner.name + ".tmp")
    pointer.write_text(s["id"])
    pointer.replace(owner)
    return folder, s


def call_context(s, r, folder):
    diff = folder / f"round-{r['number']}-input.diff"
    if not diff.exists():
        diff.write_bytes(
            git(
                s["repo"],
                "diff",
                "--no-ext-diff",
                "--no-textconv",
                "--full-index",
                s["base"],
                r["input"],
            )
        )
    # The restricted file tools cannot read our private state directory. The
    # harness delivers this separate context as a file with no argv size limit.
    delta = diff.read_text(encoding="utf-8", errors="replace")
    tools = (
        "Use local Bash for inspection and repository tests as needed. Keep temporary test output "
        "outside the source tree or in its existing ignored build paths. Leave Git mutations, "
        "publication, external graders and the independent checks to the coordinator."
        if s["profile"] == PROFILE
        else "The coordinator owns shell, Git and validation."
    )
    return (
        f"You are the sole product-code writer for round {r['number']}. Worktree: {s['repo']}. "
        f"Frozen acceptance contract: {s['task']}\nBase: {s['base']}. Input commit: {r['input']}. "
        f"Permitted file paths/subtrees: {json.dumps(s['allow'])}. "
        "Read applicable AGENTS.md and repository instructions. Edit only when you can explain "
        "how a change preserves the contract and reduces complexity. Keeping the design is valid. "
        f"{tools} End this turn with an explanation of "
        "what changed and what needs verification. The actual check results follow in this session.\n"
        f"Branch delta:\n{delta}"
    )


def assess_prompt(r, folder):
    records = []
    for check in r["checks"]:
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


def contact(s, r, folder, kind, prompt, context):
    session = r.get("session_id")
    call_name = f"r{r['number']}-call-{len(r['calls']) + 1}"
    r["calls"].append(
        {
            "name": call_name,
            "kind": kind,
            "prompt_sha256": digest(prompt.encode()),
            "resume": session,
        }
    )
    r["phase"] = "calling"
    save(folder / "state.json", s)
    run_turn(
        "claude",
        repo=Path(s["repo"]),
        prompt=prompt,
        context=context,
        model="opus",
        session_id=session,
        edit=kind != "assess",
        local_shell=s["profile"] == PROFILE and kind != "assess",
        output_dir=folder / call_name,
    )


def consume_call(s, r, folder, recover):
    call = r["calls"][-1]
    receipt_path = folder / call["name"] / "receipt.json"
    if not receipt_path.exists():
        # The adapter persists its starting receipt before spawning a provider.
        if not recover:
            raise Pending(
                "This call has no launch receipt. Inspect the workspace and use --recover to retry."
            )
        r["phase"] = call["kind"]
        save(folder / "state.json", s)
        return
    receipt = json.loads(receipt_path.read_text())
    if receipt.get("status") != "success":
        if not recover or not stopped(receipt_path):
            raise Pending(
                f"Interrupted {call['kind']} turn. Inspect {receipt_path} and the worktree; "
                "use --recover only after reconciling the stopped call."
            )
        if call["kind"] == "initial" and not r.get("session_id"):
            if changed(s):
                raise Pending(
                    "Preserve the interrupted edits and reconcile back to the clean round input before a fresh attempt."
                )
            r["phase"] = "initial"
        else:
            r["phase"] = "checks" if call["kind"] == "repair" else "assess"
        save(folder / "state.json", s)
        return
    if (
        receipt["prompt_sha256"] != call["prompt_sha256"]
        or receipt.get("model_requested") != "opus"
    ):
        raise Pending("The saved harness response does not match this request.")
    session = receipt["session_id"]
    if not session or (r.get("session_id") and session != r["session_id"]):
        raise Pending("The Opus session changed within a round.")
    if any(old.get("session_id") == session for old in s["rounds"][:-1]):
        raise Pending("Opus reused a previous round's context.")
    reported = receipt.get("model_reported")
    if reported and "opus" not in reported.lower():
        raise Pending(f"The harness reported a different model: {reported}.")
    r.update(session_id=session, model_reported=reported)
    text = receipt["text"].strip()
    if call["kind"] == "assess":
        last = text.splitlines()[-1] if text else ""
        if last == "STATUS: VERIFIED" and all(c["exit"] == 0 for c in r["checks"]):
            r["phase"] = "commit"
        elif last in {"STATUS: REPAIR", "STATUS: VERIFIED"}:
            r["phase"] = "repair"
        else:
            if not recover:
                raise Pending(
                    "Opus returned no valid final assessment. Inspect the receipt and use "
                    "--recover to request a corrected assessment."
                )
            r["phase"] = "assess"
    else:
        r["phase"] = "checks"
    save(folder / "state.json", s)


def check_candidate(s, r, folder):
    before, _ = candidate(s, folder)
    r["checks"] = []
    n = uuid.uuid4().hex[:10]
    attempt = {"tree": before, "checks": r["checks"]}
    r.setdefault("check_history", []).append(attempt)
    save(folder / "state.json", s)
    for i, cmd in enumerate(s["checks"], 1):
        path = folder / f"r{r['number']}-{n}-check-{i}.log"
        outcome, code, reason = run_command(cmd, s["repo"], path, s["timeout"])
        r["checks"].append(
            {
                "argv": cmd,
                "exit": code,
                "outcome": outcome,
                "reason": reason,
                "log": path.name,
            }
        )
        save(folder / "state.json", s)
        if outcome == "BLOCKED":
            raise Pending(
                f"Could not complete {cmd!r}: {reason}. Inspect {path} and resume."
            )
        after, _ = candidate(s, folder)
        if before != after or rev(s["repo"], "HEAD") != r["input"]:
            raise Pending(
                "Checks changed the candidate or its revision. Inspect the changes and resume."
            )
    r.update(tree=before, phase="assess")
    save(folder / "state.json", s)


def commit(s, r, folder):
    repo = s["repo"]
    head = rev(repo, "HEAD")
    checked = r["tree"]
    expected = f"Factory simplify round {r['number']} [{s['id']}]"
    if head == r["input"]:
        current, paths = candidate(s, folder)
        if current != checked:
            raise Pending(
                "The checked tree has changed. Restore the reviewed candidate before checkpointing."
            )
        if paths:
            stage(repo, paths)
            if os.fsdecode(git(repo, "write-tree")).strip() != checked:
                raise Pending("Staged tree differs from the checked candidate.")
            git(repo, "commit", "-m", expected)
    check_branch(s)
    # This also recovers a kill between committing and persisting the result.
    if rev(repo, "HEAD") != r["input"]:
        actual = os.fsdecode(git(repo, "log", "-1", "--format=%s")).rstrip("\n")
        parents = os.fsdecode(git(repo, "show", "-s", "--format=%P", "HEAD")).strip()
        if parents != r["input"] or actual != expected:
            raise Pending(
                "HEAD differs from the intended checkpoint commit. Inspect the branch before continuing."
            )
    if changed(s) or rev(repo, "HEAD^{tree}") != checked:
        raise Pending(
            "Commit hooks or another writer changed the checked candidate. Inspect before continuing."
        )
    r.update(output=rev(repo, "HEAD"), phase="publish")
    save(folder / "state.json", s)


def execute(s, folder, recover=False):
    prompt_bytes = (folder / "prompt.txt").read_bytes()
    if digest(prompt_bytes) != s["prompt_sha256"]:
        raise Pending("The pinned simplification prompt has changed.")
    prompt = prompt_bytes.decode()
    while True:
        check_branch(s)
        if not s["rounds"] or s["rounds"][-1]["phase"] == "done":
            previous = s["rounds"][-1]["output"] if s["rounds"] else s["start"]
            if rev(s["repo"], "HEAD") != previous or changed(s):
                raise Pending("The worktree no longer matches the last checkpoint.")
            if len(s["rounds"]) == 3:
                s["status"] = "complete"
                save(folder / "state.json", s)
                return
            s["rounds"].append(
                {
                    "number": len(s["rounds"]) + 1,
                    "input": previous,
                    "phase": "initial",
                    "calls": [],
                }
            )
            save(folder / "state.json", s)
        r = s["rounds"][-1]
        phase = r["phase"]
        if phase not in {"commit", "publish"} and rev(s["repo"], "HEAD") != r["input"]:
            raise Pending("The checked-out revision changed mid-round.")
        if phase == "initial":
            if changed(s):
                raise Pending("A fresh round needs its clean input revision.")
            contact(s, r, folder, "initial", prompt, call_context(s, r, folder))
        elif phase == "calling":
            consume_call(s, r, folder, recover)
            recover = False
        elif phase == "checks":
            check_candidate(s, r, folder)
        elif phase == "assess":
            if candidate(s, folder)[0] != r["tree"]:
                raise Pending(
                    "Candidate changed after checks. Inspect it before continuing."
                )
            contact(s, r, folder, "assess", assess_prompt(r, folder), "")
        elif phase == "repair":
            repairs = sum(c["kind"] == "repair" for c in r["calls"])
            if repairs >= 2:
                raise Pending(
                    "Two repair attempts exhausted for this round. Inspect its checks and report."
                )
            contact(
                s,
                r,
                folder,
                "repair",
                "Implement the scoped repair you identified from the check results. "
                "The coordinator will rerun validation in this session.",
                "",
            )
        elif phase == "commit":
            commit(s, r, folder)
        elif phase == "publish":
            if rev(s["repo"], "HEAD") != r["output"] or changed(s):
                raise Pending(
                    "Worktree or branch moved before the checkpoint was confirmed."
                )
            if s["remote"]:
                expected = (
                    s["original_remote"]
                    if r["number"] == 1
                    else s["rounds"][-2]["remote_head"]
                )
                r["remote_head"] = push_checkpoint(s, expected, r["output"])
            r["phase"] = "done"
            r["finished"] = time.time()
            save(folder / "state.json", s)
        else:
            raise Pending(f"Unknown phase {phase!r}.")


def report(s, folder):
    return {
        "id": s["id"],
        "status": s["status"],
        "branch": s["branch"],
        "profile": s["profile"],
        "state": str(folder / "state.json"),
        "rounds": [
            {
                k: r[k]
                for k in (
                    "number",
                    "phase",
                    "session_id",
                    "model_reported",
                    "input",
                    "output",
                    "remote_head",
                )
                if k in r
            }
            for r in s["rounds"]
        ],
    }


def emit_status(s, folder):
    result = report(s, folder)
    if s["status"] in {"complete", "active"}:
        try:
            qualify_legacy_checkouts(s)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            result.update(status="pending", recorded_status=s["status"], error=str(exc))
            print(json.dumps(result))
            return 2
    if s["status"] == "complete":
        wanted = s["rounds"][-1]["output"]
        try:
            check_branch(s)
            observed = rev(s["repo"], "HEAD")
            result["current_head"] = observed
            current = observed == wanted and not changed(s)
            if s["remote"]:
                result["current_remote_head"] = published(s)
                current = current and result["current_remote_head"] == wanted
            if not current:
                result.update(status="stale", recorded_status="complete")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            result.update(status="pending", recorded_status="complete", error=str(exc))
    print(json.dumps(result))
    return 0 if result["status"] == "complete" else 2


def handle(args):
    folder = None
    try:
        if args.resume:
            if any(
                (args.repo, args.base, args.task, args.check, args.allow, args.push)
            ):
                raise Pending(
                    "A resumed run uses its saved contract, commands and publication target."
                )
            folder = work_root() / str(uuid.UUID(args.resume))
            s = json.loads((folder / "state.json").read_text())
            if args.status:
                return emit_status(s, folder)
            repo = Path(s["repo"])
        else:
            if args.recover or args.release or args.status:
                raise Pending("--recover, --release and --status need --resume RUN_ID.")
            repo = Path(
                os.fsdecode(
                    git(args.repo or ".", "rev-parse", "--show-toplevel")
                ).strip()
            ).resolve()
        with workspace_lock(repo):
            if folder:
                s = json.loads((folder / "state.json").read_text())
                if s["profile"] not in (LEGACY_PROFILE, PROFILE):
                    raise Pending("Unsupported run profile.")
                if s["status"] != "active":
                    return emit_status(s, folder)
                if owner_path(s["repo"]).read_text().strip() != s["id"]:
                    raise Pending("This worktree belongs to another run.")
                if args.release:
                    if s["rounds"] and s["rounds"][-1]["phase"] == "calling":
                        last = s["rounds"][-1]["calls"][-1]
                        path = folder / last["name"] / "receipt.json"
                        if not stopped(path):
                            raise Pending(
                                "A harness writer may still be active. Verify its process first."
                            )
                    s["status"] = "released"
                    save(folder / "state.json", s)
                    print(json.dumps(report(s, folder)))
                    return 2
                qualify_legacy_checkouts(s)
            else:
                folder, s = create_run(args, repo)
            execute(s, folder, args.recover)
            print(json.dumps(report(s, folder)))
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
    p.add_argument("--timeout", type=int, default=300, help="seconds per verification command")
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
