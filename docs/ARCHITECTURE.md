# The Zombie Simulation architecture

Open the **[interactive architecture atlas](architecture/index.html)** for nine linked flow diagrams, or the **[complete class atlas](classes/index.html)** for inheritance, ownership, attributes and methods. Both work offline and include standalone SVGs, editable Graphviz DOT and a searchable source index.

The current architecture separates four responsibilities: immutable domain facts, rules that calculate transitions, state ownership that validates and publishes them, and persistence adapters that commit or query recorded data. The Python API, launcher, CLI and functional React GUI remain entrypoints into the same framework.

## Find the relevant part

| Goal | Diagram | Implementation entrypoint |
| --- | --- | --- |
| Understand the full system | [Overview](architecture/overview.svg) | `Simulation`, `SimulationFramework`, managed run worker |
| Understand an agent and its evolution | [Typed domain](architecture/domain.svg) | `domain_model.Agent`, `AgentState`, `RoleAssignment` |
| Add or change game behavior | [Rules and ownership](architecture/engine.svg) | `GameRuleSet`, `ActionHandlerRegistry`, lifecycle rules |
| Follow one committed change | [Transaction flow](architecture/flow.svg) | `TransitionPlan`, `StateCoordinator`, `UnitOfWork` |
| Understand web execution/readers | [Workspace](architecture/workspace.svg) | `WorkspaceServices`, `RunManager`, HTTP controllers |
| Add a backend or understand restart | [Persistence](architecture/storage.svg) | `PersistenceBundleFactory`, `AtomicCommitPort`, `HistoryQueryPort` |
| Understand snapshot cost and isolation | [Runtime cells](architecture/runtime.svg) | `RuntimeState`, `RuntimeSnapshot`, `CowDict` |
| Change the GUI | [GUI](architecture/gui.svg) | Functional views and `gui/src/core` controllers |
| Build a model or training workflow | [Modeling](architecture/modeling.svg) | `ObjectDecisionModel`, framework, training pipelines |

## Typed facts and persistent identity

`Agent` contains one persistent `AgentIdentity(run_id, agent_id)` and one current `AgentState`. `HumanState` and `ZombieState` inherit shared life, stamina, position, effect and assignment behavior. Human-only hunger, inventory and starvation clocks belong to `HumanState`. Conversion installs `ZombieState` under the same identity, with the ontology's complete inventory drop, assignment retirement and history recorded atomically. Death retains the final biological state and position while removing active capabilities.

Status is derived from life, biology and infection. Effective profiles derive from type defaults, role definition, configured overrides and dated effects. The authoritative objects are frozen values with named fields; record codecs preserve existing wire fields, optional-key presence and exact timestamp spellings. Unknown unregistered fields fail explicitly instead of disappearing.

Equal immutable `ProfileValues` decoded from records share instances through a cache capped at 2,048 entries. The key preserves supplied fields, integer/float distinctions and signed zero. Agent identity, role consumption and state presence remain separate. Custom numeric or profile subclasses use ordinary construction. Sharing reduces duplicate historical profile storage without removing any action evidence; exported profile records remain detached dictionaries.

Roles are a separate hierarchy: `DoctorRole`, `WarriorRole`, `ScoutRole` and `EngineerRole` derive from `HumanRoleDefinition`; `TyrantRole`, `RunnerRole`, `SpitterRole` and `ScreamerRole` derive from `ZombieRoleDefinition`. The immutable definition is shared, while `RoleAssignment` holds individual state such as Spitter charges. A role does not choose the decision model or permanently classify an identity.

The existing SDK views in `entities.py` remain plugin-facing detached records. Their implementation bytes and the pinned modeling/policy/learning files were preserved. The authoritative domain classes live in `domain_model`; similar names in these two boundaries represent different responsibilities.

## Actions, events and scheduled work

`ActionDefinition` describes a catalog contract. `ActionIntent` records a proposal and its admission outcome. `ActionOccurrence` records an admitted durative attempt, reservations, cancellation and results. `DomainEvent` is a causal envelope with a named typed payload. `ScheduledTask` is exact ordered pending work: time, phase, deterministic priority, serial and task payload.

These types share explicit codec and lifecycle boundaries without merging their meanings. In particular, an occurrence is not an Event subclass, rejected intents do not create occurrences, and queue tasks are not automatically domain facts. [Ontology implementation mapping](ONTOLOGY_IMPLEMENTATION_MAP.md) traces all 29 actions and 25 validation invariants to owners and independent acceptance cases.

`ActionHandlerRegistry` supplies all 29 named strategies. `ActionLifecycle` owns admission, reservations, completion/cancellation and evidence. Damage, infection, conversion, death, resources, geometry, signals and effects have focused rule objects. Exact precedence and random event keys remain part of the established semantics.

## Calculate, validate, commit, publish

1. `Simulation` packages a `RuleRequest` and supplies a dated `WorldReadView` plus `RuntimeSnapshot`.
2. `GameRuleSet` constructs an isolated `PlanningSession`. Its draft can read immutable base objects and stage changed records. The session has no database, live Simulation or publisher.
3. The session returns an immutable `TransitionPlan`: expected revision, typed `StateChange` values, causal `DomainEvent` values, successor runtime, metadata and read dependencies.
4. `StateCoordinator.begin()` constructs `UnitOfWork`, rejects stale revisions and checks identity, terminal life state, references and reservations.
5. A `CommitBundle` submits world delta, continuation delta, events and any command receipt together through `AtomicCommitPort` under a stable transaction identity.
6. Only a confirmed durable result, including recovery through `resolve_transaction`, allows the coordinator to install the new world and the Simulation to adopt runtime state. Readers never receive the speculative draft.

`WorldAggregate` owns typed immutable entities indexed by persistent maps. `WorldReadView` returns detached legacy records where existing APIs need them. `WorldDraft` tracks a transaction's changes; it is neither a second published world nor a storage abstraction.

`ScheduledBoundary` also protects the preparation that happens before rule planning. It retains the prior runtime owner and gives the scheduler a separate heap and decision set. A failed transaction restores that owner, exact time, pending tasks and preparation anchors; a confirmed durable commit keeps the published successor. This avoids consuming a scheduled task merely because a storage write failed.

## Continuation without copying every model memory

`RuntimeState` declares the complete continuation field register: configuration, exact time, queue, random/counter state, private memories and operational anchors. An unexpected durable field is rejected. Snapshot export is detached and preserves list, tuple and set distinctions. Cache comparisons preserve numeric wire distinctions, including signed zero, through publication, journaling and restore. Snapshot sharing also preserves exact path spelling when path equality ignores case.

`RuntimeSnapshot` shares immutable cells. Each agent's private memory is its own isolation unit. Exact built-in dictionary/list/tuple/set trees use branch-owned copy-on-write values. Custom Python types, mutable custom keys, shared references and cycles use an opaque `deepcopy` boundary that preserves the object's type and graph within that memory. Existing snapshots remain detached from writable branches. Unread opaque memories are copied at import; a writable access detaches only that agent's value. Concrete queue lists contain immutable `ScheduledTask` objects, preserving `heapq` compatibility.

This ownership support does not grant an exact restart codec to arbitrary Python objects. A legacy model with unsupported private memory can continue running while its checkpoint honestly reports state-replay-only capability. Custom objects retain their existing Python `deepcopy` contract; aliases between different agents' private memories are not a shared-state mechanism.

Journal change detection compares immutable memory-cell identities. Movement or clock changes do not force re-encoding unchanged memories. Model calls receive ordinary detached dictionaries/lists at the existing plugin boundary. Configuration and runtime exports explicitly materialize or encode mappings; internal copy-on-write mappings are not dict subclasses that a JSON encoder could silently truncate.

## Persistence and research

`PersistenceFactoryPort` defines creation, restoration, history opening and prefix export. The default `PersistenceBundleFactory` constructs compatible live state, atomic writer, dated history and checkpoint components. Default memory execution retains a durable SQLite history; SQLite execution also stores the live projection there. The independent `contract-memory` backend verifies the same transaction and query contracts without SQLite and explicitly rejects durable restart after its lifetime ends.

`AtomicCommitPort` exposes revision-checked commit and transaction resolution. `HistoryQueryPort` exposes dated world/runtime/event/measurement queries. SQL remains inside `SQLiteHistoryQueries`, run-catalog and checkpoint adapters; game rules and generic state ownership do not import SQLite. Analysis services consume the query interface and preserve frozen revisions.

World and runtime encoders are explicit, versioned boundaries. New schema/implementation versions are validated before restart. Existing compatible default wiring and legacy records remain supported through the documented codec/migration path; incompatible custom mutation services receive explicit migration errors rather than silently using the old engine.

Portable checkpoints publish a checksummed envelope and an adjacent history sidecar through an owned intermediate generation. Recovery accepts that generation only when its identity and checksum explain an interrupted promotion. Successful publication removes its prior owned generation; unrelated user files and archived checkpoints are preserved.

## GUI, operations and extensions

React views and hooks remain functional. Controllers own requests, retries, generation checks, caches, subscriptions and cleanup; rendering objects own canvas/Plotly resources. Exact rational times remain authoritative while labels may be rounded for presentation.

Start/stop behavior is documented in [START_STOP_GUIDE.md](START_STOP_GUIDE.md). The [OOP refactor guide](OOP_REFACTOR.md) and [implementation report](IMPLEMENTATION.md) cover supported extension and compatibility boundaries. The earlier [approved proposal](DEEP_OOP_REFACTOR_PROPOSAL.md) is retained as planning history; the diagrams here describe actual source ownership.

## Regenerate and inspect

```bash
PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python scripts/build_architecture_docs.py
PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python scripts/build_class_diagrams.py
```

Generation reads Python/TypeScript source and uses installed Graphviz. It does not run a simulation or fetch external diagram libraries. The class atlas inventories every maintained named class/interface, including tests and nested classes; its full JSON model records file hashes and evidence. Frozen prior diagrams remain under the refactor evidence archive.
