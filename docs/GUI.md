# Local research workspace

The GUI uses React/TypeScript, Canvas 2D, Plotly and an optional FastAPI service. Browser assets are bundled locally; charts, fonts, and scripts do not require a CDN. The engine and command journal are shared with the CLI. Simulation coordinators run in separate processes, so rendering or losing a browser connection does not pause an experiment.

Install the Python GUI dependencies and build the frontend when working from source:

```bash
python -m pip install -e '.[gui]'
cd gui
pnpm install --frozen-lockfile
pnpm run build
cd ..
zombie-sim gui --experiments-dir experiments --port 8765
```

Open `http://127.0.0.1:8765` in a browser. Node is needed to rebuild source assets, not to use an already bundled installation. The development build command type-checks the TypeScript before bundling. The local server restricts hosts/origins to loopback and establishes a same-site session cookie; hosted multi-user operation is outside this release.

## First experiment

1. Choose **New experiment**. The small preset provides a quick initial workflow; the baseline imports the ontology's 1,000-agent configuration.
2. Set the seed, horizon, populations, world dimensions, incubation duration, storage backend, and worker count. Advanced JSON exposes roles, profiles, geometry, resources, and the remaining resolved configuration.
3. **Validate**, then **Preview placement**. The preview has an independent initialization stream and does not consume a live run's decisions or randomness. Errors remain visible without changing the requested population or geometry.
4. Exact joint rejection sampling is the default. The baseline preset records the approved conditional-relocation choice. For other scenarios, explicitly choose conditional relocation and check its approximate-distribution acknowledgement. Separation and geometry constraints still remain strict. There is no silent fallback.
5. Optionally enter up to eight comma-separated replicate seeds to launch a bounded batch.
6. **Launch run**. The sidebar retains the run ID, scenario, seed, status, and committed simulation time. Initialization may take time for a dense exact-placement request.

## Live inspection

The cursor bar identifies live follow or recorded replay, exact display time, and revision. The four population cards count healthy humans, infected humans, living zombies, and dead identities. Remains do not add agents; conversion preserves identity.

In **World**, drag to pan, use the wheel or zoom buttons, and use **Fit world** to reset the camera. The origin is the lower-left corner and positive y points upward. Markers use both symbols and colors: human circles, infected rings, zombie triangles, and dead crosses. Marker size is a screen symbol, not a physical collision radius. Geometry, gates, stockpiles, remains, action indicators, recorded paths, and selected-agent sensing can be toggled using layers.

Select an agent on the map or through the keyboard-accessible search table. Search accepts IDs, roles, types, and statuses; narrow the result if more than 100 match. **Follow selected identity** keeps the camera on that identity through movement, conversion, and death. The inspector shows current applicable attributes, inventory/reserved quantities, effects, cooldowns, active occurrence, and infection episode. The full JSON details preserve fields that do not fit the compact display.

**Statistics** shows population curves, exact recorded event totals, and current resources. Reservations are displayed as a subset of stock, not added to total resources. Chart clicks select a replay time. Plotly's export control saves charts, and an accessible population table provides the same samples. Chart/cohort/event requests are bounded to two refreshes per second; their revision label explicitly shows when they lag the live scene.

Use **Edit as new run** to copy a selected run’s frozen configuration into an editable draft. The original run remains historical provenance. In **Comparison**, select up to four saved runs; population curves align on absolute simulation time through the earliest selected frontier, and each source retains its own revision. Export includes the run, seed, revision, and sampled time for every row.

## Cohorts and causal records

In **Cohorts**, save a status/type/role/model/region predicate as fixed membership at the displayed revision or dynamic membership recomputed at each selected revision. Fixed membership retains identities after conversion and death. Cohorts may overlap and are not assumed to partition the population. Cards show the denominator, current type/status counts, mean life/stamina, resource summary, and saved definition. Export includes the exact source cursor.

Human survival ends at death or conversion; identity survival ends only at death. Living members at the observation boundary are right-censored. The cohort interface does not infer causation from differences between groups.

The **Events** timeline loads the latest bounded window of recorded events through its labelled cursor. Filter by action, outcome, participant, or event text. Selecting an agent restricts the timeline to that identity, including lifecycle events. Selecting an event opens its full record and jumps to its causal revision; the inspector can show the before/after revision. For complete unbounded analysis, export the event ledger through CSV/Parquet.

## Execution and replay controls

Execution controls operate on the managed run, while the bottom viewer controls operate only on displayed history:

| Control | Behavior |
| --- | --- |
| Pause / Continue | Acknowledge an engine boundary; wall-clock pause never advances hunger or infection. |
| Step transition | While paused, process one next atomic engine transition. |
| Step timestamp | While paused, process the next ordered timestamp according to the engine's phase contract. |
| Run pace | Target 0.25×, 1×, 4× or fastest by wall-clock scheduling. Semantic durations and random draws are unchanged. |
| Checkpoint | Save complete engine continuation state at the effective boundary. |
| Stop & save | Save pending work and stop the worker; the run remains resumable. |
| Branch / intervene | Create a separate child at any committed revision, or schedule a resource addition/compatible role/model replacement when enabled in the frozen scenario. Model replacement explicitly resets private memory. |
| Replay scrub / Seek | Read committed history; the executing run continues independently. Exact rational time input is accepted. |
| Replay play / speed | Advance only the viewer's recorded-time cursor. |
| Return to live | Resynchronize all scene data to the newest committed revision. |

Each command uses a unique ID and a control generation. The UI displays pending and actual applied/rejected outcomes, including effective time/revision. Stale commands reject with a refreshable message. Retrying an identical command ID uses its durable result. Completed runs are immutable. Branches can resume any recorded committed boundary because the ledger preserves scheduler state and private model memory at every revision; they are not restricted to checkpoint-file times.

For **Recorded agent observation**, first select an identity, then change perspective. The global map, statistics, and privileged inspector disappear. The view displays only the actual input recorded for the chosen decision, including its historical time/revision. If no observation was recorded, the interface reports that rather than substituting current global knowledge.

## Reconnect, exports, and accessibility

Live subscriptions send self-contained snapshots with sequence and revision IDs. The client acknowledges each snapshot; only one can be outstanding. Slow clients cannot accumulate an unbounded semantic queue. A reconnect requests a fresh snapshot and does not restart or stop a run.

Use the map's **PNG** button for a canvas frame, the chart toolbar for chart SVG/PNG, and **Export** for scene JSON with provenance, event CSV, world SVG, population CSV, event Parquet, and a portable offline HTML animation from time zero to the current cursor. Cohort export retains its rule and membership. CLI exports also support Parquet and ontology Turtle.

Controls and form fields have accessible labels and visible keyboard focus. Search tables provide an alternative to selecting canvas markers. Chart data is available as a table. Status symbols supplement color, the layout adapts to narrow windows, and reduced-motion preferences disable CSS motion.

## Practical boundaries

Use a current browser supporting Canvas, WebSocket, ResizeObserver and native ES modules. Actual Chrome 156 checks passed desktop/mobile views, a 1,000-agent placement preview, and WebSocket snapshot acknowledgements; see [the validation record](APPLICATION_VALIDATION.md). These checks do not establish a measured 30-frame/s acceptance budget; renderer latency and 10,000-agent performance require a separately recorded browser profile. Offline replay animations use at most 300 recorded samples; their effective interval and source cursors are embedded in the portable HTML. They are sampled replay artifacts, not video recordings or evidence of uncommitted motion. Legacy runs without a runtime journal need a complete retained checkpoint for exact continuation.
