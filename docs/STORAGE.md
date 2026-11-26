# Live state, history and continuation

The memory and SQLite backends expose the same committed-world contract in `src/zombie_sim/storage.py`. Both return detached dictionaries: modifying a returned view cannot change a run. The simulation coordinator owns mutable working state and publishes transactions with an expected revision.

```python
from zombie_sim.storage import History, MemoryStore, SQLiteStore

history = History("experiment/run.sqlite", initial={"time": "0", "revision": 0, "agents": {}})
memory = MemoryStore(history=history)
# Or use SQLiteStore("experiment/run.sqlite", initial=initial_state).

memory.commit_delta([
    ["set", ["agents", "1"], {"id": "1", "type": "Human", "life": 100}],
    ["set", ["time"], "1/3"],
    ["set", ["revision"], 1],
], expected_version=0, transaction_id="admit-1",
   records=[{"id": "event-1", "kind": "example", "actor": "1", "time": "1/3"}])
memory.close()
```

Patches contain `set` or `remove`, a list of object keys, and a value for `set`. An empty path replaces the complete document. Entity maps use string IDs. Arrays are ordered values and are replaced atomically. Incremental commits clone only changed branches; checkpoints periodically capture the complete state.

## Atomicity and concurrency

The memory backend durably writes the event/patch batch before publishing a new view. A logging error therefore leaves the published view unchanged. The SQLite backend holds `BEGIN IMMEDIATE` while checking the durable revision, appending events, updating changed live entity rows, and advancing the live revision. WAL and `synchronous=FULL` are enabled. Independent readers use a read-only SQLite connection and cannot write to the ledger.

An expected revision mismatch raises `VersionConflict`. The SQLite comparison happens under the writer transaction, including when two independent store objects open the same database. Transaction IDs are checked again under that lock: concurrent retries cannot overwrite a later commit or move the live revision backwards. A malformed delta rolls back the complete transaction.

SQLite is a local single-writer store. It is not a distributed database or a supported network-filesystem deployment. The application adds an exclusive operating-system worker lock and a process lease per managed run.

## Ledger contents

| Table | Contents |
| --- | --- |
| `commits` | Monotonic revision, unique transaction ID, exact rational time, compressed patch, optional full anchor, integrity checksum. |
| `events` | Ordered semantic records with revision, event kind, actor, and compressed structured payload. |
| `participants` | Actor/target associations for per-identity histories, including lifecycle `agent` fields. |
| `live_entities` | SQLite live state indexed by collection and entity ID. |
| `live_state` | Durable live revision and initialization compatibility snapshot. The entity rows are authoritative after incremental commits. |
| `checkpoints` | Registered checkpoint paths, revisions and checksums. |
| `runtime_commits` | Atomic scheduler, counter, phase-cursor and private-model-memory patches at every world revision, with verified anchors. |
| `control_commands` | Durable pending/applied/rejected control results; semantic completion is committed with its world/runtime transaction. |
| `metadata` | Versioned run metadata and durable active-command/control state. |

Event, decision and random-draw sequences use compact sequence indexes and a bounded decoded-page cache over the complete ledger; this does not prune their history. Private memory is re-encoded for every actual decision or changed assignment, while unchanged memory on motion/hunger updates reuses its committed representation.

JSON is canonicalized with sorted keys and non-finite numbers rejected, then compressed with zlib. Ordinary state serialization never executes Python objects. Exact time is stored as numerator/denominator text; a floating-point time column narrows searches but never decides a time boundary. Commits at the same time remain ordered by revision. History rejects decreasing commit times.

Recovery anchors begin every 1,000 commits. With the default setting, compressed anchors exceeding 8 MiB scale the following interval up to a maximum of 10,000 revisions; every intervening delta remains durable. The engine also creates complete continuation checkpoints, by default every 300 simulated seconds or 250,000 transactions. Explicit configured cadences and manual checkpoints still apply. Both patches and full anchors are integrity checked during replay. Historical development ledgers with bare anchors are verified against their checked patch chain before those anchors are used.

## Replay

```python
from zombie_sim.storage import History
from zombie_sim.visualization import project_state

ledger = History("experiment/run.sqlite", read_only=True)
raw = ledger.state_at(time="40/3", revision=250)
scene = project_state(raw, "40/3")
events = ledger.events(agent_id="1", end=250)
ledger.close()
```

`state_at` finds the closest earlier anchor and applies committed patches in order. A time-only lookup includes every committed event at that time; a revision selects a causal boundary within a timestamp. Raw state contains the engine's continuous anchors and active occurrences. `project_state` evaluates these through the engine's materializer and computes current derived attributes without invoking a policy or drawing randomness. Application and CLI queries reject times or revisions beyond the committed frontier.

Research measurements use the same requested revision. Population samples and event totals carry an explicit cursor; the browser labels lagging chart/cohort cursors instead of presenting them as synchronized. The metric cache invalidates the previous frontier when another event commits at the same timestamp.

## Checkpoints and restart

`History.save_checkpoint` writes a schema envelope and SHA-256 checksum to a temporary file, flushes and fsyncs it, atomically renames it, fsyncs the parent directory, then registers it in the ledger. Partial unregistered files do not become restart points. Corrupt envelopes are rejected.

Current checkpoints also pin the ontology semantic files and the actual registered model manifests/source artifacts by content hash. Artifact corruption or mismatch rejects exact continuation. A model explicitly lacking a restartable private-memory codec permits recorded-state replay but rejects exact restart with MODEL_STATE_UNAVAILABLE. Legacy files without artifact pins cannot provide that later verification metadata.

An engine continuation checkpoint must contain more than world state: pending events, phase/cursor, occurrence and reservation state, decision/random counters, policy memory, model assignments, and resolved configuration. The engine's `checkpoint`/`restore` operations own that payload. The per-revision runtime journal retains this continuation information between checkpoints, including every decision-memory update and exact queue insertion/removal.

Managed GUI runs additionally save `worker-checkpoint.json`, containing the engine payload and the control generation, pacing, status, and processed command acknowledgements. The combined file has an integrity checksum. On restart the worker reconstructs the latest committed runtime from the ledger and reconciles its control acknowledgements before accepting another command. Checkpoint files accelerate archival continuation; they do not limit recovery to an older prefix. Managed files are saved at command boundaries and the configured cadence (300 simulated seconds or 250,000 transactions by default). Every committed delta remains durable between these full checkpoints.

The application records run creation in `manager.sqlite` before creating files or launching a process. Retrying a creation command repairs incomplete setup using the reserved run ID, including its original start request. Pausing changes only run control; it does not advance biological time. Browser disconnection has no execution effect.

Every semantic commit atomically stores its world delta, event records, scheduler changes, counters, phase cursor, model memories, and any completed command acknowledgement. Recovery therefore uses the latest committed revision even when the last checkpoint file is older. A pending advance/timestamp command retains its original target and resumes its remaining work; a completed step is acknowledged without being repeated. Nonsemantic pause/pacing commands persist in the same run-local control journal, while manager.sqlite is a reconciled application index.

GUI workers and CLI continuation share a POSIX file lease for the run directory. CLI resume rejects while a GUI coordinator owns that lease; stop/save the managed run before continuing it from the CLI. Both live backends additionally compare the durable ledger revision before publishing a commit.

`runtime.restore_revision` reconstructs any committed revision and can continue the latest original ledger or create an independent verified prefix. Historical branching creates a new run ID and records parent revision, seed policy, and inherited pending work. It never truncates or overwrites a newer parent ledger. Legacy histories created before runtime journaling can start exact continuation at a complete retained checkpoint; missing earlier private runtime history is explicitly rejected.

Portable checkpoints omit duplicate immutable event/decision/random-outcome lists from JSON and reconstruct them from the verified SQLite sidecar. The private memory and pending scheduler state remain in the checkpoint itself.

Move the JSON, its adjacent `.history.sqlite` file, and referenced `.models` files
together, preserving their relative names. The adjacent history is authoritative
even when the original absolute path still exists; a damaged adjacent file is
rejected rather than replaced by a different generation. Sidecar checksums are
streamed in bounded chunks. Failed checkpoint attempts restore cadence markers
and clean only their owned unpublished temporary database files. The complete
primary journal remains the source for recovery across checkpoint failures.

## Exports

The CLI exports replayed JSON, ordered event CSV, world SVG, ontology Turtle, and Parquet (with the optional `pyarrow` dependency). Parquet stores exact times and revisions as strings and the full structured event as JSON. These files are reproducible derivatives; the SQLite ledger remains the source of truth. Live scene transport omits past intent/occurrence collections while retaining current actions; full historical records remain in the ledger. Viewer exports retain the source run, time/revision, and visualization version; saved cohort definitions retain their membership rule and reference revision.

```bash
zombie-sim inspect experiments/runs/RUN_ID
zombie-sim replay experiments/runs/RUN_ID --time 20 --revision 120
zombie-sim export experiments/runs/RUN_ID --format parquet --output events.parquet
zombie-sim analyze experiments/runs/RUN_ID --interval 1 --output population.json
```
