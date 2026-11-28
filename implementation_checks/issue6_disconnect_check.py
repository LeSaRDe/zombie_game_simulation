"""Verify metrics cancellation with a real HTTP disconnect and private readers.

The bounded sampler gate exists only in this disposable verification service.
Production routes, HTTP middleware, disconnect handling and history cleanup are
used unchanged. No user service or existing run is opened.
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from issue2_check import Api, until
from issue6_metrics_check import digest


def serve(workspace, port):
    import uvicorn
    from fastapi import Body
    from zombie_sim import server

    app = server.create_app(workspace)
    manager = app.state.manager
    original_sampler = server.sampled_metrics
    lock = threading.Lock()
    rules, gates, readers = [], {}, []
    active = 0

    def sampled(history, *args, check_cancelled=None, **kwargs):
        nonlocal active
        assert callable(check_cancelled), "Production metrics route omitted its cancellation callback"
        with lock:
            gate = rules.pop(0) if rules else None
            record = {"name": gate["name"] if gate else "ungated", "entered": True,
                      "finished": False, "closed": False, "thread": threading.get_ident()}
            readers.append(record)
            active += 1
            if gate is not None:
                gate["entered"] = True
        original_close = history.close

        def close():
            original_close()
            try:
                history.connection.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                with lock:
                    record["closed"] = True
            else:
                raise AssertionError("Private metrics history remained open after close")

        history.close = close
        try:
            if gate is not None:
                deadline = time.monotonic() + 30
                while not gate["release"].is_set():
                    try:
                        check_cancelled()
                    except server.ViewCancelled:
                        with lock:
                            gate["cancel_observed"] = True
                        raise
                    if time.monotonic() > deadline:
                        raise AssertionError("Disposable metrics gate was not released")
                    time.sleep(.01)
            check_cancelled()
            return original_sampler(history, *args, check_cancelled=check_cancelled, **kwargs)
        finally:
            with lock:
                record["finished"] = True
                if gate is not None:
                    gate["finished"] = True
                active -= 1

    server.sampled_metrics = sampled

    @app.get("/__issue6/diagnostics")
    def diagnostics():
        with lock:
            return {"active_samplers": active, "readers": [dict(reader) for reader in readers],
                    "gates": {name: {key: value for key, value in gate.items() if key != "release"}
                              for name, gate in gates.items()}}

    @app.post("/__issue6/gate")
    def arm(body: dict = Body(...)):
        gate = {"name": body["name"], "release": threading.Event(), "entered": False,
                "finished": False, "cancel_observed": False}
        with lock:
            assert gate["name"] not in gates
            gates[gate["name"]] = gate
            rules.append(gate)
        return {"armed": gate["name"]}

    @app.get("/__issue6/gate/{name}/release")
    def release(name: str):
        gates[name]["release"].set()
        return {"released": name}

    @app.get("/__issue6/audit/{identity}")
    def audit(identity: str):
        history = manager.history(identity)
        try:
            row = manager._row(identity)
            with manager.lock:
                commands = manager.catalog.command_count(identity)
            return {"ledger_sha256": digest(history), "revision": history.revision,
                    "status": row["status"], "generation": row["generation"], "commands": commands}
        finally:
            history.close()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="zombie-issue6-disconnect-") as workspace:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"))
        with (output / "service.log").open("w") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace,
                                        "--port", str(port)], cwd=ROOT, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            api = Api(port)
            connections = []
            try:
                def ready():
                    if process.poll() is not None:
                        raise AssertionError("Disposable metrics service exited; inspect service.log")
                    try:
                        return api.call("/__issue6/diagnostics")
                    except OSError:
                        return None
                until(ready, timeout=10, description="disposable metrics service")
                identity = api.call("/api/runs", {"config": {"scenario": "issue6_disconnect", "horizon": 20,
                    "population": {"humans": 2, "zombies": 1}, "execution": {"workers": 1}},
                    "command_id": "issue6-disconnect-run"})["run_id"]
                api.command(identity, "terminate")
                until(lambda: api.row(identity)["resource_status"]["cleanup_complete"], description="fixture worker exit")
                before = api.call(f"/__issue6/audit/{identity}")

                def begin(name):
                    api.call("/__issue6/gate", {"name": name})
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    connections.append(connection)
                    connection.request("GET", f"/api/runs/{identity}/metrics")
                    until(lambda: api.call("/__issue6/diagnostics")["gates"][name]["entered"],
                          timeout=3, description=f"{name} private sampler")
                    return connection

                obsolete = begin("obsolete")
                independent = begin("independent")
                started = time.monotonic()
                obsolete.sock.shutdown(socket.SHUT_RDWR)
                obsolete.close()
                def obsolete_finished():
                    diagnostics = api.call("/__issue6/diagnostics")
                    gate = diagnostics["gates"]["obsolete"]
                    reader = next(item for item in diagnostics["readers"] if item["name"] == "obsolete")
                    return gate["cancel_observed"] and gate["finished"] and reader["closed"]
                until(obsolete_finished, timeout=3, description="HTTP metrics cancellation and private connection close")
                elapsed = time.monotonic() - started
                gate = api.call("/__issue6/diagnostics")["gates"]["independent"]
                assert not gate["cancel_observed"] and not gate["finished"], gate
                api.call("/__issue6/gate/independent/release")
                response = independent.getresponse()
                assert response.status == 200, response.status
                bundle = json.loads(response.read())
                retry = api.call(f"/api/runs/{identity}/metrics")
                assert bundle == retry and bundle["samples"], (bundle, retry)
                def idle():
                    diagnostics = api.call("/__issue6/diagnostics")
                    return diagnostics if diagnostics["active_samplers"] == 0 and all(
                        reader["finished"] and reader["closed"] for reader in diagnostics["readers"]) else None
                diagnostics = until(idle, timeout=3, description="all sampler work finished and private readers closed")
                after = api.call(f"/__issue6/audit/{identity}")
                assert before == after, (before, after)
                report = {"production_http_middleware": True, "actual_http_disconnect": True,
                          "cancellation_seconds": elapsed, "private_connection_closed": True,
                          "independent_reader_succeeded": True, "retry_succeeded": True,
                          "no_inflight_sampler_work": True, "readers": diagnostics["readers"],
                          "source_audit_unchanged": True, "source_audit": after}
            finally:
                for connection in connections:
                    connection.close()
                for name in ("obsolete", "independent"):
                    try:
                        api.call(f"/__issue6/gate/{name}/release")
                    except Exception:
                        pass
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
    report["workspace_removed"] = not Path(workspace).exists()
    report["service_exited"] = process.poll() is not None
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve")
    parser.add_argument("--port", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue6-disconnect")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        report = {"passed": False}
        try:
            report.update(check(args.output))
            report["passed"] = True
        finally:
            (args.output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
