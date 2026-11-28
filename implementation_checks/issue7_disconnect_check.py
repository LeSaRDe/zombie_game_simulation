"""Verify abandoned cohort aggregation stops after an actual HTTP disconnect.

Gates and diagnostics exist only in this disposable service. Production HTTP
middleware, routes and cancellation callbacks run unchanged. Snapshot readers
normally close before the aggregation gate; their closure is observed separately
and is not attributed to aggregation cancellation. A cached metadata connection
is warmed before private-reader tracking and is released on service shutdown.
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
    from zombie_sim import application, server

    app = server.create_app(workspace)
    manager = app.state.manager
    original_summary = application.cohort_summary
    original_history = manager.history
    lock = threading.Lock()
    rules, gates, aggregations, readers = [], {}, [], []
    active = 0
    tracking = False

    def history(identity):
        result = original_history(identity)
        with lock:
            if not tracking:
                return result
            record = {"closed": False, "thread": threading.get_ident()}
            readers.append(record)
        original_close = result.close

        def close():
            original_close()
            try:
                result.connection.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                with lock:
                    record["closed"] = True
            else:
                raise AssertionError("Tracked private cohort history remained open after close")

        result.close = close
        return result

    def summary(state, definition, *, check_cancelled=None):
        nonlocal active
        assert callable(check_cancelled), "Production cohort request omitted its cancellation callback"
        with lock:
            gate = rules.pop(0) if rules else None
            record = {"name": gate["name"] if gate else "ungated", "entered": True,
                      "finished": False, "thread": threading.get_ident()}
            aggregations.append(record)
            active += 1
            if gate is not None:
                gate["entered"] = True
                gate["private_readers_closed_at_entry"] = all(item["closed"] for item in readers)
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
                        raise AssertionError("Disposable cohort gate was not released")
                    time.sleep(.01)
            check_cancelled()
            return original_summary(state, definition, check_cancelled=check_cancelled)
        finally:
            with lock:
                record["finished"] = True
                if gate is not None:
                    gate["finished"] = True
                active -= 1

    manager.history = history
    application.cohort_summary = summary

    @app.get("/__issue7/diagnostics")
    def diagnostics():
        with lock:
            result = {"active_aggregations": active, "aggregations": [dict(item) for item in aggregations],
                      "private_readers": [dict(item) for item in readers],
                      "gates": {name: {key: value for key, value in gate.items() if key != "release"}
                                for name, gate in gates.items()}}
        result["metadata_readers"] = manager.head_diagnostics()
        return result

    @app.post("/__issue7/track")
    def track():
        nonlocal tracking
        # Creation at a reference cursor has already warmed the one cached
        # metadata connection. Later manager.history calls are private readers.
        assert manager.head_diagnostics()["active_connections"] == 1
        with lock:
            tracking = True
        return {"private_reader_tracking": True, "cached_metadata_readers": 1}

    @app.post("/__issue7/gate")
    def arm(body: dict = Body(...)):
        gate = {"name": body["name"], "release": threading.Event(), "entered": False,
                "finished": False, "cancel_observed": False}
        with lock:
            assert gate["name"] not in gates
            gates[gate["name"]] = gate
            rules.append(gate)
        return {"armed": gate["name"]}

    @app.get("/__issue7/gate/{name}/release")
    def release(name: str):
        gates[name]["release"].set()
        return {"released": name}

    @app.get("/__issue7/audit/{identity}")
    def audit(identity: str):
        reader = manager.history(identity)
        try:
            row = manager._row(identity)
            with manager.lock:
                commands = manager.catalog.command_count(identity)
                definitions = [list(item) for item in manager.catalog.view_rows(identity)]
            return {"ledger_sha256": digest(reader), "revision": reader.revision,
                    "status": row["status"], "generation": row["generation"],
                    "commands": commands, "definitions": definitions}
        finally:
            reader.close()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="zombie-issue7-disconnect-") as workspace:
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
                        raise AssertionError("Disposable cohort service exited; inspect service.log")
                    try:
                        return api.call("/__issue7/diagnostics")
                    except OSError:
                        return None
                until(ready, timeout=10, description="disposable cohort service")
                identity = api.call("/api/runs", {"config": {"scenario": "issue7_disconnect", "horizon": 20,
                    "population": {"humans": 2, "zombies": 1}, "execution": {"workers": 1}},
                    "command_id": "issue7-disconnect-run"})["run_id"]
                cohort = api.call(f"/api/runs/{identity}/cohorts", {
                    "name": "All humans", "mode": "dynamic", "predicate": {"type": "Human"},
                    "include_dead": True, "reference_revision": "0", "reference_time": "0"})
                api.command(identity, "terminate")
                until(lambda: api.row(identity)["resource_status"]["cleanup_complete"], description="fixture worker exit")
                before = api.call(f"/__issue7/audit/{identity}")
                api.call("/__issue7/track", {})

                def begin(name):
                    api.call("/__issue7/gate", {"name": name})
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    connections.append(connection)
                    connection.request("GET", f"/api/runs/{identity}/cohorts?time=0&revision=0&with_cursor=true")
                    until(lambda: api.call("/__issue7/diagnostics")["gates"][name]["entered"],
                          timeout=3, description=f"{name} cohort aggregation")
                    return connection

                obsolete = begin("obsolete")
                independent = begin("independent")
                started = time.monotonic()
                obsolete.sock.shutdown(socket.SHUT_RDWR)
                obsolete.close()

                def obsolete_finished():
                    gate = api.call("/__issue7/diagnostics")["gates"]["obsolete"]
                    return gate["cancel_observed"] and gate["finished"]
                until(obsolete_finished, timeout=3, description="HTTP cohort cancellation")
                elapsed = time.monotonic() - started
                gate = api.call("/__issue7/diagnostics")["gates"]["independent"]
                assert not gate["cancel_observed"] and not gate["finished"], gate
                api.call("/__issue7/gate/independent/release")
                response = independent.getresponse()
                assert response.status == 200, response.status
                bundle = json.loads(response.read())
                retry = api.call(f"/api/runs/{identity}/cohorts?time=0&revision=0&with_cursor=true")
                assert bundle == retry, (bundle, retry)
                assert bundle["cursor"] == {"time": "0", "revision": "0"}
                assert len(bundle["cohorts"]) == 1
                assert bundle["cohorts"][0]["definition"]["id"] == cohort["id"]
                assert bundle["cohorts"][0]["denominator"] == 2
                compatibility = api.call(f"/api/runs/{identity}/cohorts?time=0&revision=0")
                assert compatibility == bundle["cohorts"], "Default API must preserve list response"
                after = api.call(f"/__issue7/audit/{identity}")
                assert before == after, (before, after)

                def idle():
                    diagnostics = api.call("/__issue7/diagnostics")
                    return diagnostics if diagnostics["active_aggregations"] == 0 and all(
                        item["finished"] for item in diagnostics["aggregations"]) and all(
                        item["closed"] for item in diagnostics["private_readers"]) else None
                diagnostics = until(idle, timeout=3, description="all aggregation work finished and private readers closed")
                assert diagnostics["gates"]["obsolete"]["private_readers_closed_at_entry"]
                assert diagnostics["gates"]["independent"]["private_readers_closed_at_entry"]
                report = {"production_http_middleware": True, "actual_http_disconnect": True,
                          "cancellation_seconds": elapsed, "obsolete_aggregation_cancelled": True,
                          "independent_request_succeeded": True, "retry_succeeded": True,
                          "list_response_compatibility": True, "no_inflight_aggregation_work": True,
                          "private_readers_closed": True, "readers_close_before_aggregation": True,
                          "cached_metadata_readers_while_serving": diagnostics["metadata_readers"]["active_connections"],
                          "aggregations": diagnostics["aggregations"], "private_readers": diagnostics["private_readers"],
                          "source_audit_unchanged": True, "source_audit": after}
            finally:
                for connection in connections:
                    connection.close()
                for name in ("obsolete", "independent"):
                    try:
                        api.call(f"/__issue7/gate/{name}/release")
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
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue7-disconnect")
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
