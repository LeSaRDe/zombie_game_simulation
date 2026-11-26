# Parallel computation and canonical effects

The coordinator owns semantic time, reservations, ID allocation, random outcomes,
completion validation, lifecycle transitions, and ledger publication. Process workers
receive detached records and return proposals. Independent experiment replications,
policy batches, continuous actor materialization, and a bounded class of independent
action effects can use real processes.

The default worker setting is `auto`. The budget respects process CPU affinity,
ancestor cgroup CPU quotas, available memory and cgroup memory limits. Automatic
selection reserves one available CPU for the coordinator when possible; an explicit
positive count is bounded by the detected capacity, population, and memory budget.
Independent experiment jobs divide that capacity before allocating workers within
each run, avoiding nested multiplication of the requested process count. The resolved
request, capacity limits, effective count and real worker CPU seconds are available
through `Simulation.execution_diagnostics()` and CLI run manifests. These operational
settings do not change the semantic configuration fingerprint.

For batches of at least 32 eligible controllers, workers construct local observations
and run policies on detached neighborhood records. A spatial index contains conservative
movement-path envelopes; exact current positions, range, and visibility checks still
decide what each agent perceives. Index membership changes only when an actor's path or
state changes. This avoids rescanning all trajectories at each fractional event time.
Candidate order matches the original point-grid implementation. Process results return
in any order and are restored to the canonical input order before intents, IDs, draws,
or effects are published. The operational `execution.completion_order` setting can
exercise native, reverse and seeded-shuffle delivery without changing that order.

`parallel.conflict_components` connects write/read and write/write access conflicts;
read/read access alone is independent. Tokens describe concrete actors/targets and
shared predicates. At one completion frontier, every action reads the geometry token,
so a barrier mutation couples it with every simultaneous line-of-sight consumer.
Unsupported effect handlers write a shared opaque-effect token and conservatively
force serial handling of that frontier. These declarations prioritize a valid serial
meaning over speculative concurrency.

Five deterministic effect calculations have worker support: eating hunger reduction,
first-aid healing, smash/demolish integrity damage, and barrier repair. Only singleton
independent components are submitted. Workers compute bounded final values and actual
amounts, while the coordinator retains resource release/consumption, gate mode changes,
biological clocks, action completion and publication. This is action-effect computation,
in addition to parallel movement/rest/hunger materialization.

Immediately after ordinary completion validation and before mutation, the coordinator
rebuilds a fingerprint of the exact actor/target/profile/parameter inputs. A matching
proposal supplies the computed effect; a mismatch discards it and invokes the original
serial formula. Fingerprints exclude incidental ledger revisions but include all effect
inputs. A worker failure publishes no partial result and falls back to serial handlers.
Consumption, fallback and worker-batch counters are execution diagnostics outside the
semantic ledger.

`implementation_checks/effect_parallel_check.py` exercises four disjoint Doctor–patient
pairs. Runs with 1, 2 and 4 workers have identical semantic ledgers and final state after
normalizing distinct run IDs. Four prepared heals are consumed in each run; the process
runs use a real worker batch. Deliberately corrupting one read fingerprint causes one
serial fallback and preserves the same ledger/state. The machine-readable evidence is
`artifacts/model_checks/effect_parallel.json`.

This implementation is deliberately conservative: mixed unsupported frontiers serialize,
and process overhead can exceed the benefit of small arithmetic tasks. Throughput claims
require measured scenarios; the equivalence check establishes operational semantics,
not a universal performance gain.

`implementation_checks/worker_differential_check.py` compares actual 1,000-agent
baseline runs with 1 and 20 workers: all final semantic state and recorded events
match, and all 20 process IDs perform policy work. The supplied parallel acceptance
cases pass for 2 and 4 workers with reverse and shuffled delivery. Independent
1/2/4/10-worker five-second-prefix measurements on the development host took roughly
10.5/8.9/8.4/8.5 seconds using the default tmpfs scratch directory. These short-prefix
measurements are evidence of useful work
and deterministic output, not sustained utilization of every CPU. Small asynchronous
decision batches, conflict handling, durable SQLite publication, and checkpoint
serialization remain coordinator work. Increasing workers beyond four did not improve
this measured prefix. No idle CPU load is created to inflate utilization.

The exact spatial-index differential check is
`implementation_checks/spatial_index_check.py`; it compares the original point-grid
implementation and the new index through ten seconds of the full baseline, including
every event. A later four-worker prefix reached 60 seconds in 207.1 wall seconds
(30,365 revisions; 105,121 events; a 533.9 MB ledger). Its report is
`artifacts/worker-grid-60.jsonl`. The reported peak RSS includes explicit full-state
and complete-event serialization for equivalence hashes, so it is not a measurement
of steady engine memory. That historical report also includes verification in
`coordinator_cpu_seconds`, while `advance_seconds` excludes it; dividing those
two values does not measure coordinator utilization. The benchmark now stops both
advancement timers before verification and reports `verification_seconds` and
`verification_cpu_seconds` separately. In the retained prefix, 17,601 of 23,912
decisions (73.6%) ran in parallel batches, with 6,311 decisions handled serially.
That is a count of decisions, not sustained CPU utilization. This prefix does not
establish full 1,800-second acceptance.

History remains lossless. Events, decisions and random-draw sequences keep compact
sequence indexes and a bounded decoded-page cache over the durable ledger. World
transactions copy changed records under the store lock and retain undo references
until durable publication, avoiding copies of all historical map entries. Runtime
memory is re-encoded for every policy decision and each replacement or removal;
movement and hunger updates reuse unchanged committed private-memory references.
Committed references update only after the world and runtime transaction succeeds.

Full world and runtime recovery anchors begin every 1,000 revisions. If a compressed
world anchor exceeds 8 MiB, its size scales the next interval, capped at 10,000
revisions for the default anchor setting. Every intervening delta remains durable;
the tradeoff is a longer replay scan when restoring between anchors. Automatic full
checkpoint defaults are 300 simulated seconds or 250,000 transactions. Explicit
configured cadences and manual checkpoints still apply. These are execution-only
recovery accelerators: neither biological time nor event scheduling is changed.
Pause and stop requests yield at committed coordinator boundaries after the current
atomic batch and its worker results settle, without advancing to the requested
future cursor or writing an unnecessary periodic checkpoint.

A separate ext4 run profiled durable disk publication through a last sampled
cursor of 117.419 seconds (59,571 revisions; approximately 959 MB of ledger data).
It was deliberately stopped and is marked `NOT_FINAL` in
`artifacts/acceptance-baseline-physical-disk-profile-manifest.json`. A 30-sample
probe observed the coordinator waiting in `jbd2_log_wait_commit` 17 times,
runnable 10 times and in a futex wait three times. All 24 CPUs were available,
with no visible CPU quota or ancestor throttling. The physical-disk bottleneck
was synchronous durable publication; launching more policy workers cannot remove
that serial wait. Durability settings were not reduced.

The full 1,000-agent attempt used the runner's ordinary `/tmp` scratch filesystem
(tmpfs on the development host), with SQLite `synchronous=FULL` unchanged. It
reached the first event at time 1,800, then reported a SQLite disk I/O error during
the final checkpoint before 483 remaining same-time events and the command ACK.
Its actual failed invocation is preserved in
`artifacts/acceptance-baseline-tmpfs-checkpoint-failure.json`. The failure's precise
cause is unresolved; sampled free space can miss transient allocations. The
automatic retention mechanism preserved the complete committed world/runtime
prefix with its verified SHA-256.

A verified SQLite copy on the artifact disk was continued with the exact archived
package, original run ID, seed, 23 workers, queue, RNG state and checkpoint cadence.
The genuine pending command completed at time 1,800 with `HORIZON`, revision
1,091,736, and a durable applied/completed receipt. It appended 485 revisions and
968 events. Every original commit, runtime commit, event and participant row was
compared byte-for-byte after continuation; the retained source checksum remained
unchanged. The completed primary is 26,421,706,752 bytes. Its receipt, source-package
hashes and final checksum are recorded in
`artifacts/acceptance-baseline-completed-history/baseline/run-0.sqlite.continuation.json`
and `artifacts/acceptance-baseline-completed-final-audit.json`. Acceptance of recovered
captures is a separate original-validator invocation; the failed original invocation
is never relabelled as passing.

This run also exposes the remaining scaling limit. The original attempt took
11,126.85 seconds and accumulated 11,038.77 coordinator CPU seconds versus 610.42
CPU seconds across 23 worker PIDs. Its sampled peak coordinator RSS was 62.02 GB.
The frozen continuation needed 472.29 seconds to restore the large journal and
599.18 seconds for the pending command including its due full checkpoint; separate
copy and final verification took another 272.76 seconds. A host-wide probe during
that checkpoint observed about 35.98 GB of swap in use, without attributing that
total to one process. Later workspace refinements have their own regression
evidence; the archived package records precisely which code produced this run.
See `artifacts/acceptance-baseline-resource-summary.json` for measured bounds and
scope. Tmpfs execution and a short physical-disk continuation do not establish
full-horizon physical-disk throughput or power-loss persistence performance.
