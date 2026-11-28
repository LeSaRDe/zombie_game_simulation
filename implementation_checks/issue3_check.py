"""I03 configuration workflows against a disposable real local service.

Metadata faults are injected in the browser, while valid validation, preview,
creation and copied-run workflows use the production API and engine.
"""
from __future__ import annotations

import argparse
import hashlib
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
import uuid

ROOT = Path(__file__).resolve().parents[1]
NODE_MODULES = "/home/fmeng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"


def until(function, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Timed out waiting for disposable I03 fixture")


def serve(workspace, port):
    import uvicorn
    from zombie_sim.server import create_app
    app = create_app(workspace)
    manager = app.state.manager
    lock = threading.Lock()
    requests = []

    class TraceRequests:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"].startswith("/api/"):
                with lock:
                    requests.append({"method": scope["method"], "path": scope["path"]})
            await self.app(scope, receive, send)

    app.add_middleware(TraceRequests)

    @app.get("/__issue3/diagnostics")
    def diagnostics():
        with lock:
            trace = list(requests)
        return {"pid": os.getpid(), "requests": trace, "runs": manager.list_runs()}

    @app.get("/__issue3/audit")
    def audit():
        result = []
        for row in manager.list_runs():
            digest = hashlib.sha256()
            ledger = Path(row["directory"]) / "run.sqlite"
            if ledger.exists():
                with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as database:
                    for table in ("commits", "runtime_commits", "events"):
                        digest.update(table.encode())
                        for record in database.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                            for value in record:
                                encoded = value if isinstance(value, bytes) else repr(value).encode()
                                digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
            with manager.lock:
                commands = manager.catalog.command_count(row["id"])
            result.append({"id": row["id"], "status": row["status"], "generation": row["generation"],
                           "frontier": row["frontier"], "commands": commands, "history_digest": digest.hexdigest()})
        return result

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


class Api:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, path, body=None):
        request = Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=60) as response:
            return json.load(response)


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False}
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-issue3-") as workspace:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NODE_PATH=NODE_MODULES,
                       PYTHONDONTWRITEBYTECODE="1")
            with (output / "service.log").open("w") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace, "--port", str(port)],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                api = Api(port)
                report.update(workspace=workspace, port=port, service_pid=process.pid)
                try:
                    def ready():
                        if process.poll() is not None:
                            raise AssertionError("Fixture service exited; inspect service.log")
                        try:
                            return api.call("/__issue3/diagnostics")
                        except OSError:
                            return None
                    until(ready)
                    config = {"scenario": "issue3_source_copy", "seed": 123, "horizon": 30,
                              "population": {"humans": 16, "zombies": 4}, "execution": {"workers": 1},
                              "checkpoint_interval": 1000}
                    source = api.call("/api/runs", {"config": config, "command_id": str(uuid.uuid4())})["run_id"]
                    until(lambda: next(row for row in api.call("/api/runs") if row["id"] == source)["status"] == "paused")
                    report["source_before"] = next(row for row in api.call("/__issue3/audit") if row["id"] == source)
                    result = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue3.cjs"),
                                             api.base, str(output), source], cwd=ROOT, env=env,
                                            text=True, capture_output=True, timeout=180)
                    (output / "browser.log").write_text(result.stdout + result.stderr)
                    report["browser"] = json.loads((output / "browser.json").read_text())
                    assert result.returncode == 0, result.stdout + result.stderr
                    report["source_after"] = next(row for row in api.call("/__issue3/audit") if row["id"] == source)
                    assert report["source_before"] == report["source_after"], "Configuration workflows changed the copied source run"
                    report["diagnostics"] = api.call("/__issue3/diagnostics")
                    report["passed"] = True
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            process.kill(); process.wait(timeout=5)
                    report["service_exited"] = process.poll() is not None
        report["workspace_removed"] = not Path(report["workspace"]).exists()
    finally:
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output / "verification.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve")
    parser.add_argument("--port", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue3")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        check(args.output.absolute())
