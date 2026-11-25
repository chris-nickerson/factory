# Design and root-cause consensus

Use this workflow when the user asks two models to agree on a design or diagnosis. Factory reports their agreement, an unresolved disagreement or the capability needed to proceed. The participants work read-only. To implement an accepted design, start a separate change workflow within the user's authorization.

From the installed skill, run the following commands using its `scripts/factory` executable. Replace `./factory` below with that executable when working outside the Factory repository.

```sh
./factory consensus design --repo . --task 'Choose the migration order. Preserve old clients and explain the acceptance cases.'
./factory consensus diagnosis --repo . --task 'Identify what causes the duplicate rows. Distinguish a replay from a second request.'
./factory consensus status RUN_ID
./factory consensus resume RUN_ID
```

Give the request the observable facts, requirements, evidence locators and desired decision. The driver sends the task to both participants and grants each read access to the target checkout. Use this workflow where sending the task to those harnesses is in scope. The read-only harnesses may inspect sources, but some checks need capabilities outside this workflow. Disclose the missing observation in the decision or supply a neutral reproduction artifact before starting. The read and isolation guarantees of each harness apply. Independence of the initial reports is enforced by the coordinator's delivery order and reinforced by its role instructions. The native host determines filesystem isolation.

For a consequential design, put the shared outcome, constraints, evidence and open questions in the neutral task so both models can test the assumptions independently. Bring their recommendation, strongest alternative and any unresolved disagreement back to the caller using the [design choice guidance](local.md#consequential-design-choices). A confirmed proposal records agreement between the models. The caller’s choice or delegation determines which policy enters implementation.

## Role and turn rules

- Factory fills participants A and B from different vendors when two harnesses are available. Set either one with `--a SPEC` or `--b SPEC`. Both default to the `standard` model tier. For a hard design or a diagnosis with competing explanations, raise both with `--tier frontier`. With one harness, both participants use it and the result's `reductions` field says so. `--gpt-model` and `--opus-model` still set the model for the participant that uses Codex or Claude Code. [Roles, harnesses and models](roles.md)
- Keep each opening session for that participant's later turns. Read the requested and reported model from each call's receipt.
- Both agents receive the same neutral task. Each creates a fresh independent opening. The first discussion turn appears only after both reports have been saved. B then sees A, and A receives B's opening and response. Models can propose a design, challenge a diagnosis, or identify evidence that is unavailable.
- A owns odd numbered turns and B owns even turns. A substantive proposal ends with `STATUS: RESOLUTION_PROPOSED`. A continuing investigation ends with `STATUS: OPEN`. To accept a specific proposal the agent sends exactly two lines, `ACCEPT: turn_NNN_x.md` followed by `STATUS: CONFIRMED`. An amendment creates a new proposal. A final acknowledgment from A must name the same proposal B endorsed. A diagnosis proposal places `DISPOSITION: CAUSE_IDENTIFIED` or `DISPOSITION: INCONCLUSIVE` immediately above its final status line. The result exposes this disposition separately from agreement.
- The default budget is three exchanges and A's final response. Use `--exchanges` at start to change the turn count. Agents can take as long as they need. Keep the coordinator running while waiting for a result. Malformed replies get one same-session formatting correction. Exit 0 means both parties confirmed. Exit 2 means pending, blocked or budget exhausted.
- The JSON report includes the run ID, source digest, artifact directory, participants, proposal ID and accepted text when confirmed. Inspect the numbered Markdown turns and per-call receipts for reasoning, actual session IDs and reported models. `status` and `resume` compare the source to its original digest. A changed workspace leaves the decision as historical evidence.
- An interrupted call with a durable successful receipt is reused. If a provider fails, resolve the failure and resume on the original source. Older runs can resume after their former deadlines. An ambiguous live process blocks another dispatch. Unresolved disagreement or a changed subject calls for a newly scoped investigation. Keep the prior run as historical evidence.
