# Decision models

`zombie_sim.policies` supplies `HumanDefaultModel` and `ZombieDefaultModel`, with
`defaultHuman/v1` and `defaultZombie/v1` versioned registry names. The short names
`defaultHuman` and `defaultZombie` are aliases. `randomLegal/v1` samples uniformly
from observable candidates; competition and hidden changes can still cause rejection.
The current utility model implementation version is `1.1.0`.
New agent and conversion assignments record the registry's actual resolved model
version. An explicit bare major version such as `1` selects that compatible family
and is retained as `requested_version`; an explicit full version must match the
installed implementation. Existing stored assignments are preserved on replay and
restart, with checkpoint artifact pins providing exact code verification.

A model implements `initialize_memory(agent)` and
`decide(observation, memory, random.Random) -> (intent, new_memory, diagnostics)`.
`decide_batch` is a batching convenience with one RNG and memory per observer.
Register plugins using `register_model(name, factory)`; the factory takes a parameter
mapping. Unknown model IDs raise an error for the engine's recorded fallback handler.
`choose` is the engine-facing convenience function. Policy exceptions cannot mutate
world state because policies receive detached local observations.

Observations contain full local visible agent state, observed environment surfaces,
received dated signals, own state, time and bounds. Policies never accept a global
state store or hidden feasibility callback. Direct interactions use visible entities;
remembered positions only create navigation/report candidates. Geometry routing uses
visible or remembered geometry. A remembered dynamic barrier can be stale, so the
engine still validates every path. Partial surfaces enter navigation as observed edges. Only a complete observed
four-edge perimeter permits reconstructing a rectangle; unseen extents are not invented.

Memory is JSON-serializable and separate for each identity: discovered geometry,
resource sightings, dated neighbors/reports, route, objective, failed attempts,
visit counts, and report cadence. Memory is reset when its owner/type changes.
The engine retires active memory on death and starts fresh zombie memory on conversion.
Models share immutable parameter values and learned weights, never private memories.

The utility policies construct feasible-looking candidates and sum normalized
features times versioned weights. Features express survival, infection urgency,
expected damage/recovery, resource and ally value, exposure, travel/stamina cost,
exploration, communication, barrier work and waiting. Diagnostics retain every
ranked candidate, feature, score, and the chosen reason. Equal scores use the supplied
seeded RNG. Parameters and their digest are available through `model.manifest()`.
Diagnostics also identify the selected entry in the ranked list. Identical typed
intents can arise from different goals and have different feature values; their
entry identity is retained instead of guessing the selected rationale afterward.

`set_goal(memory, goal)` accepts the public `hold_location`, `reach_location`,
`seek_resource`, `supply_ally`, `protect_region`, and `explore_frontier` goals.
These goals add no sightings or map knowledge. An active hold within 0.5 m of its
position suppresses travel until its deadline, while recovery, combat and reporting
remain candidates. Location goals use routes derived from observed surfaces;
an observed blocking gate gains ally-value 0.5 for opening or demolition. A
requested resource that is not carried has want-value at least 0.9. Supply goals
use the same visible recipient-need checks as ordinary transfers. Protection
goals retain closed defenses, add ally-value 0.5 to repairs, and consider closing
visible wall gaps when a threat is observed. Frontier goals give approach travel
exploration-value 0.8. The selected action's explanation is separate from this
persistent high-level goal.

The published default weights are survival 4, infection 4, damage 2.2, recovery 2,
resource 1.4, ally 2, risk -1, travel -0.15, stamina -0.25, exploration 0.55,
communication 0.8, barrier 1.3, and waiting 0.12. Features are bounded to [0,1];
travel is duration/8 and stamina is flat cost/20. Recovery scales the missing
life/stamina fraction; hunger urgency starts at 35 and reaches one at 100;
danger is `max(0, 1 - nearest_enemy_distance/15)`. Attack damage value is expected
hit damage divided by 25 (30 for heavy strikes), clamped to one. Infection value
uses visible susceptibility and treatment slack, with urgency increasing inside
60 seconds. Resource needs, finishing-hit bonuses, ally support and communication
use the explicit bounded values in `generate_candidates`. Frontier novelty is
`1/(1 + remembered_cell_visits)`. Rest is considered below 95 stamina, movement
plans last at most three seconds, reports repeat no sooner than 12 seconds, and
dated entity sightings expire after 90 seconds. Every score is the sum of its
reported feature × weight terms; negative preferences are represented by signed
weights rather than negative feature values.

The candidate restriction uses eight local frontier headings, at most four directly
visible opponents for combat/pursuit, one-unit portable transfers, bounded movement
plans, and construction at visible entrances or opposed observed wall-end faces.
The latter must establish a one-metre-thick gap with a 2–8 m span; the candidate
checks observed occupancy, bounds, reach and corner rays before submission.
Partially observed open gates may produce closure proposals, with known occupancy
excluded and full authoritative occupancy rechecked at admission. Every ontology action remains in
the candidate vocabulary. This is a policy restriction, not an engine restriction.
Plugins may submit arbitrary typed actions allowed by the engine.

| Actions | Situations in which their utility matters |
|---|---|
| move, wait, rest | Reach resources/prey or unexplored space; await observed gate work; recover energy |
| signal | Report a fresh threat to allies or request treatment |
| melee, power_strike | Fast damage versus a reachable threat; use finishing heavy damage |
| pickup, drop, transfer | Acquire needed stocks; make capacity; supply a Doctor or hungry ally |
| eat, first_aid | Avoid hunger or restore injured living humans |
| open_gate, close_gate | Open a discovered passage or close an unoccupied threatened doorway |
| claw, bite | Faster damage or a new infection opportunity |
| feed, smash | Recover using remains or break a known destructible barrier |
| treat_infection, prophylaxis | Cure before a deadline or protect a healthy exposed human |
| guard | Prepare physical resistance before imminent contact |
| recon, mark_target | Discover nearby unknown space or share a visible threat |
| build_barricade, repair_barrier | Defend a breached entrance or restore a damaged defense |
| rally, demolish | Support visible zombie allies or efficiently break a durable obstacle |
| dash, spit, scream | Close a gap, spend a useful ranged charge, or announce fresh prey |

`ppo:<artifact-directory>` loads the alternate candidate network. Its manifest checks
encoder dimensions and a weights SHA-256 before loading tensor-only PyTorch weights.
The learned controller has a private recurrent state stored as a JSON list. Training
rewards are read separately from authoritative events and never enter actor observations.
