# Acceptance adapter and normalization

The supplied acceptance suite is now connected to the production engine through
`zombie_sim.testing:create_adapter`. The runner sends request data only; assertions
and invariant oracles remain in the parent test process. The adapter imports no
test cases or expected outcomes.

The normalization version is `zombie-sim/acceptance-normalization-v1`:

- Fixture decimal/rational time strings remain exact times. Real-valued spatial,
  profile and stamina inputs are translated to the production numeric API.
- Barrier `kind`/`rect` maps to production `type`/`footprint`, stockpile `stock` to
  `inventory`, remains `source_agent` to `source_agent_id`, and assignment
  `model_version` to `version`. Output performs the inverse naming translation.
- Explicit intent aliases map to the actual admitted occurrence IDs. All
  references use the same reversible alias table, retained in each result.
- Actual floating-point results are represented by their shortest round-tripping
  strings. The adapter does not round results to expected constants.
- Researcher snapshots include actual private per-identity memory. Ordinary
  policy observations continue to exclude other identities' private memory.
- Known occurrence/intervention causal edges are retained as typed references.
  Unknown event predecessors are left visible to the independent causal oracle.
- Controlled Bernoulli requests inject values into the real keyed random service;
  production code still computes probability, decides whether a draw is needed,
  records the draw and determines its outcome. Unused values create no draws.

Controlled fixtures use the production `state_import` mode, implemented in
`initial_state.py`, to author validated reachable states with prior deaths,
remains, dated infection episodes, active effects, cooldowns and private memory.
It does not execute fake transitions or bypass action admission. Ordinary sampled
initialization retains its original restrictions. State import retains the
required gate/shelter relation and enclosure validation.

Run the entire supplied catalog with:

```bash
PYTHONPATH=src python -m tests.run_acceptance \
  --adapter zombie_sim.testing:create_adapter \
  --timeout 1800 --report tests/results/conformance.json
```

For a repeatable narrower run of every supplied simulation and validation request:

```bash
PYTHONPATH=src:. python scripts/run_simulation_acceptance.py
```

The latter is explicitly reported as partial catalog coverage. It runs the
unchanged suite assertions and independent raw-state/trace invariants. Unsupported
workflow capabilities and invalid fixtures are errors, never passing skips.

Policy and learning workflows bind through `testing_learning.py`. Default-policy
contexts install the same independently resolved parameters; only their public
high-level goals and actual local observations seed private memory. Candidate
scores, the selected ranked entry, typed intents, before/after states and real
draws are captured from the deployed model and coordinator. The typed candidate
codec used by Gym retains exact intents beside its lossy neural feature matrix;
every requested padding index is actually decoded and rejected.

Existing-run Gym and AEC attachment preserves world state and random streams.
The normalized `reward` is the production environment's undiscounted interval
return, with its discounted training reward separately exposed as
`discounted_reward`. Reward names map to the acceptance vocabulary while the raw
event-derived terms remain present. Continuous-time cutoff and conversion use
the production controller lifecycle. AEC captures the adapter's frozen raw
observations in the requested collection order.

Boundary probes are real registry plugins: exceptions, malformed decisions,
rejected paths, per-identity counters, and an intentionally unsupported live file
handle codec. The unavailable-model probe deletes its real artifact only after
successful initialization. Its fallback is therefore distinct from invalid
configuration rejection.

The training tier requires the learning environment and runs real recurrent PPO:

```bash
PYTHONPATH=src:. .venv-training/bin/python -m tests.run_acceptance \
  --adapter zombie_sim.testing:create_adapter --tier training \
  --timeout 1800 --report tests/results/training.json
```

Training captures the optimizer's actual update count and records each train,
validation and held-out seed access at the environment reset/evaluation call.
Checkpoint reload and each held-out evaluation execute in separate fresh
processes. No expected action or test assertion is supplied to the trainer.

For long workflows, `ZOMBIE_ACCEPTANCE_RPC_TIMEOUT` controls the isolated
coordinator's RPC timeout independently of the runner's `--timeout`. Set both
limits to the intended whole-case budget. Scratch storage follows Python's
normal temporary-directory selection; a tmpfs acceptance run establishes game
semantics and process recovery, not physical-disk throughput or power-loss
persistence. SQLite's configured synchronization mode remains unchanged.

Set `ZOMBIE_ACCEPTANCE_RETAIN_HISTORY=/absolute/output/directory` to retain
complete primary simulation ledgers before the runner removes its temporary
workspace. Only the top-level adapter enables this opt-in. After coordinators
close, SQLite backup copies each primary ledger, verifies it, flushes it to the
selected output filesystem, and records its revision, byte count and SHA-256 in
`retained-history.json`. Redundant checkpoint sidecars are omitted; every world
and runtime journal entry and event remains in the retained primary ledger.
Existing retained files are never silently replaced. This mechanism is generic
and does not inspect case IDs, expected outcomes or assertions.

## Evaluating captures from a completed retained workflow

`zombie_sim.testing_recovery:create_adapter` evaluates recorded workflow captures
without creating or advancing a simulation. Set `ZOMBIE_RECOVERY_LEDGERS` to an
explicit JSON mapping from the request's run aliases to retained primary ledger
paths. Use the original request and the original acceptance runner/validators.

The reader requires the exact resolved initial configuration, matching durable
script command identities and payloads, applied receipts through the latest
frontier, and an actual terminal horizon or extinction state. It verifies every
world/runtime delta checksum and complete revision/event sequences. Unsupported
operations, missing work, corruption and mismatched evidence are errors. All
snapshot fields, model memory and semantic event/revision naming are retained.
The source is opened read-only in a pinned transaction.

Diagnostics explicitly identify `recovered-capture-evaluation`. Such a result
validates the recorded completed execution; it must be reported separately from
the original runner invocation. A pending command must first be genuinely
continued through the normal runtime API. The reader never manufactures its
completion or substitutes a new initialized run. Small real workflows verify
capture equality, source-byte preservation and rejection of invalid evidence.
