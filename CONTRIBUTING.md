# Contribute to Software Factory

Start with the [offline demo](README.md#see-evidence-go-stale) and [architecture walkthrough](docs/architecture.md). Run the offline tests from the checkout with `python3 -B -m unittest discover -s tests -v`.

- For a procedure that uses existing commands, start in the [skill's routing table](skills/software-factory/SKILL.md) and its linked references. Check a neighboring request that should follow a different route.
- For a new command or a change to a gate, follow the registration in [the CLI](skills/software-factory/scripts/factory) to its workflow. Exercise the command as its caller uses it, including the failure or exit code the caller relies on.
- For changes to installation or persisted state, test a previously installed layout or a record from an older writer. Exercise the relevant status, resume, release, or rollback command.

Describe the observed behavior and the case that would fail without the change in the pull request. Include the repository checks and any live qualification needed for a change to model behavior or host integration. Keep generated receipts and credentials out of the pull request. A code owner reviews changes before merge.

Run `python3 -B evals/qualify_upgrade.py /path/to/older/factory` to exercise the older installer and CLI in a disposable home. Run `python3 -B evals/qualify_routing.py /path/to/new/results` with an authenticated Codex CLI to sample procedure selection from a clean project. The routing eval runs live model calls and records their decisions without running the selected procedures.
