"""Git operations for simplification checkpoints and their remote receipts.

The coordinator owns the run journal. This module checks the working tree,
constructs the candidate in a temporary index, and publishes an exact commit.
"""

import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import uuid

from supervision import captured_process
from workspace import ensure_visible_index


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


def target_ref(run):
    # Earlier profile-v1 state recorded only the short name.
    return run.get("branch_ref", "refs/heads/" + run["branch"])


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


def qualify_legacy_checkouts(run):
    if "submodule_checkouts" in run:
        return
    # A legacy run without gitlinks has a uniquely determined empty baseline.
    # Historical commits matter when a later round removed a dependency.
    repo = run["repo"]
    subjects = {run["start"]}
    for record in run["rounds"]:
        subjects.update(record[key] for key in ("input", "output") if key in record)
    listings = (git(repo, "ls-tree", "-r", "-z", subject) for subject in subjects)
    index = git(repo, "ls-files", "--stage", "-z")
    if any(row.startswith(b"160000 ") for row in index.split(b"\0")) or any(
        row.startswith(b"160000 ")
        for listing in listings
        for row in listing.split(b"\0")
    ):
        guidance = "Start a fresh run from a clean candidate to requalify its dependency checkouts."
        if run["status"] == "active":
            guidance = (
                f"Inspect and preserve pending edits, then run factory simplify --resume {run['id']} "
                f"--release after its writer has stopped. {guidance}"
            )
        raise Pending(
            f"This older run did not record submodule initialization state. {guidance}"
        )
    run["submodule_checkouts"] = {}


def changed(run, *, establish=False):
    repo = run["repo"]
    present = verify_git_visibility(repo)
    if establish:
        run["submodule_checkouts"] = present
    elif present != run.get("submodule_checkouts", {}):
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


def check_branch(run):
    repo = run["repo"]
    if branch_ref(repo) != target_ref(run):
        raise Pending(f"Restore work branch {run['branch']} before resuming.")
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


def candidate(run, folder):
    repo = run["repo"]
    paths = changed(run)
    outside = [
        p
        for p in paths
        if not any(p == prefix or p.startswith(prefix + "/") for prefix in run["allow"])
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


def bound_destination(run):
    url = push_destination(run["repo"], run["remote"])
    if digest(os.fsencode(url)) != run["destination"]:
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


def published(run, destination=None):
    alias, env = destination or bound_destination(run)
    ref = target_ref(run)
    rows = git(run["repo"], "ls-remote", "--refs", alias, ref, env=env).splitlines()
    # ls-remote takes tail patterns; a ref literally named heads/refs/heads/X
    # can match the same pattern. Compare the returned full ref name as well.
    for row in rows:
        oid, name = row.split(b"\t", 1)
        if name == os.fsencode(ref):
            return os.fsdecode(oid)
    return None


def push_checkpoint(run, expected, wanted):
    destination = bound_destination(run)
    observed = published(run, destination)
    if observed == wanted:
        return observed
    if observed != expected:
        raise Pending("Remote head moved independently. Inspect before resuming.")
    if expected:
        git(run["repo"], "merge-base", "--is-ancestor", expected, wanted)
    target = target_ref(run)
    # The lease also protects the case where an unseen actor deletes or rewinds a branch.
    git(
        run["repo"],
        "push",
        "--no-follow-tags",
        f"--force-with-lease={target}:{expected or ''}",
        destination[0],
        f"{wanted}:{target}",
        env=destination[1],
    )
    if published(run, destination) != wanted:
        raise Pending(
            "The push did not confirm the expected remote head. Resume to reconcile."
        )
    return wanted


def commit_checked_tree(run, record, folder, accepted_head=None):
    """Return the checked commit, reconciling a previous interrupted attempt."""
    repo = run["repo"]
    head = rev(repo, "HEAD")
    checked = record["tree"]
    committed_here = False
    marker = f"Factory simplify round {record['number']} [{run['id']}]"
    subject = run.get("commit_subject") or marker
    if head == record["input"]:
        current, paths = candidate(run, folder)
        if current != checked:
            raise Pending(
                "The checked tree has changed. Restore the reviewed candidate before checkpointing."
            )
        if paths:
            stage(repo, paths)
            if os.fsdecode(git(repo, "write-tree")).strip() != checked:
                raise Pending("Staged tree differs from the checked candidate.")
            cleanup = ["--cleanup=verbatim"] if run.get("commit_subject") else []
            git(repo, "commit", *cleanup, "-m", subject)
            committed_here = True
    check_branch(run)
    # This also recovers a kill between committing and persisting the result.
    if rev(repo, "HEAD") != record["input"]:
        lines = os.fsdecode(git(repo, "log", "-1", "--format=%B")).splitlines()
        parents = os.fsdecode(git(repo, "show", "-s", "--format=%P", "HEAD")).strip()
        marked = marker in lines or bool(lines and lines[0].endswith(" " + marker))
        if parents != record["input"]:
            raise Pending(
                "Checkpoint parent differs from the checked input. Inspect the branch."
            )
        if not (committed_here or marked or accepted_head == rev(repo, "HEAD")):
            raise Pending(
                "Checkpoint has no run marker. Inspect the commit, then resume with "
                "--accept-checkpoint FULL_SHA if it is the intended checkpoint."
            )
    if changed(run) or rev(repo, "HEAD^{tree}") != checked:
        raise Pending(
            "Commit hooks or another writer changed the checked candidate. Inspect before continuing."
        )
    return rev(repo, "HEAD")
