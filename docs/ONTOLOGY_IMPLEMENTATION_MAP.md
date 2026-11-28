# Ontology to implementation mapping

The deeper OOP architecture preserves the canonical Markdown, OWL/catalog, SHACL and baseline meanings. The only ontology package changes are approved provenance metadata and newly generated validation/release evidence. Full formal validation passed all 62 expectations; the [formal evidence](../artifacts/deep-oop-refactor/domain-formal-evidence.json) records hashes and validation output. This mapping identifies owners and existing independent cases; it does not claim that any finite test suite proves every possible execution.

## All 25 canonical invariants

The constraints below are copied from the repository-owned [ontology §17.1](../ontology/zombie_game_ontology_v0.1.md#171-semantic-validation-checklist). The complete independent case lists remain in [tests/coverage.json](../tests/coverage.json). Typed value validation, semantic rules and cross-entity transaction validation have distinct responsibilities.

| ID | Canonical requirement | Typed facts / boundary | Enforcing behavior | Representative independent cases |
| --- | --- | --- | --- | --- |
| V01 | IDs are unique within their run and are never reused. Every reference resolves in its declared scope. | AgentIdentity; WorldAggregate; validate_transition | StateCoordinator / UnitOfWork | `LIF_conversion_atomic_cleanup`, `LIF_worked_population_accounting_K` (17 mapped) |
| V02 | length and width are positive finite reals; all positions respect bounds, and living positions/path segments respect current barriers. | WorldBounds; Point; Rectangle | GeometryRules; MoveHandler; ConfigurationService | `ACT_close_gate_living_occupant_blocks_closure`, `ACT_build_barricade_cannot_enclose_nonempty_stockpile` (48 mapped) |
| V03 | Each agent has exactly one type, a valid matching status, and life in [0,100]. | AgentState; HumanState; ZombieState | AgentState.validate | `LIF_worked_population_accounting_K`, `VAL_life_domain_0` (42 mapped) |
| V04 | life = 0 iff status is DEAD. Death is terminal; a dead identity never acts, heals, converts, or revives. | Agent.with_state; AgentState | DeathRules; DamageRules; ActionLifecycle | `ACT_feed_success`, `ACT_move_reject_dead_actor` (73 mapped) |
| V05 | A living infected human has exactly one active infection episode; all other current states have none. | HumanState; InfectionEpisode | InfectionRules; validate_transition | `ACT_bite_success`, `ACT_treat_infection_success` (34 mapped) |
| V06 | Episode deadline equals onset plus positive incubation duration. Cure, conversion, and host death close an episode exactly once. | InfectionEpisode; ExactTime | InfectionRules; ConversionRules; ScheduleRules | `ACT_bite_success`, `ACT_treat_infection_success` (35 mapped) |
| V07 | Conversion preserves identity, position, current life/stamina, and history; human inventory/role/effects do not silently disappear or persist as zombie capabilities. | Agent; AgentIdentity | ConversionRules; ResourceRules; UnitOfWork | `LIF_cure_deadline_4`, `LIF_cure_deadline_4_000000001` (16 mapped) |
| V08 | At most one compatible active role and one active model assignment exist per living agent. Dead agents have neither. | RoleAssignment; ModelAssignment; RoleRegistry | AgentState.validate; InterventionRules | `ACT_melee_reject_missing_capability`, `ACT_pickup_reject_missing_capability` (40 mapped) |
| V09 | Every action is granted by the actor's type/role and conforms to its full contract. | ActionDefinition; RoleDefinition | ActionHandlerRegistry; ActionLifecycle | `ACT_move_success`, `ACT_wait_success` (244 mapped) |
| V10 | An agent has at most one active action. Actions have positive durations; cooldowns and reservations are respected. | ActionOccurrence; Reservation; ScheduledTask | ActionLifecycle; validate_transition | `ACT_wait_success`, `ACT_rest_success` (125 mapped) |
| V11 | Stamina and hunger stay in [0,100]. Regeneration, consumption, and starvation follow their clocks without negative quantities. | HumanState; EngineFacts | ContinuousEvolution; ScheduleRules | `ACT_move_success`, `ACT_move_continuous_midpoint` (46 mapped) |
| V12 | Inventory mass never exceeds capacity. Transfer and pickup conserve items; only recorded consumption/intervention changes totals. | Inventory; ResourceQuantities | ResourceRules; PortableResourceHandler | `ACT_pickup_success`, `ACT_drop_success` (89 mapped) |
| V13 | Reserved quantities are subsets of existing stock/charges. A reservation cannot be spent twice, dropped twice, or remain after its action ends. | Reservation; SpitterRoleState | ActionEvaluation.reserve; ActionLifecycle; validate_transition | `ACT_pickup_success`, `ACT_drop_success` (79 mapped) |
| V14 | Movement respects the current speed at every point and never teleports through barriers. | Trajectory; PathPoint; EffectiveProfile | MoveHandler; ContinuousEvolution; GeometryRules | `ACT_move_success`, `ACT_move_reject_duration_zero` (44 mapped) |
| V15 | Local observations use sensing, occlusion, timestamps, and the declared field-visibility policy. Private state is not leaked by feasibility checks. | SignalPayload; TimedEffect | ObservationBuilder; ReadProjection; SignalRules | `ACT_signal_unknown_kind_rejected`, `ACT_recon_subsequent_observation_expands` (34 mapped) |
| V16 | Every stochastic outcome has a valid probability, identified source event, and recorded realized outcome. | DomainEvent / RandomEventPayload | EventRandom; AttackHandler | `ACT_melee_success`, `ACT_claw_success` (61 mapped) |
| V17 | Physical damage is integer and bounded by remaining life; starvation bypasses armor; healing cannot revive. | DomainEvent / DamageEventPayload | DamageRules; MedicalHandler; ContinuousEvolution | `ACT_melee_success`, `ACT_claw_success` (48 mapped) |
| V18 | Lethal damage resolves death before any same-hit infection draw. Re-exposure never duplicates an ongoing episode. | InfectionEpisode; lifecycle event payload | DamageRules; InfectionRules; AttackHandler | `ACT_claw_success`, `ACT_bite_success` (61 mapped) |
| V19 | Reciprocal overlapping attack attempts admit at most one valid winning attempt; cancelled attempts have no target effects. | ActionOccurrence | AttackHandler; ActionLifecycle | `CON_first_valid_winner_miss_cancels_other`, `CON_equal_time_reciprocal_only_one_kills` (6 mapped) |
| V20 | Gate modes agree with integrity. Construction/closure never creates impassable geometry on a living agent. | Gate; Barricade; Rectangle | OpenGateHandler; CloseGateHandler; BuildBarricadeHandler; GeometryRules | `ACT_open_gate_success`, `ACT_close_gate_success` (39 mapped) |
| V21 | Every death creates at most one remains entity; consumed biomass never returns; remains are not living agents. | Remains | DeathRules; FeedHandler; ResourceRules | `ACT_feed_success`, `ACT_bite_lethal_hit_has_no_infection_draw` (21 mapped) |
| V22 | Continuous evolution, biological deadlines, effect expiration, and equal-time precedence are independent of an agent's selection frequency. | ExactTime; ScheduledTask; EngineFacts | ScheduleRules; SchedulerService; ContinuousEvolution | `ACT_move_continuous_midpoint`, `ACT_guard_effect_exclusive_expiry` (57 mapped) |
| V23 | The initial role/status counts, resource totals, placement distances, geometry, and connectivity satisfy the scenario. | WorldBounds; RoleRegistry; ConfigurationService | ConfigurationService.initialize/place; formal baseline validator | `SYS_CONFIG_EXECUTION_WORKERS`, `SYS_CONFIG_EXECUTION_CHECKPOINT_INTERVAL` (9 mapped) |
| V24 | Causal history is acyclic and preserves every required state change, including interrupted and failed actions. | DomainEvent; ActionOccurrence; TransitionPlan | ActionLifecycle; UnitOfWork; AtomicCommitPort | `ACT_wait_success`, `ACT_rest_success` (87 mapped) |
| V25 | Derived values agree with their source facts; no independent writable duplicate can contradict type, status, speed, progress, or inventory totals. | ProfileValues; EffectiveProfile; AgentState | ProfileResolver; ReadProjection; DomainCodec | `ACT_guard_effect_exclusive_expiry`, `ACT_recon_effect_exclusive_expiry` (17 mapped) |

## All 29 action contracts

Each action has one concrete handler registered in [handlers.py](../src/zombie_sim/game_rules/handlers.py). Shared admission, reservations, cancellation and completion belong to [ActionLifecycle](../src/zombie_sim/game_rules/action_lifecycle.py). Definitions come from the unchanged ontology catalog through `ActionDefinition`. Each success case is also executed by the architecture event/codec test, which round-trips emitted entities, events and queue tasks.

| Action | Concrete handler | Independent success case | Other mapped cases |
| --- | --- | --- | --- |
| `bite` | `BiteHandler` | `ACT_bite_success` | 38 |
| `build_barricade` | `BuildBarricadeHandler` | `ACT_build_barricade_success` | 19 |
| `claw` | `ClawHandler` | `ACT_claw_success` | 41 |
| `close_gate` | `CloseGateHandler` | `ACT_close_gate_success` | 13 |
| `dash` | `DashHandler` | `ACT_dash_success` | 11 |
| `demolish` | `DemolishHandler` | `ACT_demolish_success` | 10 |
| `drop` | `DropHandler` | `ACT_drop_success` | 11 |
| `eat` | `EatHandler` | `ACT_eat_success` | 12 |
| `feed` | `FeedHandler` | `ACT_feed_success` | 9 |
| `first_aid` | `FirstAidHandler` | `ACT_first_aid_success` | 16 |
| `guard` | `GuardHandler` | `ACT_guard_success` | 11 |
| `mark_target` | `MarkTargetHandler` | `ACT_mark_target_success` | 9 |
| `melee` | `MeleeHandler` | `ACT_melee_success` | 19 |
| `move` | `MoveHandler` | `ACT_move_success` | 40 |
| `open_gate` | `OpenGateHandler` | `ACT_open_gate_success` | 9 |
| `pickup` | `PickupHandler` | `ACT_pickup_success` | 30 |
| `power_strike` | `PowerStrikeHandler` | `ACT_power_strike_success` | 13 |
| `prophylaxis` | `ProphylaxisHandler` | `ACT_prophylaxis_success` | 13 |
| `rally` | `RallyHandler` | `ACT_rally_success` | 9 |
| `recon` | `ReconHandler` | `ACT_recon_success` | 10 |
| `repair_barrier` | `RepairBarrierHandler` | `ACT_repair_barrier_success` | 11 |
| `rest` | `RestHandler` | `ACT_rest_success` | 25 |
| `scream` | `ScreamHandler` | `ACT_scream_success` | 8 |
| `signal` | `SignalHandler` | `ACT_signal_success` | 12 |
| `smash` | `SmashHandler` | `ACT_smash_success` | 9 |
| `spit` | `SpitHandler` | `ACT_spit_success` | 18 |
| `transfer` | `TransferHandler` | `ACT_transfer_success` | 31 |
| `treat_infection` | `TreatInfectionHandler` | `ACT_treat_infection_success` | 17 |
| `wait` | `WaitHandler` | `ACT_wait_success` | 33 |

## Architectural evidence and semantic distinctions

- `tests/architecture/test_domain.py`: all eight role branches, role-free states, typed identity conversion, frozen nested values, profile parity, explicit unknown-field errors and real-run round trips.
- `test_domain_integration.py`: real Simulation identity/state replacement and assignment retirement, not a separate demonstration model.
- `test_event_contract.py`: all 29 supplied action successes, explicit event payload/version handling, exact task order and malformed task rejection.
- `test_rule_boundaries.py` and `test_state_contract.py`: isolated read/draft/runtime ownership, immutable plans and rejected unknown continuation fields.
- Persistence/port architecture tests: atomic combined publication, stale revisions, transaction identity/retry recovery, independent in-memory history and actual Simulation use of injected ports.

The formal ontology distinguishes persistent Agent from dated AgentState. HumanState and ZombieState are disjoint state variants; conversion does not replace identity. Role specialization is independent from biological type and life status. `ActionOccurrence` is a durative activity, while `DomainEvent` records causal facts; the implementation does not invent an ontology disjointness assertion between ActionOccurrence and Event. Scheduler tasks remain an execution concern. See the [detailed ontology review](deep-oop-proposal/ontology-review.md) for exact canonical sections and formal constraints.

Runtime state, storage transactions, copy-on-write cells and persistence ports are implementation mechanisms. They preserve the ontology atomicity/history obligations without adding game mechanics or changing ontology classifications.
