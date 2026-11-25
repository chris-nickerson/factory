---
name: software-factory
description: Use Factory to verify engineering changes, get an independent review of a scoped diff, or get a design or diagnosis from two models that investigate independently, such as GPT and Claude. Use it for simplification rounds sized to a PR, measured hill-climbing, dependency upgrades and advisory remediation, PR descriptions, and documentation.
---

# Software Factory

Use `scripts/factory` in this skill's real directory or a matching installed `factory`. Run `factory inspect --repo PATH` and pass `--path` for the affected component. Read the repository instructions it finds. The scan lists suggested commands and their sources. Choose commands that exercise the requested behavior.

Factory gives review, simplification and consensus to separate model sessions. Each job is a role, and Factory chooses the harness and model that fill it from the agent CLIs on this machine. You are the host, whichever agent you are. Run `factory roles` to see what each role resolved to and why. When the user names a harness or model for a job, pass it with that role's flag. When a result reports reduced assurance, such as a reviewer from the same vendor as the author, include it in your handoff. If no role can be filled, use the [local evidence workflow](references/local.md). [Roles, harnesses and models](references/roles.md)

## Carry the request into execution

Before choosing a workflow, write a short internal task brief from the conversation. State what the user wants, which actions the user and host allow, what constraints apply and when to stop. Keep the user's wording when it already gives the executing agent enough to act. Include the context a fresh agent needs. Label observations, hypotheses, requirements and decisions the user has delegated. Preserve exact errors, public contracts and explicit limits.

Add detail only when it helps the agent act or judge success. Ground consequential instructions in the request, applicable repository instructions, verified constraints or a genuine task dependency. Leave open implementation choices open. Point to the available evidence that can settle a material uncertainty and choose a check proportionate to the outcome. Ask only when the remaining decision needs the user's judgment.

Use the brief to choose a workflow and guide your next actions. Pass the relevant part to each executing agent. Use `--task` with `factory start`, `consensus` and `simplify`. Keep the brief internal. Proceed to the user's stopping point without a separate prompt-writing or approval exchange. When the user steers the work, update the brief and any affected instructions before you act or hand off work. Carry forward requirements the new direction leaves in place. If it conflicts with a saved task or check, stop using it and start a new run if needed.

| User's request | Entry |
| --- | --- |
| Diagnose or decide independently with a second model | Use `factory consensus`. [Consensus procedure](references/consensus.md) |
| Simplify a nontrivial PR | Use `factory simplify`. Add `--push REMOTE` only if the user requests publication of each round. [Simplification procedure](references/simplify.md) |
| Resolve a dependency alert (including Socket) or upgrade a package | Trace the resolved package, make a compatible update, and check the actual consumer. [Dependency updates](references/dependencies.md) |
| Hill-climb an outcome over successive experiments | Use the [hill-climbing workflow](references/hill-climbing.md) to choose the next trial and decide which change to keep. |
| Implement, verify, refactor, measure performance, or review a change | Use a frozen local contract and the evidence commands. [Local workflow](references/local.md) |
| Write or revise a PR description | Use the [PR writing guide](references/pr-descriptions.md) and the target repository's template. |
| Write, revise or clean up documentation | Use the [Factory writing guide](references/documentation.md). |
| Deliver an implementation with simplification and independent review, including a PR ready for human review | Compose consensus if requested, your implementation, the size-based simplification rounds, a fresh independent review and final behavioral checks, through the verified PR handoff. [Full delivery](references/delivery.md) |
| Prepare an existing PR for review or babysit one | Use the [PR review workflow](references/delivery.md#pr-review-workflow). |
| Attach a real-world correction to a prior run | Use `factory outcome` with the relevant run and observed behavior. [Later outcomes](references/local.md#later-outcomes) |

For a check-only request, run the local checks. If the request requires independent review, include the review step. For verification-only and review-only requests, report the requested results and stop.

If the user only asks you to stop pushing, stop using the push-enabled run and leave its saved state in place. Resuming it would still use the original remote. If the user asks you to continue locally, [release any stopped push-enabled run](references/simplify.md#recovery) and start a new run without `--push`.

For changes to stored data, concurrent writers, replicas, event processing or data-system performance, select a [failure history and consumer observation](references/data-systems.md) when designing or reviewing the contract.

Before freezing acceptance checks, [surface consequential design choices](references/local.md#consequential-design-choices) to the developer or supervising agent, including on tasks without consensus.

When implementing or reviewing a change, [choose which tests to keep](references/local.md#choose-which-tests-to-keep). Name the regression that existing coverage would miss before expanding the suite.

When the user authorizes changes, run Factory simplification on every nontrivial PR, including local changes intended for a PR. Skip it for trivial edits such as typos or mechanical formatting. Select one fresh simplification round for a straightforward, localized behavior change, two for a moderate change with interacting pieces, and three for a large change or one with substantial access, data, or compatibility risk. Use scope and consequences to choose the count. Pass the count with `--rounds` and finish the scheduled rounds even when an earlier round makes no edits. The same consequences decide the model. Each role has a default [model tier](references/roles.md#choose-a-model-tier). Pass `--tier frontier` to `consensus` or `simplify` for a hard design, a diagnosis with competing explanations, or a change where a missed defect would be costly. Keep the default for routine work.

For prose changes, use the [Factory writing guide](references/documentation.md). For code changes, include comment and documentation review in the task brief. Before final review, [review the changed comments and documentation](references/documentation.md#review-comments-in-the-diff), including any added during repairs.

Choose evidence by what controls the outcome. If the product depends on a model making a decision, use the target's supported model and execution path to observe that decision. For behavior determined by code, exercise the code directly. [Choosing model evidence](references/local.md#when-a-model-controls-the-outcome)

Preserve the requested stopping point. For investigation, establish the observed symptom, test a competing explanation and return the mechanism or missing discriminator. For local fixes, use the repository's normal entry points and separate required build checks from evidence of behavior. For a review-only task, keep the change read-only and substantiate each finding with its real trigger.

Use the harness and model Factory resolved for each role. Verify any substituted method with the user if it changes a required assurance. Transport errors, missing access, stale evidence and partial coverage belong in the handoff. Use receipts to name the revision, evidence, verdict and remaining work.
