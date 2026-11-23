# Local change and verification

1. Inspect from the target checkout. Record the task boundary, applicable instructions, existing dirty files and intended base. Keep unrelated user edits out of commits. On a mixed branch, pass repeated `--path` arguments to `start` to freeze the review scope. Evidence freshness still uses the whole source set. For non-code or already-fixed dispositions, report the evidence directly. A diagnosis-only task ends with the supported mechanism or next discriminator.
2. Define the observable claims before editing. Put a JSON contract and any independent oracle outside the checkout. Pick checks with meaningful failure exits. Each claim uses a unique ID, an expectation and either an argument vector or a Python oracle. A check may specify a repository-relative working directory. Shell expansion requires an explicitly chosen shell.
3. Start a run, exercise the failure, implement the scoped change, then rerun the claims. Keep the run ID returned by start. CLI commands return JSON. Exit 0 means the command succeeded or the local evidence gate passed, 1 means a checked failure, and 2 means incomplete, stale, or blocked. Start the run with a literal or symbolic base and require review for a full delivery.
4. Where required, run a fresh GPT review of the final candidate and rerun any affected verification after repairs. Inspect the raw logs and actual behavior. The CLI verifies the checks you defined. An incorrect check can still give you a false positive.
5. When setup prevents a real observation, name the unavailable check. Keep that claim open. A GUI account assertion needs a real driver or an explicitly identified human observation. A mock response establishes behavior only up to the mocked boundary.

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
