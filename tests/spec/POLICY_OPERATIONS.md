# Default-policy and encoder acceptance contract

Status: **proposed D7 test interface, ready for review; framework execution has not occurred.**

The implementation plan §8 requires a focused demonstration of every action by
the default models. An action-handler test cannot establish this. The bank in
[`policies.py`](policies.py) supplies 30 small worlds, concrete objectives, and
bounded execution. It accepts different strategic choices in individual worlds,
but requires an actual selected, admitted, resolved occurrence for each of the
29 actions somewhere in its documented useful contexts. No expected action,
utility override, candidate restriction, or desired selection is sent to a
default model.

Two acceptance cases use this interface:

| Case | Actual product exercise | Independent checks |
|---|---|---|
| `POL_DEFAULT_WITNESS_BANK` | Run `HumanDefaultModel`/`ZombieDefaultModel` with the published default parameters in 30 contexts. | Verify concrete input state, unchanged default parameters, utility arithmetic, actual chosen intent, admission/occurrence linkage, and real action effects; require all 29 witnesses. |
| `POL_ENCODER_ALL_ACTION_ROUNDTRIPS` | Encode and decode one explicit typed candidate per action, attempt padding decoding, then execute the decoded candidate. | Exact lossless parameter/target mapping, padding rejection, and the complete independently written success oracle for every action. |

The second case deliberately supplies candidates because it tests the encoder,
not model choice. It must never be used as evidence for the first case.

## Default bank operation

`policy.run_bank` reads the named list under request `setup`, runs each context
independently, and captures raw results under `captures/<label>`. Each context
contains:

- `id`, `world`, `actor`, `model`, and deterministic `seed`.
- `max_decisions=8` and `horizon="35"`. Stop when either bound is reached. Finish
  the selected actor's already admitted action only if it resolves at or before
  the horizon; retain later actions as pending. Do not offer more decisions
  after the decision budget, and do not manufacture a completion at the bound.
- `memory_seed`, described below. All other agents are scripted and receive no
  unrequested decisions.
- `background_events`: actual engine admissions for other agents at specified
  times. The approaching-enemy context starts a legal two-second movement at
  time zero and a claw at time two. Process these scheduled inputs before the
  corresponding default decision boundary. A failed background admission is
  recorded normally; it must not be silently repaired.

Install and call the real versioned default model. Resolve its default parameter
catalog through the product's model registry independently of each run. Use its
normal candidate generator, feature computation, score/ranking, tie-breaking,
and private memory. Do not call a scripted replacement policy. Do not filter the
candidate set to the action a test reviewer hopes to see. Any normal pruning
must be part of the published default model/version and visible in its model
documentation. Engine legality checks still apply.

An adapter may translate the interface's objective schema into the product's
public model-memory representation. It must not turn an objective into an
action command. `recent_reports=[]` means no prior reports have been sent.
All entity/resource facts must come from the real initial local observation;
no invisible target location or researcher state may be copied into memory.
Objectives prescribe a goal, not a report that something was observed:

| Objective kind | Fields | Meaning |
|---|---|---|
| `hold_location` | `position`, `until` | Keep a rendezvous/defensive location until a time, while permitting recovery, communication, or other useful actions there. |
| `reach_location` | `position` | Navigate toward the goal; it does not declare the route traversable or reveal barriers. |
| `seek_resource` | `resource_type` | Seek useful resources using actual observations and remembered discoveries. |
| `supply_ally` | `target`, `resource_type` | Consider supplying the currently visible ally when useful and feasible. |
| `protect_region` | `rect` | Value maintaining a defensible region; this gives no shielding, ownership, map knowledge, or attack immunity. |
| `explore_frontier` | `position` | Investigate an uncertain direction; the coordinate does not reveal entities there. |
| `null` | — | Start with the default model's ordinary objective selection. |

These memory semantics are a **proposed D7 acceptance interface**, not ontology
rules. The plan leaves exact policy weights, thresholds, and memory layout open.
Review the objective mapping and the utility diagnostics before implementing
the models. The test freezes no numeric preference weights and no mandatory
winner for a single context. If a sensible default never demonstrates an action
in this finite bank, the test fails with the missing actions. Review/add a
documented useful context or revise the actual versioned policy; do not add an
adapter-only preference or convert the failure into a skip.

## Reviewable witness contexts

The expected-action column is test-side metadata only. A context can make a
different legitimate choice without failing by itself. Coverage is evaluated
across the bank, and a witness counts only in one of its documented contexts.

| Context | Potential demonstrated actions | Why the behavior is useful |
|---|---|---|
| Safe rendezvous | wait | Full energy, no threat, short location commitment. |
| Depleted rendezvous | rest | Zero energy in safety. |
| Distant supplies | move, pickup, eat | High hunger, visible food 20 metres away. |
| Fresh human warning | signal | Reporter sees an enemy its nearby ally cannot see. |
| Nearly finished opponent | melee | Adjacent ten-life zombie can be killed promptly. |
| Food at hand | pickup, eat | Hungry actor has no food but a reachable stockpile. |
| Medicine needs space | drop, pickup, first_aid | Material fills capacity while medicine is needed for a severe wound. |
| Hungry ally | transfer | Satiated actor carries food; adjacent ally is near starvation. |
| Own urgent meal | eat | High hunger with food already held. |
| Own severe wound | first_aid | Uninfected, injured actor has medicine and no threat. |
| Closed route | open_gate, move | A wall leaves only a closed gate on the useful route. |
| Exposed refuge | close_gate | A nearby outside threat faces an open defensive doorway. |
| Fragile prey | claw | Claw can kill faster than a nonlethal bite. |
| Healthy prey; armored healthy prey | bite | Healthy durable targets make transmission valuable. |
| Remains for recovery | feed | Both life and energy are scarce; biomass is reachable. |
| Weak blocking door | smash | One ordinary barrier hit can clear the route. |
| Curable neighbor | treat_infection | Visible adjacent infection has enough treatment slack. |
| Susceptible defender | prophylaxis | Healthy ally faces a visible exposure threat. |
| Decisive heavy hit | power_strike | One strike can kill faster than two ordinary melee attempts. |
| Incoming defended contact | guard | Temporary resistance can precede an observed approach while holding position. |
| Uncertain frontier | recon | Information can be gathered beyond ordinary Scout sensing before moving. |
| Wide Scout report | mark_target | The ally is visible but beyond the ordinary signal's 40-metre range. |
| Unprotected chokepoint | build_barricade | A legal gap has no gate to close or repair. |
| Damaged refuge | repair_barrier | One material can restore a useful damaged gate. |
| Ready zombie allies | rally | Several nearby allies have contact opportunities. |
| Strong blocking door | demolish | High integrity rewards greater damage efficiency. |
| Distant Runner prey | dash | Extra speed can shorten approach with follow-up energy remaining. |
| Ranged exposure | spit | Full charges provide an immediate ten-metre opportunity. |
| Wide hunt report | scream | A visible ally lies beyond ordinary signal reach. |

Guard, bite, drop, reporting, and exploration involve real strategic tradeoffs.
The suite makes no optimality claim. A passing witness needs the actual selected
intent and resulting state changes, not a label stating that the action was
available or executable. Valid attack misses count as executed attempts only
when the matching recorded hit draw says miss and the ordinary stamina/charge
costs and lack of damage are verified.

## Captured default-policy facts

The result has `default_models` and `contexts` maps. The registry capture is:

```json
{"HumanDefaultModel": {"version": "<real version>", "parameters": {"weights": {"survival": "<value>"}}}}
```

`parameters` is the actual resolved default parameter object, including nested
weights/thresholds. Each context returns its installed model's `id`, `version`,
and full `parameters`, normalized `memory_seed`, the real simulation `trace`,
and `decisions`. The installed parameters must equal the independent registry
capture, including thresholds. Context-specific weight overrides are prohibited.

The trace uses the normal simulation response collections and must include
`snapshots/initial`. Capture a snapshot immediately before each chosen intent's
admission and immediately after its resolution, before the next actor admission.
These labels appear in its decision as `before_snapshot` and `after_snapshot`.
A pending/rejected occurrence has no completed witness and need not have an
after snapshot. Snapshot state and stochastic outcomes come from the engine.

Each decision records:

```json
{
  "id": "<decision alias>", "time": "0",
  "observation_id": "<entry in trace.observations>",
  "intent_id": "<entry in trace.intents and admitted trace.occurrences>",
  "selected_candidate_id": "<candidate alias>",
  "before_snapshot": "<label>", "after_snapshot": "<label if resolved>",
  "reason": "<actual chosen explanation>",
  "candidates": [{
    "id": "<candidate alias>", "intent": {"actor": "a", "action": "wait", "parameters": {"duration": "1"}},
    "observable_feasible": true, "reason": "<actual candidate explanation>",
    "terms": [{"feature": "<feature name>", "value": "0.5", "weight_path": "/weights/survival", "contribution": "<actual contribution>"}],
    "score": "<actual score>"
  }]
}
```

The public observation has `self_state/id`, `time`, and normal local fields.
Each chosen intent records `decision_id`, `actor`, `action`, optional `target`,
`parameters`, and admission `status`; each occurrence records `actor`, `action`,
and the usual timing/result fields. Intent aliases need not equal candidate
aliases; typed semantic contents must match exactly.

For the proposed utility diagnostics, normalized feature values are in `[0,1]`.
A signed parameter weight is resolved via `weight_path`; each contribution is
`value × weight`, and score is their sum. Nonlinear urgency transforms belong
inside the declared feature calculation. Bias/exploration terms, if present,
are explicit features with real configured weights. The checker recomputes the
sum and requires a chosen feasible maximum; exact/near ties within `1e-9` may
use any seeded winner. It does not infer feature meanings from prose. The
versioned model documentation must define feature transformations and thresholds;
the concrete strategic contexts and action-effect checks supply the behavioral
oracle. This arithmetic interface is proposed D7 and must remain aligned with
the reviewed utility policy design.

## Encoder operation

`encoder.roundtrip_bank` reads 29 independent fixtures. For each, construct the
real observation from its world, encode the supplied candidate plus two padding
slots, decode every slot through the production decoder, and record the result.
Execute the decoded real candidate through ordinary admission, scheduling, and
resolution. Use the fixture's deterministic combat draws. Capture `admitted`
immediately after admission and `end` after its supplied duration, matching the
ordinary action oracle. Do not execute the original pre-encoding object.

Return `contexts/<fixture-id>` with:

- `decoded_intents`: the real decoded intent list, preserving IDs, targets,
  decimal path offsets, quantities, signal payloads, construction geometry, and
  durations exactly.
- `candidate_mask`: `[true,false,false]`.
- `index_to_intent`: `{"0":"a"}` for the supplied alias.
- `padding_rejected_indices`: `[1,2]`, captured from actual decoder rejections.
- `trace`: the real engine response for executing the decoded candidate.

The oracle checks exact decoded contents and all success assertions from
`actions.py`; reporting codec support or a successful roundtrip flag is
insufficient. Together with the real default-model bank, this covers both
candidate generation/selection and all 29 typed encoder mappings.

## Runner integration and harness tests

Add `policies` to `tests.suite.CASE_MODULES`. For each case's `policy_checks`,
resolve exactly one result at its `path` and call
`tests.policy_checks.validate_policy_result(result, spec)` after ordinary checks.
Missing captures, unsupported operations, missing witnesses, and invalid records
are failures, never skips.

`python -m unittest tests.harness.test_policies -v` tests only the independent
checker with tiny deliberately fabricated records. It verifies fail-closed
behavior for incorrect utility arithmetic, lower/masked choices, overridden
defaults, changed input worlds, changed engine intents, missing effects, missing
witnesses, and encoder mapping/padding errors. Its passing result is **harness
validation**, not default-policy, learning, or simulator conformance.
