# Write and maintain documentation

Write docs that help readers do a task or understand something they cannot learn from the code. Explain how to get started, how the parts fit together, or why a constraint matters. Keep those explanations current.

The README helps people decide whether to use the project and how to get started. `SKILL.md`, `AGENTS.md` and `CLAUDE.md` are instructions for agents. Follow the sentence style in the [PR writing guide](pr-descriptions.md).

## Keep facts in one place

Keep one source for each fact. If the code or `--help` already gives a default or lists the flags, point readers there. Leave counts, timings and other details from a specific run out of maintained docs. They go stale quickly.

## Document code where readers need it

Put a comment next to the code when the reason for it is hard to see. If the code works around a problem, trace the problem to its cause and explain the constraint the workaround handles. Remove comments that repeat the code or narrate a change. At public boundaries, document the inputs, outputs, errors and side effects callers can rely on.

## Change documentation with the code

Update or remove any documentation the code change makes false in the same change. Edit the existing explanation instead of appending an update. Reread the whole document and delete anything that no longer helps the reader.

Make claims readers can check. Run example commands as written and verify the links. If the repository has a test that checks links or examples, run it.

## Record the reason for a change

Explain why you made a change in the commit message and PR description. A reader can find the history with `git log`, `git blame` and the PR. If a mistake keeps happening, add a test or check that catches it.

Keep the trail of a long run in Factory’s run records outside the checkout. Leave decision folders, notes files, dated reports, work diaries and agent changelogs out of the repository.
