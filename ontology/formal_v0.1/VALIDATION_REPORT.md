# Validation report

Overall result: **PASS — 62/62 recorded checks met their expected outcomes.**

Execution timestamp (UTC): `2026-11-13T03:09:07.701236+00:00`.

Expected-failure fixtures count as successful tests only when they fail at the named expected constraint. A validation exception or an unrelated violation alone is not counted as a successful negative test.

## Tools and reproducibility

- Python: `3.12.16 (main, Nov 11 2026, 00:15:59) [Clang 23.1.3 ]`
- RDFLib: `7.6.0`
- pySHACL: `0.40.2`; SHACL Core/SPARQL, explicit RDFS inference; SHACL-JS disabled.
- Owlready2: `0.51` supplies the HermiT/OWLAPI JAR. The actual checks call HermiT and OWLAPI through `OwlCheck.java`.
- Java: `openjdk version "21.0.13.0.3" 2026-10-24`
- HermiT JAR SHA-256: `97e53f519720a0a2e328556e03b806aa239347c85e57637a935e6433ed2ad3a8`

The full [machine-readable report](reports/validation.json) records versions, SHA-256 values and individual outcomes. Each SHACL fixture has text and RDF validation reports under `reports/`. OWL reports identify profile violations, consistency and unsatisfiable classes.

## Results

| Check | Result |
|---|---|
| Source Markdown unchanged | PASS |
| Current plan reference and hash verified | PASS |
| OWL Turtle and RDF/XML equivalent | PASS |
| OWL 2 DL profile: core | PASS |
| OWL core logically consistent | PASS |
| All intended named classes satisfiable | PASS |
| Infection-capable action classification | PASS |
| OWL 2 DL profile: inference | PASS |
| Doctor and infected state classifications inferred | PASS |
| Role and type capabilities inferred | PASS |
| OWL 2 DL profile: conversion_history | PASS |
| Time-indexed human/zombie history consistent | PASS |
| OWL 2 DL profile: invalid_state | PASS |
| Contradictory Human/Zombie state rejected | PASS |
| OWL 2 DL profile: impossible_extension | PASS |
| Impossible extension detected before instantiation | PASS |
| Every embedded SPARQL constraint parses | PASS |
| Same-actor overlapping intervals detected | PASS |
| Touching action intervals do not overlap | PASS |
| Two reciprocal misses still conflict | PASS |
| One cancelled reciprocal attempt is allowed | PASS |
| SHACL meta-validation and baseline catalog conformance | PASS |
| Baseline configuration SHACL conformance | PASS |
| Baseline population allocations | PASS |
| Baseline portable-resource totals | PASS |
| Baseline geometry bounds and nonoverlap | PASS |
| Baseline shelter connectivity | PASS |
| SHACL: valid_state | PASS |
| SHACL: valid_treatment | PASS |
| SHACL: valid_conversion_preserves_identity | PASS |
| SHACL: valid_death | PASS |
| SHACL: missing_life | PASS |
| SHACL: life_above_100 | PASS |
| SHACL: position_outside_world | PASS |
| SHACL: dead_with_positive_life | PASS |
| SHACL: human_with_tyrant_role | PASS |
| SHACL: infected_without_episode | PASS |
| SHACL: reservation_exceeds_stock | PASS |
| SHACL: inventory_over_capacity | PASS |
| SHACL: duplicate_agent_id | PASS |
| SHACL: resurrection | PASS |
| SHACL: conversion_heals | PASS |
| SHACL: conversion_retains_role | PASS |
| SHACL: conversion_wrong_deadline | PASS |
| SHACL: treatment_at_deadline | PASS |
| SHACL: treatment_free_supply | PASS |
| SHACL: treatment_reservation_missing | PASS |
| SHACL: treatment_no_stamina_cost | PASS |
| SHACL: treatment_out_of_reach | PASS |
| SHACL: treatment_heals_life | PASS |
| SHACL: treatment_missing_cure_record | PASS |
| SHACL: treatment_dead_actor | PASS |
| SHACL: treatment_invalid_duration | PASS |
| SHACL: treatment_miss_invalid | PASS |
| SHACL: causal_cycle | PASS |
| SHACL: treatment_missing_target | PASS |
| SHACL: treatment_wrong_intent_actor | PASS |
| SHACL: doctor_wrong_skill | PASS |
| SHACL: treatment_missing_cooldown | PASS |
| SHACL: orphan_resource | PASS |
| SHACL: valid_gate | PASS |
| SHACL: breached_gate_with_integrity | PASS |

## Execution location

Project root: /home/fmeng/workspace/zombie_game_simulation

Working directory: /home/fmeng/workspace/zombie_game_simulation

Python executable: /home/fmeng/workspace/zombie_game_simulation/ontology/formal_v0.1/.venv/bin/python

Java executable: /usr/lib/jvm/java-21-openjdk-amd64/bin/java

## Meaning of this result

The OWL core and supplied catalog are checked for OWL 2 DL conformance, logical consistency and satisfiability of intended named classes. Separate cases check capability/classification inferences, a consistent conversion history, an inconsistent Human/Zombie state, and an impossible extension class. SHACL validates the named example graphs and baseline data; geometry/arithmetic checks inspect the baseline RDF independently.

**This result does not establish that all Markdown requirements are fully formalized or that a simulator implements them correctly.** Refer to [COVERAGE.md](COVERAGE.md) for the explicit missing and partial behavioral checks. No game simulation, training run, statistical-power assessment, or exhaustive temporal/probabilistic verification was performed.

The source Markdown and plan are unchanged. The authoritative scope is TASK 1 in [zombie_game_plans.md](../../prompts/zombie_game_plans.md); the manifest records both source hashes.
