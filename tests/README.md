# TASK 2 test suite

This directory provides executable ontology-grounded acceptance cases and an
independently tested runner connected to the real framework. The approved deeper
OOP refactor preserves the original 539 semantic cases and adds explicit domain,
event, ownership and persistence contracts. See
[architecture/README.md](architecture/README.md) for the new direct tests and
legacy-continuation corpus. A case catalog or source audit is not an execution
result; passing conformance requires a report from the real adapter.

Start with [COVERAGE.md](COVERAGE.md) to review the cases by action, invariant and
GUI requirement. [coverage.json](coverage.json) maps every case to its sources and
proposed design choices. The test files are ordinary Python data constructors:
inputs, operations and expected observations are visible together.

## Run now

From the repository root, with Python 3.12 or newer; no installation is needed:

```bash
python -m unittest discover -s tests/harness -v
python -m tests.audit_suite
python -m tests.run_acceptance --list
python -m tests.run_acceptance --report tests/results/conformance.json
```

The first command checks assertion logic, invariant oracles, process isolation,
failure/timeout handling and suite integrity. The second checks source pins and
traceability. The third only lists cases. The fourth deliberately exits **2** and
reports **NOT_RUN** while no implementation adapter is supplied. None of the first
three commands establishes a passing simulator.

## Run the implementation

The implementation follows [ADAPTER_CONTRACT.md](ADAPTER_CONTRACT.md). Select its factory:

```bash
PYTHONPATH=src .runtimeenv/bin/python -m tests.run_acceptance --adapter zombie_sim.testing:create_adapter --tier core
PYTHONPATH=src .runtimeenv/bin/python -m tests.run_acceptance --adapter zombie_sim.testing:create_adapter --match LIF_cure
PYTHONPATH=src .runtimeenv/bin/python -m tests.run_acceptance --adapter zombie_sim.testing:create_adapter --tier browser --timeout 180
```

`ZOMBIE_TEST_ADAPTER` can supply the same factory. No tier selection means **all**
tiers. A filtered passing run is reported as partial. Tiers are `core`,
`integration`, `browser`, `statistical`, `training`, and `performance`. The default
per-case timeout is 60 seconds; explicitly increase it for baseline, PPO, browser
or replicated benchmarks on the actual machine. Missing features/dependencies,
unexpected exceptions, timeouts and cleanup failures are errors, never skips.

The full baseline is selected with `--match BASELINE_full_default_model_run` and
requires an explicit timeout and sufficient disk/memory capacity for its actual
1,800-second simulated trajectory. Select the provisioned training Python for
the training tier. Preserve run artifacts and the distinction between current
execution evidence and earlier release reports.

## What to review

| File | Coverage |
|---|---|
| [spec/actions.py](spec/actions.py) | All 29 actions: complete successes, capability/admission failures, costs, cooldowns, reservations, attacks and effects. |
| [spec/lifecycle_geometry.py](spec/lifecycle_geometry.py) | Worked A–K, death/conversion/cure, exact-time ordering, conflicts, resource contention, geometry, observations and invalid initialization. |
| [spec/generated.py](spec/generated.py) | Independently calculated damage/exposure boundaries, movement and resource/time families. |
| [spec/research.py](spec/research.py) | Mixed action sequences, replicated hit/arbitration diagnostics, full default-policy baseline. |
| [spec/policies.py](spec/policies.py) | Real default-policy witness bank and complete action encoder checks. |
| [spec/formal.py](spec/formal.py) | Actual treatment/death/conversion RDF exports, checked against trusted SHACL and literal transition facts. |
| [spec/systems.py](spec/systems.py) | Stores, replay/restart/crash recovery, serial/parallel equivalence, configuration, plugins, learning, GUI G01–G16 and performance measurements. |
| [invariants.py](invariants.py), [research_checks.py](research_checks.py) | Independent raw-state/trace, baseline and statistical postchecks. |
| [browser/README.md](browser/README.md) | Actual browser actions, selectors, captures, accessibility and export evidence. |

Each case has stable `id`, source references, requirement/action tags, tier,
optional decision tags, a request, and nonempty independent checks. Only the
request reaches the implementation adapter. Positive checks fail on missing data;
negative checks cannot hide a missing parent collection. No production reducer or
policy supplies the expected numeric results.

The source pins cover the Markdown ontology, formal ontology/catalog/shapes/OWL,
formal examples/coverage, and the three current plan documents. The formal package
contains historical validation evidence and an older plan-file fingerprint; those
artifacts remain unchanged. This suite records the current source bytes separately
and makes no claim that the old full-package release verification has been rerun.

Formal integration cases additionally require the RDFLib/pySHACL versions pinned
in the existing formal package. Their oracle self-tests are separate from the
standard-library harness and can use the already provisioned environment:

```bash
ontology/formal_v0.1/.venv/bin/python -m unittest discover -s tests/formal_harness -v
```

These test the RDF reader and trusted shapes using static examples and mutations;
they do not execute the future simulator. See [FORMAL_OPERATIONS.md](spec/FORMAL_OPERATIONS.md).

After an intentional specification change, review affected tests, then run:

```bash
python -m tests.audit_suite --refresh-sources --write-coverage
```

Do not automatically refresh pins in CI: an unexplained source change should fail
the audit. `--write-coverage` alone regenerates the review report without accepting
changed specification bytes.

## Scope of the evidence

The suite covers all named actions, V01–V25, G01–G16 and the implementation plan's
main workflows. Those mappings are navigation aids, not a completeness proof.
GUI layout/pixel fidelity, scientific learning quality, exact conditional-uniform
placement, and hardware-specific speedups need additional release evidence.
PPO smoke tests verify training/reload mechanics rather than promising a reward
improvement. Statistical diagnostics have finite samples and fixed tolerances.

The plan's D1–D9 choices remain reviewable. Test-specific normalized names are not
requirements to expose implementation details in the user interface. A future
implementation should bind these contracts to its actual public services and
retain the ontology's semantics when adapting interface names.
