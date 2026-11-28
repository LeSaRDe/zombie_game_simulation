# Ontology review for the deeper OOP refactor

Reviewed 2026-11-27, read-only planning work. Project root: `/home/fmeng/workspace/zombie_game_simulation`.

## Decision

The requested implementation architecture does **not require a semantic ontology change**. Preserve the present Markdown vocabulary, OWL axioms/catalog, SHACL constraints, scenario defaults, and acceptance assertions. The ontology deliberately leaves processing/storage representation to TASK 2 (§1, §14.1, §14.3, §16.1). An implementation mapping, additional architectural contracts, and stronger behavioral tests are needed. These are implementation artifacts, not new game mechanics.

The current plan expressly requires a concrete refactoring plan, justification, and approval before implementation (`prompts/zombie_game_plans.md:46`–52). Current step starts at line 54. Earlier issue approvals do not supply the concrete reviewable plan requested by the edited current step.

## Read coverage and verification limits

Read the complete canonical Markdown (`ontology/zombie_game_ontology_v0.1.md`, all 808 lines); complete `ontology.ttl` (975 lines), `catalog.ttl` (550), `shapes.ttl` (2348, including all 70 SPARQL bodies), and `baseline.ttl` (962). Read complete `README.md`, `COVERAGE.md`, `VALIDATION_REPORT.md`, `manifest.json`, `examples.json`, `provenance_refresh.json`, `toolchain.json`, and `requirements.txt`.

Parsed all of `ontology.owl` with RDFLib and verified graph isomorphism against the union of the fully read core and catalog. This reads/validates the complete alternative serialization without claiming a separate manual inspection of its 2468 XML lines. Graph counts: core 902, catalog 478, RDF/XML 1380, shapes 1807, baseline 794.

Parsed the entire `coverage.json`; checked all 402 quoted substantive source lines against the Markdown (zero mismatches); reviewed every unique represented-aspect/remaining-obligation pair, all 29 action records and all 70 constraint mappings. All 70 embedded queries exactly match the already-read SHACL query bodies. Read normalized complete `baseline-summary.json`. Read and checked all 148 project-root-relative SHA256SUMS entries; only the user's edited plan differs.

Supplemental examples: all 38 TTL examples parse successfully; read `valid_conversion_preserves_identity.ttl` in full and the 35-entry example expectation manifest. Other example graph contents were parsed, not individually reviewed line by line. They are finite conformance evidence, not additional normative rules. Existing generated per-fixture reports, archived provenance copies, generator/validator Python/Java implementation, environments, and caches were not manually read; they are not canonical semantic specifications. **No canonical specification was unreadable.** No full HermiT/pySHACL execution was performed in this planning audit, and historical PASS reports are not represented as a newly completed execution.

## Recommended type model

Use explicit inheritance where the ontology actually describes specialization, and composition for independent changing axes:

```text
Agent (persistent aggregate, stable AgentIdentity(run_id, agent_id))
  current_state: AgentState
  state history: AgentStateReference(time, causal_revision)

AgentState (abstract state contract)
  HumanState (human-only inventory, hunger, infection reference/profile)
  ZombieState (zombie-only profile)

RoleDefinition (abstract immutable/versioned role contract)
  HumanRoleDefinition
    DoctorRole
    WarriorRole
    ScoutRole
    EngineerRole
  ZombieRoleDefinition
    TyrantRole
    RunnerRole
    SpitterRole
    ScreamerRole

RoleAssignment (agent identity + role definition + interval)
RoleState (applicable per-agent role data; e.g. Spitter charges/schedule)
ModelAssignment (agent identity + model/version/parameters + interval)
```

`HumanState` and `ZombieState` explicitly inherit shared state invariants. `biological_type` is derived from the concrete state type at the semantic boundary; do not retain two independently mutable type representations. Status remains the orthogonal derived state classification (`HEALTHY`/`INFECTED`/`ACTIVE`/`DEAD`) from type, life and episode. Death retains a terminal HumanState or ZombieState; it must not erase the last biological type by converting the identity into a generic DeadAgent. Dead states have no active role/model/action/capability/effect/episode and retain frozen position/type.

Each living state composes zero or one compatible RoleAssignment and exactly one active ModelAssignment. Absence means no role; do not instantiate `NoneRole` as a semantic registry member. Shared RoleDefinition objects must be immutable; Spitter charges and model-private memory are per-agent state, never mutable shared registry attributes. Role classes expose profile overrides/capability contracts but do not select policy or apply unvalidated state mutations.

Avoid permanent `DoctorAgent(HumanAgent)` identity trees: the role is removable, infection does not change human capabilities, and conversion preserves the individual. The formal `DoctorState`/`WarriorState`/etc. classes are inferred living-state classifications via `activeRole -> roleDefinition`, not a mandate to multiply every status/type/role combination into implementation subclasses.

If literal HumanAgent/ZombieAgent incarnation objects were introduced, they could preserve semantics only by being clearly time/revision-scoped objects under the same persistent identity, atomically retiring/replacing incarnations and retaining historical states. They are **unnecessary for the recommended plan**, add stale-reference and naming ambiguity, and should not be its default. Persistent Agent + explicit state/role inheritance directly satisfies extensible typed modeling.

## Conversion is a state transition, never identity replacement

Evidence:

- Markdown §1.1 (`:21`) explicitly warns that Human and Zombie must not become incompatible permanent classifications of the same identity.
- §2.1 (`:73`–75) defines Agent as persistent `(run_id, ID)` and HumanState/ZombieState as mutually exclusive time-indexed state portions; §2.2 (`:103`–108) gives historical/current state and assignment cardinalities.
- §6.4 (`:309`) requires one atomic conversion preserving ID/run/creation/location/history/current life/current stamina; cancels active action, releases reservations, ends old assignments/effects/cooldowns, drops complete inventory, installs role-free default zombie profile/model with fresh private memory, ends human biological schedules.
- README `:34` states precisely that HumanState/ZombieState are disjoint **state** classes, not permanent disjoint agent identities.
- `ontology.ttl:866` declares Agent disjoint from AgentState and Remains; `:909`/`:918` classify HumanState/ZombieState by biologicalType and make the state classes disjoint. Do not RDF-export a runtime Agent as both Agent and AgentState merely because it composes state.
- `shapes.ttl:2155` TransitionIdentity requires same `ofAgent`, same `atTime`, increasing revision. `:980` ConversionPreserves requires equal life/stamina/x/y; `:995` ConversionTypes requires infected living Human -> active role-free Zombie with no inventory. ConversionDeadline starts `:972` and requires exact episode deadline/closure revision.
- `examples/valid_conversion_preserves_identity.ttl` explicitly has one `ex:person` (ID 17) with human_before and zombie_after at t=300, revisions 0 and 1, life=64/stamina=32 preserved.

Implementation implication: stage the complete new state and all paired world/history changes in one transaction; validate the whole transition; atomically publish. References in occurrences, episodes, assignments and observation history resolve by stable identity plus revision, not by whichever mutable Python object happens to be current. Rollback/failure must leave the old state and its history intact.

## Event/activity unification without collapsing meanings

The user's phrase “events (i.e., activities of agents)” can be implemented with one typed activity registration/lifecycle contract, while preserving these separate semantic objects:

1. ActionDefinition: versioned reusable parameters, actor eligibility/capability, costs, temporal rules, preconditions and possible effects.
2. ActionIntent: proposal tied to actor, proposal time and dated observation; a rejected intent has no ActionOccurrence.
3. ActionOccurrence: admitted attempt, reservation ownership, start/planned end/resolution, actual result and caused event IDs. One occurrence per executed intent; at most one unresolved action per agent.
4. Event: identified causal fact/outcome; may record rejection/miss without state effect; may be a lifecycle, biological, intervention or action-related event.
5. Effect: actual state change or bounded temporary modifier, distinct from an action definition's possible-effect category.

Recommended: a typed ActionDefinition/ActivityHandler interface and registry for all 29 actions; immutable typed intent/occurrence/result records; a common Event envelope for ID, run, semantic time, revision, causality and payload schema; specialized action/lifecycle/resource/geometry/biological/intervention payloads; typed Effect records. Share lifecycle orchestration (validate, admit, advance, resolve, cancel) with type-specific implementations. Give the scheduler its own typed scheduled-work/deadline records; a scheduled item is not evidence that a semantic Event occurred. Conversion/death/recharge are not policy-chosen actions consuming a new action slot.

Formal precision: `ontology.ttl:7` ActionIntent, `:10` ActionOccurrence and `:86` Event are separate plain OWL classes. There is **no asserted disjointness, equivalence, or subclass relation between ActionOccurrence and Event**. Their implementation record distinction follows the Markdown definitions/relations; do not falsely describe OWL as prohibiting class overlap. A common implementation envelope does not justify equating ontology concepts or changing RDF types.

Source obligations: §2.1/§2.2 (`:82`–91, `:110`–119), §9.1 (`:406`), §9.2 (`:414`), §10–13, §14. Formal ActionCapability `shapes.ttl:425`, ActorStartIdentity `:658`, ActorEndIdentity `:642`, IntentAgreement `:1449`, OneActionAtATime `:1595`, ReciprocalAttackExclusion `:1671`, ResultTiming `:1778`, ActionState `:634`, ActionRelease `:626`. `catalog.ttl` contains all 29 definitions, not executable full effect laws.

## Game rules, state management and storage boundaries

- Game rules/services receive a consistent semantic state view, explicit time/context and recorded RNG interface, and produce validated typed transitions/outcomes. They do not import SQL/JSONL/filesystem/UI or write repositories directly. Policy receives a dated observation only and proposes intent (§8.1/§8.2); it cannot write current game state or inspect future draws/deadlines.
- State management owns current revision, identity resolution, aggregate invariants, mutation staging, reservations, active occurrence lifecycle, serialization-equivalent commit order and immutable snapshots. A transaction applies the whole semantic change, including coupled agent/environment/history effects.
- Storage ports own persistence and retrieval of committed states/history/snapshots, their codec/schema versions, and fault reporting. Concrete live state and durable record stores are separate replaceable adapters behind contracts. Do not promise that swapping an adapter automatically gives distributed serializability, durability or performance.
- A commit design must state its crash/append-failure behavior and commit point. It must not expose a transferred item at both holders, publish a conversion before cancellation/drop/history, let a failed action leave consumed items, duplicate a retried occurrence, or report an unrecorded transition as durably committed. Same-time phase ordering must remain explicit, independent of backend latency.
- Snapshot includes pending occurrences, biological deadlines, reservations, cooldowns/effects and private model state where restart promises require it. Read models/GUI snapshots are dated values, not mutable state handles. No backend may silently weaken “full evolution” to coarse frames or seed-only records.

Evidence: §1 (`:10`), §3.3 (`:163`), §6.4/§6.5, §8.2 (`:398`), §9.2.8 (`:423`), §14.1 (`:549`), §14.3 (`:580`), §16.1 (`:677`–691), §16.3 (`:714`). SHACL validates selected facts but does not prove transactional storage/history sufficiency: COVERAGE.md §§14/16 expressly retain serializability/replay gaps.

## Invariant and test mapping for the plan

| Area | Existing requirement | New architectural verification needed |
|---|---|---|
| Identity and state | V01/V03/V04/V07/V08; UniqueAgentID, StateIdentityRevision, StateStatus, StateTypeFields, TransitionIdentity, NoResurrection | Construction rejects invalid type/profile/role combinations; biological type cannot contradict state class; conversion retains same identity and immutable old state; death cannot be replaced by living state; codec round trips retain concrete state type and identity/revision. |
| Roles and memory | §7.1/§7.4/§8.2; RoleCompatibility, RoleOverrides, RoleFieldApplicability, AliveAssignments | Eight explicit roles reproduce exact capabilities/profile overrides; mutable Spitter/memory data is not shared; removing/changing roles drops capacity excess, cancels role action/effects without refunds; conversion creates fresh default-zombie memory and no role. |
| Unified action contract | §9–13, V09/V10/V13/V17–19 | All 29 IDs registered exactly once; each intent/occurrence/outcome/effect path uses common lifecycle; admission rejection does not create occurrence or pay cost; failure/miss/cancellation boundaries preserved; extension registration cannot bypass eligibility/reservation rules. |
| World and lifecycle atomicity | §3.3/§6/§9.2/§14, V12/V13/V20–24 | Inject failures at commit stages and confirm no partial transfer, duplicate drop/remains, stale reservations, unrecorded events or mixed revision; exact-deadline cure/conversion/starvation tests; reciprocal overlapping/touching interval cases. |
| Rule/state/storage dependency | §8.2/§14.1/§16.1 | Import/dependency contract tests prevent domain services depending on adapters; execute the same semantic traces through distinct storage adapter implementations and compare full observable states/events/random outcomes. |
| Replay and compatibility | §16.1/§16.3, V24/V25 | Existing artifacts decoded/replayed; immutable observation history survives later mutation; final pending action/deadline state retained; fresh replay uses recorded outcomes; counterfactual identity stays run-scoped; continuous trajectories remain reconstructible. |
| Formal evidence | Entire canonical ontology, 35 fixture outcomes + OWL examples | Run full pinned ontology validation after approved metadata maintenance; keep expected bad cases failing named constraints; supplement partial formalization with engine behavior checks, not claim full proof from SHACL. |

All existing external acceptance assertions should be retained unless an independently justified correction is explicitly approved. Add new architectural tests for actual boundaries/invariants, not tests that merely repeat new class names or call-through implementation. A conformance report should map every V01–V25 and all 29 actions to preserved runtime checks/tests and honestly list remaining partial verification.

## Provenance maintenance is necessary, but not an ontology redesign

Current ontology Markdown hash is unchanged and matches the manifest:
`20620b8f7f01a3b758fcbea0f0ca83ea3e65a5354071e6d7ef4dfa21a7ec9641`.

The edited plan hash is now:
`368333ab5f8458e2cb96f262e8566c4a5bf1f66b73f7cb7621d39331365ac115`.

Manifest/provenance currently pin:
`05915f055fa33cc00b1dfb3920b835659d3885edcc5c328bfcbb6287972d5311`.

All five rule-artifact hashes match `provenance_refresh.json`. Current SHA256SUMS has 148 entries; the edited plan is the sole mismatch. The approved implementation plan should include a documented provenance refresh preserving previous manifests/reports/history, followed by validation/repackaging. Do not silently skip the hash guard, rewrite historical PASS claims, or edit semantic files to accommodate an implementation shortcut. No files in ontology, tests or production were modified by this audit.

## Changes that would require separate semantic approval

Permanent Human/Zombie identity disjointness; multiple simultaneous roles; new type/status/lifecycle; auto-promoted roles on conversion; resurrection or reverse conversion; changing action costs/targets/timing/outcomes; policy access to hidden/current mutable state; coarsening required replay history; relaxing same-time phase ordering/resource conservation. None is required for the proposed OOP design.
