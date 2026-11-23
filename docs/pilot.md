# Pilot design

The first question was whether a portable workflow could fix a defect, verify it through a real consumer and leave enough evidence for another engineer to check the result. A useful baseline was an agent working directly from the target repository's instructions. The same task, starting code and held-back grader could then be used on both paths. [Observed pilot results](qualification.md)

## Choosing cases

| Case | Behavior the grader must distinguish |
| --- | --- |
| Library bug | A plausible explanation can accompany a function that still returns the wrong value. Call the public function with an additional input. |
| Browser interaction | A pointer can expand a disclosure when a keyboard cannot. Exercise Space and Enter as well as pointer input, and observe accessibility state. |
| Dirty branch | An unstaged edit can undo a staged change. Examine both the index and working tree, scoped to the requested change. |
| Changed subject | A previously passing command describes an earlier revision. Recompute identity before accepting its receipt. |
| Interrupted publication | A push can succeed before its receipt is written. Recover from the observed remote head and preserve independent branch changes. |
| Insufficient evidence | Agreement between agents can coexist with a missing observation. Record the uncertainty and the next discriminating experiment. |

For each task, begin with a clean fixture and verify the failing baseline. Run the grader against the produced code in a separate process. Retain blocked runs in the denominator. Compare behavioral outcomes first, then examine review findings, elapsed time, model usage and human rework. Small samples can reveal failure mechanisms. Estimating escaped-defect rates requires longer observation.

## Learning from a miss

A later correction can become a candidate check. Record the observed behavior and the revision it concerns, then try the check on the original case, another relevant implementation and an unrelated control. Repository-specific expectations stay with that project. The keyboard transfer experiment exercises this procedure on two browser fixtures and a CLI control. [Experiment](../evals/outcome_transfer.py) · [Outcome records](../skills/software-factory/references/local.md#later-outcomes)
