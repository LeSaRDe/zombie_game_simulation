# UML class diagrams for the entire project

Open the **[interactive class atlas](classes/index.html)**. The starting diagram shows the implemented separation of typed domain values, game rules, state ownership and persistence. Choose a subsystem, complete implementation, or the whole project from the Diagram menu. Each box links to full declared members and source evidence.

The current AST inventory contains **438 class/interface definitions** across Python and TypeScript, with **218 declared inheritance/implementation edges** and **268 reviewed relationships**. Exact current counts, source hashes and coverage are recorded in [coverage.json](classes/coverage.json) and [class-model.json](classes/class-model.json). These describe the implementation, while the earlier [proposal](DEEP_OOP_REFACTOR_PROPOSAL.md) remains historical planning evidence.

## How to use it

1. Open the [atlas](classes/index.html). It starts at the main `Simulation` class at a readable scale.
2. Use **Diagram** to choose a subsystem or **Entire project · including tests and examples**.
3. Click a box to see every extracted declared attribute and operation, the source path/line, and relationship evidence. Long signatures appear in full in the inspector.
4. Use **Find a class or interface** to locate a class by name or file. Search results navigate to the class's subsystem when necessary. Names such as Python `ExactTime` and TypeScript `ExactTime` remain separate definitions.
5. Use **Fit whole diagram** for orientation, **Readable size** to inspect labels, and the scrollbars/zoom slider to explore. The complete diagram is intentionally large; subsystem views and search are easier for detailed reading.
6. Use **Open SVG** to view/export a vector diagram, or **Editable DOT** to modify its Graphviz source. The [complete JSON model](classes/class-model.json) contains every extracted member and relationship.

The atlas works offline. No simulation, web service or external JavaScript library is needed to view it. Class boxes abbreviate long signatures and show a bounded selection of members; the inspector contains the full extracted list. Inherited members stay on the class that declares them.

## Diagram index

| View | What it contains | SVG |
| --- | --- | --- |
| Core overview | Persistent Agent identity and typed state, role composition, rule planning, state coordination, atomic persistence and typed activities/events. | [Overview](classes/overview.svg) |
| Complete implementation | All implementation/contract definitions, excluding the separate example and verification definitions. | [Implementation](classes/application-all.svg) |
| Entire project | All inventoried definitions, including examples, test classes and nested helpers, plus referenced external bases. | [Whole project](classes/whole-project.svg) |
| Domain/configuration/ontology | Authoritative Agent/HumanState/ZombieState, eight role classes, profile/resource/environment values, activities/events and explicit codecs; plus configuration and SDK views. | [Domain](classes/domain.svg) |
| Engine/service composition | Simulation orchestration, execution services, component factories and explicit compatibility boundaries. | [Engine](classes/engine.svg) |
| Game rules | 29 action handlers, common lifecycle, biological/resource/geometry rules, isolated planning and observation. | [Rules](classes/rules.svg) |
| State ownership | Immutable world values, persistent indexes, drafts, runtime cells, revision validation and UnitOfWork. | [State](classes/state.svg) |
| Public contracts | Decision-model, simulation, storage/history and measurement protocols. | [Contracts](classes/contracts.svg) |
| Models/Python API | `SimulationFramework`, `Experiment`, model registry, scenario builder and policy inheritance. | [Models](classes/models.svg) |
| Persistence | Atomic/read ports, compatible backend bundles, independent in-memory history, SQLite query/catalog adapters and checkpoint/version validation. | [Persistence](classes/persistence.svg) |
| Application | Managed workers/repository/queries, HTTP controllers, readers, commands, CLI and shutdown. | [Application](classes/application.svg) |
| Analysis/export | Measurements, metrics, cohorts, timeline, comparisons, scene projection and format strategies. | [Analysis](classes/analysis.svg) |
| Learning | Environments, codecs, recurrent network class, learned model, settings and training/evaluation pipelines. | [Learning](classes/learning.svg) |
| GUI | Observable controllers, reader inheritance, sessions, presenters, exact values and typed interfaces. | [GUI](classes/gui.svg) |
| Operations | Launcher/API classes and the documentation generator's nested visitor helpers. | [Operations](classes/operations.svg) |
| Examples | Custom policy and measurement example. | [Examples](classes/examples.svg) |
| Verification | Production test adapters, fault injector, supplied test classes and independent check fixtures. | [Verification](classes/verification.svg) |

Grey boundary boxes in subsystem views reference types defined elsewhere. They do not represent duplicate implementations. The full diagram groups definitions by responsibility; source paths disambiguate classes with identical names.

## Reading the notation

| Notation | Meaning in these diagrams |
| --- | --- |
| Solid line with an open triangle at the base | Declared inheritance (`extends` or a Python base class). |
| Dashed line with an open triangle at the contract | Declared TypeScript `implements`, or a reviewed structural implementation. The latter is labelled **«structural»**. |
| Filled diamond at the owner | Composition: the owner creates/contains the component and controls its lifetime. |
| Hollow diamond at the referring object | Aggregation: an injected or potentially shared collaborator. Read the note for lifetime details. |
| Solid arrow | Association: a retained reference or relationship without exclusive ownership. |
| Dashed arrow | Dependency: creates, returns, calls, or otherwise uses a type. |
| `1`, `0..1`, `*` | Required single, optional single, or multiple target references per source instance. Inverse uniqueness is not asserted. Dependencies and inheritance do not carry cardinalities. |
| `+`, `#`, `−` | Public, protected/underscore convention, private. Python's convention is not an access-control guarantee. |
| `?`, `{readOnly}`, `{static}` | Optional, readonly and static declarations. Full signatures/modifiers are available in the inspector. |
| **«protocol»**, **«interface»**, **«dataclass»** | Type/contract declarations, distinguished from ordinary implementation classes. |

The diagram keeps the semantic boundaries explicit:

- `Agent` retains `AgentIdentity`; `HumanState` and `ZombieState` inherit `AgentState`. Conversion replaces the current immutable state while historical evidence retains the previous value.
- Eight role classes inherit through Human/Zombie role branches. `RoleAssignment` references a shared immutable definition; consumable Spitter charges belong to the individual assignment.
- `ActionIntent`, `ActionOccurrence`, `DomainEvent` and `ScheduledTask` are separate concepts. An admitted durative action is not an Event subclass; queue bookkeeping is not automatically a game event.
- `GameRuleSet` calculates in a `PlanningSession` with an isolated `WorldDraft` and runtime fork. It receives no storage or publication capability.
- `StateCoordinator` retains the committed `WorldAggregate`. `UnitOfWork` validates a proposed successor and publishes it only after the persistence port confirms the atomic transaction.
- `ScheduledBoundary` retains the prior runtime owner while the scheduler prepares a due task. Failure before publication restores its heap, exact time and preparation anchors.
- Immutable domain values and persistent indexes may be structurally shared. Association edges avoid asserting an exclusive object lifetime for shared values.
- Equal `ProfileValues` may share one immutable instance through bounded decoding caches. Numeric wire types, signed zero and supplied fields remain distinct; per-agent state and role charges are never part of that cache.
- `RuntimeSnapshot` shares immutable continuation cells. Built-in trees use copy-on-write branches; richer private Python graphs use per-agent opaque copies that preserve types and aliases without copying every agent's unread memory.
- Persistence ports separate world ownership from backend details. `InMemoryHistory` is an independent contract implementation; SQLite access belongs to persistence adapters.
- Existing SDK views in `entities.py` remain detached plugin-facing values. They are distinct from authoritative `domain_model` classes, and source paths disambiguate equal names.
- Execution compatibility services remain visible in the complete inventory. Removed mutation extension points raise explicit migration errors; `game_rules` contains the active semantic implementation.
- React functions, pure numerical helpers and serialization functions remain functions. The atlas does not invent classes for them.

## React integration

The GUI's React components and hooks are functions, as requested during the OOP refactor. They are therefore not represented as classes. Their class integration is:

| Functional entrypoint | Objects it constructs/uses |
| --- | --- |
| `views/Workspace.tsx` | `RunCatalog`, `ViewSession`, `ExecutionSession` |
| `views/Configuration.tsx` | `ConfigurationEditor` |
| `views/World.tsx` | `WorldRenderer` |
| `CommandDialog.tsx` | `CommandSession` |
| `ExportDialog.tsx` | `ExportSession` |
| `PopulationChart.tsx` | `PlotlyHost`, `PopulationPresenter` |
| `ComparisonChart.tsx` | `PlotlyHost`, `ComparisonPresenter` |
| Four reader hooks | Corresponding `QueryReader` subclasses |
| `uiRuntime.ts` | Shared `ApiClient`; controllers receive transport functions where appropriate |

Arrow-function class properties such as `ConfigurationEditor.action` and `ExecutionSession.execute` are included as operations. Pure functions and TypeScript type aliases remain visible in the [architecture code index](architecture/code-index.html), not as invented class boxes.

## Coverage and regeneration

[coverage.json](classes/coverage.json) records the source roots, counts and diagram coverage. [class-model.json](classes/class-model.json) records source hashes, full declared members, nested qualified names, and every relationship. [relationships.json](classes/relationships.json) is the maintained inventory of reviewed relationships with file/line evidence and ownership notes.

The scan covers maintained source under `src/zombie_sim`, `gui/src`, `scripts`, `examples`, `tests`, `implementation_checks` and ontology build/validation scripts, plus Python GUI harnesses. It excludes installed environments, third-party libraries, generated bundles and historical artifacts. External base classes are references only. Arbitrary classes created dynamically with `type(...)` and dynamically attached attributes cannot be exhaustively inferred from declarations; the atlas does not fabricate them. Dataclass-generated methods are implicit in the **«dataclass»** label.

To regenerate from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python scripts/build_class_diagrams.py
```

Generation uses the existing Node/TypeScript installation and Graphviz `dot`. It parses source without importing the simulation or starting workers. When changing object ownership, update `relationships.json` along with the code; inheritance and member lists regenerate automatically.

For execution flow and process boundaries alongside these class relationships, use the [architecture atlas](architecture/index.html) and [architecture guide](ARCHITECTURE.md).
