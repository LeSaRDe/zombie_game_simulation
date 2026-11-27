"""Reproduce I26 configuration validation in disposable browsers, without launching runs."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from issue2_check import Api, until, ROOT, NODE_MODULES


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "engine": engine, "purpose": "pre-fix I26 review reproduction"}
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-issue26-review-") as workspace:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", NODE_PATH=NODE_MODULES)
            with (output / "service.log").open("w") as log:
                service = subprocess.Popen([sys.executable, "-m", "zombie_sim.cli", "gui", "--experiments-dir", workspace, "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                api = Api(port)
                try:
                    def ready():
                        if service.poll() is not None:
                            raise AssertionError("Disposable service exited before startup")
                        try: return isinstance(api.call("/api/runs"), list)
                        except OSError: return False
                    until(ready)
                    assert api.call("/api/runs") == []
                    with (output / "browser.log").open("w") as browser_log:
                        result = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "implementation_checks/issue26_review_browser.cjs"), api.base, str(output), engine], cwd=ROOT, env=env, stdout=browser_log, stderr=subprocess.STDOUT, timeout=120)
                    report["browser"] = json.loads((output / "browser.json").read_text())
                    assert result.returncode == 0, (output / "browser.log").read_text()
                    report["runs_after"] = api.call("/api/runs")
                    assert report["runs_after"] == []
                    report["reproduction_passed"] = True
                finally:
                    if service.poll() is None:
                        api.call("/api/shutdown", {"mode": "terminate", "timeout": 45})
                        until(lambda: api.call("/api/shutdown")["complete"], timeout=50)
                        report["shutdown"] = api.call("/api/shutdown")
                        api.call("/api/shutdown/exit", {})
                        service.wait(timeout=15)
                    report["service_returncode"] = service.returncode
                    assert service.returncode == 0
                    with sqlite3.connect((Path(workspace) / "manager.sqlite").as_uri() + "?mode=ro", uri=True) as db:
                        report["command_count"] = db.execute("SELECT COUNT(*) FROM commands").fetchone()[0]
                        report["worker_leases"] = db.execute("SELECT * FROM worker_leases").fetchall()
                    assert report["command_count"] == 0 and report["worker_leases"] == []
        report["workspace_removed"] = not Path(workspace).exists()
        report["passed"] = report.get("reproduction_passed", False) and report["workspace_removed"]
    finally:
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output / "verification.json")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", choices=("chromium", "firefox"), default="chromium")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); check(args.output.absolute(), args.engine)
