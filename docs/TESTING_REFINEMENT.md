# TASK 2 testing and refinement

Acceptance validation finished, 2026-11-25. All 539 catalog cases have passing evidence across the recorded tier executions, with no skips. The full baseline passed the original acceptance validators after genuine journal continuation and read-only capture evaluation; the original checkpoint-failed invocation remains recorded separately. This report follows the current step in
prompts/zombie_game_plans.md: exercise the supplied tests and address the six
reported runtime/GUI issues. No ontology or problem-formulation changes have
been made. The user explicitly approved correcting incomplete gate fixtures
while preserving the ontology; see GATE_FIXTURE_REVIEW.md.

## Reported issues

| User report | Implemented behavior and verification |
|---|---|
| Unknown run immediately after creation | Creation reserves the run identity before worker startup; reads distinguish initialization from an unknown run. Repeated real-browser create/start cycles pass. |
| Non-JSON runtime error | API errors use structured JSON; the viewer also handles plaintext or malformed server responses with a readable error. A real plaintext-500 regression passes. |
| Stale control generation | The viewer adopts its own acknowledged generation and ignores callbacks from an older run. A genuinely stale second tab must refresh; the acceptance case verifies rejection rather than silently overriding another controller. |
| Worker count and CPU use | Hardware-aware automatic budgeting and real process policy work are implemented and verified with deterministic serial/parallel equivalence. Full utilization of all cores for one run is **not achieved**: coordinator publication and full checkpoints remain limiting work. |
| Pause does not stop advancement | Pause acknowledges only after the current atomic work settles at a committed boundary. Repeated browser checks observe no revision advancement after acknowledgement. An already-started synchronous checkpoint can delay that acknowledgement. |
| Terminate without save | The GUI exposes Terminate (no save); termination requests no additional checkpoint, retains previously committed history, and rejects resume. A checkpoint already underway can finish before termination acknowledges. Actual browser termination cycles pass. |

## Validation evidence

| Scope | Observed result |
|---|---|
| Core acceptance tier | 489/489 pass against the final workspace, including the approved enclosure corrections, canonical configuration inputs, model-version resolution, checkpoint fixes and final control-boundary guard (44.568 seconds). |
| Lifecycle integration | The supplied worked population-accounting integration case passes. |
| System workflows (within core) | 47/47 pass: backend equivalence, exact restart, replay, abrupt crashes, corruption rejection, storage exhaustion, reordered workers, dependency retry, configuration, branching, measurements, learning interfaces and model behavior. |
| Formal exports | Three executed treatment/death/conversion traces pass the independent RDF reader and original SHACL shapes. Three additional corrected gate traces also conform. |
| Statistical diagnostics | Both predeclared 1,024-seed experiments pass their independent probability/contention checks. |
| Default model witness bank | All 29 actions selected, admitted and resolved in the independently checked witness contexts. |
| Encoder bank | All 29 typed action roundtrips, padding failures and actual action effects pass. |
| Training smoke recipe | Exactly 4,096 real PPO decisions collected; optimizer updates, disjoint split accesses and fresh-process saved-policy evaluation pass. |
| Runtime browser regression | Three actual Chromium create/terminate cycles and nine pause/resume cycles; no unknown-run/stale-generation errors, no revision advance after pause acknowledgement, readable plaintext-500 handling, terminal no-save behavior. |
| Worker scaling | Actual workers execute observation/policy work; current-code serial/20-worker comparison preserves the full state and every semantic event. Scaling is limited by remaining coordinator work; this does not claim linear speedup. |
| Full baseline | The original tmpfs invocation failed with a SQLite disk I/O error during its final checkpoint copy. Its complete committed primary/runtime journal was retained. Genuine continuation under the exact archived kernel dispatched the remaining 483 events at time 1,800 and durably completed the original command at revision 1,091,736. Independent final audit confirms the terminal receipt, no remaining due events and unchanged historical prefix. The original acceptance validators then passed against recovered initial/final captures in 456.860 seconds. |
| Browser acceptance | All 38 cases pass together (411.116 seconds), including four actual server-crash recoveries, seven exports, both keyboard browsers, configuration parity, observation isolation, replay, cohorts and stale-tab controls. |
| Browser performance | Both supplied cases pass using actual trusted inputs over a 30-second measurement interval after a 5-second warmup. At 1,000 agents: 60.00 FPS, input p95 2.4 ms, receipt p95 12.9 ms. At 10,000: 59.07 FPS, input p95 7.4 ms, receipt p95 68.9 ms, visible spatial aggregation. Observed subscriber queue depth was 1. |

The complete catalog contains 539 cases and 2,645 assertions across core,
integration, browser, performance, statistical and training tiers. The
[combined report](../tests/results/combined-final.json) records PASS for all 539
cases and pins every contributing report by checksum. These are separate tier
executions, not one uninterrupted runner invocation. The
[baseline report](../artifacts/acceptance-baseline-full-final.json) explicitly
identifies the read-only recovery adapter. Raw reports are retained under
artifacts/acceptance and tests/results, with browser recordings and images.
The aggregation script, scripts/summarize_acceptance.py, never counts failed,
skipped or missing cases as passing evidence.

Additional checkpoint/control corrections are applied to the final workspace build;
the completed baseline continuation used the separately archived source. The first rechecks pending
controls after the final clock commit, preventing an unnecessary automatic
checkpoint when a request arrives during that commit. The second makes a portable
bundle's adjacent history authoritative and hashes sidecars in 1 MiB chunks,
avoiding a full-ledger allocation. Failed copies also restore cadence markers and
clean only temporary files owned by that attempt. Eighteen bundle/hash/failure
checks pass against the workspace. The control race reproduces before the fix
and passes afterward. All 489 core cases pass again (44.568 seconds); a newly
started browser-test backend passes three create/terminate and nine pause/resume
cycles. Its test server was shut down and the user's existing server was left
untouched. These changes do not modify the archived code used by continuation.
The 1,800-second trajectory therefore verifies that archived kernel; the final
workspace is separately verified by the core suite, focused regressions and
isolated package checks, rather than a second full baseline run.

Rolling checkpoint JSON, SQLite sidecar and model pins still publish as separate
files. A failure after sidecar replacement but before JSON publication can make
the previous portable bundle unusable. The complete primary runtime journal
remains the recovery source in that situation; this refinement does not claim
atomic publication of the entire multi-file bundle.

During the full run, review found a quadratic lookup in the acceptance adapter's
semantic revision normalization. Python evaluated a full-history fallback scan
even when the revision was already mapped. A direct lookup plus binary search
for missing revisions preserves the previous output exactly; nested edge cases,
real workflow captures and all 489 core cases pass. The original worker had
already loaded the old function. Final capture evaluation uses a fresh
read-only adapter after genuine journal continuation completed the pending work.

That recovery adapter requires the original resolved configuration, matching
durable command identities and payloads, a completed acknowledgement at the
latest frontier, and complete checksummed world/runtime history. It preserves
all snapshot fields and uses the same normalizer. A real workflow differential
matches every capture; twelve invalid-evidence cases are rejected. Recovered
capture evaluation is identified separately from the original failed runner invocation.
The completion-gated preservation helper never signaled the original worker:
the checkpoint I/O failure occurred first. Automatic retention saved its complete
26,420,604,928-byte primary ledger. The continuation copied that immutable prefix
to disk and retried the same pending command, with the same run identity, random
state, queue and configuration. Before and after continuation, all 1,091,252
original world revisions, 1,091,252 runtime revisions, 3,129,700 events and
2,687,429 participant rows matched the source byte-for-byte. No initialization or
earlier simulation events were repeated. Continuation appended 485 revisions and
968 events, ending at revision 1,091,736 with termination reason HORIZON. The
completed 26,421,706,752-byte primary has SHA-256
`9e6c6f3b811d29869bc0a73f62519af48a8ce95b29dd4dbfe47ded7867107a16`;
the original retained primary's checksum remained unchanged.

The [continuation manifest](../artifacts/acceptance-baseline-completed-history/baseline/run-0.sqlite.continuation.json)
records the actual pending command, source hashes, appended work and prefix
comparisons. A separate [final audit](../artifacts/acceptance-baseline-completed-final-audit.json)
reopened the durable command receipt and confirmed its run identity, revision and
time against the final frontier, with zero pending events through the horizon.
It also counted 112 actual conversion events and 264 actual death events; those
counts come from the completed journal, not inferred endpoint differences.

The launch-matching wheel and verification metadata are retained under
`artifacts/distributions/baseline-loaded/`. Its bytes match all twelve module
hashes in the launch manifest and the recorded original capture-adapter hash.
The independent final audit also verified every one of the 48 extracted wheel
members against the archived wheel, whose SHA-256 is
`a512dece6bf9530a8ef178688b1b18810ea5a8d02470cf9af6396eabb092be47`.
Later capture changes have separate before/after provenance. The final-workspace
checkpoint changes, source hashes and regression evidence are recorded in
[checkpoint-final-provenance.json](../artifacts/acceptance/checkpoint-final-provenance.json).

The original attempt used a tmpfs primary ledger. To
accommodate checkpoint replacement peaks, the fully registered checkpoints at
1,200 and 1,500 seconds were copied to disk, hash-verified and fsynced, then their
paths were atomically replaced with links. Their coordinator pauses were 0.570
and 0.885 seconds respectively. The final checkpoint's previously absent JSON
temporary path was exclusively linked to a new, fsynced disk target; real
checkpoint/restore checks verified this publication route. The sidecar copy
failed before the JSON writer, so that spill remains empty. The exact cause of
the SQLite I/O error is not established by these samples. The complete retained
primary journal survives scratch cleanup. Its completed continuation used disk for both
the primary and checkpoint files, with SQLite synchronous=FULL and the original
checkpoint cadence unchanged. These storage interventions
are included in provenance and do not establish unassisted physical-disk
throughput or power-loss durability performance.

## Runtime changes

Run creation and read APIs distinguish initialization from an unknown identity,
pin committed read frontiers, and serialize shared-manager database access.
The UI rejects stale run callbacks, adopts acknowledged control generations,
and reports non-JSON server failures clearly. The original dry-run error's
specific cause is not inferred solely from its message; repeated regression
cycles establish the behavior of the corrected paths.

Pause interrupts advancement at a committed boundary. Its acknowledgement is
durable before controls become available. Terminate (no save) ends the worker
without requesting another checkpoint; history already committed before termination
remains available, and resume is rejected for the terminal run. Both commands
wait for an already-started synchronous checkpoint to finish; pending commands
prevent an otherwise-due optional checkpoint from starting.

Automatic worker budgeting considers CPU affinity, container CPU quotas,
available memory and nested experiment pools. Parallel workers consume detached
observation inputs; ordered publication preserves semantic IDs and RNG keys.
Event, decision and random-draw payloads are kept in the durable ledger with bounded decoded caches,
and locked transaction staging avoids repeatedly copying growing history maps.
Historical intent and occurrence records remain in world state, so complete
snapshots and checkpoints still grow with the run and require substantial memory.
On this host, the retained ext4 run spent 17 of 30 sampled coordinator waits in
jbd2_log_wait_commit; all visible CPU quotas were unlimited. The 23 workers
performed real policy work, but synchronous filesystem publication limited
sustained CPU utilization. This is not a claim of linear scaling or full use of
every core for one run. The completed trajectory began on tmpfs and finished from
a verified disk copy; it must be read separately from unassisted physical-disk
throughput measurements. The full tmpfs run’s first automatic
checkpoint at time 300 / revision 155500 held advancement for at least 60 seconds
during synchronous serialization and copying; coordinator RSS peaked near 10.15 GB.
It completed and the run continued. These observed checkpoint costs also limit
responsiveness while an already-started checkpoint finishes. Automatic checkpoint
files are rolling replacements; earlier revisions remain in the complete journal.

The CPU-utilization request remains only partially addressed. The original run
averaged about 1.05 cores of measured coordinator plus worker CPU time; automatic
23-worker selection is a hardware capacity ceiling, not a measured throughput
optimum. The short baseline prefixes plateaued around four workers. Further
work should first remove redundant full-payload JSON copies during checkpoint
serialization, with byte-equivalence and detachment regressions, and profile
coordinator preparation/publication before redesigning batching. Those changes
are not included in this release, and checkpoint improvements alone would not
keep all 24 cores continuously busy.

GUI JSON and CLI TOML inputs now use the same validated numeric representation and semantic fingerprint. New model assignments record the actual registered version; an explicit legacy major selector is retained separately from the resolved version.

Command references reject changed payloads. Recovery retains the reserved child identity and parent cursor; command receipts retain their own effective boundary even when the child later advances. Real server process crashes after durable effects verify that retrying the original request does not duplicate runs or interventions.

Checkpoints now pin ontology semantic files and actual model manifests/code
artifacts. Nonserializable model memory with an explicitly declared missing
restart codec permits history replay but rejects exact continuation with
MODEL_STATE_UNAVAILABLE. Ordinary models preserve their private memory exactly.

The viewer rebuild also passed the focused four-case server-crash recovery
regression. The final wheel was independently installed in a fresh Python 3.12
environment and checked against source, ontology and static-asset bytes.
Distribution hashes are recorded in artifacts/distributions/wheel_verification.json;
all 44 packaged files match the workspace and isolated installation, and all 48
RECORD hashes pass. The core installation executes real actions and checkpoint
restore/continuation without third-party core dependencies. The verified wheel
SHA-256 is 266264c89c5ada69f50c94239b033b8ac03ce61333d34484fc687c5a5e387d99.

## Reproduction

Use the repository source explicitly while developing:

    PYTHONPATH=src .runtimeenv/bin/python -m tests.run_acceptance --adapter zombie_sim.testing:create_adapter --tier core --report tests/results/core.json

Use .venv-training/bin/python for the selected training tier. Browser tiers
require Playwright, its Firefox/FFmpeg downloads, the installed Chromium binary,
and permission to start local browser/service processes. Full baseline and
performance tiers require appropriately long explicit timeouts.

Raw performance samples are retained in
artifacts/browser_acceptance/043ea4b6f5004b8a9f4664dea5eced1d/benchmark.json
and artifacts/browser_acceptance/e12b642dd35a4c68885ad258a4f424e7/benchmark.json.
The final benchmark includes five measured Pause clicks plus pan, selection,
cohort and replay interactions. These measure browser interaction with a paused,
real initialized scene, not
1,800-second simulation throughput.

The pre-existing user GUI server is not used for these tests. A server process
must be restarted to load changed Python modules; rebuilding static assets alone
does not replace an already running backend.
