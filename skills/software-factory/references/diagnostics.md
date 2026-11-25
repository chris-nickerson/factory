# Investigate a symptom or performance regression

Start with the operation the user experienced, the affected build, and the question the evidence must answer. For a question about how code works, follow one concrete input from its public entry point to the observed result. For a question about why a decision was made, check the introducing change and its recorded rationale. Identify any motive you could only infer.

## Analyze a supplied capture

Preserve the original. Identify its format, build, time window, workload, process and thread from the available metadata. Use the format's reader to extract a small table or call tree for the affected interval. Keep the query or command with its output so someone can repeat the analysis.

For a sampled CPU profile, rank leaf frames by self time and walk from the busiest leaf to its callers. Use sample durations when the format provides them. An inclusive parent can account for an entire request while doing little work itself. For a hang, inspect the blocked thread and the owner of the resource it awaits. For heap growth, follow a retained object to its root and compare survivors across equivalent collection points. For frame drops, align the missed frame with work on the rendering path.

Map the implicated frame to a symbol and source location in the captured build. Include the supporting interval, count or duration, its denominator, and the artifact location. If there is a healthy capture, align the two by operation and compare the same measure. A hot frame in one capture establishes where time went in that recording. To attribute a regression, identify what evidence distinguishes the proposed cause from a competing explanation. When the capture lacks symbols, an affected interval or a suitable comparison, report the strongest supported conclusion and the specific missing observation.

## Diagnose a live symptom

Reproduce the reported operation on the affected surface. Record a short observation while the symptom is present and capture a comparable healthy or idle interval when possible. Choose the instrument for the symptom. CPU samples show on-CPU work. Request spans and thread states can explain elapsed time spent waiting. Check whether instrumentation changes the symptom.

Reduce the capture as above. Test the suspected mechanism with a reversible probe within the user's scope. For example, count callbacks while an idle window spins, then exercise the same window with its timer suspended in a disposable run. If suspending the timer stops the callbacks but leaves CPU use unchanged, investigate the remaining hot frames. Restore the instrumented state. For a diagnosis-only request, hand back the observation, the implicated source, the competing explanation you tested and any remaining uncertainty.

## Fix a measured performance issue

When the request includes a fix, define the user-visible metric and workload in a [local contract](local.md#choose-the-baseline). Record output correctness, completed work, errors and retries. Capture the baseline before editing. Profile a separate run to locate the limiting operation. First consider whether the caller needs that work and how often it repeats. Check the critical path before moving work later or running it concurrently.

Change one cause and replay the workload on the original and candidate builds. Keep input, build mode, warmup, cache state and concurrency comparable. For commands whose output must stay identical, use [paired command comparisons](comparisons.md) to replay both checkouts. Alternate repeated uninstrumented runs and report the median, spread and units for each build. Confirm the consumer received equivalent results and all claimed work completed inside the measured interval. Take a second profile to check whether the predicted bottleneck moved. If observed variation obscures the difference, report it as inconclusive. Use [hill-climbing](hill-climbing.md) for a requested series of experiments and [delivery](delivery.md) when the user asks to publish the fix.
