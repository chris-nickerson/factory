# Try the simpler path against its caller

Use this pilot to decide whether a short change to the task brief saves maintainer time. It uses the usual implementation, simplification and independent review procedures. Use the candidate brief only in the experimental arm.

## Candidate task brief

In the candidate arm, add the following paragraph to the author's task brief. Also pass it to `factory simplify` in `--task`, along with any relevant observations. Leave the [canonical simplifier prompt](reconsider-from-first-principles.v1.txt) unchanged.

> Before adding a second implementation path or deleting an apparently duplicate guard, identify the caller, saved input or external constraint that could distinguish the two paths. Try the simpler implementation against that case. Reuse an existing check or make a disposable probe. For a guard, exercise both an accepted input and the violation it rejects. Use the observed result to choose the implementation and carry it into the handoff. If the paths behave alike for the supported cases, prefer the simpler one. If the evidence is missing, preserve the known contract and state what you could not verify. For routine edits with no such choice, proceed as usual.

For example, an assessment written by an older release can reach the commit step on resume without starting a new model turn. Before deleting an identity check in the reader, resume a matching assessment and one reporting a different model. If only the reader can reject the mismatch, keep the check there and reuse the existing comparison logic. The agent can make that decision under the compatibility contract. Dropping support for an older release requires a policy decision.

## Compare with the current workflow

1. **Enroll the tasks.** Before inspecting any agent output, choose four wanted tasks: a local behavior change, a multi-caller change, a compatibility or external-tool change and a routine control. For each task, reserve a realistic follow-on edit and an independent acceptance check, and keep both hidden from the initial agent. Agree on value weights now, or give equally valuable tasks equal weight.
2. **Run matched pairs.** Run each task twice in separate worktrees from the same revision, once with the current brief and once with the paragraph above. Give both evidence runs the same task-specific acceptance brief in `factory start --task`. Factory includes that text in the review prompt. Use neutral branch and worktree names. Keep the author’s handoff and trial notes with the operator, outside the reviewer’s inputs. Match model and harness versions, allowed tools, checks, simplification rounds, spend caps and time limits. The operator enforces budgets outside Factory using the same clock and provider usage limits for each arm. Randomize order within each pair, and alternate which result the maintainer reads first.
3. **Run the follow-on.** Give a fresh agent each resulting checkout with the reserved maintenance request, using the same ordinary workflow for both. A reviewer who does not know the assignment judges both stages against the same contracts. A task succeeds only when the original behavior and the follow-on change pass, including the final review required for delivery.
4. **Record every attempt.** Keep the records outside the checkout. For each attempt, record:
   - task, arm, budget, revisions and run IDs
   - initial and follow-on results, confirmed defects and repair cycles
   - owner minutes spent briefing, answering, reviewing and repairing, and interruptions
   - elapsed time for each stage and time to a correct follow-on
   - tokens from harness usage logs and dollars from provider billing or a common dated price schedule. Record unavailable usage as unknown

   Include blocked tasks, timeouts, retries and reverts. They count toward cost and earn zero value until the outcome is delivered.
5. **Decide whether to advance.** Divide each arm's total successful task value by all of its owner hours. Advance the candidate only if, compared with the current workflow, it has:
   - at least 20% more value per owner hour
   - fewer owner minutes in at least three of four pairs
   - at least as many successes
   - no new serious defect or broken contract
   - no more than 10% higher median initial elapsed time, median time to a correct follow-on or total model spend

   A zero denominator leaves the rate comparison inconclusive. Report missing and censored observations. If they could reverse the decision, keep the current workflow.
6. **Confirm before adopting.** Repeat on eight new real tasks in four pairs matched on scope and preassigned value. Choose tasks of equal value within each pair before randomly assigning one to each arm. Reserve a follow-on and acceptance check per task before assignment. Run step 3 on an isolated copy of each delivered revision to measure follow-on time. At day 30, count a success and award its value only for changes that passed both stages and shipped, still serve the requested outcome with no unresolved corrective work. Charge repairs to the original arm and report unknown exposure. Apply the thresholds from step 5. If the candidate passes, adopt it only for the kinds of tasks that benefited.
