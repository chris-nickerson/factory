# Write a pull request description

Write for a teammate who knows the product but missed the conversation. What would they need to know to review this change today or understand the decision six months from now?

Read the request, the final diff against the intended base, the check results and any existing description. Follow the repository’s template and writing conventions. When updating a body, preserve human notes, checklists and sections owned by other tools. If the repo defines an editable block, draft its contents separately. To apply the edit, insert that text between the markers in a fresh copy of the current body. Verify that all bytes outside the block match the original, including trailing newlines.

**Lead with the consequence.** Name who encountered the problem and under what conditions. Say what happens now. Explain the reason for a design choice when the diff alone cannot show it. For internal work, name the developer or system that benefits. Put any required action or breaking change near the top. A small change can fit in one paragraph.

**Use ordinary engineering language.** Follow the [Factory writing guide](documentation.md#write-in-plain-technical-english). Replace “hardens the export path” with the behavior a reader could observe.

**Show how you know.** Give the most relevant observation and link to the evidence when available. Describe the result in product terms (“the exporter wrote five rows”). A test can pass, fail or check that result. Attribute supplied results to the test run. Say “I ran” only for checks you personally performed. Group checks that support the same claim. Say which material cases remain untested.

**Show the same case before and after.** If one sentence explains the cause, use it. When the reader would have to sketch what happened, choose the smallest illustration that explains the result. Hold the input and conditions fixed, use the same labels and units, and end with what a user or caller observes. Use aligned timelines for a deadline, a table for a decision, a short trace for a handoff, or sample input and output for an API contract.

In this fictional PR, the author ran the same export on both revisions:

> Large order exports stopped after the first page, so some orders were missing from the CSV. The exporter now requests each remaining page before it closes the file.
>
> The regression test used pages of two, two and one order. On the base revision the CSV contained only the first two orders. On the fix it contained all five and one header row.
>
> | Five orders on three pages | Pages read | Orders in the CSV |
> |---|---|---|
> | Before | 1 | 2 of 5 |
> | After | 1, 2, 3 | 5 of 5 |

Read the draft with the ticket closed. Can a reviewer explain the change, the reason and the evidence? Check factual claims against the final diff and evidence, especially claims about what always happens or cannot happen. Cut repeated facts, file inventories and the agent’s work diary. For a body-only request, return the Markdown exactly as it should appear on the PR, without a chat introduction, an enclosing code fence or a closing note.
