# Collaboration protocols

Factory uses two different forms of independence. In a design discussion, each participant studies the same evidence before seeing a peer's conclusion. During simplification, each new editor starts from the current branch with a fresh session. The saved transcript or Git tree connects the work across turns.

## Agreeing on a decision

`factory consensus design` asks Codex and Opus to compare alternatives and state what evidence would change their minds. In `diagnosis`, each must connect a proposed cause to the symptom or identify the missing observation. A confirmed diagnosis may explicitly be **inconclusive**.

The coordinator saves both opening reports, then alternates replies in the original sessions. A proposal has a numbered turn. To agree, a participant must acknowledge that specific turn. Codex closes the discussion after both participants endorse the same proposal. An exhausted exchange budget produces an unresolved result with the last turn available for inspection. Format repair and resumption use the saved sessions and receipts. [Dialogue implementation](../skills/software-factory/scripts/dialogue.py) · [Original protocol prompts](prompts/two-agent-collaboration.original.txt)

For example, if a deleted item still appears in a list, one participant might suspect a failed write and the other a stale client cache. A direct read of the stored item and a fresh list response can distinguish the explanations. Both participants can agree on that experiment while the cause remains unknown.

## Simplifying a branch

The coordinator pins the task, base, permitted paths, checks and selected number of rounds. Each editing session receives the exact versioned prompt as its first user message. Supporting requirements and the branch diff travel in a separate context channel. That separation makes it possible to inspect which prompt actually ran. [Canonical prompt](../skills/software-factory/references/reconsider-from-first-principles.v1.txt)

| Phase | Owner | Evidence handed to the next phase |
| --- | --- | --- |
| Edit | Fresh Opus session, Claude Code Auto with sandboxed local shell | Working-tree candidate and an explanation of the tradeoffs |
| Check | Factory | Checked Git tree, command arguments, exit codes and captured output |
| Assess or repair | Same Opus session | Read-only assessment of the actual check results, or a scoped repair followed by new checks |
| Checkpoint | Factory | Local commit matching the checked tree and, if requested, the observed remote branch head |

A round can keep the code as it stands. The selected number of rounds still runs, with a new session for each. A full delivery adds a fresh read-only GPT review of the whole change and a final verification on the accepted revision. [Simplification and recovery](../skills/software-factory/references/simplify.md) · [Full delivery](../skills/software-factory/references/delivery.md)
