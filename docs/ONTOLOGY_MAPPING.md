# Ontology mapping and provenance

The authoritative game rules are `ontology/zombie_game_ontology_v0.1.md`, version 0.1. The original formal package is preserved. Its previous validation report is historical evidence: the current requirements file no longer matches the plan digest pinned in `manifest.json`. Every resolved configuration stores current source hashes, the manifest comparison, and registry membership. No historical PASS is presented as validation of changed requirements.

## Executable inputs

`src/zombie_sim/registry.py` imports the action and role facts from the original RDF/XML. It compares every imported action/role property with `catalog.ttl` on import and checks exact action/role set equality with the manifest. This supplies all 29 actions and all eight roles, including duration bounds, stamina, cooldown, reach, grants, and numeric role properties. A disagreement raises an error rather than choosing a source silently.

`baseline_config()` imports `baseline.ttl` directly, including allocations, four shelters, 28 barriers, ten stockpiles, scenario timing, and seed. The narrow stdlib Turtle importer accepts the grammar present in these published named-node files and rejects unsupported syntax. It is not advertised as a general RDF parser. Optional RDF validation uses actual rdflib and pyshacl.

Type defaults absent from the catalog are explicitly encoded in `domain.TYPE_PROFILES`, directly corresponding to Markdown sections 4 and 5. Profile precedence is type defaults, configured type overrides, the single catalog role, configured role overrides, explicit agent overrides, and then applicable temporary effects. Death forces speed and sensing to zero. Effects are half-open and use the strongest applicable value. Derived status, speed, sensing, resistance, progress, and inventory mass are calculated from canonical facts.

## Runtime fields

| Runtime value | Original RDF representation | Source |
|---|---|---|
| Agent dictionary key and `id` | persistent Agent, `agent_id`, `inRun` | §2.2, §4 |
| Agent snapshot at time/revision | AgentState, HumanState or ZombieState, `ofAgent`, `atTime`, `revision` | §2.1, §4 |
| `type` | `biologicalType`, `hasTypeProfile` | §4 |
| `role` | `activeRole` → RoleAssignment → `roleDefinition` | §7 |
| `model_assignment` | `activeModel` → ModelAssignment → DecisionModel | §8 |
| `last_state_event_id` | `lastEvent` | §4, §16 |
| `infection_episode` | `activeEpisode` → InfectionEpisode | §6 |
| Episode `agent_id` / `outcome` | `infectedAgent` / `episodeOutcome` | §6.2 |
| No closed outcome yet | `ONGOING` | §6.2 |
| Dead action status | `ACTION_DEAD` (distinct from biological status `DEAD`) | §4 |
| Human `inventory` and `reserved` | Inventory plus separate ResourceStock records | §3.3, §5.1 |
| Ground `inventory` and `reserved` | StockpileState plus ResourceStock records | §3.3 |
| Barrier `footprint=[xmin,ymin,xmax,ymax]` | EnvironmentState → Rectangle | §3 |
| Gate `mode` | `gateMode` | §3.2 |
| Agent `cooldowns` | Cooldown records with `forAction` and `until` | §9 |
| Agent `effects` | TimedEffect records with recipient, source, magnitude, interval | §4.1 |
| `remains` | Remains plus immutable RemainsState observations | §3.2, §6.5 |
| Lifecycle event before/after snapshots | LifecycleTransition and subtype, `beforeState` / `afterState` | §6 |
| Recorded occurrence admission/resolution boundaries | ActionOccurrence, `actorStart`, `actorAfterStart`, `actorBeforeEnd`, `actorAfterEnd`, corresponding target states | §9–13 |
| Intent and captured admission self-state | ActionIntent → Observation → `selfState`; this is not an invented full policy observation | §8–9 |
| Event `causes` | Event `cause` edges referring to actual ledger IDs | §16 |

Each export state and resource observation has an identity containing time and revision. An episode's final outcome is retained with its onset and end revisions; earlier infected states therefore remain valid. An exporter never loads or copies the original example graphs as simulator output. Arbitrary string runtime IDs cannot be mislabeled as valid ontology integer IDs: RDF export requires positive integer agent IDs.

The event clock is exact rational in the simulator/history. RDF `xsd:decimal` fields are projections at 60 digits of precision where a rational has a recurring decimal expansion. This representation choice does not change scheduling. The supplied infection-progress SHACL tolerance is 1e-9.

## Actions

All numeric values below come from the RDF catalog. Admission, completion, costs, cancellation, and effects are enforced by the engine; policy selection does not define game mechanics.

| Action | Eligibility | Markdown contract |
|---|---|---|
| move | Both types | §10 |
| wait | Both types | §10 |
| rest | Both types | §10 |
| signal | Both types | §10 |
| melee | Human | §11 |
| pickup | Human | §11 |
| drop | Human | §11 |
| transfer | Human | §11 |
| eat | Human | §11 |
| first_aid | Human | §11 |
| open_gate | Human | §11 |
| close_gate | Human | §11 |
| claw | Zombie | §12 |
| bite | Zombie | §12 |
| feed | Zombie | §12 |
| smash | Zombie | §12 |
| treat_infection | Doctor | §13.1 |
| prophylaxis | Doctor | §13.1 |
| power_strike | Warrior | §13.2 |
| guard | Warrior | §13.2 |
| recon | Scout | §13.3 |
| mark_target | Scout | §13.3 |
| build_barricade | Engineer | §13.4 |
| repair_barrier | Engineer | §13.4 |
| rally | Tyrant | §13.5 |
| demolish | Tyrant | §13.5 |
| dash | Runner | §13.6 |
| spit | Spitter | §13.7 |
| scream | Screamer | §13.8 |

## Invariants and implementation responsibilities

This table identifies the code responsible for each semantic requirement. It does not claim that mapping alone proves behavior.

| Invariant | Responsibility |
|---|---|
| V01 Identity and references | Config entity uniqueness/reference validation; engine persistent identities; revision-keyed export |
| V02 Bounds and geometry | Config finite domains, rectangle validation; geometry closed-point/segment predicates; engine trajectories |
| V03 Matching type/status/life | `domain.status`; config type/life domains; engine lifecycle |
| V04 Terminal death | Engine death reducer and admission checks; derived status; SHACL death traces |
| V05 Active infection ownership | Initialization episode construction; engine infection/cure/conversion/death reducers; export episode links |
| V06 Episode clocks and closure | Positive incubation validation; exact engine deadlines; revision-preserving episode export |
| V07 Conversion preserves identity | Engine atomic conversion and drops; type-specific state; SHACL conversion traces |
| V08 Roles and model assignment | Config role compatibility and model presence; engine assignment retirement/replacement |
| V09 Action capabilities | RDF-imported type/role grants; `domain.capabilities`; engine contract checks |
| V10 One action, duration, cooldown | Catalog durations; engine occurrence admission/resolution and cancellation |
| V11 Hunger/stamina clocks | Config domains; engine analytic evolution and starvation scheduling |
| V12 Inventory mass/conservation | Config quantities/capacity; engine transfer/consume/drop transactions; state-specific ResourceStock export |
| V13 Reservations | Config initial-state rejection; engine atomic reservations and release |
| V14 Legal continuous movement | Geometry full segment predicates; engine path timing, costs, and geometry changes |
| V15 Local observation/privacy | Engine observation builder; policies receive observation and memory only |
| V16 Recorded stochastic outcomes | Engine named deterministic draws and event records |
| V17 Damage/healing limits | Engine half-up integer damage, resistance, and life clamps |
| V18 Lethal precedence | Engine death before exposure; existing episode exclusion |
| V19 Reciprocal attacks | Engine overlapping occurrence arbitration and cancellation |
| V20 Gates/construction | Config mode/integrity, overlap/enclosure checks; engine occupancy checks |
| V21 Remains | Engine single death-created remains, reservation/consumption; exported source identity |
| V22 Clock independence | Exact engine scheduler, continuous evaluations, exclusive effect endpoints |
| V23 Initial scenario | RDF baseline import; geometry connectivity, exact/declared sampling, counts, resources |
| V24 History and causality | Atomic engine commits; append-only ledger; exported causal event references |
| V25 Derived facts | `domain.profile`, `status`, capability functions; rejection of independently configured derived fields |

## Placement and D5

`configs/baseline_exact.toml` requests exact joint rejection sampling. Each candidate begins with independent uniform draws from type-legal static space. Any pairwise failure rejects the whole candidate; no earlier position is retained. Exhausting the finite attempt budget is a failure to find a sample, not proof of infeasibility, and does not trigger a fallback.

`configs/baseline_relocation_opt_in.toml` is an explicitly experimental opt-in configuration. Its `allow_approximate=true` acknowledges randomized sequential initialization followed by finite conditional relocation sweeps. Uniform coordinate proposals and exact pairwise constraints preserve legal geometry; finite sweeps do not guarantee mixing or joint uniformity. Metadata records sampler version, proposals, sweep count, acceptance rate, explicit opt-in, and lack of a mixing guarantee. The user explicitly approved D5 on 2026-11-25. `baseline_config()` and `configs/baseline.toml` now use this sampler and record the approval decision/date; the statistical approximation and lack of a mixing guarantee remain visible.

The exact small configuration includes all eight roles and is practical without that approximation. Configuration resolution never silently scales geometry, reduces population, weakens separation, or approves an approximation.

## Verification evidence and limitations

`implementation_checks/domain_check.py` is independently written from the ontology. It verifies registry membership/source identity, closed boundary/tangent collision behavior, routing, profile precedence/effect intervals, deterministic exact placement, baseline geometry/counts/resource totals/connectivity, rejection diagnostics, sampler exhaustion, and export of actual initialized state. It neither imports nor executes the supplied acceptance suite.

A realized 24-agent initial snapshot from `configs/small.toml` (all eight roles, one infection episode, carried and ground resources) was exported and conformed to the original SHACL shapes using rdflib/pyshacl. This is snapshot evidence, not proof of all action semantics.

`implementation_checks/actions_check.py` independently exercises public admission and completion for all 29 actions, resource contention, winning reciprocal misses, invalid-first reciprocal attempts, deadline precedence, conversion reservation release and inventory drops, barrier collisions, information provenance, full-footprint visibility, and exact continuation during movement. `implementation_checks/rdf_check.py` generates actual simulation traces and validates them with the unchanged shapes. Its 35 realized traces cover every action plus death, conversion, conversion cancellation, treatment failure at the conversion deadline, model-driven reciprocal combat with atomic decision batches, and lethal damage cancelling an ongoing nonattack action. All 35 conformed in the recorded run; the TTL, actual validation reports, source provenance and file hashes are in `diagnostics/rdf/manifest.json` and its adjacent artifacts. These checks do not import or consult the supplied acceptance suite.

The exporter uses recorded admission and completion states, including reserved inventory, and real lifecycle subevents. Environment targets retain their actual admission snapshot. Missing event metadata remains an error visible to SHACL; conflicting records with the same agent/time/revision are rejected rather than assigned invented intermediate revisions. Source-event links from an occurrence resolve to its actual ledger result event. Integer-valued RDF decimals retain their decimal lexical form because the original role-override constraint compares RDF literal terms.

`validate_export` uses the original baseline validation profile. Custom profile/action parameters need a separately versioned parameterized conformance profile before their overrides can be claimed to pass those baseline-specific constraints. Failing original constraints are not suppressed. Busy-state and action-transition validation requires the real occurrence admission/completion evidence; an incomplete trace remains visibly incomplete to SHACL. Event source references require actual event metadata. The exporter does not invent historical events or use source examples to make an incomplete run pass.

## Exact continuation and read projections

`runtime.py` serializes the coordinator's raw state, exact Fraction queue and clocks, stable counters, pending decision set, model memories, occurrence/intents references, recorded decisions/draws, and configuration using explicit tagged JSON. It excludes live connections, thread/process pools, and temporary-directory handles. Restore bypasses initialization, so it never resamples agents or repeats admission costs. Runtime and state checksums must agree with the selected durable ledger revision.

An explicit checkpoint writes a verified JSON envelope and a neighboring `.history.sqlite` sidecar containing the original history through that revision. Keep these files together. Restore without a destination makes an independent temporary continuation; continuing the original run requires its ledger as `history_path`. Branching copies the parent prefix, records lineage and the selected revision, creates a new run identity, and preserves agent IDs. A new seed affects subsequent draws; pending event arbitration priorities are inherited and this is recorded.

A continuation database newer than an explicit checkpoint is never overwritten. `restore_revision` instead reconstructs an arbitrary committed revision from the atomic runtime journal and the matching world journal. Each commit stores typed coordinator attributes, exact pending-queue changes, and changed model memories in the same SQLite transaction as the world delta and event records. Decision and random-draw histories are reconstructed from their actual ledger records. An uncommitted process-local batch contributes no durable revision. Legacy ledgers without this journal still require a matching explicit checkpoint; restoring one establishes a journal from that available boundary forward.

The default revision restore copies a verified prefix into an independent temporary ledger. Continuing a live ledger requires an explicit matching destination; restoring an older revision never truncates newer history. Branches copy the selected prefix, remove inherited pending application commands, commit their own seed/identity/lineage and continuation kernel together, and retain the parent's stable agent IDs. Runtime anchors and deltas have independent checksums; corrupted continuation data is rejected even when the world ledger is valid.

`implementation_checks/runtime_check.py` verifies continuation from multiple early and late committed revisions of a real model run, including exact world facts, event IDs, model memories, decisions, draws and logical pending queue. It also covers fractional busy movement across memory and SQLite, branch seed/lineage restoration, rejection of overwriting a newer ledger, and runtime-checksum corruption. These checks are independently authored and do not consult the supplied acceptance suite.

`materialize_snapshot` evaluates hunger, rest, and movement from recorded anchors on a detached copy and computes effective profiles at the requested time. It performs no model decisions or random draws. Interpolation past a known unresolved action or biological deadline is rejected; a caller must choose the next committed state. Exact clock continuation was checked across memory and SQLite backends at rational times 1/3 and 2/3, including queue/events equality, checksum tampering, branch identity/fingerprints, and restoring an explicit checkpoint after closing its originating simulation.
