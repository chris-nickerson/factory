# Write and maintain documentation

Write docs that help readers do a task or understand something they cannot learn from the code. Explain how to get started, how the parts fit together, or why a constraint matters. Keep those explanations current.

The README helps people decide whether to use the project and how to get started. `SKILL.md`, `AGENTS.md` and `CLAUDE.md` are instructions for agents. Follow the sentence style in the [PR writing guide](pr-descriptions.md).

## Keep facts in one place

Keep one source for each fact. If the code or `--help` already gives a default or lists the flags, point readers there. Leave counts, timings and other details from a specific run out of maintained docs. They go stale quickly.

## Review comments in the diff

Read each changed comment, docstring and suppression beside the code it describes. Preserve license notices and public contracts, including inputs, outputs, errors and side effects. Keep a concise explanation where a reader could reasonably make the wrong change without knowing why the code is shaped that way. Remove narration, abandoned code and change history. If a comment says two values must always agree, consider deriving one from the other or enforcing the invariant at the write boundary.

When a comment describes a workaround, follow it to the cause. For a dependency or platform constraint, verify the affected version and behavior using the pinned source, an upstream issue or a reproduction. Keep the reason near the affected call. If Factory or the target project owns the cause, fix it within the task's scope. For a cause outside scope, retain any explanation still needed for safe maintenance and report what remains.

For a lint or type-check suppression, identify the exact diagnostic and run the checker with the suppression removed. Fix a genuine defect. When the checker rejects a valid case, keep the narrowest justified exception.

## Change documentation with the code

Update or remove any documentation the code change makes false in the same change. Edit the existing explanation instead of appending an update. Reread the whole document and delete anything that no longer helps the reader.

Make claims readers can check. Run example commands as written and verify the links. If the repository has a test that checks links or examples, run it.

## Record the reason for a change

Explain why you made a change in the commit message and PR description. A reader can find the history with `git log`, `git blame` and the PR. If a mistake keeps happening, add a test or check that catches it.

Keep the trail of a long run in Factory’s run records outside the checkout. Leave decision folders, notes files, dated reports, work diaries and agent changelogs out of the repository.
