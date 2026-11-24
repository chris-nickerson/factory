# Software Factory

Factory is a local CLI and agent skill for verifying software changes. It answers a question that matters after an agent says it fixed something: **which behavior passed, on which version of the code?**

A run starts with an observable expectation and a command that can disprove it. Factory captures the command's output and fingerprints the checkout. If someone edits the code after the check, the next status report marks the evidence stale. Local checks use Python's standard library and Git. Independent reviews and paired workflows also use the Codex and Claude Code CLIs.

## Try it from a checkout

On macOS or Linux with Git and Python 3.11 or later, run:

```sh
./factory doctor
./factory inspect --repo .
```

The second command finds this repository's test command and the file that declares it. To see how a verification result ages, run the following from the same checkout. The example works offline, without installation or model credentials.

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

`status` identifies the source change without rerunning the command. The final `check` makes a new observation. Each result includes the path to its local evidence. [Contract format and exit codes](skills/software-factory/references/local.md)

## Use it with an agent

```sh
python3 install.py
export PATH="$HOME/.local/bin:$PATH"
factory doctor
```

The defaults are `~/.local/bin/factory` and `~/.agents/skills/software-factory`. To use the command in later shells, keep `~/.local/bin` on your PATH. Open your target checkout in a fresh agent session. Try **“Use Software Factory to reproduce this bug, fix it, and verify it through the public entry point.”** A shell-capable agent can also read the skill directly. For Claude Code project skills, install with a separate `--prefix` and `--skill-dir /path/to/project/.claude/skills`. [Agent entry point](skills/software-factory/SKILL.md)

| Task | Entry point | Evidence |
| --- | --- | --- |
| Check a change | `start`, `check`, `status` | Frozen contract, command output and source fingerprint for each claim. |
| Upgrade a dependency or clear a scanner alert | [Dependency updates](skills/software-factory/references/dependencies.md) | Resolved versions in each affected install root, a working consumer, and the scanner result on the updated revision when applicable. |
| Request independent review | `start --require-review --base REF`, then `review` | A fresh, read-only Codex review of the selected change. |
| Resolve a design or diagnosis | `consensus design` or `consensus diagnosis` | Independent GPT and Opus openings, numbered replies and acknowledgment of a specific proposal. [Protocol](skills/software-factory/references/consensus.md) |
| Simplify a branch | `simplify --base REF --rounds N --task TEXT --check COMMAND` | One to three fresh Opus sessions. Factory checks each candidate before committing. Use `--push REMOTE` for per-round publication. [Procedure](skills/software-factory/references/simplify.md) |
| Record a later correction | `outcome RUN_ID --note TEXT` | An observation attached to the checked revision. [Using feedback](skills/software-factory/references/local.md#later-outcomes) |

Use `factory doctor --profile paired` to check the provider CLIs and their reported login state. Provider turns run until completion, provider failure or cancellation. Verification commands and Git operations have separate time limits. Cross-model runs send task context to the selected providers.

## Run the tests

```sh
python3 -B -m unittest discover -s tests -v
```

The offline suite uses real Git repositories, bare remotes and subprocesses. Provider fixtures make interruptions and conflicting responses reproducible. Live evaluations exercise actual provider sessions and grade the resulting behavior outside the edited checkout. [Qualification results and limits](docs/qualification.md)

For a source tour, start with the lifecycle of one check, then follow a simplification checkpoint through interruption and recovery. [Architecture](docs/architecture.md) · [Collaboration protocols](docs/collaboration.md) · [Design influences](docs/source-inventory.md)

## Storage and upgrades

Factory keeps run state outside the project under `$FACTORY_STATE_DIR` or `$XDG_STATE_HOME/software-factory`, defaulting to `~/.local/state/software-factory`. Logs can contain source and command output.

To switch an existing installation to the latest version on its recorded origin's `main`, run:

```sh
factory update
```

Factory fetches into a temporary checkout and switches the executable and skill together through a single release link. Custom install locations are preserved. Archive installs default to the personal Factory GitHub repository. For an older release without the update command, run `python3 install.py` from an updated checkout once. The installer also accepts `--dry-run`, `--rollback` and `--remove`. Use the installation's original prefix.
