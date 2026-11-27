"""Exercise real HTTP disconnects through production middleware, without a browser."""
from __future__ import annotations

import argparse
import asyncio
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from issue2_check import Api, serve, until


def serve_previous_poll(workspace, port):
    """Keep the old endpoint only in this comparison service, never in product."""
    from fastapi import Request
    from fastapi.responses import Response
    from zombie_sim import server
    original = server.create_app
    globals()["Request"] = Request

    def previous_app(*args, **kwargs):
        app = original(*args, **kwargs)
        manager = app.state.manager
        app.router.routes = [route for route in app.router.routes
                             if getattr(route, "path", "") != "/api/runs/{run_id}/view"]

        @app.get("/api/runs/{run_id}/view")
        async def previous_view(request: Request, run_id: str):
            cancelled = threading.Event()
            work = asyncio.create_task(asyncio.to_thread(manager.snapshot, run_id, cancel_event=cancelled))
            try:
                while not work.done():
                    if await request.is_disconnected():
                        cancelled.set()
                    await asyncio.wait({work}, timeout=.05)
                return await work
            except server.ViewCancelled:
                return Response(status_code=499)
            finally:
                cancelled.set()
        return app

    server.create_app = previous_app
    serve(workspace, port)


def check_service(output, previous=False):
    with TemporaryDirectory(prefix="zombie-issue2-disconnect-") as workspace:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        mode = "previous-poll" if previous else "receive-watcher"
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"))
        with (output / f"{mode}.log").open("w") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace,
                                        "--port", str(port), *( ["--previous"] if previous else [])],
                                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            api = Api(port)
            connections = []
            try:
                def ready():
                    if process.poll() is not None:
                        raise AssertionError(f"{mode} service exited")
                    try:
                        return api.call("/__issue2/diagnostics")
                    except OSError:
                        return None
                until(ready, timeout=10, description="disposable HTTP service")
                identity = api.call("/api/runs", {"config": {"scenario": "issue2_disconnect", "horizon": 20,
                    "population": {"humans": 2, "zombies": 1}, "execution": {"workers": 1}},
                    "command_id": "disconnect-run"})["run_id"]
                api.command(identity, "terminate")
                until(lambda: api.row(identity)["resource_status"]["cleanup_complete"], description="fixture worker exit")
                before = api.call("/__issue2/audit")

                def begin(name):
                    api.call("/__issue2/gate", {"name": name, "run_id": identity, "kind": "delay"})
                    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                    connections.append(connection)
                    connection.request("GET", f"/api/runs/{identity}/view")
                    until(lambda: api.call("/__issue2/diagnostics")["gates"][name]["entered"],
                          timeout=3, description=f"{name} private reader")
                    return connection

                obsolete = begin("obsolete")
                independent = begin("independent")
                started = time.monotonic()
                obsolete.sock.shutdown(socket.SHUT_RDWR)
                obsolete.close()
                if previous:
                    time.sleep(1)
                    observed = api.call("/__issue2/diagnostics")["gates"]["obsolete"]["cancel_observed"]
                    assert not observed, "Comparison unexpectedly observed disconnect; re-evaluate old-path claim"
                    api.call("/__issue2/gate/obsolete/release")
                else:
                    until(lambda: (gate := api.call("/__issue2/diagnostics")["gates"]["obsolete"])["cancel_observed"]
                          and gate["finished"], timeout=3, description="actual HTTP disconnect cancellation")
                    observed = True
                elapsed = time.monotonic() - started
                gate = api.call("/__issue2/diagnostics")["gates"]["independent"]
                assert not gate["cancel_observed"] and not gate["finished"], gate
                api.call("/__issue2/gate/independent/release")
                response = independent.getresponse()
                assert response.status == 200, response.status
                bundle = json.loads(response.read())
                assert bundle["run_id"] == identity
                retry = api.call(f"/api/runs/{identity}/view")
                assert retry["state"] == bundle["state"]
                assert api.call("/__issue2/audit") == before
                return {"mode": mode, "disconnect_observed": observed, "seconds": elapsed,
                        "production_http_middleware": True, "test_trace": "transparent pure ASGI",
                        "independent_reader_succeeded": True, "retry_succeeded": True,
                        "audit_and_frontier_unchanged": True}
            finally:
                for connection in connections:
                    connection.close()
                for name in ("obsolete", "independent"):
                    try:
                        api.call(f"/__issue2/gate/{name}/release")
                    except Exception:
                        pass
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve")
    parser.add_argument("--port", type=int)
    parser.add_argument("--previous", action="store_true")
    args = parser.parse_args()
    if args.serve:
        (serve_previous_poll if args.previous else serve)(args.serve, args.port)
    else:
        output = ROOT / "artifacts/issue2/disconnect"
        output.mkdir(parents=True, exist_ok=True)
        report = {"passed": False}
        try:
            report["previous"] = check_service(output, previous=True)
            report["current"] = check_service(output)
            report["passed"] = True
        finally:
            (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
