---
name: software-factory
description: Use Factory for evidence-backed engineering tasks, independent design or diagnosis with GPT and Opus, or three fresh Opus simplification rounds on a branch. Supports local fixes, scoped review and runtime verification across repositories.
---

# Software Factory

Use the executable at `scripts/factory` relative to this skill's real directory, or a matching installed `factory`. Use `factory doctor --profile paired` when a task requires both providers. Start discovery with `factory inspect --repo PATH` and pass `--path` for the affected component. Read the applicable repository instructions and verify which commands exercise the requested behavior. The scan lists candidates and their sources. The host and task determine which actions are authorized.

| User's request | Entry |
| --- | --- |
| Diagnose or decide independently with a second model | Use `factory consensus`. [Consensus procedure](references/consensus.md) |
| Three-pass first-principles simplification | Use `factory simplify`. Select the push-each-round variant when requested. [Simplification procedure](references/simplify.md) |
| Implement, verify, or review a change | Use a frozen local contract and the evidence commands. [Local workflow](references/local.md) |
| Deliver an implementation with GPT and Opus | Compose consensus if requested, GPT implementation, the three Opus rounds, a fresh GPT review and final behavioral checks. [Delivery and continuation](references/delivery.md) |

Preserve the requested stopping point. For investigation, establish the observed symptom, test a competing explanation and return the mechanism or missing discriminator. For local fixes, use the repository's normal entry points and separate required build checks from evidence of behavior. For a review-only task, keep the change read-only and substantiate each finding with its real trigger.

Use the selected model and harness for a named profile. Verify any substituted method with the user if it changes a required assurance. Transport errors, missing access, stale evidence and partial coverage belong in the handoff. Use receipts to name the revision, evidence, verdict and remaining work.
