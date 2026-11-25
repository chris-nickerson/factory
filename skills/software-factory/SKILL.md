---
name: software-factory
description: Use Factory for evidence-backed engineering tasks, independent design or diagnosis with GPT and Opus, or size-based Opus simplification rounds on a branch. Supports measured hill-climbing, dependency upgrades, advisory remediation, writing PR descriptions and documentation, scoped review and runtime verification across repositories.
---

# Software Factory

Use the executable at `scripts/factory` relative to this skill's real directory, or a matching installed `factory`. Use `factory doctor --profile paired` when a task requires both providers. Start discovery with `factory inspect --repo PATH` and pass `--path` for the affected component. Read the applicable repository instructions and verify which commands exercise the requested behavior. The scan lists candidates and their sources. The host and task determine which actions are authorized.

On hosts without the provider CLIs, use `factory doctor --profile local` and the [local evidence workflow](references/local.md). Independent review requires Codex; simplification requires Claude Code; consensus requires both.

## Carry the request into execution

For each ordinary request, use the conversation to form a working brief before choosing a workflow. Keep the user's words when they already give the executing agent enough to act. Resolve references and corrections, carrying forward requirements the correction leaves in place. State what the user wants to receive, what actions they authorize, the constraints and where work should stop. Include context a fresh agent would otherwise lose. Distinguish observations, hypotheses, requirements and delegated decisions. Preserve exact errors, public contracts and explicit limits.

Add detail only when it helps the agent act or judge success. Ground consequential instructions in the request, applicable repository instructions, verified constraints or a genuine task dependency. Leave open implementation choices open. Point to the available evidence that can settle a material uncertainty and choose a check proportionate to the outcome. Ask only when the remaining decision needs the user's judgment.

Use the brief to select the workflow below and guide your own next actions. Pass the relevant part to each executing agent, using `--task` for `factory start`, `consensus` and `simplify`. Keep the brief internal and proceed through the user's stopping point without a prompt-writing or approval exchange. When the user steers the work, the conversation governs: update the affected instructions before further actions or handoffs. If a frozen task or check conflicts with the correction, stop using it and start a newly scoped run when needed.

| User's request | Entry |
| --- | --- |
| Diagnose or decide independently with a second model | Use `factory consensus`. [Consensus procedure](references/consensus.md) |
| Simplify a nontrivial PR | Use `factory simplify`. Select the push-each-round variant when requested. [Simplification procedure](references/simplify.md) |
| Resolve a dependency alert (including Socket) or upgrade a package | Trace the resolved package, make a compatible update, and check the actual consumer. [Dependency updates](references/dependencies.md) |
| Hill-climb an outcome over successive experiments | Use the [hill-climbing workflow](references/hill-climbing.md) to choose the next trial and decide which change to keep. |
| Implement, verify, refactor, measure performance, or review a change | Use a frozen local contract and the evidence commands. [Local workflow](references/local.md) |
| Write or revise a PR description | Use the [PR writing guide](references/pr-descriptions.md) and the target repository's template. |
| Write, revise or clean up documentation | Use the [documentation guide](references/documentation.md). |
| Prepare a PR for review or babysit one | Use the [PR review workflow](references/delivery.md#pr-review-workflow). |
| Attach a real-world correction to a prior run | Use `factory outcome` with the relevant run and observed behavior. [Later outcomes](references/local.md#later-outcomes) |
| Deliver an implementation with GPT and Opus | Compose consensus if requested, GPT implementation, the size-based Opus rounds, a fresh GPT review and final behavioral checks. [Delivery and continuation](references/delivery.md) |

For changes to stored data, concurrent writers, replicas, event processing or data-system performance, select a [failure history and consumer observation](references/data-systems.md) when designing or reviewing the contract.

Before freezing acceptance checks, [surface consequential design choices](references/local.md#consequential-design-choices) to the developer or supervising agent, including on tasks without consensus.

When implementing or reviewing a change, [choose which tests to keep](references/local.md#choose-which-tests-to-keep). Name the regression that existing coverage would miss before expanding the suite.

Run Factory simplification on every nontrivial PR, including local changes intended for a PR. Skip it for trivial edits such as typos or mechanical formatting. Select one fresh Opus round for a straightforward, localized behavior change, two for a moderate change with interacting pieces, and three for a large change or one with substantial access, data, or compatibility risk. Use scope and consequences to choose the tier. Pass the count with `--rounds` and finish the scheduled rounds even when an earlier round makes no edits.

Include comment and documentation review in the task brief for code changes. Before final review, [review the changed comments and documentation](references/documentation.md#review-comments-in-the-diff), including any added during repairs.

Choose evidence by what controls the outcome. If the product depends on a model making a decision, use the target's supported model and execution path to observe that decision. For behavior determined by code, exercise the code directly. [Choosing model evidence](references/local.md#when-a-model-controls-the-outcome)

Preserve the requested stopping point. For investigation, establish the observed symptom, test a competing explanation and return the mechanism or missing discriminator. For local fixes, use the repository's normal entry points and separate required build checks from evidence of behavior. For a review-only task, keep the change read-only and substantiate each finding with its real trigger.

Use the selected model and harness for a named profile. Verify any substituted method with the user if it changes a required assurance. Transport errors, missing access, stale evidence and partial coverage belong in the handoff. Use receipts to name the revision, evidence, verdict and remaining work.
