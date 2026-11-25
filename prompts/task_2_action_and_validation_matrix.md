# TASK 2 Action and Validation Matrix

**Stage:** 1 — companion to [implementation plan revision 0.2](task_2_implementation_plan.md), November 24, 2026  
**Status:** Proposed implementation and tests; no simulator code has been added.

This matrix turns the ontology's 29 action contracts and 25 invariants into concrete implementation obligations and acceptance checks. [Section 5](#5-visualization-and-gui-acceptance) adds G01–G16 for the Visualization & GUI requirement. Numeric values are the v0.1 baseline. A resolved scenario can replace parameters within their declared domains; runtime handlers read the resolved registry rather than duplicating constants.

## 1 Action implementation matrix

In the tables, **duration / stamina / cooldown** uses seconds and flat stamina units. Movement has an additional distance cost. Contact range is 1.5 m and barrier work range is 2 m unless stated otherwise. All applicable start and completion conditions, visibility checks, and shared cancellation rules remain mandatory even when not repeated in a row.

### 1.1 Common actions

Source: ontology Sections 9–10.

| Action | Baseline duration / stamina / cooldown | Implementation obligations | Policy demonstration and decisive checks |
|---|---|---|---|
| `move` | 0.25–5 / distance cost / none | Time-parameterized legal path; enough stamina for the full plan; per-segment speed limit; actual-distance cost; dynamic barrier interruption. | Navigate around a discovered wall toward a resource. Reject a crossing with legal endpoints; interpolate mid-move; stop 0.01 m before new blocking geometry. |
| `wait` | 0.25–5 / 0 / none | Stationary; no stamina gain; all biological clocks and incoming effects continue. | Wait briefly for an observed gate operation or cooldown. Verify that waiting cannot pause infection or starvation. |
| `rest` | 1–5 / 0 / none | Stationary continuous stamina gain at type/role rate, capped at 100; no life healing. | Recover stamina before travel/combat. Verify partial recovery before an interruption and no overshoot. |
| `signal` | 0.5 / 1 / 2 | Validate bounded payload and knowledge provenance; emit at completion; radius 40 m, TTL 8 s; deliver once at emission. | Request supplies or warn allies. Test reception through walls, opponents' noise cues, original observation timestamps, and no reception by late entrants. |

### 1.2 Human actions

Source: ontology Section 11.

| Action | Baseline duration / stamina / cooldown | Implementation obligations | Policy demonstration and decisive checks |
|---|---|---|---|
| `melee` | 1 / 6 / 1 | Human hit formula; raw damage 16 or role override; mitigation, death, and reciprocal conflict rules. | Attack a reachable threat when escape is unattractive. Test hit/miss, armor rounding, same-type prohibition, and a winning miss cancelling the reciprocal attack. |
| `pickup` | 1 / 1 / none | Reserve an exact positive quantity in the stockpile; check capacity; atomically move stock on success. | Collect medicine/food/material needed for the current objective. Two agents competing for one item cannot both reserve it; cancellation leaves the item in its original holder. |
| `drop` | 0.5 / 0 / none | Reserve own items; create a ground stockpile at the actor's position; preserve exact quantities. | Free capacity for more urgent resources. Test competing reservations, exact quantity, zero/negative rejection, and no duplicate drop on death. |
| `transfer` | 1 / 1 / none | Reserve own items; recipient must be another living human; recheck full destination capacity at completion. | Give medicine to a visible Doctor or food to a starving ally. Concurrent transfers cannot overfill capacity; a converted recipient receives nothing. |
| `eat` | 2 / 0 / none | Reserve/consume one food; hunger must remain positive; reduce by 40, floor zero; clear starvation timers below 100. | Eat when hunger makes continued travel risky. Verify food at a lethal starvation deadline is too late; surviving same-time starvation occurs first. |
| `first_aid` | 3 / 4 / 2 | Self/visible injured living human; one medical supply; heal `10 + floor(20 × medical_skill + 0.5)`, capped at 100; retain infection. | Heal a wounded self/ally. Test normal and Doctor proficiency, full-health completion failure, self-targeting, and no cure or revival. |
| `open_gate` | 1 / 1 / none | CLOSED → OPEN with positive integrity unchanged; an independent barricade can still obstruct the opening. | Open a known route to supplies or shelter. Reject an already open/breached gate; test the overlapping-barricade case. |
| `close_gate` | 1 / 1 / none | OPEN → CLOSED; no living point or intact barricade in the footprint; recheck occupancy at completion. | Close a doorway after escape when observations support it. A moving agent entering before completion prevents closure; a dead identity's old point alone does not. |

### 1.3 Zombie actions

Source: ontology Section 12.

| Action | Baseline duration / stamina / cooldown | Implementation obligations | Policy demonstration and decisive checks |
|---|---|---|---|
| `claw` | 1 / 6 / 1 | Zombie hit formula; raw damage 14 or role override; no infection exposure. | Prefer faster direct damage in a close fight. Test role damage, rally bonus, resistance, reciprocal cancellation, and absence of any infection draw. |
| `bite` | 1.5 / 10 / 2 | Zombie hit formula; raw damage 6; after nonlethal damage, expose a healthy human using virulence. | Choose infection opportunity when timing and survival favor it. Baseline conditional exposure probability is 0.36; a lethal bite or an existing episode creates no new episode. |
| `feed` | 3 / 0 / 1 | Reserve one biomass from remains; require life or stamina below maximum at both ends; heal 8 and restore 12 stamina at baseline. | Recover from accessible remains. Two feeders cannot consume one biomass twice; the source identity remains dead; invalid completion releases biomass. |
| `smash` | 2 / 10 / 1 | Deterministic 20 integrity damage to a CLOSED gate or intact barricade; gate breach or barricade destruction at zero. | Break a known barrier blocking pursuit. Reject permanent walls/open gates; verify no hit draw and no negative integrity. |

### 1.4 Human role actions

Source: ontology Sections 7 and 13.1–13.4.

| Action and role | Baseline duration / stamina / cooldown | Implementation obligations | Policy demonstration and decisive checks |
|---|---|---|---|
| `treat_infection` — Doctor | 4 / 6 / 2 | Self/visible infected living human; reserve one medical supply; close the same active episode only strictly before its deadline; no life healing. | Treat the reachable patient with urgent but positive completion slack. Test deadline equality, self-treatment, two competing cures, no item consumption on failure, and conversion of the acting Doctor. |
| `prophylaxis` — Doctor | 4 / 6 / 2 | Self/healthy living human; consume one medical supply; resistance 0.80 for 120 s; strongest-value/refresh rules. | Protect an uninfected ally near an observed threat. Infection acquired before completion makes the target ineligible; protection is inactive exactly at expiry. |
| `power_strike` — Warrior | 1.5 / 15 / 6 | Human hit formula; raw damage 34; all reciprocal and damage rules apply. | Choose a strong finishing attack when expected timing permits it. Verify no guaranteed hit, cooldown on miss, and cancellation by a faster valid reciprocal attack. |
| `guard` — Warrior | 1 / 8 / 8 | Apply resistance 0.60 for 4 s at completion; actor becomes available for other actions while effect persists. | Prepare for imminent visible contact. Guard does not shield allies or lower infection probability; test effect expiry and role loss. |
| `recon` — Scout | 2 / 6 / 20 | Raise sensing radius to max(current base, 85 m) for 12 s; retain occlusion. | Inspect unexplored nearby space. Subsequent observations expand; past ones do not; a wall still occludes. |
| `mark_target` — Scout | 0.5 / 1 / 3 | Directly visible living target at admission and completion; emit current dated report with radius 90 m and TTL 10 s. | Report a newly discovered threat. No fixed contact reach; range derives from sensing/visibility. A report never auto-tracks or authorizes an unseen direct attack. |
| `build_barricade` — Engineer | 8 / 12 / 2 | Two materials; x/y-parallel footprint, length 2–8 m, thickness 1 m; center within 2 m; entire footprint visible/in bounds; occupancy, overlap, stockpile, and remains checks at both ends; new identity/integrity 100. | Defend a useful known entrance with enough materials. Test shared wall edges, open/breached gate overlap, moving occupancy, simultaneous overlapping builds, and nonempty resource points. |
| `repair_barrier` — Engineer | 5 / 8 / 1 | One material; restore up to 60 integrity; damaged gate or intact damaged barricade; breached gate becomes OPEN with occupancy/barricade checks. | Restore a useful damaged defense. Reject destroyed barricades/full integrity; test concurrent repairs, occupied breached gates, and no automatic closure. |

### 1.5 Zombie role actions

Source: ontology Sections 7 and 13.5–13.8.

| Action and role | Baseline duration / stamina / cooldown | Implementation obligations | Policy demonstration and decisive checks |
|---|---|---|---|
| `rally` — Tyrant | 2 / 15 / 20 | Other living zombies within 30 m at emission gain hit bonus 0.10 for 10 s through barriers; emit radius-30/TTL-10 cue; hide unseen recipient identities from actor result. | Support visible nearby zombies approaching a fight. Exclude self, use strongest bonus, retain recipients' effects after emitter death, and do not force actions. |
| `demolish` — Tyrant | 3 / 18 / 6 | Deterministic 60 integrity damage with smash target/breach rules. | Break a durable barrier efficiently. Check clamping, resource/geometry consequences of destruction, and no damage to permanent obstacles. |
| `dash` — Runner | 1 / 12 plus distance cost / 8 | Continuous legal path under 1.5× base speed, baseline limit 4.8 m/s; enough energy after flat cost; multiplier ends with occurrence. | Close a useful gap while retaining follow-up energy. Test instantaneous speed, interruption and partial cost, cooldown, and no automatic destination attack. |
| `spit` — Spitter | 1 / 8 / 8 | Visible opponent within 12 m; reserve one charge; spend on valid hit/miss; raw damage 4; exposure potency 0.30; release on invalid target. | Take a valuable ranged exposure opportunity. Test three-charge capacity, first-spend +30 s recharge, no postponement by further spends, death/role cancellation, and no persistent projectile/puddle. |
| `scream` — Screamer | 2 / 15 / 30 | Emit known dated target/location or own position, radius 120 m, TTL 12 s; allies receive HUNT_CUE, humans source noise. | Alert others to a recent useful sighting. No hidden global target, forced movement, damage, or rally bonus; check memory provenance and one-time delivery. |

## 2 Shared action test harness

Each action test constructs a small world through the same validated state builder and submits an intent through the public engine path. Directly calling an effect function alone is insufficient evidence that admission, scheduling, and completion work together.

For every applicable action, cover:

1. Correct type/role capability; alive/idle actor; sufficient stamina; off cooldown; positive legal duration; intent executed at most once.
2. Target observation/eligibility, inclusive distance boundaries, and clear interaction segment at admission and resolution. Self-target cases avoid accidentally requiring a second visible agent.
3. Successful resolution; exact pre/post field changes; unchanged unrelated fields; event provenance and result visibility.
4. Insufficient stock, simultaneous reservation claims, reservation release after failure/cancellation, and no partial fill for requested quantities.
5. Target moves, dies, converts, becomes fully healed, is cured first, or geometry changes before completion, as applicable.
6. Actor death/conversion/intervention; costs already paid; appropriate cancellation reason; no lingering timers/reservations/effects.
7. Cooldown begins at resolution, including miss/failure/conflict cancellation; rejection starts none; death/conversion retires obsolete cooldown state.
8. Replay of a mid-action state, final outcome, and restart with the same pending action produces equivalent results.

Only melee, claw, bite, power strike, and spit can return `MISSED`. Movement interruption has `PARTIAL_BLOCKED`. Admission rejection has no admitted occurrence. End-of-run pending actions remain `IN_PROGRESS`.

## 3 Invariant traceability

Source: ontology Section 17.1. These are behavioral acceptance obligations in addition to the formal package's existing finite-graph checks.

| ID | Runtime responsibility | Required tests and evidence |
|---|---|---|
| V01 | Scoped identity allocator and reference validator | Unique IDs across lifecycle changes, no reuse after death, no double intent execution, cross-run rejection except declared lineage references. |
| V02 | World/domain validators and geometric predicates | Nonfinite/invalid bounds, outside points, forbidden footprints, complete path segments, and legal outer boundary points. |
| V03 | Tagged type state and derived status | Every type/status/life combination; reject incompatible human/zombie fields and out-of-range life. |
| V04 | Terminal death reducer | Attempts to act/heal/convert after death; duplicate lethal events; permanent frozen type/location; cancelled deadlines. |
| V05 | Active episode index | Exactly one episode iff living infected human; clear current references after cure/conversion/death; preserve historical states. |
| V06 | Episode timers and closure | Exact onset-plus-incubation deadline, strictly early cures, one closure only, cure then reinfection with a new identity. |
| V07 | Atomic conversion transaction | Preserved ID/location/current life/stamina; exactly one inventory drop; retirement of role/model/actions; fresh zombie memory; no hidden healing. |
| V08 | Assignment registry | At most one compatible role and one required living model; assignment interval/history checks; dead cleanup; role intervention without replenishment. |
| V09 | Frozen action registry and admission/resolution contracts | All 29 handlers registered; capability/target/parameter errors rejected; all role actions exercised; no policy bypass. |
| V10 | Active-action slot, scheduler, cooldowns | Overlap versus touching boundaries; no zero-time action loops; future cooldown rejection; reservations retained only while needed. |
| V11 | Continuous stamina/hunger evaluators and starvation queue | Long idle intervals, partial rest/motion, hunger saturation, exact damage recurrence, eating reset, no negative or over-cap values. |
| V12 | Resource transaction ledger and capacity checks | Initial + intervention additions = current + consumption; competing pickup/transfer; capacity changes; reservations not double-counted. |
| V13 | Reservation ownership ledger | Items, biomass, and charges cannot be double reserved/spent; release in source holder on cancellation; no orphan reservations after actor death. |
| V14 | Trajectory admission and interruption | Per-segment speed, paths with legal endpoints crossing walls, dash speed/cost, dynamic obstacle stop offset, and mid-segment queries. |
| V15 | Observation builder and policy-visible result filter | Occlusion, visible geometry portions, stale reports, equal masks for equal observations, private memory isolation, hidden target failure redaction. |
| V16 | Keyed random service and outcome ledger | Probability endpoints 0/1, clamping, distinct hit/exposure draws, no draw after lethal hit, source-event linkage, worker-count independence. |
| V17 | Damage/healing reducers | Half-up integer rounding, resistance cap, actual versus raw/mitigated damage, starvation bypass, capped healing, no revival. |
| V18 | Damage/death/exposure ordering | Lethal bite/spit makes no infection draw; nonlethal exposure creates at most one episode; reinfection only after prior closure. |
| V19 | Reciprocal encounter index and arbitration | Winner hit or miss, invalid-first resolution, unequal durations, touching intervals, ties, and cancellation reason precedence. |
| V20 | Barrier reducers and spatial predicate dependencies | Gate integrity/mode correspondence, occupied closure/repair, intact overlapping barricade, simultaneous construction, shared-edge rules. |
| V21 | Death-to-remains mapping and biomass ledger | Exactly one remains entity per death, four initial biomass, simultaneous feeding, exhaustion, no effect on dead identity or population count. |
| V22 | Exact clock, continuous anchors, event phases | Same-time expiry/starvation/recharge/conversion/intervention/action boundaries; decision-frequency independence; lazy query versus full advancement. |
| V23 | Initializer and baseline importer | Exact populations/roles/infection/resources, 2 m/15 m distances, no initial zombie inside shelter, geometry/connectivity, and explicit placement-distribution reporting. |
| V24 | Transaction/event ledger and reconstruction | Acyclic causes, complete action failures/cancellations, monotone commit order, random-time replay, durable crash recovery, and branch provenance. |
| V25 | Central derived-state functions | Recompute status/speed/sense/resistance/progress/capacity totals from canonical facts; invalidate caches after effects, roles, death, and conversion. |

## 4 Required integrated scenarios

The following cases supplement individual action tests and reproduce ontology worked cases A–K where applicable.

| Scenario | Expected evidence |
|---|---|
| Nonlethal bite, cure, reinfection | Separate hit/exposure records; correct conditional probability; original episode closes once; later successful exposure starts a different episode. |
| Cure completes at conversion deadline | Conversion phase wins; current life/stamina persist; Doctor supplies are released; no zombie cure. |
| Lethal bite of a five-life human | Actual damage is five; terminal human death; no infection draw; one inventory drop and one remains entity. |
| Reciprocal melee/claw with ten-life actors | At most one valid winning attempt, including when it misses; no two effects from the overlapping pair. |
| Opponent attack is invalid at its earlier completion | Invalid attempt does not cancel the later reciprocal attack; later validity is evaluated from its actual current state. |
| Two pickups of one item, then winner converts | One reservation; losing claim spends no stamina; conversion releases the stockpile item and drops only carried inventory. |
| Multiple transfers to nearly full inventory | Serializable completion order; no overcapacity; failed transfer returns its exact reservation. |
| Treatment and healing on the same infected target | Cure affects infection only; first aid affects life only; completion revalidation uses the changed target. |
| Closed gate with legal movement endpoints on opposite sides | Crossing path rejected; opening makes a legal route; overlapping intact barricade still blocks it. |
| Shelter entered by a zombie | Ordinary sensing/combat applies inside; closing the gate grants no immunity. |
| Gate closes ahead of a moving agent | Evaluate occupancy at closure; if legal, reschedule the moving agent's path stop before contact and preserve actual distance cost. |
| Building versus stockpile creation at one footprint | Spatial predicate conflict prevents an intact new barricade from enclosing a nonempty stockpile. |
| Spitter spends, misses, fails, and recharges | Miss consumes; invalid target releases; first spend schedules recharge; later spend does not postpone it; role loss cancels recharge. |
| Tyrant dies after rally | Eligible recipients retain effect until expiry; actor result never discloses hidden recipients; no forced behavior. |
| Hunger from baseline t=0 to t=1610 | Hunger reaches 100 at 1600; first damage at 1610; eating at 1609 prevents it; same-time food follows that tick. |
| Five conversions and three other human deaths | 777 healthy, 15 infected, 205 living zombies, three dead identities; total 1,000; remains excluded from population. |
| Horizon reached during treatment/movement | Final snapshot preserves unresolved occurrences, reservations, trajectories, and timers; no fabricated completion. |
| Checkpoint during a busy mixed-role scene | Resume matches uninterrupted deterministic execution, including effects, pending claims, signals, recharge, and model memory. |
| Multiple workers and deliberately reordered worker completion | Same canonical semantic event stream, RNG records, and final state as serial execution. |
| Policy failure and storage failure | Policy failure produces a recorded fallback wait; storage failure stops at the last durable revision without a false completed status. |

## 5 Visualization and GUI acceptance

Source: the new Visualization & GUI requirement in [zombie_game_plans.md](zombie_game_plans.md) and the design in [implementation plan Section 13](task_2_implementation_plan.md#13-visualization-and-gui). These are proposed acceptance tests for Stage 2, not tests already executed against a GUI.

| ID | Area | Required scenario and evidence |
|---|---|---|
| G01 | Graphical configuration and CLI parity | Load the baseline, change legal parameters, save/import/export the configuration, and launch from the GUI. The resolved configuration/fingerprint, seed, initial state, and semantic results match the corresponding CLI run. Viewer layout and pacing do not enter the scenario fingerprint. |
| G02 | Validation and initialization preview | Show field-level and summary errors for invalid counts, role/type combinations, parameter domains, geometry, and unavailable models. Previewing does not advance the live RNG; preview reuse requires matching seed/configuration fingerprint. Sampling failure never silently changes counts/distances. |
| G03 | World rendering and agent inspection | Render all environment types and distinguish type/status/role with labels or symbols as well as color. Select/follow/search an agent through movement, infection, conversion, and death; compare its displayed fields and active/reserved resources with the selected committed revision. Rendering never makes remains a living agent or marker size a collision radius. |
| G04 | Cohort definitions | Compare a fixed initially-infected cohort with a dynamic currently-infected cohort across cure, conversion, reinfection, role changes, and death. Verify membership, denominators, event counts, overlapping-cohort labels, and human-versus-identity survival censoring against saved definitions. |
| G05 | Linked statistics and cursor consistency | Cross-select a chart time, agent, or event and verify linked panels use the same run/time/revision. Population totals, incidence, resources, and sampled summaries match ledger-derived measurements. Delayed metrics expose their watermark rather than appearing current. Cross-run comparison displays separate revision cursors and explicit time alignment. |
| G06 | Pause, stepping, pacing, and restart | Pause immediately around cure/conversion and food/starvation deadlines; step one atomic transition or one complete timestamp. Verify phase ordering, immediate cleanup, and preserved pending work. Wall-clock pause/pacing produces no wait actions, extra biological time, or altered random sequence; a checkpoint with an unfinished timestamp resumes correctly. |
| G07 | Replay versus live execution | While a managed run continues, pause playback, seek backward/forward, navigate events, and return to live. The live state is unchanged by viewing. Replay invokes no policies/random draws, respects pending actions at the horizon, and uses recorded segments/discontinuities instead of extrapolating unknown state. |
| G08 | Command lifecycle and concurrency | Retry a start, stop, branch, or intervention after a lost acknowledgement; apply it at most once. Inject crashes after effect/run creation and before outcome acknowledgement; atomic command commits or journal reconciliation recover the same result without duplicate effects, child runs, or workers. Test conflicting tabs/CLI commands, stale control generations/revisions, pending/applied/rejected status, and correct effective time/revision. Disconnecting the viewer does not stop a run. |
| G09 | Streaming and seek recovery | Delay, omit, duplicate, and reorder scene deltas; missing bases trigger a full snapshot and do not create mixed state. Old seek responses cannot overwrite a newer selection. Verify large IDs/revisions and exact time strings round-trip without browser numeric rounding. |
| G10 | Event and causal timeline | Inspect a reciprocal attack, its losing cancellation, and a lethal hit's cleanup. Show the correct ordered starts/results/causes and navigate before/after revisions, including multiple events sharing a timestamp and multiple effects in one atomic transaction. |
| G11 | Observation perspective | Compare the recorded-agent-observation view with the exact decision input, including occlusion, dated signals, and unseen targets. Switching from researcher view clears privileged overlays/inspector caches. Renderer selection, global charts, and GUI queries never enter a policy's observation or private memory. |
| G12 | Tuning existing instances | Change semantic parameters through Edit as new run, a branch, or a supported scheduled intervention. Preserve the original run's frozen configuration/history and validate intervention time/targets/invariants. A model change has an explicit event and memory policy; display settings remain presentation-only. |
| G13 | Observer independence | Run the same deterministic seed with no GUI, live follow, different display/pacing rates, exports, and a slow subscriber. Compare canonical semantic histories and final states, excluding the separate control audit. Both live-state backends and supported worker counts behave equivalently. |
| G14 | Responsiveness and bounded work | Measure the Section 13.6 frame/input/acknowledgement targets for 1,000 agents and profile 10,000 with aggregation. Exercise multiple panels, long timelines, rapid scrubbing, cohort changes, and slow/disconnected clients. Buffers and cancelled-query work remain bounded; coalescing affects presentation only, and lag/aggregation are visible. |
| G15 | Accessible and actionable workflows | Complete the primary workflow using keyboard controls in supported desktop Chromium/Firefox builds and narrow windows. Verify labels, focus, non-color status indicators, reduced motion, accessible data tables, useful validation/errors, progress/cancel states, and disabled inapplicable actions. |
| G16 | Exports and complete walkthrough | Through the GUI, launch the baseline, inspect an infection outcome, compare cohorts, pause/step a deadline, replay, create a changed instance, and export results. Reconstruct the exported scene/chart/table/animation from saved run/revision/interval, filters/cohort, sampling settings, and visualization version. Cancelling an export leaves the simulation and history intact. |

Use protocol/service contract tests for commands and data projections, browser integration tests for user workflows and reconnection, and deterministic scene/plot fixtures for visual comparisons. Compare numeric/semantic data directly as well as using screenshots; a plausible-looking image alone cannot establish correct counts, hidden-state handling, or event order. Keep renderer-frame performance separate from simulation throughput and history completeness.

## 6 Release evidence

The release report will name the configuration, source revision, dependency locks, command or GUI workflow, seed, backend, worker count, and output artifact for each acceptance category. It will separate existing formal-package checks, new simulator contract tests, stochastic checks, benchmarks, training smoke results, and G01–G16 GUI results. GUI evidence also identifies browser/OS/hardware, view settings, screenshots or recordings, projection/command logs, and measured rendering/interaction performance.

No passing finite test suite will be described as a proof of all possible simulation histories. Known limitations, including practical placement sampling and any nondeterministic model execution, remain attached to the runs they affect.
