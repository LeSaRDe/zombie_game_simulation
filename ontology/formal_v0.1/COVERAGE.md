# Formalization coverage

The unchanged Markdown remains the semantic review baseline. This release supplies an OWL core, SHACL validation rules, and a baseline catalog. It is **not a complete formal behavioral specification**. Every action currently has PARTIAL coverage. Prose annotations are never counted as logical axioms or executable checks.

The detailed [coverage register](coverage.json) accounts for **402 substantive source lines**, all 25 listed invariants, all 29 actions, and each embedded SPARQL constraint. Source IDs use one-based line numbers in the SHA-256-pinned Markdown.

| Source section | Status | Represented aspects | Remaining obligations |
|---|---|---|---|
| 1 | DOCUMENTATION | Version, scope, notation and confirmed choices. | No executable semantics are claimed for introductory prose. |
| 2 | PARTIAL | Core classes, selected disjointness/relationships/cardinalities, state identity and references. | Not every conceptual relation has a complete closed-world shape; cross-run scope is checked for state/world and assignment ownership, not every possible reference. |
| 3 | PARTIAL | World dimensions, point bounds, rectangles, gate integrity/mode, resource stocks/holders, baseline connectivity. | Continuous paths, runtime line of sight, barrier occupancy and construction geometry, sound propagation and signal delivery are not completely formalized. |
| 4 | PARTIAL | Common numeric fields, typed references, identity uniqueness, state status, death cleanup, active actions, role overrides. | Effective-property aggregation, complete cooldown/effect maps and global event provenance are not exhaustively checked. |
| 5 | PARTIAL | Human/zombie numeric dictionaries, inventory capacity, resistance bounds, episode progress, presence of starvation timers. | Continuous hunger accumulation and scheduled damage, feeding recovery, Spitter recharge scheduling and all timer recurrence laws remain behavioral obligations. |
| 6 | PARTIAL | Legal type/status/life combinations, episode timing, cure/conversion/death transition fragments, preserved identity/life/location, no recorded resurrection. | Complete inventory-drop accounting, remains creation, all cancellations, model-memory resets, and stochastic transmission are not proved. |
| 7 | PARTIAL | Eight typed role definitions, profile domains, type compatibility, role capabilities, common overrides and OWL impossible-extension detection. | All role-assignment interval overlap/retirement consequences and future extension equivalence require additional checks. |
| 8 | PARTIAL | Observation self-state/time/observer links, model identifiers/versions, intent/actor relationships. | Visibility completeness, private-memory isolation, stale-message policy, the one-second decision bound, and fallback decisions are not validated. |
| 9 | PARTIAL | Admitted occurrence schema, positive planned durations, actor eligibility/capability, flat stamina, target presence/reach, outcomes, cooldowns and overlap checks. | Full item/charge reservation lifecycle for every action, visibility, every cancellation branch, and global atomicity remain outside complete coverage. |
| 10 | PARTIAL | All four common action definitions with baseline duration/cost/cooldown and possible-effect classification. | The move trajectory, actual-distance energy, rest integration, signal reception and continuous clocks require a behavioral formalism or additional trace validators. |
| 11 | PARTIAL | All eight human action definitions and their common typed admission/resolution fields. | Per-action combat, pickup/drop/transfer/eating/first-aid/gate state effects are not exhaustively checked by the generic occurrence constraints. |
| 12 | PARTIAL | All four base zombie action definitions, ranges and costs; infection-capable versus damage-only classification. | Hit/exposure probability semantics, damage arithmetic, feeding and barrier destruction are not fully checked. |
| 13 | PARTIAL | All thirteen role action definitions; detailed Doctor treatment resource/deadline/lifecycle checks. | Even treatment remains partial: visibility, all self-treatment/cancellation variants and complete frame conditions are not exhaustively checked. Other role-specific effects are metadata, not executable laws. |
| 14 | PARTIAL | Causal-cycle rejection, overlapping actor-action rejection, and exclusion of two resolved reciprocal attacks in supplied traces. | Global equal-time precedence, first-valid winner selection, fair seeded arbitration, parallel serializability and all resource races are not proved. |
| 15 | PARTIAL | Baseline population allocations, seed/horizon, 28 barrier rectangles, 10 stockpiles, resource totals and exact rectangular connectivity. | A 1,000-agent initial placement is not generated. Placement feasibility, statistical significance, model behavior and gameplay balance are not established. |
| 16 | PARTIAL | Run/scenario/model/observation/event/history vocabulary and selected causal/reference constraints. | Full replay sufficiency, restartable private memory, counterfactual coupling and scientific measurement validity need later design and verification. |
| 17 | PARTIAL | Expected-good and expected-bad examples, real HermiT/OWLAPI and pySHACL runs, targeted constraints and diagnostic reports. | Passing examples is finite evidence; it is not exhaustive testing or a proof of every listed invariant. |
| 18 | DOCUMENTATION | Requirements correspondence and review priorities are retained in source and this coverage map. | Review guidance is not an executable game rule. |

## Invariant correspondence

| Source ID | Checks / evidence | Remaining limits |
|---|---|---|
| V01 | UniqueAgentID | All other identity namespaces and cross-run links need broader coverage. |
| V02 | PositionBounds RectangleOrder | Continuous trajectories and dynamic obstacles are not covered in full. |
| V03 | StateStatus StateTypeFields AgentState_lifeShape | Snapshot checks are covered; complete evolution is not. |
| V04 | StateStatus DeadCleanup NoResurrection DeathTypes | Only represented states/transitions are checked; omitted future behavior is not proved. |
| V05 | StateStatus EpisodeOwnership | Global episode overlap/history completeness remains partial. |
| V06 | EpisodeDeadline EpisodeClosure EpisodeEndOrder CureEpisode ConversionDeadline | All host-death and duplicated lifecycle event cases are not exhaustively checked. |
| V07 | TransitionIdentity ConversionTypes ConversionPreserves ConversionDeadline | Inventory drops, cancellations and model-memory resets are gaps. |
| V08 | RoleCompatibility AliveAssignments ModelOwnership DeadCleanup | Assignments linked in snapshots are checked; full interval uniqueness is a gap. |
| V09 | ActionCapability RequiredTargets ActionAdmission | Complete contracts for all 29 actions are not enforced. |
| V10 | ActionState OneActionAtATime ActionDuration AdmissionCooldown ActionCooldown | General reservations and all interruption cases remain partial. |
| V11 | AgentState_staminaShape HumanState_hungerShape StarvationTimers | Rate integration and timer recurrence are gaps. |
| V12 | InventoryCapacity ReservationBound | Global transfer/consumption conservation remains a gap outside selected treatment checks. |
| V13 | ResourceStock_holderShape ReservationBound TreatmentReserve TreatmentConsume TreatmentFailureRelease | Nonmedical reservation release and charge/biomass lifecycles remain partial. |
| V14 | PositionBounds | Endpoint checks cannot prove path legality or speed at every instant. |
| V15 | ObservationSelf IntentAgreement | Sensing/occlusion/memory privacy and feasibility information leakage are gaps. |
| V16 | catalog probability parameter bounds | Actual random draws, sources, independence and their probability law are not validated. |
| V17 | AgentState_lifeShape TreatmentEffect CureStates | Physical damage and other healing arithmetic are not fully encoded. |
| V18 | StateStatus EpisodeOwnership | Lethal-hit ordering and reinfection transmission event laws remain a gap. |
| V19 | ReciprocalAttackExclusion | Winner arbitration and target-invalid ordering still require behavioral verification. |
| V20 | GateModeIntegrity GateStateIntegrity BarricadeStateIntegrity | Occupancy/construction race effects are not checked in full. |
| V21 | RemainsState_biomassShape BiomassReservation | Exactly one remains per death and biomass creation/consumption histories are not fully checked. |
| V22 | EpisodeDeadline InfectionProgress | Continuous clocks, equal-time phase ordering and selection-frequency independence are not proved. |
| V23 | baseline SHACL and independent RDF arithmetic/geometry checks | No complete initial agent placement or model execution is generated. |
| V24 | NoCausalCycle | Acyclicity is checked; completeness/replayability of the causal record is not proved. |
| V25 | StateStatus InfectionProgress RoleOverrides | All derived speed/sensing/effect/armor calculations are not yet checked. |

## Action contracts

All 29 named actions have structured definitions, capability links and possible-effect classifications in `catalog.ttl`. The common action shapes cover selected admission/timing/capability/reach/cooldown/overlap rules. Doctor treatment additionally has resource, deadline, cure and frame checks. These are finite-trace checks, not execution semantics.

The following still require a separate behavioral specification or additional validators: complete numerical effects for other actions; trajectory/occlusion geometry; all item/charge reservations; exact continuous clocks; all lifecycle side effects; seeded fairness/probability laws; observation privacy; and complete replay history. Choosing the behavioral formalism remains a later design decision. No Common Logic file or theorem-prover result is claimed in this release.

## Validation coverage

| SPARQL constraint | Dedicated expected-failure examples |
|---|---|
| ActionAdmission | treatment_dead_actor |
| ActionCapability | None yet; query parses and is included in conformance runs. |
| ActionCooldown | treatment_missing_cooldown |
| ActionDuration | treatment_invalid_duration |
| ActionRelease | None yet; query parses and is included in conformance runs. |
| ActionState | None yet; query parses and is included in conformance runs. |
| ActorEndIdentity | None yet; query parses and is included in conformance runs. |
| ActorResolutionAlive | None yet; query parses and is included in conformance runs. |
| ActorStartIdentity | None yet; query parses and is included in conformance runs. |
| AdmissionCooldown | None yet; query parses and is included in conformance runs. |
| AdmissionStamina | treatment_no_stamina_cost |
| AgentEndReach | None yet; query parses and is included in conformance runs. |
| AgentStartReach | treatment_out_of_reach |
| AliveAssignments | None yet; query parses and is included in conformance runs. |
| BarricadeStateIntegrity | None yet; query parses and is included in conformance runs. |
| BiomassReservation | None yet; query parses and is included in conformance runs. |
| ConversionDeadline | conversion_wrong_deadline |
| ConversionPreserves | conversion_heals |
| ConversionTypes | conversion_retains_role |
| CureEpisode | None yet; query parses and is included in conformance runs. |
| CureStates | None yet; query parses and is included in conformance runs. |
| DeadCleanup | None yet; query parses and is included in conformance runs. |
| DeadInventory | None yet; query parses and is included in conformance runs. |
| DeathTypes | None yet; query parses and is included in conformance runs. |
| DurationBounds | None yet; query parses and is included in conformance runs. |
| EpisodeClosure | None yet; query parses and is included in conformance runs. |
| EpisodeDeadline | None yet; query parses and is included in conformance runs. |
| EpisodeEndOrder | None yet; query parses and is included in conformance runs. |
| EpisodeOwnership | None yet; query parses and is included in conformance runs. |
| GateModeIntegrity | breached_gate_with_integrity |
| GateStateIntegrity | None yet; query parses and is included in conformance runs. |
| InfectionProgress | None yet; query parses and is included in conformance runs. |
| IntentAgreement | treatment_wrong_intent_actor |
| InventoryCapacity | inventory_over_capacity |
| LivingDeathMetadata | None yet; query parses and is included in conformance runs. |
| MissOnlyAttack | treatment_miss_invalid |
| ModelAssignmentInterval | None yet; query parses and is included in conformance runs. |
| ModelOwnership | None yet; query parses and is included in conformance runs. |
| NoCausalCycle | causal_cycle |
| NoResurrection | resurrection |
| ObservationSelf | None yet; query parses and is included in conformance runs. |
| OneActionAtATime | None yet; query parses and is included in conformance runs. |
| PositionBounds | position_outside_world |
| ReciprocalAttackExclusion | None yet; query parses and is included in conformance runs. |
| RectangleOrder | None yet; query parses and is included in conformance runs. |
| RequiredTargets | treatment_missing_target |
| ReservationBound | reservation_exceeds_stock |
| ResultTiming | None yet; query parses and is included in conformance runs. |
| RoleAssignmentInterval | None yet; query parses and is included in conformance runs. |
| RoleCompatibility | human_with_tyrant_role |
| RoleFieldApplicability | None yet; query parses and is included in conformance runs. |
| RoleOverrides | doctor_wrong_skill |
| StarvationTimers | None yet; query parses and is included in conformance runs. |
| StateIdentityRevision | None yet; query parses and is included in conformance runs. |
| StateStatus | dead_with_positive_life, infected_without_episode |
| StateTypeFields | None yet; query parses and is included in conformance runs. |
| StateWorld | None yet; query parses and is included in conformance runs. |
| TimedEffectInterval | None yet; query parses and is included in conformance runs. |
| TransitionIdentity | None yet; query parses and is included in conformance runs. |
| TreatmentConsume | treatment_free_supply |
| TreatmentCureRecord | treatment_missing_cure_record |
| TreatmentDeadline | treatment_at_deadline |
| TreatmentEffect | treatment_heals_life |
| TreatmentFailureRelease | None yet; query parses and is included in conformance runs. |
| TreatmentReserve | treatment_reservation_missing |
| TreatmentStartTarget | None yet; query parses and is included in conformance runs. |
| TreatmentSupplyEvidence | None yet; query parses and is included in conformance runs. |
| TreatmentTargetRecords | None yet; query parses and is included in conformance runs. |
| UniqueAgentID | duplicate_agent_id |
| UniqueInventoryResource | None yet; query parses and is included in conformance runs. |
