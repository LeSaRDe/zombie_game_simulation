# System and browser adapter contract

`systems.py` supplies executable specifications for the **future** implementation.
The stdlib runner sends only each case's `request` to `Adapter.execute(request)`.
The adapter must bind these operations to the real application services, process
supervisor, storage, model interfaces and browser. It must not import expected
checks, construct a replacement simulator, implement the asserted behavior itself,
or return a verdict in place of evidence. Unsupported operations are failures.
Dependency-specific cases are explicitly selected by tier; an unavailable selected
dependency is an error, never a passing skipped test.

These protocol names, normalized error codes and GUI labels are proposed testing
interfaces under D1/D3/D4/D7/D9, not evidence that those design decisions have been
approved. They can be mapped to different product APIs while retaining semantics.

## Request and response

`request.kind` is `workflow` or `browser`. `setup.runs` maps local run aliases to
`{world, config}`. World fixtures use the same validated builder and defaults as
simulation requests. Setup does not create or advance runs. Aliases are scoped to
one isolated test workspace. `run.create` creates a paused managed run at the initial
pre-decision boundary, including when model decision mode is selected. Explicit
`advance("0")` starts decisions at time zero; later advances run due decisions.
No run progresses merely because a capture or GUI query is made. GUI start and CLI
start use real managed execution through their common service.

Execute `steps` sequentially. `label` saves the operation's result under
`response.captures[label]`. Capture labels are unique within a request. A step
referring to another label reads that actual artifact, never an expected value.
Return all raw service records needed by the checks, plus diagnostic logs and
artifact paths. Fail any unexpectedly rejected operation, browser timeout, missing
capture, missing feature or unexpected worker exception.

Snapshots have exactly the shared normalized schema in the main adapter contract:
time/revision strings; `world`; keyed agents, barriers, stockpiles, remains,
episodes, reservations and signals. Agent records include their `id`. Optional
current infection is represented by `infection_episode: null` when inapplicable.
`snapshot_paths` nominates captured snapshots for the runner's independent invariant
checks; `baseline_paths` additionally requests the 1,000-agent baseline checks.

Equivalent-run comparisons normalize only run-scoped **identity namespaces** and
execution-only metadata. Assign semantic object/event IDs from their recorded
creation order, preserving every reference and causality edge. Normalize the run
namespace to `RUN`; parent/child lineage references remain explicit aliases.
Do not sort away ordering differences, discard RNG draws, alter times/quantities,
remove failures/cancellations, or omit model memory from exact restart snapshots.
Semantic history excludes the separate control audit and includes all semantic
events, occurrences, draws, continuous segments, decisions and assignments.
The complete normalization must be versioned and included with the adapter.

## Run, storage, fault and configuration operations

| Operation | Real operation and captured facts |
|---|---|
| `run.create` | Validate/build the named run, create durable history and acquire its worker lease. |
| `run.script` | Execute embedded simulation operations (`submit`, `submit_batch`, `advance`, etc.) through the public engine. Optional `draws` are keyed test RNG inputs `{intent, channel: hit/infection, value}`; record the real probability, draw and outcome. |
| `run.capture` | Query the specified committed run projection at its current cursor. `what` values are defined below. |
| `run.checkpoint` | Write an actual checkpoint and manifest. Return `state` (full snapshot), artifact paths/checksums and declared `restart_capability`. |
| `run.restart` | Destroy worker and live-store objects, open the requested checkpoint in a fresh process, validate identities/checksums, recover its cursor and outstanding work. `exact: true` forbids silently dropping model memory. |
| `run.replay` | Reconstruct the full snapshot at an exact recorded `time` through the history reader, without invoking policy or random services. |
| `run.recover` | Restart a killed worker against its existing durable ledger; `replay_commands` retries only the test driver's previously recorded commands with their original IDs. Do not fabricate missing semantic results. |
| `run.await` | Bounded wait for a named real lifecycle state; timeout is failure. |
| `run.branch` | Create a distinct child from an explicit time/revision boundary; return `parent_alias`, `child_alias`, actual run IDs, lineage and random-alignment mode. |
| `run.intervene` | Submit `{id, at, change}` to the intervention service. Supported changes match simulation `intervene`: resource addition, role replacement, model replacement. Requires `interventions_enabled`. |
| `fault.arm` | Install one real failure hook at the named point/occurrence. Persistent write faults stay armed. Capture fault point, error, process and durable revision. Missing hook is an error. |
| `artifact.corrupt` | Modify bytes or manifest reference for the specified checkpoint checksum, model artifact checksum or ontology fingerprint. No adapter-generated pretend error. |
| `workers.completion_order` | Gate actual worker completion delivery with a deterministic reverse/shuffle schedule. Keep semantic event IDs/RNG keys intact. |
| `server.recover` | Restart the server, reconcile durable command journal and worker leases, preserving surviving managed workers or recovering killed ones. |
| `commands.inspect` | Read actual journal records: `semantic_effects`, `resulting_run_ids`, `active_worker_leases`, effective time/revision, and status. Filter worker leases to the command's resulting/affected run; `active_worker_lease_count` is the length of those raw rows. Zero is valid if the worker has already completed; never more than one active holder. |
| `runs.list` | Enumerate runs in the isolated test workspace. |
| `config.resolve` | Resolve preset + semantic/execution overrides through the shared schema/validator, return semantic configuration/fingerprint, seed and execution configuration. |
| `config.export_import` | Serialize the referenced resolved configuration to the actual format, then read and resolve it with the production importer. |
| `cli.run` | Invoke the actual CLI entry point with a configuration file and bind the resulting run to an alias; retain exit status/stdout/stderr and artifacts. |
| `measurement.query` | Invoke the ledger-derived measurement implementation for the named time/interval; return its numeric fields and provenance. |
| `observation.read` | Read the exact observation stored for the identified decision, without recomputing it from a later global state. |

`run.capture.what` values:

- `semantic_snapshot`, `initial_snapshot`, `durable_snapshot`: complete normalized
  snapshots. The last is reconstructed exclusively from committed durable data.
- `semantic_history`: the complete ordered semantic history described above;
  includes an `occurrences` map, even when empty.
- `occurrences`, `decisions`, `random_draws`, `model_memory`, `interventions`:
  corresponding recorded collections. Decisions contain input, output, model
  ID/version, memory revision, fallback reason and actual admitted occurrence.
- `execution_counters`: raw cumulative policy invocation and RNG-service invocation
  counts, with all engine-side calls instrumented. Replay must leave them equal.
- `resolved_config`, `initialization_provenance`, `status`, `fault_trace`,
  `scheduler_diagnostics`: actual service records. Retry diagnostics include the
  number of rejected tentative transactions, never an adapter's judgment.
- `timeline_records`: the same ordered event projection consumed by the timeline,
  including ID, time, phase/order, before/after revisions, causal IDs and occurrence
  link. `agent` filters actor **or target**, including associated cleanup events.

Crash points are before durable history commit, after history commit/before publish,
after checkpoint rename/before catalog registration, and command effect/before ack.
All abrupt crash tests terminate the process and discard volatile objects. This
also applies to the **memory** backend: its live state is volatile but its history
ledger/checkpoint is durable. Preserving Python objects across a restart is invalid
evidence. Each test uses an isolated temporary directory; inject faults only there.
`history_write` with `ENOSPC` must exercise actual persistence error handling.
`dependency_validation` omits one declared read key on the first tentative event;
the real coordinator must detect conflict and retry without partial commit.

`on_fault: capture` / `on_error: capture` captures the expected raised error with
`code` and diagnostic fields instead of aborting the whole test. Unexpected errors
still fail. A model-checksum corruption test must start with a real pinned default
model artifact even when actions are scripted.

## Model, learning and training operations

| Operation | Required behavior |
|---|---|
| `model.install_fixture` | Register a tiny test plugin through the real model registry, before run creation. It substitutes only a policy, never the engine. Fixtures are defined below. |
| `rl.attach` | Wrap the existing run with the real Gymnasium/AEC adapter. Preserve controlled identity, reward-task version, horizon/cutoff and episode IDs. |
| `rl.step` | Call the adapter with the given typed intent. Optional keyed `draws` use the same real RNG hook as `run.script`. Return actual elapsed time, reward and each reward term, discount, termination/truncation, bootstrap mask, controller episode ID and next controller episode ID. |
| `rl.aec_batch` | Iterate the real AEC API in `order`, recording each observation before submitting that actor's supplied intent. Return per-agent raw observations; do not sort or rebuild observations to conceal API-order leakage. |
| `encoder.evaluate` | Encode the supplied observation, encode/decode every candidate, and attempt to decode every padding slot. Return neighborhood features, decoded intents, candidate mask and each padding error. |
| `training.run` | Execute the plan's PPO smoke recipe for exactly 4096 collected decisions with the specified disjoint seed splits. Defaults include 1024-decision rollout batches and the versioned recipe from §9.3. Record actual optimizer updates, split accesses and checkpoint artifacts. |
| `training.evaluate_checkpoint` | Run deterministic held-out evaluation with the saved policy; return actual actions, `action_count`, elapsed times and reward terms. |
| `training.reload_checkpoint` | Load policy/encoder/normalization metadata from the saved bytes into a fresh trainer process. |

Policy fixtures are deliberately small boundary probes:

- `exception`: raises a named exception on its first decision; record normalized
  fallback reason `MODEL_EXCEPTION`.
- `missing`: a valid pinned assignment whose artifact becomes unavailable **after
  initialization**, so the runtime fallback is tested separately from invalid
  configuration rejection; record `MODEL_UNAVAILABLE`.
- `malformed`: returns a typed-contract violation (for example a missing action);
  record `INVALID_MODEL_OUTPUT`.
- `repeated_invalid`: always requests an out-of-bounds move; bounded rejection
  recovery must admit one recorded 1 s fallback wait, without a zero-time loop;
  record `REJECTION_LIMIT`.
- `private_counter`: immutable shared weights; private memory `{count: 0}`; each
  call increments only that actor's count and returns a 1 s wait. Count is 1 at
  t=0 and 4 at t=3. Persist and reload that memory through the actual model codec.
- `unserializable_memory`: declares no exact restart codec and retains a live
  process-local handle. State/history replay remains available, exact policy
  restart must be rejected explicitly.

Encoder input agent shorthand is expanded through the same production observation
schema defaults; absent local resources/geometry/signals/history are empty. Never
consult hidden global state to fill an observation. All padding decode attempts
must be returned, not just one chosen failure. No success is inferred from a model
training without raising: the tests compare saved/reloaded action and reward traces.

## Browser operations

See [browser/README.md](../browser/README.md) for selectors, capture fields and
browser requirements. Each `browser.*` operation binds to an actual browser page;
high-level form helpers expand to documented mouse/keyboard/form interactions and
retain an action log. They cannot call the business API instead of using the UI.
Service-side setup/fault/capture operations may call APIs directly to arrange
fixtures or independently verify the result.

`export.read_artifact` opens the actual downloaded artifact and its provenance
sidecar: validate the file format/signature, parse CSV/Parquet/SVG where applicable,
decode PNG dimensions, and inspect animation container/frames. Return byte length,
decoded metadata and the exact exported source scene from the export bundle's
sidecar. Never reconstruct missing sidecar data from the live run. Retain files for
visual regression; matching metadata alone does not prove pixel fidelity.
