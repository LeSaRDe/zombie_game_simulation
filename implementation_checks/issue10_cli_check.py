"""Verify I10 guide terminal workflows without touching user run workspaces.

The actual ./simulate wrapper, HTTP service, worker, headless commands and
durable files are used. I12's launcher shutdown path is intentionally outside
this documentation check; service exit uses an identity-verified signal after
all owned run workers have stopped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import traceback

from launcher_check import Api, free_port, history_cursor, process_alive, read_rows, until

ROOT = Path(__file__).resolve().parents[1]
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue10-cli")
    parser.add_argument("--check-interrupt", action="store_true",
                        help="Reproduce the separately reported SIGINT issue only when authorized")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="zombie-issue10-cli-")).resolve()
    workspace = scratch / "launcher-workspace"
    port = free_port()
    api = Api(port)
    report = {"status": "RUNNING", "scratch": str(scratch), "port": port,
              "checks": {}, "commands": [], "limits": [
                  "No browser clients or outstanding expensive requests during service exit.",
                  "Launcher shutdown I12 is not exercised or declared fixed.",
                  "SIGINT during advancement failed in the archived first attempt; no save guarantee is established.",
                  "The separately reported SIGINT defect is excluded from subsequent guide checks."]}
    identity = None
    interrupted = None
    worker_pids = set()
    started = time.monotonic()

    def command(argv, *, label, timeout=180):
        before = time.monotonic()
        result = subprocess.run([str(x) for x in argv], cwd=ROOT, env=ENV,
                                capture_output=True, text=True, timeout=timeout)
        (output / f"{label}.log").write_text(result.stdout + "\n" + result.stderr)
        report["commands"].append({"label": label, "argv": [str(x) for x in argv],
                                   "returncode": result.returncode,
                                   "seconds": round(time.monotonic() - before, 3)})
        assert result.returncode == 0, (label, result.stdout, result.stderr)
        return result.stdout

    def cli(*arguments, label):
        return json.loads(command([sys.executable, "-m", "zombie_sim.cli", *arguments], label=label))

    def launcher(*arguments, label):
        return command([ROOT / "simulate", "--workspace", workspace, "--port", str(port),
                        "--timeout", "90", *arguments], label=label)

    def row(run_id):
        return next(item for item in api.call("/api/runs") if item["id"] == run_id)

    def wait_status(run_id, status):
        return until(lambda: (found if (found := row(run_id))["status"] == status else None),
                     timeout=90, description=f"{run_id} {status}")

    def leases():
        return read_rows(workspace, "SELECT run_id,pid FROM worker_leases")

    def stop_service():
        nonlocal identity
        if identity is None:
            return
        assert not leases(), leases()
        assert api.call("/api/launcher") == identity, "Service identity changed"
        os.kill(identity["pid"], signal.SIGTERM)
        until(lambda: not process_alive(identity["pid"]), timeout=30, description="service exit")
        assert not api.available(), "Service endpoint remains open"
        identity = None

    try:
        validated = cli("validate", "configs/small.toml", "--preview", label="01-validate-small")
        assert validated["valid"] and validated["initialization"]
        cli("validate", "configs/baseline.toml", label="02-validate-baseline")
        run_dir = scratch / "cli-example"
        run = cli("run", "configs/small.toml", "--workers", "1", "--backend", "memory",
                  "--until", "30", "--output", str(run_dir), label="03-run-to-30")
        assert run["status"] == "interrupted" and run["time"] == "30", run
        assert (run_dir / "checkpoint.json").is_file() and (run_dir / "manifest.json").is_file()
        inspected = cli("inspect", str(run_dir), label="04-inspect-30")
        assert inspected["time"] == "30", inspected
        replay_file = run_dir / "replay.json"
        before_replay = history_cursor(run_dir)
        cli("replay", str(run_dir), "--time", "15", "--output", str(replay_file), label="05-replay-15")
        replay = json.loads(replay_file.read_text())
        assert replay["time"] == "15" and history_cursor(run_dir) == before_replay
        cli("resume", str(run_dir), "--until", "120", label="06-resume-to-120")
        final = cli("inspect", str(run_dir), label="07-inspect-120")
        manifest = json.loads((run_dir / "manifest.json").read_text())
        assert final["time"] == "120" and manifest["status"] == "completed", (final, manifest)
        assert manifest["run_id"] == run["run_id"]
        report["checks"]["headless_validate_preview_run_inspect_replay_resume"] = {
            "status": "PASS", "run_id": run["run_id"], "time_before_resume": "30",
            "time_after_resume": final["time"], "retained_checkpoint": True,
            "replay_time": "15", "replay_did_not_advance_history": True}

        if args.check_interrupt:
            # Exercise the documented Ctrl+C coordinator path only after real commits
            # exist; initialization and checkpoint interruption are not claimed.
            interrupt_config = scratch / "interrupt.json"
            base = dict(validated["resolved"])
            base["horizon"] = 3600
            base["checkpoint_interval"] = 1000
            interrupt_config.write_text(json.dumps(base))
            interrupt_dir = scratch / "interrupted-cli"
            with (output / "08-headless-interrupt.log").open("w") as log:
                interrupted = subprocess.Popen([sys.executable, "-m", "zombie_sim.cli", "run",
                    str(interrupt_config), "--workers", "1", "--output", str(interrupt_dir)],
                    cwd=ROOT, env=ENV, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

                def advancing():
                    if interrupted.poll() is not None:
                        raise AssertionError("Headless process exited before interrupt test")
                    if not (interrupt_dir / "manifest.json").exists():
                        return False
                    try:
                        cursor = history_cursor(interrupt_dir)
                        return cursor if cursor and cursor[0] >= 30 else False
                    except sqlite3.OperationalError:
                        return False

                observed = until(advancing, timeout=90, description="headless real advancement")
                interrupted.send_signal(signal.SIGINT)
                assert interrupted.wait(timeout=90) == 0
            interrupted_manifest = json.loads((interrupt_dir / "manifest.json").read_text())
            assert interrupted_manifest["status"] == "interrupted"
            assert (interrupt_dir / "checkpoint.json").is_file()
            cli("inspect", str(interrupt_dir), label="09-inspect-interrupted")
            report["checks"]["headless_sigint_during_advancement"] = {
                "status": "PASS", "observed_cursor": observed,
                "saved_time": interrupted_manifest["time"], "checkpoint_written": True}
            interrupted = None

        launcher("gui", "--no-browser", label="10-launcher-gui")
        identity = api.call("/api/launcher")
        assert Path(identity["workspace"]).resolve() == workspace
        assert api.call("/api/runs") == []
        launcher("gui", "--no-browser", label="11-launcher-reuse")
        assert api.call("/api/launcher") == identity
        launcher("start", "small", "--workers", "1", "--horizon", "600", "--no-browser",
                 label="12-launcher-start-small")
        run_id = api.call("/api/runs")[0]["id"]
        wait_status(run_id, "running")
        worker_pids.update(item["pid"] for item in leases())
        launcher("list", label="13-launcher-list")
        launcher("pause", run_id, label="14-launcher-pause")
        paused = wait_status(run_id, "paused")
        initial = history_cursor(paused["directory"])
        time.sleep(.3)
        assert history_cursor(paused["directory"]) == initial
        launcher("resume", run_id, label="15-launcher-continue")
        until(lambda: history_cursor(paused["directory"])[0] > initial[0], description="continued history")
        launcher("stop", run_id, label="16-launcher-stop-save")
        saved = wait_status(run_id, "stopped")
        assert not leases()
        saved_cursor = history_cursor(saved["directory"])
        checkpoint_path = Path(saved["directory"]) / "worker-checkpoint.json"
        assert checkpoint_path.is_file()
        service_pid = identity["pid"]
        stop_service()
        assert all(not process_alive(pid) for pid in worker_pids)
        launcher("gui", "--no-browser", label="17-launcher-restart-same-workspace")
        identity = api.call("/api/launcher")
        assert identity["pid"] != service_pid
        assert row(run_id)["status"] == "stopped" and history_cursor(saved["directory"]) == saved_cursor
        launcher("resume", run_id, label="18-launcher-resume-saved")
        worker_pids.update(item["pid"] for item in leases())
        wait_status(run_id, "running")
        launcher("pause", run_id, label="19-launcher-pause-before-terminate")
        wait_status(run_id, "paused")
        terminate_cursor = history_cursor(saved["directory"])
        checkpoint_digest = digest(checkpoint_path)
        launcher("terminate", run_id, label="20-launcher-terminate")
        wait_status(run_id, "terminated")
        terminated = until(lambda: (current if (current := row(run_id))["resource_status"]["cleanup_complete"] else None),
                           timeout=30, description="termination worker cleanup complete")
        assert not leases() and terminated["resource_status"]["cleanup_complete"], terminated
        assert digest(checkpoint_path) == checkpoint_digest, "Termination wrote a new managed checkpoint"
        final_cursor = history_cursor(saved["directory"])
        time.sleep(.3)
        assert history_cursor(saved["directory"]) == final_cursor
        assert final_cursor[0] >= terminate_cursor[0]
        with sqlite3.connect((Path(saved["directory"]) / "run.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            assert db.execute("SELECT COUNT(*) FROM commits WHERE revision<=?", (saved_cursor[0],)).fetchone()[0] > 0
        launcher("requests", label="21-launcher-requests")
        report["checks"]["launcher_real_wrapper_lifecycle"] = {
            "status": "PASS", "run_id": run_id, "scenario_population": 24,
            "service_reused": True, "saved_run_reopened_after_service_restart": True,
            "paused_cursor": initial, "saved_cursor": saved_cursor,
            "terminated_cursor": final_cursor, "checkpoint_unchanged_on_termination": True,
            "history_retained": True, "cleanup_complete": True,
            "worker_pids": sorted(worker_pids)}
        shutil.copy2(workspace / ".launcher/service.log", output / "launcher-service.log")
        stop_service()
        assert all(not process_alive(pid) for pid in worker_pids)
        report["status"] = "PASS"
    except BaseException as error:
        report["error"] = repr(error)
        report["traceback"] = traceback.format_exc()
        report["status"] = "FAIL"
        raise
    finally:
        if interrupted is not None and interrupted.poll() is None:
            interrupted.send_signal(signal.SIGINT)
            interrupted.wait(timeout=90)
        if identity is not None:
            for item in api.call("/api/runs"):
                if item["status"] not in {"terminated", "completed", "stopped", "failed"}:
                    launcher("terminate", item["id"], label="cleanup-terminate")
            stop_service()
        assert not any(process_alive(pid) for pid in worker_pids), worker_pids
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["service_exited"] = not api.available()
        report["workers_exited"] = True
        shutil.rmtree(scratch)
        report["temporary_workspace_removed"] = not scratch.exists()
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"status": report["status"], "report": str(output / "verification.json")}))


if __name__ == "__main__":
    main()
