# Coordinate a multi-stage change

Use a plan when part of a project can proceed independently and another part needs a specific result first. For example, an exporter migration can start by capturing files from the released exporter while another engineer updates the reader. Switching the writer needs evidence from both. A one-branch fix with several checks fits a single [local contract](local.md).

## Describe the work

Give each item a unique ID and a task that names an observable result. List its immediate prerequisites in `needs`. Save the JSON file outside every checkout the plan will inspect. Editing a tracked or unignored plan inside a checkout can invalidate its evidence.

```json
[
  {"id": "corpus", "task": "Capture representative exports produced by the released CLI"},
  {"id": "reader", "task": "Make the reader accept both supported file formats"},
  {"id": "writer", "needs": ["corpus", "reader"], "task": "Switch the writer and round-trip old and new exports through the updated reader"}
]
```

From the directory containing the saved file, run `factory plan migration.json`. The first report lists `corpus` and `reader` in `next`. The writer is `WAITING`. For a planning request, hand back the file, the proposed evidence for each stage and the decisions still open.

## Carry an item through verification

1. Pick an eligible item and give one owner its task, worktree, acceptance checks and authorized stopping point. When running items concurrently, give each writer a separate worktree. The coordinator owns edits to the plan. Inspecting it neither assigns an owner nor starts work.
2. Start a [local evidence run](local.md) in that worktree. Pass the item's exact `task` text to `factory start --task`. Add the returned ID to the item's `run` field and retain that worktree for later status checks. For an item with prerequisites, also save an `inputs` object. Use each immediate prerequisite's ID as a key and copy its verified `subject` from the current plan report as the value. For the writer, record both `corpus` and `reader`. Each item gets its own run.
3. Exercise the surface the next stage depends on. For the corpus, record the release and exercise its actual exporter. For the reader, open a file of each supported format. If the unknown is a live stall, capture a trace during the stall and compare it with a healthy run. If two implementations could work, isolate the decision in a small prototype and measure the difference. Carry the observation into the next owner's brief.
4. Inspect the plan after each result. `READY` identifies unstarted work whose prerequisites have verified. For an eligible item marked `ATTENTION`, use its `reason` when present. When it reports an evidence status, run `factory status RUN_ID` to find the check or review that needs attention. A satisfied item is `VERIFIED`. Use the `complete` boolean to test whether the whole plan has verified. A valid inspection can exit successfully while work is pending.

## Resume and check the combined result

Give the next coordinator the manifest path, the state directory used by the runs, the item owners, and each branch or PR. Reinspect the plan and compare each eligible item with work already in flight before assigning it. A change to an upstream checkout can make its evidence stale and put dependent items back into `WAITING`. Unrelated branches can still proceed.

A dependency records the required order of evidence. The integration owner still has to bring the verified inputs together. If the reader changes after the writer passed in a separate checkout, first verify the reader again. Once the prerequisites verify, the writer shows `ATTENTION` because its recorded reader subject is outdated. Integrate the new reader into the writer checkout, start a fresh writer run, and update its `run` and `inputs` together. Repeat the round trip against the new reader. Refresh evidence for any external inputs the workspace fingerprint cannot see. Before handing off a PR, confirm its head and [delivery checks](delivery.md) at the forge. Stop at the endpoint the user requested.
