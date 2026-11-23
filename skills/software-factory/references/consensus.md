# Design and root-cause consensus

Use this workflow when the user requests cross-model agreement about a design or diagnosis. It returns an agreed decision with caveats, an unresolved disagreement, or the missing capability. The frozen task stays read-only. Start a separate authorized change workflow to implement an accepted design.

From the installed skill, run the following commands using its `scripts/factory` executable. Replace `./factory` below with that executable when working outside the Factory repository.

```sh
./factory consensus design --repo . --task 'Choose the migration order. Preserve old clients and explain the acceptance cases.'
./factory consensus diagnosis --repo . --task 'Identify what causes the duplicate rows. Distinguish a replay from a second request.'
./factory consensus status RUN_ID
./factory consensus resume RUN_ID
```

Give the request the observable facts, requirements, evidence locators and desired decision. The driver sends the task and grants read access to the target checkout to Codex and Claude Code. Use the paired workflow where this use of both providers is in scope. The read-only harnesses may inspect sources, but some checks need capabilities outside this workflow. Disclose the missing observation in the decision or supply a neutral reproduction artifact before starting. The read and isolation guarantees of each harness apply. Independence of the initial reports is enforced by the coordinator's delivery order and reinforced by its role instructions. The native host determines filesystem isolation.

## Role and turn rules

- A uses Codex with its configured model or `--gpt-model`. B uses Claude Code with `opus` or `--opus-model`. Keep each opening session for that participant's later turns. Interpret reported model identity from its receipt when available.
- Both agents receive the same neutral task. Each creates a fresh independent opening. The first discussion turn appears only after both reports have been saved. B then sees A, and A receives B's opening and response. Models can propose a design, challenge a diagnosis, or identify evidence that is unavailable.
- A owns odd numbered turns and B owns even turns. A substantive proposal ends with `STATUS: RESOLUTION_PROPOSED`. A continuing investigation ends with `STATUS: OPEN`. To accept a specific proposal the agent sends exactly two lines, `ACCEPT: turn_NNN_x.md` followed by `STATUS: CONFIRMED`. An amendment creates a new proposal. A final acknowledgment from A must name the same proposal B endorsed. A diagnosis proposal places `DISPOSITION: CAUSE_IDENTIFIED` or `DISPOSITION: INCONCLUSIVE` immediately above its final status line. The result exposes this disposition separately from agreement.
- The default budget is three exchanges and A's final response. Use `--exchanges` at start to change the turn count. Agents can take as long as they need. Keep the coordinator running while waiting for a result. Malformed replies get one same-session formatting correction. Exit 0 means both parties confirmed. Exit 2 means pending, blocked or budget exhausted.
- The JSON report includes the run ID, source digest, artifact directory, proposal ID and accepted text when confirmed. Inspect the numbered Markdown turns and per-call receipts for reasoning, actual session IDs and reported models. `status` and `resume` compare the source to its original digest. A changed workspace leaves the decision as historical evidence.
- An interrupted call with a durable successful receipt is reused. If a provider fails, resolve the failure and resume on the original source. Older runs can resume after their former deadlines. An ambiguous live process blocks another dispatch. Unresolved disagreement or a changed subject calls for a newly scoped investigation. Keep the prior run as historical evidence.
