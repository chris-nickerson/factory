# Deliver a stack of pull requests

Use a stack when each change needs its predecessor and reviewers should be able to review each increment on its own. Independent PRs can each follow [full delivery](delivery.md). For a status request, inspect the stack once. For a build or babysit request, carry it through the requested review state. Landing requires the user's authority for the PRs being merged. Keep any named human-owned PR at its requested stopping point.

## Establish the chain

Read the repository, target branch and ordered PRs from the request and the forge. Record each PR's head repository, branch and commit, base repository, branch and commit, and open or merged state. The bottom PR targets the integration branch. Each child targets the preceding PR's head branch. In a local checkout, fetch those refs and compare their tips with the forge. For a linear stack, `git merge-base --is-ancestor BASE_SHA HEAD_SHA` checks that the head includes the intended base. Inspect the parent-to-child diff to see exactly what reviewers would receive. Resolve a missing link, unexpected base or diverged tip before acting on it.

On GitHub, `gh pr view NUMBER --json url,state,headRefName,headRefOid,baseRefName,baseRefOid,reviewDecision,mergeStateStatus,statusCheckRollup` supplies the branch and check summary. Also inspect required checks, the revision each approval or review covered, outstanding review threads, and any required queue. Treat pending or unknown forge state as an open question. A check on the previous head can still appear in a PR's history.

## Build or repair the stack

1. Give each change a worktree and compare it with its immediate parent. Use [full delivery](delivery.md) for the scoped change, including an independent review and behavioral check at the exact base and head. During construction, push and open each requested PR against its intended base. Read back each published link. The coordinator owns base changes.
2. Work on the lowest PR whose failure holds up the others. Trace a failed check or review finding to the change that introduced it, fix it on the owning branch and publish within the requested scope. Batch related repairs. Keep unaffected work going where dependencies permit. Apply any requested round limit across the agreed scope.
3. When a parent moves, fetch and reconcile the child with its new parent. For a rewritten parent, replay only the child's commits from the previous parent tip. Inspect the resulting diff for lost child changes or duplicated parent changes. Check for concurrent pushes before updating a remote branch. Refresh behavioral evidence and independent review for the changed base and head, and recheck the forge. Repeat bottom-up.
4. For a review-ready handoff, list the PRs bottom-up with their actual bases, head commits, behavioral evidence, checks and remaining human decisions. End here when the user wants to land the stack themselves.

## Land the verified prefix

Start at the lowest unmerged PR. Establish which consecutive PRs have the required evidence and approvals. A later passing PR cannot be landed across a gap. For a request to land just the verified prefix, that first gap bounds this pass. For an end-to-end request, repair in-scope failures and continue until the requested endpoint or a decision requiring the user.

Before each merge, read the current base and head again and bind the merge to the reviewed head using the forge's expected-head option when available. Confirm this PR targets the intended integration branch. Use the project's ordinary protected merge or queue mechanism. Only arm the current bottom PR when merge-when-ready was requested. Wait for the forge to confirm the merge, then fetch the integration branch and confirm it contains the reported merge commit. Queue admission alone leaves the PR in flight.

Read the next PR again. After a squash merge, a child's old parent commits can remain in its branch. Compare against the saved parent tip, reconcile the child's own patch with the new integration tip, and retarget that child if needed. Re-establish checks, approvals and evidence against the resulting base and head before continuing. If a merge races with another publisher, inspect the actual refs and forge state before retrying. Report what landed, the lowest remaining PR and the specific evidence or authority it needs.
