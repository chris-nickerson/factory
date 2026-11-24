---
name: software-factory
description: Use Factory for evidence-backed engineering tasks, independent design or diagnosis with GPT and Opus, or size-based Opus simplification rounds on a branch. Supports dependency upgrades, advisory remediation, scoped review and runtime verification across repositories.
---

# Software Factory

Use the executable at `scripts/factory` relative to this skill's real directory, or a matching installed `factory`. Use `factory doctor --profile paired` when a task requires both providers. Start discovery with `factory inspect --repo PATH` and pass `--path` for the affected component. Read the applicable repository instructions and verify which commands exercise the requested behavior. The scan lists candidates and their sources. The host and task determine which actions are authorized.

| User's request | Entry |
| --- | --- |
| Diagnose or decide independently with a second model | Use `factory consensus`. [Consensus procedure](references/consensus.md) |
| Simplify a nontrivial PR | Use `factory simplify`. Select the push-each-round variant when requested. [Simplification procedure](references/simplify.md) |
| Resolve a dependency alert (including Socket) or upgrade a package | Trace the resolved package, make a compatible update, and check the actual consumer. [Dependency updates](references/dependencies.md) |
| Implement, verify, refactor, measure performance, or review a change | Use a frozen local contract and the evidence commands. [Local workflow](references/local.md) |
| Attach a real-world correction to a prior run | Use `factory outcome` with the relevant run and observed behavior. [Later outcomes](references/local.md#later-outcomes) |
| Deliver an implementation with GPT and Opus | Compose consensus if requested, GPT implementation, the size-based Opus rounds, a fresh GPT review and final behavioral checks. [Delivery and continuation](references/delivery.md) |

Run Factory simplification on every nontrivial PR, including local changes intended for a PR. Skip it for trivial edits such as typos or mechanical formatting. Select one fresh Opus round for a straightforward, localized behavior change, two for a moderate change with interacting pieces, and three for a large change or one with substantial access, data, or compatibility risk. Use scope and consequences to choose the tier. Pass the count with `--rounds` and finish the scheduled rounds even when an earlier round makes no edits.

Preserve the requested stopping point. For investigation, establish the observed symptom, test a competing explanation and return the mechanism or missing discriminator. For local fixes, use the repository's normal entry points and separate required build checks from evidence of behavior. For a review-only task, keep the change read-only and substantiate each finding with its real trigger.

Use the selected model and harness for a named profile. Verify any substituted method with the user if it changes a required assurance. Transport errors, missing access, stale evidence and partial coverage belong in the handoff. Use receipts to name the revision, evidence, verdict and remaining work.
