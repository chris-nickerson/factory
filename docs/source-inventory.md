# Design influences

Factory grew out of individual skills for triage, code review, simplification and delivery. A repository can already know how to launch its application, exercise a particular surface and publish a change. Moving that knowledge into every agent prompt would create a second copy for maintainers to keep current. Factory keeps those commands with the project and shares the procedures that transfer across projects.

| Source workflow | Decision carried into Factory |
| --- | --- |
| Bug triage and verification | Reproduce a failure through a consumer entry point. Freeze the expectation before editing, then replay it after the change. |
| Independent review | Bind findings to a specific candidate, account for both staged and unstaged changes, and invalidate the verdict when its subject moves. |
| Ticket delivery | Give each phase an owner and a stopping point. Investigation can end with an inconclusive diagnosis. Publication requires selecting a destination. |
| First-principles simplification | Keep the prompt as a versioned asset. A fresh editor inherits the branch and requirements. Each round is checked independently. [Canonical prompt](../skills/software-factory/references/reconsider-from-first-principles.v1.txt) |
| Repository-specific launch and verification skills | Discover nested instructions and local tools. A test of a library, a browser interaction and a remote deployment each need a different observation. |

Poteto's pstack also informed the design. Its task routing keeps detailed playbooks out of the initial context. Its bug-fix and evaluation procedures emphasize reproducing behavior and comparing approaches on the same case. The links below pin the material considered during design. [Poteto Mode](https://github.com/cursor/plugins/blob/9d76bcab133aefcccb16121d7be874e6aa823729/pstack/skills/poteto-mode/SKILL.md) · [Bug-fix playbook](https://github.com/cursor/plugins/blob/9d76bcab133aefcccb16121d7be874e6aa823729/pstack/skills/poteto-mode/playbooks/bug-fix.md) · [Evaluation playbook](https://github.com/cursor/plugins/blob/9d76bcab133aefcccb16121d7be874e6aa823729/pstack/skills/poteto-mode/playbooks/eval.md)
