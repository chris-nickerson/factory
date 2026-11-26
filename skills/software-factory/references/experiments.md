# Resolve a design choice with a prototype

Name the decision and the observation that would change it. Use the caller's constraints to choose representative inputs and the smallest working variants that could give different answers. For a keyboard interaction, drive the keystrokes and observe focus. For a latency question, time the operation the user waits for. A preference that remains after both variants work belongs to the caller unless they delegated the choice.

Build the variants in a disposable directory or separate worktree. Give them the same data and exercise the real boundary in question. For a visual decision, make the variants easy to switch between, capture the relevant states and try the interaction. For a behavioral decision, replay the same input and save each outcome. Record any substitute for a real service and the conclusion that substitute permits.

Return the decision, the observed tradeoff, the scratch artifact and how to repeat the experiment. If both variants behave alike, name the remaining discriminator. A decision-only request ends here. For an authorized implementation, carry the winning behavior into a [local contract](local.md) and build it in the target project.

## Verify or restore visual parity

1. Identify the reference implementation or approved captures, the candidate, and the states and surfaces that must match. Capture the reference before editing. Match the renderer, viewport, device scale, fonts, theme, data and interaction sequence. Wait for assets and the intended state. Repeat a reference capture if the surface moves between runs.
2. Preserve the reference and capture settings outside the candidate's edits. Use the project's visual test runner or drive both builds with the same browser or device. Compare decoded pixels at their original dimensions. For exact parity, a dimension mismatch or any changed pixel fails. Apply an existing tolerance or mask only within its agreed scope. If the reference is unavailable or unstable, identify the affected states and the evidence needed to compare them.
3. Keep a result per state with the dimensions, changed pixels or the project's difference metric, and paths to the reference, candidate and difference image. Inspect where the difference appears. A focus-ring regression can be invisible on the initial screen and obvious after tabbing to the control.
4. For an audit, report the mismatches and stop. For an authorized migration or repair, address the source of the difference one component at a time and rerun every affected state against the original reference. Use the same comparison as a [Factory check](local.md) when delivering the change. Report exactly which states matched and which remain open.
