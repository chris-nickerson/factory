# Write and maintain documentation

Write for a capable reader who missed the conversation. Lead with what the reader can do or what result they should expect. This guide applies to documentation, agent instructions, pull requests, CLI text and code comments.

## Write in plain technical English

Write like you’re explaining the work to a teammate. In the README, use first person when you say why Factory exists or what you want it to become. In a procedure, speak to the person doing the work. Give a real request, command or result when it helps the reader see what you mean.

- Name the actor, action and object. Put a condition before an action when the reader must check it first.
- Use one main thought per sentence. Keep a condition or reason with the action when the reader needs both to make a decision.
- Use the same term for the same thing. Explain Factory terms on first use. Match names the reader sees in code, commands and output.
- Use headings that answer a reader's question. Give each numbered step one action. Put prerequisites, commands and expected results where the reader needs them.

| Reader's task | What to write |
| --- | --- |
| Get started | Explain what the project does, give the prerequisites and walk through a working example. |
| Complete a procedure | State when to use it, who acts, where to run commands and how to recognize success or recover from failure. |
| Look up a fact | Give the exact flag, default, state or constraint. Link to the source that owns it. |
| Understand a design | Explain what the parts do, why they work that way and where the guarantees end. |
| Follow agent instructions | Put discovery terms in the skill description. In the loaded instructions, state the trigger, action, allowed side effects and stopping point. Link to detailed mechanics. Give an example where nearby requests lead to different decisions. |
| Recover from an error | Say what failed, what the reader can safely do next and where details are available. Check whether callers depend on the exact output. |

For pull request descriptions, start from the [PR writing guide](pr-descriptions.md).

## Factory terms

| Term | Meaning |
| --- | --- |
| Contract | The claims and checks saved by `factory start`. A frozen contract keeps the same checks across revisions. |
| Subject | The workspace fingerprint associated with the result. In a Git checkout, it includes HEAD, the index, tracked working files and unignored new files. |
| Stale result | A result for a different subject. Use `factory check RUN_ID` for a stale check or `factory review RUN_ID` for a stale review. |
| Checkpoint | The checked Git commit for a simplification round. A round with no edits can use the existing commit. |
| Receipt | A saved record of an operation, such as a provider call, check, review or publication. |

Keep working files, the Git index and a committed tree distinct. A change can be present in one even when it is absent from another.

## Examples from Factory

| Before | After |
| --- | --- |
| “The second `check` makes a new observation, and this time it fails.” | “Run `./factory check "$run"` to check the current file. In this example, the new check fails because the file now says `pending`.” |
| “For the requested push-each-round procedure, select the actual work-branch remote.” | “If the user asks to push each round, pass `--push REMOTE` with the work branch's remote.” |
| “Read repository evidence and command candidates without executing project code” | “Find repository instructions, skills, and suggested commands without running project code” |

## Keep facts in one place

Keep one source for each fact. If the code or `--help` already gives a default or lists the flags, point readers there. Leave counts, timings and other details from a specific run out of maintained docs. They go stale quickly.

## Review comments in the diff

Read each changed comment, docstring and suppression beside the code it describes. Preserve license notices and public contracts, including inputs, outputs, errors and side effects. Keep a concise explanation where a reader could reasonably make the wrong change without knowing why the code is shaped that way. Remove narration, abandoned code and change history. If a comment says two values must always agree, consider deriving one from the other or enforcing the invariant at the write boundary.

When a comment describes a workaround, follow it to the cause. For a dependency or platform constraint, verify the affected version and behavior using the pinned source, an upstream issue or a reproduction. Keep the reason near the affected call. If Factory or the target project owns the cause, fix it within the task's scope. For a cause outside scope, retain any explanation still needed for safe maintenance and report what remains.

For a lint or type-check suppression, identify the exact diagnostic and run the checker with the suppression removed. Fix a genuine defect. When the checker rejects a valid case, keep the narrowest justified exception.

## Change documentation with the code

Update or remove any documentation the code change makes false in the same change. Edit the existing explanation instead of appending an update. Reread the whole document and delete anything that no longer helps the reader.

## Review a writing change

1. Read the changed text with the issue closed. Check whether a new reader can identify the next action, its conditions and its expected result.
2. Trace changed strings to their consumers. Preserve protocol lines, pinned prompts, fixtures, license text and exact output that callers rely on. Keep existing public links and anchors usable.
3. Make claims readers can check. Run changed examples as written, verify the links and run any repository test for links or examples. Exercise changed procedures, help and diagnostics through their entry points. For routing, check a neighboring request with a different correct outcome. Compare what the host loaded and what the agent attempted.
4. [Review the changed comments and docstrings](#review-comments-in-the-diff) beside the code.

Use sentence length and terminology reports to find passages worth reading. Judge the result by whether readers can complete the task and preserve the contract.

## Record the reason for a change

Explain why you made a change in the commit message and PR description. A reader can find the history with `git log`, `git blame` and the PR. If a mistake keeps happening, add a test or check that catches it.

Keep the trail of a long run in Factory’s run records outside the checkout. Leave decision folders, notes files, dated reports, work diaries and agent changelogs out of the repository.
