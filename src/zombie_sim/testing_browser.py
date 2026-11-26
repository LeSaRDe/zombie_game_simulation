"""Acceptance binding to a real HTTP service, managed coordinators and browsers.

All browser captures come from the React projection that was actually committed.
Fixture preparation uses the same durable command service as other research tools.
"""
from __future__ import annotations
from copy import deepcopy
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid

from .storage import canonical


def execute_browser(adapter, request):
    import uvicorn
    from .server import create_app
    from .testing import fixture_config, normalize_intent, normalize_snapshot, occurrence_aliases, request_numbers, _wire
    from .testing_workflows import _capture, _semantic
    from .engine import Simulation
    from .runtime import restore_revision
    artifacts = Path("artifacts/browser_acceptance").absolute() / uuid.uuid4().hex
    artifacts.mkdir(parents=True, exist_ok=True)
    app = create_app(adapter.workdir / "managed")
    manager = app.state.manager
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0)); listener.listen()
    url = f"http://127.0.0.1:{listener.getsockname()[1]}"
    isolated_server=None
    if any(step["op"]=="server.recover" for step in request["steps"]):
        from .testing_server import IsolatedServer
        isolated_server=IsolatedServer(adapter.workdir/"managed",listener)
        server=thread=None
    else:
        server = uvicorn.Server(uvicorn.Config(app, log_level="error", timeout_graceful_shutdown=2))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        until = time.monotonic() + 10
        while not server.started:
            if time.monotonic() > until: raise RuntimeError("Browser acceptance service did not start")
            time.sleep(.01)
    node = shutil.which("node") or str(Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
    environment = dict(os.environ)
    environment.setdefault("NODE_PATH", str(Path.home()/".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"))
    driver_path = Path(__file__).resolve().parents[2]/"gui/browser_driver.cjs"
    stderr = (artifacts/"browser-stderr.log").open("w")
    driver = subprocess.Popen([node, str(driver_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=stderr, text=True, env=environment)
    captures = {}; runs = {}; paths = {}; specs = request.get("setup", {}).get("runs", {}); diagnostics = {}
    browser_open = False
    import platform
    from .hardware import available_resources
    diagnostics["environment"]={"os":platform.platform(),"python":sys.version,"hardware":available_resources(),"adapter":"zombie_sim.testing_browser/v1"}

    def browser(operation, **fields):
        driver.stdin.write(canonical({"op": operation, **fields}) + "\n"); driver.stdin.flush()
        if not select.select([driver.stdout], [], [], 120 if operation=="benchmark" else 60)[0]: raise TimeoutError(f"Actual browser timed out: {operation}")
        line = driver.stdout.readline()
        if not line: raise RuntimeError(f"Browser driver exited during {operation}; see {artifacts/'browser-stderr.log'}")
        response = json.loads(line)
        diagnostics["interactions"] = response.get("log", [])
        if not response["ok"]: raise RuntimeError(response["error"])
        return response["result"]

    def await_run(name, status=None):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            row = dict(manager._row(runs[name]))
            if row["status"] == "failed": raise RuntimeError(row["error"])
            if row["status"] != "initializing" and (status is None or row["status"].upper() == status): return row
            time.sleep(.025)
        raise TimeoutError(f"Run {name} did not reach {status or 'initialization'}")

    restored_captures = {}

    def restored(name):
        await_run(name)
        history = manager.history(runs[name])
        try: revision = history.revision
        finally: history.close()
        cached = restored_captures.get(name)
        if cached is not None and cached[0] == revision:
            return cached[1]
        if cached is not None: cached[1].close()
        sim = restore_revision(Simulation, paths[name], revision=revision, workers=1)
        restored_captures[name] = (revision, sim)
        return sim

    def release_restored(sim):
        # Detached captures remain immutable and open for repeated queries at
        # the same durable revision. The cache owns their eventual close.
        if not any(cached is sim for _, cached in restored_captures.values()):
            sim.close()

    def numeric_wire(value):
        # JSON numbers lose Python int/float representation in JavaScript.
        # Normalize integral floats on both sides without changing quantities.
        if isinstance(value,dict): return {key:numeric_wire(item) for key,item in value.items()}
        if isinstance(value,list): return [numeric_wire(item) for item in value]
        if isinstance(value,float) and value.is_integer(): return int(value)
        return value

    def run_capture(name, what, step):
        sim = restored(name)
        try:
            if what in {"semantic_snapshot", "initial_snapshot", "durable_snapshot"}:
                raw = sim.history.state_at(revision=0 if what == "initial_snapshot" else None)
                from .visualization import project_state
                return _semantic(sim, normalize_snapshot(numeric_wire(project_state(raw)), occurrence_aliases(sim)))
            if what == "initial_random_draws": return _wire(sim.history.state_at(revision=0).get("initialization", {}).get("random_draws", []))
            if what == "timeline_records": return _wire(numeric_wire(manager.timeline(runs[name], agent=step.get("agent"))), occurrence_aliases(sim))
            return _capture(sim, what)
        finally: release_restored(sim)

    def capture_browser(raw, what):
        state = raw["app"]; view = state.get("view")
        name = next((name for name, identity in runs.items() if identity == state["run_id"]), None)
        aliases = {};semantic_sim=None
        if name:
            sim = restored(name)
            try:
                from types import SimpleNamespace
                semantic_sim=SimpleNamespace(events=list(sim.events));aliases = occurrence_aliases(sim)
            finally: release_restored(sim)
        if what == "cohorts":
            return {**{item["definition"]["name"]: _wire(item) for item in state["cohorts"]}, "overlap_label": raw.get("cohort_overlap_label")}
        if what == "control": return {"run_state": state["run"]["status"].upper(), "generation": state["run"]["generation"]}
        if what == "command":
            command = (raw.get("recovery_command") or {}).get("receipt") or state.get("command") or {}
            return {**command, "status": command.get("status", "").upper(), "effective_revision": command.get("revision"), "code": "STALE_CONTROL_GENERATION" if "Stale control generation" in command.get("error", "") else command.get("code")}
        if what == "selected_event":
            event = state["selected_event"]
            return {**event, "type": event["kind"].upper(), "revision_before": str(max(0, int(event["ledger_revision"])-1)), "revision_after": str(event["ledger_revision"])}
        if what == "timeline": return _wire({"records": state["shownEvents"], "occurrences": state.get("timeline_occurrences", {})}, aliases)
        if what == "projection": return normalize_snapshot(view["state"], aliases)
        if what == "validation":
            config=raw["configuration"];issues=config["issues"];aliases={"population.humans":"human_count","population.human_roles.TYRANT":"human_roles.TYRANT"}
            return {"fields":{aliases.get(issue["path"],issue["path"]):issue for issue in issues},"summary_codes":[issue["code"] for issue in issues],"start_control":{"disabled":config["start_disabled"]}}
        if what in {"preview", "preview_scene"}:
            config=raw["configuration"];scene=normalize_snapshot(config["preview"]["state"])
            scene.update(artifact_id=config["artifact_id"],legend={"categories":raw.get("legend_tokens",[]),"non_color_tokens":raw.get("legend_tokens",[])})
            return scene
        cursor = {"run_id": state["run_id"], "time": view["time"], "revision": view["revision"]} if view else {"run_id": state["run_id"], "time":state["observation"]["time"], "revision":str(state["observation"]["revision"])}
        if view:
            scene = normalize_snapshot(view["state"], aliases)
            if semantic_sim is not None: scene = _semantic(semantic_sim,scene)
            inspector = scene["agents"].get(state["selected"])
        else:
            observed = state["observation"]["observation"]
            scene = {"agents": {observed["self_state"]["id"]:observed["self_state"],**observed.get("local_agents", {})}, **observed.get("local_environment", {})}
            inspector = observed.get("self_state")
        scene["living_agents"] = {key:value for key,value in scene["agents"].items() if value.get("status") != "DEAD"}
        scene["glyph_semantics"] = raw.get("glyph_semantics")
        metrics_cursor = state.get("metrics_cursor")
        statistics = {"cursor": {key:metrics_cursor[key] for key in ("run_id","time","revision")} if metrics_cursor else None,
                      "populations": {key:value for key,value in (metrics_cursor or {}).get("populations", {}).items() if key in {"healthy","infected","zombies","dead","total"}},
                      "watermark": metrics_cursor,
                      "lag_label": raw.get("statistics_watermark_label", "")}
        return {"mode": state["mode"].upper(), "perspective": "AGENT_OBSERVATION" if state["perspective"] == "agent" else "RESEARCHER",
                "selected_agent": state["selected"], "follow_agent": state["selected"] if state["follow"] else None,
                "scene": scene, "world": {"cursor":cursor}, "inspector": {"agent":inspector,"cursor":cursor},
                "statistics": statistics, "observation": (state.get("observation") or {}).get("observation"),
                "privileged_cache_keys": state["privileged_cache_keys"]}

    try:
        for index, step in enumerate(request["steps"]):
            step_started = time.monotonic()
            with (artifacts/"workflow-progress.jsonl").open("a") as progress:
                progress.write(canonical({"index":index,"operation":step["op"],"run":step.get("run"),"phase":"started","wall_time":time.time()})+"\n")
            operation = step["op"]; name = step.get("run"); result = None
            if operation == "run.create":
                spec = specs[name]
                created = manager.create(fixture_config(spec["world"], spec.get("config")), start=False)
                runs[name] = created["run_id"]; paths[name] = Path(manager._row(runs[name])["directory"])/"run.sqlite"
                result = await_run(name)
            elif operation == "run.script":
                for offset, item in enumerate(step["steps"]):
                    item = deepcopy(item)
                    if item["op"] == "submit": item = {"op": "submit", "intent": normalize_intent(item.get("intent", {key:value for key,value in item.items() if key != "op"}))}
                    if item["op"] == "submit_batch": item["intents"] = [normalize_intent(intent) for intent in item["intents"]]
                    result = manager.command(runs[name], "script", {"step":item, "draws": step.get("draws", []), "command_id": f"script-{index}-{offset}"})
                    if result["status"] != "applied": raise RuntimeError(canonical(result))
                    if browser_open: time.sleep(.12)
            elif operation == "run.restart": result=manager.restart_checkpoint(runs[name],step["checkpoint"])
            elif operation == "run.capture": result = run_capture(name, step.get("what", "semantic_snapshot"), step)
            elif operation == "run.await": result = await_run(name, step["state"])
            elif operation == "cli.run":
                from .testing_workflows import resolved_config
                draft=resolved_config(step["draft"])["resolved"];path=adapter.workdir/f"cli-{index}.json";path.write_text(canonical(draft))
                directory=manager.root/"runs"/f"cli-{uuid.uuid4().hex}"
                completed=subprocess.run([sys.executable,"-m","zombie_sim.cli","run",str(path),"--output",str(directory)],capture_output=True,text=True,timeout=45)
                (artifacts/f"cli-{index}.log").write_text(completed.stdout+completed.stderr)
                if completed.returncode:raise RuntimeError(completed.stderr)
                manifest=json.loads((directory/"manifest.json").read_text());identity=manifest["run_id"];runs[step["bind_run"]]=identity;paths[step["bind_run"]]=directory/"run.sqlite"
                with manager.lock,manager.connection:
                    manager.connection.execute("INSERT OR IGNORE INTO runs(id,directory,config,status,frontier) VALUES(?,?,?,?,?)",(identity,str(directory),canonical(manifest["config"]),"completed",canonical({})))
                result={"exit_code":completed.returncode,"stdout":completed.stdout}
            elif operation == "fault.arm" and step["point"]=="export_before_encode":
                app.state.exports.arm_pause(runs[name]);result={"point":step["point"]}
            elif operation == "export.read_artifact":
                from .testing_browser_exports import read_artifact
                result=read_artifact(captures[step["artifact_from"]],runs)
            elif operation == "runs.list": result = manager.list_runs()
            elif operation == "measurement.query":
                from .visualization import populations
                result = populations(manager.snapshot(runs[name], step["time"])["state"])
            elif operation == "observation.read":
                sim = restored(name)
                try: result = numeric_wire([item for item in sim.decisions if str(item.get("agent", item.get("actor"))) == step["agent"]][step["decision_index"]]["observation"])
                finally: release_restored(sim)
            elif operation.startswith("browser."):
                action = operation.split(".",1)[1]
                if action == "release_export":
                    for identity in runs.values(): app.state.exports.release(identity)
                elif action == "benchmark":
                    result=browser(action,artifacts=str(artifacts),**{key:value for key,value in step.items() if key not in {"op","label"}})
                    (artifacts/"benchmark.json").write_text(canonical(result))
                elif action == "export_form": result=browser(action,**{key:value for key,value in step.items() if key not in {"op","label"}})
                elif action == "await_export": result=browser(action,artifacts=str(artifacts),**{key:value for key,value in step.items() if key not in {"op","label"}})
                elif action == "export_import_config":result=browser(action,format=step["format"],path=str(artifacts/f"draft-{index}.{step['format']}"))
                elif action == "capture" and step.get("what")=="accessibility": result=browser("accessibility")
                elif action == "capture" and step.get("what")=="export_job": result=browser("export_job")
                elif action == "open":
                    diagnostics["browser"] = browser("open", url=url, artifacts=str(artifacts), run_id=runs.get(name), **{key:value for key,value in step.items() if key in {"engine","viewport","reduced_motion"}})
                    browser_open = True
                elif action == "capture":
                    current=browser("peek");expected=None
                    if current["run_id"] and current["mode"]=="live" and current["perspective"]=="researcher": expected=json.loads(manager._row(current["run_id"])["frontier"]).get("revision")
                    raw = browser("capture", path=str(artifacts/f"{index}-{step['label']}.png"),what=step.get("what"),expected_revision=expected)
                    (artifacts/f"{index}-{step['label']}.json").write_text(canonical(raw))
                    result = capture_browser(raw, step.get("what"))
                elif action == "select_run": result = browser(action, run_id=runs[name])
                elif action in {"sync", "await_view"}:
                    identity = browser("capture", path=str(artifacts/f"{index}-sync.png"))["app"]["run_id"]
                    row = manager._row(identity); result = browser(action, revision=json.loads(row["frontier"]).get("revision"))
                elif action == "import_config":
                    path = artifacts/f"draft-{index}.json";path.write_text(canonical(request_numbers(step["draft"])))
                    result = browser(action, path=str(path))
                elif action == "capture_transport":
                    result = browser(action); trace = result["application_trace"]
                    result["applied_revision_regressions"] = sum(int(b["revision"]) < int(a["revision"]) for a,b in zip(trace,trace[1:]) if a["run_id"] == b["run_id"] and a["mode"] == b["mode"] == "live")
                else:
                    result = browser(action, **{key:value for key,value in step.items() if key not in {"op","label"}})
                    if step.get("bind_run"):
                        identity = result["app"]["run_id"]; runs[step["bind_run"]] = identity
                        paths[step["bind_run"]] = Path(manager._row(identity)["directory"])/"run.sqlite"
            elif operation=="fault.arm" and step["point"]=="command_after_effect_before_ack":
                if isolated_server is None:raise RuntimeError("Command crash requires an isolated server process")
                result=isolated_server.arm(step["point"],step.get("occurrence",1))
            elif operation=="server.recover":
                result=isolated_server.recover()
                diagnostics.setdefault("server_recoveries",[]).append(result)
                trace=adapter.workdir/"managed"/"server-faults.jsonl"
                if trace.exists():shutil.copyfile(trace,artifacts/"server-faults.jsonl")
            elif operation=="commands.inspect":
                from .command_recovery import inspect_command
                result=inspect_command(manager,step["command_id"])
            else: raise NotImplementedError(f"Browser workflow operation is not yet bound: {operation}")
            if "label" in step: captures[step["label"]] = result
            with (artifacts/"workflow-progress.jsonl").open("a") as progress:
                progress.write(canonical({"index":index,"operation":operation,"run":name,"phase":"completed","elapsed_seconds":time.monotonic()-step_started,"wall_time":time.time()})+"\n")
        return {"captures":captures,"diagnostics":diagnostics,"artifact_directory":str(artifacts)}
    finally:
        for _, captured_sim in restored_captures.values(): captured_sim.close()
        restored_captures.clear()
        if driver.poll() is None:
            try: browser("close", trace_path=str(artifacts/"trace.zip"))
            except Exception: pass
        driver.terminate()
        try: driver.wait(timeout=10)
        except subprocess.TimeoutExpired: driver.kill();driver.wait()
        stderr.close()
        if isolated_server:
            isolated_server.close()
            # A killed HTTP process may leave healthy managed workers. Settle
            # every worker belonging to this isolated fixture workspace.
            for row in manager.list_runs():
                if row["status"] not in {"stopped","terminated","completed","failed"}:
                    manager.command(row["id"],"stop")
            manager.close()
        else:
            server.should_exit=True;thread.join(timeout=15)
        listener.close()
