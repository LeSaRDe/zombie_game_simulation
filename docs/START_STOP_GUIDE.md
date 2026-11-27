# Starting and stopping the Zombie Game Simulation

For a first experiment with screenshots, start with the
[friendly user guide](USER_GUIDE.md). This page is the detailed service,
launcher and command-line reference.

This guide covers the current Linux checkout at
`/home/fmeng/workspace/zombie_game_simulation`. You can run a simulation directly
in a terminal, or start the local web service and control simulations in a browser.
The browser GUI and HTTP API are served by the same Python service; ordinary use
does not require a separate frontend server.

**Use `./simulate shutdown` to save active runs and close the owned service, or
add `--terminate` to end them without another checkpoint. Closing a browser tab
does not stop a simulation.**

## Contents

- [Use the easy launcher](#use-the-easy-launcher)
- [Choose an operation](#choose-the-operation-you-need)
- [Prepare the terminal](#prepare-the-terminal)
- [Start the web service and GUI](#start-the-web-service-and-open-the-gui)
- [Create a GUI run](#create-and-start-a-simulation-in-the-gui)
- [Pause, save, continue or terminate](#pause-save-continue-or-terminate-a-gui-run)
- [Shut down and restart the service](#shut-down-and-restart-the-web-service)
- [Run directly from the command line](#run-directly-from-the-command-line)
- [Control managed runs through the API](#control-a-gui-managed-run-from-a-terminal)
- [Share CLI and GUI runs](#share-runs-between-the-cli-and-gui)
- [Preserve and recover saved work](#preserve-saved-work-and-recover-after-an-interruption)
- [Troubleshoot](#troubleshoot-startup-and-shutdown)

## Use the easy launcher

The simplest option on this Linux checkout is:

```bash
cd /home/fmeng/workspace/zombie_game_simulation
./simulate
```

No manual environment activation is needed. The script prefers `.runtimeenv`,
then `.venv`, then `python3`. To select another prepared Python environment, set
`ZOMBIE_SIM_PYTHON` to its interpreter path. The chosen environment needs Python
3.12 or later and the GUI dependencies described below; the launcher does not
install packages automatically.

Choose **1** to start a small simulation, **9** to open the GUI, or **10** to shut
down runs and the service. The menu explains whether an action saves a checkpoint.
After choosing a run-control operation, select the run from a numbered list.
The browser opens automatically when a graphical desktop is available; otherwise
the script prints its address. Choosing **0**, closing the menu terminal, or
pressing Ctrl+C in the menu leaves the independently running service and
simulations intact.

The launcher uses `runs/launcher` and port **8767** by default. This is a separate
workspace from the manual `runs/workspace` examples later in this guide. It will
not take over or stop an unrelated service already using a port. Use one service
per workspace; stop a manually started service before trying to use its directory
with the launcher.

For direct commands instead of the menu:

```bash
./simulate start                   # Small scenario and GUI
./simulate start baseline          # Full 1,000-agent scenario and GUI
./simulate start configs/small.toml --workers 4 --no-browser
./simulate list
./simulate pause 1
./simulate resume 1
./simulate stop 1                  # Save, wait for worker exit, remain resumable
./simulate terminate 1             # End an active run without another checkpoint
./simulate gui                     # Start/reuse this workspace's service and open the browser
./simulate shutdown                # Save active runs and stop the service
./simulate shutdown --terminate    # Terminate active runs and stop the service
```

These are individual examples; each `start` creates another run. Replace `1` with
the intended run's current list number, full ID or unique ID prefix. IDs are the
best choice when other clients might create runs and reorder the list. In an
interactive terminal, omit the ID to select from a menu, for example
`./simulate terminate`. Termination keeps existing history. Already stopped,
failed or otherwise inactive runs are left unchanged instead of restoring them
just to change a status; saved stopped runs therefore remain resumable.

To use another workspace or port, put the options **before** the action and use
the same workspace on subsequent calls:

```bash
./simulate --workspace runs/my-study --port 8770 start --no-browser
./simulate --workspace runs/my-study --port 8770 list
./simulate --workspace runs/my-study --port 8770 shutdown
```

The launcher's shutdown procedure prevents new starts/resumes and analysis work,
closes viewers, cancels outstanding readers/exports, reconciles accepted commands,
saves or terminates active runs and verifies worker cleanup before requesting
service exit. Browser tabs may remain open. Progress prints on phase changes and
at least every five seconds while waiting, with elapsed time, outstanding work
and per-run command references. The shutdown timeout covers the whole operation.
An incomplete result keeps the service draining and reports the unfinished phase;
retry with the same mode and, if needed, a larger timeout. Simulation writers are
never force-killed. Existing history and older checkpoints remain retained.

If shutdown fails before the service begins exiting, the service can remain
available for inspection and a repeated `shutdown`; new starts remain blocked
until that shutdown completes and the service is restarted. For a new session
where you want to observe service exit directly, use the
[foreground service workflow](#start-the-web-service-and-open-the-gui), followed
by [explicit run cleanup and Ctrl+C](#shut-down-and-restart-the-web-service).
Do not start a foreground service against a workspace whose launcher service
is still running.

Commands wait up to 900 seconds by default, including long checkpoints. Shutdown
uses one overall budget. A timeout does not cancel a submitted writer command.
Ordinary run-control requests have a printed reference and saved payload under
the workspace's `.launcher/requests/` folder; shutdown uses stable per-run command
IDs reported by its status endpoint and printed with the outcomes:

```bash
./simulate requests
./simulate retry REPLACE_WITH_REQUEST_REFERENCE
./simulate --timeout 1800 shutdown
```

`retry` resubmits the exact original operation and reconciles its durable result;
it does not create a duplicate run. A definite rejection is identified separately
and retains that rejection on retry. Check the run state before issuing a new
operation after a rejection. The default service log is
`runs/launcher/.launcher/service.log`. Run `./simulate --help` or
`./simulate start --help` for options, including seed and horizon overrides.

The rest of this guide documents the underlying manual commands. The launcher's
`stop`, `terminate` and `shutdown` commands are conveniences provided by this
script; they are not new subcommands of `python -m zombie_sim.cli`.

## Choose the operation you need

| Your intention | Operation | Can the run continue later? |
| --- | --- | --- |
| Temporarily halt simulation time | GUI **Pause run** or API `pause` | Yes, with **Continue run**. The worker remains resident. |
| Save continuation state and release the run worker | GUI **Stop & save** or API `stop` | Yes, after the worker finishes saving and exits. |
| End a managed run without requesting another checkpoint | GUI **Terminate without a new checkpoint** or API `terminate` | The GUI/API reject further execution of that run. Existing history is retained. |
| Finish a headless command at a chosen simulation time | CLI `run … --until TIME` | Yes if the horizon has not been reached and extinction has not completed the run. |
| Interrupt a foreground headless run or resume | Press **Ctrl+C** once | Finishes atomic work, saves a committed checkpoint and manifest, then closes workers. See interruption details below. |
| Close only the viewer | Close the browser tab | The simulation continues if it was running. |
| Shut down a foreground HTTP service and GUI hosting | Press **Ctrl+C** in the service terminal | Drains viewers/readers and saves active runs before exit. Terminate runs first if you want no new checkpoint. |

“Without save” means **without an additional checkpoint requested by termination**.
It does not disable the durable history, remove earlier checkpoints, delete files,
or undo events already committed. A checkpoint already in progress may finish
before pause or termination can acknowledge.

## Prepare the terminal

### Use the existing environment in this checkout

Run these commands in each terminal that will issue simulation commands:

```bash
cd /home/fmeng/workspace/zombie_game_simulation
source .runtimeenv/bin/activate
export PYTHONPATH="$PWD/src"
python -m zombie_sim.cli --help
```

The commands below use `python -m zombie_sim.cli` so they select the Python
environment you activated and the source tree you are working on. The installed
`zombie-sim` command is an equivalent entry point when it belongs to that same
environment.

### Install on a fresh checkout

Python 3.12 or later is required. From the repository root, create and activate
a virtual environment, then install the package:

```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[gui]'
```

The GUI extra installs the web-service dependencies. For headless simulation
alone, `python -m pip install -e .` is sufficient. Optional Parquet/analysis
features use `.[analysis]`; ontology tooling uses `.[ontology]`.
Use a Python interpreter of at least version 3.12 when creating the environment.
The repository already contains the compiled GUI; Node and pnpm are needed only
when rebuilding frontend source.

## Start the web service and open the GUI

Keep this command running in a dedicated terminal:

```bash
python -m zombie_sim.cli gui \
  --experiments-dir /home/fmeng/workspace/zombie_game_simulation/runs/workspace \
  --host 127.0.0.1 \
  --port 8765
```

Wait for the startup message, then open [http://127.0.0.1:8765](http://127.0.0.1:8765).
The terminal stays occupied because it owns the web service. Starting the service
does not itself create a new simulation or start every saved run.

The GUI opens on **Choose a run or create an experiment.** Select an existing
run to load its recorded history, or choose **New experiment** to create one.
Opening the home screen does not automatically reconstruct an indexed run.
**Initializing the world** describes actual run initialization; **Loading
recorded history** describes a viewer read. Cancel loading or return to **Run
list** without stopping the simulation. If a read fails, choose **Retry loading**
or **Return to run list**. Atomic reader work already in progress may finish
before cancellation takes effect.

The `--experiments-dir` directory is the persistent workspace. Reuse **the same
absolute directory** on subsequent starts to see the same experiments. A
different directory opens a different workspace. Run only one web-service
instance for a given workspace directory.

This release supports local loopback hosting only. `--host 0.0.0.0` is not a
supported way to expose it on a network. No external database service is needed;
the application uses local SQLite files.

If port 8765 is already occupied, first check whether your existing service is
the one you want. Do not start a duplicate service for its workspace. To create
a separate workspace on another port, use both a different directory and port:

```bash
python -m zombie_sim.cli gui \
  --experiments-dir /home/fmeng/workspace/zombie_game_simulation/runs/other-workspace \
  --host 127.0.0.1 --port 8767
```

Then open [http://127.0.0.1:8767](http://127.0.0.1:8767).

## Create and start a simulation in the GUI

1. Select **New experiment** or **Create your first experiment**.
2. Start with the small preset for a quick check. For the full scenario, choose
   **Ontology baseline · 1,000 agents**. The baseline has a 1,800-second simulated
   horizon and uses the explicitly approved approximate placement sampler.
3. Set the seed, horizon, population, storage backend and worker selection.
   **Automatic** considers CPU affinity, quotas and available memory. A manual
   worker limit is also available. More workers do not guarantee faster execution;
   serial coordination and checkpoints still limit scaling.
4. Select **Validate**, then **Preview placement**. The preview is separate from
   the live run and does not consume its decision randomness.
5. Select **Launch run**. This creates **and starts** the simulation. Wait for
   initialization and the start acknowledgement before issuing another control.
6. Select the run in the sidebar. Its execution status, time and revision identify
   the simulation you are controlling. **Run pace** changes wall-clock pacing;
   **Fastest** removes intentional pacing delays.

The GUI's built-in small preset and `configs/small.toml` are different scenarios.
The file has 24 agents and a 120-second horizon. To use that exact file in the GUI,
open **Advanced configuration · JSON**, use **Import configuration**, and select
`configs/small.toml` before validation and launch. Import the same configuration
and seed when comparing GUI and CLI behavior.

Initialization of a dense scenario and large checkpoints can take substantial
time. A pending command or slow initial display is not an instruction to create
a duplicate run. Follow its status and any displayed error.

## Pause, save, continue or terminate a GUI run

### Pause and continue

Select **Pause run** in the **EXECUTION** control bar. Wait until the command is
applied and the run status is `paused`. At that point, time and revisions no
longer advance on their own. Pausing does not shut down the coordinator or its
worker pool, so resident processes and memory are expected.

Select **Continue run** to advance again. **Step transition** and **Step timestamp**
are available while paused. The replay player's pause button affects only the
display of recorded history; it does not pause the simulation. Selecting an older
replay time also leaves live execution unchanged.

### Save and stop for later

Select **Stop & save**. Wait for the applied acknowledgement and `stopped` status.
The worker saves continuation state and exits. Acknowledgement can precede the
last serialization and process cleanup, so allow that work to finish before
closing the service or taking control through the CLI.

To resume later, restart the web service with the same workspace if necessary,
select the stopped run, and select **Continue run**. If the service reports that
the previous worker is still saving, wait and retry after it finishes. **Checkpoint**
alone saves a continuation checkpoint without stopping execution.

### Terminate without an extra save

Select **Terminate without a new checkpoint** for the selected run. The GUI
first shows **Termination requested**, then **Stopping / cleanup** after
acknowledgement. Wait for **terminated** and the **Worker cleanup complete**
notice before treating the worker resources as released.
There is no need to use **Stop & save** first if the intention is specifically
to avoid an additional checkpoint.

The GUI/API will not continue a terminated run. Its existing history remains
available under **Terminated history** for inspection and export; termination
is not deletion. Live updates end after the final frame. To run the
scenario again from the beginning, use **Edit as new run** or **New experiment**
to create a new identity.

Direct CLI `resume` also enforces durable termination before restoring state,
under the run's worker lease. A terminated run remains available for replay and
export but cannot resume in place. Stopped or interrupted histories remain
resumable when otherwise valid.

### Understand acknowledgement and delays

Pause and termination take effect at a committed engine boundary. An already
running synchronous checkpoint must finish before these commands can be applied;
large runs can therefore remain pending for a considerable time. A terminal run
status can appear before all process cleanup has finished.

If a request times out, do not assume it failed. For a request issued through
**Run commands**, use that dialog's **Retry original command** to reconcile its
existing reference and payload. For a toolbar error, refresh and check the
selected run's status before issuing another operation; the dialog does not
retain toolbar requests. If another tab changed the control generation, use
**Refresh controls** before submitting a new command. Closing or refreshing a
browser does not stop the worker.

## Shut down and restart the web service

For a normal complete shutdown:

1. Terminate any runs for which you do **not** want another checkpoint, then wait
   for their applied outcomes. Other active runs will be saved by shutdown.
2. In the terminal running `gui`, press **Ctrl+C once**. Browser tabs may stay open.
3. Wait for the service process to exit and the shell prompt to return.

The foreground service uses the same drain coordinator as the launcher. Accepted
commands and initialization settle before worker cleanup is considered complete.
Status remains available at `GET /api/shutdown`, including phase, elapsed time,
outstanding readers/exports/commands and per-run outcomes. The default shutdown
budget is 900 seconds; if incomplete, the service stays available for status and
another Ctrl+C retries the same mode. Repeated signals do not authorize killing
a simulation writer. “Shutting down” alone is not completion.

Restart with the same `gui --experiments-dir … --port …` command, then reopen the
browser. Resume a saved run with **Continue run**. Rebuilding frontend assets or
refreshing a tab does not reload Python modules in an already-running service;
restart the service after backend code changes.

To check which local process listens on the example port on Linux:

```bash
ss -ltnp 'sport = :8765'
```

No listener on that port confirms that the HTTP endpoint is closed. It does not
by itself prove that every simulation subprocess has exited. The worker check
below provides an additional check for managed runs.

### Check managed worker cleanup

Before stopping the service, this read-only query lists any registered run-worker
leases in the workspace:

```bash
python - <<'PY'
import sqlite3
from pathlib import Path

path = Path('/home/fmeng/workspace/zombie_game_simulation/runs/workspace/manager.sqlite')
with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as connection:
    rows = connection.execute('SELECT run_id,pid FROM worker_leases').fetchall()
for run_id, pid in rows:
    print(run_id, pid)
if not rows:
    print('No managed worker leases remain.')
PY
```

After normal worker cleanup, its lease is removed. For a remaining PID, inspect
its command and children before drawing conclusions:

```bash
SIM_WORKER_PID=12345  # Replace with the PID printed above.
ps -p "$SIM_WORKER_PID" -o pid,ppid,stat,etime,args
ps --ppid "$SIM_WORKER_PID" -o pid,ppid,stat,etime,args
```

A lease can be stale after a crash, and an operating-system PID can be reused.
Do not signal a PID merely because it appears in the lease table. This table
covers managed coordinators; it is not an inventory of independent CLI runs.

### Optional background web service

Foreground operation is easiest to inspect. If you need a background service,
use the prepared Python environment, keep a log and record the service PID:

```bash
mkdir -p runs/workspace
nohup python -m zombie_sim.cli gui \
  --experiments-dir /home/fmeng/workspace/zombie_game_simulation/runs/workspace \
  --host 127.0.0.1 --port 8765 \
  > runs/workspace/web-service.log 2>&1 &
printf '%s\n' "$!" > runs/workspace/web-service.pid
```

Do not run this in addition to the foreground service for the same workspace.
Read the log to confirm startup. To shut it down, first stop or terminate all
runs through the GUI/API as above, close browser tabs, then verify the recorded
PID still belongs to this service:

```bash
SIM_SERVER_PID=$(cat runs/workspace/web-service.pid)
ps -p "$SIM_SERVER_PID" -o pid,ppid,stat,etime,args
```

Only after that verification, request graceful service shutdown:

```bash
kill -TERM "$SIM_SERVER_PID"
```

Check the log, process exit and port closure. This is service shutdown, not a
replacement for the managed run's `terminate` command.

## Run directly from the command line

Headless runs need no web service, browser or GUI dependencies. With the terminal
prepared as above, validate and execute the small file:

```bash
python -m zombie_sim.cli validate configs/small.toml --preview
python -m zombie_sim.cli run configs/small.toml \
  --workers auto --backend memory --until 30 --output runs/cli-example
python -m zombie_sim.cli inspect runs/cli-example
```

Use a new output directory for each new run. `run` refuses to overwrite an
existing `run.sqlite`. At successful command exit it writes a checkpoint and
manifest and releases its resources. Output is normally printed as JSON at the
end, so a quiet terminal during advancement is not proof that execution stopped.

`--until 30` means **absolute simulated time 30 seconds**, not 30 wall-clock
seconds or 30 additional seconds. A run stopped below its horizon is reported as
`interrupted` and can continue unless extinction has already completed it.
Omitting `--until` advances to the configured horizon, unless all agents die
first. The engine does not advance beyond that horizon.

Continue the same run to its configured 120-second horizon:

```bash
python -m zombie_sim.cli resume runs/cli-example --until 120
python -m zombie_sim.cli inspect runs/cli-example
```

`resume` uses the latest committed world/runtime journal when available. Completed
runs are left complete. To start over, use `run` with a new output directory.
Use `resume` only for stopped/interrupted runs; see the terminated-status
limitation above.

For the full baseline:

```bash
python -m zombie_sim.cli validate configs/baseline.toml
python -m zombie_sim.cli run configs/baseline.toml \
  --workers auto --backend memory --output runs/baseline-example
```

This is a substantial workload, with 1,000 identities, 1,800 simulated seconds,
large histories and expensive checkpoints. Store it on a local disk with room
for history and checkpoint copies. Use the small scenario first. The measured
baseline did not sustain all-core utilization; automatic worker selection is a
hardware budget, not a guarantee of optimal throughput.

`--workers 4` is an example manual limit; `--backend sqlite` selects SQLite live
state. Both `memory` and `sqlite` write durable SQLite history. The `resume`
command has no `--workers` override. Inspect supported options with:

```bash
python -m zombie_sim.cli run --help
python -m zombie_sim.cli resume --help
```

### Stop a headless run from its terminal

Prefer a planned boundary with `--until` when practical. For an unplanned stop,
press **Ctrl+C once** and wait:

| Command being interrupted | Current behavior |
| --- | --- |
| `run` during advancement | Requests a stop at the next committed boundary, then saves its checkpoint/manifest and closes workers. |
| `resume` during advancement | Uses the same boundary-safe saving and cleanup path as `run`. |
| Initialization or checkpoint writing | Records the interrupt and finishes that operation before exiting safely; repeated Ctrl+C does not cut through saving or cleanup. |

Wait for the final output and shell prompt. Large initializations and checkpoints
can take time; an interrupt is a stop request, not an immediate exit. Storage or
validation failures are reported as errors, not successful saves. Preserve the
run directory and output when diagnosing such an error.

To request an interrupt from another terminal, send `kill -INT PID` to a
**verified headless coordinator PID**. This targets that process; terminal Ctrl+C
also reaches the process group, whose policy workers defer to the coordinator.
Do not target an arbitrary policy
worker. For a genuine pause with a later Continue button, or controlled
termination without another checkpoint, use a GUI/API-managed run instead of a
direct headless invocation.
**Ctrl+Z** is shell job suspension, not the simulator's Pause operation.

There are no native CLI `pause`, `stop`, `terminate`, `status` or `server-stop`
subcommands. `inspect` reads saved history; it is not a process-status command.
The next section shows how to control managed runs from a terminal.

## Control a GUI managed run from a terminal

The web service must be running. These Bash examples use `curl` and the prepared
Python environment, and preserve each command payload for exact retry.

First establish a local session cookie and list the runs:

```bash
SIM_URL=http://127.0.0.1:8765
SIM_COOKIE_JAR=$(mktemp /tmp/zombie-session.XXXXXX)
curl --fail-with-body --silent --show-error \
  --cookie-jar "$SIM_COOKIE_JAR" "$SIM_URL/api/runs" | python -m json.tool
```

### Create a managed run without opening the GUI

This optional example creates a **paused** run from `configs/small.toml`. Save
the creation request before submitting it so an uncertain response can be retried
without creating another run:

```bash
SIM_CREATE_REQUEST=$(python - <<'PY'
import json
from pathlib import Path
import tomllib
import uuid

payload = {'config': tomllib.loads(Path('configs/small.toml').read_text()),
           'command_id': str(uuid.uuid4()), 'start': False}
directory = Path('runs/control-requests')
directory.mkdir(parents=True, exist_ok=True)
path = directory / ('create-' + payload['command_id'] + '.json')
with path.open('x') as output:
    json.dump(payload, output, indent=2)
print(path.resolve())
PY
)
curl --fail-with-body --silent --show-error --cookie "$SIM_COOKIE_JAR" \
  --header 'Content-Type: application/json' \
  --data-binary "@$SIM_CREATE_REQUEST" "$SIM_URL/api/runs"
```

Copy `run_id` from the response and use the next procedure with
`SIM_OPERATION=continue` to start it. If creation loses its response, retry the
same creation POST against the same service with the same file; do not regenerate
the file. The saved `command_id` can also be queried at `/api/commands/<command_id>`.
Creating a paused run still initializes a worker, which must eventually be stopped
or terminated if you want to release it.

### Send and verify a run control command

Copy the intended run's `id`, then choose **one** operation. `continue` starts or
resumes a resumable managed run; `pause`, `stop` and `terminate` have the same
meaning as the GUI controls. Use a fresh request for each new operation.

```bash
SIM_RUN_ID=REPLACE_WITH_THE_RUN_ID
SIM_OPERATION=terminate  # Or pause, stop, continue, checkpoint.
SIM_RUNS_FILE=$(mktemp /tmp/zombie-runs.XXXXXX)
curl --fail-with-body --silent --show-error --cookie "$SIM_COOKIE_JAR" \
  "$SIM_URL/api/runs" --output "$SIM_RUNS_FILE"

SIM_REQUEST=$(python - "$SIM_RUNS_FILE" "$SIM_RUN_ID" "$SIM_OPERATION" "$SIM_URL" <<'PY'
import json
from pathlib import Path
import sys
import uuid

runs = json.loads(Path(sys.argv[1]).read_text())
run = next(item for item in runs if item['id'] == sys.argv[2])
command_id = str(uuid.uuid4())
payload = {'operation': sys.argv[3], 'command_id': command_id,
           'generation': run['generation']}
directory = Path('runs/control-requests')
directory.mkdir(parents=True, exist_ok=True)
path = directory / (command_id + '.json')
with path.open('x') as output:
    json.dump(payload, output, indent=2)
with path.with_suffix('.target.json').open('x') as output:
    json.dump({'service_url': sys.argv[4], 'run_id': run['id']}, output, indent=2)
print(path.resolve())
PY
)
```

Check that preparation succeeded and that the saved body targets your intended
operation. Then submit that body unchanged:

```bash
printf 'Target: %s/api/runs/%s/commands\n' "$SIM_URL" "$SIM_RUN_ID"
cat "$SIM_REQUEST"
curl --fail-with-body --silent --show-error --cookie "$SIM_COOKIE_JAR" \
  --header 'Content-Type: application/json' \
  --data-binary "@$SIM_REQUEST" \
  "$SIM_URL/api/runs/$SIM_RUN_ID/commands"
```

The response can be `pending`; that is not completion. Read the saved command
ID, then query its result until it is `applied` or `rejected`:

```bash
SIM_COMMAND_ID=$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["command_id"])' "$SIM_REQUEST")
curl --fail-with-body --silent --show-error --cookie "$SIM_COOKIE_JAR" \
  "$SIM_URL/api/commands/$SIM_COMMAND_ID" | python -m json.tool
```

Repeat the last GET while pending. An applied result includes the effective
time/revision and `run_status`. For stopping, look for `stopped`; for termination,
look for `terminated`. Then query `/api/runs` and check the selected run's
`resource_status`: `cleanup_complete` must be `true` and `worker_active` must be
`false` before treating cleanup as complete. An applied receipt alone does not
prove process exit.

If submission or polling loses its response, query the **same command ID** or
repeat the **same POST to the same service URL and run ID with the same saved
body**. The adjacent `.target.json` file records that target for a later terminal
session. Do not regenerate the payload for an uncertain retry. A rejected
stale-generation request is different: inspect
the current state, then prepare a new request if you still want that action.
After restarting the service, establish a fresh cookie with the first GET before
reusing a saved request. The service has no HTTP shutdown endpoint.

## Share runs between the CLI and GUI

To put a new headless run into the GUI workspace's normal directory layout,
omit `--output` and supply the global workspace option **before** `run`:

```bash
python -m zombie_sim.cli \
  --experiments-dir /home/fmeng/workspace/zombie_game_simulation/runs/workspace \
  run configs/small.toml --workers auto --until 30
```

The command prints the run ID and directory when it finishes. Refresh or restart
the GUI using that workspace to inspect the registered run. Direct CLI execution
is not a live managed worker that the GUI can pause or terminate while that CLI
command is running.

To continue a previously managed run through the CLI, first **Stop & save** in
the GUI and wait for its worker to exit. Then use its directory:

```bash
python -m zombie_sim.cli resume \
  runs/workspace/runs/REPLACE_WITH_THE_RUN_ID --until 120
```

An active coordinator owns a file lease, so CLI resume rejects simultaneous
ownership. A GUI pause alone does not release that lease. Never start two writers
for the same run or two web services for the same workspace.

## Preserve saved work and recover after an interruption

Keep the complete workspace directory. A managed workspace contains
`manager.sqlite` and `runs/<run-id>/`; each run retains `run.sqlite`, a manifest,
managed or portable checkpoints, model-pin files, and any exports. A custom
headless output directory contains the corresponding per-run files.

For a portable checkpoint, keep its JSON, adjacent `.history.sqlite` sidecar and
referenced `.models` files together with their relative names. A JSON export,
PNG or replay animation is not a continuation checkpoint. Do not remove SQLite
`-wal` or `-shm` files while a run/service is using the database. Shut down cleanly
before copying a complete workspace as an ordinary filesystem backup.

After a crash, preserve the journal and reopen the same workspace. New runs can
recover from the latest committed runtime boundary, which can be newer than the
last checkpoint. Recovery is not evidence that an interrupted checkpoint file is
complete. If recovery rejects a damaged bundle, preserve the original files and
the error rather than replacing history with an older file.

Force-killing a process is an emergency operating-system action, not **Terminate
without a new checkpoint**: it does not provide the application acknowledgement or mark the
run intentionally terminated, and it can leave subprocesses or incomplete
checkpoint files. Prefer managed control and graceful shutdown. If a process
cannot be stopped normally, identify the exact coordinator and descendants,
preserve the files, and treat the next start as crash recovery. Avoid broad
commands such as `pkill python`.

## Troubleshoot startup and shutdown

| Symptom | What to check |
| --- | --- |
| `No module named zombie_sim` or command not found | Activate the intended environment and set the source `PYTHONPATH` as shown, or install the package in that environment. |
| Missing FastAPI/Uvicorn/WebSocket dependency | Install the GUI extra with that environment's `python -m pip install -e '.[gui]'`. |
| Address already in use | Inspect the listener on the selected port. Reuse the intended existing service, or stop it correctly; choose a different port and directory for a separate workspace. |
| Browser connection refused | Confirm the service terminal is still running and the browser uses its actual host and port. |
| Existing runs are missing | Check the absolute `--experiments-dir`; a different directory is a different workspace. |
| Run stays initializing | Check service errors and placement settings. Dense exact sampling can be slow; do not launch duplicates to retry a pending creation. |
| Pause/terminate stays pending | Wait for current atomic work or a synchronous checkpoint; check the command result and service log. Browser disconnection does not cancel the request. |
| Run is paused but processes remain | This is expected. Use **Stop & save** or **Terminate without a new checkpoint** to release the worker. |
| Stale control generation | Refresh controls, especially after another tab/client acted. Retry uncertain requests with their original ID/body. |
| API says to establish a local session | Perform a fresh GET to obtain the service cookie, especially after a service restart. |
| CLI says there is an active coordinator | Stop/save the GUI-managed run and wait for exit before CLI resume. |
| Saved run is already complete | Create a new run, or use supported historical branching for a separate experiment; resume does not extend the original horizon. |
| GUI looks unchanged after code edits | Rebuild changed frontend assets when needed, restart the Python service, and reload the browser. |
| Shutdown reports incomplete | Inspect the reported phase and `.launcher/service.log`. Retry the same save/terminate mode, increasing `--timeout` if needed. Writer work and histories remain retained; do not start another service on the same workspace. |

### Rebuild the GUI only when needed

From the repository root, with Node/pnpm available:

```bash
cd gui
pnpm install --frozen-lockfile
pnpm run build
cd ..
```

The build checks TypeScript, bundles the viewer and copies it into the Python
package's static directory. Then restart the normal Python `gui` service.
`pnpm run dev` is a frontend-development command, not the complete simulation
service; no API proxy is configured for it in this checkout.

## Further reference

- [GUI features and controls](GUI.md)
- [History, checkpoint bundles and recovery](STORAGE.md)
- [Worker budgeting and measured scaling limits](PARALLEL.md)
- [Current validation results and remaining limitations](TESTING_REFINEMENT.md)

Command and shutdown behavior in this guide follows the current
[`cli.py`](../src/zombie_sim/cli.py), [`server.py`](../src/zombie_sim/server.py),
[`application.py`](../src/zombie_sim/application.py) and
[`main.tsx`](../gui/src/main.tsx). Check `python -m zombie_sim.cli --help` when
using a different installed version.
