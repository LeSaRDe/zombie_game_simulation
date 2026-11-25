# Application validation record

Recorded on 2026-11-25. These checks were written for the implementation and did not read, import, enumerate, or execute the supplied acceptance suite.

## Executed checks

The production frontend passed TypeScript 5.9.3 checking and a Vite 7.2.2 build using Node 24.22.3. React 19.2.0 and Plotly 3.3.0 are pinned in `gui/package.json`, with resolution recorded in `gui/pnpm-lock.yaml`. Compiled assets are copied to `src/zombie_sim/static` by the build script.

The local HTTP service ran with Python 3.14.4, FastAPI 0.165.0, Uvicorn 0.54.0, and websockets 16.1.1. `gui/verify_api.py` exercised actual HTTP requests against the listening service and separately spawned simulation workers. Its latest executed result was **passed** for:

- Static index/assets, session-cookie establishment, configuration validation, and an isolated placement preview.
- Idempotent creation, correct persistent run identity, and initial population accounting.
- Atomic transition stepping, an explicit continuation checkpoint, and a fixed initially infected cohort.
- A scheduled resource addition, advance to 3 seconds, and reconstruction of revision zero.
- Population sampling at 0, 1, 2, and 3 seconds with conservation of the three persistent identities.
- Nonempty JSON, CSV, SVG, Parquet, and portable offline HTML-animation exports.
- Idempotent counterfactual branch creation, a distinct child identity/seed, inherited state at 3 seconds, an additional historical revision-zero branch, and an unchanged parent revision.
- Child continuation through the infection deadline at 5 seconds and the resulting zombie population at 6 seconds.
- Explicit stop/save for parent and child.
- A separate live run with start, pause, pacing change, continue, and completed horizon at 4 seconds.

The latest checked parent was `0f51ba3363a64a0893a760431a134bd9`, its child was `97e23173b06f40d7a2d900ba547670ae`, and the live-control run was `d7f4d8d543ed44249653d0b1bd48ef77`. They were created under the disposable verification directory `/tmp/zombie-gui-browser-check`; the check creates new identities on every invocation.

Independent storage smoke checks additionally passed memory/SQLite state parity, exact rational lookups, nested deltas, checkpoint integrity and round trips, reopened SQLite state, stale-writer compare-and-swap rejection, concurrent idempotent transaction retries, rollback after malformed patches, anchor tamper rejection, lifecycle participant indexing, infected-cohort membership, equal-time metric-cache invalidation, future-cursor rejection, and interrupted creation reconciliation.

## Reproduction

Start the server, then run the check against its loopback address:

```bash
zombie-sim gui --experiments-dir /tmp/zombie-gui-browser-check --port 8765
python gui/verify_api.py http://127.0.0.1:8765
```

The check needs the GUI and analysis dependencies, because it verifies Parquet as well as the core API. It does not run any code from the supplied acceptance suite.

## Limits of this evidence

The in-app computer-use surface was unavailable, but a subsequent actual headless Chrome 156.0.8078.79 session through Playwright passed `gui/verify_browser.cjs`. It checked the world Canvas, Plotly population chart, agent selection, restricted agent perspective, configuration validation, placement preview, Escape dismissal, and responsive world/statistics/cohorts/events/comparison/configuration views. The 390 × 844 mobile viewport had document width exactly 390 pixels after correcting intrinsic grid sizing. It also received a real WebSocket snapshot and sent its acknowledgement; the GUI dependency extra now explicitly installs the required WebSocket transport. There were no page errors.

The browser generated a 1,000-identity baseline preview using the explicitly accepted conditional-relocation sampler, and the resulting screenshots were visually inspected. Screenshots and the machine-readable browser record are in `artifacts/browser/`: `world.png`, `statistics.png`, `configuration.png`, `baseline-preview.png`, `mobile.png`, `mobile-configuration.png`, and `report.json`. The frontend was rebuilt and those final assets were copied into the Python package.

This is functional and visual Chrome evidence. It does not establish full accessibility conformance, Firefox behavior, sustained frame rate, pointer latency, or the proposed 10,000-agent rendering budget.

`gui/verify_recovery.py` subsequently passed **12 forced-process-exit cases**: before/after the first semantic commit, both memory and SQLite backends, and step/step-timestamp/advance commands. Each case restored the latest world/runtime journal, recovered or reused the command acknowledgement, and matched uninterrupted state, events, model memory, and pending queue through six seconds. No newer committed history was discarded.

`implementation_checks/runtime_check.py` also verified historical decision-boundary continuation with real default-model memory, decisions and draws; exact fractional busy-action continuation on both backends; counterfactual seed/lineage restoration; and corrupt runtime-journal rejection. New runs support exact continuation and branches at every committed revision, including between checkpoint files.

`gui/verify_manager.py` passed actual managed subprocess checks for a branch at historical revision zero, reconciliation of an intentionally lost manager acknowledgement from the run ledger, recovery after terminating a worker at a committed revision newer than its checkpoint file, and immediate stop/resume. Additional focused checks rejected a second CLI coordinator using the same file lease and rejected a stale independent memory-store writer against the durable ledger. These checks were rerun after the final transaction/recovery changes.

A separate disposable CLI workflow passed run-to-2-seconds, inspection, revision-zero replay, revision-zero branching with a different seed, original-ledger continuation to 6 seconds, child continuation to 1 second, time-filtered Turtle export, and metric export. It invoked the CLI dispatcher with its real engine, persistence, and exporters.
