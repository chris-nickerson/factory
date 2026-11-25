# Software Factory

Factory is an agent skill and a local command-line tool for engineering work you can check. You ask your coding agent for something in plain language. The skill picks a procedure, and the `factory` command records evidence the agent cannot fake: which behavior passed, on which version of the code.

## What you can ask for

- **Fix a bug or build a change.** The agent writes down the expected behavior before it edits, reproduces the failure, then shows the same check passing on the final code. If the code changes after a check, the evidence goes stale.
- **Get a second opinion.** GPT and Claude Opus work through a design or a diagnosis independently, then argue until they agree on one proposal or agree that the evidence is missing.
- **Simplify a branch.** One to three fresh Opus sessions reconsider the change from first principles. Factory checks and commits each round.
- **Upgrade a dependency or clear a scanner alert.** The agent traces the resolved package and checks the code that actually uses it.
- **Ship a pull request.** The agent writes the description, watches CI and reviews, and fixes what is real.
- **Keep documentation honest.** The agent removes what has gone stale and documents only what stays true.

Factory is not tied to one kind of project. It reads each repository's own instructions and test commands instead of bringing its own.

## Install

You need macOS or Linux, Git and Python 3.11 or later.

```sh
git clone https://github.com/chris-nickerson/factory.git
cd factory
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
factory doctor
```

This installs `factory` in `~/.local/bin` and the skill in `~/.agents/skills/software-factory`. The default skill directory contains a regular `SKILL.md` so agents that skip directory symlinks can discover it. The skill and CLI follow the same active release. Add `~/.local/bin` to your `PATH` in your shell profile so later shells find it.

Run `factory doctor --profile paired` to check the Codex and Claude Code CLIs. If they are unavailable, use the [local evidence workflow](skills/software-factory/references/local.md).

Open a repository in a new agent session and try:

> Use Software Factory to reproduce this bug, fix it, and verify it through the public entry point.

## See evidence go stale

This example runs offline from a checkout, without installing anything or signing in to a model. It checks one claim, changes the code under it, then asks Factory what it knows.

```sh
demo=$(mktemp -d)
mkdir "$demo/project"
printf 'ready\n' > "$demo/project/answer.txt"
cat > "$demo/contract.json" <<'JSON'
[{"id":"ready","expect":"answer.txt contains the line ready","argv":["grep","-Fx","ready","answer.txt"]}]
JSON

run=$(./factory start --repo "$demo/project" --task "Verify readiness" \
  --contract "$demo/contract.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["run"])')
./factory check "$run"                  # VERIFIED
printf 'pending\n' > "$demo/project/answer.txt"
./factory status "$run"                 # INCOMPLETE, claim STALE (exit 2)
./factory check "$run"                  # FAILED, claim FAIL (exit 1)
```

`status` notices the edit without rerunning the check. The second `check` makes a new observation, and this time it fails.

## Update

```sh
factory update
```

Factory installs the latest `main` from the repository you installed from and lists the commits it brought in. Pass `--json` for a machine-readable report. To go back, run `python3 install.py --rollback` from your checkout with the original install prefix.

If the default skill directory is still a symlink after updating, run `factory update` again so the new CLI can migrate it. You can also run `python3 install.py` once from an updated checkout. For a legacy install with a custom prefix, migrate from the original home directory so Factory can identify the default skill path. Rolling back to a release that predates this layout restores the symlink.

Keep the installed skill path out of Git's index. If the index tracks an older skill symlink, remove that entry before verifying changes in the checkout.

Factory keeps run records outside your project, in `~/.local/state/software-factory` by default. Set `FACTORY_STATE_DIR` to move them. The records can include source code and command output.

## Learn more

- [How Factory works](docs/architecture.md) follows one check, one model debate and one simplification round through the code.
- [The skill](skills/software-factory/SKILL.md) is what agents read. It maps each kind of request to a procedure.
- `factory --help` lists every command and option.

## Work on Factory

```sh
python3 -B -m unittest discover -s tests -v
```

The tests use real Git repositories, bare remotes and subprocesses. They run offline. The scripts in `evals/` run live sessions against real models and grade the result outside the edited checkout.
