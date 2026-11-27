"""Independent real-browser branch-survival provenance and terminal-view reuse checks in a disposable service."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import uuid

from issue2_check import Api, until
from issue5_check import NODE_MODULES, ROOT
from issue7_check import lifecycle_fixture, cohort_oracle


def audit(row):
    digest = hashlib.sha256()
    with sqlite3.connect((Path(row["directory"]) / "run.sqlite").as_uri() + "?mode=ro", uri=True) as database:
        for table in ("commits", "runtime_commits", "events"):
            digest.update(table.encode())
            for record in database.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                for value in record:
                    data = value if isinstance(value, bytes) else repr(value).encode()
                    digest.update(len(data).to_bytes(8, "big")); digest.update(data)
    return {"id": row["id"], "config": row["config"], "status": row["status"],
            "frontier": row["frontier"], "generation": row["generation"], "history_digest": digest.hexdigest()}


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "engine": engine}
    signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(RuntimeError("Check interrupted")))
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-final-gui-") as workspace:
            report["lifecycle"] = lifecycle_fixture(workspace)
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", NODE_PATH=NODE_MODULES)
            with (output / "service.log").open("w") as log:
                service = subprocess.Popen([sys.executable, "-m", "zombie_sim.cli", "gui", "--experiments-dir", workspace, "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                api = Api(port)
                report.update(workspace=workspace, port=port, service_pid=service.pid)
                try:
                    def ready():
                        if service.poll() is not None: raise AssertionError("Disposable service exited")
                        try: return isinstance(api.call("/api/runs"), list)
                        except OSError: return False
                    until(ready)
                    source = report["lifecycle"]["run_id"]
                    report["source_before"] = audit(api.row(source))
                    branch_at = api.call(f"/api/runs/{source}/view?time=2")
                    child = api.call(f"/api/runs/{source}/branch", {"command_id":str(uuid.uuid4()),"revision":branch_at["revision"]})["run_id"]
                    until(lambda: api.row(child)["status"] == "paused")
                    api.command(child, "stop")
                    until(lambda: api.row(child)["resource_status"]["cleanup_complete"])
                    report["child_before"] = audit(api.row(child))
                    for identity in (source,child):
                        view = api.call(f"/api/runs/{identity}/view")
                        api.call(f"/api/runs/{identity}/cohorts", {"name":"All retained identities","mode":"dynamic","predicate":{},"include_dead":True,"reference_time":view["time"],"reference_revision":view["revision"]})
                    pending = api.call("/api/runs", {"config":{"scenario":"terminal_reuse","horizon":30,"execution":{"workers":1},"population":{"humans":2,"zombies":2,"human_roles":{},"zombie_roles":{}}},"command_id":str(uuid.uuid4())})["run_id"]
                    until(lambda:api.row(pending)["status"] == "paused")
                    ids = {"source":source,"child":child,"pending":pending}
                    with (output / "browser.log").open("w") as browser_log:
                        result = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_survival_terminal.cjs"), api.base, str(output), json.dumps(ids), engine], cwd=ROOT, env=env, stdout=browser_log, stderr=subprocess.STDOUT, timeout=180)
                    report["browser"] = json.loads((output / "browser.json").read_text())
                    assert result.returncode == 0, (output / "browser.log").read_text()
                    report["source_after"] = audit(api.row(source))
                    assert report["source_before"] == report["source_after"], "Editor changed frozen source history"
                    report["child_after"] = audit(api.row(child))
                    assert report["child_before"] == report["child_after"], "Cohort views changed the child history"
                    report["walkthrough_passed"] = True
                finally:
                    if service.poll() is None:
                        try:
                            for row in api.call("/api/runs"):
                                if row["status"] not in {"terminated", "completed", "stopped", "failed"}: api.command(row["id"], "terminate")
                            report["cleanup_runs"] = until(lambda: (rows if all(r["resource_status"]["cleanup_complete"] for r in rows) else None) if (rows := api.call("/api/runs")) else True, timeout=90)
                        finally:
                            service.terminate()
                        try: service.wait(timeout=45)
                        except subprocess.TimeoutExpired:
                            report["forced_cleanup"] = True; service.kill(); service.wait(timeout=5)
                    report["service_returncode"] = service.returncode
                    with sqlite3.connect(Path(workspace) / "manager.sqlite") as database:
                        report["worker_leases"] = database.execute("SELECT * FROM worker_leases").fetchall()
                    with socket.socket() as probe: report["endpoint_closed"] = probe.connect_ex(("127.0.0.1", port)) != 0
                    report["application_shutdown_completed"] = "Application shutdown complete." in (output / "service.log").read_text()
                    assert service.returncode in (0, -signal.SIGTERM) and not report.get("forced_cleanup")
                    assert report["application_shutdown_completed"]
                    assert report["worker_leases"] == [] and report["endpoint_closed"]
        report["workspace_removed"] = not Path(workspace).exists()
        report["passed"] = report.get("walkthrough_passed", False) and report["workspace_removed"]
    except BaseException as error:
        report["error"] = repr(error)
        raise
    finally:
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output / "verification.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("chromium", "firefox"), default="chromium")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/remaining-survival-terminal-chromium")
    args = parser.parse_args(); check(args.output.absolute(), args.engine)
