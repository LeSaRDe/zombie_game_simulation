"""I01 integration checks against an isolated real HTTP service and workers.

The service mode adds instrumentation and bounded cleanup/checkpoint barriers only
inside this test fixture. It never connects to the user's launcher workspace.
Run with PYTHONPATH=src .runtimeenv/bin/python implementation_checks/issue1_check.py.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
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


def until(function, timeout=60, description="condition"):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = function()
        if last:
            return last
        time.sleep(.05)
    raise AssertionError(f"Timeout waiting for {description}: {last!r}")


def alive(pid):
    try:
        return Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def process_io():
    return {name: int(value) for line in Path("/proc/self/io").read_text().splitlines()
            for name, value in [line.split(":", 1)]}


def immutable_record_hashes(database, through_revision):
    """Hash actual ordered SQLite values, retaining types and exact BLOB bytes."""
    def encode(value):
        if value is None:
            return ["null"]
        if isinstance(value, bytes):
            return ["blob", value.hex()]
        if isinstance(value, int):
            return ["integer", str(value)]
        if isinstance(value, float):
            return ["real", value.hex()]
        assert isinstance(value, str), type(value)
        return ["text", value]

    tables = {}
    for table, order in (("commits", "revision"), ("runtime_commits", "revision"), ("events", "sequence")):
        digest = hashlib.sha256()
        count = 0
        rows = database.execute(f"SELECT * FROM {table} WHERE revision<=? ORDER BY {order}", (through_revision,))
        columns = json.dumps([column[0] for column in rows.description], separators=(",", ":")).encode()
        digest.update(len(columns).to_bytes(8, "big")); digest.update(columns)
        for row in rows:
            payload = json.dumps([encode(value) for value in row], ensure_ascii=False,
                                 separators=(",", ":")).encode()
            digest.update(len(payload).to_bytes(8, "big")); digest.update(payload)
            count += 1
        tables[table] = {"rows": count, "sha256": digest.hexdigest()}
    return {"through_revision": through_revision,
            "encoding": "sha256/type-tagged-json-rows/hex-blobs/length-prefixed-v1", "tables": tables}


def barrier(directory, name, payload):
    (directory / f"{name}-entered.json").write_text(json.dumps(payload))
    deadline = time.monotonic() + 45
    while not (directory / f"{name}-release").exists():
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Test barrier {name} was not released")
        time.sleep(.025)


def instrumented_worker(root, run_id):
    """Spawn-safe wrapper: all delays are confined to this disposable fixture."""
    from zombie_sim import application
    from zombie_sim.engine import Simulation
    directory = Path(root) / "runs" / run_id
    scenario = json.loads((directory / "manifest.json").read_text())["config"]["scenario"]
    original_close = Simulation.close
    original_checkpoint = Simulation.checkpoint
    original_atomic = application._atomic_json

    def atomic(path, value):
        result = original_atomic(path, value)
        if Path(path).name == "worker-checkpoint.json":
            with (directory / "test-checkpoint-writes.jsonl").open("a") as stream:
                stream.write(json.dumps({"sha256": sha(path), "time_ns": time.time_ns()}) + "\n")
        return result

    def checkpoint(self, *args, **kwargs):
        if scenario == "issue1_checkpoint_delay":
            barrier(directory, "checkpoint", {"pid": os.getpid()})
        return original_checkpoint(self, *args, **kwargs)

    def close(self):
        if not getattr(self, "_closed", False):
            pool = getattr(self, "_pool", None)
            pids = sorted(getattr(pool, "_processes", {}) or {})
            evidence = {"coordinator": os.getpid(), "pool": pids}
            (directory / "test-processes.json").write_text(json.dumps(evidence))
            if scenario == "issue1_cleanup_delay":
                barrier(directory, "cleanup", evidence)
        return original_close(self)

    application._atomic_json = atomic
    Simulation.checkpoint = checkpoint
    Simulation.close = close
    application._run_worker(root, run_id)


def service(workspace, port):
    import uvicorn
    from zombie_sim import application
    from zombie_sim.server import create_app
    from zombie_sim.visualization import project_state, view_bundle
    application._run_worker = instrumented_worker
    app = create_app(workspace)
    manager = app.state.manager
    counters = {"state_at": 0}
    count_lock = threading.Lock()
    original_state_at = application.History.state_at

    def counted_state_at(self, *args, **kwargs):
        with count_lock:
            counters["state_at"] += 1
        return original_state_at(self, *args, **kwargs)

    application.History.state_at = counted_state_at

    @app.get("/__issue1/diagnostics")
    def diagnostics():
        return {"pid": os.getpid(), "counters": dict(counters),
                "cpu_ns": time.process_time_ns(), "io": process_io(),
                "cache": manager.snapshot_diagnostics(),
                "head_readers": manager.head_diagnostics(),
                "processes": {identity: {"pid": process.pid, "alive": process.is_alive()}
                              for identity, process in manager.processes.items()}}

    @app.get("/__issue1/audit/{identity}")
    def audit(identity: str, through_revision: int | None = None):
        row = manager._row(identity)
        directory = Path(row["directory"])
        with sqlite3.connect((directory / "run.sqlite").as_uri() + "?mode=ro", uri=True) as db:
            db.execute("BEGIN")
            frontier = db.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
            counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                      for name in ("commits", "runtime_commits", "events", "control_commands")}
            selected_revision = frontier[0] if through_revision is None else through_revision
            assert 0 <= selected_revision <= frontier[0]
            immutable_records = immutable_record_hashes(db, selected_revision)
        writes = directory / "test-checkpoint-writes.jsonl"
        processes = directory / "test-processes.json"
        return {"frontier": frontier, "counts": counts, "immutable_records": immutable_records,
                "cheap_head": manager.read_head(identity),
                "checkpoint_sha256": sha(directory / "worker-checkpoint.json"),
                "checkpoint_writes": [json.loads(line) for line in writes.read_text().splitlines()] if writes.exists() else [],
                "files": sorted(path.name for path in directory.iterdir()
                                if not path.name.startswith("test-") and not path.name.endswith(("-wal", "-shm"))),
                "processes": json.loads(processes.read_text()) if processes.exists() else None,
                "lease_count": manager.connection.execute("SELECT COUNT(*) FROM worker_leases WHERE run_id=?", (identity,)).fetchone()[0]}

    @app.get("/__issue1/barrier/{identity}/{name}/{action}")
    def fixture_barrier(identity: str, name: str, action: str):
        assert name in {"cleanup", "checkpoint"} and action in {"read", "release"}
        directory = Path(manager._row(identity)["directory"])
        if action == "release":
            (directory / f"{name}-release").touch()
        entered = directory / f"{name}-entered.json"
        return json.loads(entered.read_text()) if entered.exists() else None

    @app.get("/__issue1/cache/{identity}")
    def cache_check(identity: str):
        before_calls = counters["state_at"]
        for _ in range(30):
            manager.read_head(identity)
            manager.list_runs()
        assert counters["state_at"] == before_calls, "Cheap heads reconstructed history"
        before = manager.snapshot_diagnostics()
        # A previously unused replay key makes concurrent reconstruction cold.
        with ThreadPoolExecutor(8) as pool:
            bundles = list(pool.map(lambda generation: manager.snapshot(identity, revision=0, generation=generation), range(8)))
        after = manager.snapshot_diagnostics()
        assert after["builds"] - before["builds"] == 1, (before, after)
        assert [bundle["query_generation"] for bundle in bundles] == [str(i) for i in range(8)]
        agent = next(iter(bundles[0]["state"]["agents"]))
        original_life = bundles[0]["state"]["agents"][agent]["life"]
        bundles[0]["state"]["agents"][agent]["life"] = -123
        assert bundles[1]["state"]["agents"][agent]["life"] == original_life
        assert manager.snapshot(identity, revision=0)["state"]["agents"][agent]["life"] == original_life
        head = manager.read_head(identity)
        live = manager.snapshot(identity)
        assert live["control"]["generation"] == head["generation"]
        assert live["control"]["resource_status"] == head["resource_status"]
        return {"cheap_head_calls": 30, "parallel_readers": 8, "cold_builds": after["builds"] - before["builds"],
                "detached": True, "request_generation_preserved": True, "cache": manager.snapshot_diagnostics()}

    @app.get("/__issue1/measure/{identity}")
    def measure(identity: str):
        def measure_calls(function, repetitions):
            io_before = process_io()
            cpu = time.process_time_ns(); wall = time.perf_counter_ns(); calls = counters["state_at"]
            for _ in range(repetitions):
                function()
            cpu_elapsed = time.process_time_ns() - cpu
            wall_elapsed = time.perf_counter_ns() - wall
            io_after = process_io()
            return {"calls": repetitions, "cpu_ns": cpu_elapsed,
                    "wall_ns": wall_elapsed, "state_at_calls": counters["state_at"] - calls,
                    "io_delta": {key: io_after[key] - value for key, value in io_before.items()}}
        def old_eager_projection():
            history = manager.history(identity)
            try:
                frontier = history.revision
                state = project_state(history.state_at(None, frontier), None)
                view_bundle(state, run_id=identity, sequence=frontier, frontier=frontier)
            finally:
                history.close()
        eager = measure_calls(old_eager_projection, 5)
        cheap = measure_calls(lambda: manager.read_head(identity), 50)
        manager.snapshot(identity)
        before = manager.snapshot_diagnostics()
        cached = measure_calls(lambda: manager.snapshot(identity), 10)
        after = manager.snapshot_diagnostics()
        assert cheap["state_at_calls"] == cached["state_at_calls"] == 0
        assert before["builds"] == after["builds"]
        return {"scope": "same isolated committed history; service-process CPU, not user's observed CPU",
                "previous_eager_projection": eager, "new_idle_head": cheap, "cached_view": cached,
                "unchanged_cache_builds": before["builds"]}

    @app.get("/__issue1/head-readers/{identity}")
    def head_readers(identity: str):
        source = manager._row(identity)
        source_path = Path(source["directory"]) / "run.sqlite"
        fd_before = len(list(Path("/proc/self/fd").iterdir()))
        with tempfile.TemporaryDirectory(prefix="head-readers-", dir=workspace) as temporary:
            probe = application.RunManager(temporary)
            remaining_connections = []
            try:
                capacity = probe.head_diagnostics()["capacity"]
                directories = []
                for index in range(capacity + 3):
                    directory = Path(temporary) / "runs" / f"copy-{index}"
                    directory.mkdir(parents=True)
                    original = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
                    copied = sqlite3.connect(directory / "run.sqlite")
                    try:
                        original.backup(copied)
                    finally:
                        copied.close(); original.close()
                    with probe.connection:
                        probe.connection.execute(
                            "INSERT INTO runs(id,directory,config,status,generation,frontier) VALUES(?,?,?,?,?,?)",
                            (f"copy-{index}", str(directory), source["config"], "terminated",
                             source["generation"], source["frontier"]))
                    directories.append(directory)

                # This separate copied ledger holds a genuine multi-megabyte
                # WAL. A cached metadata reader must not pin its read transaction.
                writer = sqlite3.connect(directories[0] / "run.sqlite")
                try:
                    writer.execute("PRAGMA journal_mode=WAL")
                    writer.execute("PRAGMA wal_autocheckpoint=0")
                    writer.execute("CREATE TABLE fixture_wal(payload BLOB)")
                    writer.executemany("INSERT INTO fixture_wal VALUES(?)", [(b"x" * 1048576,)] * 8)
                    writer.commit()
                    wal_bytes = (directories[0] / "run.sqlite-wal").stat().st_size
                    assert wal_bytes >= 8 * 1048576
                    first_head = probe.read_head("copy-0")
                    first_connection = probe._head_readers["copy-0"].history.connection
                    reader_before = probe.head_diagnostics()
                    for _ in range(40):
                        assert probe.read_head("copy-0")["revision"] == first_head["revision"]
                        assert probe._head_readers["copy-0"].history.connection is first_connection
                    reader_after = probe.head_diagnostics()
                    assert reader_after["opened"] == reader_before["opened"]
                    assert not first_connection.in_transaction
                    checkpoint = writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                    assert checkpoint == (0, 0, 0), checkpoint
                finally:
                    writer.close()

                for index in range(1, capacity + 3):
                    probe.read_head(f"copy-{index}")
                    current = probe.head_diagnostics()
                    assert current["entries"] <= capacity and current["active_connections"] <= capacity
                evicted = probe.head_diagnostics()
                assert evicted["closed"] >= 3
                try:
                    first_connection.execute("SELECT 1")
                except sqlite3.ProgrammingError:
                    pass
                else:
                    raise AssertionError("Evicted head connection remained open")
                remaining_connections = [entry.history.connection for entry in probe._head_readers.values()]
                fd_peak = len(list(Path("/proc/self/fd").iterdir()))
                assert fd_peak <= fd_before + 3 * capacity + 8, (fd_before, fd_peak, capacity)
            finally:
                probe.close()
            closed = probe.head_diagnostics()
            assert closed["active_connections"] == closed["entries"] == 0
            for connection in remaining_connections:
                try:
                    connection.execute("SELECT 1")
                except sqlite3.ProgrammingError:
                    pass
                else:
                    raise AssertionError("Manager shutdown left a cached head connection open")
            fd_after = len(list(Path("/proc/self/fd").iterdir()))
            assert fd_after <= fd_before + 1, (fd_before, fd_after)
            return {"copied_real_ledgers": capacity + 3, "retained_wal_bytes": wal_bytes,
                    "repeated_reads": 40, "opened_before": reader_before["opened"],
                    "opened_after": reader_after["opened"], "same_connection_reused": True,
                    "checkpoint_with_cached_reader": checkpoint, "no_pinned_read_transaction": True,
                    "evicted": evicted, "closed": closed, "evicted_and_remaining_connections_closed": True,
                    "file_descriptors": {"before": fd_before, "peak": fd_peak, "after": fd_after}}

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


class Api:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, path, body=None):
        request = Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=120) as response:
            return json.load(response)

    def row(self, identity):
        return next(row for row in self.call("/api/runs") if row["id"] == identity)

    def command(self, identity, operation, wait=True, **extra):
        response = self.call(f"/api/runs/{identity}/commands", {"operation": operation,
                             "command_id": str(uuid.uuid4()), **extra})
        if wait:
            response = until(lambda: (value if (value := self.call(f'/api/commands/{response["command_id"]}'))["status"] != "pending" else None),
                             timeout=120, description=f"{operation} receipt")
            assert response["status"] == "applied", response
        return response


def terminal_evidence(api, identity, checkpoint, receipt=None, prior_audit=None):
    row = until(lambda: (row if (row := api.row(identity))["resource_status"]["cleanup_complete"] else None),
                timeout=60, description="worker cleanup")
    assert row["status"] == "terminated" and not row["resource_status"]["worker_active"]
    prior_records = prior_audit["immutable_records"] if prior_audit else None
    audit_path = f"/__issue1/audit/{identity}"
    if prior_records:
        audit_path += f'?through_revision={prior_records["through_revision"]}'
    before = api.call(audit_path)
    assert str(before["cheap_head"]["revision"]) == str(before["frontier"][0]), "Cached head missed committed writer progress"
    assert before["checkpoint_sha256"] == checkpoint
    if prior_audit:
        assert before["counts"]["commits"] >= prior_audit["counts"]["commits"]
        assert before["counts"]["runtime_commits"] >= prior_audit["counts"]["runtime_commits"]
        assert before["counts"]["events"] >= prior_audit["counts"]["events"]
        assert set(prior_audit["files"]) <= set(before["files"])
        assert before["immutable_records"] == prior_records, "Pre-termination immutable audit records changed"
    if receipt:
        assert str(before["frontier"][0]) == str(receipt["revision"])
    time.sleep(.5)
    after = api.call(audit_path)
    assert before["frontier"] == after["frontier"] and before["counts"] == after["counts"]
    assert before["immutable_records"] == after["immutable_records"], "Terminal immutable audit records changed"
    assert set(before["files"]) <= set(after["files"])
    assert after["lease_count"] == 0
    processes = after["processes"]
    assert processes and not alive(processes["coordinator"])
    assert all(not alive(pid) for pid in processes["pool"]), processes
    return {"frontier": after["frontier"], "audit_counts": after["counts"],
            "immutable_audit_retention": {"verified_against_pre_termination": prior_records is not None,
                                         "unchanged_after_cleanup": True, **after["immutable_records"]},
            "cached_head_matches_final_frontier": True,
            "checkpoint_sha256": checkpoint, "retained_files": after["files"],
            "exited_processes": processes, "cleanup_complete": True}


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="zombie-issue1-") as workspace:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NODE_PATH=NODE_MODULES)
        with (output / "service.log").open("w") as log:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace, "--port", str(port)],
                                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            api = Api(port)
            report = {"passed": False, "workspace": workspace, "port": port, "service_pid": process.pid}
            try:
                def ready():
                    if process.poll() is not None:
                        raise AssertionError("Fixture service exited; inspect service.log")
                    try:
                        return api.call("/__issue1/diagnostics")
                    except OSError:
                        return None
                until(ready, description="isolated service")
                small = {"scenario": "issue1_cleanup_delay", "horizon": 120,
                         "population": {"humans": 16, "zombies": 4}, "checkpoint_interval": 1000,
                         "execution": {"workers": 2, "parallel_min_agents": 2}}
                identity = api.call("/api/runs", {"config": small, "command_id": str(uuid.uuid4())})["run_id"]
                until(lambda: api.row(identity)["status"] == "paused", description="small initialization")
                api.command(identity, "step")
                before = api.call(f"/__issue1/audit/{identity}")
                report["cache"] = api.call(f"/__issue1/cache/{identity}")
                browser = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue1.cjs"),
                                          api.base, identity, str(output)], cwd=ROOT, env=env,
                                         text=True, capture_output=True, timeout=150)
                (output / "browser.log").write_text(browser.stdout + browser.stderr)
                assert browser.returncode == 0, browser.stdout + browser.stderr
                report["browser"] = json.loads((output / "browser.json").read_text())
                report["small_browser_open"] = terminal_evidence(api, identity, before["checkpoint_sha256"], report["browser"]["terminate_receipt"], before)
                report["small_measurement"] = api.call(f"/__issue1/measure/{identity}")

                # A queued terminate must wait for an already executing checkpoint.
                checkpoint_config = dict(small, scenario="issue1_checkpoint_delay")
                checkpoint_id = api.call("/api/runs", {"config": checkpoint_config, "command_id": str(uuid.uuid4())})["run_id"]
                until(lambda: api.row(checkpoint_id)["status"] == "paused", description="checkpoint fixture")
                prior_checkpoint = api.call(f"/__issue1/audit/{checkpoint_id}")
                checkpoint_command = api.command(checkpoint_id, "checkpoint", wait=False, name="already-in-progress")
                until(lambda: api.call(f"/__issue1/barrier/{checkpoint_id}/checkpoint/read"), description="checkpoint entered")
                terminate = api.command(checkpoint_id, "terminate", wait=False)
                pending = api.row(checkpoint_id)["resource_status"]
                assert pending["phase"] == "termination_requested" and not pending["cleanup_complete"], pending
                assert api.call(f'/api/commands/{terminate["command_id"]}')["status"] == "pending"
                api.call(f"/__issue1/barrier/{checkpoint_id}/checkpoint/release")
                receipt = until(lambda: (value if (value := api.call(f'/api/commands/{terminate["command_id"]}'))["status"] == "applied" else None))
                audit = api.call(f"/__issue1/audit/{checkpoint_id}")
                assert len(audit["checkpoint_writes"]) == 2, audit["checkpoint_writes"]
                assert api.call(f'/api/commands/{checkpoint_command["command_id"]}')["status"] == "applied"
                report["checkpoint_already_in_progress"] = terminal_evidence(api, checkpoint_id, audit["checkpoint_writes"][-1]["sha256"], receipt, prior_checkpoint)
                report["checkpoint_already_in_progress"]["pending_phase"] = pending

                from zombie_sim.config import baseline_config
                baseline = baseline_config()
                baseline.update(scenario="issue1_baseline_1000", horizon=120, checkpoint_interval=1000)
                baseline["execution"] = {"workers": 2}
                full_id = api.call("/api/runs", {"config": baseline, "command_id": str(uuid.uuid4())})["run_id"]
                until(lambda: api.row(full_id)["status"] == "paused", timeout=150, description="1000-agent initialization")
                initial = api.call(f"/api/runs/{full_id}/view")
                assert len(initial["state"]["agents"]) == 1000
                report["full_population_placement"] = api.row(full_id)["config"]["placement"]
                before = api.call(f"/__issue1/audit/{full_id}")
                api.command(full_id, "start")
                until(lambda: int(api.call(f"/__issue1/audit/{full_id}")["frontier"][0]) > before["frontier"][0], timeout=120, description="real baseline progress")
                before_terminate = api.call(f"/__issue1/audit/{full_id}")
                receipt = api.command(full_id, "terminate")
                report["baseline_1000_browser_closed"] = terminal_evidence(api, full_id, before["checkpoint_sha256"], receipt, before_terminate)
                assert report["baseline_1000_browser_closed"]["exited_processes"]["pool"], "Full baseline did not exercise a worker pool"
                report["full_population_measurement"] = api.call(f"/__issue1/measure/{full_id}")

                # Repeat the full population with the browser attached, at a
                # committed paused boundary, including delayed real cleanup.
                open_config = dict(baseline, scenario="issue1_cleanup_delay")
                open_id = api.call("/api/runs", {"config": open_config, "command_id": str(uuid.uuid4())})["run_id"]
                until(lambda: api.row(open_id)["status"] == "paused", timeout=150, description="browser-open 1000-agent initialization")
                api.command(open_id, "step")
                open_view = api.call(f"/api/runs/{open_id}/view")
                assert len(open_view["state"]["agents"]) == 1000
                open_before = api.call(f"/__issue1/audit/{open_id}")
                open_output = output / "baseline-browser-open"
                open_output.mkdir(exist_ok=True)
                browser = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue1.cjs"),
                                          api.base, open_id, str(open_output)], cwd=ROOT, env=env,
                                         text=True, capture_output=True, timeout=150)
                (open_output / "browser.log").write_text(browser.stdout + browser.stderr)
                assert browser.returncode == 0, browser.stdout + browser.stderr
                report["baseline_1000_browser"] = json.loads((open_output / "browser.json").read_text())
                report["baseline_1000_browser_open"] = terminal_evidence(api, open_id, open_before["checkpoint_sha256"],
                    report["baseline_1000_browser"]["terminate_receipt"], open_before)
                assert report["baseline_1000_browser_open"]["exited_processes"]["pool"]
                report["persistent_head_readers"] = api.call(f"/__issue1/head-readers/{identity}")
                report["final_diagnostics"] = api.call("/__issue1/diagnostics")
                assert all(not item["alive"] for item in report["final_diagnostics"]["processes"].values())
                report["passed"] = True
            finally:
                (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
                # Release only this fixture's barriers, then gracefully close its service.
                for directory in (Path(workspace) / "runs").glob("*"):
                    for name in ("cleanup", "checkpoint"):
                        (directory / f"{name}-release").touch()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=45)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve")
    parser.add_argument("--port", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue1")
    args = parser.parse_args()
    if args.serve:
        service(args.serve, args.port)
    else:
        check(args.output.absolute())
