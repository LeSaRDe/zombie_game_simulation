# Parallel computation and canonical effects

The coordinator owns semantic time, reservations, ID allocation, random outcomes,
completion validation, lifecycle transitions, and ledger publication. Process workers
receive detached records and return proposals. Independent experiment replications,
policy batches, continuous actor materialization, and a bounded class of independent
action effects can use real processes.

`parallel.conflict_components` connects write/read and write/write access conflicts;
read/read access alone is independent. Tokens describe concrete actors/targets and
shared predicates. At one completion frontier, every action reads the geometry token,
so a barrier mutation couples it with every simultaneous line-of-sight consumer.
Unsupported effect handlers write a shared opaque-effect token and conservatively
force serial handling of that frontier. These declarations prioritize a valid serial
meaning over speculative concurrency.

Five deterministic effect calculations have worker support: eating hunger reduction,
first-aid healing, smash/demolish integrity damage, and barrier repair. Only singleton
independent components are submitted. Workers compute bounded final values and actual
amounts, while the coordinator retains resource release/consumption, gate mode changes,
biological clocks, action completion and publication. This is action-effect computation,
in addition to parallel movement/rest/hunger materialization.

Immediately after ordinary completion validation and before mutation, the coordinator
rebuilds a fingerprint of the exact actor/target/profile/parameter inputs. A matching
proposal supplies the computed effect; a mismatch discards it and invokes the original
serial formula. Fingerprints exclude incidental ledger revisions but include all effect
inputs. A worker failure publishes no partial result and falls back to serial handlers.
Consumption, fallback and worker-batch counters are execution diagnostics outside the
semantic ledger.

`implementation_checks/effect_parallel_check.py` exercises four disjoint Doctor–patient
pairs. Runs with 1, 2 and 4 workers have identical semantic ledgers and final state after
normalizing distinct run IDs. Four prepared heals are consumed in each run; the process
runs use a real worker batch. Deliberately corrupting one read fingerprint causes one
serial fallback and preserves the same ledger/state. The machine-readable evidence is
`artifacts/model_checks/effect_parallel.json`.

This implementation is deliberately conservative: mixed unsupported frontiers serialize,
and process overhead can exceed the benefit of small arithmetic tasks. Throughput claims
require measured scenarios; the equivalence check establishes operational semantics,
not a universal performance gain.
