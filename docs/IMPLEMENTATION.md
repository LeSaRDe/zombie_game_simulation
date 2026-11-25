# TASK 2 implementation and verification

Implemented on 2026-11-25 from the ontology and the reviewed TASK 2 plan. The
current instruction in `prompts/zombie_game_plans.md` authorizes implementation
and prohibits consulting the supplied acceptance suite. No acceptance-suite
contents were opened, imported, discovered through a test runner, or executed.
An early repository inventory exposed only the name of its README; this was
disclosed during implementation. Independent checks below were written directly
from the specifications and implementation contracts.

## Architecture

| Component | Implementation and responsibility |
| --- | --- |
| Specification registry | `registry.py` verifies immutable ontology/catalog data, eight roles and all 29 actions. Source and semantic configuration digests are retained. |
| Configuration | `config.py` resolves TOML/JSON, imports baseline geometry/resources, validates bounds and populations, initializes identities and records placement provenance. |
| State and geometry | `domain.py` derives type/role/effect profiles; `geometry.py` implements closed-footprint intersections and routing. Observations clip visible barrier surfaces at sensing and occlusion boundaries. |
| Scheduler | `engine.py` advances a rational event clock, applies phase precedence, seeded arbitration, biological timers and continuous motion/rest/hunger. One coordinator publishes each atomic transition. |
| Actions | `actions.py` implements admission, reservations, resolution-time revalidation, effects, cancellation and cooldowns for all 29 actions. Coupled lifecycle changes and action evidence share an atomic revision. |
| Models | `policies.py` implements local candidate generation, bounded memory, seeded choices and interchangeable model assignments. Observations do not expose global state or other agents' private memory. |
| Parallel execution | `parallel.py` supplies conflict components, process inference, continuous materialization and verified independent deterministic effects. Mixed unsupported frontiers execute serially; see `PARALLEL.md`. |
| Persistence | `storage.py` implements memory and SQLite live stores, incremental durable history, exact-time/revision replay and integrity checks. `runtime.py` journals pending events, counters and private memory in the same transaction. |
| Application | `application.py` manages separate run processes, leases, durable commands, recovery, interventions and historical branches. `cli.py` exposes the same simulation/history services. |
| Learning | `learning.py` provides Gymnasium/AEC adapters, imitation, recurrent PPO, elapsed-time rewards, checkpoint reload and held-out evaluation. |
| Visualization | `server.py` and the built `gui/` workspace provide configuration, live/replay views, linked inspection, cohorts, comparisons and exports. `visualization.py` projects committed history without running policies. |
| Ontology export | `ontology_export.py` exports actual states, action boundaries and lifecycle records for validation against the original SHACL rules. Conflicting evidence is rejected rather than assigned invented revisions. |

The library's public entry point is `zombie_sim.Simulation`. Useful methods include
`advance_until`, `step`, `observe`, `snapshot`, `submit_intents`, `intervene`,
`checkpoint`, `restore`, `restore_revision`, `branch` and `close`. `return_snapshot=False`
avoids copying a complete researcher view during headless advancement.

## Verified behavior

| Check | Observed result and evidence |
| --- | --- |
| Domain and initialization | Baseline geometry/resource totals, roles, profiles and strict placement constraints pass `implementation_checks/domain_check.py`. |
| All 29 actions | `implementation_checks/actions_check.py` exercises public admission/resolution, scarce reservations, reciprocal attacks, failed preconditions, construction visibility and lifecycle cancellation. |
| Ontology conformance | **35 actual engine traces** conform to original SHACL, including every action, conversion, exact-deadline treatment, model batch ordering and lethal damage during a wait. `diagnostics/rdf/manifest.json` records each trace and report. |
| Event clock and lifecycle | Exact treatment deadline, idle starvation, all due events at the horizon, busy fractional-time restart, and memory/SQLite/two-worker equivalence pass `implementation_checks/engine_check.py`. A separate long-advance check verified intermediate automatic checkpoints and restoration after completion. |
| Arbitrary-revision restart | `implementation_checks/runtime_check.py` reproduces world, events, private memory, decisions, draws and queue from historical revisions; verifies branch seed/lineage, corruption rejection and parent-prefix protection. |
| Parallel effects | Workers 1/2/4 produce equal semantic histories and states for independent healing effects. A deliberately stale worker fingerprint falls back to serial calculation with identical results. `artifacts/model_checks/effect_parallel.json`. |
| Hard crashes and controls | `gui/verify_recovery.py` passes 12 before/after-commit process exits across memory/SQLite and step/timestamp/advance. `gui/verify_manager.py` verifies lost acknowledgement reconciliation, historical branching, worker termination and restart. |
| CLI/API | Real run, replay, resume, branch, intervention, metrics, exports and process control exercised through the CLI and listening HTTP service. See `APPLICATION_VALIDATION.md` and `gui/verify_api.py`. |
| Learning | Corrected smoke run completed **4,096 decisions and 96 PPO updates**; weights changed and reloaded. The saved policy ran through ordinary engine assignment. Gym/AEC checks cover conversion, unequal elapsed durations, terminal rewards, truncation and candidate masks. |
| Formal package | The original formal validation command passes **62/62** after the explicit D8 plan-reference refresh. Game-rule files are unchanged. |
| Installable distribution | `artifacts/distributions/zombie_sim-0.1.0-py3-none-any.whl` contains 28 source/data files byte-matching the final workspace. An isolated installation passed core simulation, bundled 29-action/eight-role registry and HTML/JavaScript/CSS resource checks. The installed CLI also validated and initialized the small scenario. |

The corrected learning report is `artifacts/training/smoke_final/report.json`; the
deployable artifact is `artifacts/training/smoke_final/selected`. Each of utility,
random, imitation and PPO survived the full 60 seconds on all 30 held-out seeds,
with mean raw reward 0.6. This easy task validates the pipeline and does not
demonstrate PPO superiority or a useful learned strategy at baseline scale.

Browser and frontend build evidence is maintained in `APPLICATION_VALIDATION.md`.
That record distinguishes actual rendered-browser checks from source inspection,
API checks and unmeasured browser performance requirements.

## Measured execution

| Measurement | Small scenario | Full-population pilot |
| --- | ---: | ---: |
| Agents | 24 | 1,000 |
| Simulated duration | 120 s, completed horizon | 5 s of a 1,800 s horizon |
| Initialization | 0.11 s | 6.93 s |
| Execution | 20.21 s | 29.38 s |
| Decisions | 1,055 | 2,404 |
| Recorded events | 5,275 | 8,160 |
| History database | 16.28 MB | 19.22 MB |
| Peak resident memory | 213.48 MiB | 356.95 MB |

Both runs used one worker and the memory live backend with durable SQLite history.
The small run used Python 3.14.4; the baseline pilot used Python 3.12.3 on the same
Linux development host. Timing includes ordinary persistence; the small run also
includes its scheduled checkpoints. Hardware, configuration fingerprints and
sampler records are in `artifacts/benchmarks/small_120/summary.json` and
`artifacts/benchmarks/baseline_1000_5s.json`.

The small scenario ended with 14 healthy humans, no infected humans, seven living
zombies and three dead identities, preserving 24 identities. Its final checkpoint
took 0.87 seconds and occupied 6.69 MB; reconstructing its midpoint from history
took 0.052 seconds. These are individual measurements, not stable latency bounds.

The approved baseline sampler kept all 1,000 agents and strict geometry/separation
constraints. It records its approximate conditional relocation distribution and
does not claim exact joint sampling. No full **1,000-agent / 1,800-second** run has
been validated. The first-five-second rate would linearly project to about three
hours and 6.9 GB of ledger data; longer runs change interaction density and anchor
costs, so that extrapolation is not a capacity guarantee. Current in-process
semantic collections grow with history, making bounded-memory archival an
important next optimization before large batches.

## Reproduce independent verification

From the repository root, install the relevant optional dependencies, then run
the explicit implementation checks individually. These commands do not discover
or execute the supplied acceptance suite:

```bash
PYTHONPATH=src python implementation_checks/domain_check.py
PYTHONPATH=src python implementation_checks/actions_check.py
PYTHONPATH=src python implementation_checks/engine_check.py
PYTHONPATH=src python implementation_checks/runtime_check.py
PYTHONPATH=src python implementation_checks/models_check.py
PYTHONPATH=src python implementation_checks/effect_parallel_check.py
PYTHONPATH=src python implementation_checks/learning_check.py
PYTHONPATH=src python implementation_checks/rdf_check.py
PYTHONPATH=src python gui/verify_recovery.py
PYTHONPATH=src python gui/verify_manager.py
```

The RDF check requires the ontology extra; the learning check requires the learning
extra. The existing formal package has its own documented Python/JDK dependencies
and verification entry point. `scripts/benchmark.py` runs a declared scenario and
records wall time, memory, checkpoint size and replay latency in a fresh directory.

## Provenance and practical limits

D8 maintenance preserved the original manifest, checksums, reports and release
archive in `ontology/formal_v0.1/provenance/before-task2-57e073fe0f18/`. Only the
manifest's plan hash was refreshed; the ontology Markdown, Turtle, RDF/XML,
catalog, baseline and SHACL rules remain byte-identical. The existing validator
and packaging workflow produced fresh reports and checksums for the current
reference. `scripts/refresh_ontology_provenance.py` records this maintenance.

Parallel effect support is conservative and covers five deterministic effect
families. Other effects remain correct serial coordinator work; no universal
speedup is claimed. SQLite supports a local single writer per run. The GUI is a
local research workspace, with portable HTML animation export rather than an
encoded video renderer. Sustained frame rate, 10,000-agent rendering, Firefox
coverage and the full-duration baseline remain unverified performance targets.

Passing these independent checks does not establish that the untouched acceptance
suite passes. That suite remains available for a separate validation stage under
the user's instruction.
