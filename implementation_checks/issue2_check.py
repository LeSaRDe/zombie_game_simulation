"""I02 real-browser checks in a disposable local service and run workspace.

Fixture delays/errors exist only in this process. No user service or history is
opened. Run with PYTHONPATH=src .runtimeenv/bin/python implementation_checks/issue2_check.py.
"""
from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import HTTPCookieProcessor, Request, build_opener
from urllib.error import HTTPError
import uuid

ROOT = Path(__file__).resolve().parents[1]
NODE_MODULES = "/home/fmeng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"


def until(function, timeout=60, description="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError(f"Timed out waiting for {description}")


def fixture_worker(root, identity):
    from zombie_sim import application
    directory = Path(root) / "runs" / identity
    scenario = json.loads((directory / "manifest.json").read_text())["config"]["scenario"]
    if scenario == "issue2_initialization_failure":
        journal = application._journal(Path(root) / "manager.sqlite")
        with journal:
            journal.update_run(identity, status="failed", error="Fixture worker initialization failed before publishing a world")
        journal.close()
        return
    if scenario == "issue2_initialization_delay":
        (directory / "fixture-init-entered").touch()
        until(lambda: (directory / "fixture-init-release").exists(), timeout=75,
              description="test initialization release")
    application._run_worker(root, identity)


def serve(workspace, port):
    import uvicorn
    from fastapi import Body
    from zombie_sim import application
    from zombie_sim.server import create_app
    application._run_worker = fixture_worker
    app = create_app(workspace)
    manager = app.state.manager
    lock = threading.Lock()
    counters = {"state_at": 0, "snapshot_calls": 0, "http_views": 0}
    requests, gates, rules = [], {}, []
    original_snapshot = manager.snapshot
    original_state_at = application.History.state_at

    def state_at(history, *args, **kwargs):
        with lock:
            counters["state_at"] += 1
        return original_state_at(history, *args, **kwargs)

    def snapshot(identity, *args, cancel_event=None, **kwargs):
        gate = None
        with lock:
            counters["snapshot_calls"] += 1
            if cancel_event is not None:
                counters["http_views"] += 1
                for index, rule in enumerate(rules):
                    if rule["run_id"] == identity:
                        gate = rules.pop(index)
                        gate["entered"] = True
                        break
        if gate is not None:
            try:
                deadline = time.monotonic() + 45
                while gate["kind"] == "delay" and not gate["release"].is_set():
                    if cancel_event.is_set():
                        gate["cancel_observed"] = True
                        raise application.ViewCancelled("Fixture observed HTTP viewer cancellation")
                    if time.monotonic() > deadline:
                        raise RuntimeError("Fixture reader gate was not released")
                    time.sleep(.01)
                if cancel_event.is_set():
                    gate["cancel_observed"] = True
                    raise application.ViewCancelled("Fixture observed HTTP viewer cancellation")
                if gate["kind"] == "error":
                    raise ValueError(f"Fixture history failure: {gate['name']}")
                return original_snapshot(identity, *args, cancel_event=cancel_event, **kwargs)
            finally:
                gate["finished"] = True
        return original_snapshot(identity, *args, cancel_event=cancel_event, **kwargs)

    application.History.state_at = state_at
    manager.snapshot = snapshot
    # This browser fixture controls response timing/errors to test the view
    # controller. Production process cancellation is separately exercised by
    # process_http_cancellation_check.py for all five HTTP read operations.
    original_reader_call = app.state.readers.call
    def controlled_read(operation, *args, cancel_event=None, **kwargs):
        if operation == "snapshot":
            return manager.snapshot(*args, cancel_event=cancel_event, **kwargs)
        return original_reader_call(operation, *args, cancel_event=cancel_event, **kwargs)
    app.state.readers.call = controlled_read

    class TraceRequests:
        """Count requests without altering ASGI receive/disconnect behavior."""
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"].startswith("/api/"):
                with lock:
                    requests.append({"method": scope["method"], "path": scope["path"]})
            await self.app(scope, receive, send)

    app.add_middleware(TraceRequests)

    @app.get("/__issue2/diagnostics")
    def diagnostics():
        with lock:
            return {"pid": os.getpid(), "counters": dict(counters),
                    "cache": manager.snapshot_diagnostics(), "requests": list(requests),
                    "gates": {name: {key: value for key, value in gate.items() if key != "release"}
                              for name, gate in gates.items()}}

    @app.post("/__issue2/gate")
    def arm(body: dict = Body(...)):
        assert body["kind"] in {"delay", "error"}
        gate = {**body, "release": threading.Event(), "entered": False,
                "finished": False, "cancel_observed": False}
        with lock:
            assert body["name"] not in gates
            gates[body["name"]] = gate
            rules.append(gate)
        return {"armed": body["name"]}

    @app.get("/__issue2/gate/{name}/release")
    def release(name: str):
        gates[name]["release"].set()
        return {"released": name}

    @app.get("/__issue2/initialization/{identity}/release")
    def release_initialization(identity: str):
        (Path(manager._row(identity)["directory"]) / "fixture-init-release").touch()
        return {"released": identity}

    @app.get("/__issue2/initialization/{identity}/state")
    def initialization_state(identity: str):
        row = manager._row(identity)
        directory = Path(row["directory"])
        return {"status": row["status"], "entered": (directory / "fixture-init-entered").exists(),
                "released": (directory / "fixture-init-release").exists(),
                "history_exists": (directory / "run.sqlite").exists()}

    @app.get("/__issue2/audit")
    def audit():
        result = []
        for row in manager.list_runs():
            path = Path(row["directory"]) / "run.sqlite"
            frontier = None
            if path.exists():
                with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as database:
                    frontier = database.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
            with manager.lock:
                command_count = manager.catalog.command_count(row["id"])
            result.append({"id": row["id"], "status": row["status"], "generation": row["generation"],
                           "frontier": frontier, "commands": command_count,
                           "history_bytes": path.stat().st_size if path.exists() else 0})
        return result

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


class Api:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, path, body=None):
        request = Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=150) as response:
                return json.load(response)
        except HTTPError as error:
            error.response_body = error.read().decode()
            error.add_note(f"{path}: {error.response_body}")
            raise

    def row(self, identity):
        return next(row for row in self.call("/api/runs") if row["id"] == identity)

    def command(self, identity, operation, **extra):
        result = self.call(f"/api/runs/{identity}/commands", {"command_id": str(uuid.uuid4()), "operation": operation, **extra})
        receipt = until(lambda: (row if (row := self.call(f'/api/commands/{result["command_id"]}'))["status"] != "pending" else None),
                        timeout=120, description=f"{operation} acknowledgement")
        assert receipt["status"] == "applied", receipt
        return receipt


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zombie-issue2-") as workspace:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NODE_PATH=NODE_MODULES,
                   PYTHONDONTWRITEBYTECODE="1")
        with (output / "service.log").open("w") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace, "--port", str(port)],
                                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            api = Api(port)
            report = {"passed": False, "workspace": workspace, "port": port, "service_pid": process.pid}

            def browser(phase, identities=None):
                args = [str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue2.cjs"),
                        api.base, str(output), phase, json.dumps(identities or {})]
                result = subprocess.run(args, cwd=ROOT, env=env, text=True, capture_output=True, timeout=200)
                (output / f"browser-{phase}.log").write_text(result.stdout + result.stderr)
                assert result.returncode == 0, result.stdout + result.stderr
                return json.loads((output / f"browser-{phase}.json").read_text())

            try:
                def ready():
                    if process.poll() is not None:
                        raise AssertionError("Fixture service exited; inspect service.log")
                    try:
                        return api.call("/__issue2/diagnostics")
                    except OSError:
                        return None
                until(ready, description="isolated service")
                report["empty_workspace"] = browser("empty")
                small = {"scenario": "issue2_tiny_a", "seed": 21, "horizon": 120,
                         "population": {"humans": 16, "zombies": 4}, "execution": {"workers": 1},
                         "checkpoint_interval": 1000}
                identities = {}
                from zombie_sim.config import baseline_config
                full = baseline_config()
                full.update(scenario="issue2_baseline_1000", horizon=120, checkpoint_interval=1000)
                full["execution"] = {"workers": 2}
                configurations = {"tiny_a": small, "tiny_b": dict(small, scenario="issue2_tiny_b", seed=22),
                                  "baseline": full, "active": dict(small, scenario="issue2_active", seed=23)}
                for key, config in configurations.items():
                    identity = api.call("/api/runs", {"config": config, "command_id": str(uuid.uuid4())})["run_id"]
                    identities[key] = identity
                    until(lambda: api.row(identity)["status"] == "paused", timeout=150, description=f"{key} initialization")
                    api.command(identity, "step")
                    if key != "active":
                        api.command(identity, "terminate")
                        until(lambda: api.row(identity)["resource_status"]["cleanup_complete"], description="terminal cleanup")
                try:
                    api.call("/api/runs", {"config": dict(small, scenario="issue2_initialization_failure"), "command_id": str(uuid.uuid4())})
                except HTTPError as error:
                    # The synchronous create endpoint can report the intended
                    # worker failure after reserving its durable run identity.
                    assert error.code == 422 and "Fixture worker initialization failed" in error.response_body
                failed = next(row["id"] for row in api.call("/api/runs")
                              if row["config"]["scenario"] == "issue2_initialization_failure")
                identities["failed"] = failed
                until(lambda: api.row(failed)["status"] == "failed", description="failed initialization fixture")
                report["prepared"] = api.call("/__issue2/audit")
                report["populated_workspace"] = browser("populated", identities)
                report["final_audit"] = api.call("/__issue2/audit")
                report["diagnostics"] = api.call("/__issue2/diagnostics")
                report["passed"] = True
            finally:
                (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
                for directory in (Path(workspace) / "runs").glob("*"):
                    (directory / "fixture-init-release").touch()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=45)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
    print(json.dumps({"passed": report["passed"], "report": str(output / "verification.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve")
    parser.add_argument("--port", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue2")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        check(args.output.absolute())
