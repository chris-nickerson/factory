# Replay a caller before and after a change

For a refactor, identify what an existing caller can observe. Capture representative inputs from the supported versions, including a previously rejected input when rejection is part of the contract. Keep one checkout at the accepted revision. Make the structural change in a second checkout. Migrate internal callers together and retain published interfaces that external callers still use.

When the operation has a deterministic result, prepare one driver that invokes the public entry point in its working directory. Have it exit successfully only when the operation finishes, check expected side effects or errors, and write the observable result to stdout. Use identical inputs, dependencies and configuration. Keep the driver and read-only fixtures outside both checkouts. Reset mutable state between calls if the operation writes data. The command you supply executes in both directories with your account's permissions.

For example, to compare the usage text customers see after reorganizing Factory's CLI registration, run this from a directory containing two Factory checkouts.

```sh
factory compare --before original --after refactored -- ./factory --help
```

A `MATCH` means every process exited successfully and produced the same stdout bytes. The JSON report includes each sample's size and digest. Different output or a nonzero command exit stops the comparison with exit 1. If Factory cannot launch the command in one checkout, it reports that checkout and exits 2. Both reports retain completed samples. Inspect the first difference through the same caller. A legitimately different result needs a decision about the public contract. For interactive programs, images, services or expected failures, have the driver exercise the relevant boundary and check the result it records. Empty stdout can match even when the work is wrong.

For a performance comparison, pass `--trials 6` before `--` to repeat six pairs, alternating the first checkout. The report includes individual wall times and each side's minimum, median and maximum in milliseconds. The interval includes process startup and ends at process exit. Choose a workload that waits for the user-visible result and includes the same completed work on both sides. Repeated runs can warm caches or change external state. Match those conditions and inspect the samples before attributing a change to the implementation. For a live service or an existing project benchmark, follow the [diagnostics procedure](diagnostics.md) to measure at the relevant boundary.

Run the project's other contract checks before handing off the refactor. Name the caller that benefited from the simpler structure and any contract the replay did not exercise.
