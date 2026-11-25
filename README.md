# Software Factory

Software Factory helps your coding agent verify engineering work. The skill tells the agent how to handle your request. The `factory` CLI saves the checks before the agent edits, then records what happens when it runs them. Each result is tied to a workspace fingerprint, a digest of the source state Factory checked.

## What you can ask for

- **Fix a bug or build a change.** The agent records what should happen before it edits. It checks the original code and reruns the same check on the final code.
- **Get a second opinion.** Codex and Claude Opus investigate a design or diagnosis independently, then compare proposals. They can agree, identify missing evidence, or reach the discussion limit without agreement.
- **Simplify a branch.** One to three fresh Opus sessions reconsider the change. Factory checks each round and commits a changed tree only after it passes.
- **Upgrade a dependency or clear a scanner alert.** The agent traces the resolved package and checks the code that actually uses it.
- **Prepare a pull request.** The agent writes the description, monitors CI and review feedback, and fixes confirmed problems within the request.
- **Update documentation.** The agent checks instructions against the current project and updates or removes stale information.

Factory uses the target repository's instructions and checks. Its records rely on the local account, which controls the checks, tools and saved results.

## Install

You need macOS or Linux, Git and Python 3.11 or later.

```sh
git clone https://github.com/chris-nickerson/factory.git
cd factory
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
factory doctor
```

This installs `factory` in `~/.local/bin` and the skill in `~/.agents/skills/software-factory`. The default skill directory contains the full instructions in a regular `SKILL.md` so agents that skip directory symlinks can discover and read them. Add `~/.local/bin` to your `PATH` in your shell profile so later shells find it.

Run `factory doctor --profile paired` to check the Codex and Claude Code CLIs. If they are unavailable, use the [local evidence workflow](skills/software-factory/references/local.md).

Open a repository in a new agent session and try:

> Use Software Factory to reproduce this bug, fix it, and verify it through the public entry point.

## See evidence go stale

Run this example offline from the Factory checkout. You need Git and Python, and you can use the checkout's `./factory` directly. The example creates a temporary project, checks its file, then edits the file so you can see what happens to the earlier result.

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

After you edit `answer.txt`, `./factory status "$run"` reports the earlier check result as `STALE` without rerunning the check. Run `./factory check "$run"` to check the current file. In this example, the new check fails because the file now says `pending`.

## Update

```sh
factory update
```

Factory installs the latest `main` from the repository you installed from. It lists the incoming commits when it knows the previous source commit and the fetched history covers the range. Pass `--json` for a machine-readable report. To go back, run `python3 install.py --rollback` from an up-to-date checkout with the original install prefix.

Wait for an update or rollback to finish before you open a new agent session. During the switch, the CLI and skill files can come from different releases. If the command stops partway through, rerun the same command to finish the switch.

If the default skill directory is still a symlink or its entry still points readers to `release/SKILL.md` after updating, run `factory update` again so the new CLI can migrate it. You can also run `python3 install.py` once from an updated checkout. For a legacy install with a custom prefix, migrate from the original home directory so Factory can identify the default skill path. Rolling back to a release that predates this layout restores the symlink.

Keep the installed skill path out of Git's index. If the index still tracks an older symlink at that path, remove the index entry before verifying changes in that checkout.

Factory saves run records outside your project, in `~/.local/state/software-factory` by default. To choose a different directory, set `FACTORY_STATE_DIR`. Use the same directory for every Factory command on a worktree so the commands share the workspace lock and can tell which run owns the worktree. Records can include source code and command output.

## Learn more

- [How Factory works](docs/architecture.md) follows one check, one model debate and one simplification round through the code.
- [The skill](skills/software-factory/SKILL.md) is what agents read. It maps each kind of request to a procedure.
- `factory --help` lists every command and option.

## Work on Factory

```sh
python3 -B -m unittest discover -s tests -v
```

The tests use real Git repositories, bare remotes and subprocesses. They run offline. The scripts in `evals/` exercise live model sessions or a browser with checks outside the edited checkout. See the [contributor guide](CONTRIBUTING.md) for where to make changes and how to verify them.

## License

Software Factory is available under the [MIT License](LICENSE). See the [security policy](SECURITY.md) to report a vulnerability privately.
