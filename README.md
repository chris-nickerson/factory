# Software Factory

I’m building Software Factory around how I want to work with coding agents. When I describe a bug, I want the agent to figure out why it happens before changing the code. When I ask for a second opinion, I want someone to look at the problem independently. When the work is done, I want to see what changed and what I can rely on.

I want Factory to grow into a toolkit I can use across projects, from the first question through the pull request. I care about making changes a teammate can understand and maintain. Sometimes that means shipping a small fix. Sometimes it means finding the missing evidence, simplifying a design, or leaving code alone.

Today, Factory is an agent skill and a local CLI. The skill reads your request and chooses a workflow. It uses the repository’s own instructions and tools, and it carries your constraints through the work. The CLI runs checks, keeps results, and coordinates separate model sessions when a workflow calls for them.

## What you can ask for

| If you need to | Ask Factory to |
| --- | --- |
| Fix a bug or build a change | Confirm the behavior through a real entry point, make the change, and show what happens afterward. |
| Decide between designs or diagnose a hard problem | Have Codex and Claude Opus investigate independently, then compare the evidence behind their conclusions. |
| Simplify a branch | Give fresh Opus sessions the branch, its constraints, and the checks it must pass. |
| Upgrade a dependency | Find which version the project actually installs and check the code that uses it. |
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

> Use Software Factory to get a second diagnosis from Opus. Stay read-only and tell me what observation would settle the disagreement.

Independent review requires Codex. Simplification requires Claude Code. A two-model design or diagnosis requires both. Run `factory doctor --profile paired` to check their availability, or use the [local workflow](skills/software-factory/references/local.md) to run checks without them.

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

Factory saves run records outside your project in `~/.local/state/software-factory` by default. Set `FACTORY_STATE_DIR` to change the location. Use the same state directory for every Factory command on a worktree so the commands share its lock and know which run owns it. Records can include source code and command output.

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
