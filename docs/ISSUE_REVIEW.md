# GUI and launcher issue review

**Current review: I27 — GUI times expose long exact fractions instead of readable seconds.**
The updated task plan reports values such as
`127500000000000017/2500000000000000` appearing frequently in the GUI.
The symptom is reproduced in Chromium and Firefox; source and ontology review
are complete. The [I27 proposal](#i27-gui-times-expose-long-exact-fractions)
below was approved: “I approve the I27 proposal. Implement and verify the fixes.”
**Implementation and verification are complete within the scope below.** All 38
supplied browser cases and the dedicated Chromium/Firefox workflows pass.
I01–I26 approval, implementation and verification records
remain below; [I26's final evidence](../artifacts/issue26-fix/verification.json)
is retained.

Review opened on 2026-11-25 against the current step in
[the task plan](../prompts/zombie_game_plans.md). **Issues I01–I24 are approved for investigation and implementation, with
existing audit history retained.** After I11, the user approved I12 and explicitly
approved all remaining issues. This supersedes the earlier per-issue
approval pauses recorded below for that earlier batch. The latest updated plan
again requires individual review and approval for the newly reported issue.
Any ontology or problem-formulation changes still require separate approval.
The task plan, ontology, running
services and existing simulation records are not changed by this work.

This inventory separates verified source defects, observations from the actual
workspace, and explanations that still need a controlled reproduction. Earlier
passing acceptance tests do not establish that the newly reported workflows are
correct. A proposed fix is not a guarantee by itself: the acceptance conditions
below must pass before that issue can be called fixed.

## Review queue

| ID | Issue | Evidence | Approval |
| --- | --- | --- | --- |
| I01 | Termination, retained history, misleading saved-run classification and continuing CPU work | Real-worker/browser, immutable-audit, retained-WAL reader and resource-cleanup checks passed | Approved with existing audit history retained; completed |
| I02 | Opening the GUI falsely reports world initialization while loading existing history | Chooser, truthful loading, cancellation, retry, slow-summary and creation checks passed | Approved; completed |
| I03 | Validate can parse an empty configuration before it has loaded | Metadata loading/retry, guarded parsing, visible feedback and configuration regressions passed | Approved; completed |
| I04 | Deleting numeric input forces zero back into the field | Nine-field editing, domain and payload checks passed in Chromium and Firefox | Approved; completed |
| I05 | Population changes leave role counts inconsistent; percentage controls are missing | Exact allocation, imported/saved targets, real preview/launch and CLI parity passed in Chromium and Firefox | Approved; completed |
| I06 | Statistics can be blank or stale, including its time axis | Previous-build reproduction, Chromium/Firefox workflows, independent sampler and HTTP cancellation checks passed | Approved; completed |
| I07 | Cohorts have unclear empty states and share unrelated request failures | Independent historical oracles, Chromium/Firefox workflows, HTTP cancellation and five acceptance cases passed | Approved; completed |
| I08 | Events stops showing new events after its early-history limit | Independent ledger oracles, Chromium/Firefox workflows, HTTP cancellation and six acceptance cases passed | Approved; completed |
| I09 | Comparison does not refresh when selected runs advance | Independent history oracle, Chromium/Firefox workflows, HTTP cancellation and four acceptance regressions passed | Approved; completed |
| I10 | A comprehensive guide must explain complete everyday workflows | Nine screenshots, actual GUI/launcher/CLI workflows, short baseline and documentation checks passed within the stated limits | Approved; completed |
| I11 | The human decision model appears blank despite an actual default | Registry/assignment/old-checkpoint checks and final Chromium/Firefox workflows passed; one extra acceptance case blocked by the separate I22 adapter ambiguity | Approved; completed within stated verification limits |
| I12 | Launcher service shutdown waits without useful progress | Busy/queued reader and export cleanup, command/crash races, timeout retry, both browser states and complete launcher workflows passed | Approved together after I11; completed |
| I13 | Direct CLI resume can reopen a GUI-terminated run | Durable termination enforcement, unchanged rejected histories and permitted continuation passed on both backends | Approved together after I11; completed |
| I14 | Ordinary field edits can silently overwrite Advanced JSON edits | Mixed edits, invalid JSON protection and explicit discard passed in Chromium and Firefox | Approved together after I11; completed |
| I15 | Cohort JSON export can mislabel the time/revision of cached results | 28 exports checked against their exact historical cursor in Chromium and Firefox | Approved together after I11; completed |
| I16 | First registration of unindexed histories can reconstruct them during service startup | Metadata-only first registration and indexed startup, integrity checks and history preservation passed | Approved together after I11; completed |
| I17 | Partial JSON drafts can validate with default seeds but fail Launch's seed check | Actual empty-draft, explicit and replicate-seed launches passed in both browsers | Approved together after I11; completed |
| I18 | Role-map order can affect seeded per-identity role assignment | Canonical versioned ordering, JSON/TOML equivalence and old-checkpoint continuation passed | Approved together after I11; completed |
| I19 | Initially Zombie cohort members may be counted as Human-survival events | Final v3 run-entry risk sets: 124 cursors/856 cohort comparisons, imported deaths, nested branches, plus 748 prior cohort checks passed | Approved together after I11; completed |
| I20 | Model availability validation may not enforce Human/Zombie applicability | Defaults, explicit/imported agents and immediate/future interventions checked on both backends | Approved together after I11; completed |
| I21 | Interrupting a direct headless run can fail while saving its checkpoint | 14 controlled real-SIGINT cases and actual checkpoint I/O failure/recovery passed | Approved together after I11; completed |
| I22 | Browser acceptance adapter's run selector also matches Comparison checkboxes | Sidebar-button selector and unchanged edit/intervention, stale-control and configuration parity cases passed | Approved together after I11; completed |
| I23 | Conversion ignores the scenario's chosen Zombie model | Real conversion uses selected Zombie model and fresh memory on both backends | Covered by blanket approval; completed |
| I24 | Explicit agents without assignments may ignore scenario model defaults | Both initialization paths/backends preserve explicit assignments and fill missing defaults correctly | Covered by blanket approval; completed |
| I25 | Analysis detail clicks make historical time zero look like stopped/reset execution | Separate execution/view clocks, explicit history navigation, corrected time editor and truthful status; both browser workflows plus 12 acceptance cases passed | Individually approved; completed within the verification scope below |
| I26 | Resizing the baseline world leaves dependent layout coordinates unchanged | Coherent resizing, actual 1,000-agent preview/launch, custom/import/save workflows and 499 acceptance cases passed | Individually approved; completed within the verification scope below |
| I27 | GUI times expose long exact fractions instead of readable seconds | Shared formatting, exact controls and data preservation verified; 38 browser acceptance cases and both-browser regressions passed | Individually approved; completed within the verification scope below |

## I01 Termination and what without save means

**Approval.** On 2026-11-25, the user approved this proposal with existing audit
history retained, and requested implementation and verification before I02 is
presented for review. No discard operation or ontology change is authorized.

**Observed behavior.** In the actual `runs/launcher` workspace, all five indexed
runs have status `terminated` and applied termination receipts. Each primary
ledger's latest revision equals its recorded termination revision: 21000, 233000,
2766, 10211 and 47520. The manager's worker-lease table is empty. Each managed
`worker-checkpoint.json` modification time precedes its termination request.
These observations support that those runs stopped advancing and did not write
a new managed checkpoint on termination. They do not, by themselves, prove that
every operating-system process has exited or identify the user's CPU consumers.

**What is saved today.** Existing journals and older checkpoints remain on disk;
one current primary ledger is approximately 3.576 GB. The sidebar renders every
indexed run under the literal heading **SAVED RUNS**, including terminated runs.
Consequently, “without save” currently means *without requesting another
checkpoint*, not *discard the run's already-recorded data*.

**Causes.** The termination handler deliberately retains committed history and
skips its save paths. It records an applied receipt before closing the process
pool and releasing the worker lease. Separately, a terminal run remains subscribed
to live updates. The WebSocket handler reconstructs a full scene before checking
whether its revision changed, and repeats after an approximately 0.1-second idle
wait. Full state reconstruction and copies can therefore keep the web service
busy even after the simulation has stopped. This is a verified source mechanism;
live process/thread sampling is still needed to attribute the reported CPU load.

Sources: [termination handler](../src/zombie_sim/application.py#L248),
[worker cleanup](../src/zombie_sim/application.py#L321),
[pool shutdown](../src/zombie_sim/runtime.py#L411),
[live subscription](../gui/src/main.tsx#L160),
[sidebar](../gui/src/main.tsx#L218),
[stream loop](../src/zombie_sim/server.py#L237).

**Approved behavior.**

1. Distinguish “termination requested,” “simulation stopped,” and “worker cleanup
   complete.” Keep durable command acknowledgement and actual resource cleanup
   separately observable; do not present an early receipt as proof of process exit.
2. Check a cheap committed revision/control version before constructing a scene.
   Reuse immutable projections and prevent duplicate simultaneous reconstruction.
   Finish or idle terminal subscriptions after their final state; explicit history
   inspection remains possible without continuous background rebuilding.
3. Replace the blanket saved-run classification with clear Active, Saved/Completed
   and Terminated-history groups. A terminated run should not look like a saved,
   resumable experiment.
4. Retain existing audit history and use an explicit label such as **Terminate
   without a new checkpoint**. Explain retained history beside the control.

**Retention decision is part of this review.** The recommendation above preserves
the existing research record. If the desired action is instead *stop and discard
all run output*, that requires a separate explicit lifecycle/retention proposal,
including active readers, export jobs, checkpoint files and branch references.
It must not be implemented as an incidental sidebar filter or an unapproved
filesystem deletion. [Ontology section 16.1](../ontology/zombie_game_ontology_v0.1.md#L677)
requires reconstructable semantic records and final termination information;
[implementation-plan sections 10.2–10.4](../prompts/task_2_implementation_plan.md#L369)
require authoritative history and control audit. Whether a deliberate discard
operation changes that contract must be reviewed before changing either document.

**Why the proposal addresses the causes.** Worker cleanup becomes an observable
completion condition; unchanged terminal state no longer triggers repeated
reconstruction; the interface stops confusing retained audit history with a saved
continuation. None of these recommended changes alters the simulated world rules.

**Acceptance conditions.** Exercise small and baseline-sized runs with the browser
open and closed, while paused, while advancing and during checkpoint work. Verify
stable world/time revisions after the effective termination boundary; no checkpoint
requested by termination; coordinator/pool exit and lease release; no repeated
unchanged terminal snapshot reconstruction; correct sidebar grouping; and retained
history integrity. Measure process-specific CPU/read activity before and after.
An in-progress checkpoint may finish; the UI must describe that wait accurately.

**Implemented and verified on 2026-11-25.** The implementation now exposes
`resource_status` separately from a durable command receipt. The GUI shows
Termination requested, Stopping / cleanup, then terminated with an explicit
Worker cleanup complete notice. Existing checkpoints and audit history remain
available in Terminated history. The button reads **Terminate without a new
checkpoint**, with a caveat that an already-running checkpoint can finish.

Live streams check committed metadata before reconstructing a scene, reuse a
bounded cache of detached compact projections, coalesce simultaneous reads, and
close after an acknowledged final terminal frame. A second head check prevents
termination during slow reconstruction from closing the stream on an older
scene. Cleanup continues to be observed through lightweight run summaries;
explicit history inspection remains available.

| Verification | Result |
| --- | --- |
| Real 20-agent run, browser open, deliberately delayed cleanup | Durable termination ACK observed while coordinator/pool still lived; UI remained in cleanup until actual exit. |
| Real 1,000-agent run, browser closed, terminate while advancing | Final revision/time matched the termination receipt and stayed stable; original managed checkpoint hash remained unchanged; coordinator and both pool workers exited. |
| Real 1,000-agent run, browser open, terminate while paused | Correct grouping, cleanup notices, terminal stream closure, retained replay and no page errors. |
| Terminate queued during a real checkpoint | Request remained pending; the already-started checkpoint completed; termination requested no additional checkpoint. |
| Paused and terminal browser idle intervals | Zero additional history reconstruction calls and zero projection builds after initial data settled; terminal sockets closed without reconnecting. |
| Eight concurrent cold readers | One reconstruction; detached results and per-request generations preserved. |
| Immutable audit contents in all four real-run scenarios | Pre-termination commit, runtime-journal and event row hashes remained identical after termination and cleanup. |
| Persistent metadata readers across 11 copied real ledgers | Forty reads reused one connection against an 8.47 MB WAL; idle cache stayed within eight entries; eviction and shutdown closed all readers. WAL truncation succeeded and file descriptors returned from 117 to their original 90. |
| Slow projection overtaken by termination; unchanged-revision control update | Both focused protocol checks passed; final revision and controls were delivered with one outstanding frame. |
| Existing regressions | Manager recovery, command idempotency, terminal restore, GUI replay preservation and stream gap/duplicate/reorder checks passed. |
| Frontend | TypeScript, production build, packaged assets and visual inspection passed. |

In the isolated 1,000-agent test service, the prior eager projection used
**196.01 ms CPU per call** (five calls), the new idle head used **0.120 ms per
call** (50 calls), and a detached cached scene used **32.31 ms per call** (ten
calls). Idle heads and cached scenes performed zero history reconstructions.
The report includes service-process CPU and read counters. These measurements
demonstrate the removed reader work; they do not identify the processes behind
the user's earlier CPU observation.

**Retained-history verification follow-up.** Read-only checks of the existing
large histories found another I01 reader cost: opening a fresh SQLite connection
for every head can rebuild its WAL index. The 3.576 GB primary with a 1.620 GB WAL
used approximately 323 ms per head despite no scene reconstruction. The fix now
retains at most eight idle read-only metadata connections, separately from scene
reconstruction. Busy connections cannot be evicted mid-request; temporary
overflow readers close when their request finishes. All readers close with the
manager, and no metadata read transaction remains open between requests.

The repeated read-only probe passed on all five existing histories. Warm metadata
reads on the largest history fell to **0.043 ms median** after its one-time
335 ms attachment. One hundred reads used **4.49 ms CPU and 46 KB logical reads**,
compared with approximately 31.5 CPU seconds and 162 GB logical reads before
connection reuse. These figures measure the metadata path separately from the
process-status observer, with the operating-system page cache left intact.
No large scene was materialized. The smallest retained history's cached scene
fell from 26.7 ms to 1.14 ms. Five metadata connections opened and closed exactly;
file descriptors returned from four to four.

Primary histories, WALs, checkpoints and manifests preserved their sizes and
modification times; files up to 16 MiB also preserved their SHA-256 fingerprints.
SQLite refreshed its transient shared-memory indexes. Evidence:
[before probe](../artifacts/issue1-retained-head-probe.json) and
[after probe](../artifacts/issue1-retained-head-after.json).

Evidence: [integration report](../artifacts/issue1/verification.json),
[1,000-agent browser report](../artifacts/issue1/baseline-browser-open/browser.json),
[cleanup screenshot](../artifacts/issue1/baseline-browser-open/stopping-cleanup.png),
[retained-history screenshot](../artifacts/issue1/baseline-browser-open/terminated-history.png),
[replay regression](../artifacts/issue1-replay-acceptance.json),
[stream regression](../artifacts/issue1-stream-acceptance.json),
[integration check](../implementation_checks/issue1_check.py), and
[protocol checks](../implementation_checks/issue1_stream_check.py).

**Scope and limits.** These were short functional runs, not another full 1,800 s
baseline acceptance experiment. No ontology or acceptance-test inputs changed.
Existing services were not restarted; the GUI service must be restarted to load
the backend fixes. I12's broader service-shutdown problem and I13's direct CLI
continuation restriction remain separate queued issues.

## I02 Opening the GUI reports initialization while reading history

**Approval.** On 2026-11-25, the user approved this proposal and requested
implementation and verification before I03 is presented. This approval covers
viewer navigation, truthful loading states, retry and cancellation. It does not
authorize the separate configuration-editor fixes in I03 or later issues.

**Cause and evidence.** Opening the launcher GUI does not itself create a world.
The frontend can automatically select an existing run, then display “Initializing
the world” whenever it has a run ID but no loaded view. That condition also covers
loading a large saved/terminated history, errors and a delayed service response.
Existing large histories are expensive to reconstruct, particularly alongside
the redundant reader work described in I01.

Two related loading mechanisms were confirmed during implementation. Replacing
run-summary requests every second could discard every response when latency
exceeded one second. Also, the original creation endpoint could wait up to 30
seconds for initialization before returning the new run identity, preventing
the viewer from identifying that initialization promptly. The approved loading
behavior therefore also requires coalesced summary polling and an immediate
acceptance response for GUI creation, without changing durable command receipts.

**Approved proposal.** Represent no selection, actual initialization, loading existing
history, ready, and failed states separately. Do not automatically reconstruct a
large terminated run merely to open the home screen. Show a run chooser/summary,
then load the selected history with progress, cancellation and an error/retry path.
Keep the actual initialized run status separate from viewer-loading state.

**Approved concrete behavior.**

| Situation | Intended screen behavior |
| --- | --- |
| Open launcher option 9 / open the GUI | Load lightweight run summaries and show “Choose a run or create an experiment.” Do not select and reconstruct a retained run automatically. |
| Create a new experiment | Select the newly requested run. Show “Initializing world” only while the service reports that this run is initializing. |
| Select an existing run | Show “Loading recorded history” with the run identity and known committed time/revision. Do not invent a completion percentage. |
| Cancel or choose another run while loading | Cancel the viewer request and invalidate its response so it cannot replace the newly selected view. Release unnecessary reader work where possible; report honestly if an already-started operation must finish. The simulation's execution state is unaffected. |
| Loading succeeds | Show the requested scene and its actual run status, including retained terminated history. |
| Loading fails or the service is unavailable | Show the actual error with Retry and Return to run list. Do not leave “Initializing world” on screen. |

This proposal changes viewer navigation and loading feedback. It does not change
simulation rules, create an experiment merely by opening the GUI, or rewrite
existing history. Launcher service-start behavior will be verified as part of
the reproduction, rather than assumed to be the source of world creation.

**Why and validation.** Status-specific messages remove the false claim that a
world is being created. Test an empty workspace, existing tiny/large histories,
initializing and failed runs, delayed requests and unavailable services. Opening
the GUI must not create a run or automatically launch expensive history work.
Check request counters and unchanged run identities/revisions when opening the
home screen. Deliberately delay a history response, cancel it or select another
run, and verify that the late response cannot change the current selection.
Source: [selection/loading/view logic](../gui/src/main.tsx#L123).
No ontology change is proposed.

**Implementation.** The home screen now presents a run chooser without automatic
selection. Viewer state distinguishes idle, loading run information, actual
initialization, recorded-history loading, ready and failed. History errors have
explicit Retry/Return actions. Run summaries allow one in-flight request, so
responses slower than the polling interval can still update the chooser.

Cancelling or switching aborts the viewer request and invalidates stale response
tokens and sockets. The HTTP handler watches actual disconnects and signals a
request-specific cancellation event. Private SQLite queries and patch replay
check that event; lock waits are cancellable; readers close on exit. Atomic
decoding, projection and copying may finish before the next cancellation check.
Other readers, simulation execution and retained research data are unaffected.

GUI creation requests an immediate HTTP 202 acceptance containing the reserved
run identity, rather than waiting for initialization to finish. That response
does not invent an initial time/revision or replace the durable creation receipt.
The selected run waits for a fresh summary before probing history. Execution
controls remain guarded until the start acknowledgement arrives; if that response
is lost, the GUI reconciles its own pending start from committed run summaries
without resubmitting creation. A late acknowledgement cannot reselect a run.

**Implemented and verified on 2026-11-25.**

| Check | Result |
| --- | --- |
| Empty/populated browser home and launcher option 9 | No new run, control command, automatic history reconstruction or run stream; existing run frontiers stayed unchanged. Launcher reused its existing disposable service. |
| Run summaries delayed by 1,500 ms each | Successive summaries completed; chooser and explicit selection became ready despite latency exceeding the polling interval. |
| Real 20-agent and 1,000-agent histories | Explicit selection loaded the correct population; delayed history showed recorded-history loading with its known committed frontier. |
| Cancel, switch selection and late responses | Actual server readers observed cancellation and finished; late successful or failed responses could not replace a newer selection or same-run request. |
| Active-run viewer cancellation | Simulation remained running; cancellation added no control command or generation change. |
| History/service errors and failed initialization | Errors were distinct from initialization; Retry and Return worked. |
| GUI creation held before actual worker initialization | HTTP 202 returned the identity without fabricated time/revision; the GUI waited for a fresh summary and made no full-history requests before readiness. Cancelling/reselecting the viewer left the accepted run unchanged. |
| Committed-boundary labels | Existing history showed its actual committed time/revision. Initializing viewer and chooser omitted time/revision while the ledger did not yet exist. |
| Held and lost start acknowledgements | Controls stayed guarded while acknowledgement was pending, including after navigation. Lost receipt recovery submitted no duplicate creation/start; the next Pause used the correct control generation. |
| Five focused reader checks | Cancellation before work, during lock waits, between patches and after atomic projection closed private readers, preserved independent readers/cache, and left immutable ledger contents unchanged. |
| Actual HTTP disconnect through production middleware | Previous polling missed the disconnect; the receive watcher observed it in approximately 52 ms. A second reader and subsequent retry succeeded; audit and frontier stayed unchanged. |
| Creation receipt/retry compatibility | Immediate acceptance retained one run identity; finalized creation receipt remained pinned to time/revision zero after later advancement; altered retry content was rejected. |
| Existing regressions and frontend checks | Stale controls/seek, observation cache clearing, GUI/CLI configuration parity, manager recovery, terminal restore and I01 stream checks passed. TypeScript and packaged production build passed. |

The browser suite covers 16 workflows and reports no page errors. These are
short functional checks, not a repeat of the full 1,800-second acceptance run.
The 1,000-agent browser fixture has shallow real history plus controlled delay;
it verifies viewer behavior, not naturally accumulated multi-gigabyte history
throughput. Patch replay and atomic-stage cancellation have separate reader checks.
Screenshots were reviewed for the chooser, loading, error/retry and actual
initialization states.

Evidence: [browser/integration report](../artifacts/issue2/verification.json),
[populated browser checks](../artifacts/issue2/browser-populated.json),
[launcher check](../artifacts/issue2-launcher/verification.json),
[disconnect comparison](../artifacts/issue2/disconnect/verification.json),
[stale-control/seek regression](../artifacts/issue2-stale-acceptance.json),
[observation regression](../artifacts/issue2-observation-acceptance.json),
[configuration parity](../artifacts/issue2-config-parity.json),
[reader checks](../implementation_checks/issue2_reader_check.py), and
[creation checks](../implementation_checks/issue2_creation_check.py).

**Scope.** Opening the browser home screen does not reconstruct indexed histories.
Previously unindexed histories can still be reconstructed during first service
registration; that separate reported mechanism is queued as I16. I02 does not
establish bounded shutdown for all service work (I12). No ontology, existing
audit records, supplied acceptance-test inputs or running user services change.
Restart the existing web service to load these backend and packaged GUI changes.

## I03 Validate reports Unexpected end of JSON input

**Approval.** The user approved I03 and requested implementation and verification
before I04 is presented. This covers configuration loading, metadata validation,
retry and guarded JSON parsing. Numeric editing, role allocation, model defaults
and field/Advanced JSON synchronization remain separately queued.

**Original cause and evidence.** Configuration started with `advanced = ''`, then filled it
after asynchronous `/api/config` loading. Validate/Preview/Launch did not require
that loading to have completed. Their handler immediately called
`JSON.parse(advanced)`. Parsing `''` reproduces the exact reported error. Empty
or incomplete manually edited JSON takes the same path. The user's exact browser
sequence is not yet traced; a malformed HTTP response is not assumed to be the cause.

**Approved proposal.** Add loading/ready/failed states, disable dependent actions until the
presets are valid, provide metadata retry, and use one editor parser with clear
empty/incomplete-configuration messages. Validate the metadata response shape.

**Approved concrete behavior.**

| Situation | Intended behavior |
| --- | --- |
| Open New experiment while configuration metadata is loading | Show “Loading configuration”; disable Validate, Preview placement and Launch until a valid draft is available. |
| Metadata fails, is empty, or has an unexpected structure | Show a readable configuration-loading error and Retry; keep dependent actions disabled. |
| Metadata loads successfully | Populate the selected preset and enable actions against that draft. |
| Advanced JSON is empty or incomplete | Explain that a complete JSON configuration is required, with a useful parse error when available; preserve the entered text. |
| Retry after a loading failure | Load and validate metadata, then restore normal editing and validation. |

All dependent actions will use the same guarded draft parser, so an immediate
click or keyboard submission cannot bypass the loading state. This does not
change numeric-field editing, role allocation, model defaults or ontology rules;
those remain separate queued issues.

**Why and validation.** Actions cannot parse the uninitialized empty draft. Test
slow, failed and empty metadata responses, immediate clicks, malformed Advanced
JSON and successful retry. Source: [Configuration](../gui/src/main.tsx#L99).
No ontology change is proposed.

**Implemented and verified on 2026-11-26.** The configuration dialog now has
loading, ready and failed states, with explicit Retry. Metadata is checked for
the editor's supported schema, preset objects and field structure before use;
simulation-domain validation remains in the backend. Editing, preset selection,
import, save, validation, preview, launch and export are guarded until metadata
is ready. Aborted or obsolete metadata responses cannot overwrite a newer dialog.

One draft parser handles Validate, Preview, Launch and Export. It rejects empty,
incomplete and non-object JSON with a readable message, preserving the text.
Editing or choosing another preset clears old errors, so correction can enable
Launch again. Feedback stays outside the scrolling editor, beside the action
buttons. Keyboard focus excludes controls disabled through their parent fieldset.
Save draft deliberately preserves raw text after loading; it does not certify
that unfinished edits form a valid simulation configuration.

| Verification | Result |
| --- | --- |
| Delayed metadata | Mouse, keyboard and programmatic activation submitted no API mutation and saved no unloaded draft; Tab and Shift+Tab stayed inside the dialog with Advanced JSON expanded. |
| 13 metadata fault cases | HTTP failure, empty/malformed responses, missing/invalid containers, malformed field records and unsupported schema all produced a loading error; explicit Retry restored editing. |
| 32 invalid draft/action combinations | Empty, whitespace, incomplete, array, null and scalar drafts were rejected by Validate/Preview/Launch/Export with text preserved, no API work and no new run. Every error remained visible and unobscured without scrolling. |
| Closed/reopened dialog | A late completed metadata response did not replace the new editor's text. |
| Valid workflows | Small and baseline presets validated; a corrected draft produced a real 20-agent preview and JSON export, then exactly one real run through I02's immediate HTTP 202/start-acknowledgement flow. |
| Edit as new run | Copied configuration validated; original source history, frontier, status, generation and command count stayed unchanged. |
| Existing acceptance regressions | All five `GUI_VALIDATION_*` cases, `GUI_CONFIG_CLI_PARITY` and `GUI_PREVIEW_RNG_ISOLATION` passed. |
| Frontend and cleanup | TypeScript, production build, packaged assets, independent review and visual inspection passed. The eight browser workflows reported no page errors; disposable service/workspace cleanup completed. |

Evidence: [integration report](../artifacts/issue3/verification.json),
[browser results](../artifacts/issue3/browser.json),
[visible JSON feedback](../artifacts/issue3/draft-json-error.png),
[metadata retry screen](../artifacts/issue3/metadata-error-retry.png),
[validation regressions](../artifacts/issue3-validation.json),
[GUI/CLI parity](../artifacts/issue3-config-parity.json), and
[preview isolation](../artifacts/issue3-preview-isolation.json).

**Scope and limits.** This is targeted configuration verification, not a rerun of
the entire acceptance catalogue or long baseline experiment. Browser import
helpers now wait for the editor to become enabled; supplied acceptance inputs
and assertions are unchanged. Existing user services, simulation records, ontology
and the user's task plan were not modified by I03. Reload the GUI to use the new
bundle. I04/I05/I11/I14 remain separate, and partial-draft launch seed handling
was reported as I17 before further investigation.

## I04 Numeric fields cannot be cleared

**Approval.** The user approved I04 and requested implementation and verification
before I05 is presented. This covers editable numeric text, commit/submission
validation, permitted zero and decimal values, and preset/import/copy resets.
Role allocation, model defaults and broader Advanced JSON synchronization remain
separate queued work.

**Cause and evidence.** Every numeric keystroke is converted with `Number(value)`;
`Number('')` is zero. The controlled field immediately writes that zero back.
The manual Workers field uses the same pattern.

**Approved proposal.** Keep editable text, including an empty string, while typing. Parse
and validate at an appropriate commit/submission boundary. Distinguish a missing
required value from a legitimate zero and reuse this behavior across numeric
fields, including new percentage inputs.

**Concrete behavior to review.** Apply this to all nine numeric controls in
New experiment: seed, horizon, incubation duration, world length/width, Human/
Zombie/infected counts, and manual Workers.

| Situation | Intended behavior |
| --- | --- |
| Backspace/Delete removes the last digit | Keep the field empty; do not insert zero or restore the old value. |
| Type a replacement after clearing | Display the entered number without an injected leading zero. |
| Leave a field blank/incomplete, or submit while it is still focused | Preserve the text, identify the field needing a complete number, and submit nothing. Do not silently use the previous value. |
| Enter a complete number | Parse at blur or submission and preserve the existing backend domains: zero is allowed for seed/counts; durations, dimensions and manual worker counts must be positive; seed/counts/workers must be integers. |
| Load a preset, import, or copy an existing run | Replace the editing buffers with the chosen configuration's actual values. Clear errors from the prior draft. |
| Switch worker selection | Preserve the explicit `auto` mode and keep manual input/errors consistent with the newly selected mode. |

Validate, Preview, Launch and configuration export must use the same committed
numeric values, including when a field still has focus. The editor will be
reusable for I05's later percentage controls, but I04 does not add percentages
or recalculate role counts. I14's broader conflict between field edits and
Advanced JSON remains a separate review. No defaults or ontology domains change.

**Why and validation.** Empty text is no longer coerced to zero. Test clearing,
select-all replacement, retyping, decimals, allowed zero, positive-only values
and submission while blank. Exercise each field with both keyboard deletion
methods, integer versus fractional input, blur and focused-field submission,
preset/import/copy replacement, and payload agreement with the visible values.
Invalid input must never create a run. Sources:
[numeric inputs](../gui/src/main.tsx), [backend domains](../src/zombie_sim/config.py#L97).
No ontology change is proposed.

**Implemented and verified on 2026-11-26.** All nine numeric controls keep raw
editable text until blur or submission. The shared parser distinguishes empty,
incomplete, nonfinite and out-of-domain values, with an inline field error and
visible action feedback. It preserves backend domains, including positive
dimensions/durations smaller than the metadata's suggested UI minimums.

Pending numeric edits commit together from current references, so a click that
blurs the input cannot submit an earlier value. An invalid pending field blocks
Validate, Preview, Launch, Export and Save; correcting another field cannot hide
it. Numeric commits update only edited paths in the current Advanced JSON,
preserving unrelated properties. A newer explicit JSON edit supersedes pending
numeric text. Preset/import/copy replacement clears old buffers and errors, while
switching worker mode clears only that control's pending edit. Save still permits
unfinished Advanced JSON when there are no pending numeric edits, as in I03.

| Verification | Result |
| --- | --- |
| Clearing and retyping | All nine fields passed repeated Backspace and select-all/Delete replacement in both Chromium and Firefox: 18 sequences per browser, with no injected zero. |
| Blank input and actions | 45 field/action combinations per browser preserved blank text, displayed errors, sent no API work and did not overwrite the saved draft. Native mouse blur/click and keyboard submission also passed. |
| Numeric domains | 33 cases per browser covered allowed zero, positive values, integer/fractional values, finite decimals/scientific notation, incomplete text and overflow: 11 accepted and 22 rejected as intended. |
| Draft transitions | Multiple pending edits, correction, worker modes, presets, imports, copied runs and explicit Advanced JSON edits passed without stale numeric submission. |
| Real payloads | Validate, real Preview, JSON Export and exactly one HTTP 202 Launch agreed on all nine edited values. Created test runs reached terminal resource cleanup. |
| I03 regression | All eight workflows passed, including 13 metadata-failure/retry and 32 invalid-draft/action cases. |
| Existing acceptance | All five `GUI_VALIDATION_*` cases and `GUI_CONFIG_CLI_PARITY` passed. |
| Frontend and evidence | TypeScript, production build, packaged assets, independent source/evidence review and visual inspection passed. Both browsers reported zero page errors. Source-run audit hashes, frontier, status, generation and command counts were unchanged; disposable services and workspaces were removed. |

Evidence: [Chromium integration report](../artifacts/issue4-chromium/verification.json),
[Firefox integration report](../artifacts/issue4-firefox/verification.json),
[visible blank-field feedback](../artifacts/issue4-chromium/blank-field-error.png),
[corrected Firefox preview](../artifacts/issue4-firefox/corrected-numeric-draft.png),
[configuration regression report](../artifacts/issue4-configuration-regression/verification.json),
[validation acceptance report](../artifacts/issue4-validation.json), and
[GUI/CLI parity report](../artifacts/issue4-config-cli-parity.json).
The reproducible checks are [issue4_check.py](../implementation_checks/issue4_check.py)
and [verify_issue4.cjs](../gui/verify_issue4.cjs).

**Scope and limits.** Verification used desktop Chromium and Firefox with short
functional runs, not the complete acceptance catalogue or a performance/long-run
baseline. Existing user services, simulation histories, supplied acceptance
inputs/assertions, ontology and task-plan edits were preserved. Reload the GUI
to use the rebuilt assets. I05 role allocation, I11 model defaults, I14's broader
nonnumeric-field/Advanced JSON synchronization and I17's partial-draft launch
seed handling remain separately queued.

## I05 Role percentages and population consistency

**Approval.** The user approved the I05 proposal and requested implementation
and verification before I06 is presented. This includes target percentages,
exact-share integer allocation, rounding visibility and saved/imported provenance.

**Cause and evidence.** Changing a population field updates only that field;
existing Human/Zombie role counts remain fixed. The backend correctly rejects
role totals exceeding the population. For example, changing baseline Humans to
100 or Zombies to 10 reproduces the respective validation failures. The built-in
small preset has empty role maps, so that particular failure depends on nonzero
allocations in a baseline/import/copied configuration.

**Approved proposal.** Provide separate type-compatible role panels with editable target
percentages, a visible automatic **No active role** remainder and calculated
integer counts. Recalculate when a population or target percentage changes.
Use deterministic largest-remainder allocation, including the no-role share,
to make counts sum exactly to the population. Show realized percentages whenever
rounding differs. Reject invalid shares or totals above 100%, handle zero
population explicitly, and preserve unchanged imported exact counts.

**Concrete behavior to review.**

| Situation | Intended behavior |
| --- | --- |
| Edit Humans or Zombies | Recalculate that type's role counts from its target percentages once the population is a valid integer; update all displayed counts together. |
| Edit a role percentage | Preserve the editable text using I04's numeric behavior; after a valid commit, update the calculated counts and the automatic no-role remainder. |
| Role targets sum to less than 100% | Assign the remaining target share to **No active role**, so all target shares total 100%. |
| Role targets are negative, nonfinite, incomplete, or total more than 100% | Keep the input with a useful error and block submission; do not silently normalize it. |
| Population is zero | Show zero counts and realized percentages as “—”; retain the target shares for a later population increase. An imported zero population without targets starts with 100% no-role. |
| Import existing integer role counts | Keep valid exact counts unchanged until the corresponding population or target share is edited. Derive initial target shares as exact count/population ratios, not rounded display values. Reject incompatible or over-allocated counts instead of silently repairing them. |
| Save/export/reopen a percentage-configured draft | Preserve requested targets, the allocation method and tie order alongside the resolved integer counts. Check their consistency when importing. This is configuration provenance, not an added agent role or ontology rule. |

For each type independently, the allocation includes the no-role category:

1. Use exact decimal/rational target shares; do not calculate from rounded labels.
2. Compute each quota as population × target share and take its integer floor.
3. Give each remaining agent to the largest fractional remainder. Resolve ties
   in the fixed ontology-table order: no-role, Doctor, Warrior, Scout, Engineer
   for Humans; no-role, Tyrant, Runner, Spitter, Screamer for Zombies.
4. Show each target percentage, resulting integer count and realized percentage.
   Mark rounded percentage labels with “≈”. The engine still receives integer
   role maps; the no-role count remains the unassigned remainder.

Infection is a separate status: initially infected agents are a subset of the
Human total and can have Human roles. Role percentages do not create another
infected population or change infection selection. If reducing Humans makes
the infected count invalid, report that existing constraint rather than
silently lowering it. Role assignment to individual identities continues to use
the existing seeded initialization rules.

**Rounding requires review.** Ten percent of seven agents is 0.7 agents; exact
arbitrary percentages and integer counts cannot always both be achieved. Target
versus realized percentages must be visible rather than silently claimed equal.
For example, a 10% Doctor target among seven Humans can yield one Doctor—about
14.29% realized—while the counts across all categories still total seven.
The baseline must round-trip unchanged: Human shares 50% no role, 10% Doctor,
15% Warrior, 10% Scout, 15% Engineer; Zombie shares 60% no role, 10% Tyrant,
15% Runner, 10% Spitter, 5% Screamer.

**Why and validation.** A single allocation calculation maintains the dependency
between totals, percentages and integer counts. Test baseline/import roundtrips,
small/zero populations, fractional ties, overflow, role compatibility and GUI/CLI
resolved-count agreement. Also verify imported repeating shares (such as one
of three agents), target provenance roundtrips, repeated edits, seed independence
of count allocation, and retained infected-count validation. “No active role”
is a UI category, not a new ontology role.
Sources: [field update](../gui/src/main.tsx#L102),
[configuration validation](../src/zombie_sim/config.py#L140),
[baseline role counts](../ontology/zombie_game_ontology_v0.1.md#L611),
[single-role/type rules](../ontology/zombie_game_ontology_v0.1.md#L329), and
[formal role compatibility](../ontology/formal_v0.1/shapes.ttl#L1822).
No ontology change is needed for this configuration conversion.

**Implemented and verified on 2026-11-26.** Separate Human and Zombie tables now
show editable target percentages, the automatic no-role remainder, integer
counts and realized percentages. Pending entries stay visible and commit
atomically with population edits. Blank/invalid targets or combined shares over
100% block actions with field/group feedback. Counts shown while edits are
pending are explicitly labeled as the last committed configuration.

The frontend uses exact rational arithmetic and deterministic largest remainders.
The backend independently verifies the saved fractions, method, fixed tie order
and resulting integer counts. Targets are stored under `gui.role_allocation`,
which is excluded from the modeled scenario fingerprint; the engine continues
to receive ordinary integer role maps. Initialization assignment rules are
unchanged. Unchanged imported count maps keep their representation and ordering.

Preset, import and copy operations reset pending edits. **Load saved draft** now
restores the saved browser draft, including exact targets; JSON/TOML exchange
also preserves and verifies them. Partial baseline imports display effective
800/200 populations and baseline shares even when those fields are omitted from
the raw JSON. Explicit-agent scenarios and `semantic` blocks that supply the
population or role settings display their authoritative counts and explain why
conflicting population/role field edits are disabled. Browser-unrepresentable
integer allocations produce a useful precision error rather than rounded counts;
this adds no ontology or backend population limit.

| Verification | Result |
| --- | --- |
| Chromium and Firefox workflows | 13 workflow groups passed per browser, with 31 allocation observations; 26 observations containing saved target metadata were checked by an independent Python `Fraction` oracle. |
| Allocation boundaries | Baseline roundtrip/resizing, all eight roles, seven-agent rounding, fixed ties, exact one-of-three shares, zero populations with retained targets, tiny decimal shares and seed-independent counts passed. |
| Editable input | All eight role controls passed both deletion/retyping methods. Forty blank-field/action combinations and ten invalid target strings plus total overflow were rejected without API work or stale submission. |
| Imports and transitions | Invalid/incompatible/overallocated counts, imprecise browser remainders and contradictory provenance were rejected. Partial baseline, explicit-agent and wrapped population inputs, atomic edits, Advanced JSON replacement, presets, saved drafts and copied runs passed. |
| Backend consistency | Twenty-one invalid configurations were rejected through resolution, JSON import/export and TOML import/export: 105 checks. Valid metadata round-tripped without changing the semantic fingerprint. |
| Real simulation and CLI | Both browsers produced the same configured counts through Validate, actual Preview, export and exactly one HTTP 202 Launch. The 12-agent preview contained five healthy Humans, two infected Humans and five Zombies. Actual CLI JSON/TOML resolution and fingerprints agreed with GUI results. |
| Existing regressions | I04's nine-field numeric workflows and I03's loading/parsing workflows passed on the final functional implementation. All five `SYS_CONFIG_*` cases, all five `GUI_VALIDATION_*` cases and `GUI_CONFIG_CLI_PARITY` passed. |
| Build, review and cleanup | TypeScript, production build/package, independent source/evidence review and visual inspection passed. Both browsers reported zero page errors. Source history digests, command counts, status, generation and frontier stayed unchanged; created workers, disposable services and test workspaces cleaned up. |

Evidence: [Chromium report](../artifacts/issue5-chromium/verification.json),
[Firefox report](../artifacts/issue5-firefox/verification.json),
[visible target/count rounding](../artifacts/issue5-chromium/rounded-target-and-count.png),
[invalid-target feedback](../artifacts/issue5-firefox/invalid-role-target.png),
[numeric regression](../artifacts/issue5-numeric-regression/verification.json),
[configuration regression](../artifacts/issue5-configuration-regression/verification.json),
[backend configuration acceptance](../artifacts/issue5-config-acceptance.json),
[GUI validation acceptance](../artifacts/issue5-validation.json), and
[GUI/CLI acceptance](../artifacts/issue5-config-cli-parity.json).
Reproducible checks: [issue5_check.py](../implementation_checks/issue5_check.py)
and [verify_issue5.cjs](../gui/verify_issue5.cjs).

**Scope and limits.** These are desktop Chromium/Firefox functional checks and
short real simulations, not the entire acceptance catalogue or a long baseline
performance rerun. Existing simulation histories, running user services, supplied
acceptance inputs/assertions, ontology and user task-plan edits were preserved.
Restart the web service and reload the GUI to activate both the Python checks
and rebuilt interface; follow the [restart guide](START_STOP_GUIDE.md#shut-down-and-restart-the-web-service).
At I05 completion, I06 was left unimplemented pending review; its subsequent
approval and results are recorded below. I11/I14/I17 remain separate, and the
existing role-map ordering risk was reported as I18 before further investigation.

## I06 Statistics is blank or stops following time

**Approval.** The user approved the I06 proposal and requested implementation
and verification before I07 is presented. This includes independent Statistics
refresh, exact source cursors, visible initial samples and explicit chart
following/zoom behavior, with browser reproduction of the remaining axis cause.

**Confirmed causes.** Population traces are lines-only. At time zero or before a
second sampled point exists, there is no line segment to display; a read-only
time-0.5 example contains only the time-zero sample. Metrics, Events and Cohorts
also share a single `Promise.all`: one slow/failed endpoint prevents all three
from updating. Full historical reconstruction adds increasing latency.

**Controlled reproduction of the previous build.** A disposable real 20-agent
run confirmed invisible single-point traces at 0 and 0.5 seconds. Healthy
refreshes advanced the axis normally to 3, 5 and 8 seconds; an independent
autorange defect was not reproduced. A controlled Cohorts 503 left the chart
and its source cursor at 5 seconds while the live world reached 8 seconds.
Restoring Cohorts released the metrics and axis together. Native manual zoom
was also discarded by the next refresh because the old chart was purged and
recreated. The fix therefore addresses the measured data dependency and chart
lifecycle, rather than claiming an unobserved Plotly autorange failure.
Evidence: [previous-build browser reproduction](../artifacts/issue6-baseline-verified/browser.json).

**Approved proposal.** Render an initial point and explicit loading/empty/error states.
Separate each view's requests, loading/error state and source cursor; request
only necessary data with bounded refresh and obsolete-request cancellation.
Make live time-axis following explicit, with a clear paused/manual-zoom mode and
reset-to-live action. Include the exact selected frontier alongside regular
interval samples. Preserve revision-consistent samples, including repeated
semantic timestamps, and use the measured bottlenecks to improve query reuse.

**Approved behavior.**

| Situation | Intended behavior |
| --- | --- |
| A new run has only its time-zero sample | Show population markers and the accessible table, with a useful nonzero display range on the time axis. Do not imply that the displayed axis range is elapsed simulation time. |
| The selected committed time falls between regular samples | Include the exact selected frontier as well as regular samples. Label its time and causal revision; preserve distinct revisions at the same timestamp. |
| Live simulation advances | Update plotted arrays and the displayed time extent from the latest successfully read metric cursor. Never label older data as current. |
| A user zooms or pans the time axis | Suspend automatic axis movement. In live mode, **Return to live** restores following of the latest committed extent. In replay, **Reset chart view** restores the selected historical extent; the existing global Live control leaves replay. |
| Statistics is still loading, temporarily behind, or fails | Show its own loading/error/Retry state. Keep any last verified data with its source cursor and an explicit stale/refreshing indication. Distinguish failure from a valid empty result. |
| Events or Cohorts is slow or fails | Continue refreshing Statistics independently. This isolates the dependency; the complete Events/Cohorts workflows remain I07/I08. |
| A response arrives after changing run, replay time or perspective | Discard obsolete data; do not mix samples or event totals from different source cursors. Bound refreshes to avoid overlapping backlogs. |
| A chart is shown, resized or updated repeatedly | Preserve its intended zoom/follow state and click handlers. Verify lifecycle/resize behavior in a real browser before selecting a fix. |

The implementation should separate metric fetching from the other readers,
avoid rebuilding the Plotly chart unnecessarily, and reuse bounded metric work
where measured history costs warrant it. It must preserve the distinction between
sampled populations and exact event totals. Any backend query/cache changes must
retain read-only history access and source-revision consistency. No changes to
the definition of healthy, infected, zombie, dead or remains counts are proposed.

**Why and validation.** A single valid sample becomes visible and an unrelated
view failure cannot block statistics. Test time zero, fractional times, steady
advancement, pause/resume, replay, resize, manual zoom, slow/failed endpoints and
both presets with growing histories. Include repeated-time revisions, termination,
tab switching and reordered responses. Check plotted arrays, axis ranges,
accessible table and source cursor against committed backend metrics, not just
the presence of a canvas. A complete 1,800-second baseline performance rerun is
not a prerequisite for this targeted visualization fix; any measured performance
claims must state the actual history size and test duration.
Sources: [Statistics reader](../gui/src/useStatisticsReader.ts),
[population chart](../gui/src/PopulationChart.tsx),
[metric sampling](../src/zombie_sim/metrics.py), and
[metrics endpoint](../src/zombie_sim/server.py#L200).
No ontology change is required.

**Implemented.** Statistics now has its own bounded reader, explicit source
time/revision, loading/failure/Retry states and stale-data labels. It keeps one
request in flight per context, coalesces moving live cursors, rejects obsolete
responses and clears privileged data on perspective changes. Events and Cohorts
still share their separate auxiliary reader; their full workflows remain I07/I08.
The chart uses persistent Plotly updates, visible markers, an explicit live
extent, preserved manual axes, one set of handlers and resize observation.
Exact sample clicks retain both time and revision; replay reset remains in replay.
Resources, event totals, table and chart use the same verified metric source.

The backend always includes the exact selected endpoint and derives discrete
population/resource samples incrementally from checksum-verified ledger patches.
Its eight-entry cache retains compact measurement state and bounded samples,
not full historical states or completed occurrences. Source identity includes
the file identity and initial checksum; same-time revisions invalidate boundary
samples. A private reader and cooperative cancellation release abandoned HTTP
work without interrupting other readers. The cache assumes the committed ledger
prefix is immutable: it verifies newly read patches, the initial payload and the
cached tail, but does not recheck every old middle payload on every warm request.

**Backend verification.** The independent check matched 201 pointwise samples
against full historical reconstruction across 15 real engine commits, including
cure, lethal combat, conversion and resource consumption/reservation. It also
passed bounds/deadline checks, nonzero history origins, reverse/repeated-time
queries, source replacement/isolation, cache eviction, corruption, cancellation
and eight concurrent readers. The source audit remained unchanged.

On a separate 20-agent, 241-commit, 120-second growth fixture, the previous
sampler made 63 full-state reads; the new cold and warm samplers made zero.
Observed query times were approximately 117 ms, 5.3 ms and 0.5 ms respectively.
The retained compact state serialized to 4,535 bytes both before and after the
history doubled; this is not an RSS or Python heap measurement. A bounded query
returned 16 samples with its coarser 8-second interval disclosed. These are
local fixture measurements, not a general simulation performance guarantee.

An actual HTTP disconnect through the production middleware cancelled the
private reader in about 53 ms in the test; an independent request and subsequent
retry both succeeded. All tracked readers closed, no sampler work remained, and
the source audit was unchanged.
Evidence: [sampler and cache checks](../artifacts/issue6-metrics.json) and
[HTTP cancellation checks](../artifacts/issue6-disconnect/verification.json).

**Browser verification completed.** Chromium 156 and Firefox 153 each passed
12 workflow groups and 24 chart captures. The check compares actual Plotly
arrays, exact sample cursors, accessible table rows, axis ranges, event totals
and resources with independently reconstructed committed history: 304 sample
comparisons in Chromium and 295 in Firefox. Both browsers passed initial and
fractional samples, repeated-time revisions, native zoom and reset, actual
start/pause/resume, replay sample clicks, resize/tab changes, independent failed
Cohorts/delayed Events, metric failure/Retry/valid-empty/malformed responses,
and reordered run/replay/perspective responses. There were no page errors.

The small configuration reached 40 modeled seconds, with 495 commits in the
Chromium workflow and 493 in Firefox; their deliberate wall-clock pause points
differ. Both checked baseline charts at 0 and 0.5 seconds, then advanced the real
1,000-agent baseline to 1 second for the obsolete-run response check, using one
worker and a 3-second configured horizon. The slow-metrics test used two
reads with a maximum of one in flight. Three read-only audit windows per browser
preserved semantic/runtime ledger contents, command counts and frontier/status.
Both runs per browser terminated with worker cleanup complete, and unchanged
terminal cursors generated zero extra metric requests during the 1.3-second
idle check. The disposable services exited and workspaces were removed.

Visual inspection confirmed visible initial markers, legible source/error
labels and the baseline's fractional-time curves. Evidence:
[Chromium](../artifacts/issue6-chromium/verification.json),
[Firefox](../artifacts/issue6-firefox/verification.json),
[initial chart](../artifacts/issue6-chromium/initial-statistics.png),
[retained data after failure](../artifacts/issue6-chromium/statistics-error-retains-data.png),
and [baseline chart](../artifacts/issue6-chromium/baseline-statistics.png).

**Regression verification.** TypeScript checking and production packaging passed.
The existing linked-cursor/watermark, replay-preserves-live, fixed/dynamic-cohort
and perspective-cache-clearing browser acceptance cases passed, as did PNG and
SVG chart export. The browser adapter's Events/Cohorts capture wait now uses
their own auxiliary cursor; supplied acceptance inputs and assertions were not
changed.
Evidence: [build](../artifacts/issue6-frontend-build.log),
[linked cursors](../artifacts/issue6-GUI_LINKED_CURSOR_AND_WATERMARK.json),
[replay](../artifacts/issue6-GUI_REPLAY_PRESERVES_LIVE.json),
[cohorts](../artifacts/issue6-GUI_FIXED_DYNAMIC_COHORTS.json),
[perspective](../artifacts/issue6-GUI_OBSERVATION_CLEARS_PRIVILEGED_CACHES.json),
and [chart exports](../artifacts/issue6-chart-export.json).

**Scope and limits.** Existing user services and simulation histories were not
modified. The ontology, user task-plan edits and supplied acceptance fixtures
were preserved. Verification uses disposable runs and services. The audit
comparisons cover read-only replay/zoom/tab/perspective operations; intentional
advance/start/pause/terminate commands naturally change the disposable fixtures.
This is targeted functional verification, not the full acceptance catalogue or
a complete 1,800-second baseline performance run. Restart the web service and
reload the GUI to activate the Python changes and packaged interface; follow
the [restart guide](START_STOP_GUIDE.md#shut-down-and-restart-the-web-service).

Reproducible checks: [backend sampler](../implementation_checks/issue6_metrics_check.py),
[disconnect lifecycle](../implementation_checks/issue6_disconnect_check.py),
[browser service harness](../implementation_checks/issue6_check.py) and
[browser workflows](../gui/verify_issue6.cjs). The documented earlier sampler is
retained as a small frozen fixture for the measured before/after comparison.

## I07 Cohorts need independent loading and an understandable workflow

**Approval.** The user approved I07 and requested implementation and verification
before I08 is presented. The scope includes independent reading, guided creation,
membership/source labels, undefined empty means, validation and a practical guide.

**Evidence.** Cohort creation/reading exists, and earlier small integration tests
exercised it. That does not prove the current user workflow works on large live
runs. I06 separates Statistics from the other readers; Cohorts still needs its
own refresh/error handling instead of depending on Events. An empty collection
and failed/pending collection are insufficiently distinguished.
The default “Initially infected” example can legitimately select zero agents in
the built-in small preset, which starts with no infected humans.

**Proposal.** Give cohorts independent loading/error/cursor state and an explicit
empty-state explanation. Show a short creation flow: select a run and revision,
choose a predicate, choose fixed membership or dynamic membership, name and create
the cohort, then inspect member count and statistics. Use “All humans” with no
status restriction as the first example rather than a potentially empty infected
cohort. Explain that fixed membership
retains identities after conversion/death and dynamic membership is reevaluated.

**Concrete behavior to review.**

| Situation | Intended behavior |
| --- | --- |
| No cohorts have been created | Explain that the run has no saved cohort definitions and show a short creation flow with an **All humans** example. |
| Configure the first cohort | Select the run and reference cursor, name it, choose fixed or dynamic membership, and choose filters. The example uses Human type with any status; explicitly show whether dead identities are included. Existing saved definitions keep their original meaning. |
| Choose fixed membership | Capture matching IDs at the reference time/revision and retain those IDs after conversion or death. Show both the definition's reference cursor and the cursor of the currently displayed measurements. |
| Choose dynamic membership | Reevaluate the recorded predicate at the displayed cursor. Explain that a Human-filtered member can leave after conversion and that status/dead filters affect membership. |
| Submit a definition | Show useful field errors without losing input. While creation is pending, prevent repeated clicks. Identify the created cohort after success and refresh the list. |
| A valid cohort has no matching members | Show **0 members**, explain the active filters and source cursor, and display undefined means as “—”, with denominator zero. This is a valid result, distinct from a loading failure. |
| Display a populated cohort | Show its name, mode, predicate, reference cursor, measurement cursor, member IDs/count, healthy/infected/zombie/dead breakdown, and mean life/stamina with their denominators. Explain that cohorts may overlap. |
| A read is delayed or fails | Give Cohorts its own loading/error/Retry state. Retain any last verified cards with an explicit stale indication and their original cursor; Events or Statistics failures must not block them. |
| Switch run, replay time or perspective | Cancel/discard obsolete reads and never present one run or cursor's members as another's. Do not expose researcher-only cohort contents in agent perspective. |

The user guide should walk through **All humans** first, then a fixed-versus-
dynamic example involving infection/conversion/death. It should explain why the
small preset's initially infected example can legitimately be empty, how to
clear filters, and how to inspect member identities. Creating a cohort records
an analysis definition; it must not change simulation decisions, random draws
or the semantic event ledger.

**Why and validation.** Users can distinguish “no cohort created” from a broken
request. Verify actual member IDs and counts across creation, evolution, replay,
conversion/death and failure/retry. Keep the separate export-provenance defect
I15 outside this approval. I19's Human-survival eligibility concern also remains
separate; this proposal does not redefine or claim to fix survival measurements.
Verify both presets, empty and overlapping cohorts, delayed/reordered responses,
replay and run changes, and actual member IDs against the selected snapshot.
Sources: [cohort creation and reading](../gui/src/main.tsx),
[cohort API](../src/zombie_sim/application.py), and
[cohort membership and summaries](../src/zombie_sim/visualization.py).
No ontology change is proposed.

**Implemented.** Cohorts now has an independent reader with one request in flight,
bounded refresh, exact run/time/revision validation, obsolete-response rejection,
and its own loading/failure/Retry states. It retains verified cards with their
original source labels while stale. Refresh Cohorts also reloads definitions at
an unchanged cursor. Run/perspective changes discard privileged collections.
The All humans example, explicit dead-identity option, clear-filter control,
preserved invalid drafts, guarded creation and highlighted created card provide
a complete first-use workflow. Cards show reference and measurement cursors,
member IDs/counts, population breakdowns and average denominators; zero-member
means display “—”. The [guide](GUI.md#cohorts-and-causal-records) walks through
creation, fixed/dynamic membership, lifecycle changes, filters and recovery.

The backend captures both reference time and revision, including projected
positions between committed events, and validates new definitions before saving.
It provides an opt-in response envelope so even an empty collection has an exact
source cursor; existing list-response consumers remain supported. Mean life and
stamina use the number of member identities present at the selected cursor and
return null for a zero denominator. Legacy names/default filters/reference times
are enriched on read without rewriting stored definitions. Fixed membership and
the original include-dead rules remain unchanged. I15 export provenance and I19
survival eligibility remain separate; neither calculation was changed here.

**Independent backend verification.** A scripted real 10-agent simulation produced
16 commits over four seconds, including new infection, cure, two conversions,
Human/Zombie deaths and movement. The check compared 748 summaries across 17
definitions with independently evaluated predicates and reconstructed snapshots.
It covered every causal revision, reverse and fractional queries, all filters,
overlapping/empty groups, fixed/dead membership, and an exact one-third-second
region selection between commits. It also verified 23 invalid-definition
rejections, four concurrent readers, cancellation and response-copy isolation.
Both legacy JSON definitions remained byte-for-byte unchanged. Semantic/runtime/
event/control/metadata ledger contents and serialized RNG/policy state were
unchanged by the analysis operations. All private readers closed and the
disposable workspace was removed.
Evidence: [backend checks](../artifacts/issue7-cohorts.json).

**Browser verification.** Chromium 156 and Firefox 153 each passed eight workflow
groups, 20 captures, 94 independently reconstructed cohort summaries and 2,289
member-ID comparisons. These checks cover creation, retained invalid input,
pending duplicate-submit prevention, explicit empty/loading/failure states,
retry, Events/Statistics failure isolation, delayed/coalesced reads, source
mismatch rejection, and obsolete run/replay/perspective responses. Both browsers
checked actual fixed/dynamic membership and means through public engine actions
for infection, cure, conversion and death. Five read-only audit windows per
browser left simulation/runtime history, command counts and frontier/status
unchanged; cohort definitions alone were saved as analysis metadata.

The small configuration reached four modeled seconds, the 1,000-agent baseline
reached half a second, and the separate eight-agent scripted lifecycle history
covered four seconds and 15 revisions. The slow-reader test made two requests
with a maximum of one in flight; terminal idle checks found zero redundant cohort
requests. There were no page errors. Both managed runs per browser terminated
with worker cleanup complete; the completed lifecycle fixture had no worker.
Services exited and temporary workspaces were removed. Visual inspection
confirmed clear reference/measurement labels, created and empty cards, dead-filter
semantics and zero-denominator means.
Evidence: [Chromium](../artifacts/issue7-chromium/verification.json),
[Firefox](../artifacts/issue7-firefox/verification.json),
[first-use view](../artifacts/issue7-chromium/initial-cohorts.png),
[created and empty groups](../artifacts/issue7-chromium/created-cohorts.png), and
[lifecycle groups](../artifacts/issue7-firefox/fixed-dynamic-lifecycle.png).

**HTTP and regression verification.** An actual disconnected HTTP client stopped
obsolete cohort aggregation in about 53 ms in the disposable test. An independent
request, retry and legacy list-response request succeeded. No aggregation remained
active and all private history readers were closed; they close before aggregation,
while the intentional cached metadata reader remains until service shutdown.
The source audit and saved definitions were unchanged. TypeScript/build/package
checks and five existing acceptance cases passed: fixed/dynamic cohorts,
cure/reinfection/death, linked cursors, replay preservation and perspective cache
clearing. The browser driver now waits on Cohorts' own cursor and explicitly sets
type/dead filters to preserve test intent; supplied inputs/assertions were not
changed.
Evidence: [HTTP cancellation](../artifacts/issue7-disconnect/verification.json),
[build](../artifacts/issue7-frontend-build.log),
[fixed/dynamic](../artifacts/issue7-GUI_FIXED_DYNAMIC_COHORTS.json),
[cure/reinfection/death](../artifacts/issue7-GUI_COHORT_CURE_REINFECTION_DEATH.json),
[linked cursors](../artifacts/issue7-GUI_LINKED_CURSOR_AND_WATERMARK.json),
[replay](../artifacts/issue7-GUI_REPLAY_PRESERVES_LIVE.json), and
[perspective](../artifacts/issue7-GUI_OBSERVATION_CLEARS_PRIVILEGED_CACHES.json).

**Scope and limits.** This is targeted desktop-browser and backend verification,
not the whole acceptance catalogue or a long baseline performance run. The
ontology, user task-plan edits, existing simulation histories and running user
services were preserved. Restart the web service and reload the GUI to activate
both the backend and packaged interface, following the
[restart guide](START_STOP_GUIDE.md#shut-down-and-restart-the-web-service).
Reproducible checks: [backend oracle](../implementation_checks/issue7_cohorts_check.py),
[browser harness](../implementation_checks/issue7_check.py),
[browser workflows](../gui/verify_issue7.cjs) and
[disconnect lifecycle](../implementation_checks/issue7_disconnect_check.py).

## I08 Events loads early history instead of recent events

**Approval.** The user approved I08 and requested implementation and verification
before I09 is presented. The approved scope includes latest pages, stable
pagination, identity filtering, bounded occurrence output and independent UI state.

**Cause and evidence.** The timeline calls `history.events(..., limit=5000)`
without the latest-first option. It therefore retrieves the earliest 5,000
records while the UI claims a latest-event window. An in-memory 5,002-event
reproduction returns IDs 1–5000; the latest query returns 3–5002. The response
also carries every historical occurrence, increasing latency as the run grows.

**Proposal.** Query a bounded recent window in a declared stable order, add
pagination for older history, apply relevant participant filters before limiting,
and return only occurrence details referenced by that window. Display accurate
loaded counts, source revision and filter/empty states. Explain clearing selected
agent and text filters when they hide events.

**Concrete behavior to review.**

| Situation | Proposed behavior |
| --- | --- |
| Open Events | Show the latest recorded events through the selected view's causal revision, using a default page of 500 records and a server maximum of 5,000. Show the source time/revision and loaded count. |
| Read the order | Display each page in ascending ledger sequence, with exact simulation time and revision. Distinct events at the same time remain distinct and retain their causal order. |
| Inspect an identity | Apply its participant filter before the page limit, including relevant actor/target and occurrence-linked records. A match near the newest end of a long history must remain discoverable. |
| Search the displayed page | Clearly label text/action/outcome search as filtering the loaded page. Show matching versus loaded counts; do not imply that a page-local search searched the entire run. Provide separate controls to clear the selected identity and clear search text. |
| Browse earlier history | Provide Older/Newer page controls using stable sequence boundaries. Pin pagination to its source revision so new live events cannot shift pages, create duplicates or skip records. |
| Resume recent events | Provide Show latest events. In live mode it follows the latest verified selected frontier; in replay it stays capped at the selected historical revision. Older-page browsing stays stable and clearly indicates that it is not following new events. |
| Inspect an event | Keep its full record and transaction-exact Before transition / After transition actions. Fetch only the occurrence details needed by returned events; retain causal references without embedding all historical occurrences. |
| No matching events | Distinguish a valid empty page, an active identity/search filter hiding records, and an unloaded or failed request. Explain the appropriate next action. |
| A read is slow, fails, or becomes obsolete | Give Events its own bounded reader, loading/error/Retry state and truthful source label. Keep verified results explicitly stale; discard responses for an obsolete run, perspective, selected revision, filter or page. Other views continue independently. |

The storage query already supports latest-window ordering and indexed participant
filtering before its limit. The timeline currently bypasses those capabilities:
it selects the earliest window, then applies identity filtering afterward, while
returning all historical occurrences. I07 has removed Cohorts from its fetch;
I08 will complete Events' own request state and navigation rather than reconnect
the views. Existing event history, event identities, causal revisions and outcome
definitions remain unchanged. The guide will cover latest events, older pages,
identity filters, page-local search and exact event inspection.

**Why and validation.** Selecting the latest matching window removes the early-
history cutoff. Revision-pinned sequence pagination makes page continuity
testable, and limiting occurrence details bounds response content by the selected
records rather than all past actions. Verify more than 5,000 events, matches near
the newest edge, actor/target and occurrence-linked filtering, equal-time ordering,
no duplicate/missing records across pages, live advancement while browsing older
pages, replay caps, before/after jumps, failure/retry and reordered responses.
Compare returned/displayed sequences and cursors against direct ledger queries,
check payload size on a growing history, and confirm read-only operations preserve
the simulation ledger and runtime/RNG state. Run the existing event and linked-
cursor acceptance cases and a real-browser walkthrough.
Sources: [timeline](../src/zombie_sim/application.py),
[event query](../src/zombie_sim/storage.py), [Events view](../gui/src/main.tsx).
No ontology change is proposed.

**Implemented.** The timeline now reads the latest 500 matching records by
default, with a validated maximum of 5,000, and returns them in ascending durable
sequence order. Older/Newer use exclusive sequence boundaries and retain the
original source time/revision. Identity filtering precedes the page limit and
includes indexed participants, explicit actor/target fields and action-linked
participants. Sequence and revision identifiers remain exact strings, including
values beyond JavaScript's safe integer range. Only occurrence details referenced
by the selected page are returned.

Events has its own coalesced reader, source validation, cancellation, loading,
failure and Retry states. Verified older results retain their original source
label while refreshing. Page-local text search and identity filters have separate
clear controls. Show latest events resumes the selected view's source, including
its replay cap. Event inspection retains the original record and exact
transaction Before/After boundaries. Long fractional row times use clearly marked
decimal approximations for readability; the tooltip, accessible label, full
record and replay commands retain exact values. The packaged GUI and the
[Events walkthrough](GUI.md#cohorts-and-causal-records) include these changes.

**Backend verification completed.** The independent
[timeline oracle](../implementation_checks/issue8_timeline_check.py) passed 149
queries and 11,784 event comparisons, including complete Older/Newer traversal,
equal-time ordering, historical caps, actor/target/action-linked participation,
invalid inputs, concurrent readers and sequences above `2^53`. A controlled
history grew from 5,309 to 10,609 events: the pinned response stayed identical,
the newest page remained 500 records, and only its 500 referenced occurrences
were returned. Latest response sizes were 251,391 and 268,742 bytes in these
fixtures; these are observations, not a fixed byte-size guarantee. All 165
private readers closed, and no full-world reconstruction was invoked by the
production timeline. Separate comparisons covered 16 real engine revisions.
Read-only audit windows preserved semantic, runtime/RNG and command history.
Evidence: [backend report](../artifacts/issue8-timeline.json).

The [HTTP disconnect check](../implementation_checks/issue8_disconnect_check.py)
used the actual production middleware and socket disconnect. It verified
cancellation, private-reader closure, an independent concurrent request, a
successful retry, unchanged source history and disposable-service cleanup.
Evidence: [disconnect report](../artifacts/issue8-disconnect/verification.json).

The three existing timeline acceptance cases passed against the final packaged
GUI: atomic conversion and both reciprocal-action timelines. The linked-cursor,
replay-preserves-live and perspective-cache-clearing cases also passed during
I08 verification. Supplied test inputs and assertions were unchanged; the browser
adapter was updated to capture the approved ascending row order.
Evidence: [timeline cases](../artifacts/issue8-timeline-regressions-final.json),
[linked cursor](../artifacts/issue8-linked-cursors.json),
[replay](../artifacts/issue8-replay.json) and
[perspective](../artifacts/issue8-perspective.json).

**Chromium and Firefox verification.** In each browser, the final packaged
interface passed 24 page captures against independent full-ledger queries and
five read-only audit windows. Checks
covered the real 20-agent run beyond the former cutoff, pinned pages during live
advancement, identity and text filters, exact event Before/After transitions,
replay caps, loading/empty/error/Retry behavior, unrelated panel failures,
delayed/obsolete/mismatched responses, perspective clearing and final terminated
history. Delayed reads never exceeded one Events request in flight; an unchanged
terminal cursor generated no redundant requests. Each browser checked 8,266
visible time labels, including 5,956 rounded values, against their exact source
times.

The 20-agent history contained 7,834 events at 200 simulated seconds and 8,149 at
206 seconds. The actual 1,000-agent baseline reached 0.5 seconds with 3,331 events;
both its newest and older pages matched the source ledger. This is a bounded
baseline workflow check, not a long-horizon 1,000-agent performance claim. Test
runs and the disposable service completed cleanup. Evidence:
[Chromium report](../artifacts/issue8-chromium-final/verification.json),
[Firefox report](../artifacts/issue8-firefox-verified/verification.json),
[browser harness](../implementation_checks/issue8_check.py) and
[browser workflows](../gui/verify_issue8.cjs).

Earlier Firefox attempts interrupted by SIGTERM were not counted as passes;
their disposable services/workspaces were explicitly cleaned up. A subsequent
uninterrupted run exposed a timing race in the new verification harness: its
separate state and DOM reads could straddle refreshes. The failure screenshot
already showed the correct error state. The harness now waits for the final
command cursor, failed phase, rendered banner and enabled Retry together in one
browser snapshot. It retains the original data/source/recovery assertions;
production code was unchanged. The final Firefox report records both failure
snapshots and the successful recovery checks. Earlier evidence remains in
`artifacts/issue8-firefox-interrupted`,
`artifacts/issue8-firefox-final-interrupted` and
`artifacts/issue8-firefox-timing-failure`.

**Performance boundary.** Output is bounded by the selected records and their
referenced occurrence details. Complete filtering of legacy occurrence-only
participants can still scan historical records and build transient ownership
metadata. Compressed anchors decode and verify atomically before the requested
fields are retained. This is not a constant-work query guarantee, a persistent
cache or a history migration. These reads do not alter stored history.

**Completed.** TypeScript, production build/package and the checks above passed.
The ontology, supplied acceptance inputs/assertions, task plan, earlier issue
fixes and user histories/services were preserved. To activate the backend and
packaged GUI in an already-running service, follow the
[restart guide](START_STOP_GUIDE.md#shut-down-and-restart-the-web-service) and
reload the browser. I09 was presented separately after I08 completion.

## I09 Comparison does not refresh with advancing runs

**Approval.** The user approved the I09 proposal after I08 completion. Implement
and verify the aligned, refreshing Comparison workflow below, then present I10
for review. No ontology change or unrelated issue fix is authorized.

**Cause and evidence.** Its loading effect depends on selected run IDs, not their
advancing source frontiers. Keeping the same selection therefore leaves curves
stale. Selecting fewer than two runs is a normal incomplete comparison, which
also needs clear guidance rather than an unexplained blank region.

**Proposal.** Explain selecting two to four runs and the shared time domain.
Track each selected run's committed frontier, refresh bounded aligned data when
it changes, show source cursors/loading/errors, and cancel obsolete selections.
Include completed/paused selections and preserve alignment through the earliest
selected frontier as specified by the comparison contract.

**Concrete behavior to review.**

| Situation | Proposed behavior |
| --- | --- |
| Open Comparison with fewer than two runs chosen | Explain that a comparison needs two to four runs, show available runs and a short example for choosing a second run. Do not show an unexplained empty plot. |
| Choose runs | Identify each by scenario, seed and run ID. Keep valid selections while their frontiers update and during ordinary tab changes. Explain when a chosen run is still initializing or has no readable history. |
| Align the curves | Use absolute simulation seconds over the histories' common available interval, ending at the earliest selected committed frontier. Respect a branch history's nonzero start; explain when the common start exceeds the end. Equal endpoints give a valid single-time comparison. Evaluate each run at common explicit sample times, including both endpoints, rather than inventing interpolated population observations. Start with one-second spacing and increase it when needed to keep at most 2,000 samples per run, including endpoints; disclose the actual spacing and count. Show raw population counts with their definitions and units. |
| Runs advance | Refresh bounded data when the relevant selected frontiers change, even if the checkboxes stay unchanged. Refresh at most twice per wall-clock second, with only one comparison batch in flight. Coalesce superseded inputs; one slow response must not build an unbounded request queue. |
| Publish a refreshed comparison | Require every selected run's response to match the requested exact common sample times and its captured frontier revision cap. Retain each run's actual source revision at every sample, including the shared endpoint; this may precede its captured frontier revision. Display the common interval and per-run source cursors together. Never label an older complete comparison as current. |
| One read fails or is delayed | Show which run is pending or failed and provide Retry. While refreshing the same selected run set, retain the last verified complete comparison with its original sources and a stale label. Distinguish missing data from a valid zero population. Other workspace views continue independently. |
| Change selections, run or perspective | Cancel/discard obsolete responses and clear or mask curves from a previous selection context, so the checkboxes cannot silently describe a different displayed dataset. Clear researcher-only comparison data in agent perspective. |
| Zoom, resize or switch population measure | Keep series identities/colors clear, preserve deliberate zoom during ordinary data updates, and provide Reset comparison view to restore the aligned extent. Label the selected measure and show an accessible table, including single-time samples. |
| Export the comparison | Export the verified dataset currently displayed, retaining run IDs, seeds, sample times and causal revisions. Do not substitute newer data or a different selection during export. |

The guide will walk through selecting two runs with different seeds, reading the
shared endpoint and individual source revisions, observing a live refresh,
comparing paused/completed histories, recovering from a failed read and exporting
the displayed result. Run controls and recorded histories are not changed by
comparison. Cohort export issue I15 remains outside this proposal.

The implementation will extend the bounded history reader/API to accept explicit
common sample times: the current per-run metrics grids start at each history's
own origin and cannot alone guarantee cross-run alignment. Exact times and
revision caps will remain canonical strings. Selection state will be retained
above the conditionally mounted Comparison panel so ordinary tab changes do not
erase it.

**Why and validation.** Tracking the actual comparison inputs removes the stale
checkbox-only dependency. Publishing a complete aligned dataset with explicit
source cursors prevents mixtures of times or runs. Verify two advancing runs,
mixed live/paused/completed histories, different horizons/population sizes,
same-time revisions, nonzero history origins and no-overlap cases. Test selection
changes, slow/failed and reordered responses, perspective clearing, resize/zoom,
single-time samples and CSV consistency. Compare plotted arrays and table rows
with independently reconstructed source histories; confirm comparison and export
leave semantic/runtime/RNG state unchanged. Use real-browser checks, not merely
the presence of a chart.
Source: [Comparison](../gui/src/main.tsx).
No ontology change is proposed.

**Implemented.** Comparison now tracks the selected runs' exact committed times
and revisions. Its independent reader starts at most two batches per second,
coalesces advancing inputs and keeps one batch active per selection context.
Changing the main run, selected set or perspective cancels and masks obsolete
results. Ordinary tab changes retain the selected runs and chart view. Fewer
than two selections, initializing histories, no common interval, loading and
read failures have explicit explanations.

The new read-only `POST /api/comparison` captures two to four distinct source
caps, finds the common available interval and samples each history at the same
exact times. It includes both endpoints and increases one-second spacing by
powers of two as needed to stay within 2,000 observations per run. A run's
revision at the common endpoint can precede its captured frontier revision;
both are displayed. The first available commit determines the history origin.
Ordinary branches retain the parent prefix, so their available history can
begin before their branch point. A failed source produces a run-specific error
and no partial comparison dataset.

The chart shows single observations, preserves deliberate zoom through normal
updates and tab changes, and offers Reset comparison view. Each plotted sample
has an exact-time/revision hover value and a matching accessible table row.
CSV export uses the displayed verified dataset and captured metadata, including
run IDs, scenarios, seeds, source caps, actual sample revisions, common interval,
spacing, measurement version, definition and units. During a failed refresh it
exports the retained complete dataset with its original sources. The
[Comparison walkthrough](GUI.md#compare-independent-runs) explains these controls
and the separation between comparison history and the main replay cursor.

**Backend verification completed.** The independent
[comparison oracle](../implementation_checks/issue9_comparison_check.py) passed
49 ready comparisons and a no-overlap case, with 2,827 population samples checked
against complete historical states. This includes 15 real-engine causal
revisions in forward/reverse order, equal-time caps, different counts and
history origins, two to four sources, exact fractional endpoints, a single-time
interval, eight concurrent queries and invalid/unavailable inputs. A deliberately
corrupted second source verified that successful first-source samples cannot
escape as a partial result. A controlled 20,000-second interval produced 1,251
observations per run at 16-second spacing, including the exact fractional start
and endpoint. The compact cache stayed within eight entries and its sample bound.
No full-world reconstruction was called by the production comparison; private
readers closed and semantic/runtime/RNG/control/definition audits were unchanged.
Evidence: [comparison report](../artifacts/issue9-comparison.json).

The [real HTTP disconnect check](../implementation_checks/issue9_disconnect_check.py)
passed through the production POST route, middleware and session cookie. It
verified cancellation of a two-source batch, closure of all private readers,
an unaffected concurrent batch, retry, unchanged history and complete disposable
service/workspace cleanup. The existing independent Statistics sampler checks
also passed; its API and sampling behavior remain unchanged. Evidence:
[disconnect report](../artifacts/issue9-disconnect/verification.json) and
[Statistics regression](../artifacts/issue9-statistics-regression.json).

**Browser verification completed.** Chromium and Firefox each passed 24 captures,
checking 240 population observations against independently reconstructed source
histories, actual Plotly arrays, exact source rows and the full accessible table.
The workflows used four managed runs with 20, 10, 8 and 6 agents, distinct seeds
and horizons, plus a real branch retaining its parent prefix. A separately
labeled archived fixture with three static agents and a nonzero starting time
exercised equal endpoints, no overlap and shared grids across different origins.
These fixtures do not constitute a long-horizon or 1,000-agent comparison
performance benchmark.

Both browsers verified unchanged-selection refresh while two real simulations
ran, same-time revision updates, mixed paused/completed histories, the four-run
selection limit, native zoom and reset, resize, tab persistence and stable
series colors. They also checked per-run failure/Retry, malformed-source
rejection, delayed coalesced reads, obsolete selection/main-run/perspective
responses and researcher-data clearing. The delayed case had one batch in flight
and two requests in each browser. Recorded server arrival gaps for comparison
requests were at least 0.500 seconds in these runs; unchanged terminal sources
generated no redundant requests during the idle check.

Three CSV exports per browser matched the displayed complete dataset: ordinary
verified data, retained data during a failed refresh, and comparison during main
viewer replay. Each included exact source caps/sample revisions and measurement
version/definition/units. Five read-only audit windows per browser preserved
semantic history, runtime/RNG and command records. All temporary workers cleaned
up, services exited and workspaces were removed. Visual inspection confirmed
visible initial markers, readable source/error labels and plotted populations.
Evidence: [Chromium](../artifacts/issue9-chromium/verification.json),
[Firefox](../artifacts/issue9-firefox/verification.json),
[browser harness](../implementation_checks/issue9_check.py) and
[browser workflows](../gui/verify_issue9.cjs).

Initial browser attempts identified two assumptions in the new verification
harness: raw histories omit derived `status`, and ordinary branches retain
earlier parent commits. The oracle now derives population categories directly
from life/type/infection facts; the real branch verifies its actual retained
prefix, while a separately labeled fixture covers nonzero origins. These were
new-harness corrections, not changes to supplied acceptance inputs or simulator
behavior. Failed-attempt artifacts remain in the `issue9-*-oracle-fixture-failure`
and `issue9-*-branch-fixture-failure` directories under `artifacts`.

**Regression verification.** TypeScript and production build/package passed.
The four existing linked-cursor/watermark, replay-preserves-live,
perspective-cache-clearing and stale-seek/exact-string acceptance cases passed
against the final packaged interface. Evidence:
[build](../artifacts/issue9-frontend-build.log),
[linked cursors](../artifacts/issue9-GUI_LINKED_CURSOR_AND_WATERMARK.json),
[replay](../artifacts/issue9-GUI_REPLAY_PRESERVES_LIVE.json),
[perspective](../artifacts/issue9-GUI_OBSERVATION_CLEARS_PRIVILEGED_CACHES.json) and
[exact strings](../artifacts/issue9-GUI_STALE_SEEK_AND_EXACT_STRINGS.json).

**Performance boundary.** Output and transient derived caches are bounded. Cold
or newly aligned comparisons can still scan historical patches. Separate
comparison and Statistics build locks avoid making one view wait on the other's
cache lock. These are presentation/read changes; they do not alter simulation
decisions, random draws, stored history or ontology definitions.

**Completed.** The approved I09 behavior and checks above passed. Earlier issue
fixes, the user-edited task plan, ontology, supplied acceptance tests and existing
user histories/services were preserved. Restart an already-running web service
and reload its GUI to activate the backend and packaged frontend, following the
[restart guide](START_STOP_GUIDE.md#shut-down-and-restart-the-web-service).
I10 is presented below for separate approval.

## I10 Comprehensive friendly user guide

**Approval.** After completing I09, the user approved this proposal. The guide
and disposable-workspace walkthrough verification are complete within the
limits below. At I10 approval, I11 and I12 remained separate, unapproved fixes;
I11 has since been completed as recorded next.

**Gap.** Existing startup/shutdown and GUI documents explain many controls, but
do not provide a sufficiently guided, verified path through the reported trouble
spots. Documentation cannot substitute for fixing broken behavior.

**Proposal.** After the relevant fixes are approved and verified, provide a quick
first-run walkthrough with screenshots, explain all statuses and save/terminate
semantics, model and percentage selectors, Statistics and live/replay time,
cohort examples, event filtering, comparison setup, launcher shutdown phases,
troubleshooting and file locations. Keep one primary guide and link detailed
reference pages instead of competing instructions.

**Concrete deliverable to review.** Create `docs/USER_GUIDE.md` as the friendly
starting point, linked from the project README and existing guides. Keep
`docs/GUI.md` and `docs/START_STOP_GUIDE.md` as detailed references and reconcile
their overlapping instructions. Organize the main guide around tasks:

| Reader's task | Proposed guide content |
| --- | --- |
| Get a first result | A short Small 20 agents walkthrough: open the launcher/GUI, create and validate an experiment, launch, wait for a readable world, advance, pause, inspect and stop. Give the expected screen/result after each step and a corresponding screenshot. |
| Choose how to operate | Explain launcher, browser GUI and direct CLI entry points, working directory, service URL/workspace, required dependencies, and how to recognize an already-running service. Put optional installation/reference detail behind links. |
| Configure an experiment | Explain seeds, horizons, populations, role percentages/counts, numeric editing, placement choices, model identifiers/defaults, validation/preview, import/export and replicate seeds. Clearly distinguish scenario settings from viewer preferences. |
| Inspect a run | Guided World, Statistics, Cohorts, Events and Comparison examples, including exact time versus revision, filters, empty results, stale sources, fixed versus dynamic membership, common comparison intervals, tables and exports. |
| Control execution and history | A decision table for pause, continue, stepping, checkpoint, Stop & save and termination without another checkpoint. Explain retained audit history, saved versus terminated runs, replay versus execution, restarting the service and resuming eligible runs. |
| Work with the baseline | A separate 1,000-agent path explaining the already-approved approximate placement choice, strict geometry checks, initialization progress, worker settings and the limits of observed performance evidence. |
| Recover from trouble | Symptom → meaning → next action entries for initialization, missing/failed curves, hidden filter matches, no common comparison interval, disconnected service, stale GUI assets and shutdown waits. Show useful log/output locations and what to retain when reporting a failure. |

The guide will describe current verified behavior. The pending model-selector
change (I11) and launcher shutdown fix (I12) will be explicitly identified where
they affect instructions; approving I10 does not authorize implementing those
fixes or claiming they already work. Document the available verified route and
update the affected instructions when those later fixes are separately approved.
Screenshots will come from disposable demonstration runs, with no user run
deleted or repurposed.

**Why and validation.** Follow the guide from a clean workspace using actual GUI
labels and verify every documented outcome. Include a small deterministic example
for cohorts/events/comparison and a separate realistic baseline workflow. Any
remaining limitations must be described where they affect the user's action.
Check copied commands, relative links, file paths and screenshot captions; walk
through both GUI and CLI start/stop paths using temporary workspaces and verify
worker/service cleanup and retained records. Treat any newly discovered defect
as a separate report requiring review, rather than silently expanding the guide
task into an unapproved code fix.
No ontology change is proposed; behavior descriptions wait for their approvals.

**Delivered.** [The friendly user guide](USER_GUIDE.md) is now the primary
starting point, linked from [README](../README.md), [GUI](GUI.md) and
[startup/shutdown](START_STOP_GUIDE.md) references. It covers the Small first run,
all five analysis views, configuration and role editing, model defaults,
execution versus replay, save/termination, launcher and direct CLI, service
restart, baseline placement, files and troubleshooting. Nine screenshots show
actual disposable runs. The guide explicitly distinguishes the GUI's 20-agent
preset from the launcher's 24-agent `configs/small.toml` scenario.

At I10 delivery, pending I11/I12 behavior was identified at the point of use.
The model instructions and configuration screenshots have since been updated
for completed I11. Existing I13/I14/
I15/I17/I19 limitations are also described where relevant. The new I20 source
concern and I21 interruption failure were reported immediately and left for
separate review; I21's observed failure is documented in the interruption
instructions. Documentation does not claim these issues fixed.

**Walkthrough verification.**

| Check | Result and evidence |
| --- | --- |
| Actual browser first-run and analysis workflow | PASS in Chromium 156.0.8078.79. Through GUI controls: load/validate/preview/launch Small 20 with seed 123, horizon 60, one worker and explicit `HumanDefaultModel`; Continue/Pause at 1×, step a transition, inspect World/Statistics; create seed 321 with 2 infected/3-second incubation, replay 0, create fixed/dynamic Human cohorts, inspect conversion at 3 seconds, compare the two runs and export displayed CSV; Stop & save both. [Browser report](../artifacts/issue10-gui/browser.json), [driver](../gui/verify_issue10.cjs). |
| Meaningful analysis examples | Fixed Human group retained 16 identities, dynamic Human group had 14 after two conversions. Comparison had 7 shared observations per run over 0–6 seconds. Selected conversion retained exact revision 25→26 and sequence 126. The second run deliberately differs in infection settings; the guide does not present this as a seed-only causal comparison. |
| Foreground service and retained records | PASS: production `python -m zombie_sim.cli gui` in a temporary workspace; both runs retained committed histories (55/65 commits and 216/252 events), worker cleanup completed, no leases remained, browser closed, service received SIGINT and exited 0 with application shutdown complete, endpoint closed, scratch removed. Individual worker PIDs were not captured in this GUI check; launcher check below captured them. [Report](../artifacts/issue10-gui/verification.json), [service log](../artifacts/issue10-gui/service.log), [harness](../implementation_checks/issue10_gui_check.py). |
| Actual launcher wrapper | PASS: `./simulate gui` start/reuse, list, Small 24 launch, pause/continue, Stop & save, service exit/restart using the same workspace, saved-run resume, pause/terminate, retained history and unchanged existing checkpoint across the termination boundary. Both observed coordinator PIDs exited; cleanup completion and closed endpoint were checked. Service cleanup used the verified owned PID after run cleanup, not the pending I12 `shutdown` workflow. [Report](../artifacts/issue10-cli/verification.json), [check](../implementation_checks/issue10_cli_check.py). |
| Direct CLI commands | PASS: validate/placement preview, run Small 24 to 30 seconds, inspect, replay 15 without changing committed history, resume to 120/completed with the same run identity; checkpoint and manifest present. Separate SIGINT attempt failed as recorded in I21 and is not counted as passing. [Same terminal report](../artifacts/issue10-cli/verification.json). |
| Baseline GUI preview | PASS: baseline validation and placement of 1,000 identities in the approved relocation mode; independent world/barrier/shelter checks for 1,000 positions and 499,500 pair distances. Preview took 7.565 seconds on this machine. No baseline worker was launched by the browser check. [Browser baseline evidence](../artifacts/issue10-gui/browser.json). |
| Baseline direct CLI | PASS: documented configuration with one worker advanced to exact 1/2 second, revision 270, horizon still 1,800. All 1,000 identities retained; initial 800 Humans/200 Zombies included 20 infected Humans. Independent 499,500 pair checks and geometry checks passed; checkpoint, manifest and history files written, process exited and scratch removed. [Report](../artifacts/issue10-baseline-cli/verification.json), [check](../implementation_checks/issue10_baseline_cli_check.py). |
| Documentation | Local file/anchor links checked; all nine PNGs visually reviewed against captions and current labels; task-plan bytes preserved. README/GUI/start-stop instructions reconciled, including current model/shutdown limits. [Documentation check](../artifacts/issue10-docs.json). |

**Verification limits.** This is a documentation release against the existing
I01–I09 implementation. It does not rerun the full acceptance suite or establish
new performance guarantees. Baseline execution ended at 0.5 seconds; neither
that check nor the preview establishes full 1,800-second throughput. Service exit
was checked after browser closure and worker cleanup, without pending heavy
reader/export work; this does not resolve I12. Fresh dependency installation,
all optional export backends and every configuration combination were not
retested; those reference sections retain their existing validation scope.

Earlier guide-check attempts are retained separately: the actual headless
interrupt failure, two launcher-check assertions corrected to wait for cleanup
and compare checkpoints across only the termination boundary, an Events search
fixture correction, and screenshot drafts corrected for explicit model choice,
1× pacing and fully acknowledged saved status. Those attempts are not substituted
for final passing evidence and required no production changes.

**Completed.** I10 added documentation, screenshots and independent walkthrough
checks. Production simulation code, ontology, supplied acceptance tests,
user-edited task plan and existing user histories/services were preserved.
I11 below is ready for separate review and approval.

## I11 Make the decision-model default explicit

**Approval.** The user approved this proposal after the completed I10 guide.
Implementation and verification are complete within the limits below. I12 and
the separate I20 compatibility concern remain unapproved.

**Cause and evidence.** Metadata exposes a free-text `human_model` field, but
presets omit the key. The GUI displays an empty value while initialization uses
`HumanDefaultModel`, currently version `1.1.0`. Omitting the field validates;
explicitly setting it to an empty string fails. Valid default aliases include
`HumanDefaultModel`, `defaultHuman` and `defaultHuman/v1`.

**Proposal.** Show a selected **Default human utility policy** with the actual
resolved identity, and a corresponding zombie selection. Obtain available choices
from registered model metadata; retain an advanced registered-plugin/artifact
path. Explain that a model chooses actions from local observations and private
memory; it is not an agent role or an arbitrary user-written name.

**Concrete behavior to approve.**

1. Replace the ambiguous text field with **Human decision model** and **Zombie
   decision model** selectors. Show **Default human utility policy —
   HumanDefaultModel · 1.1.0** and **Default zombie utility policy —
   ZombieDefaultModel · 1.1.0** for untouched presets, using the actual installed
   versions rather than hard-coded display versions.
2. Add declarative registry metadata for friendly labels, canonical IDs,
   aliases, supported agent types and installed versions. The existing registry
   lists names (including aliases); model manifests already expose identity,
   version and applicability. Populate the selectors from this metadata, show
   aliases as one policy choice, and do not load trained weights merely to
   display configuration choices. Include the registered `randomLegal/v1`
   alternative for both types, with its meaning explained.
3. Preserve supported imported aliases, parameters, explicit versions and
   omitted default keys unless the user deliberately changes that setting.
   A visible derived default must not silently rewrite a configuration or alter
   its fingerprint. Existing frozen run assignments and history remain intact.
   For explicit per-agent assignments, explain that they take precedence and
   avoid presenting top-level controls as if they replace those assignments.
4. Keep an **Advanced registered model or artifact** path for custom plugins
   and `ppo:<artifact-directory>`. Explain that registration/dependencies and
   artifact files must exist where the service runs; typing a new name does not
   create a model. Preserve unresolved imported values visibly with actionable
   validation feedback. Do not silently substitute a default for an invalid,
   blank or unavailable selection.
5. Add concise help explaining local observations/private memory and the
   distinction from roles. Update the guide and model reference once the actual
   selector is implemented and verified.

**Why this addresses the cause.** The form makes the runtime fallback visible
and uses the same registered identities as validation and initialization. A
default choice no longer depends on the user guessing text. Preserving omitted
and explicitly supplied values avoids changing unrelated experimental inputs.
Correctness is conditional on the checks below, not guaranteed by a label change.

**Acceptance conditions.** Verify untouched Small and baseline presets, actual
Human/Zombie assignments and resolved versions; default aliases and JSON/TOML
round trips; switching to a supported alternative; blank/unknown IDs, missing
artifacts and unavailable dependencies; plugin metadata; explicit per-agent
drafts; copy-as-new versus existing frozen history; keyboard interaction and
load/retry states in Chromium and Firefox. Use actual validation/preview/launch
paths and confirm old histories remain unchanged. Loading the selector must
not import a heavyweight model artifact.

**Scope boundary.** I20 below is a newly reported, unverified concern about
server-side model/type compatibility enforcement. Selecting compatible choices
from declared metadata is included here. Investigating or correcting every
configuration/initialization/intervention compatibility path remains a separate
review; I11 does not claim that concern already resolved. No changes to policy
algorithms, ontology action contracts or default decision behavior are proposed.

Sources: [field metadata](../src/zombie_sim/server.py),
[configuration validation and fallback](../src/zombie_sim/config.py),
[policy registry/manifests](../src/zombie_sim/policies.py), [model reference](MODELS.md).

**Implemented.** The editor now shows separate Human/Zombie selectors, inherited
defaults, requested IDs, registered identities and installed versions. Available
choices come from the new declarative
[model catalog](../src/zombie_sim/model_catalog.py). Listed choices are filtered
by declared applicability; legacy plugins without metadata remain available
through the advanced ID/artifact entry. Unknown and empty IDs remain visible.
Missing dependencies now receive a field-specific `MODEL_UNAVAILABLE` error with
installation guidance. The metadata request never instantiates a policy or loads
learned weights.

Opening/validating a default leaves omitted keys omitted. Imported aliases and
complete drafts survive JSON/TOML round trips without incidental fingerprint
changes. Explicit per-agent assignments and semantic overrides show their
effective settings with read-only explanations. New model edits read current
Advanced JSON, preserving unrelated edits; the separate I14 behavior of other
ordinary controls is unchanged. Saved-draft loading resets the advanced-input
display to the loaded value. These controls are implemented in
[ModelSelection](../gui/src/ModelSelection.tsx) and
[modelSelection helpers](../gui/src/modelSelection.ts).

**Checkpoint compatibility decision.** Saved model artifacts pin the entire
implementation source file. To preserve existing checkpoints, `policies.py`
was left byte-identical to the pre-I11 snapshot. Optional friendly registration
uses `zombie_sim.model_catalog.register_model(...)`, which delegates to the
unchanged legacy registry. The original `policies.register_model` API still
works. Catalog metadata is tied to the actual factory identity and is filtered
when a legacy registration replaces it. No artifact-pin rule was weakened and
no default-policy algorithm/version changed.

**Verification results.**

| Check | Result and evidence |
| --- | --- |
| Catalog and assignments | PASS: all eight built-in aliases match actual manifests; untouched Small and baseline initialization produced 20 and 1,000 correct model assignments. Metadata reads called no factories or heavy dependency imports. Plugin metadata is detached; replacement invalidates stale descriptions, conflicting declarations stay advanced-only, and five invalid replacements leave the registry unchanged. [Backend report](../artifacts/issue11-models.json), [check](../implementation_checks/issue11_models_check.py). |
| Configuration and execution | PASS: 12 alias JSON/TOML round trips, two explicit-agent round trips preserving requested versions/parameters, blank/unknown/missing-artifact errors for both types, and missing-PyTorch feedback. An actual 20-agent alternative-model run advanced to 2 seconds. Same backend report. |
| Earlier behavior and checkpoints | PASS: policy source byte identity, 30 unchanged function/class ASTs, 16 identical seeded decisions, and a checkpoint created using pre-I11 policy classes restored and advanced from 1 to 2 seconds. Five historical files remained unchanged. Same backend report; scratch removed. |
| Chromium and Firefox | PASS against final `index-1KRRB60M.js`, in Chromium 156.0.8078.79 and Firefox 153.0. Each exercised 12 workflow groups: catalog failures/retry, visible Small/baseline defaults and omitted keys, six real previews including 1,000 agents, aliases and fingerprints, per-agent versions/parameters, semantic overrides, saved-draft reset, advanced invalid values, keyboard alternatives, numeric/role edits, two actual default/randomLegal launches, and copy-as-new with unchanged source configuration/history. [Chromium report](../artifacts/issue11-chromium/verification.json), [Firefox report](../artifacts/issue11-firefox/verification.json), [driver](../gui/verify_issue11.cjs), [harness](../implementation_checks/issue11_check.py). |
| Cleanup | Both browser fixtures verified worker cleanup, no remaining leases, service application shutdown, closed endpoint and removed scratch workspace. Their intentionally signalled service returned SIGTERM status −15 without forced cleanup. This is disposable test cleanup, not an I12 busy-service shutdown guarantee. |
| Existing model acceptance cases | Nine PASS: default action witness bank; four fallback cases; private-memory isolation, memory restart, unserializable-memory restart limits and artifact-checksum rejection. [Regression index](../artifacts/issue11-model-regressions.json). |
| Existing GUI/CLI parity | PASS: baseline configuration import/edit/export, initial/final semantic state and history parity, including unchanged scenario after view-only controls. [Report](../artifacts/issue11-GUI_CONFIG_CLI_PARITY.json). |
| Existing edit/intervention acceptance case | ERROR in the browser adapter before the intervention step: a broad run-ID locator matched both the sidebar button and Comparison checkbox. Reported immediately as I22; adapter and supplied acceptance inputs were left unchanged. This case is not counted as passed. [Failure report](../artifacts/issue11-GUI_EDIT_NEW_AND_MODEL_INTERVENTION.json). Independent I11 copy-as-new/frozen-history checks passed in both browsers. |
| Build and documentation | TypeScript check and production packaging PASS; final assets `index-1KRRB60M.js` / `index-j9hAS5wo.css`. [Build log](../artifacts/issue11-frontend-build.log). User/GUI/model references updated; two new configuration screenshots visually reviewed, local links checked, and old screenshots/evidence retained. |

The initial metadata prototype and exploratory browser attempts are archived
separately; final reports above use the separate catalog and final packaged
viewer. The guide's browser script was adapted to the selectors without
overwriting I10 evidence. This is targeted verification, not a full-suite pass,
full-baseline performance test, arbitrary-plugin certification or a resolution
of I20 applicability enforcement. The separate I22 adapter limitation is
recorded separately rather than being silently fixed within this issue.

**Completed.** I11's approved selector behavior and dedicated checks passed.
Existing policy source/checkpoint pins, ontology, supplied acceptance tests,
user-edited task plan and user histories/services were preserved. Restart an
existing web service and reload the GUI to activate the backend and packaged
viewer, following [the restart guide](START_STOP_GUIDE.md#shut-down-and-restart-the-web-service).
I12 is presented next for separate approval.

## I12 Launcher hangs during service shutdown

**Approval.** The user approved I12 and all remaining listed issues together
after I11. Implementation and verification are in progress; the recorded
proposals below define the scope, with existing audit history retained.

**Actual evidence.** The current service log reaches “Shutting down,” “Waiting
for connections to close,” then “Waiting for background tasks to complete.”
All five simulation records are terminated and no worker leases remain. This
places the observed wait in web-service shutdown, not an unapplied run command.

**Causes.** Uvicorn is started without a graceful shutdown deadline; its installed
default is no deadline. It waits for outstanding HTTP/WebSocket request tasks
before application lifespan cleanup. Large scene/history queries dispatched with
`asyncio.to_thread` can keep computing after a browser disconnects. Cancelling
the awaiting coroutine does not stop its underlying thread. Export cleanup in
lifespan consequently cannot, by itself, resolve an earlier request-task wait.
The launcher prints one line and then polls silently for up to 900 seconds.

I02, I06, I07, I08 and I09 added independent readers and cooperative cancellation
for selected-history, Statistics, Cohorts, Events and Comparison requests. These
changes do not provide a service-wide drain registry, cancel every live-stream
projection or export, or establish bounded shutdown during initialization or
checkpoint writing. I12 remains separate from those completed fixes.

**Proposal.** Extend draining to close subscriptions, stop admitting expensive
reader work and cancel/bound queued and active reconstruction/metric/export work.
Make heavy jobs cooperatively cancellable or isolate them in supervised processes
that can be stopped without touching the authoritative writer. Set an explicit
graceful shutdown deadline after that work has a genuine termination path. Report
phases and periodic progress: run commands, worker cleanup, viewers/readers,
exports, then service exit. Preserve exact-instance process checks and history;
do not replace the wait with a broad process kill.

**Concrete behavior to review after I11.**

1. Give the service an explicit shutdown coordinator and status record for its
   exact instance. Report phases for command reconciliation, saving/terminating
   runs, worker cleanup, closing viewers, draining readers/exports and final
   service exit. Include elapsed time, remaining work, run/command references
   and actionable errors. The launcher prints a progress change immediately and
   a short heartbeat at least every five seconds while waiting.
2. Start draining before requesting final Uvicorn exit. Reject new creation,
   resume and expensive analysis/export work while keeping status, command
   reconciliation and required stop/terminate operations available. Track actual
   tasks and their resources, rather than assuming a disconnected browser means
   the work has ended. Close subscriptions server-side so users do not have to
   find every connected tab to make progress.
3. Extend cancellation to the remaining reader/export paths and join their
   cleanup. Retain safe boundaries around atomic reads. If work cannot cooperate
   within a configured grace period, isolate that read-only job in a supervised
   process that can be stopped without affecting the authoritative writer.
   A cancelled coroutine alone is insufficient. Set the service's graceful
   shutdown deadline only once remaining tasks have an actual cleanup path.
4. Keep **save** and **terminate without another checkpoint** distinct. Report
   each run's durable outcome and worker cleanup separately. Account for pending
   creation/initialization, branch and control requests so shutdown cannot miss
   a worker that appears after the initial run list. Never claim success while
   a requested save, command, worker or owned service remains unresolved.
5. Use an explicit overall wait budget, retaining the existing configurable
   launcher timeout as the user-facing limit. Exhaustion produces a clear
   incomplete result with the outstanding phase and retry information; it does
   not authorize killing a writer in the middle of a checkpoint. Preserve the
   draining state until safely completed, and make retry reconcile the same
   instance and durable commands. A longer timeout must not be the only remedy.
6. Retain workspace locks, exact service identity/PID checks and unrelated-port
   protection. Only report complete shutdown after owned worker cleanup and
   service exit are verified. Update the launcher messages, GUI/service-close
   guidance and user guide around the verified behavior.

**Why this addresses the causes.** Draining starts while the application can
still cancel and observe its work, before the server waits for requests to end.
Readers have a real cleanup path; the launcher reports that progress instead of
silently polling a PID. Separate run and service outcomes prevent an early
acknowledgement from being mistaken for full shutdown. Checkpoints and other
writer work retain their integrity boundaries. The result will be judged by
the following tests rather than an unconditional promise of a shutdown time.

**Acceptance conditions.** Test menu and direct-command workflows, both shutdown
modes, repeated shutdown/retry, start/list/open/pause/continue/save/terminate and
retained requests. Include open and closed browser subscriptions, a slow live
projection, long retained-history reads across all four analysis panels, active
and queued exports, initialization, checkpoint work, concurrent creation and
control requests, occupied ports and unrelated services. Cover Small and the
1,000-agent baseline plus a long-history fixture; record each test's actual
size/duration rather than claiming a full baseline run from a short check.
Assert phase/heartbeat visibility, bounded read-only cancellation, released
readers/files/worker leases, coordinator and pool exit, closed service endpoint,
unchanged retained history, resumable saves and no new checkpoint requested by
termination. Inject an uncooperative task to verify truthful timeout/incomplete
status and safe retry. Compare both launcher-owned and foreground-service
shutdown without expanding into the separate headless CLI interruption issue
I21. Existing user histories/services must not be used as destructive fixtures.

Earlier 11 launcher checks used tiny four-agent scripted scenes. I10 verified
real lifecycle controls and an idle foreground service's exit, but deliberately
did not claim this busy-service shutdown path had passed.
Sources: [service startup and current drain gate](../scripts/launcher_service.py),
[launcher shutdown wait](../scripts/simulation_launcher.py),
[readers and live stream](../src/zombie_sim/server.py),
[export lifecycle](../src/zombie_sim/export_jobs.py),
[current log](../runs/launcher/.launcher/service.log).
No ontology change is proposed.

## I13 Additional issue CLI continuation bypasses termination

**Reported before further work.** GUI/API reject execution of a terminated run,
but direct CLI resume restores the journal and checks only the engine's completed
state. Restoration can classify a noncompleted history as paused without enforcing
the durable managed termination flag. The earlier start/stop guide already
documents this limitation.

**Proposed direction.** Enforce terminal control state consistently at continuation
entry points before restoration/advancement, under the existing run lease. Keep
read-only replay available. Historical branching policy is a separate explicit
choice and must not be silently changed.

**Why and validation.** Interface choice cannot bypass an intentional terminal
state. Test GUI/API/CLI continuation of terminated, completed, stopped and interrupted
runs on both backends; rejected continuation must leave history/checkpoints unchanged.
Sources: [CLI resume](../src/zombie_sim/cli.py#L224),
[managed terminal check](../src/zombie_sim/application.py#L394).
No implementation or ontology change is approved.

## I14 Additional issue Advanced JSON edits can be lost

**Reported immediately; further investigation paused.** Editing the JSON textarea
changes only `advanced`. Editing an ordinary field clones the stale `draft` and
rewrites `advanced`, potentially discarding JSON edits without warning.

**Proposed direction.** Use one committed configuration state shared by both
editors, with an explicit invalid/unapplied JSON state. Never overwrite unapplied
JSON silently; reconcile valid edits or ask the user to apply/discard an invalid
draft before switching editing modes.

**Why and validation.** The two editors can no longer independently overwrite
each other's changes. After approval, reproduce mixed editing, invalid JSON,
import/preset changes, validation and roundtrip preservation.
Source: [Configuration state/update](../gui/src/main.tsx#L99).
No implementation or ontology change is approved.

## I15 Additional issue Cohort export can misstate provenance

**Reported immediately; further investigation paused.** The JSON cohort export
uses cached cohort results but labels them with the current viewer's time/revision.
The cached results can lag behind that viewer. This is a research-data provenance
problem, not merely a visual lag.

**Proposed direction.** Bind cohort results and export metadata to the same
immutable source run/time/revision, independently of subsequent viewer movement.
If a requested cursor has not loaded, wait for that exact result or explicitly
export the displayed older cursor; never relabel it as newer.

**Why and validation.** Export metadata will describe the data actually exported.
After approval, test export during delayed cohort refresh, live advancement,
replay/selection changes and errors; compare memberships/statistics with the
declared historical cursor.
Source: [cohort export control](../gui/src/main.tsx#L231).
No implementation or ontology change is approved.

## I16 Additional issue unindexed histories load during service registration

**Reported before further work.** During I02 review, source inspection showed
that `RunManager.__init__` discovers manifests absent from `manager.sqlite` and
calls `History.state_at()` to register each run. Indexed workspaces skip this
path, but first registration of a large unindexed history can delay service
startup before the browser's run chooser is available. This is separate from
the frontend automatically selecting an already-indexed run.

**Proposed investigation and direction, not yet approved.** Reproduce first
registration in a disposable workspace, establish which manifest/ledger metadata
can safely identify the committed frontier without scene reconstruction, and
propose lightweight registration or an explicit import workflow with progress.
Preserve identity, provenance and recovery validation. Test indexed startup and
first import independently. No import behavior has been changed and no ontology
change is proposed. Further investigation awaits individual review.

Source: [history discovery during manager startup](../src/zombie_sim/application.py).

## I17 Additional issue partial drafts use different seed sources at launch

**Reported before further work.** During I03 source review, Launch was found to
derive its default replicate seed from the raw `config.seed`, even after backend
validation has supplied defaults in `validated.resolved`. A partial JSON object
such as `{}` can therefore pass validation but fail the frontend's nonnegative
integer seed check. This behavior predates I03. The new JSON parser permits valid
objects and does not redefine backend defaults to hide this separate mismatch.

**Proposed investigation and direction, not yet approved.** Reproduce partial
drafts with omitted seeds, explicit seeds and optional replicate seeds, then
align default launch seed selection with the resolved configuration while
preserving explicit replicate overrides and durable creation identity. Verify
Validate/Preview/Launch agreement and GUI/CLI defaults. No seed behavior or
ontology rule has been changed; further investigation awaits individual review.

Source: [Configuration launch seed selection](../gui/src/main.tsx).

## I18 Additional issue role-map order and seeded assignment

**Reported before further work.** During I05 source review, the initializer was
found to build its role list by iterating `population.human_roles` and
`population.zombie_roles` before applying its seeded shuffle. Different map
ordering can therefore affect per-identity assignments for the same seed and
counts. This is a source-confirmed mechanism, not a completed cross-format
reproduction. I05 preserves existing assignment rules and unchanged map ordering;
it does not resolve this separate reproducibility concern.

**Proposed investigation and direction, not yet approved.** Reproduce equivalent
count maps in different insertion orders, through JSON/TOML and GUI/CLI paths,
then propose canonical initialization ordering with explicit compatibility and
provenance treatment for existing runs. Do not rewrite past histories or claim
old seeded outcomes remain identical if the initial ordering changes. Further
investigation and implementation await individual review.

Source: [initial role-list construction](../src/zombie_sim/config.py).

## I19 Additional concern initially Zombie members and Human survival

**Reported before further work.** During I06 review, the Cohorts implementation
was observed to count members currently Zombie or DEAD as Human-survival events.
For a cohort containing initially Zombie identities, that may classify them as
having ended a Human lifetime even though they did not enter the run as Humans.
Ontology §16.2 distinguishes Human survival from persistent-identity survival.
This is a source concern, not a completed behavioral reproduction. It does not
affect I06 population-curve definitions; further investigation is paused.

**Proposed investigation and direction, not yet approved.** Reproduce Human-only,
Zombie-only and mixed fixed/dynamic cohorts, establish the eligible Human-survival
denominator and entry times, and propose an explicit measurement definition and
correction before changing research results. Preserve recorded histories and
keep identity survival separate. I07's forthcoming usability proposal does not
implicitly approve this change.

Source: [cohort measurements](../src/zombie_sim/application.py),
[measurement definitions](../ontology/zombie_game_ontology_v0.1.md#L691).

## I20 Additional concern model type compatibility validation

**Reported before further work.** During the I10 model-reference audit,
configuration validation was observed to check whether a model ID can be
created, while policy manifests separately declare `applicable_types`. No
behavioral reproduction has established whether other layers reject an
incompatible Human/Zombie assignment or what its effect would be. This is a
source concern, not a verified incorrect simulation outcome. The concern was
reported to the user; further investigation and fixes are paused.

**Proposed investigation, not yet approved.** Trace and exercise default,
explicit-agent, imported and intervention assignments with compatible and
incompatible types. If enforcement is missing, propose validation that uses
declared applicability consistently and reports errors without changing old
history. Review that concrete result before altering runtime behavior. The
I11 selector proposal independently filters its visible choices by declared
metadata and does not claim to fix all assignment paths.

Sources: [configuration](../src/zombie_sim/config.py),
[policy manifests](../src/zombie_sim/policies.py).

## I21 Additional issue headless interrupt checkpoint failure

**Reported before further work.** An actual direct CLI `run` was sent one SIGINT
during advancement in a disposable I10 guide check. It exited with
`zombie-sim: Runtime snapshots require a committed boundary; pending state
writes exist` instead of successfully completing its checkpoint path. The
failed attempt is retained in
[the report](../artifacts/issue10-cli-interrupt-failure/verification.json) and
[the command log](../artifacts/issue10-cli-interrupt-failure/08-headless-interrupt.log).
The test process/workspace were cleaned up; existing user histories were not
involved. The issue was reported to the user immediately. No deeper cause
investigation or production fix has been made.

**What is established and what is not.** The error establishes that checkpoint
serialization encountered pending writes after this interruption. It does not
yet establish exactly where the interrupt landed, the safe recovery boundary,
or the behavior of every interruption path. The final passing I10 lifecycle
check excludes this failure and does not count it as fixed. The guide now
describes the failure and recommends a planned `--until` or managed stop.

**Proposed investigation, not yet approved.** Reproduce controlled interrupts
at known engine phases, determine which committed world/runtime state can be
saved or recovered, then propose boundary-safe interruption and truthful exit
status/manifest behavior. Verify `run`, `resume`, initialization, checkpoint
writing and worker cleanup without weakening atomicity or rewriting existing
history. Present the concrete fix before implementation.

## I22 Additional issue ambiguous browser-adapter run selector

**Reported before further work.** During I11's additional regression checks,
`GUI_EDIT_NEW_AND_MODEL_INTERVENTION` stopped when the adapter tried to select
the original run. Its selector `[data-run-id="…"]` matched two DOM elements:
the sidebar run-card button and an existing Comparison checkbox. Playwright
raised a strict-mode locator error before the intervention step. This is a
confirmed adapter ambiguity, not evidence that the application's intervention
failed. The error was reported immediately; further investigation and fixes
are paused. [Failure report](../artifacts/issue11-GUI_EDIT_NEW_AND_MODEL_INTERVENTION.json),
[log](../artifacts/issue11-GUI_EDIT_NEW_AND_MODEL_INTERVENTION.log).

**Proposed fix, not yet approved.** Scope the adapter's run-selection operation
to the intended sidebar run-card button using its semantic role/container.
Preserve the supplied test actions, inputs and assertions. Check all equivalent
adapter run-selection paths for the same ambiguity, then rerun the affected
edit/intervention case and relevant run-switching acceptance checks. This would
remove the ambiguity without hiding a match arbitrarily or changing simulation
behavior. [Adapter source](../gui/browser_driver.cjs).

## Approval record and next action

**I01 approved and completed.** Existing audit history is retained, terminated
history is separated from saved/resumable runs, and termination progress and
background reader work have been corrected and verified as documented above.

**I02 approved and completed.** The chooser, loading/cancellation/retry states
and immediate creation handoff passed the documented checks.

**I03 approved and completed.** Configuration readiness, retry and parsing passed
the documented checks.

**I04 approved and completed.** All nine numeric controls passed the documented
Chromium/Firefox editing, validation and payload checks.

**I05 approved and completed.** Exact role targets, consistent integer counts,
saved/imported metadata and real GUI/CLI workflows passed the documented checks.

**I06 approved and completed.** Previous-build reproduction, exact-source
sampling, chart lifecycle, Chromium/Firefox workflows, HTTP cancellation and
the six relevant acceptance cases passed as documented above.

**I07 approved and completed.** The independent historical oracles, both browser
workflows, HTTP cancellation and five acceptance regressions passed as documented.

**I08 approved and completed.** Independent ledger oracles, both final browser
workflows, HTTP cancellation and six relevant acceptance cases passed as
documented above.

**I09 approved and completed.** Exact-time history oracles, final Chromium/Firefox
chart/table/export workflows, HTTP cancellation, Statistics regression and four
existing acceptance cases passed.

**I10 approved and completed.** The comprehensive guide, nine screenshots,
GUI/launcher/direct-CLI walkthroughs, short baseline and documentation checks
are complete with the limits stated above.

**I11 approved and completed.** Catalog/model/default/checkpoint verification,
both final browser workflows and ten existing acceptance cases passed. The
additional edit/intervention case was blocked by the separately reported I22
adapter ambiguity and is not counted as passing. **I12 is presented and awaiting
review and approval.** The I20 concern, I21 failure and I22 adapter issue remain
queued; their further investigation and fixes are not approved.

A discard operation still requires a
separate retention/lifecycle proposal before any data deletion or ontology/plan
changes.

All other entries remain queued. Approval of I01–I11 does not approve the remaining
issues. After each review, record the accepted behavior, implement only that
approved scope, validate it against the stated conditions, report the result and
present the next issue. Newly discovered issues must be reported before further
investigation or changes on that line of work.

**Batch approval update.** The latest user instruction approves I12–I22 together.
Their implementation, reproductions and verification may proceed without
additional per-issue approval pauses. Prior pending-approval statements are
historical; ontology/problem-formulation changes remain a separate boundary.

## I23 Conversion must use the selected Zombie default

**Reported before investigation during the approved batch.** Conversion called
`decision_model_assignment("ZombieDefaultModel")` directly. This ignored the
scenario's `zombie_model`, despite ontology §5 requiring the scenario default
Zombie model with fresh private memory. The correction uses that resolved default
and retains the biological built-in fallback for old configurations without the
setting. It does not rewrite previous assignments or events. This is an existing
ontology correction covered by the user's blanket approval, not an ontology edit.

**Verification.** The real conversion/intervention checks pass on memory and
SQLite backends, including custom Zombie assignment and fresh memory. Evidence:
[focused core checks](../artifacts/issues13-18-20-21-23/verification.json).

## I24 Missing explicit-agent assignments and scenario defaults

**Reported before investigation during the approved batch; now reproduced and
fixed.** Explicit-agent and state-import paths used biological built-ins when
an assignment was absent, even when a scenario selected another default. Both
paths now fill only missing living-agent assignments from resolved scenario
defaults. Explicit assignments and dead imported agents' empty assignments remain
intact. Ontology §15.6 already permits experiment model assignments; no ontology
change was required. Four path/backend checks and checkpoint-preservation checks
pass in the [focused core report](../artifacts/issues13-18-20-21-23/verification.json).
The five supplied configuration acceptance cases also pass after this correction:
[report](../artifacts/remaining-i24-config-regression.json).

## Verification of the approved remaining-issues batch

This section supersedes the historical pending-approval statements above.

**I16 complete.** Startup registration reads the ledger's exact committed
time/revision and durable control metadata without reconstructing state or
runtime. Identity, resolved configuration and parent provenance remain recorded.
Durable termination overrides a stale manifest. Full integrity validation is
deferred to ordinary replay/restore; registration is not an integrity certificate.
The disposable 20,001-commit, 1,000-identity fixture registered with no scene/runtime
reads; indexed startup opened no histories. A corrupted ledger still failed on
opening, and all source manifest/history bytes were unchanged. Read-only manager
workers also reject mutation entrypoints. Evidence:
[discovery checks](../artifacts/issue16-discovery.json).

**I19 complete.** Human-survival risk sets include displayed members
who entered the source run as living Humans. Initially Zombie members are excluded;
identities already dead at entry are excluded from both risk sets. Identity
survival includes both living entry types. Eligible members without an event are
right-censored at the cursor; missing identities and unavailable entry evidence
are reported separately. Dynamic cohorts describe the currently matching
population, not a fixed survival study.

The final ontology review corrected an intermediate convention: §16.3 makes a
branch a separate run with its own starting snapshot, so the child's survival
entry is its branch boundary, not the parent's original entry. A cursor in an
inherited prefix instead uses that historical source run's entry, including
nested branches. `zombie-sim/cohort-survival-v3` records the explicit entry run
ID/time/revision alongside denominators, events, censoring and exclusions. No
ontology or recorded simulation data changes. The earlier v2 evidence is retained
as a superseded implementation check, not the final measurement contract.

Final independent real lifecycle oracles verified 124 cursors and 856 cohort
comparisons: Human-only, Zombie-only and mixed fixed/dynamic groups; conversion,
death, cure, fractional replay and backward seeks; branches before/after conversion;
nested branches and inherited prefixes; and dead-at-entry imports on memory/SQLite.
The initial Zombie-only group has zero Human intervals/events while an in-run
Zombie death counts for identity survival. A child entering after that death
excludes the already-dead identity. Unknown-entry/missing-member counts and
cancellation also pass. All inspected histories and manager rows remain unchanged.
The previous 748 cohort-summary comparisons pass again with v3. Evidence:
[final survival checks](../artifacts/issue19-survival.json),
[cohort regression](../artifacts/remaining-cohorts-regression.json).

**Core regression.** All 489 supplied core acceptance cases passed with the
integrated batch changes. This is a core-tier result, not a claim that all 539
catalog cases were run: [report](../artifacts/remaining-core-acceptance.json),
[log](../artifacts/remaining-core-acceptance.log).

**I13, I18, I20, I21 and I23–I24 complete.** The
[focused core report](../artifacts/issues13-18-20-21-23/verification.json) records
39 checks. CLI resume checks both ledger and manager termination records under
the existing worker lease before restoration; rejected terminated/completed
histories remain unchanged and replay/branching stays available. New role
initialization uses `canonical_v2` ordering, recorded in configuration/provenance;
old frozen configurations retain `legacy_insertion_v1`, and exact checkpoint
restoration preserves stored state. An actual pre-fix checkpoint continued with
equivalent state, events, decisions and draws, without changing the source artifact.

Model compatibility is checked before creation/import/intervention and rechecked
when scheduled changes take effect. Conversion uses the selected scenario Zombie
model with fresh memory. CLI run/resume now defer SIGINT until committed boundaries
and protect initialization, saving and cleanup. Fourteen real signal cases cover
both backends, dirty state, initialization, restore, checkpoint writing and
process-group interruption during worker startup. A real checkpoint I/O failure
reports a failed manifest, closes resources, and recovers from committed history
without claiming the failed save succeeded. `policies.py` remains unchanged.

**I14, I15, I17 and I22 complete.** The combined
[Chromium](../artifacts/remaining-gui-chromium/verification.json) and
[Firefox](../artifacts/remaining-gui-firefox/verification.json) checks cover valid
JSON plus numeric/role/model edits, invalid/non-object draft protection, explicit
discard, import/export roundtrips, actual `{}` default-seed launch, explicit
seeds and replicate overrides. Cohort exports use their immutable result cursor;
14 exports per browser were compared with independently replayed membership,
population and means across stale replay, errors/retries, live advancement and
run changes. Firefox also checked the displayed I19 survival counts against the
export. Source lifecycle histories were unchanged and services/workers cleaned up.

The browser adapter now identifies a sidebar run button rather than any element
with `data-run-id`, so Comparison checkboxes cannot make selection ambiguous.
Supplied acceptance cases and assertions were preserved:
[edit/intervention](../artifacts/remaining-GUI_EDIT_NEW_AND_MODEL_INTERVENTION.json),
[stale control](../artifacts/remaining-GUI_STALE_CONTROL_REJECTED.json),
[configuration parity](../artifacts/remaining-GUI_CONFIG_CLI_PARITY.json).

**Full browser-tier follow-through.** All 38 supplied browser case IDs now have
passing evidence in the [consolidated final record](../artifacts/remaining-browser-final.json).
The [initial complete run](../artifacts/remaining-browser-acceptance.json) passed
35 and exposed three failures. The model-validation adapter incorrectly tried to
select an arbitrary ID as a dropdown option; it now enters that exact text through
the actual Advanced field, and the [unchanged case passed](../artifacts/remaining-GUI_VALIDATION_HUMAN_MODEL.json).
Both keyboard cases found an actual I06 table-contract regression: the extra
Revision column changed the required measurement headers. The product now keeps
exact revision visibly beneath each Time value, with the time/revision replay link
and accessible label intact. The original five headers are restored and
[both unchanged keyboard cases pass](../artifacts/remaining-keyboard-acceptance.json).
The adapter does not filter out mismatched DOM headers or substitute expected data.

**Launcher regression.** All eleven workflows in the
[launcher verification](../artifacts/remaining-launcher/verification.json) pass:
service startup/reuse, foreign-workspace/foreign-listener refusal, start and pause,
creation retry, stop/resume, termination and duplicate retries, drain admission,
save shutdown, restart and terminate shutdown, and unchanged already-stopped runs.
The disposable service and worker leases were cleaned up. The independent harness
now checks the new `SERVICE_DRAINING` contract, compares stable service identity
fields, and distinguishes legitimate coordinator shutdown commands from rejected
external requests. Earlier harness attempts and their cleanup outcomes are retained.

**I12 complete.** Shutdown now starts an explicit drain before Uvicorn exits.
It closes viewers; cancels and joins bounded, reusable read-only analysis/export
workers; fences external mutations; reconciles accepted commands and unfinished
creation/branch requests; saves or terminates active simulations; verifies worker
leases and cleanup; and only then permits service exit. Command-status receipts
read committed cursor metadata instead of reconstructing a scene. Completed exports,
passive interrupted histories and existing audit prefixes remain intact.

The launcher reports phase changes, elapsed time and outstanding work, with
heartbeats within five seconds. One timeout budget covers the entire request.
Incomplete shutdown retains the service's status endpoint and durable command IDs
for a same-mode retry; simulation writers are never force-killed. Only exact owned
read-only children can be terminated to cancel otherwise uncooperative read work.
Stop/terminate requests remain admissible during early reader drain, then an atomic
fence closes all external mutation admission before command reconciliation and
final cleanup. Status/receipt reads and shutdown retry remain available.

Evidence:

- [Main lifecycle checks](../artifacts/issue12/report.json): real Small 24-agent
  work through time 12, suspended active/queued readers and export preparation,
  save/reopen/terminate, unchanged existing checkpoints on termination, writer-safe
  timeout/retry with four-second progress, 1,000-agent initialization followed by
  termination, and foreground SIGINT through normal service exit.
- [Concurrency checks](../artifacts/issue12-concurrency/report.json): accepted
  creation/branch requests across timeout, an actual held checkpoint, late and
  slow-body terminal admission, four active/queued exports, natural completion
  during stop, durable terminated receipt before manager acknowledgement, structured
  preview validation through the read process, and inactive-history preservation.
- [Metadata/publication checks](../artifacts/issue12-metadata.json): creation
  revision zero and branch receipt pins after the child advances, with `state_at`
  forbidden; completed export retention during its publication/cleanup window.
- [Chromium with open tabs](../artifacts/remaining-shutdown-chromium-open/verification.json)
  and [Firefox with closed tabs](../artifacts/remaining-shutdown-firefox-closed/verification.json):
  all five panels across two live runs; terminate/save respectively; readers,
  exports, sockets, pending commands and worker leases clear; normal service exit.
- [Actual launcher menu checks](../artifacts/issue12-menu/report.json): the reported
  `./simulate` path **10 → 2 → 0** terminates without changing its checkpoint;
  **10 → 1 → 0** saves and stops. Both show progress and close the exact service
  with no worker leases. Menu list/request inspection and leaving the menu preserve
  the service and history; the direct `requests` command also passes.

The baseline check covers initialization at time zero, not a full-horizon baseline
benchmark. Long-history coverage uses two checksum-valid retention fixtures with
20,001 no-op revisions each, not 20,001 scientific transitions. The checks use
disposable services; no existing user service or experiment was stopped or rewritten.

**Final integrated follow-ups.** All four supplied command-recovery cases pass
after the metadata-only receipt change:
[consolidated evidence](../artifacts/remaining-command-recovery-completed.json).
The first recheck passed creation, branch and intervention but exposed an I01/I02
GUI race during Stop recovery: effect cleanup aborted an old view request, while
reusing the already-current terminal view left `viewPending` set. The reuse path
now clears that flag. The unchanged Stop recovery case passes, and deterministic
held-response checks in both browsers prove pending clears before the late response
is released. Original failure evidence is retained.

The final v3 survival cards/exports and that terminal-view fix pass together in
[Chromium](../artifacts/remaining-survival-terminal-chromium/verification.json) and
[Firefox](../artifacts/remaining-survival-terminal-firefox/verification.json).
An actual child created after conversion/death shows its own entry, excludes the
already-dead identity and reports no pre-entry survival events; prefix replay
names the parent entry. Both ledgers remain unchanged and all test services close.

Statistics' corrected five-column table also passes 24 independently checked
captures per engine, exact time/revision/count and accessible-label checks,
single-request/coalescing behavior and terminal-read quiescence:
[Chromium](../artifacts/remaining-issue6-chromium/verification.json),
[Firefox](../artifacts/remaining-issue6-firefox/verification.json).

**Batch complete.** I12–I24 and the related integration regressions above are
implemented and verified. No ontology or problem-formulation change was required.
The user-edited plan, supplied acceptance inputs/assertions and pinned default
policy source remain unchanged. Updated guides describe the final behavior;
[file/link/package checks](../artifacts/remaining-review.json) verify retained
inputs, documentation destinations and the packaged GUI build. Existing user
services are not hot-reloaded; a newly started service loads these fixes.

## I25 Analysis clicks look like a stopped or reset simulation

**Current status: approved, implemented and verified.**
The [updated task plan](../prompts/zombie_game_plans.md#L33) reports a run apparently
stopping and its time returning to zero after exploring Statistics, Cohorts and
Events. Its [review instruction](../prompts/zombie_game_plans.md#L41) requires approval
of this issue's proposal before implementation. The user subsequently approved
the proposal explicitly: “I approve the I25 proposal. Implement and verify the
fixes.” The evidence below retains the original diagnosis and pre-fix results.

### What the evidence shows

The recorded run continued executing while the GUI displayed an old state.
That distinction is too easy to miss in the current interface.

For the actual launcher run `55d1d7a2146946d59e6334342074534e`, read-only inspection
found just **create, start and terminate** commands. There is no recorded Pause,
Stop or reset command and no worker failure. The final termination receipt and
ledger agree on **157 simulation seconds, revision 32175**.

The existing service log shows analysis at approximately **73.49 seconds,
revision 14435**, followed by an explicit historical request for **time 0,
revision 1**. Later Statistics/Cohorts/Events reads remain at that historical
cursor; termination is recorded separately afterward. The log identifies the
requested cursor but does not record which exact control the user clicked.
Evidence: [workspace audit](../artifacts/issue25-review/workspace-evidence.json),
[request before the change](../runs/launcher/.launcher/service.log#L6506),
[time-zero request](../runs/launcher/.launcher/service.log#L6509).

The same visible symptom was reproduced on the unchanged packaged GUI in
[Chromium](../artifacts/issue25-review/chromium/verification.json) and
[Firefox](../artifacts/issue25-review/firefox/verification.json), using separate
disposable runs with real default decision models:

| Action | Pre-fix result | Execution result |
| --- | --- | --- |
| Open Statistics, Cohorts or Events | Changes the visible tab | Continues running |
| Expand cohort member IDs/definition | Opens analysis details | Continues running |
| Click **Inspect chart time** without editing its initial `0` | Switches the viewer to recorded time 0, revision 1 | Continues running |
| Click the first Statistics sample | Inspects that sample at time 0, revision 1 | Continues running |
| Click the first recorded event | Inspects that event at time 0, revision 1 | Continues running |
| Click event **Before/After transition** | Moves the historical inspection cursor | Continues running |
| Click **Return to live** | Resumes following the current recorded frontier | Execution never needed restarting |

The browser reproductions emitted **zero execution commands**. The manager command
journal was identical before and after the analysis clicks. While the display
stayed at zero, the test runs advanced through 7, 8 and 9–10 seconds. Both test
services exited normally with no worker leases left. A screenshot shows the
large zero-time viewer clock and the separate, smaller running clock in the sidebar:

![Current GUI after selecting an initial event: viewer at zero, run still running](../artifacts/issue25-review/chromium/first-event.png)

### Pre-fix causes

1. A sample or event selection invokes the shared `replay()` callback. It switches
   the browser from live follow to recorded replay and loads the selected historical
   time/revision. It does not send Pause, Stop, Terminate or reset to the worker.
   The linked panels then correctly stay at that historical cursor.
2. The largest clock shows **the displayed state's time**. Execution status and its
   advancing time are shown elsewhere, with less emphasis. The current replay badge
   and help text exist, but do not explain the transition prominently enough.
3. The Statistics time-entry control initializes to literal `0` and stays there
   until edited. Clicking **Inspect chart time** therefore selects zero even after
   the run has advanced, without requiring an intentional zero-time entry.

The retained browser reports above capture these pre-fix behaviors. The affected
implementation is now updated in [the main viewer](../gui/src/main.tsx),
[execution/view readouts](../gui/src/RunViewStatus.tsx),
[Statistics editor](../gui/src/PopulationChart.tsx),
[sample navigation](../gui/src/StatisticsPanel.tsx) and
[event navigation](../gui/src/EventsPanel.tsx).

### Approved fix

**Make execution and inspection unambiguous, while preserving non-mutating replay.**

1. Place two clearly labelled readouts beside the main controls, visible from every
   analysis tab: **Simulation — Running · 157 s · revision 32175** and
   **Viewing recorded history — 0 s · revision 1**. Use authoritative run summaries
   for the first and the selected immutable view for the second. Preserve exact
   times/revisions even where the compact clock rounds its display.
2. When a sample/event/seek opens history, show a persistent, status-aware message:
   **“You are viewing recorded history. The simulation is still running.”** Include
   a prominent **Return to live** action. If execution is actually paused, stopped,
   completed, terminated or failed, describe that real state instead. A failed or
   stale status request must show **last confirmed status**, not claim execution is
   currently running.
3. Label history actions explicitly, such as **Inspect recorded time** and
   **Inspect this recorded event**. Keep the approved linked-view behavior: selecting
   an event/sample still updates the displayed historical state, counts and details
   together. Ordinary tab navigation and cohort detail expansion stay in the current
   viewing mode.
4. Initialize the untouched Statistics time field from the current selected cursor,
   rather than silently targeting zero. Preserve intentional user edits as live time
   advances; handle switching runs/resetting the editor deliberately. Explicit `0`
   remains a valid historical target. Empty/invalid values receive clear feedback.
5. Keep run controls and replay playback distinct. **Pause run** changes execution;
   replay controls only change what is viewed. Update the guide with this distinction
   and the concrete analysis-click workflow.

Example after the fix: while the run reaches 80 seconds, clicking an event from
time zero shows **Simulation: Running at 80 s** beside **Viewing history: 0 s**,
with the explanation and Return to live action remaining visible. No restart or
implicit pause is introduced.

### Why this addresses the issue, and how it will be verified

The proposal addresses both demonstrated causes: a history selection that resembles
a stopped clock, and the untouched time field's zero target. It preserves the
recorded history and actual worker progression. Passing the checks below is the
completion criterion; it is not a claim that every possible GUI failure is ruled out.

- Repeat the reproduced actions in Chromium and Firefox, including keyboard access
  and narrow layouts. Verify both clocks, labels, explanation and Return to live.
- Assert no execution commands from tab changes, cohort details, samples, events,
  Before/After, or replay playback. Check the durable ledger continues advancing
  during historical inspection and never rewinds.
- Check intentional zero-time selection, untouched/current-time initialization,
  edited/empty/invalid drafts, switching runs, and delayed/stale responses.
- While history remains selected, exercise an explicit pause/continue/stop/terminate,
  natural completion and run-status request failure. Verify truthful execution
  status independently of the unchanged historical cursor and its populations.
- Re-run relevant linked-cursor, replay-preservation, event-causality, observer
  independence and keyboard acceptance cases. Preserve supplied test inputs and
  assertions. Verify cleanup of every disposable run/service.

**Ontology and scope.** No ontology or problem-formulation change is needed. The
[approved plan §13.3](../prompts/task_2_implementation_plan.md#L503) already requires
seeking and replay playback to affect only the viewer, with an explicit command
required to pause execution. G05/G07/G08/G13 require linked views, replay separation,
truthful control state and observer independence. All current Markdown/formal
ontology specifications were reviewed; their semantics remain unchanged.

**Review boundary.** The user workspace was inspected read-only. Only disposable
test runs were created/terminated. A [source audit](../artifacts/issue25-review/review-verification.json)
confirms 7,820 existing production/specification/test files are unchanged. The
reproduction scripts are [Python](../implementation_checks/issue25_review_check.py)
and [browser](../implementation_checks/issue25_review_browser.cjs).
That review boundary describes the pre-fix investigation. The implementation
below follows the user's subsequent explicit approval.

### Implementation after approval

- Added adjacent **Simulation** and **Viewing** readouts above every workspace
  tab. Both display exact time/revision strings. Execution reads run summaries;
  the viewer reads the loaded immutable state or recorded agent observation.
  Historical populations and details remain tied to that selected view.
- Added a persistent history explanation and prominent **Return to live**.
  Its wording follows actual execution and cleanup states. Pause, Continue,
  Stop and Terminate remain explicit execution actions; replay remains read-only.
- Qualified stale execution information as **Last confirmed**, including the
  header/sidebar. A failed status request qualifies immediately; a request five
  seconds old qualifies even if it has not returned. Age is measured from request
  start, including on response arrival. An independent timer updates idle replay
  displays, while each render samples the actual clock.
- Preserved newer confirmed generations/revisions against delayed command
  acknowledgements and summaries. At an equal revision, newer request provenance
  also protects completion and cleanup status. A late Continue receipt cannot
  replace an already observed completion with Running.
- Made the untouched Statistics editor follow the selected cursor and submit its
  exact revision. Intentional edits survive live updates; run switches and
  **Use selected view time** reset the draft. Explicit zero, fractions and Enter
  submission work. Empty, malformed, negative and zero-denominator drafts show
  accessible feedback without seeking.
- Made recorded-history navigation explicit in Statistics, Events and the
  replay controls. Renamed the chart-only axis reset **Follow latest chart
  samples**, keeping it distinct from the main viewer's **Return to live**.
  The footer identifies its captured frontier as the frontier when the view was
  read, rather than implying it is current execution.
- Updated the [user workflow](USER_GUIDE.md#pause-save-terminate-or-replay) and
  [GUI guide](GUI.md#live-inspection). Rebuilt the packaged browser assets.

The independent post-fix checks are
[Python](../implementation_checks/issue25_fix_check.py) and
[browser](../implementation_checks/issue25_fix_browser.cjs). Unlike the retained
pre-fix reproductions, these assert the corrected behavior. Their first delayed
response check exposed a subsecond freshness flicker when a response render
reused the previous timer tick; the final implementation samples time on every
render and retains that failing evidence before rerunning both engines.

### Final verification

The [consolidated report](../artifacts/issue25-fix/verification.json) records
**PASS** on the final packaged build, `index-CyeA3pXk.js`:

| Check | Result |
| --- | --- |
| TypeScript, production build and packaged assets | Passed; packaged files match the build output |
| Independent Chromium workflow | Passed, 41 recorded checkpoints |
| Independent Firefox workflow | Passed, 41 recorded checkpoints |
| Supplied related acceptance cases | 12 passed; no failures, errors or skips |
| Analysis action command audit | Zero execution commands in both engines; durable command journals unchanged during analysis |
| Execution during historical inspection | Ledger advanced from 5 to 24 seconds in Chromium and 5 to 26 seconds in Firefox; retained historical checksums unchanged |
| Final disposable-service cleanup | Both exited normally with return code 0, zero worker leases, and temporary workspaces removed |

The independent workflows cover tabs and cohort expansion, untouched/current
time, intentional zero/fractions, edited and invalid drafts, exact Statistics
table samples, actual Plotly marker clicks, event selection, Before/After,
replay playback, run switching, keyboard operation and 390-pixel layouts.
They also hold or fail real browser requests to verify last-confirmed status,
late responses, and stale historical responses after switching runs.
Explicit Pause/Continue/Stop/Continue/Terminate and natural completion update
execution status while retaining the selected historical cursor and populations.
A delayed Continue acknowledgement cannot overwrite a newer completed summary.

The 12 acceptance cases cover linked cursors, replay preserving live execution,
causal conversion events, exact strings/stale seeks, stream gaps/reordering,
command recovery/stop, observation-cache privacy, three observer-independence
configurations, and Chromium/Firefox keyboard access. Their supplied inputs and
assertions were not changed. This is focused I25 verification, not a rerun of
the entire framework suite.

Evidence: [Chromium](../artifacts/issue25-fix/chromium/verification.json),
[Firefox](../artifacts/issue25-fix/firefox/verification.json),
[desktop history view](../artifacts/issue25-fix/chromium/running-history.png),
[narrow history view](../artifacts/issue25-fix/firefox/narrow-history.png), and
[terminated history view](../artifacts/issue25-fix/chromium/terminated-history.png).
Desktop and narrow screenshots were visually inspected for readable, separate
execution/view clocks and the persistent history explanation.

Earlier attempts remain alongside the final reports. In addition to the fixed
freshness flicker, test-fixture corrections addressed waiting on absent live-mode
banners, held request cleanup and using the production service-exit callback.
The earlier bare-server fixtures were drained first, then their listeners were
terminated; [cleanup evidence](../artifacts/issue25-fix/fixture-attempt-cleanup.json)
records their exit. Final verification uses the production shutdown lifecycle.

The [source audit](../artifacts/issue25-fix/source-verification.json) compares
7,820 pre-existing files: only the four approved GUI sources, packaged index and
replaced browser bundles changed. Two GUI files were added for the readouts and
their styling. Ontology specifications, supplied tests, task plans, scripts,
backend code and policies remain unchanged. The original user run's command
journal, final execution metadata and ledger frontier still match the read-only
pre-fix audit. No user simulation was started, stopped or rewritten for verification.

**Using the fix:** refresh the GUI page to load the rebuilt browser assets.
The [updated guide](USER_GUIDE.md#pause-save-terminate-or-replay) explains which
clock to read and how to return from recorded history to live follow.

## I26 World resizing leaves dependent layout coordinates unchanged

**Current status: approved, implemented and verified within the scope below.**
The [updated task plan](../prompts/zombie_game_plans.md#L33) reports the baseline
validation failure and requests automatic adjustment of related settings. Its
review instruction says: **“For each issue, you will wait for my review and
approval before continuing.”** The user subsequently approved the proposal:
**“I approve the I26 proposal. Implement and verify the fixes.”** The original
diagnosis and proposal are retained below, followed by implementation evidence.

### Cause and reproduced behavior

Selecting **Ontology baseline · 1,000 agents** loads a complete map in absolute
meter coordinates. Changing World length/width currently changes only the world
bounds. The map's 28 barriers (including four gates), four shelter interiors and
ten stockpiles retain their original coordinates.

For example, `barriers[0]` is `obstacle1`, whose footprint is
`[420, 180, 460, 340]`. It cannot fit inside a 200 × 200 world. The backend's
bounds check therefore correctly returns:

> barriers[0]: rectangle must have positive area and lie inside world bounds

The missing behavior is dependency adjustment in the configuration editor;
weakening or bypassing the geometry validator would conceal the problem.

The unchanged GUI reproduced this exact message in both
[Chromium](../artifacts/issue26-review/chromium/verification.json) and
[Firefox](../artifacts/issue26-review/firefox/verification.json), for length-only,
width-only and both-dimension changes. Submitted requests had the new dimensions
and unchanged geometry. No simulation was launched, no execution command was
issued, and both disposable services exited cleanly.

Relevant code: [baseline construction](../src/zombie_sim/config.py#L63),
[shared draft commit](../gui/src/main.tsx#L164),
[geometry validation](../src/zombie_sim/config.py#L175), and
[placement/connectivity](../src/zombie_sim/config.py#L400).

### Proposed behavior

**Changing world dimensions in the form will resize the spatial layout together.**

1. Apply an independent scale on each axis: `new_x = old_x × new_length / old_length`
   and `new_y = old_y × new_width / old_width`. Transform complete obstacle,
   wall and gate footprints, shelter interiors and stockpile coordinates as one
   operation. Retain entity IDs and shelter/gate/wall relationships. Do not clip,
   remove or independently relocate objects to make an invalid layout fit.
2. Apply this to ordinary custom spatial layouts as well as the preset. Explicit
   initial agent coordinates, when supplied in an ordinary new scenario, follow
   the same transform and remain subject to validation. Non-spatial custom
   settings remain intact. A visible note explains that world resizing also
   resizes custom coordinates, and a concise change summary identifies what moved.
3. Keep population and role counts, infection counts, inventories, gate integrity,
   seed, model settings, horizon, speeds, sensing/action ranges and initial
   separation distances unchanged. They are independent experiment parameters.
   A smaller world deliberately changes density; do not silently lower the
   population or spacing to make placement succeed.
4. Run the existing geometry checks on the adjusted configuration. For explicit
   initial agent coordinates, also check bounds, blocked positions, shelter
   restrictions and pairwise spacing during **Validate**, before reporting ready
   to launch. These deterministic agent checks currently happen only at
   initialization and must not be deferred after automatically shrinking those
   positions. Preview and initialization additionally verify connectivity and
   generated population placement. For definite
   custom conflicts, identify the relevant object/field or agent pair and the
   conflicting requirement. Preserve the draft so the user can correct it.
   An exhausted sampling budget must say no placement was found within the
   budget; it must not claim mathematical impossibility.
5. Show that this is a **customized baseline** and save the concrete adjusted
   configuration. Validate, Preview, Launch, Save and Export must all use the
   same committed values. Existing runs and their recorded histories are never
   resized or rewritten.

For the requested 200 × 200 world, the scale is 0.2 on both axes:

| Item | Original | Resized |
| --- | --- | --- |
| Obstacle 1 footprint | `[420,180,460,340]` | `[84,36,92,68]` |
| Shelter 1 interior | `[152,152,248,248]` | `[30.4,30.4,49.6,49.6]` |
| Exterior stockpile 1 | `(100,500)` | `(20,100)` |
| Shelter envelope | 100 × 100 m | 20 × 20 m |
| Gate footprint dimensions | 6 × 2 m | 1.2 × 0.4 m |
| Population | 800 Humans + 200 Zombies | Unchanged |
| Initial spacing | 2 m for every pair; 15 m Human–Zombie | Unchanged |

### How the implementation will preserve custom intent

- Integrate one resize operation into the shared GUI draft-commit path. Commit
  complete valid numeric edits together; empty or unfinished numeric/JSON input
  must not trigger a partial resize or overwrite the existing draft.
- Retain a reference layout during repeated edits, preserving identical shared
  coordinates and avoiding cumulative rounding or double scaling. Changing a
  preset, importing a configuration, or deliberately editing its geometry
  establishes the appropriate new reference. Saved/exported drafts retain
  concrete coordinates and sufficient editor provenance for consistent reopening.
- Resolve omitted preset geometry and effective `semantic` overrides before
  adjustment. Write the resized values to the effective configuration, so an
  old override cannot silently undo the world edit. Handle supported rectangle
  objects/arrays and agent maps/arrays consistently.
- Direct Advanced JSON or imported-file values remain explicit instructions;
  merely parsing, loading or importing them does not trigger an inferred resize.
  Subsequent World length/width form edits perform the announced resize.
  General CLI/API configuration resolution must not silently reinterpret files.
- A historical/runtime state import is a different case from an ordinary initial
  layout: it can contain frozen death positions, matching remains, signals and
  model-private spatial memory. Do not partially scale such records. Preserve
  that input and explain the unsupported automatic transformation, offering the
  ordinary new-scenario layout workflow. This is a capability boundary, not a
  claim that its geometry is mathematically impossible.

### Why the proposal addresses this issue

For a valid layout and positive dimensions, consistent axis scaling preserves
rectangle order, shared boundaries, containment and non-overlap mathematically.
Moving all connected parts together preserves the shelter assembly and its
topology. Revalidation catches floating-point degeneracy, malformed custom data
or other constraints that coordinate scaling alone cannot guarantee.

The proposal has also been checked with the actual initializer, without changing
application code. Isolated probes transformed the complete baseline map, used
seed `20261106`, and retained the previously approved relocation sampler,
population and separation settings:

| World | Geometry / connectivity | Initialized agents | Minimum same-type / cross-type distance |
| --- | --- | --- | --- |
| 1,000 × 1,000 m | Pass | 1,000 | 2.0281 / 15.0005 m |
| 200 × 200 m | Pass | 1,000 | 2.0042 / 15.0593 m |
| 200 × 1,000 m | Pass | 1,000 | 2.0068 / 15.0013 m |
| 1,000 × 200 m | Pass | 1,000 | 2.0730 / 15.0093 m |

No agents were inside blocking geometry and no Zombies started inside shelters.
See [feasibility evidence](../artifacts/issue26-review/feasibility.json) and the
[reproducible probe](../artifacts/issue26-review/feasibility_probe.py).
These checks establish that the reported dimensions can work under the existing
constraints. They are not a guarantee for every seed/custom configuration or
evidence that the proposed GUI implementation already passes. For example, a
1 × 1 m world cannot place two agents 2 m apart; that genuine conflict must still
be rejected.

### Verification required after approval

- Repeat the exact baseline → 200 × 200 → Validate → Preview → Launch workflow
  in Chromium and Firefox. Confirm 1,000 agents, unchanged roles/resources and
  strict spacing, readable adjustment feedback and correct initial geometry.
- Cover length-only/width-only edits, asymmetric worlds, enlargement, repeated
  resize/restore, sequential field blur, empty/invalid drafts and keyboard use.
- Cover valid custom layouts, custom resource-only edits, explicit agent
  positions, conflicting coordinates/spacing, partial presets and semantic
  overrides. Verify historical/runtime imports are never partially rewritten.
  Definite explicit-agent conflicts must fail Validate; generated-placement
  feasibility must remain clearly distinguished from configuration validation.
- Check Save/Load, copy-as-new, JSON/TOML export/import, preview invalidation and
  launch payload consistency. Verify direct configuration loading does not
  silently rescale geometry and unchanged baseline configurations remain intact.
- Run focused configuration, geometry, numeric editing, Advanced JSON protection
  and GUI/CLI parity regressions without changing supplied acceptance inputs or
  assertions. Verify disposal of all test services/runs.

**Ontology.** No ontology or problem-formulation change is proposed.
[§15.6](../ontology/zombie_game_ontology_v0.1.md#L669) permits world/geometry
variation and requires changed values to be recorded and revalidated.
[§3.1](../ontology/zombie_game_ontology_v0.1.md#L122) defines point agents, so the
smaller valid doorway does not require a new physical-body model. All canonical
Markdown/formal specifications were reviewed; the
[ontology review](../artifacts/issue26-review/ontology-review.json) records graph
integrity, OWL serialization equivalence and independent scaled-layout checks.

**Review boundary.** Only review documentation, independent reproduction scripts
and isolated evidence were added. The
[source audit](../artifacts/issue26-review/review-verification.json) verifies
existing production code, ontology, supplied tests and the user-edited plan are
unchanged. The reproduction scripts are
[Python](../implementation_checks/issue26_review_check.py) and
[browser](../implementation_checks/issue26_review_browser.cjs).
That review boundary describes the pre-implementation investigation. The work
below follows the user's subsequent explicit approval.

### Implementation after approval

- Added [worldLayout.ts](../gui/src/worldLayout.ts), a shared form-driven resize
  operation called by the existing draft commit before Validate, Preview, Launch,
  Save or Export. All supported barrier/shelter rectangles, stockpile points and
  ordinary explicit agent positions change together. IDs, references and
  non-spatial attributes are retained.
- Resolved effective preset and `semantic` spatial values before resizing.
  Materialized coordinates take precedence over the original map; unrelated
  semantic settings survive. Direct JSON/TOML loading and general configuration
  resolution do not infer a resize.
- Saved versioned reference geometry under `gui.world_resize`. Decimal-rational
  axis calculations and stable reference coordinates avoid cumulative drift.
  Reopening concrete resized data does not apply the transform again; deliberate
  geometry edits invalidate the old reference. Unsupported, stale or tampered
  metadata cannot supply a misleading adjustment summary.
- Added visible resizing guidance, a change summary and **Customized baseline**
  label. World inputs display effective dimensions, including partial presets
  and semantic overrides. Preview invalidation and unfinished JSON/numeric-draft
  protections remain part of the shared editor workflow.
- Guarded historical/runtime imports, model-private spatial state and ambiguous
  alternate coordinate representations before any draft mutation. The error
  explains the unsupported automatic transformation and retains the input.
- Added a reusable deterministic initial-position check in
  [config.py](../src/zombie_sim/config.py). Ordinary explicit positions now fail
  Validate on out-of-bounds coordinates, blocked positions, initial Zombie shelter
  occupancy or insufficient spacing. Diagnostics identify affected agents,
  objects and actual/required distances. Initialization reuses these rules;
  historical state imports retain their separate semantics. Validate does not
  perform stochastic sampling or promise connectivity/placement success.
- Updated the [GUI resizing guide](GUI.md#resize-a-world-and-its-layout) and
  [baseline walkthrough](USER_GUIDE.md#resize-the-baseline-world), and rebuilt
  the packaged assets.

The implementation preserves the approved 1,000-agent population, role/resource
totals, 2 m minimum pair spacing and 15 m Human–Zombie spacing. It uses the
already-approved conditional relocation sampler; no new approximation or
ontology change was introduced.

### Final verification

The [consolidated verification record](../artifacts/issue26-fix/verification.json)
passes. The final TypeScript/Vite build was packaged successfully; its served
JavaScript is `index-CxGhr5tJ.js` and its stylesheet is `index-DRWMcKSA.css`.
The packaged files match the built files byte for byte.

| Verification | Result and evidence |
| --- | --- |
| Supplied core acceptance suite | **489 passed**, no failures, errors or skips; [report](../artifacts/issue26-fix/core-acceptance.json) |
| Supplied browser acceptance cases | **10 passed**: configuration validation (5), CLI parity (1), preview RNG isolation (1), edit-as-new/model intervention (1), and keyboard accessibility in both engines (2); [reports](../artifacts/issue26-fix/acceptance/) |
| Independent layout helper | **35 passed**, including asymmetric/repeated scaling, exact restoration, semantic overrides, custom geometry, explicit positions, stale/tampered references and guarded runtime data; [report](../artifacts/issue26-fix/layout-helper.json) |
| Explicit-position validation | **26 direct and 26 real HTTP checks passed**, including historical-state compatibility and JSON/TOML round trips; [report](../artifacts/issue26-fix/validation.json) |
| Actual I26 GUI workflows | **29 Chromium / 28 Firefox checks passed**; [Chromium](../artifacts/issue26-fix/chromium/verification.json), [Firefox](../artifacts/issue26-fix/firefox/verification.json) |
| Numeric editing regressions | Both engines passed 11 workflows, nine fields, 45 blank-field/action combinations and 33 domain cases each; [Chromium](../artifacts/issue26-fix/numeric-chromium/verification.json), [Firefox](../artifacts/issue26-fix/numeric-firefox/verification.json) |
| Mixed editor and retained GUI regressions | Both engines passed Advanced JSON protection, round trips, default-seed and historical cohort export checks; [Chromium](../artifacts/issue26-fix/mixed-editor-chromium/verification.json), [Firefox](../artifacts/issue26-fix/mixed-editor-firefox/verification.json) |

The **499 supplied acceptance cases** are distinct. The separately recorded five
`SYS_CONFIG` cases are a subset of the 489 core cases and are not counted again.
This is targeted coverage, not a rerun of the complete 539-case catalog.

In both browsers, changing the baseline to **200 × 200 m** passed Validate,
Preview and actual Launch with all **1,000 agents**. Independent checks found
800 Humans, 200 Zombies, 20 initially infected Humans, unchanged role counts and
resource totals (600 Food, 280 Medical Supply, 400 Material), valid geometry and
no initial Zombie shelter occupancy. Minimum same-type separation was
**2.0041515665 m** and minimum Human–Zombie separation was **15.0593150446 m**,
above the retained 2 m / 15 m limits. Every initialization field supplied by the
preview matched the launched revision-zero record for every identity.

These actual executions used seed `20261106`, one worker and a deliberately
short **0.05 s horizon**, and completed. Tests first confirmed that resizing
preserved the original independent parameters, then explicitly changed the
worker/horizon settings to bound execution. This verifies initialization and
launch, not a full 1,800 s simulation or feasibility for every seed and custom
world. The strict validator and placement checks still reject genuine conflicts.

Browser coverage also includes length-only/width-only edits, enlargement,
asymmetric dimensions, repeated restoration, invalid or unfinished input,
partial presets, semantic overrides, custom resource quantities and geometry,
explicit-agent spacing conflicts, historical-state protection, saved drafts,
JSON/TOML export/import, preview invalidation and immutable copy-as-new source
history. Direct JSON/API changes remain literal and do not trigger inferred
scaling. Desktop and 390 px views were visually inspected; see the
[desktop screenshot](../artifacts/issue26-fix/chromium/resized-baseline-preview.png)
and [narrow screenshot](../artifacts/issue26-fix/chromium/narrow-resize-feedback.png).

Initial independent browser-check attempts compared whole preview records with
live records containing additional runtime fields. Their failed assertions and
cleanup evidence are retained. The corrected oracle compares every
preview-provided field per identity and separately verifies geometry, counts,
roles, resources and spacing. No application fix or supplied acceptance-test
change was made to satisfy that harness correction.

The disposable I26, HTTP and mixed-editor services exited with code zero, no
worker leases and their temporary workspaces removed. Numeric-regression
services also exited and removed their workspaces. Copy-as-new and regression
source histories match their before/after audit records. The
[source audit](../artifacts/issue26-fix/source-verification.json), rechecked after
all verification, confirms ontology, supplied tests, the user-edited plan,
launcher scripts, policies and other engine sources remain unchanged from the
review snapshot. Existing user runs and their audit histories were retained.

**Using the update.** Restart the web service and refresh the GUI to load both
the validation changes and rebuilt interface. With the friendly launcher,
`./simulate shutdown` saves active runs and stops its service; `./simulate gui`
starts it again and opens the GUI. Then follow the
[200 × 200 walkthrough](USER_GUIDE.md#resize-the-baseline-world). Existing
configurations change only when you deliberately edit their world dimensions in
the form.

## I27 GUI times expose long exact fractions

**Current status: individually approved, implemented and verified within the scope below.**

**Approval.** The user approved this proposal: “I approve the I27 proposal.
Implement and verify the fixes.” The original diagnosis and proposal below are
retained as the pre-implementation review record.

**Reported issue.** The latest [task plan](../prompts/zombie_game_plans.md)
requires live time values such as `127500000000000017/2500000000000000` to be
readable and sensibly rounded while retaining useful precision. It also requires
an explanation and approved proposal before implementation. The diagnosis and
proposal below record that review; production behavior was unchanged at that stage.

### Cause and observed evidence

The reported fraction is exactly **51.0000000000000068 seconds**. The engine uses
exact rational time and emits canonical strings through
[`clock` / `stamp`](../src/zombie_sim/engine.py#L31). This supports precise
scheduling, history queries and causal revision selection. Geometric durations
can originate as floating-point calculations and are converted once into the
recorded clock representation, so long numerators and denominators are expected.
The reported symptom does not establish a scheduler error.

The GUI lacks a shared time presentation policy:

- [RunViewStatus](../gui/src/RunViewStatus.tsx#L47) renders the execution and
  displayed-view times directly as strings. Statistics, Cohorts, Comparison,
  chart hover labels and various notices do the same.
- [main.tsx](../gui/src/main.tsx#L44) formats selected sidebar and notice values
  with a generic floating-point, two-decimal helper, also used for non-time data.
- [EventsPanel](../gui/src/EventsPanel.tsx#L6) separately rounds event-row labels
  to three decimals with exact integer arithmetic and an approximation marker,
  but its source/cursor labels still print the raw fraction.

The [formatting audit](../artifacts/issue27-review/formatting-audit.json) records
29 source locations and eight probes against the existing helpers. Those probes
also establish two boundary cases within this issue: very small positive times
can be displayed as zero, and converting large exact integers through JavaScript
`Number` can change their displayed integer value. Reusing the generic helper
for every clock would therefore be insufficient.

Both [Chromium](../artifacts/issue27-review/chromium/verification.json) and
[Firefox](../artifacts/issue27-review/firefox/verification.json) reproduce the
reported fraction on **14 GUI surfaces**, including both large clocks,
Statistics source/table labels, Events source/status text, Cohorts and Comparison.
The [clock screenshot](../artifacts/issue27-review/chromium/raw-live-clocks.png)
shows the contradiction clearly: the sidebar reads `51 s`, while both main
clocks print the entire fraction. Existing event rows already render rounded
labels such as `≈51 s`.

The reproduction used the real engine to advance two isolated runs to the exact
reported time, then viewed them in live-follow mode while paused. These are
controlled rendering reproductions, not screenshots of continuous execution.
Selecting the Statistics endpoint retained the exact fraction and revision
`70`. Browser navigation issued no execution commands and left configurations,
command ledgers and recorded histories unchanged. Both disposable services
exited with code zero, no worker leases and their temporary workspaces removed.

### Proposed behavior

Use one time formatter throughout ordinary GUI readouts, with the following
explicit policy:

| Exact source value | Proposed visible label | Meaning |
| --- | --- | --- |
| `0` | `0 s` | Exactly zero |
| `5/2` | `2.5 s` | Exactly representable at the displayed precision |
| `127500000000000017/2500000000000000` | `≈51 s` | Rounded display of the reported value |
| `1/3` | `≈0.333 s` | Repeating fraction rounded to milliseconds |
| `0.00000001` | `1e-8 s` | Small positive time remains visibly nonzero |
| `9007199254740993` | `≈9.0072e15 s` | Compact large time; exact integer remains available |

1. For ordinary values from `0.001` to below `1e9` seconds, use up to **three
   decimal places**, removing unnecessary trailing zeros. Round to the nearest
   millisecond, with half ties rounded upward for valid nonnegative clocks.
2. For smaller positive or very large values, use scientific notation with up to
   **six significant digits**. Normalize carry at the notation boundaries, so
   a rounded mantissa does not become an awkward `10e…`. Zero has its own exact
   representation and is never used as the label for a positive tiny time.
3. Add `≈` only when the displayed numeric value differs from the exact source.
   Explain once near the time controls that it means display rounding. Retain
   revision/sequence context: different instants can legitimately have the same
   rounded label.
4. Use exact integer/rational arithmetic to calculate the text. Do not first
   convert large numerator/denominator strings to `Number`. Handle absent or
   malformed values with a clear unavailable label rather than inventing zero.
5. Make the exact source value available through a clearly labelled **Exact
   time** detail, usable with keyboard and touch. Hover text can supplement it,
   but must not be the only way to inspect precision.

Ordinary decimal labels have at most **0.0005 s display error**. Scientific
labels round at the sixth significant digit. These are presentation bounds;
the stored time and the time used by the engine remain exact.

### Concrete implementation plan

**A. Shared formatting and display.** Introduce a pure time-formatting module
with a structured result containing the compact label, original exact text and
whether rounding occurred. Add a reusable display/detail component or equivalent
shared presentation helpers. Keep generic formatting for life, stamina,
coordinates and other non-time measurements separate.

**B. Apply it to the complete time-readout inventory.**

| Area | Readouts to update |
| --- | --- |
| Execution and viewing | Both status clocks, sidebar/chooser summaries, loading boundaries and operation acknowledgements |
| Statistics | Metric/resource cursors, stale/error source messages, chart-source caption, sample table and Plotly hover labels |
| Events | Existing rounded rows, source/paging/status labels and selected-event provenance |
| Cohorts | Creation reference, saved reference, measurement/export source and survival entry times |
| Comparison | Common intervals, sample spacing, origin/frontier/source times, sample tables and chart hovers |
| Research controls | Observation headings, branch/intervention context, command receipts and time-control summaries |

Chart positions still use the existing numeric plotting coordinates; their
readable ticks and hover text are presentation only. Exact time/revision values
in `customdata`, row attributes, callbacks and keys remain authoritative.
Do not key, sort, deduplicate or select records using formatted labels.

**C. Separate readable summaries from exact editing.** For the replay,
Statistics, export and intervention time controls, show a compact time summary
and provide an optional, clearly labelled exact editor. Opening the editor
reveals the original input string; it does not count as an edit. Entering or
pasting text continues to accept exact decimal/fractional values under the
existing validation rules. Preserve entered text while the user edits.

An untouched selection submits its original exact time and, where currently
supported, revision. In particular, preserve I25's Statistics editor behavior.
Never put `≈` into an editable numeric value, parse the compact label as a
request, or replace a submitted time merely because focus changed. Export and
intervention submissions continue to use their exact input strings. This
proposal includes making these editors discoverable by keyboard, with readable
summaries in their collapsed state; it does not propose changing command or
export semantics.

**D. Preserve research data.** The scheduler, simulation state, history,
checkpoints, API/transport strings, raw record details, CSV/JSON/Parquet data and
export provenance retain their exact values. Human-readable GUI labels change;
opening or selecting them must not mutate the run. Exact details can continue
to show a fraction when it is the authoritative representation.

**E. Document and package.** Update the GUI/user guides to explain the precision
policy, approximation marker, exact-time access and exact selection behavior.
Rebuild and verify the packaged GUI assets after implementation.

### Why this addresses the issue

One formatter removes the current raw-string/two-decimal/three-decimal
inconsistency. Exact arithmetic prevents oversized fractions from overflowing
or losing significant digits before rounding. Scientific notation prevents tiny
positive times from masquerading as zero and keeps very large times readable.
Separating display text from exact input and selection data prevents a cosmetic
change from selecting the wrong side of an event boundary.

For example, the reported fraction is slightly later than `51`. Showing both as
`51 s` or `≈51 s` must never merge their observations, change a deadline, or
substitute revision `69` for revision `70`. The implementation is only complete
when the regression checks below establish those properties. A proposal alone
is not a verified fix.

### Verification required after approval

- Test the user example, exact integers/decimals, repeating fractions, zero,
  tiny positive times, large rational components, ties, notation-boundary carries
  and absent/invalid inputs. Verify labels and approximation flags against an
  independent exact-arithmetic oracle.
- Reproduce the reported workflow in Chromium and Firefox with the final
  packaged assets, including actively advancing runs as well as paused/live,
  historical replay, stale/error/loading states and all inventoried readouts.
  Check desktop and narrow layouts, keyboard access and exact detail disclosure.
- Use two distinct times that round to the same label and multiple revisions at
  one time. Verify chart/table/event selections and before/after navigation send
  the original exact time/revision. Rounded text must never become identity.
- Cover untouched and edited exact-time controls, opening/closing without
  changes, partial/invalid input, focus/blur, live refresh and run switching.
  Check exact request payloads for seek, cohort reference, export and intervention,
  including retained command retry requests.
- Compare machine-readable exports and provenance with the exact source data;
  retain raw inspection data and source-history/configuration/command audits.
- Run relevant supplied exact-string, linked-cursor, replay isolation,
  timestamp-step/restart, causal-timeline, keyboard and export acceptance cases,
  plus I25 editor/view regression checks. Do not change supplied acceptance inputs
  or assertions to accommodate rounded labels. Where a browser adapter currently
  reads visible text as an exact value, update its query to the retained exact
  metadata while preserving the supplied test's input and expected value.
- Verify build/package parity and clean shutdown of disposable verification
  services, with no outstanding worker leases or changes to existing user runs.

### Ontology and review boundary

No ontology or problem-formulation change is proposed. Canonical Markdown and
formal specifications were reviewed. [Ontology §14.1](../ontology/zombie_game_ontology_v0.1.md#L544)
defines nonnegative elapsed time and exact equal-time precedence while leaving
storage representation to TASK 2. The [implementation plan](../prompts/task_2_implementation_plan.md#L171)
requires exact rational clocks with readable seconds and prohibits epsilon
merging. Its transport/export contracts require exact values and provenance.

The [ontology review](../artifacts/issue27-review/ontology-review.json) records
successful parsing of the canonical graphs, equivalent OWL serializations and
all 70 embedded SPARQL queries. It is a semantic review and syntax/integrity
check, not a full reasoner/SHACL conformance rerun.

Only this review document, independent reproduction scripts and isolated
evidence were added. The scripts are
[Python](../implementation_checks/issue27_review_check.py) and
[browser](../implementation_checks/issue27_review_browser.cjs).
The [review verification](../artifacts/issue27-review/review-verification.json)
checks production code/assets, ontology, supplied tests, implementation plans,
the user-edited task plan and launcher scripts against the start-of-review
snapshot. That boundary describes the review before approval; implementation
now proceeds under the user's explicit approval above.

### Implementation after approval

- Added [timeFormat.ts](../gui/src/timeFormat.ts), which parses decimal,
  scientific and fractional strings and rounds with exact integer arithmetic.
  It returns the original string separately from the readable label and its
  approximation flag. Invalid values are unavailable, not silently zero.
- Added [TimeValue and ExactTimeInput](../gui/src/TimeValue.tsx). Exact-value
  disclosures work through ordinary buttons; exact editors use native
  keyboard-accessible disclosures. Their input strings remain authoritative;
  opening a disclosure does not invoke an edit or submit a rounded value.
- Applied the shared policy to both clocks, run summaries, Statistics, Events,
  Cohorts, Comparison, observation/branch context and command receipts. Chart
  hover labels use an additional formatted field while retaining the original
  exact time/revision fields for navigation. Event details expose the event's
  exact time separately from the page's source cursor.
- Preserved the Statistics editor's I25 behavior. Replay now keeps its edited
  text separately from the live playback position; live refresh cannot overwrite
  a draft. An untouched inspection uses the loaded state's exact time/revision.
  Invalid drafts stay editable without navigating, and run changes reset them.
- Command-bar notices retain a disclosure of the actual receipt timestamp,
  independently of the advancing execution clock. Export/intervention controls
  retain their exact request strings and existing operation semantics.
- Updated browser-driver selectors to open the new visible disclosures, and
  changed the I25 independent harness to inspect exact metadata where visible
  labels are now rounded. Supplied acceptance inputs and expected assertions
  were retained.
- Updated [GUI documentation](GUI.md#readable-and-exact-times) and the
  [user guide](USER_GUIDE.md#read-the-time-and-source-labels), and rebuilt the
  packaged GUI. No scheduler, storage, API, ontology or machine-readable export
  implementation changed.

### Final verification

The [consolidated verification record](../artifacts/issue27-fix/verification.json)
passes. The final TypeScript/Vite build and packaged GUI match byte for byte:
`index-CBxHCmxL.js` and `index-D-HLrYWX.css`.

| Verification | Result and evidence |
| --- | --- |
| Shared formatter against independent arithmetic | **556 passed**: 532 valid strings, 20 invalid inputs and four numeric inputs, checked using Python Decimal/Fraction arithmetic; [report](../artifacts/issue27-fix/formatting.json) |
| Dedicated I27 browser workflows | **31 checks passed per engine**; [Chromium](../artifacts/issue27-fix/chromium/verification.json), [Firefox](../artifacts/issue27-fix/firefox/verification.json) |
| I25 time/navigation regressions | **41 steps passed per engine**; [Chromium](../artifacts/issue27-fix/i25-chromium/verification.json), [Firefox](../artifacts/issue27-fix/i25-firefox/verification.json) |
| Entire supplied browser acceptance tier | **38 distinct cases passed**, including exact strings, linked cursors, replay, timestamp stepping/restart, causal timelines, command recovery, keyboard and exports; [combined report](../artifacts/issue27-fix/acceptance/verification.json) |
| Actual downloaded data and provenance | Exact CSV, cohort JSON and Comparison CSV values, source fields and provenance checked independently in both engines; [report](../artifacts/issue27-fix/artifact-exactness.json) |

The original browser-tier run passed 37 cases and hit the runner's **60-second
whole-case limit** in `GUI_PREVIEW_RNG_ISOLATION`. This case performs several real
1,000-agent initializations. Its unchanged rerun passed in **64.286 seconds**
with a **120-second limit**. The original report, exception and successful rerun
are retained, and the case is counted once. No application change or weaker
assertion was used to resolve the timeout.

The browser checks cover the reported fraction and nearby exact instants with
the same readable label, multiple causal revisions at one time, chart/table/event
selection, before/after navigation, live execution, paused/history views,
retained stale/error sources, keyboard disclosure and 390 px layouts. Untouched
controls submit the original time/revision; edited fractions and partial drafts
survive live updates and focus changes. Opening/closing an exact editor does not
alter its value. An actual intervention retained its exact timestamp and the
command-bar receipt exposed that same value independently of the live clock.

Desktop and narrow screenshots were inspected:
[readable clocks](../artifacts/issue27-fix/chromium/readable-live-clocks.png) and
[narrow controls](../artifacts/issue27-fix/chromium/narrow-readable-times.png).
The captured primary run is paused; separate checks prove active execution and
draft preservation while live time advances. Raw record details and explicitly
opened exact editors intentionally retain full fractional values.

The first independent harness attempts used a nonexistent cohort-export locator
and began a simulated outage before the prior Statistics source had loaded.
Those harness errors and their cleanups are retained. The final runs correct
those fixture assumptions and verify the actual loaded-source behavior; no
production change was made for either harness correction.

The I27 and I25 disposable services all exited with code zero, completed
shutdown, released worker leases and removed their temporary workspaces. Paused
source audits and existing active-history prefixes stayed unchanged. The
[timeout cleanup audit](../artifacts/issue27-fix/acceptance/timeout-cleanup.json)
confirms the timed-out fixture workspace was removed, its recorded workers were
gone and no inspected process referenced its exact paths. Four unrelated
processes restricted file-descriptor inspection; all predated the attempt.
No user service or run was stopped during verification.

The [source audit](../artifacts/issue27-fix/source-verification.json), rechecked
against the final build, confirms the ontology, supplied test definitions,
user-edited plan, launcher, configuration files and backend implementation remain
unchanged from the review snapshot. Three generated, tracked test-cache files
were restored byte for byte to that snapshot after an inventory command
regenerated them; no test source or assertion changed. Existing I01–I26 evidence
and audit histories remain intact.

This verification covers the full **38-case browser tier**, independent formatter
oracles and the targeted browser/data regressions above. It is not a rerun of the
complete 539-case catalog or a full-duration baseline simulation. The unchanged
backend and ontology were verified by source hashes.

**Using the update.** Refresh the GUI to load the rebuilt interface. Ordinary
readouts now show values such as **≈51 s**. Use **Exact time** to reveal the
original value, or expand **Edit exact time** to enter a precise timestamp. See
[the time guide](GUI.md#readable-and-exact-times).
