# Choosing evidence for a data-system change

Start with one promise a caller relies on. Who can write the data? Which copy does the caller read? At what point has the system acknowledged success? Trace one operation across those boundaries. Choose the failure history that could break the promise and put its observable result in the Factory contract. Use a barrier, a controlled failure or a saved input to reproduce the history. A randomly timed sleep makes a poor witness.

## When the caller loses the answer

A timeout leaves the outcome unknown. Let a purchase worker issue a credit, let the ledger commit it, then lose the reply before the worker saves its offset. Restart the worker and redeliver the purchase. Count credits in the ledger and check the amount and beneficiary. Then submit a distinct purchase for the same amount. Both purchases should count. A broker's delivery guarantee stops at the external ledger.

Find where the receiver remembers operation identity, whether it records that identity atomically with the effect, and how long it remembers. Compare that lifetime with the longest supported replay. If the receiver offers neither deduplication nor authoritative reconciliation, surface that limit before promising one effect per purchase. [Making retries safe with idempotent APIs](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)

## When two writers can each make a valid decision

State the invariant across records. Suppose at least one responder must remain on call. Have two transactions each read both responders on duty, synchronize after both reads, then each take a different responder off duty. Inspect committed state through a fresh reader. Each row update can succeed without a lost update while the pair violates the rule. Exercise the deployed isolation level and any whole-transaction retry path.

A lease introduces a different history. Pause writer A after it acquires the lease, let B acquire the expired lease and write, then resume A. If correctness depends on exclusive ownership, observe the resource rejecting A's stale write. Checking expiry in A still leaves a pause between that check and the write. A monotonic fencing token enforced by the destination is one way to close the gap. [How to do distributed locking](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)

## When readers can see different histories

Ask which observer needs which order. After an acknowledged profile edit, route that user to a lagging replica. If the product promises read-your-writes, the new value must be visible there or the read must wait or route elsewhere. For monotonic reads, first show the new value, then switch replicas and check that the old value never reappears in that session. Test failover separately if acknowledged writes must survive leader loss. Record what may be unavailable during a partition. Wall-clock timestamps alone cannot establish causality between machines.

## When the same fact lives in several places

Identify the authoritative input and how far the derived view has consumed it. For a database plus search index, interrupt the process between writes, then update one item and delete another while the index catches up. Verify the surviving item has the new value and the deleted item is absent. Compare a rebuilt index and the live index to the authoritative records at the same committed position. Include missing keys, extra keys and values. Matching counts can hide a stale row replacing a lost one. A log or transactional outbox can make committed changes recoverable. Its consumer still owns duplicate effects, ordering and recovery before source history expires. [Using logs to build a solid data infrastructure](https://martin.kleppmann.com/2015/05/27/logs-for-data-infrastructure.html)

For windowed aggregates, distinguish when the event occurred from when the processor saw it. Deliver an older event after a window has emitted, then replay it. Check the downstream total against the product's late-data policy, including any correction or deliberate exclusion. A watermark expresses progress under assumptions about lateness. It cannot guarantee that every source has sent every event. [The Dataflow Model](https://research.google/pubs/the-dataflow-model-a-practical-approach-to-balancing-correctness-latency-and-cost-in-massive-scale-unbounded-out-of-order-data-processing/)

## When data outlives the writer

Rehearse the actual rollout and rollback order. Read a released record with the candidate. If old writers can coexist, give an old writer a new record, change an unrelated field through its normal save path, then reopen it with the candidate. Assert that the new field survived. A successful decode can hide a destructive rewrite. For a backfill, overlap a live edit with the scan, interrupt and resume, then compare the final values with the source at a known position. For deletion promises, include retained logs, rebuilds and restored backups in the observation boundary.

## When load changes the result

Choose a load parameter that could expose a bottleneck. Examples include traffic to one key, fan-out per request, bytes per write and backlog during a slow sink. Uniform keys can make a partitioned design look scalable while one tenant overwhelms its partition. Benchmark the real access pattern, including index maintenance or compaction if it competes with foreground work. For fan-out, measure end-to-end tail latency under representative arrivals. Record offered and completed work, errors and queue growth. After restoring sink capacity, measure whether the backlog drains within the recovery objective. A fast median among completed requests can coexist with steadily rising wait times. [The Tail at Scale](https://research.google/pubs/the-tail-at-scale/)
