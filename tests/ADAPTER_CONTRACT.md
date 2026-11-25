# Framework adapter contract

This is a test interface for the implementation that will follow TASK 2's current
test-writing step. There is deliberately no simulator adapter in this repository
yet. The tests must be connected to the real framework; a replacement miniature
engine or canned expected responses are not conformance evidence.

## Python boundary

Provide an importable factory, for example `zombie_game.testing:create_adapter`:

```python
def create_adapter(*, workdir):
    return FrameworkTestAdapter(workdir=workdir)

class FrameworkTestAdapter:
    def execute(self, request: dict) -> dict:
        ...  # Arrange fixtures, call real interfaces, capture actual records.

    def close(self) -> None:
        ...  # Close browser, workers, files and stores, including failure paths.
```

The runner uses a fresh spawned process and temporary directory per case, sends
only `case['request']`, and applies assertions in the parent process. Expected
values, requirement tags and postchecks are not sent to the adapter. Responses
must be finite JSON data; quantities representing real numbers and semantic times
use exact decimal or rational strings. Counts/life/resources are integers; Booleans
are not integers. Identity and revision values are strings, including in JavaScript.

On POSIX the adapter runs in an isolated process session; leftover descendants are
terminated during cleanup, including timeout/error paths. Worker/browser processes
must remain in that session. The adapter still owns orderly shutdown and diagnostic
capture; process-group cleanup is a final containment measure.

`execute` must raise on unexpected errors or unsupported operations. An expected
validation rejection is returned only through the specified validation/error
operation. Returning `passed: true`, silently skipping a feature or synthesizing
missing observations is invalid. Selected cases with missing dependencies fail.
The included `tests.harness.fakes` are restricted runner probes, and the acceptance
CLI explicitly refuses them as an adapter.

Aliases such as `h`, `attack`, and `stock` name real entities/occurrences in an
isolated fixture. Normalize real IDs to these aliases consistently in every
reference. Newly generated identities remain unique. Keep a reversible alias map
in diagnostics. Do not erase ordering, causality or values when normalizing.

## Controlled world fixtures

For `kind: simulation`, `setup` describes world bounds plus lists of agents,
barriers, stockpiles and remains. Missing fields use the ontology's type/role
profile defaults; omitted stocks are zero, empty effects/cooldowns are empty maps,
and infection absence means no active episode. Explicit overrides always win,
including zero/false/null. Per-agent profile overrides such as
`base_damage_resistance` and `infection_resistance` are declared scenario variations.
They must pass through the same schema/derived-state machinery as user configuration.

An `infection: {onset_at, incubation_duration}` fixture creates an actual episode
with its exact deadline and timer. Explicit `episodes`, `infection_episode`,
`model_assignment`, effects, cooldowns and reservations allow valid checkpoint-like
states and invalid-input probes; never silently repair invalid probes. A dead
source-agent/remains fixture represents a previously committed death with matching
records. Do not revive it or give it an active role/model. Authoring helpers are in
[spec/dsl.py](spec/dsl.py); fixture values are not production code.

Small controlled worlds deliberately permit close initial contact and nonbaseline
counts. They test reachable local states, not the baseline population sampler.
`preset: baseline_v0.1` uses the actual baseline importer/sampler and all its initial
placement constraints. Do not impose baseline 2 m / 15 m spacing on microfixtures.

`config.decision_mode: scripted` installs a policy fixture that takes only the
explicitly supplied decisions. It prevents incidental autonomous actions from
obscuring a mechanical contract. Clocks, hunger, conversions, recharge, action
admission and all effects still run in the real engine. `decision_mode: model`
uses the assigned real model, including versioned default policies when no custom
assignment is supplied. No adapter-level action bypass is permitted.

## Simulation operations

| Operation | Meaning |
|---|---|
| `submit` | Submit the provided intent through actual observation/capability/admission checks at current semantic time. `id` identifies the intent and its admitted occurrence alias. |
| `submit_batch` | Present all `intents` at the same decision boundary, before committing simultaneous claims. Input list order must not become arbitration priority. |
| `advance` | Advance to absolute exact `to`, including all due phases at that time, unless a defined run stop is reached. No wall-clock sleep or synthetic wait action. |
| `snapshot` | Capture full committed state under the given `label`. Queries do not execute decisions or advance biological time. |
| `observe` | Capture the actor's actual policy-visible observation under `label`. No global-state fields may be filled in. |
| `intervene` | Submit a versioned scheduled `{id, at, change}` through the authorized intervention service. Requires `interventions_enabled`. |

Intent `parameters` follow each ontology action contract. Movement paths are lists
of `{x, y, offset}`, with offsets relative to admission and an explicit duration.
Resource actions use `resource_type` and positive integer `quantity`; construction
uses `center: [x,y]`, `orientation: x|y`, and `length`. Signal payload coordinates
include their original observation time. The input does not grant knowledge of an
unseen target merely by naming its alias.

Intervention kinds include `replace_role` (`agent`, `role`, optional declared
`drop_order`), `replace_model` (`agent`, `model_id`, `model_version`,
`memory_policy`), and resource additions described by the system cases. Role/model
changes call the real lifecycle/capacity logic; no replenishment is inferred.
Return outcomes in `interventions[id]` including status and effective boundary.

Optional `draws` inject **values**, keyed by `{intent, channel, value}`, into the
real keyed RNG service for `hit` and `infection`. The engine must still compute
probabilities, decide whether a draw is permitted and record its actual result.
Unused supplied values are not extra actual draws. Unspecified stochastic channels
use the recorded seed. Never force an outcome or borrow the expected probability.

## Simulation response

Always return these collections, including empty collections:

```json
{
  "snapshots": {}, "intents": {}, "occurrences": {}, "observations": {},
  "events": [], "random_draws": []
}
```

- `intents[id]` records admission status, normalized rejection reason and actor.
  Accepted intents create `occurrences[id]`; rejected intents do not.
- Occurrences record actor/target/action, start/scheduled end, costs/reservations,
  result and causal records. `result: IN_PROGRESS` has no `resolved_at` field.
  Final results include `SUCCEEDED`, `MISSED`, `FAILED_PRECONDITION`,
  `PARTIAL_BLOCKED`, `CANCELLED_BY_CONFLICT`, `CANCELLED_BY_DEATH`, and `CANCELLED_BY_CONVERSION`, as asserted
  by cases. Preserve actual outcome detail even where the policy-visible result
  must be redacted.
- `observations[label]` contains actual self/local agent/resource/barrier/signal
  records. Local agents are keyed by ID and include `id`. Opponent signal `kind`
  is `NOISE`; do not retain the allied payload. Signal records use
  `position_at_emission`, `sender_type_at_emission`, emitted/expiry times and dated
  payload; they are not live target trackers.
- `events` is an ordered ledger. `causes` contains preceding **event IDs** only;
  occurrence/intervention causes use separate typed reference fields. Convert a
  backend's heterogeneous edges losslessly into these fields. Ledger order is a
  valid topological order; retain phase and transaction/revision order.
- `random_draws` contains actual hit/infection Bernoulli records with `intent`,
  `channel`, `probability`, `value`, `outcome`, and source event linkage. Outcomes
  use `value < probability`. Other initialization/policy/arbitration draws belong
  in separate typed RNG collections and remain in complete semantic history.

Every snapshot has `time`, `revision`, `world: {length,width}`, and keyed `agents`,
`barriers`, `stockpiles`, `remains`, `episodes`, `reservations`, `signals` maps.

| Record | Required normalized fields |
|---|---|
| Agent | `id`, `type`, `status`, nullable `role`, integer `life`, `stamina`, `x`, `y`, nullable `active_action`, `cooldowns`, `effects`, nullable `infection_episode`; live model assignment and derived profile fields when inspected. |
| Human | Additionally `hunger`, `inventory`, `reserved`, `carry_capacity`; inventories contain all three portable resource keys. Zombie records omit human-only fields. |
| Assignment | `model_assignment: {model_id, model_version, ...}`; model memory remains per identity and is recorded for exact restart. Dead assignment is absent/null. |
| Barrier | `kind: Obstacle|Gate|Barricade`, `rect: [xmin,ymin,xmax,ymax]`; gate/barricade integer `integrity`, `max_integrity`; gate `mode`. |
| Stockpile | `id`, `x`, `y`, `stock`, `reserved`. Reservations are part of physical stock, not extra stock. |
| Remains | `source_agent`, `x`, `y`, integer `biomass`, `reserved_biomass`; preserve exhausted identity/history. |
| Episode | `agent`, `onset_at`, `incubation_duration`, `conversion_due_at`, `outcome`, optional closure boundary. Historical closed episodes remain recorded. |

Missing optional current references are null; inapplicable type fields and expired
effects are omitted. Effects/cooldowns are maps keyed by the names asserted in the
cases. Real scalars may be exact strings; approximate checks declare their own
tolerance. A full-phase snapshot has already resolved conversions due at its time;
a GUI snapshot paused within a timestamp can have a due episode awaiting its phase.

## Validation, workflows and browsers

`kind: validation` calls the real configuration/initial-state validator with the
supplied fixture. It returns `validation: {valid, issues}`; each issue has a stable
normalized `code` and actionable field path/message. Cases assert categories
including `INVALID_DOMAIN`, `DUPLICATE_ID`, `INCOMPATIBLE_ROLE`,
`INVALID_TYPE_STATUS`, `INVALID_EPISODE`, `INVENTORY_CAPACITY`, `INVALID_GEOMETRY`,
`INVALID_GATE_STATE`, `INVALID_REFERENCE`, and `INVALID_RESERVATION`. Unexpected
exceptions are test failures, not validation success.

Workflow/browser operations and evidence requirements are specified in
[SYSTEM_OPERATIONS.md](spec/SYSTEM_OPERATIONS.md),
[RESEARCH_OPERATIONS.md](spec/RESEARCH_OPERATIONS.md), and
[browser/README.md](browser/README.md). Default-policy witness/encoder contracts
are in [POLICY_OPERATIONS.md](spec/POLICY_OPERATIONS.md).
Focused RDF exports are specified in [FORMAL_OPERATIONS.md](spec/FORMAL_OPERATIONS.md);
the parent runner parses them and runs the trusted repository SHACL shapes.
Snapshots designated by `snapshot_paths` receive the same independent checks;
`baseline_paths` also checks the literal baseline geometry/counts/resources and
pair distances. Postcheck metadata stays in the runner, outside adapter requests.

## Reviewing future interface changes

Normalize alternate production API names in the adapter. If a test prescribes an
unreviewed design choice or the ontology changes, update its case and traceability
with an explicit rationale; do not hide disagreements behind catch-all skips or
weaken assertions merely to match the implementation. Keep failing diagnostics,
actual requests/results and artifacts when investigating conformance failures.
