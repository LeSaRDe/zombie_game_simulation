# Gate fixture review — TASK 2 acceptance testing

**Approved and implemented, 2026-11-25.** The user approved fixture corrections while preserving the ontology. All 443 simulation and validation cases now pass. Executed open-gate, smash and repair traces with the corrected enclosures also pass the original SHACL shapes. The policy witness and 29-action encoder banks pass after their corresponding explicit enclosure corrections.

The current evidence does **not** require refactoring, redefining, or reformalizing the ontology. The implementation must retain the mandatory gate–shelter relationship. The supplied suite contains incomplete gate fixtures; changing that relationship solely to accept those fixtures would change the domain model.

## Evidence and scope

- `ontology/zombie_game_ontology_v0.1.md`, §3.2, lists `shelter_id` among every Gate's required properties.
- §2 specifies `Shelter hasWall Obstacle` as one or more walls and an enclosed protected region except for its gates. Entity references must resolve within the same run.
- `ontology/formal_v0.1/shapes.ttl`, `Gate_hasShelterShape` (line 1274), independently requires exactly one `hasShelter` IRI of class `Shelter`.
- The authoritative baseline supplies the enclosure, gate, and ownership together.
- `tests/spec/actions.py:_gate` and `tests/spec/lifecycle_geometry.py:barrier` create Gate records without a shelter reference or enclosing shelter. Derived positive and negative cases inherit that omission.
- In the first complete simulation/validation run, 395 of 443 cases passed. The 47 errors and one assertion failure listed below all arose from this omission. The negative boundary-position case reaches the mandatory-reference error before its intended geometry error.

The Markdown specification and formal cardinality agree. There is no demonstrated contradiction that would justify changing either. This is a test-arrangement defect, not evidence that the action's expected damage, timing, resource, or gate-mode effects should change.

## Proposed fixture correction

Revise the test fixtures explicitly, with a visible reviewable diff. Each gate scenario should identify an actual shelter, include enclosing obstacle walls and an interior rectangle, and provide reciprocal `shelter.gates` and `gate.shelter_id` references. Keep the existing gate ID, footprint, mode, integrity, action, event times, and substantive outcome assertions. Review each geometry/visibility fixture individually: added walls can change routes and visibility, so a generic adapter-side auto-enclosure would conceal a change in the test input.

For the common gate `[12, 9, 13, 11]`, one concrete valid enclosure is:

| Record | Footprint / references |
|---|---|
| Gate `g` | Existing footprint and state; `shelter_id = shelter-g` |
| West lower wall | `[12, 5, 13, 9]` |
| West upper wall | `[12, 11, 13, 15]` |
| South wall | `[13, 5, 21, 6]` |
| North wall | `[13, 14, 21, 15]` |
| East wall | `[20, 6, 21, 14]` |
| Shelter `shelter-g` | Interior `[13, 6, 20, 14]`, the five walls, gate `g` |

The actor at `[10, 10]` retains its original distance and unobstructed interaction segment to the gate. This example is not a blanket replacement for all cases. Occupancy, movement and observation fixtures require their own verified enclosure geometry.

The implemented action/lifecycle helper uses a narrower three-wall enclosure whose gate spans the complete west side of the interior. For gate bounds [x0,y0,x1,y1], the interior is [x1,y0,x1+8,y1], with 0.1 m thick north, south and east walls. This retains corner approaches on the west face, occupied gate positions and all original movement/contact axes. The helper is part of the visible test fixtures, not an adapter behavior. Deliberately malformed rectangles remain malformed and are not auto-repaired.

All action, timing, damage, resource and visibility assertions were retained. Three total-barrier counts increased by exactly three to account for the explicit fixture walls; the expected admission/rejection outcomes did not change. Policy doorway fixtures separately retain their existing two wall segments and add the three missing enclosure sides. Original tests with gates replaced by an Obstacle or Barricade receive no gate enclosure.

No failures were converted to skips, no production validation was bypassed, and no ontology files were changed. The reviewed source-pin audit now includes all test specification modules, including the new enclosure fixture helper.

## Alternative requiring an explicit ontology decision

If standalone gates are intended as a domain concept, that is a separate model change: redefine Gate ownership as optional (or introduce a separate barrier concept), revise inverse relationships, Markdown requirements, OWL restrictions, SHACL cardinalities, baseline assumptions, initialization validators and formal examples; then validate the revised formal package and rebuild the affected tests. This change is **not recommended based on the current evidence** and has not been made. It would require the explicit review and approval stipulated in the plan file.

## Affected supplied cases

- `ACT_close_gate_living_occupant_blocks_closure`
- `ACT_close_gate_reject_busy_actor`
- `ACT_close_gate_reject_dead_actor`
- `ACT_close_gate_reject_insufficient_stamina`
- `ACT_close_gate_reject_missing_capability`
- `ACT_close_gate_success`
- `ACT_close_gate_wrong_gate_mode`
- `ACT_demolish_breach_clamps_integrity`
- `ACT_demolish_reject_busy_actor`
- `ACT_demolish_reject_cooldown`
- `ACT_demolish_reject_dead_actor`
- `ACT_demolish_reject_insufficient_stamina`
- `ACT_demolish_reject_missing_capability`
- `ACT_demolish_success`
- `ACT_open_gate_reject_busy_actor`
- `ACT_open_gate_reject_dead_actor`
- `ACT_open_gate_reject_insufficient_stamina`
- `ACT_open_gate_reject_missing_capability`
- `ACT_open_gate_success`
- `ACT_open_gate_wrong_gate_mode`
- `ACT_repair_barrier_breached_gate_becomes_open`
- `ACT_repair_barrier_missing_consumable`
- `ACT_repair_barrier_reject_busy_actor`
- `ACT_repair_barrier_reject_cooldown`
- `ACT_repair_barrier_reject_dead_actor`
- `ACT_repair_barrier_reject_insufficient_stamina`
- `ACT_repair_barrier_reject_missing_capability`
- `ACT_repair_barrier_success`
- `ACT_smash_breach_clamps_integrity`
- `ACT_smash_reject_busy_actor`
- `ACT_smash_reject_cooldown`
- `ACT_smash_reject_dead_actor`
- `ACT_smash_reject_insufficient_stamina`
- `ACT_smash_reject_missing_capability`
- `ACT_smash_success`
- `CON_invalid_first_attempt_does_not_win`
- `GEO_barricade_over_gate_breached`
- `GEO_barricade_over_gate_closed`
- `GEO_barricade_over_gate_open`
- `GEO_intact_barricade_prevents_gate_closure`
- `GEO_moving_occupant_prevents_gate_closure`
- `GEO_newly_closed_gate_stops_before_contact`
- `GEO_repair_breached_gate_with_living_occupant_rejected`
- `GEO_shelter_entry_does_not_grant_immunity`
- `OBS_occlusion_gate_breached_0`
- `OBS_occlusion_gate_closed_200`
- `OBS_occlusion_gate_open_200`
- `VAL_living_on_closed_barrier_boundary`
