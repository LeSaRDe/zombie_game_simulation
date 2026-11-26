"""Exercise the friendly launcher against disposable real services and workers.

This check never uses the user's default workspace or ports. It needs permission
to bind loopback sockets and spawn processes, but no third-party test libraries.
"""
from __future__ import annotations

import argparse
import hashlib
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts/simulation_launcher.py"


def until(function, *, timeout=30, description="condition"):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = function()
        if last:
            return last
        time.sleep(.1)
    raise AssertionError(f"Timed out waiting for {description}; last={last!r}")


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def process_alive(pid):
    try:
        # Zombies have exited; waiting for their adopting parent's reap does not
        # imply a still-running simulation or an open listening socket.
        state = Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[0]
        return state != "Z"
    except FileNotFoundError:
        return False


class Api:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, path, body=None, *, timeout=5):
        encoded = None if body is None else json.dumps(body).encode()
        request = Request(self.base + path, data=encoded,
                          headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=timeout) as response:
            return json.load(response)

    def available(self):
        try:
            return self.call("/api/launcher", timeout=1)
        except (OSError, ValueError, HTTPError, URLError):
            return False


def read_rows(workspace, query, values=()):
    database = Path(workspace) / "manager.sqlite"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query, values)]


def history_cursor(directory):
    database = Path(directory) / "run.sqlite"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        return connection.execute(
            "SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1"
        ).fetchone()


class Check:
    def __init__(self, workspace, port, logdir):
        self.workspace = Path(workspace).absolute()
        self.port = port
        self.api = Api(port)
        self.logdir = logdir
        self.calls = 0
        self.identity = None

    def cli(self, *args, success=True, timeout=90):
        self.calls += 1
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
        completed = subprocess.run(
            [sys.executable, str(LAUNCHER), "--workspace", str(self.workspace),
             "--port", str(self.port), "--timeout", "45", *args],
            cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout,
        )
        (self.logdir / f"{self.calls:02d}-{args[0]}.log").write_text(
            completed.stdout + "\n" + completed.stderr
        )
        if success and completed.returncode:
            raise AssertionError(f"Launcher {args!r} failed ({completed.returncode}):\n"
                                 + completed.stdout + completed.stderr)
        if not success and not completed.returncode:
            raise AssertionError(f"Launcher {args!r} unexpectedly succeeded:\n" + completed.stdout)
        return completed

    def service(self):
        identity = self.api.call("/api/launcher")
        assert identity["schema"] == "zombie-sim/launcher-v1", identity
        assert Path(identity["workspace"]).resolve() == self.workspace.resolve(), identity
        self.identity = identity
        return identity

    def run(self, identity):
        return next(row for row in self.api.call("/api/runs") if row["id"] == identity)

    def wait_status(self, identity, status):
        def matches():
            row = self.run(identity)
            if row["status"] == "failed":
                raise AssertionError(row)
            return row if row["status"] == status else None
        return until(matches, description=f"run {identity} status {status}")

    def no_leases(self, identity=None):
        query = "SELECT run_id,pid FROM worker_leases"
        values = ()
        if identity:
            query += " WHERE run_id=?"
            values = (identity,)
        return not read_rows(self.workspace, query, values)

    def final_cleanup(self):
        """Stop only the disposable instance whose identity we observed."""
        live = self.api.available()
        if not live:
            if self.identity is not None and process_alive(self.identity["pid"]):
                raise RuntimeError("Disposable service still runs without a reachable control endpoint")
            if (self.workspace / "manager.sqlite").is_file() and not self.no_leases():
                raise RuntimeError("Disposable workspace still contains worker leases after service exit")
            return
        if (self.identity is None or live.get("instance") != self.identity.get("instance")
                or Path(live.get("workspace", "")).resolve() != self.workspace.resolve()):
            raise RuntimeError("Refusing cleanup of an unrecognized service")
        try:
            self.cli("shutdown", "--terminate", timeout=70)
        except Exception:
            # Cleanup can still succeed if the launcher path itself is what the
            # test exposed as defective. Use only the verified disposable API.
            rows = self.api.call("/api/runs")
            for row in rows:
                if row["status"] not in {"terminated", "completed", "stopped", "failed"}:
                    command = str(uuid.uuid4())
                    self.api.call(f"/api/runs/{row['id']}/commands",
                                  {"operation": "terminate", "command_id": command})
                    until(lambda: self.api.call(f"/api/commands/{command}")["status"] != "pending",
                          timeout=30, description="cleanup command")
            until(self.no_leases, timeout=30, description="cleanup worker release")
            # Recheck instance ownership immediately before signalling.
            current = self.api.call("/api/launcher")
            assert current == live
            os.kill(current["pid"], signal.SIGTERM)
            until(lambda: not self.api.available(), timeout=15, description="cleanup service exit")


class UnrelatedHandler(BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):
        self.requests.append(("GET", self.path))
        body = b'{"message":"unrelated local service"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.requests.append(("POST", self.path))
        self.send_error(405)

    def log_message(self, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/launcher/verification.json")
    args = parser.parse_args()
    report_path = args.report.absolute()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    logdir = report_path.parent / ("commands-" + uuid.uuid4().hex[:8])
    logdir.mkdir()
    scratch = Path(tempfile.mkdtemp(prefix="zombie-launcher-check-")).resolve()
    check = Check(scratch / "workspace", free_port(), logdir)
    results = {}
    started = time.monotonic()
    cleanup_ok = False
    report = {"status": "RUNNING", "workspace": str(check.workspace), "port": check.port,
              "log_directory": str(logdir), "checks": results}
    try:
        config = scratch / "scenario.json"
        config.write_text(json.dumps({
            "seed": 70, "horizon": 3600, "decision_mode": "scripted",
            "population": {"humans": 3, "zombies": 1, "infected": 0},
            "execution": {"workers": 1}, "checkpoint_interval": 1000,
        }))
        check.cli("gui", "--no-browser")
        first_service = check.service()
        assert not check.api.call("/api/runs")
        check.cli("gui", "--no-browser")
        assert check.service() == first_service
        results["service_start_and_reuse"] = "PASS"

        other = Check(scratch / "wrong-workspace", check.port, logdir)
        other.calls = 100
        other.cli("gui", "--no-browser", success=False)
        assert check.api.call("/api/launcher") == first_service
        assert not check.api.call("/api/runs")
        results["wrong_workspace_listener_rejected_without_effects"] = "PASS"

        check.cli("start", str(config), "--no-browser")
        runs = check.api.call("/api/runs")
        assert len(runs) == 1, runs
        identity = runs[0]["id"]
        check.wait_status(identity, "running")
        check.cli("list")
        check.cli("pause", identity)
        row = check.wait_status(identity, "paused")
        initial = history_cursor(row["directory"])
        time.sleep(.35)
        assert history_cursor(row["directory"]) == initial
        results["real_start_and_acknowledged_pause_quiescence"] = "PASS"

        creation = read_rows(check.workspace, "SELECT id,request FROM commands WHERE operation='create'")[0]
        check.cli("retry", creation["id"])
        assert len(check.api.call("/api/runs")) == 1
        assert check.run(identity)["status"] == "paused"
        assert history_cursor(row["directory"]) == initial
        results["creation_retry_preserves_identity_and_does_not_restart"] = "PASS"

        check.cli("stop", identity)
        check.wait_status(identity, "stopped")
        assert check.no_leases(identity)
        controls_before = read_rows(check.workspace, "SELECT COUNT(*) AS n FROM commands")[0]["n"]
        check.cli("stop", identity)
        assert check.no_leases(identity)
        assert read_rows(check.workspace, "SELECT COUNT(*) AS n FROM commands")[0]["n"] == controls_before
        check.cli("resume", identity)
        check.wait_status(identity, "running")
        check.cli("pause", identity)
        check.wait_status(identity, "paused")
        results["stop_releases_worker_duplicate_stop_is_inert_and_resume_works"] = "PASS"

        checkpoint = Path(row["directory"]) / "worker-checkpoint.json"
        checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
        check.cli("terminate", identity)
        check.wait_status(identity, "terminated")
        assert check.no_leases(identity)
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == checkpoint_hash
        stopped_cursor = history_cursor(row["directory"])
        termination = read_rows(check.workspace,
                                "SELECT id,response FROM commands WHERE operation='terminate' AND run_id=?",
                                (identity,))[-1]
        check.cli("retry", termination["id"])
        check.cli("terminate", identity)
        check.cli("resume", identity, success=False)
        assert check.no_leases(identity)
        assert check.run(identity)["status"] == "terminated"
        assert history_cursor(row["directory"]) == stopped_cursor
        assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == checkpoint_hash
        assert read_rows(check.workspace, "SELECT response FROM commands WHERE id=?",
                         (termination["id"],))[0]["response"] == termination["response"]
        results["terminate_no_checkpoint_exact_retry_duplicate_safe_and_resume_rejected"] = "PASS"

        check.cli("start", str(config), "--no-browser")
        second = next(item for item in check.api.call("/api/runs") if item["id"] != identity)
        # Once shutdown fencing begins, a browser racing the stop sweep cannot
        # introduce a fresh run or resume one behind that sweep.
        before_drain_runs = len(check.api.call("/api/runs"))
        before_drain_commands = read_rows(check.workspace, "SELECT COUNT(*) AS n FROM commands")[0]["n"]
        drained = check.api.call("/api/launcher/drain", {"instance": first_service["instance"]})
        assert drained["draining"] is True
        assert check.api.call("/api/launcher")["draining"] is True
        prohibited = [
            ("/api/runs", {"config": json.loads(config.read_text()), "start": True,
                           "command_id": str(uuid.uuid4())}),
            (f"/api/runs/{second['id']}/commands", {"operation": "continue",
                                                   "command_id": str(uuid.uuid4())}),
        ]
        for path, body in prohibited:
            try:
                check.api.call(path, body)
            except HTTPError as error:
                assert error.code == 503, error
                assert json.load(error)["code"] == "LAUNCHER_DRAINING"
            else:
                raise AssertionError(f"Draining service accepted mutation {path}")
        assert len(check.api.call("/api/runs")) == before_drain_runs
        assert read_rows(check.workspace, "SELECT COUNT(*) AS n FROM commands")[0]["n"] == before_drain_commands
        results["shutdown_drain_fences_new_run_and_resume_mutations"] = "PASS"
        check.cli("shutdown")
        assert not check.api.available()
        until(lambda: not process_alive(first_service["pid"]), timeout=15, description="saved service exit")
        assert check.no_leases()
        saved = read_rows(check.workspace, "SELECT status FROM runs WHERE id=?", (second["id"],))[0]
        assert saved["status"] == "stopped", saved
        assert (Path(second["directory"]) / "worker-checkpoint.json").is_file()
        results["shutdown_saves_active_run_releases_workers_and_stops_service"] = "PASS"

        check.cli("gui", "--no-browser")
        next_service = check.service()
        assert next_service["instance"] != first_service["instance"]
        assert check.run(second["id"])["status"] == "stopped"
        assert check.no_leases()
        check.cli("resume", second["id"])
        check.wait_status(second["id"], "running")
        check.cli("pause", second["id"])
        second_hash = hashlib.sha256((Path(second["directory"]) / "worker-checkpoint.json").read_bytes()).hexdigest()
        check.cli("start", str(config), "--no-browser")
        third = next(item for item in check.api.call("/api/runs")
                     if item["id"] not in {identity, second["id"]})
        check.cli("stop", third["id"])
        assert check.no_leases(third["id"])
        third_checkpoint = Path(third["directory"]) / "worker-checkpoint.json"
        third_hash = hashlib.sha256(third_checkpoint.read_bytes()).hexdigest()
        third_cursor = history_cursor(third["directory"])
        check.cli("shutdown", "--terminate")
        assert not check.api.available()
        until(lambda: not process_alive(next_service["pid"]), timeout=15, description="terminated service exit")
        assert check.no_leases()
        assert read_rows(check.workspace, "SELECT status FROM runs WHERE id=?", (second["id"],))[0]["status"] == "terminated"
        assert hashlib.sha256((Path(second["directory"]) / "worker-checkpoint.json").read_bytes()).hexdigest() == second_hash
        assert read_rows(check.workspace, "SELECT status FROM runs WHERE id=?", (third["id"],))[0]["status"] == "stopped"
        assert hashlib.sha256(third_checkpoint.read_bytes()).hexdigest() == third_hash
        assert history_cursor(third["directory"]) == third_cursor
        results["restart_saved_run_and_shutdown_without_extra_checkpoint"] = "PASS"
        results["terminate_shutdown_does_not_restore_or_rewrite_already_stopped_run"] = "PASS"

        server = ThreadingHTTPServer(("127.0.0.1", 0), UnrelatedHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            unrelated = Check(scratch / "unrelated-port", server.server_address[1], logdir)
            unrelated.calls = 200
            unrelated.cli("gui", "--no-browser", success=False)
            assert thread.is_alive()
            assert not any(method == "POST" for method, _ in UnrelatedHandler.requests)
            assert unrelated.api.call("/still-here")["message"] == "unrelated local service"
            results["unrelated_listener_is_not_attached_or_signalled"] = "PASS"
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        report["status"] = "PASS"
    except BaseException as error:
        report["status"] = "FAIL"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        try:
            check.final_cleanup()
            cleanup_ok = not check.api.available()
        except BaseException as error:
            report["status"] = "FAIL"
            report["cleanup_error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            report["cleanup_complete"] = cleanup_ok
            report["elapsed_seconds"] = time.monotonic() - started
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            if cleanup_ok and report["status"] == "PASS":
                shutil.rmtree(scratch)
            else:
                print(f"Retained disposable diagnostic workspace: {scratch}", file=sys.stderr)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
