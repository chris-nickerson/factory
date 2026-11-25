# Roles, harnesses and models

Factory hands three jobs to a separate model session: reviewing a change, simplifying a branch, and reaching consensus. Each job is a role. A harness is the agent CLI that runs the session, such as Codex or Claude Code. Factory decides which harness and model fill each role, tells you why, and lets you override the choice.

| Role | Job | What the harness must provide |
| --- | --- | --- |
| `reviewer` | Reviews the scoped diff in one fresh, read-only turn. | Read-only turns |
| `simplifier` | Edits the branch, runs local tests, then assesses the check results. | Editing, a sandboxed shell, read-only turns and session resume |
| `consensus-a`, `consensus-b` | Investigate independently, then answer each other. A opens the exchange. | Read-only turns and session resume |

## See what fills each role

Run `factory roles` from the project. `factory doctor` prints the same report beside its other checks.

```sh
factory roles --repo .
```

The report shows:

- `host`: the harness whose session is running Factory, and the evidence for it.
- `harnesses`: each supported CLI, whether it is installed and signed in, and what it can do.
- `roles`: for each role, the harness, the model argument Factory will pass, where the choice came from, and any reduced assurance. `SIGNED_OUT` means the chosen harness needs a login before the role can run.

A login check cannot prove model access. The first live turn does.

## Override a role for one run

Pass a role spec to the command that uses the role.

```sh
factory review RUN_ID --reviewer claude
factory simplify --simplifier claude:frontier --base trunk --task '...' --check '...'
factory consensus design --a claude --b codex:frontier --task '...'
```

A spec has three forms:

| Spec | Meaning |
| --- | --- |
| `HARNESS` | Use this harness. A lower-priority setting still supplies the model when it names a tier or was written for the same harness. Otherwise the role's default tier applies. |
| `HARNESS:MODEL` | Use this harness and this model. |
| `:MODEL` | Keep the harness Factory resolved and change only the model. |

`MODEL` is a tier, `default`, a model family, or a complete model name. When the user names a harness or model for a job, pass it with the role's flag.

## Choose a model tier

A tier names how capable a model the role needs, so the same request works on any harness.

| Tier | Use it for | Default for |
| --- | --- | --- |
| `frontier` | The most capable family. One turn carries the whole judgment. | `reviewer` |
| `standard` | A cheaper family for work that repeats across turns and rounds. | `simplifier`, `consensus-a`, `consensus-b` |
| `default` | Whatever model the harness itself would choose. Factory passes no model. | |

Choose the tier for each run from the task, the way you choose a round count. Pass `--tier frontier` to raise every role the command fills, or put a tier in one role's spec.

| The task | Tier |
| --- | --- |
| A design that spans several components, is hard to reverse, or has no clear precedent in the codebase | `frontier` for consensus |
| A diagnosis with competing explanations or thin evidence | `frontier` for consensus |
| A change to access control, stored data, concurrency or a compatibility contract | `frontier` for simplification |
| A localized change, a routine decision between known options, or a question the evidence nearly settles | The role default |
| A low-risk change where the user asks for a cheaper review | `standard` for the reviewer |

Diff size alone is a poor reason to raise a tier. A run keeps its model until it finishes, so choose before you start it.

```sh
factory consensus design --tier frontier --task '...'
factory simplify --tier frontier --rounds 3 --base trunk --task '...' --check '...'
factory review RUN_ID --tier standard
```

The [built-in policy](../scripts/defaults.toml) maps each tier to a model family for each harness. Factory's code names no model. Claude Code accepts a family name directly. Codex accepts only complete model names, so Factory asks `codex debug models` which listed model currently carries the family. If the catalog is unavailable, a default role uses Codex's own default model and reports the reduction. A tier you asked for by name fails with the choice to make: set the role to `codex:default`, or name a model yourself, which Factory passes to Codex as written.

## Set your own defaults

Put role specs in `~/.config/software-factory/config.toml`, or under `XDG_CONFIG_HOME` when it is set. Use `[models.HARNESS]` to change the family behind a tier.

```toml
[roles]
reviewer = "codex"
simplifier = "claude:frontier"

[models.claude]
standard = "sonnet"
```

A project can declare the same tables in its `software-factory.toml`. The project file may be part of the change under review, so Factory ignores its role settings until you approve them. Read the settings, then run `factory roles --repo . --approve`. A later edit to those tables needs a new approval.

Factory resolves each role in this order and reports which source decided:

1. The flag for this run.
2. The approved project configuration.
3. Your user configuration.
4. The default for this machine.

## How Factory chooses a default

Factory considers the harnesses that are installed, signed in and able to do the role's job.

- **Simplifier.** Claude Code when it is available, otherwise Codex.
- **Reviewer.** A harness from a different vendor than whoever last changed the code. After a completed simplification run that changed the branch, that writer is the simplifier. Otherwise Factory treats the hosting session as the probable author. With no writer signal, Factory prefers Codex.
- **Consensus.** Codex for A and Claude Code for B when both are available, so the participants come from different vendors.

On a machine with both harnesses, a branch simplified by Claude Code is reviewed by Codex. A review started from a Codex session with no simplification is reviewed by Claude Code.

Factory finds the host from the nearest agent process above it, then from environment variables the host sets. A session started inside another agent's terminal inherits the outer agent's variables, which is why the process decides first. Set `FACTORY_HOST` to a harness name or `none` when the detection is wrong.

## Reduced assurance

With one harness, Factory still fills every role. It states what the result is worth less for:

| Statement | What it means |
| --- | --- |
| The reviewer shares a vendor with the writer | The review comes from a fresh session of a related model. It is less independent than a review from another vendor. |
| The reviewer's independence is unverified | Only one vendor's harness is available, and Factory could not tell who wrote the change. |
| Same-model consensus | Both participants use one harness and model. Agreement shows consistency between two sessions. |
| Same-harness consensus, model diversity unverified | Both participants use one harness that does not report its model. |
| Both consensus participants come from one vendor | The participants use different models from the same vendor. |
| The role uses the harness default model | The harness could not list its models, so Factory could not resolve the role's default tier. |

A reduction appears in the `reductions` field of the role report, in a review's `review_reductions` and receipt, and in a consensus result. A reduced review still satisfies `--require-review`. Report each reduction to the user with the result. If the user requires an independent vendor, install and sign in to a second harness, then rerun the step.

## What each harness provides

| | Codex | Claude Code |
| --- | --- | --- |
| Read-only turn | Read-only sandbox with a shell | File-reading tools, no shell |
| Editing turn | Workspace-write sandbox. The shell cannot reach the network or write Git metadata. Temporary files go to a private directory for that turn. | File tools and a sandboxed shell. Factory denies writes to `.git`, `git commit` and `git push`. |
| Session resume | Yes | Yes |
| Reports its model | No | Yes |

A reviewer without a shell cannot run Git, so Factory puts the complete diffs in its prompt. If the diffs are too large to deliver that way, the review is `BLOCKED` with the reason.

Each turn's receipt records the model Factory requested as `model_requested`, the tier or family it came from as `model_selector`, and what the harness reported as `model_reported`. `model_identity` is `matched`, `indeterminate` when the report cannot settle it, `unrequested` when Factory passed no model, or `unreported` when the harness named none. A report is indeterminate when it lists several models or leaves out a revision the request pinned. A turn fails if the harness reports a different model than the one requested.

## Saved runs

A run saves its role bindings when it starts. `resume` and `status` reuse the saved harness and model, whatever the configuration says now. Runs saved before roles existed keep their original assignment: Claude Code with `opus` for simplification, and Codex for A with Claude Code for B in consensus.
