# Write and maintain documentation

Documentation earns its place when it changes what a reader does next. It holds what the code cannot say: the purpose, the main concepts, how the parts fit, and why a decision went one way. Everything else already has a better home, and a second copy drifts away from it.

Agents tend to fail here in predictable ways. Writing is cheap for an agent and reading is expensive for a person, so drafts grow until nobody reads them in full. Agents record what they just did: counts, timings, flags, dates and file lists, which are the facts most likely to go stale. They append a sentence for each change and rarely remove one, so a document turns into a changelog. They edit sentences without rereading the document, so every line can be true while the framing is wrong. Each habit below counters one of these.

## Give each document one reader and one job

Name the reader before you write. The README serves a person deciding whether to use the project and how to start. `SKILL.md`, `AGENTS.md`, `CLAUDE.md` and their references serve agents. Do not write one document for both.

Pick one mode per document and keep to it:

- A **tutorial** walks a newcomer to a first working result. Show the output each step should produce.
- A **how-to** gets a competent reader through one task. Name it by the task and skip the background.
- A **reference** lists facts for lookup: commands, options, formats, errors. Generate it from the code when you can. Otherwise link to `--help` or the source.
- An **explanation** covers why a design has its shape, the constraints and the alternatives considered. It describes stable structure, not the current file list.

Split a document that mixes modes and link the parts. Write sentences the way the [PR writing guide](pr-descriptions.md) describes under “Use ordinary engineering language.”

## Keep facts where they stay true

Before you add a fact, ask how quickly it will change and where it already lives.

- **Stable facts** belong in documentation: the purpose, the concepts, the decisions and the guarantees callers rely on.
- **Facts that change with the code**, such as flags, defaults, file names and schemas, live in the code, its `--help` output and its tests. Link to them. Repeat one only where a reader needs it in context, and only if it is exact on the commit that lands it.
- **Facts about a moment**, such as test results, timings, pilot findings and the reasons for a particular change, belong in the commit message and the PR description. They are dated by nature, and no one has to keep them current. Do not commit status reports, dated qualification write-ups or work diaries to the repository.

Keep one source for each fact. Wherever a reader needs a fact that lives elsewhere, link to it.

## Record decisions where the next reader will look

| What needs recording | Where it goes |
| --- | --- |
| Why this line or this check exists | A comment next to the code, only when the reason is not obvious. State the constraint, not the history. |
| Why a change was made, what was tried and how it was verified | The commit message and PR description. `git log`, `git blame` and the PR recover them later. |
| A mistake that will recur | A test, check or script that fails when it recurs. Add prose to a skill only when the fix needs judgment, and include an example of the failure. |
| The trail of a long or unattended run | Factory's run records, outside the checkout. Commit a decision log only when a reviewer needs it to trust the result. |
| The stable shape of the system | The explanation document. Update it in the same change that alters the design. |

Do not keep decision folders, notes files or changelogs of agent work in the repository. They become a second history that disagrees with Git.

## Change documentation with the code

Every change that alters behavior includes the documentation it makes false. Search for the old command, flag, term or behavior in the README, `docs/`, the skill and its references. Fix or delete each hit in the same change.

After editing, reread the whole document, not just the changed lines. Check that the opening still describes the project as it is now. Prefer replacing a sentence to adding one. Deleting a section that no longer helps anyone is a normal edit. A shorter document that stays true is worth more than a complete one that does not.

Make claims checkable. A command in a document should run as written. A count or list should be exact on the commit that lands it, or link to the command that produces it. Relative links must resolve. Use the repository's tests to catch what you can.

## Document code at its boundaries

Names and structure say what code does. A comment explains what they cannot: a hidden constraint, an invariant, a workaround and the cause it works around, or a surprising result. Delete comments that narrate the code, describe the change, or mention a ticket or conversation.

Give each module a short statement of its purpose. At a public boundary, state the contract: inputs, outputs, errors and side effects. Leave the implementation to the code. A tested example is better than a paragraph about how to call something.
