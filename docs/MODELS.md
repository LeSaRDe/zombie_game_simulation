# Decision models

`zombie_sim.policies` supplies `HumanDefaultModel` and `ZombieDefaultModel`, with
`defaultHuman/v1` and `defaultZombie/v1` versioned registry names. The short names
`defaultHuman` and `defaultZombie` are aliases. `randomLegal/v1` samples uniformly
from observable candidates; competition and hidden changes can still cause rejection.

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

The candidate restriction uses eight local frontier headings, at most four directly
visible opponents for combat/pursuit, one-unit portable transfers, bounded movement
plans, and gate-centered defensive construction. Every ontology action remains in
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
