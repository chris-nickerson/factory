# Local change and verification

1. Inspect from the target checkout. Record the task boundary, applicable instructions, existing dirty files and intended base. Keep unrelated user edits out of commits. On a mixed branch, pass repeated `--path` arguments to `start` to freeze the review scope. Evidence freshness still uses the whole source set. For non-code or already-fixed dispositions, report the evidence directly. A diagnosis-only task ends with the supported mechanism or next discriminator.
2. Define the observable claims before editing. Put a JSON contract and any independent oracle outside the checkout. Pick checks with meaningful failure exits. Each claim uses a unique ID, an expectation and either an argument vector or a Python oracle. A check may specify a repository-relative working directory. Shell expansion requires an explicitly chosen shell.
3. Start a run and capture the baseline that fits the task. Implement the scoped change, then replay the frozen claims. Keep the run ID returned by start. CLI commands return JSON. Exit 0 means the command succeeded or the local evidence gate passed, 1 means a checked failure, and 2 means incomplete, stale, or blocked. Start the run with a literal or symbolic base and require review for a full delivery.
4. Where required, run a fresh GPT review of the final candidate and rerun any affected verification after repairs. Inspect the raw logs and actual behavior. The CLI verifies the checks you defined. An incorrect check can still give you a false positive.
5. When setup prevents a real observation, name the unavailable check. Keep that claim open. A GUI account assertion needs a real driver or an explicitly identified human observation. A mock response establishes behavior only up to the mocked boundary.

## Consequential design choices

When two viable approaches satisfy the request but differ materially in what users experience, what maintainers must support, or how costly the choice is to reverse, surface the choice while the caller can still influence it. Keep routine, reversible implementation details in the normal workflow.

Start with the outcome the caller asked for and the constraints that actually bind it. Trace what the system must do to deliver that outcome. Identify which claims come from the code, a trace or a measurement, and which depend on assumptions. Where comparable systems or current engineering practice can inform the choice, consult primary sources, link them and explain which conditions carry over.

Give the developer or supervising agent a short comparison in the conversation before implementing an option or freezing checks that select it. For each credible option, explain what users would notice and what the code would have to own. Recommend one, explain the deciding trade-off and name the observation or priority that would reverse it. If the caller already chose a policy, carry it forward. If they delegated the choice, identify it as the agent's decision and proceed. If an unresolved priority would change the choice and belongs to the caller, ask one focused question. Continue work and checks shared by the options while awaiting the answer. Carry the choice, who made it and why into the existing brief and PR.

For example, a chat user wants to send another message as soon as an answer finishes. A trace showing the stream waiting on unused sandbox startup justifies testing that a text-only follow-up succeeds while startup is stalled. Both background warmup and startup on first use can pass that test. Warmup can shorten the wait at the first sandbox operation, but spends capacity on unused starts and needs an owner for work that outlives a turn. Starting on demand avoids that work and puts startup latency on the first operation. How often users need a sandbox and what that wait costs them would affect the recommendation. An assertion that a text-only turn starts zero sandboxes selects the on-demand policy. Freeze it only if that policy was chosen.

## Choose the baseline

- **Bug fix or new behavior.** Exercise the reported failure or missing behavior through the public entry point. Replay the same case after the change.
- **Behavior-preserving refactor.** Capture a passing example on the original implementation. Replay the same inputs against the candidate and compare observable output, errors or side effects. If a contract crosses a release or process boundary, exercise the consumer that depends on it. For a saved format, keep a record written by the released version and open it with the candidate. A candidate reading its own output covers a different case.
- **Performance claim.** Define the operation the user waits for, a representative workload and the metric. Check that both versions complete the same amount of correct work inside the timed interval, including deferred work and failures. Match meaningful settings and cache state, alternate repeated baseline and candidate runs, and report the unit, median and spread. If variation obscures the difference, report it as inconclusive. A contract can run the project's benchmark and retain its raw samples beside the correctness result.
- **Checks that enforce a requirement.** Choose a valid input and a known violation from the requirement or last accepted release. Run both through the command or service that decides whether work proceeds. A passing build on valid input cannot show that the check still blocks a violation. Assert the outcome its caller uses. The rule can move between files, and a CI job may treat every nonzero exit alike. For an intentional policy change, choose examples on either side of the new boundary. Reuse existing evidence when it already shows both outcomes.

## Choose which tests to keep

Start with the failure a caller would observe. Read the nearest tests and the repository’s testing requirements. If an existing check catches that failure, demonstrate it. Extend a case or strengthen an assertion when that closes the gap. Add a permanent test when it protects a distinct behavior worth maintaining. A one-time probe, migration rehearsal or comparison can stay in the run evidence.

Use the cheapest boundary that can expose the fault. Drive the real consumer when the risk lies in wiring, storage, process lifetime or compatibility. Use a clock, fake or stub to control an external dependency when it preserves the behavior in question. Derive the expected result from the requirement, a trusted example or an invariant. Assert exact error text or payload fields only when callers depend on them. A useful test fails on a plausible wrong result and stays green after an internal refactor. For a disputed assertion, try both edits in a disposable checkout.

Control time, randomness and shared state. Wait for observable events with bounded waits. Give randomized failures replayable inputs. Investigate a flaky failure before accepting a retry. Keep setup small enough that a failure points to the broken promise. Profile slow feedback before dropping coverage.

When replacing or removing a test, identify the guarantee that survives elsewhere or the requirement that changed. Protect published formats, significant side effects and failure paths, including cases where exact bytes matter. Judge the suite by the regressions it catches and the cost of keeping it trustworthy. Test counts and coverage percentages alone cannot answer either question.

## When a model controls the outcome

Identify the decision the user depends on and where it happens. Use deterministic checks for guarantees the runtime enforces, including any side effects it prevents. If success also depends on a model interpreting input, choosing an action or stopping, put a real model run through that decision in the contract. A reviewer model reading the diff or a scripted model response exercises a different boundary.

Start with the project's eval runner, supported model and normal inputs. Choose a case that could disprove the claim and an observable outcome, such as the resulting artifact, action trace or scored response. A local fixture can stand in for external effects. Record what it replaces. Run a baseline or simpler candidate under the same conditions when claiming an improvement; a passing baseline leaves that improvement unproven.

Use contrasting inputs when claiming generality. Include other supported models when their behavior matters to the claim, and repeat trials when estimating reliability. Record the revision, model and settings, cases, outcomes and trial counts. Limit the conclusion to what those runs sampled. If a required model or harness is unavailable, keep that claim open and finish the checks that can run.

Example contract for a public library function, with a separate engineering check:

```json
[
  {"id":"addition","expect":"consumer receives 5 and -1 for the specified input pairs","oracle":"consumer.py"},
  {"id":"suite","expect":"required repository unit tests pass","argv":["python3","-m","unittest","discover"]}
]
```

An oracle is copied into the frozen run contract. Factory executes it in a new Python process with the target as its working directory. Import the target as a real consumer would. For a local source import, add `os.getcwd()` to the oracle's module search path. Let failed assertions or other errors exit nonzero. For an external service, verify the responding build identity inside the oracle. Keep the contract and any attached state outside the workspace.

```sh
factory inspect --repo .
factory start --repo . --task "Fix incorrect addition" --contract /path/to/contract.json --require-review --base HEAD
factory check RUN_ID
factory review RUN_ID
factory status RUN_ID
```

A run tracks the whole Git source set, including staged content, unstaged changes and unignored new files. In plain folders it hashes the whole tree. Put generated outputs in the repository's established ignored directories or outside it. A check that changes the subject cannot establish a pass. Receipts persist under `FACTORY_STATE_DIR` or the user's XDG state directory. One local Factory operation locks a workspace at a time. Other applications can still write to it.

For build-only, configuration, documentation or unusual tasks, choose a fitting consumer or artifact check. An independent Python oracle can call any installed runtime. A target can declare repeatable command candidates as argument arrays in the `[checks]` table of `software-factory.toml`. Inspect reads those declarations, and the agent selects an appropriate check for the contract.

## Later outcomes

When the user reports a correction or real-world outcome, use `factory outcome RUN_ID --note "what happened"` and optionally `--evidence TICKET_OR_ARTIFACT`. Factory stores the reference as text. Use `factory outcome RUN_ID` to see the observations and evidence-bearing revision fingerprints, including after checkout removal. Select `--subject FINGERPRINT` if several revisions were checked. Repeating the same observation and reference on one revision returns the original record.

When asked to learn from feedback, inspect the cited evidence and the original contract. Propose the smallest check or workflow change that would have caught the miss. Name the repository, harness, task type or explicit preference that limits its scope. Try the proposal on the original case, a second applicable case and an unrelated control. Use synthetic reproductions for cross-repository work and keep private evidence local. Promotion to a shared workflow is a separate reviewed change.
