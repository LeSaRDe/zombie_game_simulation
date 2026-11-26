"""Shared CLI/HTTP application services and separately managed run processes."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time
import traceback
import uuid

from .storage import History, canonical, exact_time
from .visualization import project_state, view_bundle, cohort_summary, cohort_members


class RunInitializing(ValueError):
    """A known run exists but has not published its first complete revision."""


TERMINAL_STATES = {"stopped", "completed", "failed", "terminated"}


def _same_command_request(left, right):
    """Compare immutable JSON payloads, excluding only their already-keyed ID."""
    def same(a,b):
        if isinstance(a,dict) and isinstance(b,dict):
            return a.keys()==b.keys() and all(same(a[key],b[key]) for key in a)
        if isinstance(a,list) and isinstance(b,list):
            return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
        if isinstance(a,bool) or isinstance(b,bool):return type(a) is type(b) and a==b
        if isinstance(a,(int,float)) and isinstance(b,(int,float)):return a==b
        return type(a) is type(b) and a==b
    return same({key:value for key,value in left.items() if key!="command_id"},
                {key:value for key,value in right.items() if key!="command_id"})


def _check_command_request(record,request):
    if not _same_command_request(json.loads(record["request"]),request):
        raise ValueError("Command ID already belongs to different request content")


def _atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w") as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def _connect(path):
    connection = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    return connection


def _journal(path):
    connection = _connect(path)
    connection.executescript("""
      CREATE TABLE IF NOT EXISTS runs (
        id TEXT PRIMARY KEY, directory TEXT NOT NULL, config TEXT NOT NULL,
        status TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0,
        frontier TEXT NOT NULL DEFAULT '{}', error TEXT, parent TEXT);
      CREATE TABLE IF NOT EXISTS commands (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL, operation TEXT NOT NULL,
        request TEXT NOT NULL, status TEXT NOT NULL, response TEXT,
        created REAL NOT NULL);
      CREATE INDEX IF NOT EXISTS pending_commands ON commands(run_id,status,created);
      CREATE TABLE IF NOT EXISTS views (
        run_id TEXT NOT NULL, id TEXT NOT NULL, definition TEXT NOT NULL,
        PRIMARY KEY(run_id,id));
      CREATE TABLE IF NOT EXISTS worker_leases (
        run_id TEXT PRIMARY KEY, pid INTEGER NOT NULL, heartbeat REAL NOT NULL);
    """)
    connection.commit()
    return connection


def _restore_engine(payload, directory):
    from .engine import Simulation
    if hasattr(Simulation, "from_serialized"):
        return Simulation.from_serialized(payload, history_path=str(directory / "run.sqlite"))
    raise RuntimeError("Engine does not support serialized continuation")


def _run_worker(root, run_id):
    """Single coordinator process; browser disconnects do not own its lifetime."""
    from .engine import Simulation
    journal = _journal(Path(root) / "manager.sqlite")
    row = journal.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    directory = Path(row["directory"])
    lease_file = (directory / "worker.lock").open("a+")
    try:
        import fcntl
        fcntl.flock(lease_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, ImportError):
        lease_file.close()
        journal.close()
        return
    with journal:
        journal.execute("INSERT OR REPLACE INTO worker_leases VALUES(?,?,?)", (run_id, os.getpid(), time.time()))
    config = json.loads(row["config"])
    control = {"status": "paused", "generation": int(row["generation"]), "processed": {}, "pacing": 1.0}
    simulation = None
    try:
        checkpoint = directory / "worker-checkpoint.json"
        ledger_path = directory / "run.sqlite"
        has_runtime = False
        if ledger_path.exists():
            reader = History(ledger_path, read_only=True)
            try:
                has_runtime = reader.runtime_at() is not None
            finally:
                reader.close()
        requested_restore = directory / "requested-restore.json"
        if requested_restore.exists():
            from .runtime import restore
            selected = json.loads(requested_restore.read_text())
            simulation = restore(Simulation, selected["path"], history_path=ledger_path)
            control.update(simulation.history.get_metadata("control_state", {}) or {})
            control["status"] = "paused"
            requested_restore.unlink()
        elif has_runtime:
            from .runtime import restore_revision
            simulation = restore_revision(Simulation, ledger_path, output_history_path=ledger_path)
            control.update(simulation.history.get_metadata("control_state", {}) or {})
            if control["status"] in {"stopped", "failed", "interrupted"}:
                control["status"] = "paused"
        elif checkpoint.exists():
            envelope = json.loads(checkpoint.read_text())
            if envelope.get("checksum") != hashlib.sha256(canonical({k: v for k, v in envelope.items() if k != "checksum"}).encode()).hexdigest():
                raise ValueError("Managed checkpoint checksum mismatch")
            control = envelope["control"]
            simulation = _restore_engine(envelope["engine"], directory)
            control["status"] = "paused"
        else:
            execution = config.get("execution", {})
            simulation = Simulation(config, history_path=str(directory / "run.sqlite"),
                                    backend=config.get("storage", {}).get("backend", "memory"), workers=execution.get("workers", 1), run_id=run_id)

        def apply_semantic(active):
            simulation._active_control_command = active
            operation, request = active["operation"], active["request"]
            if operation == "step":
                simulation.step(timestamp=False, return_snapshot=False)
            elif operation in {"step_timestamp", "advance"}:
                simulation.advance_until(active["target"], return_snapshot=False)
            elif operation == "intervene":
                if request.get("apply_now") and exact_time(request.get("time", simulation.time)) != simulation.time:
                    raise ValueError("Apply now requires the current simulation time")
                simulation.intervene(request["change"], at=request.get("time"), id=active["id"])
                if request.get("apply_now"):
                    simulation.advance_until(simulation.time, return_snapshot=False)
            response = simulation.history.command_result(active["id"])
            if response is None:
                desired = active["desired_control"]
                response = {"command_id": active["id"], "run_id": run_id, "status": "applied",
                            "time": str(simulation.time), "revision": str(simulation.revision),
                            "generation": desired["generation"], "run_status": desired["status"],
                            "pacing": desired["pacing"], "control": desired}
                simulation.history.finish_command(response, desired)
            control.update(response.get("control", active["desired_control"]))
            control["processed"][active["id"]] = response
            simulation._active_control_command = None
            return response

        # A semantic result and its command acknowledgement share the run ledger
        # transaction. Reconcile a lost manager/HTTP ACK before processing retries.
        with journal:
            for response in simulation.history.command_results():
                if response.get("run_id") != run_id:
                    continue
                control["processed"][response["command_id"]] = response
                journal.execute("UPDATE commands SET status=?,response=? WHERE id=?", (response["status"], canonical(response), response["command_id"]))
        active = simulation.history.get_metadata("active_control_command")
        if active and active.get("operation") in {"step", "step_timestamp", "advance", "intervene"}:
            response = apply_semantic(active)
            with journal:
                journal.execute("UPDATE commands SET status=?,response=? WHERE id=?", (response["status"], canonical(response), response["command_id"]))
        if simulation.run_status == "COMPLETED":
            control["status"] = "completed"

        def boundary():
            return {"time": str(simulation.time), "revision": str(simulation.revision),
                    "generation": control["generation"], "status": control["status"], "pacing": control["pacing"],
                    "workers": simulation.workers, "worker_budget": getattr(simulation, "_runtime_worker_budget", {})}

        def publish(save=False):
            if save:
                payload = {"schema": "zombie-sim/managed-checkpoint-v1", "engine": simulation.serialize(), "control": control}
                payload["checksum"] = hashlib.sha256(canonical(payload).encode()).hexdigest()
                _atomic_json(checkpoint, payload)
            with journal:
                journal.execute("UPDATE runs SET status=?,generation=?,frontier=?,error=NULL WHERE id=?",
                                (control["status"], control["generation"], canonical(boundary()), run_id))
                journal.execute("UPDATE worker_leases SET heartbeat=? WHERE run_id=? AND pid=?", (time.time(), run_id, os.getpid()))

        publish(save=True)
        last_runtime_time = simulation.time
        last_runtime_revision = simulation.revision
        def controls_waiting():
            return journal.execute("SELECT 1 FROM commands WHERE run_id=? AND status='pending' AND operation NOT IN ('create','branch') LIMIT 1", (run_id,)).fetchone() is not None

        while control["status"] not in TERMINAL_STATES:
            pending = journal.execute("SELECT * FROM commands WHERE run_id=? AND status='pending' AND operation NOT IN ('create','branch') ORDER BY created,id", (run_id,)).fetchall()
            for command in pending:
                request = json.loads(command["request"])
                operation = command["operation"]
                try:
                    if request.get("generation") is not None and int(request["generation"]) != control["generation"]:
                        raise ValueError(f"Stale control generation: refresh generation {control['generation']}")
                    if request.get("revision") is not None and int(request["revision"]) != simulation.revision:
                        raise ValueError("The selected revision is stale; refresh before applying this operation")
                    if operation in {"start", "continue", "resume"}:
                        control["status"] = "running"
                    elif operation == "pause":
                        control["status"] = "paused"
                    elif operation == "script":
                        if control["status"] != "paused":
                            raise ValueError("Pause the run before submitting scripted research commands")
                        from .commands import execute_script_command
                        simulation.inject_random_values(request.get("draws", []))
                        desired = {"status": "paused", "generation": control["generation"] + 1, "pacing": control["pacing"]}
                        step = request["step"]
                        payload = {key: value for key, value in step.items() if key != "op"}
                        if step["op"] == "submit":
                            payload = step["intent"]
                        semantic_response = execute_script_command(simulation, step["op"], payload, command["id"], desired_control=desired)
                        control.update(semantic_response.get("control", desired))
                    elif operation in {"step", "step_timestamp", "advance", "intervene"}:
                        if operation != "intervene" and control["status"] != "paused":
                            raise ValueError("Pause the run before stepping or advancing to a time")
                        desired = {"status": control["status"], "generation": control["generation"] + 1, "pacing": control["pacing"]}
                        target = request.get("time", str(simulation.next_event_time())) if operation == "advance" else str(simulation.next_event_time())
                        active = {"id": command["id"], "operation": operation, "request": request, "target": str(target), "desired_control": desired}
                        existing = simulation.history.begin_command(active)
                        if existing is None:
                            semantic_response = apply_semantic(active)
                        else:
                            semantic_response = existing
                            control.update(existing.get("control", desired))
                    elif operation == "stop":
                        control["status"] = "stopped"
                    elif operation == "terminate":
                        # Do not create a checkpoint or erase already committed
                        # audit data. This run cannot subsequently be resumed.
                        control["status"] = "terminated"
                    elif operation == "checkpoint":
                        name = request.get("name") or f"revision-{simulation.revision}"
                        if not isinstance(name, str) or not name or any(not (char.isalnum() or char in "-_") for char in name):
                            raise ValueError("Checkpoint names may contain letters, digits, hyphens and underscores")
                        simulation.checkpoint(directory / "checkpoints" / f"{name}.json")
                    elif operation == "pace":
                        pace = request.get("pacing", 1)
                        if pace not in (0, 0.25, 1, 4):
                            raise ValueError("Pacing must be 0 (fastest), 0.25, 1 or 4")
                        control["pacing"] = pace
                    else:
                        raise ValueError(f"Unknown operation {operation!r}")
                    if operation in {"step", "step_timestamp", "advance", "intervene", "script"}:
                        response = semantic_response
                    else:
                        control["generation"] += 1
                        response = {"command_id": command["id"], "run_id": run_id, "status": "applied", **boundary()}
                        response["status"] = "applied"
                        response["run_status"] = control["status"]
                        response["control"] = {key: control[key] for key in ("status", "generation", "pacing")}
                        simulation.history.finish_command(response, response["control"])
                except (ValueError, KeyError, RuntimeError) as error:
                    response = {"command_id": command["id"], "run_id": run_id, "status": "rejected", "error": str(error), **boundary()}
                    response["status"] = "rejected"
                    simulation._active_control_command = None
                    simulation.history.finish_command(response, {key: control[key] for key in ("status", "generation", "pacing")})
                control["processed"][command["id"]] = response
                # The runtime and command journals already make this boundary
                # restartable. Serializing the whole world on pause/continue
                # needlessly keeps CPUs busy after the semantic stop and delays
                # publication of the new control generation.
                publish(save=operation in {"checkpoint", "stop"})
                with journal:
                    journal.execute("UPDATE commands SET status=?,response=? WHERE id=?", (response["status"], canonical(response), command["id"]))
                if control["status"] in TERMINAL_STATES:
                    break
            if control["status"] == "running":
                started = time.monotonic()
                old_time = simulation.time
                horizon = exact_time(config.get("horizon", config.get("simulation", {}).get("horizon", 1800)))
                target = min(horizon, old_time + 1)
                simulation.advance_until(target, max_events=250, return_snapshot=False, should_yield=controls_waiting)
                if not controls_waiting() and simulation.time < target and (not simulation.queue or simulation.queue[0][0] > target) and simulation.run_status != "COMPLETED":
                    simulation.advance_until(target, return_snapshot=False, should_yield=controls_waiting)
                if simulation.run_status == "COMPLETED" or (simulation.time >= horizon and (not simulation.queue or simulation.queue[0][0] > horizon)):
                    control["status"] = "completed"
                save = not controls_waiting() and (simulation.time - last_runtime_time >= exact_time(config.get("checkpoint_interval", 30))
                        or simulation.revision - last_runtime_revision >= int(config.get("checkpoint_transactions", 50000))
                        or control["status"] == "completed")
                publish(save=save)
                if save:
                    last_runtime_time, last_runtime_revision = simulation.time, simulation.revision
                if control["pacing"]:
                    wait = max(0, float(simulation.time - old_time) / control["pacing"] - (time.monotonic() - started))
                    # Short waits keep run-control receipt responsive.
                    deadline = time.monotonic() + wait
                    while time.monotonic() < deadline:
                        if journal.execute("SELECT 1 FROM commands WHERE run_id=? AND status='pending' LIMIT 1", (run_id,)).fetchone():
                            break
                        time.sleep(min(0.025, max(0, deadline - time.monotonic())))
            elif control["status"] == "paused":
                time.sleep(0.025)
        publish(save=control["status"] != "terminated")
    except BaseException as error:
        with journal:
            journal.execute("UPDATE runs SET status='failed',error=? WHERE id=?", (f"{type(error).__name__}: {error}", run_id))
        (directory / "failure.log").write_text(traceback.format_exc())
    finally:
        with journal:
            for pending in journal.execute("SELECT id FROM commands WHERE run_id=? AND status='pending' AND operation NOT IN ('create','branch')", (run_id,)).fetchall():
                response = {"command_id": pending["id"], "run_id": run_id, "status": "rejected",
                            "error": "The run worker stopped before this command could be applied.",
                            "time": str(simulation.time) if simulation else "0", "revision": str(simulation.revision) if simulation else "0"}
                journal.execute("UPDATE commands SET status='rejected',response=? WHERE id=?", (canonical(response), pending["id"]))
        if simulation is not None:
            simulation.close()
        with journal:
            journal.execute("DELETE FROM worker_leases WHERE run_id=? AND pid=?", (run_id, os.getpid()))
        journal.close()
        lease_file.close()


class RunManager:
    def __init__(self, root="experiments"):
        self.root = Path(root).absolute()
        self.root.mkdir(parents=True, exist_ok=True)
        self.connection = _journal(self.root / "manager.sqlite")
        self.lock = threading.RLock()
        self.processes = {}
        candidates = [self.root]
        run_directory = self.root / "runs"
        if run_directory.is_dir():
            candidates.extend(path for path in run_directory.iterdir() if path.is_dir() and not path.name.startswith("."))
        for directory in candidates:
            manifest_path = directory / "manifest.json"
            if not manifest_path.is_file() or not (directory / "run.sqlite").is_file():
                continue
            manifest = json.loads(manifest_path.read_text())
            identity = manifest.get("run_id")
            if not identity or "config" not in manifest:
                continue
            if self.connection.execute("SELECT 1 FROM runs WHERE id=?", (identity,)).fetchone():
                continue
            history = History(directory / "run.sqlite", read_only=True)
            try:
                state = history.state_at()
            finally:
                history.close()
            status = manifest.get("status", "interrupted")
            if status not in TERMINAL_STATES:
                status = "interrupted"
            frontier = {"time": str(state.get("time", 0)), "revision": str(state.get("revision", 0)), "generation": 0, "status": status, "pacing": 0}
            with self.connection:
                self.connection.execute("INSERT INTO runs(id,directory,config,status,frontier,parent) VALUES(?,?,?,?,?,?)", (identity, str(directory), canonical(manifest["config"]), status, canonical(frontier), canonical(manifest.get("parent")) if manifest.get("parent") else None))

    def list_runs(self):
        with self.lock:
            rows = self.connection.execute("SELECT * FROM runs ORDER BY rowid DESC").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["config"] = json.loads(item["config"])
                item["frontier"] = json.loads(item["frontier"])
                process = self.processes.get(item["id"])
                if process is not None and not process.is_alive() and item["status"] in {"running", "paused", "initializing"}:
                    item["status"] = "interrupted"
                    item["error"] = "Worker exited. Resume from the saved boundary."
                result.append(item)
            return result

    def _row(self, run_id):
        # All uses of the shared journal connection participate in one lock,
        # including read paths called by concurrent HTTP/WebSocket threads.
        with self.lock:
            row = self.connection.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown run {run_id}")
        return row

    def launch_worker(self, run_id):
        if self._row(run_id)["status"] == "terminated":
            raise ValueError("Terminated runs cannot be resumed; create a new experiment")
        old = self.processes.get(run_id)
        if old is not None and old.is_alive():
            if self._row(run_id)["status"] in {"stopped", "failed", "interrupted"}:
                old.join(timeout=2)
                if old.is_alive():
                    raise ValueError("The previous worker is still saving its final boundary; retry resume shortly")
            else:
                return
        lease = self.connection.execute("SELECT pid FROM worker_leases WHERE run_id=?", (run_id,)).fetchone()
        if lease:
            try:
                os.kill(lease[0], 0)
                return
            except ProcessLookupError:
                pass
        process = multiprocessing.get_context("spawn").Process(target=_run_worker, args=(str(self.root), run_id), daemon=False)
        process.start()
        self.processes[run_id] = process

    def create(self, config, command_id=None, *, start=False, parent=None):
        from .config import resolve_config
        resolved = resolve_config(config)
        if hasattr(resolved, "to_dict"):
            resolved = resolved.to_dict()
        command_id = command_id or str(uuid.uuid4())
        with self.lock:
            existing = self.connection.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            if existing:
                if existing["operation"] != "create":
                    raise ValueError("Command ID already belongs to a different operation")
                _check_command_request(existing,{"config":config,"start":start})
                response = json.loads(existing["response"])
                saved_request = json.loads(existing["request"])
                row = self._row(response["run_id"])
                if row["status"] == "initializing":
                    directory = Path(row["directory"])
                    directory.mkdir(parents=True, exist_ok=True)
                    for name in ("checkpoints", "exports", "views", "artifacts"):
                        (directory / name).mkdir(exist_ok=True)
                    _atomic_json(directory / "manifest.json", {"run_id": row["id"], "config": json.loads(row["config"]), "parent": json.loads(row["parent"]) if row["parent"] else None})
                    self.launch_worker(row["id"])
                if saved_request.get("start", start):
                    self.command(row["id"], "start", {"command_id": command_id + ":start"}, wait=False)
                return response
            run_id = uuid.uuid4().hex
            directory = self.root / "runs" / run_id
            response = {"command_id": command_id, "run_id": run_id, "status": "applied", "generation": 0}
            # Reserve identity before filesystem/process work. Retry reconciles
            # the same row rather than creating another experiment identity.
            with self.connection:
                self.connection.execute("INSERT INTO runs(id,directory,config,status,parent) VALUES(?,?,?,?,?)", (run_id, str(directory), canonical(resolved), "initializing", canonical(parent) if parent else None))
                self.connection.execute("INSERT INTO commands VALUES(?,?,?,?,?,?,?)", (command_id, run_id, "create", canonical({"config": config, "start": start}), "applied", canonical(response), time.time()))
            directory.mkdir(parents=True, exist_ok=True)
            for name in ("checkpoints", "exports", "views", "artifacts"):
                (directory / name).mkdir(exist_ok=True)
            _atomic_json(directory / "manifest.json", {"run_id": run_id, "config": resolved, "parent": parent, "created": time.time()})
            self.launch_worker(run_id)
            if start:
                self.command(run_id, "start", {"command_id": command_id + ":start"}, wait=False)
            return response

    def command(self, run_id, operation, request=None, *, wait=True):
        request = dict(request or {})
        command_id = request.setdefault("command_id", str(uuid.uuid4()))
        with self.lock:
            run = self._row(run_id)
            old = self.connection.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            if old:
                if old["run_id"] != run_id or old["operation"] != operation:
                    raise ValueError("Command ID already belongs to a different operation")
                _check_command_request(old,request)
                if old["status"]=="pending":self.launch_worker(run_id)
                return json.loads(old["response"]) if old["response"] else {"command_id": command_id, "status": "pending", "run_id": run_id}
            if run["status"] in {"completed", "terminated"}:
                raise ValueError(f"{run['status'].capitalize()} runs are immutable; create a new run")
            if operation not in {"start", "continue", "resume", "pause", "step", "step_timestamp", "advance", "intervene", "script", "stop", "terminate", "checkpoint", "pace"}:
                raise ValueError(f"Unknown operation {operation!r}")
            old_worker = self.processes.get(run_id)
            if run["status"] in {"stopped", "failed", "interrupted"} and old_worker is not None and old_worker.is_alive():
                old_worker.join(timeout=2)
                if old_worker.is_alive():
                    raise ValueError("The previous worker is still saving its final boundary; retry resume shortly")
            with self.connection:
                self.connection.execute("INSERT INTO commands VALUES(?,?,?,?,?,?,?)", (command_id, run_id, operation, canonical(request), "pending", None, time.time()))
            self.launch_worker(run_id)
        if wait:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                response = self.command_result(command_id)
                if response["status"] != "pending":
                    return response
                time.sleep(0.025)
        return {"command_id": command_id, "run_id": run_id, "status": "pending"}

    def command_result(self, command_id):
        with self.lock:
            row = self.connection.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            if row is None:
                raise KeyError(command_id)
            if row["status"] == "pending" and row["operation"] not in {"create", "branch"}:
                try:
                    history = self.history(row["run_id"])
                    try:
                        durable = history.command_result(command_id)
                    finally:
                        history.close()
                except (ValueError, sqlite3.OperationalError):
                    durable = None
                if durable:
                    with self.connection:
                        self.connection.execute("UPDATE commands SET status=?,response=? WHERE id=?", (durable["status"], canonical(durable), command_id))
                        # The semantic/control ACK can become durable before
                        # the worker finishes writing its optional checkpoint
                        # and publishes manager.sqlite. Expose the acknowledged
                        # generation immediately, or the next GUI/API command
                        # can be built from a generation we already superseded.
                        run = self._row(row["run_id"])
                        acknowledged = int(durable.get("generation", run["generation"]))
                        if acknowledged > run["generation"]:
                            frontier = json.loads(run["frontier"])
                            if int(durable.get("revision", 0)) >= int(frontier.get("revision", 0)):
                                frontier.update(time=durable.get("time", "0"), revision=str(durable.get("revision", 0)))
                            control = durable.get("control", {})
                            status = durable.get("run_status", control.get("status", run["status"]))
                            frontier.update(generation=acknowledged, status=status,
                                            pacing=durable.get("pacing", control.get("pacing", frontier.get("pacing", 1))))
                            self.connection.execute("UPDATE runs SET generation=?,status=?,frontier=? WHERE id=?",
                                                    (acknowledged, status, canonical(frontier), row["run_id"]))
                    return durable
            return json.loads(row["response"]) if row["response"] else {"command_id": command_id, "run_id": row["run_id"], "status": row["status"]}

    def history(self, run_id):
        run = self._row(run_id)
        path = Path(run["directory"]) / "run.sqlite"
        if not path.exists():
            if run["status"] == "failed":
                raise ValueError(run["error"] or "Run initialization failed")
            raise RunInitializing("Run initialization is still in progress")
        try:
            history = History(path, read_only=True)
            if history.revision < 0:
                history.close()
                raise RunInitializing("Run initialization has not published a complete revision yet")
            return history
        except sqlite3.OperationalError as error:
            if run["status"] == "initializing" and "no such table" in str(error):
                raise RunInitializing("Run initialization is still creating its history") from error
            raise

    def snapshot(self, run_id, time=None, revision=None, generation=0):
        history = self.history(run_id)
        try:
            frontier = history.revision
            if revision is not None and not 0 <= int(revision) <= frontier:
                raise ValueError(f"Revision must lie between 0 and committed frontier {frontier}")
            if time is not None:
                latest = history.state_at()
                if not 0 <= exact_time(time) <= exact_time(latest.get("time", 0)):
                    raise ValueError("Replay time must lie within the committed history")
            state = project_state(history.state_at(time, frontier if revision is None else revision), time)
            bundle = view_bundle(state, run_id=run_id, mode="replay" if time is not None or revision is not None else "live",
                                 sequence=frontier, frontier=frontier, generation=generation)
            run = self._row(run_id)
            bundle["control"] = {"status": run["status"], "generation": run["generation"],
                                 "pacing": json.loads(run["frontier"]).get("pacing", 1)}
            return bundle
        finally:
            history.close()

    def save_cohort(self, run_id, definition):
        definition = copy.deepcopy(definition)
        if definition.get("mode") not in {"fixed", "dynamic"}:
            raise ValueError("Cohort mode must be fixed or dynamic")
        predicate = definition.get("predicate", {})
        unknown = set(predicate) - {"type", "role", "status", "model_assignment", "region"}
        if unknown:
            raise ValueError(f"Unknown cohort predicates: {', '.join(sorted(unknown))}")
        region = predicate.get("region")
        if region is not None and (not isinstance(region, list) or len(region) != 4
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in region)
                or not region[0] <= region[2] or not region[1] <= region[3]):
            raise ValueError("Cohort region must be [xmin, ymin, xmax, ymax] with finite ordered bounds")
        state = self.snapshot(run_id, revision=definition.get("reference_revision"))["state"]
        if definition.get("mode") == "fixed" and "members" not in definition:
            dynamic = dict(definition, mode="dynamic")
            definition["members"] = cohort_members(state, dynamic)
        definition.setdefault("id", uuid.uuid4().hex)
        definition.setdefault("reference_revision", str(state.get("revision", 0)))
        with self.lock, self.connection:
            self.connection.execute("INSERT OR REPLACE INTO views VALUES(?,?,?)", (run_id, definition["id"], canonical(definition)))
        return definition

    def branch(self, run_id, request):
        """Stage a complete child before publishing its durable reserved identity."""
        from .engine import Simulation
        from .runtime import restore_revision, branch as branch_engine, serialize, checkpoint, close
        command_id = request.get("command_id") or str(uuid.uuid4())
        with self.lock:
            parent = self._row(run_id)
            previous = self.connection.execute("SELECT * FROM commands WHERE id=?", (command_id,)).fetchone()
            if previous:
                if previous["operation"] != "branch" or previous["run_id"] != run_id:
                    raise ValueError("Command ID belongs to a different operation")
                _check_command_request(previous,request)
                response = json.loads(previous["response"])
                child_id = response["run_id"]
                if previous["status"] == "applied":
                    return response
            else:
                if request.get("generation") is not None and int(request["generation"]) != parent["generation"]:
                    raise ValueError("Stale control generation; refresh before branching")
                if parent["status"] not in {"paused", "stopped", "completed"}:
                    raise ValueError("Pause the run before branching from a committed revision")
                reader=self.history(run_id)
                try:
                    selected_revision=int(request.get("revision",reader.revision))
                    if not 0<=selected_revision<=reader.revision:
                        raise ValueError("Branch revision must lie within the parent's committed history")
                    if reader.runtime_at(selected_revision) is None:
                        raise ValueError("This legacy revision has no runtime journal; use a complete retained checkpoint")
                finally:reader.close()
                child_id = uuid.uuid4().hex
                response = {"command_id": command_id, "run_id": child_id, "status": "pending",
                            "parent_revision":str(selected_revision)}
                with self.connection:
                    self.connection.execute("INSERT INTO commands VALUES(?,?,?,?,?,?,?)", (command_id, run_id, "branch", canonical(request), "pending", canonical(response), time.time()))
            directory = self.root / "runs" / child_id
            if not (directory / "worker-checkpoint.json").exists():
                source = Path(parent["directory"]) / "run.sqlite"
                reader = History(source, read_only=True)
                try:
                    revision = int(response.get("parent_revision",request.get("revision", reader.revision)))
                    if not 0 <= revision <= reader.revision:
                        raise ValueError("Branch revision must lie within the parent's committed history")
                    if reader.runtime_at(revision) is None:
                        raise ValueError("This legacy revision has no runtime journal; use a complete retained checkpoint")
                finally:
                    reader.close()
                if "parent_revision" not in response:
                    # Upgrade an older pending reservation at its first retry;
                    # all newly accepted reservations already carry this pin.
                    response["parent_revision"]=str(revision)
                    with self.connection:
                        self.connection.execute("UPDATE commands SET response=? WHERE id=?",(canonical(response),command_id))
                stage = self.root / "runs" / f".{child_id}.{uuid.uuid4().hex}.partial"
                restored = restore_revision(Simulation, source, revision=revision)
                child = None
                try:
                    child = branch_engine(restored, stage, seed=request.get("seed"), run_id=child_id)
                    for index, change in enumerate(request.get("interventions", [])):
                        child.intervene(change.get("change", change), at=change.get("time"), id=f"{command_id}:{index}")
                    checkpoint(child, stage / "checkpoint.json")
                    control = {"status": "paused", "generation": 0, "processed": {}, "pacing": 1.0}
                    document = {"schema": "zombie-sim/managed-checkpoint-v1", "engine": serialize(child), "control": control}
                    document["checksum"] = hashlib.sha256(canonical(document).encode()).hexdigest()
                    _atomic_json(stage / "worker-checkpoint.json", document)
                    resolved = child.config
                    frontier = {"time": str(child.time), "revision": str(child.revision), "generation": 0, "status": "paused", "pacing": 1.0}
                finally:
                    if child is not None:
                        close(child)
                    close(restored)
                response.update(revision=frontier["revision"],time=frontier["time"])
                with self.connection:
                    self.connection.execute("UPDATE commands SET response=? WHERE id=?",(canonical(response),command_id))
                os.replace(stage, directory)
                lineage = {"parent_run_id": run_id, "revision": str(revision), "seed": request.get("seed"), "history": str(source)}
                with self.connection:
                    self.connection.execute("INSERT OR REPLACE INTO runs(id,directory,config,status,generation,frontier,parent) VALUES(?,?,?,?,?,?,?)", (child_id, str(directory), canonical(resolved), "paused", 0, canonical(frontier), canonical(lineage)))
            elif not self.connection.execute("SELECT 1 FROM runs WHERE id=?", (child_id,)).fetchone():
                manifest = json.loads((directory / "manifest.json").read_text())
                with self.connection:
                    self.connection.execute("INSERT INTO runs(id,directory,config,status,parent) VALUES(?,?,?,?,?)", (child_id, str(directory), canonical(manifest["config"]), "paused", canonical({"parent_run_id": run_id})))
            if response.get("revision") is None:
                # Older pending reservations can recover their own boundary
                # from the immutable staging checkpoint, never a later frontier.
                envelope=json.loads((directory/"checkpoint.json").read_text())
                document=envelope["document"]
                if hashlib.sha256(canonical(document).encode()).hexdigest()!=envelope.get("checksum"):
                    raise ValueError("Branch staging checkpoint checksum mismatch")
                response.update(revision=str(document["ledger_revision"]),
                                time=str(document["payload"]["attributes"]["state"]["time"]))
            response.update(status="applied", parent_run_id=run_id)
            with self.connection:
                self.connection.execute("UPDATE commands SET status='applied',response=? WHERE id=?", (canonical(response), command_id))
            self.launch_worker(child_id)
            return response

    def cohorts(self, run_id, state=None):
        if state is None:
            state = self.snapshot(run_id)["state"]
        with self.lock:
            definitions = [json.loads(row[0]) for row in self.connection.execute("SELECT definition FROM views WHERE run_id=?", (run_id,))]
        result = []
        episodes = state.get("episodes", {})
        for definition in definitions:
            summary = cohort_summary(state, definition)
            members = set(summary["members"])
            reference = int(definition["reference_revision"])
            selected = [episode for episode in episodes.values() if str(episode.get("agent_id", episode.get("agent"))) in members]
            summary.update(member_ids=summary["members"],
                           cures=sum(episode.get("outcome") == "CURED" for episode in selected),
                           conversions=sum(episode.get("outcome") == "CONVERTED" for episode in selected),
                           new_incidence=sum(int(episode.get("onset_revision", 0)) > reference for episode in selected))
            agents = [state["agents"][identity] for identity in members if identity in state["agents"]]
            summary["human_survival"] = {"events": sum(agent.get("type") == "Zombie" or agent.get("status") == "DEAD" for agent in agents)}
            summary["identity_survival"] = {"events": sum(agent.get("status") == "DEAD" for agent in agents)}
            result.append(summary)
        return result

    def restart_checkpoint(self, run_id, name):
        """Restart the current committed boundary from a named exact checkpoint."""
        row = self._row(run_id)
        if row["status"] != "paused":
            raise ValueError("Pause the run before restarting from a checkpoint")
        if not name or any(not (char.isalnum() or char in "-_") for char in name):
            raise ValueError("Invalid checkpoint name")
        path = Path(row["directory"]) / "checkpoints" / f"{name}.json"
        # Validate the real artifact before discarding the live coordinator.
        from .engine import Simulation
        from .runtime import restore
        restored = restore(Simulation, path, workers=1)
        try:
            if str(restored.revision) != str(json.loads(row["frontier"])["revision"]):
                raise ValueError("An older checkpoint must be opened as a child run; committed history cannot be overwritten")
        finally:
            restored.close()
        process = self.processes.get(run_id)
        if process is None:
            raise ValueError("The coordinator is owned by another manager")
        process.terminate(); process.join(timeout=10)
        if process.is_alive():
            raise RuntimeError("The previous coordinator has not exited")
        _atomic_json(Path(row["directory"]) / "requested-restore.json", {"path": str(path)})
        self.launch_worker(run_id)
        return {"run_id": run_id, "checkpoint": str(path)}

    def timeline(self, run_id, revision=None, agent=None):
        """Recorded causal events with transaction-exact before/after cursors."""
        history = self.history(run_id)
        try:
            frontier = history.revision if revision is None else int(revision)
            state = history.state_at(revision=frontier)
            occurrences = state.get("occurrences", {})
            records = history.events(end=frontier, limit=5000)
            if agent is not None:
                relevant = {identity for identity, item in occurrences.items() if str(agent) in {str(item.get("actor")), str(item.get("target"))}}
                records = [event for event in records if str(agent) in {str(event.get(key)) for key in ("actor", "target", "agent", "agent_id", "target_id")} or event.get("occurrence", event.get("action_id")) in relevant]
            return {"records": [dict(record, type=str(record.get("kind", "event")).upper(),
                                     revision_before=str(max(0, int(record["ledger_revision"]) - 1)),
                                     revision_after=str(record["ledger_revision"])) for record in records],
                    "occurrences": occurrences}
        finally:
            history.close()

    def close(self):
        # Explicit server shutdown saves managed runs. A browser disconnect does
        # not call this method and cannot stop a run.
        for run_id, process in self.processes.items():
            if process.is_alive():
                if self._row(run_id)["status"] not in TERMINAL_STATES:
                    self.command(run_id, "stop", wait=True)
                process.join(timeout=10)
        self.connection.close()
