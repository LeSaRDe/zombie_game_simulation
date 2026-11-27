# Local research workspace

New to the simulator? Start with the [friendly user guide](USER_GUIDE.md), which
walks through a first experiment with screenshots. This page is the detailed GUI
reference.

For setup, complete service shutdown, terminal controls and restart procedures,
see [Starting and stopping the Zombie Game Simulation](START_STOP_GUIDE.md).

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

## Open an existing run

The home screen says **Choose a run or create an experiment.** It lists run
summaries without selecting a run or reconstructing its history. Choose a run
from the sidebar or the home-screen cards when you want to inspect it.

**Loading recorded history** means the viewer is reading an existing record;
it does not mean a new simulation is being created. The panel identifies the
selected run and its known committed time and revision. **Initializing the
world** appears only when the service reports actual run initialization.

Use **Cancel loading and return to runs** to leave a pending view, or **Run list**
to return after it loads. Changing the selection also cancels the previous viewer
request. These actions do not pause, terminate or delete a simulation. Reader
work stops at safe boundaries; an atomic read, decode or projection already in
progress may finish first. A delayed response cannot replace your new selection.

If loading fails, the error panel offers **Retry loading** and **Return to run
list**. If the workspace service is unavailable before selection, use **Retry run
list** after the service is available again. The error is shown separately from
initialization.

## First experiment

1. Choose **New experiment**. The small preset provides a quick initial workflow; the baseline imports the ontology's 1,000-agent configuration.
2. Set the seed, horizon, populations, world dimensions, incubation duration, storage backend, and worker count (`auto` uses the detected CPU and memory budget). Advanced JSON exposes roles, profiles, geometry, resources, and the remaining resolved configuration.
3. **Validate**, then **Preview placement**. The preview has an independent initialization stream and does not consume a live run's decisions or randomness. Errors remain visible without changing the requested population or geometry.
4. Exact joint rejection sampling is the default. The baseline preset records the approved conditional-relocation choice. For other scenarios, explicitly choose conditional relocation and check its approximate-distribution acknowledgement. Separation and geometry constraints still remain strict. There is no silent fallback.
5. Optionally enter up to eight comma-separated replicate seeds to launch a bounded batch.
6. **Launch run**. The accepted run is selected immediately, so you can follow actual initialization. The sidebar retains the run ID, scenario, seed, status, and committed simulation time. Initialization may take time for a dense exact-placement request. Cancelling its viewer leaves the accepted simulation running or initializing independently.

When the configuration dialog first opens, **Loading configuration** means it
is fetching presets and editor fields. Editing, validation, preview and launch
become available after that finishes. If loading fails, choose **Retry loading
configuration** in the dialog; closing the dialog is also safe.

You can completely clear any numeric field and type a replacement. Empty or
unfinished numbers stay visible; leaving the field or submitting shows an error
beside the field and near the action buttons. Correct these entries before
Validate, Preview, Launch, Export or Save draft. None of those actions silently
uses the previous number. Zero is valid for seeds and population counts;
durations, dimensions and manual worker counts must be positive. Population
counts, seeds and manual Workers require whole numbers.

The **Human roles** and **Zombie roles** panels let you set a target percentage
for each compatible role. **No active role** automatically receives the remaining
percentage. Changing a population or a target recalculates the whole-number
counts for that type; the counts, including agents without a role, always add up
to its population. Initially infected humans remain part of the Human total and
may have Human roles.

Small populations cannot always match a target percentage exactly. For example,
a 10% Doctor target among seven Humans gives one Doctor, approximately 14.29%.
The panel shows both **Target** and **Realized**, with “≈” on rounded percentage
labels. Equal rounding remainders use a fixed order, so changing the seed does
not change the role counts. The seed still controls which individual agents
receive those roles. A zero population shows zero counts and “—” for actual
percentages, while retaining targets for a later increase.

Keep each target between 0% and 100%, with their combined total at most 100%.
Empty, unfinished or invalid entries stay visible until corrected. Reducing
Humans below the initially infected count requires correcting that separate
constraint; the editor does not silently lower the infection count.

Valid imported role counts stay unchanged until you edit their population or
targets. Exported configurations retain exact targets and the rounding method
alongside their integer counts. Contradictory imported targets/counts produce
an error. For a configuration that explicitly lists individual agents, population
and role controls are read-only: edit the individual records in Advanced JSON
to change those assignments. These controls are also read-only when a
`semantic` block supplies the population or role settings; edit that block
instead of entering outer values that it would override.

Advanced JSON must contain a complete JSON object. If it is empty or incomplete,
the dialog explains what needs attention and keeps your text. Correct the text,
then Validate again; no preview or run is created from an unreadable draft.
Simulation constraints are still checked by the backend. **Save draft** preserves
your current Advanced JSON text locally, including unfinished JSON, once
configuration has loaded and pending numeric-field edits are valid. Saving a
draft does not mean it has passed simulation validation.

Use **Load saved draft** to restore the last draft saved in this browser. This
replaces the current editor contents, including role targets. JSON or TOML export
is the portable way to keep or share a configuration outside this browser.

### Resize a world and its layout

Changing **World length** or **World width** scales the spatial layout on that
axis. Obstacles, walls, gates, shelter interiors, stockpiles and ordinary explicit
initial agent positions move together. The editor also adjusts valid custom
layouts and shows a resize summary; a resized baseline is labelled
**Customized baseline**. Shrinking both dimensions from 1,000 to 200 m multiplies
all layout coordinates by 0.2, including the shelter and gate dimensions.

Population and role counts, resource quantities, integrity, model settings,
speeds, sensing/action ranges and initial separation requirements keep their
declared values. The smaller world therefore has a greater population density.
**Validate** checks the resulting configuration and deterministic conflicts in
explicit initial positions. **Preview placement** additionally checks connectivity
and generates the population under the unchanged spacing constraints. A sampling
budget failure is not proof that no placement exists.

Repeated form edits use a saved reference layout to avoid cumulative scaling.
Save/export includes the concrete resized coordinates and editor provenance;
reopening that draft does not resize it again. Deliberate geometry edits establish
a new reference. JSON and TOML inputs are interpreted as written: loading a file
or editing Advanced JSON does not infer a resize. Subsequent dimension edits in
the form apply the announced layout adjustment, including effective preset or
`semantic` values.

Historical/runtime state imports can contain frozen death locations, remains,
signals and model-private spatial memory. The editor explains that automatic
resizing is unsupported for these records and keeps the draft intact. Use an
ordinary new-scenario layout for automatic world resizing. Existing runs remain
immutable; **Edit as new run** changes only the new experiment's configuration.

### Decision models in the current editor

A decision model chooses an agent's next action from its local observations and
private memory. It is separate from the agent's role, such as Doctor or Runner.

The **Human decision model** and **Zombie decision model** selectors show a
friendly policy name, requested identifier and installed version. Untouched
presets select **Default human utility policy** (`HumanDefaultModel`) and
**Default zombie utility policy** (`ZombieDefaultModel`), currently version
`1.1.0`. The detail beneath each selector shows the registered identity, such as
`defaultHuman/v1`, and whether the setting is inherited or explicitly supplied.
Reading these defaults does not insert model keys into the configuration.

Choose a listed alternative to change the new experiment. The registry's
`randomLegal/v1` policy samples uniformly from locally observable candidates;
an attempted action can still be rejected by the engine. Choices are filtered
by their declared Human/Zombie applicability. Imported aliases such as
`defaultHuman` remain unchanged until you deliberately select another value.

Choose **Advanced registered model or artifact** to enter a registered ID or
`ppo:<artifact-directory>`. The plugin registration, artifact files and required
dependencies must exist in the service environment. The list itself does not
load trained weights. Plugins without descriptive metadata are still available
through this advanced path. Unknown or explicit empty values stay visible and
receive validation feedback; they do not silently become defaults. An arbitrary
name does not create a model.

Explicit per-agent configurations display **Per-agent assignments · edit
Advanced JSON** and summarize their assignments. Edit the individual
`model_assignment` records there; the population selectors do not replace them.
When a `semantic.human_model` or `semantic.zombie_model` value overrides a
top-level setting, the corresponding control explains that it must be edited
in Advanced JSON. Per-agent parameters and requested versions remain intact.

All ordinary field edits read the current valid Advanced JSON draft. Unfinished
or non-object JSON disables field and replacement controls until you correct it
or explicitly choose **Discard unfinished JSON**. Custom settings survive mixed
JSON, numeric, role and model editing. Partial drafts use resolved server defaults
for Launch, including the seed; replicate seed overrides remain explicit.
See [Decision models](MODELS.md) for registry and artifact details. Exporting a
configuration preserves settings, not plugin code or learned weights.

## Live inspection

Two readouts above the workspace separate **Simulation** execution from the
state you are **Viewing**. Each shows readable time and its revision, with an
**Exact time** button for the original timestamp. The Simulation
readout uses the service's run summaries; Viewing uses the loaded state, which
may lag behind or deliberately show earlier history. They remain visible in
every analysis tab. A failed summary request or a request more than five seconds
old changes the status to **Last confirmed**; it does not claim the simulation is
currently running. The header and sidebar use the same qualification.

Selecting a population sample, recorded event, or historical time opens
**Viewing recorded history**. A persistent message describes the independently
reported execution status, with **Return to live** beside it. For example,
Simulation may show Running at 80 seconds while Viewing recorded history shows
0 seconds. The run continues until an execution control or completion condition
stops it. Returning to live resumes following the latest committed state; it
does not restart execution. Changing tabs or expanding cohort details does not
move the viewing cursor.

### Readable and exact times

Time readouts share one display policy. Ordinary times use up to three decimal
places, without trailing zeros: `2.5 s`, `≈0.333 s` or `≈51 s`. The **≈** marker
means that only the displayed number was rounded. Positive times below `0.001 s`
and times at or above `1e9 s` use up to six significant digits in scientific
notation, such as `1e-8 s`, so a small positive time is never labelled zero.
Ordinary rounding has at most `0.0005 s` display error.

Choose **Exact time** beside a readout to reveal its original decimal or fraction.
The button works with keyboard and touch. Selecting a chart, table sample or
event uses its original time and revision, even when several labels look alike.
The engine, history, raw record details and machine-readable exports keep exact
values.

Time controls in Replay, Statistics, Export and intervention dialogs show a
compact summary. Expand **Edit exact time** to type or paste a value. Opening or
closing this editor does not alter its value. An untouched Replay or Statistics
selection uses the displayed state's exact time and revision. Once you type,
your draft stays fixed while live updates arrive; **Use selected view time**
restores following. Entering invalid text does not navigate the viewer.

### Inspect the world and analysis panels

The four population cards describe the displayed revision: healthy humans,
infected humans, living zombies, and dead identities. Remains do not add agents;
conversion preserves identity.

In **World**, drag to pan, use the wheel or zoom buttons, and use **Fit world** to reset the camera. The origin is the lower-left corner and positive y points upward. Markers use both symbols and colors: human circles, infected rings, zombie triangles, and dead crosses. Marker size is a screen symbol, not a physical collision radius. Geometry, gates, stockpiles, remains, action indicators, recorded paths, and selected-agent sensing can be toggled using layers.

Select an agent on the map or through the keyboard-accessible search table. Search accepts IDs, roles, types, and statuses; narrow the result if more than 100 match. **Follow selected identity** keeps the camera on that identity through movement, conversion, and death. The inspector shows current applicable attributes, inventory/reserved quantities, effects, cooldowns, active occurrence, and infection episode. The full JSON details preserve fields that do not fit the compact display.

**Statistics** shows sampled population curves, exact recorded event totals and
resources at its labeled source time and revision. All three use that same
source, even when the live world has moved ahead. Reservations are a subset of
stock, not additional resources. A new run has visible population markers at
time zero; its initial one-second axis range is only for visibility and does
not mean the simulation has already advanced.

The chart normally follows the latest verified Statistics data. Zooming or
panning pauses automatic axis movement while data can continue updating. Use
the chart's **Follow latest chart samples** button to restore following. While replaying,
**Reset chart view** restores the extent of the selected history; use the main
viewer’s **Return to live** control to leave replay. Changing workspace tabs
preserves your manual chart view.

Click a marker or a time in **Accessible population table** to inspect its exact
time and revision, including separate causal boundaries at the same time. Each
revision appears beneath its Time value, preserving the five measurement columns. The
keyboard-accessible **Recorded time to inspect (s)** control opens with **Edit exact
time**. Its field follows the selected
view's exact time until you edit it. Click **Inspect recorded time** or press
Enter: an untouched field selects that exact time and revision. Edited text
stays fixed as execution advances; **Use selected view time** restores following.
Switching runs resets the editor. Explicit `0` and exact fractions such as `5/2`
are valid; empty or invalid input shows an error without navigating.
Curves include regular samples plus the exact selected endpoint; they do
not show every intervening event. Recorded outcome totals are counted through
the selected causal revision. Plotly's export control saves the displayed chart.

Statistics refreshes independently of Events and Cohorts, with at most one
request in flight and a half-second refresh interval. **Statistics through …**
means its verified data is behind or differs from the selected world view.
Loading and refreshing messages explain what is pending. If a request fails,
the last verified data keeps its original source label; choose **Retry
Statistics**. A valid empty result is labeled explicitly, rather than showing
an unexplained blank plot. If chart drawing fails, the population table remains
available alongside **Retry chart**.

Use **Edit as new run** to copy a selected run’s frozen configuration into an
editable draft. The original run remains historical provenance. To compare
different runs, follow [Compare independent runs](#compare-independent-runs).

## Cohorts and causal records

A **cohort** is a named group of agents you want to study. Start with this example:

1. Select a run and open **Cohorts**. A message saying **No cohorts have been
   created** means the view loaded successfully and the run has no saved groups.
2. Choose **Use All humans example**. This fills the name, selects **Fixed
   identities**, sets Type to **Human** and Status to **Any status**, and includes
   matching identities that are already dead. The small preset initially selects
   16 humans; the ontology baseline initially selects 800, including infected humans.
3. Check **Reference for this submission**. Use the main replay controls first if
   you want to select agents at an earlier time. Creation captures the displayed
   time and revision when you click, even if the live simulation continues.
4. Choose **Create cohort** once. The form is disabled while creation is pending.
   Its success message identifies the saved definition; its card is highlighted
   after the collection refreshes. Saving a group does not change the simulation.
5. Read the card's count and population breakdown. Open **Member IDs … and
   definition** to see exactly which identities are included and how they were
   selected. The reference cursor describes the original selection; **Measured
   through …** identifies the displayed measurements.

Use **Fixed identities** to follow the same agents. Filters and the checkbox for
already-dead identities apply when the initial members are chosen. Those IDs
remain members after conversion or death, even if they no longer satisfy the
original type, role or status filter.

Use **Dynamic filters** to ask who matches now, or at the selected replay cursor.
Filters are reevaluated at each measurement. The dead-identity checkbox applies
each time. A Human-filtered identity leaves after conversion; a dead Human still
matches Human/Any status when dead identities are included. A HEALTHY or INFECTED
status filter excludes dead agents regardless of that checkbox.

To compare the two modes, create **Humans at the reference** using Fixed
identities and **Humans at each time** using Dynamic filters, both with Type Human
and Any status. Use a history containing infection, conversion or death, then
replay before and after the change. A newly infected human remains in both groups;
a converted identity stays in the fixed group and leaves the dynamic Human group.
A death stays in the fixed group; in the dynamic group its inclusion depends on
the dead-identity checkbox and status filter. To study infection specifically,
repeat with Status INFECTED: cure, conversion and death remove a member from the
dynamic infected group while its fixed counterpart retains the ID. If creating
a new example run, you can set **Initially infected** above zero and a horizon
beyond incubation, but treatment or earlier death can prevent conversion.

**Clear all filters** selects any type/status/role/model across the whole world
and includes dead identities. Optional filters let you choose a role, a model ID,
or an inclusive rectangular region entered as `xmin, ymin, xmax, ymax` in meters.
Region selection uses positions at the exact reference or measurement time.
Invalid names or region bounds are explained beside the form without discarding
your entries. Different groups can overlap; adding their counts need not equal
the population.

A card showing **0 members** is a valid result. The small preset starts with no
infected humans, so an INFECTED group is initially empty. Check its filters or
use the All humans example. Mean life and stamina average the member identities
present at the measurement cursor, including any retained dead members. Each
mean shows its denominator; a zero denominator displays **—**, not zero.

**Loading Cohorts** and **Could not refresh Cohorts** describe requests, not empty
groups. Cohorts refreshes independently of Statistics and Events. During a
delay or failure, any previous cards retain their original measurement cursor
and a stale label. Choose **Retry Cohorts** after a failure. Use **Refresh Cohorts**
to reload definitions saved in another browser while the simulation cursor is
unchanged. In agent perspective, researcher-only cohort contents are hidden and
cleared. Existing saved definitions retain their original membership rules.

Cohort membership and population counts are distinct from survival measurements:
Human survival includes only members who entered the source run as living Humans
and ends at death or conversion, while identity survival ends only at
death. Cards report eligible members, events and right-censored survivors, plus
initially non-Human exclusions, identities already dead at entry and unavailable
entry evidence. Survival exports identify their measurement definition as
`zombie-sim/cohort-survival-v3` and retain
the exact result's run/time/revision, even while a newer cursor is loading or has
failed. A child run enters at its branch boundary; inherited-prefix replay uses
the historical source run's entry. The entry run ID/time/revision are explicit.
Dynamic groups
describe current membership; differences between groups alone do not establish
causation.

In **Events**, start with this workflow:

1. Select a run and open **Events**. The latest page contains up to 500 records
   through the displayed source time and revision. A new, unadvanced run may have
   no events yet; this is a valid empty result.
2. Read the rows from top to bottom: they are in ascending ledger sequence. Rows
   show simulation time, revision and sequence. A time marked **≈** is rounded
   for readability using the shared time policy. Select the record and choose
   **Exact time** to read its original value. Replay always uses the exact time. Several records
   can share a timestamp or transaction without being the same event.
3. Choose **Older** to inspect earlier records, then **Newer** to move forward.
   Paging pins the source revision, so a running simulation cannot shift the
   pages underneath you. The browsing message identifies that fixed source.
4. Choose **Show latest events** to follow the selected view again. In live mode
   this follows new verified events. In replay it shows the latest records up to
   the selected historical revision; it does not expose later history or leave
   replay. The main viewer's **Return to live** control leaves replay.
5. To inspect an agent, select it in **World**, then return to **Events**, or use
   **Inspect identity history** in its inspector. The identity filter is applied
   before the page limit and includes actor, target and action-linked records.
   Choose **Clear identity … filter** to return to all identities.
6. Use **Search the loaded page** for action names, outcomes or other record text.
   The counts show matches within the loaded page, not matches across the whole
   run. **Clear search** removes text filtering independently of identity
   filtering. Browse other pages to examine additional history.
7. Select a record to see its full details and inspect its exact causal revision.
   **Before recorded transition** and **After recorded transition** inspect the states immediately
   before and after its committed transaction. If several events belong to that
   transaction, they share these boundaries. The selected record retains its
   original source label while you inspect those states.

**Loading Events** means a request is in progress. Long histories can take longer
to filter; you may change your selection while waiting. **Could not refresh
Events** provides **Retry Events** and retains any previous verified page with
its original source label. **Refresh Events** explicitly rereads the current
page. Statistics and Cohorts load independently.

If no rows appear, read the message: there may be no events at that cursor, no
events for the selected identity, or no text matches in the loaded page. Clear
the corresponding filter or choose another page. While browsing older pages,
reaching their newest page still leaves the source pinned; use **Show latest
events** to resume following. Viewing, searching and paging do not alter the
simulation or its recorded history.

## Compare independent runs

Use **Comparison** to put two to four runs on the same time axis. Here is a first
example:

1. Create two Small 20 agents experiments with different seeds. Let each advance
   for a while; they may be running, paused, completed or terminated when you
   compare them. A newly created, unadvanced run has one observation at time zero.
2. Select one of those runs in the sidebar and open **Comparison**. The current
   run starts selected. Under **Runs to compare**, check the second run. Labels
   show each scenario, seed, status and full run ID, so similar names are easy to
   distinguish. A fifth selection is disabled while four are selected.
3. Read **common interval** above the chart. If one run has reached 12 seconds
   and the other 8 seconds, their comparison ends at 8 seconds. A recorded
   history beginning at 5 seconds can only be compared from 5 seconds onward.
   Ordinary branches retain the earlier parent history, so their available
   history can begin before the branch point; read **History starts** in the
   source table. Equal start and end times give a single visible point;
   disjoint histories show **no common interval** with their exact bounds.
4. Choose **Population measure**: Healthy humans, Infected humans, Living
   zombies or Dead identities. Counts are raw identities, so different starting
   populations can produce different totals. Conversion moves an identity from
   Human to Zombie; death counts once, and remains add no identities.
5. Read **Captured frontier caps and actual source cursors**. The captured
   frontier is the latest history boundary used for that run's request. Its
   source at the common endpoint may be an earlier revision. Revisions belong
   to their individual runs; equal revision numbers do not establish alignment.
6. Keep the same checkboxes selected while runs advance. Comparison refreshes
   automatically when their committed times or revisions change. A paused or
   completed run can hold the shared endpoint in place. Switching workspace
   tabs preserves your selections; selecting a different main run in the
   sidebar starts a new comparison with that run selected.

All selected runs are sampled at the same exact times, including the shared
start and end. Sampling begins with one-second grid spacing and increases it
when needed to keep at most 2,000 observations per run. The interval, spacing and
count are displayed. These are sampled observations: connecting lines do not
add measurements or reveal every intervening event. Use Events for those details.

Drag on the chart to zoom. Manual zoom remains in place while verified data
updates and when you switch tabs. Choose **Reset comparison view** to restore the
shared extent. A single-time chart uses a wider axis only to make its markers
visible. Every plotted observation is also available in **All verified
observations**, with the exact time, source revision and all population counts.

**Loading Comparison** names the histories being read. While refreshing, an
existing complete result retains its original source labels. **Could not refresh
Comparison** identifies a failed run when the service can determine it; choose
**Retry Comparison**. **Refresh Comparison** explicitly rereads unchanged
sources. A still-initializing selection explains why it has no readable history.
Changing the selected run set clears the previous set's results while the new
comparison loads. Statistics, Cohorts and Events continue independently.

**Export displayed comparison CSV** exports the complete verified dataset shown
in the table, including all four counts, run IDs, scenario names, seeds, captured
frontiers, actual sample revisions, common interval, spacing, measurement version,
definition and units. During a refresh or failure, export stays tied to the
displayed older dataset and its source labels. It does not silently substitute
newer history.

Comparison uses each selected run's committed history. Seeking the main viewer
into replay leaves that comparison basis unchanged, and comparing/exporting does
not move the main replay cursor or affect simulation execution. Switching to
agent perspective clears the global comparison data.

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
| Terminate without a new checkpoint | End the worker permanently without requesting another checkpoint. Existing audit history and checkpoints remain available; this does not delete the run. |
| Run commands | Prepare a new run, branch, intervention or stop with a retained command reference. Retry an interrupted request using its original reference and payload. |
| Branch / intervene | Create a separate child at any committed revision, or schedule a resource addition/compatible role/model replacement when enabled in the frozen scenario. Model replacement explicitly resets private memory. |
| Replay scrub / Inspect recorded time | Read committed history; the executing run continues independently. Exact rational time input is accepted. |
| Replay play / speed | Advance only the viewer's recorded-time cursor. |
| Return to live | Resynchronize all scene data to the newest committed revision. |

Pause and Terminate acknowledge only after the current atomic work settles. An already-running synchronous checkpoint must finish before either command can acknowledge; the interface remains pending during that wait. After Pause acknowledges, simulation time and revisions do not advance on their own.

Termination has separate progress states: **Termination requested** while the
command awaits a boundary, **Stopping / cleanup** after the durable
acknowledgement, and **terminated** with a **Worker cleanup complete** notice
after worker exit is verified. The sidebar separates **Active**, **Saved / completed**, and
**Terminated history**. Terminal live subscriptions close after their final
frame; select a historical cursor to inspect the retained record.

Each command uses a unique ID and a control generation. The UI displays pending and actual applied/rejected outcomes, including effective time/revision. Stale commands reject with a refreshable message. Retrying an identical command ID uses its durable result. Completed and terminated runs are immutable. Branches can resume any recorded committed boundary because the ledger preserves scheduler state and private model memory at every revision; they are not restricted to checkpoint-file times.

The **Run commands** dialog retains unresolved requests across reloads. A response timeout does not imply that the command failed: **Retry original command** reconciles the same durable reference, including incomplete run or branch creation. Reusing a reference with different parameters is rejected. A new command receives a new reference after a terminal acknowledgement. An intervention at the current time is applied before acknowledgement; a future intervention is scheduled.

For **Recorded agent observation**, first select an identity, then change perspective. The global map, statistics, and privileged inspector disappear. The view displays only the actual input recorded for the chosen decision, including its historical time/revision. If no observation was recorded, the interface reports that rather than substituting current global knowledge.

## Reconnect, exports, and accessibility

Live subscriptions send self-contained snapshots with sequence and revision IDs. The client acknowledges each snapshot; only one can be outstanding. Slow clients cannot accumulate an unbounded semantic queue. A reconnect requests a fresh snapshot and does not restart or stop a run.

Use **Export** for scene PNG, chart PNG/SVG, CSV, Parquet or portable HTML replay. Each job pins its source run and committed revision before rendering; downloads include provenance. Progress and cancellation refer to the actual export task. The map PNG button and chart toolbar also provide quick captures. Cohort export retains its rule and membership. CLI exports additionally support ontology Turtle.

Controls and form fields have accessible labels and visible keyboard focus. Search tables provide an alternative to selecting canvas markers. Chart data is available as a table. Status symbols supplement color, the layout adapts to narrow windows, and reduced-motion preferences disable CSS motion.

## Practical boundaries

Use a current browser supporting Canvas, WebSocket, ResizeObserver and native ES modules. Actual Chromium and Firefox keyboard workflows pass. Recorded 30-second browser benchmarks measured approximately 60 FPS at 1,000 agents and 59 FPS at 10,000 agents; the latter displays a spatial-aggregation label while retaining selected-identity inspection. See [the current refinement report](TESTING_REFINEMENT.md) for raw samples, input and receipt latency, browser coverage and scope. These renderer measurements do not measure simulation throughput. Offline replay animations use at most 300 recorded samples; their effective interval and source cursors are embedded in the portable HTML. They are sampled replay artifacts, not video recordings or evidence of uncommitted motion. Legacy runs without a runtime journal need a complete retained checkpoint for exact continuation.
