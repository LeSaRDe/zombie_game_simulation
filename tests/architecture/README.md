# Deep OOP architecture contracts

These tests implement the approved [deeper OOP proposal](../../docs/DEEP_OOP_REFACTOR_PROPOSAL.md). They exercise production objects and port implementations directly, alongside the unchanged game-outcome assertions in the original 539-case catalog. Added cases in `tests/spec/deep_oop.py` cover conversion continuation, retained historical identity, independent Spitter reservoirs and terminal dead Human states.

Run the direct contracts from the project root:

```bash
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python -m unittest discover -s tests/architecture -v
```

An absent class, unimplemented port, unexpected exception or missing dependency is a failure, never a skip. Class inheritance checks accompany actual behavior: real Simulation lookup must return authoritative `Agent` values, conversion must change the biological state variant under the same identity, and modifying old snapshots cannot change current or historical state. Persistence contracts run identical bundles through memory, SQLite and an independent non-SQL implementation; a patched `sqlite3.connect` rejects concrete backend leakage in the independent adapter.

`test_persistence_contract.py` checks atomic world/runtime/event/receipt commit, exact time, detached reads, cancellation, expected revisions, same-transaction retry, different-payload rejection and real persistence error rollback. Separate killed-process tests prove crash recovery before and after durable commit. `test_domain.py` covers ontology-derived domain records; `test_domain_integration.py` proves use through real runtime transitions. Rule/event contracts cover all 29 actual action fixtures, immutable transition output, custom stateless rules through actual execution/checkpoint/journal/branch, and rejection of missing, changed or unrecorded rule bindings. State contracts cover persistent overlays, historical spatial indexes, runtime copy isolation, lossless configuration serialization and stable untouched memory tokens. The non-SQL simulation contract checks real execution, lifecycle, metrics and timeline through an injected persistence factory.

Expected first-red results are retained in `artifacts/deep-oop-refactor/architecture-first-red-*.log`; those logs demonstrate missing architecture, not passing conformance. Source pins are refreshed only after reviewing the approved contract/provenance changes, never automatically by CI.

The differential driver captures reference results in isolated processes from the immutable accepted package:

```bash
PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python scripts/deep_oop_differential.py --capture
PYTHONDONTWRITEBYTECODE=1 .runtimeenv/bin/python scripts/deep_oop_differential.py
```

Capture refuses to overwrite a corpus. The current v4 corpus holds original checkpoint files, pins, journal-only recovery prefixes, complete observations/events/decisions/random draws and **every serialized runtime attribute**, excluding only duplicate `state` (compared as the complete world) and physical placement fields `history_path`, `backend`, `workers`, `worker_request`. This includes configuration, execution counters, prepared effects, parallel statistics, randomness overrides and optional extension bindings whenever present. Missing or extra fields fail; defaults are not silently invented. Comparison checks fresh execution, named-checkpoint restore and journal-only restore at multiple boundaries for both backends and workers 1/2/4. Original artifact hashes are verified before and after. Only the two specifically validated ontology-manifest provenance paths listed in each report may differ.

Earlier v3 reports compared a selected list of runtime fields. They remain historical evidence for those selected fields and complete world/events, but do not qualify the all-attribute continuation contract: that projection missed lost `parallel_effect_stats`. The driver rejects those older corpora for current qualification. Corrected v4 captures come independently from the unchanged archived engine; they do not copy refactored output into expectations.

The actual full `BASELINE_full_default_model_run` remains a separate mandatory release gate. Small fixtures and differential checks do not replace its 1,000-agent, 1,800-second default-policy trajectory.

The qualification driver records commands, logs, omitted gates and source hashes. Partial selections never claim a completed release. List commands first; choose a new output directory and an assessed wall budget for the full baseline:

```bash
.runtimeenv/bin/python scripts/verify_deep_oop.py --gate all --output artifacts/deep-oop-refactor/qualification --list
.runtimeenv/bin/python scripts/verify_deep_oop.py --gate architecture --gate core --output artifacts/deep-oop-refactor/qualified-contracts
.runtimeenv/bin/python scripts/verify_deep_oop.py --gate baseline --baseline-timeout 43200 --output artifacts/deep-oop-refactor/qualified-baseline
```

The baseline command sets the coordinator RPC budget to the same explicit budget and retains the actual primary history under its evidence directory. This is a resource budget, not a promise that every machine will finish within it. Every named gate remains mandatory for release; a timeout or missing browser/training dependency is a failure, never a passing skip.

The real-browser gate allows 300 seconds per workflow. Its 1,000-agent GUI/CLI comparisons allow 120 seconds for the independent CLI execution (`ZOMBIE_ACCEPTANCE_CLI_TIMEOUT` can explicitly override that budget); the measured CLI needed about 75 seconds on the qualification machine. These wall budgets do not change the original rendering FPS, input latency or receipt latency assertions.
