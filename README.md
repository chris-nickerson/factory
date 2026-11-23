# Software Factory

Software Factory is a portable agent skill and local CLI for evidence-backed engineering. An agent can discover a repository's commands, fix a defect, run independent acceptance checks, obtain a fresh GPT review, or coordinate a design discussion and three Opus simplification rounds. The run record tracks which revision each observation covers.

## Start using it

From this checkout on macOS or Linux with Git and Python 3.11 or later:

```sh
./factory doctor
./factory inspect --repo /path/to/project
python3 install.py --dry-run
python3 install.py
```

The installer places `factory` in `~/.local/bin` and `software-factory` in `~/.agents/skills` by default. Add that bin directory to your PATH if needed. In a fresh Codex session opened in your target repository, ask **“Use Software Factory to reproduce this bug, fix it locally, and verify the fix through the public entry point.”** The agent authors and executes the checks using the procedures packaged with the skill.

For a Claude Code project, supply `--skill-dir /path/to/project/.claude/skills` with a separate `--prefix` for that installation. Codex and Cursor also support project-local `.agents/skills`. For a shell-capable agent without native skills, supply the installed `SKILL.md` as its entry point. For a one-off run, call `./factory` directly from this checkout. [Agent entry and routes](skills/software-factory/SKILL.md)

## Choose a workflow

| Goal | Entry point | What you get |
| --- | --- | --- |
| Discover how a component works | `factory inspect --repo PATH --path component/file` | Applicable instruction paths, manifests, CI, local skills and command candidates with working directories. |
| Verify a change locally | `factory start --repo PATH --task TEXT --contract FILE`, then `factory check RUN_ID` | Frozen expectations and commands, captured output and a result per claim. [Contract example](skills/software-factory/references/local.md) |
| Get an independent GPT review | Include `--require-review --base REF` at start, then `factory review RUN_ID` | Fresh read-only Codex review. Repeated `--path` at start limits its scope on a mixed branch. `factory status RUN_ID` rechecks evidence freshness. |
| Argue a design or diagnosis | `factory consensus design --repo PATH --task TEXT` or `factory consensus diagnosis ...` | Independent GPT/Opus openings and a bounded dialogue. The final acknowledgment binds both agents to the same proposal. [Consensus and recovery](skills/software-factory/references/consensus.md) |
| Run the three simplification rounds | `factory simplify --repo PATH --base REF --task TEXT --check 'make test'` | Three fresh Opus sessions with Auto editing, sandboxed shell and local tests. Factory runs independent checks, obtains a read-only assessment and owns Git checkpoints. Add `--push REMOTE` for per-round commit publication and remote head readback. [Three-round procedure](skills/software-factory/references/simplify.md) |
| Deliver a complete change | Ask a coordinating GPT agent to use the full delivery profile | Implementation, the selected collaboration phases, a fresh whole-change review and final behavioral verification. The coordinating agent drives repo-specific PR/CI work within the requested scope. [Delivery procedure](skills/software-factory/references/delivery.md) |

Run `factory doctor --profile paired` to check the local Codex and Claude Code installations and their reported login state. Named cross-model workflows require working model access. Budget exhaustion, a missing peer, stale evidence or an observed regression stays visible in the result. The CLI uses exit 0 for success, 1 for failed local evidence and 2 for incomplete or blocked work.

## Record a later outcome

Use `factory outcome RUN_ID --note "Reopened: pointer works, Space does not" --evidence TICKET-123` to attach an observation. Read it with `factory outcome RUN_ID`. If the run checked multiple revisions, select the fingerprint with `--subject`. An outcome is local feedback about a particular revision. The original verification verdict still describes the frozen checks. [Using feedback](skills/software-factory/references/local.md#later-outcomes)

## State and upgrades

Runs use `$FACTORY_STATE_DIR` or `$XDG_STATE_HOME/software-factory` (default `~/.local/state/software-factory`). Keep state outside the target checkout. Evidence can contain source, change descriptions and command output. The CLI stores it locally. Cross-model runs send their task context to the configured providers.

Installations reference content-addressed copies of the complete skill and executable. Rerun `python3 install.py` to install an updated checkout, `python3 install.py --rollback` to switch to the previous release, or `python3 install.py --remove` to unlink that installation. Use the original prefix for each operation. Existing unrelated skills and foreign executables are preserved.

## Verification and design

Run `python3 -B -m unittest discover -s tests -v` for the offline regression suite. It uses real Git worktrees, subprocesses and local bare remotes. The optional live qualification runs an actual Codex agent on a disposable library or web task and grades the resulting code from outside the checkout. [Local task qualification](evals/qualify.py) · [Live paired qualification](evals/qualify_pair.py) · [Test results and limits](docs/qualification.md)
