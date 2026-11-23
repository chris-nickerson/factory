# Opus simplification

Choose the round count using the PR tiers in SKILL.md. Existing invocations with no count run three rounds. Supply the user's requirements and confirmed facts in the task. Resolve the original base explicitly. Choose checks that capture the branch's existing behavior before simplifying it. [Choosing a baseline](local.md#choose-the-baseline) Run check-only commands against the real behavior and include the target repository's required checks. When possible, include an independent acceptance check whose oracle lives outside the editable source.

Start on a clean, committed, named work branch, preferably a dedicated worktree. Factory computes a common base, takes ownership for the run, and allows edits to paths in the starting branch delta. Add an explicitly relevant file or subtree with `--allow PATH` when simplifying across module boundaries. Keep the state directory outside the checkout. Git index entries marked assume-unchanged or skip-worktree can hide checked-out bytes, so this route requires visible index entries and clean initialized submodules. It reports these conditions without modifying the index or submodule. The coordinator can inspect Git-visible changes. Host file permissions and the operator's isolated worktree govern access to other files.

For the requested push-each-round procedure, select the actual work-branch remote. The following example assumes a Python project using a `trunk` base and an `origin` remote.

```sh
factory simplify --repo . --base trunk --rounds 2 --task 'Preserve the parser contract and existing error messages.' \
  --check 'python3 -m unittest discover -s tests' --push origin
```

Each `--check` is one argument vector with shell-style quoting. To invoke a project script, pass its executable and arguments. Repeat the option to add another check. Use `--commit-subject TEXT` for a repository-required checkpoint title. Factory passes that title as a single line and records the checked revision in its run receipt. For local-only work, omit `--push`. Use `--timeout SECONDS` to change the limit for each verification command. Opus editing, assessment and repair turns have no Factory time limit.

The first message of each fresh session comes from the [canonical prompt](reconsider-from-first-principles.v1.txt). The runner supplies the requirements, edit scope and branch evidence separately. New editing and repair turns use Claude Code Auto with file tools and sandboxed Bash for local tests. Auto evaluates shell requests. Factory runs its own checks and owns Git commits and pushes. Each assessment resumes the same session with read-only file tools. Runs started with the earlier file-only profile retain that profile on resume. Auto shell requires a working Claude Code sandbox on the host. Factory returns actual check output to the same session for assessment. A failed check forces repair even when the model claims success. A round can attempt two repairs before stopping with its artifacts intact.

Factory commits only a checked tree. For the push variant, it compares the remote baseline, pushes a fast-forward update to the named work branch and reads back its head. A clean round counts once its existing commit is present remotely. Each completed round records its session, revisions, logs and publication receipt. The command exits after the selected number of rounds. For full delivery, obtain a fresh GPT review of the entire final branch and verify the required behavior.

## Recovery

A completed run reports its ID, target count and checkpoints. A pending run reports the reason and its run ID when available. Use `--status` to inspect its count and checkpoints. A successful run exits 0. Pending or released runs exit 2. Inspecting a completed run checks the current branch and, for a push run, the remote tip. A changed head yields a stale status and preserves the historical receipts.

```sh
factory simplify --resume RUN_ID --status
factory simplify --resume RUN_ID
```

To set a compliant title on an existing run before it commits, including after a commit hook rejects the title, retry with `--resume RUN_ID --recover --commit-subject TEXT`. The new title applies to the waiting checkpoint and later rounds. If Factory stopped after Git committed and the message has no run marker, inspect the local commit and resume with `--accept-checkpoint FULL_SHA` to accept that exact commit. Its parent, tree, branch and clean worktree must still match the checked round. Resume reconciles successful calls, committed trees and lost remote receipts before launching another turn. If a provider call failed, inspect its receipt, the worktree, and any active process. After resolving an authentication or environment failure, or preserving any partial edits from a failed first call and restoring its clean input, use `factory simplify --resume RUN_ID --recover`. A surviving writer or independently moved branch requires reconciliation. To retire a stopped run while preserving its worktree, use `--release` with the run ID. Use the same state directory for all invocations.

Logs can contain source and command output. The default location is private local Factory state. The check result applies to the named commands, inputs and revision. A simplification pass alone supplies no evidence for an unexercised behavior.

When a remote rejects an already-committed subject during publication, preserve the rejection, release the stopped run, and prepare a compliant branch before starting a new run. Publication retries the recorded SHA. A publication receipt identifies the checked commit on the named remote. Git hooks run normally. If a hook changes the local worktree while Git is pushing, the remote can already hold the checked commit when Factory reports the local mismatch. Inspect both heads and the hook result before resuming.
