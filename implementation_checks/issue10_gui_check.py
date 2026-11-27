"""I10 guide walkthrough against the unchanged production GUI in a temporary workspace."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
from issue2_check import Api, until
from issue5_check import NODE_MODULES, ROOT


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "scope": "Current GUI documentation walkthrough, not broad acceptance or full baseline performance"}
    def interrupted(number, frame):
        raise RuntimeError(f"Interrupted by signal {number}")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-issue10-gui-") as workspace:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", NODE_PATH=NODE_MODULES)
            with (output / "service.log").open("w") as log:
                command = [sys.executable, "-m", "zombie_sim.cli", "gui", "--experiments-dir", workspace, "--port", str(port)]
                service = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                report.update(workspace=workspace, port=port, service_pid=service.pid, service_command=command)
                api = Api(port)
                try:
                    def ready():
                        if service.poll() is not None: raise AssertionError("Disposable service exited")
                        try: return isinstance(api.call("/api/runs"), list)
                        except OSError: return False
                    until(ready)
                    with (output / "browser.log").open("w") as log:
                        browser = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue10.cjs"), api.base, str(output), str(ROOT / "docs/images/user-guide")], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600)
                    report["browser"] = json.loads((output / "browser.json").read_text())
                    assert browser.returncode == 0, (output / "browser.log").read_text()
                    report["walkthrough_runs"] = api.call("/api/runs")
                    report["retained_history"] = []
                    for row in report["walkthrough_runs"]:
                        with sqlite3.connect(Path(row["directory"]) / "run.sqlite") as db:
                            report["retained_history"].append({"run_id": row["id"], "commits": db.execute("select count(*) from commits").fetchone()[0], "events": db.execute("select count(*) from events").fetchone()[0]})
                    report["walkthrough_passed"] = True
                finally:
                    if service.poll() is None:
                        try:
                            for row in api.call("/api/runs"):
                                if row["status"] not in {"terminated", "completed", "stopped", "failed"}: api.command(row["id"], "terminate")
                            report["cleanup_runs"] = until(lambda: (rows if all(row["resource_status"]["cleanup_complete"] for row in rows) else None) if (rows := api.call("/api/runs")) else True, timeout=60)
                        finally:
                            report['service_shutdown_signal'] = 'SIGINT (Ctrl+C equivalent), after browser closed and workers cleaned'
                            service.send_signal(signal.SIGINT)
                    try:
                        service.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        report["required_forced_service_cleanup"] = True
                        service.kill(); service.wait(timeout=5)
                    report["service_returncode"] = service.returncode
                    report["service_exited"] = service.poll() is not None
                    with sqlite3.connect(Path(workspace) / "manager.sqlite") as database:
                        report["remaining_worker_leases"] = database.execute("SELECT * FROM worker_leases").fetchall()
                    with socket.socket() as probe:
                        probe.settimeout(1)
                        report["endpoint_closed"] = probe.connect_ex(("127.0.0.1", port)) != 0
                    service_log = (output / "service.log").read_text()
                    report["application_shutdown_completed"] = "Application shutdown complete." in service_log and "Finished server process" in service_log
                    assert not report.get("required_forced_service_cleanup"), "Disposable service needed forced cleanup"
                    assert report["service_returncode"] == 0, report["service_returncode"]
                    assert report["remaining_worker_leases"] == []
                    assert report["endpoint_closed"] and report["application_shutdown_completed"]
                    assert all(row["resource_status"]["cleanup_complete"] and not row["resource_status"]["worker_active"] for row in report["cleanup_runs"])
                    report["passed"] = report.get("walkthrough_passed", False)
    finally:
        report["workspace_removed"] = not Path(report["workspace"]).exists() if "workspace" in report else True
        report["passed"] = report["passed"] and report["workspace_removed"]
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output / "verification.json")}))

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue10-gui")
    check(parser.parse_args().output.absolute())
