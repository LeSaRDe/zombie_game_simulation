# Browser acceptance specifications

The browser cases live in `tests/spec/systems.py` and are executed by the shared
adapter-driven runner. They require a **real browser and the future GUI/server**;
no present GUI implementation or browser adapter is supplied. Selecting the browser
tier without them fails explicitly. Do not interpret harness self-tests as GUI
acceptance. No frontend dependencies are installed by this specification.

Implement the browser binding using Playwright or an equivalent automation library,
with pinned desktop Chromium/Firefox versions. Record browser version, OS, viewport,
device scale, hardware, adapter/version, application revision and artifact directory.
The `GUI_ACCESSIBLE_KEYBOARD_*` cases run both named engines; normal cases use the
declared default engine. Screenshots/traces supplement the numerical assertions.

## Stable interaction contract

The proposed `data-testid` hooks below identify semantic controls. Visible accessible
labels must still be present: test IDs are not a substitute for accessibility.
Select by exact test ID, wait for the actual control to become ready, perform a real
interaction, and observe the server acknowledgement or rendered cursor. Never force
click a disabled control or modify component state directly.

| Group | Test IDs |
|---|---|
| Draft | `config-<field>`, `config-validate`, `config-save`, `config-preview`, `config-edit-new` |
| Execution | `run-start`, `run-pause`, `run-stop`, `run-step-transition`, `run-step-timestamp`, `run-checkpoint` |
| Selection/layers | `agent-search`, `agent-search-select`, `agent-follow`, `layer-trails`, `layer-global-agents`, `view-pacing` |
| Replay | `replay-exact-time`, `replay-seek`, `replay-pause`, `replay-return-live` |
| Commands | `command-submit`, `command-retry`, `command-refresh` |
| Timeline | `timeline-first-event`, `event-before`, `event-after` |
| Export/table | `export-start`, `export-cancel`, `population-table` |

`config-<field>` uses the literal field key in the case, including dots. Form helpers
must also log each visible field/option/control used so missing UI cannot hide behind
a helper name. Methods and required behavior:

| Operation | Browser activity |
|---|---|
| `open`, `open_tab`, `select_tab`, `select_run` | Start/select actual page(s) and choose a run in the sidebar. Tabs retain independent stale control generations. |
| `click`, `fill` | Interact with the exact test ID. `bind_run` reads the actual resulting run ID into a test alias. Extra fields such as checkpoint `name` fill the dialog. |
| `import_config`, `export_import_config` | Use the file import/export UI and actual files. |
| `cohort_create` | Open cohort builder, fill name/fixed-vs-dynamic/predicate, save through the GUI. |
| `chart_select` | Select the supplied chart's time using its accessible control or chart event; record the event and resulting shared cursor. |
| `timeline_filter`, `timeline_select` | Fill actual timeline filters and select the recorded event/occurrence. |
| `select_observation` | Choose the actor's recorded decision and switch perspective through UI controls. |
| `command_prepare` | Open the start/stop/branch/intervention dialog; assign the test command ID via the transport seam, fill child/source/time/change fields. `start` creates a new run from the existing configuration. |
| `intervention_form` | Fill an intervention dialog; explicit model replacement includes model ID/version and memory policy. |
| `export_form` | Fill format, time/interval, sampling/cohort and output settings; bind the job alias when submitted. |
| `sync`, `await_view`, `await_export` | Bounded waits on real rendered revision/job state. A still-loading UI cannot satisfy captures. |
| `disconnect`, `reconnect` | Drop/reestablish viewer transport; retain/reload browser state through supported reconnect behavior. Do not stop the simulation. |
| `elapse_wall_time` | Let real wall time pass without sending engine events. |
| `transport`, `release_transport` | Intercept real WebSocket/HTTP messages to hold, omit, duplicate or reorder selected messages; retain original payloads and release them deterministically. |
| `projection_fixture` | Feed a minimal valid projection bundle to the **actual browser transport reducer**, for exact-string serialization tests only. This is a frontend protocol fixture, not a simulated evolution or fake server. |
| `release_export` | Release the service's test barrier after cancellation so the real export worker can settle. |
| `keyboard_workflow` | Perform the named full workflow using Tab/Shift-Tab/arrows/Enter/Space only. Capture input event log and resulting focused element; do not use mouse or direct business APIs. |
| `observer_load` | Exercise the given display rates/pacing in the real UI; `slow` withholds acknowledgements, `exports` launches real exports, `live` follows normally. Configure a 16-bundle subscriber limit. |
| `benchmark` | Build the stated real scene; exercise selection/pan/scrub/cohorts/pause over the measured interval, with warmup excluded. See performance rules below. |
| `capture`, `capture_transport` | Extract factual DOM attributes/text, the exact committed renderer projection, actual render/transport log and recorded service cursor. Do not return validation verdicts. |

## Captured facts

Default `capture` returns mode/perspective, selected/followed identity, scene agents
and geometry, world/inspector/statistics cursors, inspector agent fields and chart
values. Each cursor contains actual run ID, exact time and revision. These values
must be read from the view used to render that panel, not from an unrelated API
request. `scene.agents` includes inspectable dead identities; `scene.living_agents`
excludes them and `scene.remains` is separate. Inspector agent fields use the same
normalized record as `run.capture`. Converting an entity changes its symbol/status;
it does not create a new agent identity. Marker semantics are `screen_symbol`.

Special capture projections:

- `validation`: keyed field codes, summary codes/text, actual start button disabled
  state. Normalized codes come from shared validation errors, not a test prediction.
- `preview` / `preview_scene`: actual artifact ID, seed/fingerprint and visible
  renderer objects. Legend `non_color_tokens` are labels/symbol keys read from DOM
  or renderer instructions, not a computed “accessible” flag.
- `cohorts`: definitions and measurements keyed by saved cohort name, raw member
  IDs, denominator, cure/conversion/new-incidence counts, human/identity survival
  events and overlap label. Empty dynamic membership has denominator zero; fixed
  membership retains IDs after conversion/death.
- `control` / `command`: actual lifecycle state, command status, generation and
  effective boundary. Stale generation remains stale until the user refreshes.
- `timeline`: ordered `records` plus occurrence map for the active filter. A before
  or after jump uses the event's transaction boundary, never an arbitrary time-only
  approximation that loses simultaneous events or immediate cleanup.
- `selected_event`: raw selected event type/time, before/after revision, causes.
- `projection`: exact normalized payload accepted by the browser reducer, including
  identifiers larger than JavaScript's safe integer range as strings.
- `accessibility`: actual accessible names/roles/disabled flags, table headers,
  focused test ID, rendered status tokens and effective reduced-motion mode.
- `export_job`: real job status and number of still-active tasks; cancellation must
  settle rather than leaving encoding/query work running indefinitely.
- `capture_transport`: actual snapshot requests, peak queued bundles and publication
  application trace. `applied_revision_regressions` is computed solely from that
  recorded monotone application trace; include the trace so a reviewer can verify
  it. No screenshot or test-level passed boolean substitutes for these facts.

Researcher→observation switching clears privileged caches; the observation inspector
selects the observing agent. The capture includes all surviving privileged cache
keys (expected empty), not merely the visible main canvas. The saved observation
comparison includes local geometry, dated reports and all allowed fields.

## Performance and exports

Performance cases use the `performance` tier, not ordinary browser CI. Record raw
`requestAnimationFrame` timestamps/frame durations, input-to-render latencies and
command-send-to-receipt-ack latencies. Derive FPS/p95 from those raw samples in the
test adapter; return samples plus the derived measurements. Do not trust a product
“performance passed” flag. The 1,000-agent targets are >=30 FPS, p95 input <=100 ms,
and p95 receipt ack <=250 ms on recorded local hardware. Pending application is a
separate latency. The 10,000-agent case profiles aggregation rather than inventing
an unapproved FPS target. Both use a configured buffer cap of 16 bundles.

Return `frame_times_ms` as durations between consecutive rendered frames,
`input_latencies_ms` (at least 20 samples), and `receipt_ack_latencies_ms` (at least 5).
Exclude warmup and cover the requested 30-second interval. The parent runner
independently recomputes FPS as frames / elapsed time and p95 by nearest rank
(`ceil(0.95*n)`), compares reported metrics within 1e-6, and applies the targets.
The 10,000-agent profile still requires raw measurements even without an FPS target.

Decode actual downloaded export files and provenance sidecars. Preserve PNG/SVG
images, tables and animation for review; also compare exact source run/time/revision,
cohort/filter, sampling settings, units and visualization version. Artifact readers
must fail on empty, invalid-format or missing-sidecar output. Semantic assertions
and screenshot regression together are needed for release evidence; these tests do
not declare visual fidelity merely because a PNG exists.

The cases cover the complete workflow in independently diagnosed stages. For a
release walkthrough, retain one continuous browser recording of configuration,
initialization, infection inspection, cohort comparison, deadline stepping, replay,
Edit as new run, and export using these same controls. The recording supplements
the executable checks and is not a substitute for them.
