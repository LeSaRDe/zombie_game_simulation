"""Check comparison POST cancellation through real middleware and sockets.

Only this disposable verification service installs sampling gates and reader
tracking. The production comparison route, session cookie and disconnect watcher
are exercised unchanged; no user runs or services are accessed.
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
    from zombie_sim import comparison, server

    app = server.create_app(workspace)
    manager = app.state.manager
    original_sample, original_history, original_comparison = comparison.metrics_at_times, manager.history, manager.comparison
    lock = threading.Lock()
    rules, gates, readers = [], {}, []
    active_samples = active_batches = 0

    def history(run_id):
        reader = original_history(run_id)
        record = {"run_id": run_id, "thread": threading.get_ident(), "closed": False}
        with lock:
            readers.append(record)
        original_close = reader.close

        def close():
            original_close()
            try:
                reader.connection.execute("SELECT 1")
            except sqlite3.ProgrammingError:
                with lock:
                    record["closed"] = True
            else:
                raise AssertionError("Private comparison history remained open")

        reader.close = close
        return reader

    def sampled(history, *args, check_cancelled=None, **kwargs):
        nonlocal active_samples
        assert callable(check_cancelled), "Comparison omitted its cancellation callback"
        with lock:
            gate = rules.pop(0) if rules else None
            active_samples += 1
            if gate is not None:
                gate["entered"] = True
                gate["thread"] = threading.get_ident()
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
                        raise AssertionError("Disposable comparison gate was not released")
                    time.sleep(.01)
            check_cancelled()
            return original_sample(history, *args, check_cancelled=check_cancelled, **kwargs)
        finally:
            with lock:
                active_samples -= 1
                if gate is not None:
                    gate["finished"] = True

    def compared(*args, **kwargs):
        nonlocal active_batches
        with lock:
            active_batches += 1
        try:
            return original_comparison(*args, **kwargs)
        finally:
            with lock:
                active_batches -= 1

    manager.history, manager.comparison = history, compared
    comparison.metrics_at_times = sampled

    @app.get("/__issue9/diagnostics")
    def diagnostics():
        with lock:
            return {"active_samples": active_samples, "active_batches": active_batches,
                    "readers": [dict(reader) for reader in readers],
                    "gates": {name: {key: value for key, value in gate.items() if key != "release"}
                              for name, gate in gates.items()}}

    @app.post("/__issue9/gate")
    def arm(body: dict = Body(...)):
        gate = {"name": body["name"], "release": threading.Event(), "entered": False,
                "finished": False, "cancel_observed": False}
        with lock:
            assert gate["name"] not in gates
            gates[gate["name"]] = gate
            rules.append(gate)
        return {"armed": gate["name"]}

    @app.get("/__issue9/gate/{name}/release")
    def release(name: str):
        gates[name]["release"].set()
        return {"released": name}

    @app.get("/__issue9/audit/{identity}")
    def audit(identity: str):
        reader = manager.history(identity)
        try:
            row = manager._row(identity)
            with manager.lock:
                commands = manager.catalog.command_count(identity)
            return {"run_id": identity, "ledger_sha256": digest(reader), "revision": reader.revision,
                    "status": row["status"], "generation": row["generation"], "commands": commands}
        finally:
            reader.close()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="zombie-issue9-disconnect-") as workspace:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"))
        with (output / "service.log").open("w") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace,
                                        "--port", str(port)], cwd=ROOT, env=env,
                                       stdout=log, stderr=subprocess.STDOUT)
            api = Api(port); connections = []
            try:
                def ready():
                    if process.poll() is not None:
                        raise AssertionError("Disposable comparison service exited; inspect service.log")
                    try:
                        return api.call("/__issue9/diagnostics")
                    except OSError:
                        return None
                until(ready, timeout=10, description="disposable comparison service")
                identities, sources = [], []
                for seed in (123, 124):
                    identity = api.call("/api/runs", {"config": {"scenario": "issue9_disconnect", "seed": seed,
                        "horizon": 20, "population": {"humans": 2, "zombies": 1}, "execution": {"workers": 1}},
                        "command_id": f"issue9-disconnect-run-{seed}"})["run_id"]
                    identities.append(identity)
                    api.command(identity, "step")
                    api.command(identity, "terminate")
                    until(lambda: api.row(identity)["resource_status"]["cleanup_complete"], description="fixture worker exit")
                    row = api.row(identity)
                    sources.append({"run_id": identity, "time": str(row["frontier"]["time"]),
                                    "revision": str(row["frontier"]["revision"])})
                body = {"sources": sources}
                before = [api.call(f"/__issue9/audit/{identity}") for identity in identities]

                def begin(name):
                    api.call("/__issue9/gate", {"name": name})
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    connections.append(connection)
                    # Establish an actual production session on this raw socket.
                    connection.request("GET", "/api/runs")
                    response = connection.getresponse(); response.read()
                    assert response.status == 200
                    cookie = response.getheader("Set-Cookie").split(";", 1)[0]
                    connection.request("POST", "/api/comparison", body=json.dumps(body),
                                       headers={"Content-Type": "application/json", "Cookie": cookie})
                    until(lambda: api.call("/__issue9/diagnostics")["gates"][name]["entered"],
                          timeout=3, description=f"{name} private comparison")
                    return connection

                obsolete = begin("obsolete")
                independent = begin("independent")
                started = time.monotonic()
                obsolete.sock.shutdown(socket.SHUT_RDWR); obsolete.close()

                def obsolete_finished():
                    diagnostics = api.call("/__issue9/diagnostics"); gate = diagnostics["gates"]["obsolete"]
                    owned = [reader for reader in diagnostics["readers"] if reader["thread"] == gate["thread"]]
                    return gate["cancel_observed"] and gate["finished"] and len(owned) >= 2 and all(reader["closed"] for reader in owned)

                until(obsolete_finished, timeout=3, description="POST disconnect cancels and closes the complete private batch")
                elapsed = time.monotonic() - started
                gate = api.call("/__issue9/diagnostics")["gates"]["independent"]
                assert not gate["cancel_observed"] and not gate["finished"], gate
                api.call("/__issue9/gate/independent/release")
                response = independent.getresponse()
                assert response.status == 200, response.status
                bundle = json.loads(response.read())
                retry = api.call("/api/comparison", body)
                assert bundle == retry and bundle["status"] == "ready" and len(bundle["runs"]) == 2, (bundle, retry)
                after = [api.call(f"/__issue9/audit/{identity}") for identity in identities]
                assert before == after, (before, after)

                def idle():
                    diagnostics = api.call("/__issue9/diagnostics")
                    return diagnostics if diagnostics["active_samples"] == diagnostics["active_batches"] == 0 and all(
                        reader["closed"] for reader in diagnostics["readers"]) else None

                diagnostics = until(idle, timeout=3, description="all comparison work and private readers closed")
                report = {"production_http_middleware": True, "actual_http_disconnect": True,
                          "method": "POST", "production_session_cookie": True,
                          "cancellation_seconds": elapsed, "private_connections_closed": True,
                          "independent_batch_succeeded": True, "retry_succeeded": True,
                          "no_inflight_comparison_work": True, "readers": diagnostics["readers"],
                          "source_audit_unchanged": True, "source_audits": after}
            finally:
                for connection in connections:
                    connection.close()
                for name in ("obsolete", "independent"):
                    try:
                        api.call(f"/__issue9/gate/{name}/release")
                    except Exception:
                        pass
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
    report["workspace_removed"] = not Path(workspace).exists()
    report["service_exited"] = process.poll() is not None
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve"); parser.add_argument("--port", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue9-disconnect")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        args.output.mkdir(parents=True, exist_ok=True); report = {"passed": False}
        try:
            report.update(check(args.output)); report["passed"] = True
        finally:
            (args.output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
