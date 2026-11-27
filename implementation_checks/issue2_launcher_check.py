"""Verify actual menu option 9 using a disposable launcher service.

Only opening the operating-system browser is intercepted. The menu, launcher,
HTTP service, simulation worker and durable journals are real.
"""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import simulation_launcher as module


def until(function, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Disposable launcher did not reach the requested state")


def journal(workspace):
    with sqlite3.connect((workspace / "manager.sqlite").as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT id,directory,status,generation,frontier FROM runs ORDER BY id").fetchall()
        commands = db.execute("SELECT id,operation,status,response FROM commands ORDER BY id").fetchall()
    histories = {}
    for identity, directory, *_ in rows:
        with sqlite3.connect((Path(directory) / "run.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            histories[identity] = db.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
    return {"runs": rows, "commands": commands, "frontiers": histories}


def main():
    output = ROOT / "artifacts/issue2-launcher"
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False}
    transcript = io.StringIO()
    with tempfile.TemporaryDirectory(prefix="zombie-issue2-launcher-") as temporary:
        workspace = Path(temporary).resolve()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        launcher = module.Launcher(workspace, port=port, timeout=40)
        original_request = module.API.request
        requests, opened = [], []

        def request(self, endpoint, payload=None, timeout=40):
            requests.append({"method": "GET" if payload is None else "POST", "path": endpoint})
            return original_request(self, endpoint, payload, timeout)

        def open_menu():
            requests.clear()
            with patch("builtins.input", side_effect=["9", "0"]), \
                    patch.dict(os.environ, {"DISPLAY": ":issue2-test"}), \
                    patch.object(module.webbrowser, "open", side_effect=lambda url, **kw: opened.append(url) or True), \
                    patch.object(module.API, "request", request):
                assert module.menu(launcher) == 0
            assert requests and all(item["method"] == "GET" for item in requests), requests
            return list(requests)

        with redirect_stdout(transcript):
            try:
                empty_requests = open_menu()
                assert launcher.api.request("/api/runs") == []
                service = dict(launcher.record)
                config = {"scenario": "Issue 2 launcher fixture", "decision_mode": "scripted",
                          "population": {"humans": 3, "zombies": 1}, "horizon": 60,
                          "execution": {"workers": 1}}
                identity = launcher.api.request("/api/runs", {"config": config, "command_id": str(uuid.uuid4())})["run_id"]
                until(lambda: any(row["id"] == identity and row["status"] == "paused"
                                  for row in launcher.api.request("/api/runs")))
                before = journal(workspace)
                populated_requests = open_menu()
                time.sleep(.3)
                assert journal(workspace) == before, "Opening the GUI changed a run or command journal"
                assert launcher.record["pid"] == service["pid"] and launcher.record["instance"] == service["instance"]
                assert opened == [f"http://127.0.0.1:{port}"] * 2
                report.update(passed=True, workspace=str(workspace), service_pid=service["pid"],
                              empty_workspace_run_count=0, existing_run_count=1,
                              service_reused=True, existing_run_and_commands_unchanged=True,
                              browser_urls=opened, empty_menu_requests=empty_requests,
                              populated_menu_requests=populated_requests)
            finally:
                if launcher.record is not None and launcher.owns_process(launcher.record):
                    launcher.shutdown(terminate=True)
                if launcher.record is not None:
                    assert not launcher.owns_process(launcher.record), "Disposable service did not exit"
                report["disposable_service_exited"] = True
                (output / "menu.log").write_text(transcript.getvalue())
                (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
