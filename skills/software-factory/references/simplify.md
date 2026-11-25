# Simplification rounds

Choose the round count using the PR tiers in SKILL.md. Existing invocations with no count run three rounds. Supply the user's requirements and confirmed facts in the task. Resolve the original base explicitly. Choose checks that capture the branch's existing behavior before simplifying it. [Choosing a baseline](local.md#choose-the-baseline) Run check-only commands against the real behavior and include the target repository's required checks. When possible, include an independent acceptance check whose oracle lives outside the editable source.

Start on a clean, committed, named work branch, preferably a dedicated worktree. Factory computes a common base, takes ownership for the run, and allows edits to paths in the starting branch delta. Add an explicitly relevant file or subtree with `--allow PATH` when simplifying across module boundaries. Keep the state directory outside the checkout. Git index entries marked assume-unchanged or skip-worktree can hide checked-out bytes, so this route requires visible index entries and clean initialized submodules. It reports these conditions without modifying the index or submodule. The coordinator can inspect Git-visible changes. Host file permissions and the operator's isolated worktree govern access to other files.

If the user asks to push each round, pass `--push REMOTE` with the work branch's remote. For local work, omit `--push`. This example uses a Python project, a `trunk` base and the `origin` remote.

```sh
factory simplify --repo . --base trunk --rounds 2 --task 'Preserve the parser contract and existing error messages.' \
  --check 'python3 -m unittest discover -s tests' --push origin
```

Pass one command and its arguments per `--check`, using shell-style quoting. Repeat the option for each additional check. If the repository requires a checkpoint title, pass one line with `--commit-subject TEXT`. Factory records the checked revision in its run receipt. Use `--timeout SECONDS` to set the limit for each verification command. The simplifier's editing, assessment and repair turns have no Factory time limit. Factory [chooses the simplifier](roles.md#how-factory-chooses-a-default). Pass `--simplifier SPEC` to choose the harness or model for this run, or `--tier frontier` for a change with substantial risk.

The first message of each fresh session comes from the [canonical prompt](reconsider-from-first-principles.v1.txt). The runner supplies the requirements, edit scope and branch evidence separately. Editing and repair turns can change worktree files and run local tests in a sandboxed shell that cannot write Git metadata. With Claude Code, Auto evaluates each shell request and the host needs a working Claude Code sandbox. With Codex, the shell has no network access and temporary files go to a private directory for the turn. Factory runs its own checks and owns Git commits and pushes. Each assessment resumes the same session read-only. A run keeps the harness, model and tool profile it started with on resume. [What each harness provides](roles.md#what-each-harness-provides) Factory returns actual check output to the same session for assessment. A failed check forces repair even when the model claims success. A round can attempt two repairs before stopping with its artifacts intact.

Factory commits only a checked tree. For the push variant, it compares the remote baseline, pushes a fast-forward update to the named work branch and reads back its head. A clean round counts once its existing commit is present remotely. Each completed round records its session, revisions, logs and publication receipt. The command exits after the selected number of rounds. For full delivery, run `factory review` on the entire final branch and verify the required behavior.

## Recovery

A completed run reports its ID, target count and checkpoints. A pending run reports the reason and its run ID when available. Use `--status` to inspect its count and checkpoints. A successful run exits 0. Pending or released runs exit 2. Inspecting a completed run checks the current branch and, for a push run, the remote tip. A changed head yields a stale status and preserves the historical receipts.

```sh
factory simplify --resume RUN_ID --status
factory simplify --resume RUN_ID
```

Use the same state directory for every command. Before launching another turn, resume checks for successful provider calls, existing commits and pushes whose receipts were lost.

| Situation | What to do |
| --- | --- |
| Before Git created the commit, for example after a hook rejected its title | Retry with `--resume RUN_ID --recover --commit-subject TEXT`. The new title applies to this checkpoint and later rounds. |
| After Git created a commit whose message has no run marker | Inspect the local commit. To accept that exact commit on resume, pass `--accept-checkpoint FULL_SHA`. Its parent, tree, branch and clean worktree must match the checked round. |
| During a provider call | Inspect its receipt, the worktree and any active process. Fix login or environment problems. If the first call left partial edits, save them and restore the clean input. Resolve any surviving writer or independently moved branch. Retry with `factory simplify --resume RUN_ID --recover`. |
| You want to retire the stopped run | Use `--release` with the run ID to preserve the worktree and release the run. |

Logs can contain source and command output. The default location is private local Factory state. The check result applies to the named commands, inputs and revision. A simplification pass alone supplies no evidence for an unexercised behavior.

When a remote rejects an already-committed subject during publication, preserve the rejection, release the stopped run, and prepare a compliant branch before starting a new run. Publication retries the recorded SHA. A publication receipt identifies the checked commit on the named remote. Git hooks run normally. If a hook changes the local worktree while Git is pushing, the remote can already hold the checked commit when Factory reports the local mismatch. Inspect both heads and the hook result before resuming.
