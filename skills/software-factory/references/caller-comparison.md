# Try the simpler path against its caller

Use this pilot to decide whether a short change to the task brief saves owner time. It uses the usual implementation, simplification and independent review procedures. Use the candidate brief only in the candidate arm.

## Candidate task brief

In the candidate arm, add the following paragraph to the author's task brief. Also pass it to `factory simplify` in `--task`, along with any relevant observations. Leave the [canonical simplifier prompt](reconsider-from-first-principles.v1.txt) unchanged.

> Before adding a second implementation path or deleting an apparently duplicate guard, identify the caller, saved input or external constraint that could distinguish the two paths. Try the simpler implementation against that case. Reuse an existing check or make a disposable probe. For a guard, exercise both an accepted input and the violation it rejects. Use the observed result to choose the implementation and carry it into the handoff. If the paths behave alike for the supported cases, prefer the simpler one. If the evidence is missing, preserve the known contract and state what you could not verify. For routine edits with no such choice, proceed as usual.

For example, an assessment written by an older release can reach the commit step on resume without starting a new model turn. Before deleting an identity check in the reader, resume a matching assessment and one reporting a different model. If only the reader can reject the mismatch, keep the check there and reuse the existing comparison logic. The agent can make that decision under the compatibility contract. Dropping support for an older release requires a policy decision.

## Set up both arms

The owner delegates the task and reviews its result. The operator runs the comparison and records the evidence. One person can do both jobs. Split setup minutes shared by a pair equally between its arms and charge arm-specific work to the arm that incurred it. Report whether the owner knew the assignment.

- Before seeing output, select four wanted tasks: a local behavior change, a multi-caller change, a compatibility or external-tool change and a routine edit. Fix value weights, delivery deadlines and defect severity criteria before assignment. Use equal weights for equally valuable tasks.
- For each task, reserve a realistic follow-on request and executable acceptance checks for both stages. Keep them outside the checkout and hidden from the initial agents.
- Match harness, model, allowed tools, ordinary checks, simplification rounds and budgets. Enforce time and spend limits outside Factory using the same clock and provider limits for both arms.
- Give each evidence run the ordinary task-specific acceptance brief in `factory start --task`. Factory includes this text in its review prompt. Only the candidate author and simplifier receive the extra paragraph. Use neutral worktree and branch names. Keep the author's handoff and trial record outside the blind reviewer's inputs.

## Run the pilot

Run each of the four tasks in both arms, on separate copies of the same revision. Randomize arm order within each pair and alternate which result the owner reads first.

1. Run the hidden initial check on each delivered revision. Record failures as well as passes.
2. Give a fresh agent each passing checkout and its reserved follow-on request. Use the ordinary maintenance workflow for both arms.
3. Run the hidden follow-on check and replay the original check on the modified checkout.
4. A reviewer blind to assignment judges both stages against the frozen contracts. Credit each task once per arm only if both stages and the required delivery reviews pass within budget. Either copy can earn pilot credit without shipping.

Keep one record per attempt outside the checkout. Include the task, arm, budget, revisions, run IDs, owner minutes by activity, interruptions, elapsed time per stage, time to a correct follow-on, unique defects and repair cycles. Use the harness session IDs in the run receipts to attribute tokens from the CLI usage logs and dollars from billing or a common dated price schedule. Include failed runs, retries, timeouts and reverts in time and spend. Mark unavailable usage and censored times explicitly.

## Decide whether to advance

Compare total credited value divided by all owner hours in each arm. Keep the current workflow unless the candidate meets every threshold:

- At least 20% more credited value per owner hour and fewer owner minutes on at least three of four pairs.
- At least as many successful tasks and no new serious defect or broken contract.
- At most 10% higher median initial elapsed time, median time to a correct follow-on and total model spend. Apply the 10% limit to owner minutes on the routine edit as well.

Four pairs screen for an effect. If ordinary variation could explain the gain, stop with an inconclusive result. A further trial needs fresh pairs and a new contract. If either arm records zero owner hours or the baseline arm earns zero value, the percentage gain is undefined. Keep the current workflow in that case or when missing observations could reverse the decision.

## Confirm on shipped work

Enroll eight new real tasks, one pair for each of the four task types. Match the tasks within each pair on scope and preassigned value, then randomly assign one to each arm. Run each task once. Use the same setup, blinding, budgets, acceptance checks and attempt records as the pilot. Run the follow-on stage on an isolated copy of each delivered revision.

Thirty days after each change ships, credit its value only if both stages passed and the shipped change still serves its requested outcome with no unresolved corrective work. Unshipped tasks earn zero at the agreed delivery deadline. Charge repair effort to its original arm and report unknown exposure. Apply the pilot thresholds to these four new pairs. If they pass, adopt only for enrolled task types whose candidate succeeded and used fewer owner minutes than its baseline task. Treat this as a scoped rollout and keep recording later outcomes.
