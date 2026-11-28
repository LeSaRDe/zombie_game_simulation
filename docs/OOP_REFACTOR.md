# OOP refactor: scope, compatibility and verification

This implements the request to refactor the complete framework around object-oriented architecture and provide a comprehensive implementation diagram. The user selected functional React views backed by composable objects. This architectural change does not change the ontology or the approved simulation mechanics.

The [architecture guide](ARCHITECTURE.md), [interactive diagram atlas](architecture/index.html), [code index](architecture/code-index.html), and [runnable modeling example](../examples/oop_custom_model.py) are the main entrypoints for reviewing and extending the result.

## Implementation map

| Area | Before | Implemented structure |
| --- | --- | --- |
| Engine | Large `Simulation` with mixed responsibilities and action mixin | Stable façade over 11 actual behavioral services, explicit context protocols and injectable service factory. |
| Canonical domain | Dictionary helpers with implicit interfaces | `AgentFactory`, typed immutable views, exact cursors, intent/decision objects and structural public protocols. Existing serialized records retained. |
| Ontology | Module-global parsing and catalog setup | `OntologyCatalog` owns loading, validation and provenance; compatibility constants use a default catalog. |
| Modeling | Existing policy classes with procedural registration | `ObjectDecisionModel` adapter, memory codecs, `ModelRegistry`, `ModelCatalog`, `ScenarioBuilder`, `SimulationFramework`, `Experiment`. |
| Persistence | Existing stores/history classes plus procedural runtime | Store/history classes retained; `RuntimeService` owns actual checkpoint/journal/restore/branch algorithms. |
| Managed execution | Large manager plus a procedural worker loop | `RunRepository`, `WorkerSupervisor`, `RunWorker`, `HistoryQueryService`, coordinated by `RunManager`. |
| Configuration | Procedural resolution, validation and encoding | `ConfigurationService` and `ConfigurationCodec` own algorithms and dependencies. |
| HTTP | Route closures owning shared behavior | `WorkspaceHTTPApplication`, explicit HTTP controllers and per-socket `LiveViewSession`. |
| Readers and analysis | Function dispatch and global caches | `ReadOperationRegistry`, instance-owned analysis/cache services and custom measurement strategies. |
| Exports | Format branches and shared functions | `ExportService`, `ExportRendererRegistry` and six concrete format strategies behind `ExportJobs`. |
| Commands and shutdown | Mixed helpers and existing shutdown class | `ScriptCommandService`, `CommandReceiptService`, explicit `WorkspaceServices` resource lifecycle and existing `ShutdownCoordinator`. |
| CLI and learning | Procedural CLI and training orchestration | `SimulationCLI`, `HeadlessRunController`, `TrainingPipeline`, `EvaluationPipeline`, injectable `LearningBackend`. |
| GUI | Large entry module with embedded effects and workflows | Functional extracted views, typed controllers/readers/sessions, Canvas renderer and Plotly presenters. |
| Fault testing | Global fault schedule | `FaultInjector` with isolated schedules and compatible default hooks. |

Pure algorithms and thin compatibility/process entrypoints remain functions. This avoids artificial classes without owned state or replaceable behavior. The old `policies.py` and `learning.py` already contain model/environment classes and are deliberately byte-identical because historical checkpoint pins hash their entire source files.

## Compatibility commitments

- Preserve ontology specifications and supplied acceptance definitions.
- Preserve existing APIs, record schemas, exact time/revision handling, RNG/event order, model assignment and privacy rules.
- Preserve old default-wiring checkpoints and journals without migration.
- Keep service objects out of serialized state; recreate them lazily during constructor-free restore.
- Record nondefault core bindings and reject mismatched exact restoration. Custom core bindings currently require one worker.
- Keep all historical run data. Verification uses disposable workspaces and the retained pre-refactor package under `artifacts/oop-refactor/baseline-package`.
- Preserve GUI test interfaces and exact-value metadata; browser helper adjustments only open the pre-existing exact-value disclosure before entering a value.

## Verification evidence

The current consolidated result is [verification.json](../artifacts/oop-refactor/verification.json). Independent checks and the retained source snapshot live under [artifacts/oop-refactor](../artifacts/oop-refactor/).

**Final result: 538 of the 539 supplied acceptance cases were executed and passed.**
The one unexecuted case is the full 1,000-agent, 1,800-second baseline described below.
The final GUI passed TypeScript compilation, production packaging, ten controller
checks and the detailed Chromium/Firefox editor and exact-time regressions.
The offline wheel passed a clean Python 3.12 installation with all 75 packaged
files verified, both storage backends, custom-model memory and old-checkpoint continuation.

| Verification | Evidence |
| --- | --- |
| Full supplied core acceptance | `core-acceptance.json`: 489 cases. |
| Old/new execution and old checkpoint continuation | `core-verification.json`: scripted/model × memory/SQLite × 1/2 workers; full state, events, decisions, draws and runtime attributes. Only physical history paths are excluded from comparison. |
| Real parallel deterministic effects | Existing effect checks compare 1/2/4 workers and stale-proposal serial fallback. |
| Public OOP modeling API | `sdk-checks.json`: nine checks covering immutability, exact cursors, real custom model/memory codec, inherited implementation pin rejection, checkpoint continuation, measurements and injected training/evaluation. |
| Application/service parity and injection | `services-verification.json`: retained-source config/analysis/export byte equivalence, reader registry, caches, exports, live-view races and resource lifetimes. |
| Catalog/fault ownership | `registry-fault-checks.json`: isolated catalog/fault state, metadata behavior and actual transaction failure/retry. |
| Formal and integration acceptance | Population accounting, policy witness bank, all-action encoder roundtrips, actual treatment/conversion/death SHACL traces. |
| Statistical and training acceptance | Fixed-seed trials; training/reload/split checks. |
| GUI acceptance and rendering | `browser-acceptance.json`, `performance-acceptance.json`; final build plus controller and real-browser checks. |
| Exact-time GUI regression | `i27-chromium-complete/verification.json`, `i27-firefox-complete/verification.json`; mixed editor checks are in `editor-*-verified/verification.json`. |
| CLI, launcher and service shutdown | `cli-lifecycle.json`, `service-lifecycle.log`: save/resume/terminate/shutdown, interruption, receipts, process cleanup and full-population initialization. |
| Actual OOP learning pipelines | `training-pipeline/report.json`, `training-pipeline/evaluation-pipeline.json`: eight real training decisions, changed PPO weights, reload and independent evaluation through the new pipeline objects. |
| Isolated installed distribution | `distribution/wheel_verification.json`, `distribution/isolated_sdk.json`; every source/install/RECORD byte and authoritative bundled ontology checked. |

This refactor does **not** claim a newly completed 1,000-agent, 1,800-second baseline trajectory or a new long-duration throughput result. The complete historical baseline remains separate evidence. GUI rendering benchmarks and full-population initialization are not simulation-throughput measurements.

Regression work found and corrected extraction errors in TOML codec qualification, a worker checkpoint call, browser `fetch` receiver binding, and a configuration-editor constructor default. Earlier failed runs are retained where recorded; only the final passing runs support the final verification claim. Two older standalone implementation harnesses have stale fake-manager interfaces and fail identically against the retained original package; real-manager export and explicit live-view tests cover those behaviors without changing supplied acceptance fixtures.

The rendering benchmark initially dragged outside the viewport. A before/after
comparison proved that the original and refactored layouts had identical canvas
geometry. The adapter now scrolls the actual canvas into view before panning;
all timing assertions and thresholds are unchanged. Final measured results were
60.00 FPS for 1,000 agents and 55.14 FPS for 10,000 agents, with input p95 of
5.2 ms and 29.5 ms respectively. These are single-host measurements of rendering,
not long-run simulation throughput. See `layout-comparison/layout.json` and
`performance-measurements.json` for the comparison and raw measurement summaries.

To reproduce the main checks:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python -m tests.run_acceptance --adapter zombie_sim.testing:create_adapter --tier core --report artifacts/oop-refactor/core-acceptance.json
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python implementation_checks/oop_sdk_check.py
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python implementation_checks/oop_core_check.py
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python implementation_checks/oop_services_check.py
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python implementation_checks/oop_registry_fault_check.py
```

Browser checks need the existing local browsers and permission to launch disposable local services. The training tier uses the existing `.venv-training` environment. The architecture generator needs Graphviz; the resulting atlas is standalone.
