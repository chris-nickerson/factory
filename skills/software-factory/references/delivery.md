# Full delivery

The coordinating GPT session owns implementation and Git. Split the task into acceptance scenarios and settle any required consensus first. Bind the intended branch and base. Start the evidence run with the whole branch's base and required review before implementing. If the task has no code-change disposition, record how that conclusion was established and stop there.

Implement the agreed design and run the frozen checks. Checkpoint the scoped implementation on the work branch before handing it to Opus. Use the simplification command with the round count selected for this change, with the original base, scoped paths, acceptance checks and requested publication mode. Keep a record of both run IDs. An unavailable required role leaves full delivery pending. Reuse the same run ID when resuming that phase.

After the final scheduled checkpoint, run the independent GPT review on the whole final change and replay the behavioral and engineering checks on the final subject. A changed head invalidates earlier review and check evidence. Adjudicate a finding using the actual trigger and source, repair confirmed blockers, then refresh review and final checks. Preserve the completed simplification count.

## PR review workflow

Use the target forge through the host's authenticated tools. Read applicable repository and user instructions, including any review skill the host exposes. Follow their rules for checks, evidence, reviewers, replies and queueing. Use the steps below wherever local instructions leave a gap. A fresh checkout with no review skill uses the same workflow.

1. Establish the requested endpoint, ordering and any round limit. Verify the repository, PR, base, remote head and existing checks. When asked to mark it ready, promote the intended draft and verify the transition. Respect an explicit draft or ready-only stopping point.
2. For babysitting, wait for current-head CI and requested reviews to settle. Inspect failed jobs, review threads, PR comments and any applicable QA plan. Recheck the head before using a result. An approval on a different revision or a skipped check is evidence only for what it covered.
3. Triage each new finding against the code. Fix valid findings and in-scope CI failures together, run affected checks and recheck the remote head before pushing. Reconcile concurrent updates without overwriting them. Reply with the fix and its evidence, or the reason a finding does not apply. Resolve addressed threads according to local policy; leave genuine disputes open. Refresh the PR evidence after a change.
4. One round covers the findings on the reviewed head, their disposition, and publication of any fixes. At the round limit, take one final status snapshot of the head, checks, approval and unresolved threads, then return. Waiting for replacement CI or triaging fresh reviews starts a new cycle unless the user explicitly requested that wait. For continued babysitting, repeat on material changes. If only human approval remains, report whose action is needed. Use the host's wait mechanism between checks; respect any deadline and report a stalled check with its last observed state.
5. Stop at merge-ready by default. Merge only within the authorized endpoint, with the required approvals and checks on the intended head, using the repository's normal protections. If the forge cannot perform a required action, report the missing access or capability and the last verified state.

At handoff, distinguish disposition, reviewed revision, runtime evidence and remote publication. Give the exact remaining blocker whenever a required phase stays open.
