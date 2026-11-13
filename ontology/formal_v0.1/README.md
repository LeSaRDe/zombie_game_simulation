# Zombie Game formal specification — 0.1.0

This package formalizes selected aspects of the unchanged `../zombie_game_ontology_v0.1.md` and checks them with real OWL/SHACL software. It is a **review release**, not a complete formal behavioral specification or a simulation implementation.

Read [VALIDATION_REPORT.md](VALIDATION_REPORT.md) for the actual results and [COVERAGE.md](COVERAGE.md) for what the results cover. All 29 actions have structured catalog definitions; none is claimed to have a completely formalized behavioral contract. Doctor treatment has the most detailed transition checks in this release.

## Files

| File | Purpose |
|---|---|
| `ontology.ttl` | OWL 2 DL classes, relationships, disjointness, restrictions and inference definitions. |
| `catalog.ttl` | Eight baseline roles, 29 actions, capabilities, numeric baseline parameters and possible effects. |
| `ontology.owl` | RDF/XML serialization of the same combined OWL core/catalog, checked for graph equivalence. |
| `shapes.ttl` | SHACL Core and SHACL-SPARQL constraints; constraint IRIs appear in diagnostics. |
| `baseline.ttl` | Initial world geometry, stockpiles, population allocations and scenario parameters. It does not instantiate 1,000 moving agents. |
| `baseline-summary.json` | Readable companion to the baseline graph. Validation reads the RDF, not this summary. |
| `examples/`, `examples.json` | Positive/negative data graphs and independently stated expected outcomes. |
| `coverage.json`, `COVERAGE.md` | Source-line traceability, invariant/action coverage and explicit limitations. |
| `reports/`, `VALIDATION_REPORT.md` | Actual machine-readable and human-readable validation results. |
| `manifest.json` | Source identity and SHA-256, namespace, registry counts and scope. |
| `build_spec.py`, `build_examples.py`, `build_baseline.py` | Rebuild the artifacts and fixed test data. |
| `validate.py`, `OwlCheck.java`, `check_baseline.py` | Repeatable validation and independent baseline checks. |
| `check_constraint_boundaries.py` | Isolated checks of overlapping/touching intervals and reciprocal misses/cancellation. |
| `document_package.py` | Regenerate coverage documentation and summarize the recorded results. |
| `package_release.py`, `SHA256SUMS.txt` | Create and verify the downloadable review archive and file checksums. |
| `requirements.txt`, `toolchain.json` | Exact Python versions and portable JDK provenance. |

`sourceText` annotations preserve the corresponding action prose for review. An annotation is not an executable constraint or a logical translation of that prose.

## Representation decisions

The local namespace is `urn:zombie-game:v0.1:`. It does not depend on a web server or claim a registered public namespace. OWL and SHACL share these identifiers. Turtle is a serialization, not another logic language. The standards used are [OWL 2 DL](https://www.w3.org/TR/owl2-syntax/), [SHACL Core/SPARQL](https://www.w3.org/TR/shacl/), and [RDF 1.1 Turtle](https://www.w3.org/TR/turtle/).

- `Agent` is persistent. `AgentState` carries biological type, status, coordinates, life, applicable role/model references, time and causal revision. HumanState and ZombieState are disjoint **state** classes, not permanent disjoint agent identities.
- Role definitions and action definitions are named individuals. Derived classes such as DoctorState, InfectedHumanState and InfectionCapableActionDefinition are classes. No class/individual punning is needed for the role registry.
- Biological type uses `biologicalType`; active role uses `activeRole -> roleDefinition`; the Markdown `ID` becomes `agent_id`; `run_id` becomes `inRun`; `last_state_event_id` becomes `lastEvent`. Human/zombie attribute prefixes are omitted because the state class establishes applicability.
- The record key for a state is `(ofAgent, atTime, revision)`. Distinct causal revisions at the same time allow valid pre/post states for an instantaneous event.
- `activeEpisode` is a fact about that particular state. An episode can later close without invalidating an earlier state. Episode closure carries both `ended_at` and `end_revision`.
- Inventory/stock and environment state records describe values at an observation point. Quantities reserved are subsets of total stock, not additional items. Shapes count reserved stock toward carried mass.
- Game real-valued fields use finite `xsd:decimal`; counts and life use `xsd:integer`. Decimal encoding avoids NaN/infinity. Computed infection progress is checked with absolute tolerance `1e-9` for finite-decimal serialization; this is a validation tolerance, not a different incubation rule.
- Type/role profiles grant **capabilities**. Inferring a capability does not establish the target, stamina, distance, visibility, cooldown or resource conditions for a particular attempt.
- Possible-effect categories classify action definitions; they do not assert that an action occurrence actually produced the effect. In particular, bite/spit are infection-capable but a miss or failed exposure creates no infection.
- No missing RDF statement is treated as a negative OWL fact. Required/absent fields are checked by explicit SHACL constraints. Distinct enumerated individuals are declared different where OWL identity reasoning would otherwise permit merging.

## Doctor treatment trace format

An occurrence records `actorStart` (before admission), `actorAfterStart`, `actorBeforeEnd`, and `actorAfterEnd`. The latter two are required only once resolved. Agent targets use corresponding start and before/after-end states. An intent and its self observation identify the actor and proposal time.

The treatment example pays stamina at admission, reserves but does not yet consume medicine, and consumes it only on successful completion. Its linked CureTransition references the exact episode and target states. Completing at the conversion deadline is rejected as a recorded success. Resource consumption at completion and the absence of an old active action are checked separately from the earlier stamina cost.

The state examples are focused synthetic records for conformance tests, not a complete replay log of the baseline scenario. Geometry/visibility evidence, full assignment history, all continuous changes and complete causal provenance are not certified by these examples.

## Validation procedure

1. Parse the RDF files; compare the OWL Turtle union with its RDF/XML serialization; verify the unchanged source hash.
2. Use OWLAPI to check the OWL 2 DL profile. Use HermiT for logical consistency, classification and satisfiability of the intended classes.
3. Run separate OWL cases for positive inference, valid conversion history, a contradictory state and an impossible unused extension class. The impossible class must be detected even though its ontology is still consistent with that class empty.
4. Meta-validate the SHACL shapes and parse every embedded SPARQL query, including those not reached by a particular fixture.
5. Validate `ontology.ttl + catalog.ttl + each example` using **RDFS inference only**. The vocabulary individuals are included in the input union. This avoids implicitly relying on an OWL reasoning pass to fill required data.
6. Require positive examples to conform. A negative example must be nonconforming **and** name its expected source constraint/shape; unrelated errors or exceptions do not satisfy it.
7. Validate the baseline configuration and independently inspect population/resource arithmetic and rectangle connectivity from its RDF.

Four additional isolated query tests check overlapping versus touching action intervals and reciprocal misses versus cancellation. They test those query boundaries, not conformance of complete action traces.

HermiT performs the OWL reasoning; the Python script does not replace it with handcrafted consistency assertions. SHACL performs the graph validation; the independent Python geometry checks are labelled separately. Neither pass establishes whole-program correctness or stochastic fairness.

## Run in the existing project environment

From the zombie_game_simulation project root in PowerShell:

```powershell
.\ontology\formal_v0.1\.venv\Scripts\python.exe ontology\formal_v0.1\validate.py
.\ontology\formal_v0.1\.venv\Scripts\python.exe ontology\formal_v0.1\document_package.py
```

The validator returns exit code 0 only if every recorded expectation is met. A complete run writes `reports/validation.json`; filtered runs write different filenames so they do not masquerade as the full report.

To rebuild specifications and fixtures before revalidating:

```powershell
.\ontology\formal_v0.1\.venv\Scripts\python.exe ontology\formal_v0.1\build_spec.py
.\ontology\formal_v0.1\.venv\Scripts\python.exe ontology\formal_v0.1\build_examples.py
.\ontology\formal_v0.1\.venv\Scripts\python.exe ontology\formal_v0.1\build_baseline.py
.\ontology\formal_v0.1\.venv\Scripts\python.exe ontology\formal_v0.1\validate.py
.\ontology\formal_v0.1\.venv\Scripts\python.exe ontology\formal_v0.1\document_package.py
```

For an independent environment, create a Python 3.12 virtual environment, install `requirements.txt` from PyPI, and provide a JDK through `JAVA_HOME` or under `.runtime/jdk-*/`. The tested JDK is recorded in `toolchain.json`; its archive checksum was verified before extraction. Owlready2 supplies the HermiT JAR and its bundled OWLAPI. `validate.py` compiles the small Java bridge automatically. The `.venv/`, `.runtime/`, caches and compiled classes are excluded from the review archive.

## Editing and versioning

The original Markdown and plan are not rewritten. This release follows TASK 1 in [prompts/zombie_game_plans.md](../../prompts/zombie_game_plans.md). The manifest records the ontology and plan paths and SHA-256 hashes, and validation checks both. All package paths resolve relative to this project. A changed Markdown source causes `build_spec.py` to stop until its mapping and pinned hash have been deliberately reviewed.

Edit the authoring scripts to update generated artifacts, then regenerate and rerun validation. The `.ttl` files are readable, portable outputs; direct edits must also be reflected in the authoring definitions before rebuilding. Each new game rule needs both a documented mapping and appropriate positive/negative evidence, or an explicitly declared gap. See [COVERAGE.md](COVERAGE.md) before treating this release as a complete specification.
