# Software Factory

I want coding agents to understand a problem before they change code, make the smallest change that holds up, and give me enough evidence to decide what to do next. Sometimes that means shipping a small fix. Sometimes it means finding the missing evidence, simplifying a design, or leaving the code alone. I’m building Software Factory to grow into a way of working across the whole engineering task, from the first question through the pull request.

Today, Factory is an installable agent skill and a local CLI. The skill reads your request, chooses a workflow, and carries your constraints through the work using the repository’s own instructions and tools. The CLI runs checks, saves what happened, and coordinates separate model sessions when a workflow calls for them.

## What you can ask for

| If you need to | Ask Factory to |
| --- | --- |
| Fix a bug or build a change | Confirm the behavior through a real entry point, make the change, and show what happens afterward. |
| Diagnose a stall or slow operation | Collect a live trace or analyze the one you supply, identify the cause, and measure a repair when requested. |
| Try a design or match a reference UI | Build a disposable prototype to settle the decision, or render both versions to check visual parity. |
| Compare two implementations of a command | Replay the same workload in two checkouts and compare its output and elapsed time. |
| Deliver a stack of PRs | Check each parent and child, follow CI and review feedback, and land eligible changes when asked. |
| Decide between designs or diagnose a hard problem | Have two models investigate independently, then compare the evidence behind their conclusions. |
| Simplify a branch | Give fresh model sessions the branch, its constraints, and the checks it must pass. |
| Upgrade a dependency or clear a scanner alert | Find which version the project actually installs and check the code that uses it. |
| Review a change | Have a fresh session from a model that didn’t write the change review the scoped diff and back each finding with the case that triggers it. |
| Coordinate a migration across several branches | Show which pieces can start, which depend on earlier work, and which need fresh evidence when you pick the project back up. [Plan a multi-stage change](skills/software-factory/references/plans.md) |
| Prepare a pull request | Explain the change, follow CI and review feedback, and fix confirmed issues. |
| Improve documentation | Check what the project does and write instructions someone can follow without reading the ticket. |

## Install

You need macOS or Linux, Git, and Python 3.11 or later.

```sh
git clone https://github.com/chris-nickerson/factory.git
cd factory
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
factory doctor
```

The installer puts the CLI in `~/.local/bin` and the skill in `~/.agents/skills/software-factory`. The skill includes a regular `SKILL.md` for hosts that skip directory symlinks. To keep the CLI available in new shells, add `~/.local/bin` to your shell’s `PATH`.

### Try it on a real task

Open one of your repositories in a new coding-agent session, then ask for the outcome you want.

> Use Software Factory to reproduce this bug, fix it, and verify it through the public entry point. Keep the change local.

> Use Software Factory to get a second diagnosis from another model. Stay read-only and tell me what observation would settle the disagreement.

### Which model does which job

Review, simplification and two-model decisions each run in a separate model session through an agent CLI you have installed. Factory supports Codex and Claude Code, and you can start it from either one. A review is worth more when the reviewer isn’t the model that wrote the change, so with both installed Factory has Claude simplify and Codex review, and pairs the two for a design or diagnosis. With one installed, everything still runs and Factory tells you which assurance is reduced, such as a review from the same vendor as the author.

```sh
factory roles
```

The command shows which CLI and model fill each role on your machine and why. Each role also has a model tier. The reviewer uses the most capable family, and repeated simplification and discussion turns use a cheaper one. Override either per run or in a config file. [Roles, harnesses and models](skills/software-factory/references/roles.md) explains the choices. Without either CLI, use the [local workflow](skills/software-factory/references/local.md) to run checks.

## Update

```sh
factory update
```

Factory installs the latest `main` from the repository you installed from. It shows incoming commits when the prior source commit and intervening history are available. Use `--json` for a machine-readable report. To roll back, run `python3 install.py --rollback` from an up-to-date checkout with the original install prefix.

Let the command finish before opening a new agent session. During the switch, the CLI and skill files can come from different releases. If the command stops partway through, rerun it to finish the switch.

<details>
<summary>Older installs and local run records</summary>

If the default skill directory is still a symlink or its entry points to `release/SKILL.md` after updating, rerun `factory update` or run `python3 install.py` from an updated checkout. If you installed with a custom prefix, migrate from the original home directory so Factory can find the default skill path. Rolling back to a release that predates this layout restores the symlink.

Keep the installed skill path out of Git’s index. If the index tracks an older symlink at that path, remove the index entry before verifying changes in the checkout.

Factory saves run records outside your project in `~/.local/state/software-factory` by default. Set `FACTORY_STATE_DIR` to change the location. Use the same state directory for every Factory command on a worktree so the commands share its lock and know which run owns it. Records can include source code and command output. The checks and saved records rely on the local account that runs them.

</details>

## Learn more

- [The skill](skills/software-factory/SKILL.md) shows how Factory chooses a procedure and what each procedure allows.
- [How Factory works](docs/architecture.md) follows a local check, an independent model discussion, and a simplification round.
- `factory --help` lists the commands and options.

## See evidence go stale

[Try Factory offline](docs/architecture.md#try-factory-offline) to see what happens to an earlier check result after the source changes. The example runs from a checkout with Git and Python and needs no model login.

## Work on Factory

Use the [contributor guide](CONTRIBUTING.md) to find where a change belongs and how to verify it. Run the offline suite from the checkout.

```sh
python3 -B -m unittest discover -s tests -v
```

## License

Software Factory is available under the [MIT License](LICENSE). See the [security policy](SECURITY.md) to report a vulnerability privately.
