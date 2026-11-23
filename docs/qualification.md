# Factory qualification

23 November 2026. Factory was exercised through its public CLI, a fresh Codex session using the installed skill in a disposable repository, a native Chrome browser, and local Git remotes. Both the actual GPT and Claude Opus providers ran. An expired Claude login during the first attempt also exercised the blocked path.

## What was exercised

| Surface | Method | Observed result |
| --- | --- | --- |
| Local change, fresh review and evidence | A live Codex engineer repaired a Python duration parser, with an external consumer checking valid hours/minutes and rejection of invalid input. A separate Codex session reviewed the actual change. | Red baseline, successful repair, passing behavioral check and final review. |
| Browser behavior | A live Codex engineer repaired a keyboard-inaccessible disclosure. An external Playwright driver launched Chrome, tabbed to the control and tested Space, Enter, pointer input, visibility and accessibility state. The grader repeated the actions in a different order. | The original implementation failed the Space assertion. Both keyboard and pointer interaction worked after repair. |
| Discovery in existing projects | Inspected a web application, a native application and a monorepo without executing target commands. | Found the npm verify script, simulator test target, nested backend instructions, Python checks and project-owned verification skills. These were discovery checks. |
| Cross-model consensus | Ran design and diagnosis with actual GPT and Claude Opus in independent sessions with same-session replies. | Both agents confirmed the shared calculation in three turns. On a separate report with no timing, workload or trace, both confirmed an inconclusive diagnosis. An earlier attempt with expired Claude authentication stopped before publishing a turn. |
| Three simplification rounds | Ran three fresh sessions reporting `claude-opus-5-5`, each receiving the exact first-principles prompt. The coordinator executed the consumer check, resumed the same session for assessment, and read back the remote ref. | Round one consolidated the duplicate pricing rule. Rounds two and three retained the simpler implementation. All three external checks and remote checkpoints passed. |
| Interruption and publication | Exercised coordinator death, command timeouts, a surviving child, remote divergence, no-change rounds, uncertain commit or push receipts and stale completion. | The regression suite checks preserved ownership, resumable records, clean process shutdown and rejection of conflicting heads. |
| Release management | Installed into disposable prefixes, repeated install, switched between content-addressed releases, rolled back and unlinked the entry. | Rollback restored the old package. A conflicting user-owned executable prevented removal. |

The offline suite includes negative cases for optimized Python assertions, changed source symlink targets, hidden Git index entries, dirty submodules, stale or altered evidence, an empty scoped review, a healthy HTTP endpoint running the wrong build, and a model claiming verification after a failed check. The publication suite also exercises a branch sharing a name with a tag, changed remote URLs, chained Git URL rewrites, and interruption during Git hooks. A scoped review inspects the index even when unstaged changes reverse a staged edit.

## Live comparison

Three fresh Codex implementation sessions handled each task with Factory and three handled the same task directly. All 12 started from failing fixtures. The grading process checked the final code against additional inputs or a different interaction sequence. Each Factory run also required an independent GPT review on its final subject.

| Task | Factory behavioral passes | Direct behavioral passes | Factory final reviews cleared | Median implementation time, Factory / direct |
| --- | --- | --- | --- | --- |
| Duration parser | 3/3 | 3/3 | 3/3 | 36.6 s / 27.5 s |
| Keyboard disclosure | 3/3 | 3/3 | 3/3 | 55.8 s / 67.2 s |

The timing includes grader startup and excludes the subsequent independent review. The cases ran concurrently and Factory received reliability fixes during the pilot. Treat these as operational observations. Both methods solved these small tasks. Factory additionally produced a frozen contract, baseline failure, independently replayable result, fresh review and revision-bound receipts. Larger tasks, human rework and escaped defects require separate measurement.

## Boundaries of the evidence

The engine verifies a concrete contract. The author of a claim must pick an observation capable of disproving it. An external server, database, account or hosted deployment can change even when the local source is unchanged. Put the build/environment identity in the check and rerun it when the environment changes. Local source identity covers Git-visible files and modes, regular-file symlink targets, and initialized submodules. Ignored dependencies and external services have their own verification surfaces.

All 70 regression tests passed on macOS ARM64 with Python 3.13 and Linux ARM64 with Python 3.11. The macOS Python 3.11 run is also part of the release's local verification contract. The qualified execution environment is POSIX. Hosts need Git for Git workflows, Python 3.11+ and any target-specific tools. The watchdog supervises a process group. Services that deliberately leave that group need their own lifecycle adapter. Review scopes can be narrowed by path. Simplification requires a clean committed branch and a known base. All durable state and provider receipts are local to the configured state directory.

During the first live simplification, Opus tried to open the external grader during its read-only assessment. The harness recorded the denied read and paused. Inspection showed the edit and a passing check. We clarified how the assessor should use coordinator-provided results and resumed the same session. All three rounds completed. The qualification grader now prints which behavioral cases passed.

A clean Auto delivery trial confirmed a design in five turns and an inconclusive diagnosis in three. Three distinct Opus sessions received the canonical prompt, published a checked first-round simplification and retained it in the following rounds. All three remote readbacks matched, the external consumer passed, and a fresh GPT review returned CLEAR.

The Auto editing profile was also exercised through the public Claude Code CLI on macOS. Opus edited a function and ran its Python test with Bash. A marker written by the test and an independent replay confirmed execution. A resumed assessment could neither execute Bash nor create a file with Write. A direct Git commit attempt was denied during an Auto editing turn and the repository head stayed fixed. A Python bytecode cache surfaced as an out-of-scope change in the pricing fixture. Factory passes the Python bytecode setting to Claude Code and the fixture declares its interpreter cache in Git ignore rules. An unexpected unignored output still stops a round for reconciliation.

Reproduce the paired workflow with `python3 evals/qualify_pair.py /tmp/factory-pair-new` in this checkout. It performs both discussions, runs three simplification rounds against a disposable local bare remote, and requires a fresh GPT review and an observed edit. Hosted PR mutation, merge, production deployment, and native Windows execution remain outside this pilot. The full-delivery skill delegates authorized forge operations to the host agent and target repository.

## Reproduce

```sh
python3 -B -m unittest discover -s tests -v
./factory doctor
python3 -B evals/qualify.py library /tmp/factory-library-new
python3 -B evals/qualify.py library /tmp/factory-library-direct-new --direct
```

The live runner requires authenticated Codex access. For the browser case, use `web` in place of `library` and set `FACTORY_PLAYWRIGHT` to a resolvable Node package exporting Playwright's Chromium driver. It launches the installed Chrome channel. Each invocation requires a new output directory and preserves its independent grader output, transcript, timing and review decision for inspection.
