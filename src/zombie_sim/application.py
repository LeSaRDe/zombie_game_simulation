"""Shared CLI/HTTP application services and separately managed run processes."""
from __future__ import annotations

import copy
from collections import OrderedDict
from contextlib import contextmanager
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import threading
import time
import traceback
import uuid

from .storage import History, canonical, exact_time
from .visualization import project_state, view_bundle, cohort_summary, cohort_members


class RunInitializing(ValueError):
    """A known run exists but has not published its first complete revision."""


class ViewCancelled(Exception):
    """A disconnected viewer no longer needs its private read request."""


def _check_view_cancelled(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise ViewCancelled("History loading was cancelled")


@contextmanager
def _view_lock(lock, cancel_event):
    """Allow an obsolete viewer to leave a reconstruction queue promptly."""
    _check_view_cancelled(cancel_event)
    if cancel_event is None:
        lock.acquire()
    else:
        while not lock.acquire(timeout=0.05):
            _check_view_cancelled(cancel_event)
    try:
        _check_view_cancelled(cancel_event)
        yield
    finally:
        lock.release()


TERMINAL_STATES = {"stopped", "completed", "failed", "terminated"}


class _HeadReader:
    """A metadata connection and its active readers, never a reconstructed state."""
    def __init__(self):
        self.history = None
        self.lock = threading.Lock()
        self.users = 0
        self.cached = False


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


def _journal(path):
    from .persistence.catalog import SQLiteRunCatalog
    return SQLiteRunCatalog(path)


def _restore_engine(payload, directory):
    from .engine import Simulation
    if hasattr(Simulation, "from_serialized"):
        return Simulation.from_serialized(payload, history_path=str(directory / "run.sqlite"))
    raise RuntimeError("Engine does not support serialized continuation")


class RunWorker:
    """Own one coordinator's engine, journal, lease and durable control state.

    A browser never owns this lifetime. The process entry point constructs this
    object inside the child; no open connection, engine or lock is pickled.
    """
    def __init__(self, root, run_id, *, simulation_factory=None, journal_factory=None,
                 history_factory=History):
        from .engine import Simulation
        self.root = Path(root)
        self.run_id = run_id
        self.simulation_factory = simulation_factory if simulation_factory is not None else Simulation
        self.journal_factory = journal_factory if journal_factory is not None else _journal
        self.history_factory = history_factory
        self.simulation = None
        self.journal = None
        self.lease_file = None
        self.directory = None
        self.config = None
        self.control = None
        self.checkpoint = None
        self.last_runtime_time = None
        self.last_runtime_revision = None
        self._closed = False

    def run(self):
        """Single coordinator process; browser disconnects do not own its lifetime."""
        if self._closed:
            raise RuntimeError("Run worker is closed")
        self.journal = self.journal_factory(Path(self.root) / "manager.sqlite")
        row = self.journal.run(self.run_id)
        self.directory = Path(row["directory"])
        self.lease_file = (self.directory / "worker.lock").open("a+")
        try:
            import fcntl
            fcntl.flock(self.lease_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, ImportError):
            self.lease_file.close()
            self.journal.close()
            self._closed = True
            return
        with self.journal:
            self.journal.set_lease(self.run_id, os.getpid(), time.time())
        self.config = json.loads(row["config"])
        self.control = {"status": "paused", "generation": int(row["generation"]), "processed": {}, "pacing": 1.0}
        self.simulation = None
        try:
            self.checkpoint = self.directory / "worker-checkpoint.json"
            ledger_path = self.directory / "run.sqlite"
            has_runtime = False
            if ledger_path.exists():
                reader = self.history_factory(ledger_path, read_only=True)
                try:
                    has_runtime = reader.runtime_at() is not None
                finally:
                    reader.close()
            requested_restore = self.directory / "requested-restore.json"
            if requested_restore.exists():
                from .runtime import restore
                selected = json.loads(requested_restore.read_text())
                self.simulation = restore(self.simulation_factory, selected["path"], history_path=ledger_path)
                self.control.update(self.simulation.history.get_metadata("control_state", {}) or {})
                self.control["status"] = "paused"
                requested_restore.unlink()
            elif has_runtime:
                from .runtime import restore_revision
                self.simulation = restore_revision(self.simulation_factory, ledger_path, output_history_path=ledger_path)
                self.control.update(self.simulation.history.get_metadata("control_state", {}) or {})
                if self.control["status"] in {"stopped", "failed", "interrupted"}:
                    self.control["status"] = "paused"
            elif self.checkpoint.exists():
                envelope = json.loads(self.checkpoint.read_text())
                if envelope.get("checksum") != hashlib.sha256(canonical({k: v for k, v in envelope.items() if k != "checksum"}).encode()).hexdigest():
                    raise ValueError("Managed checkpoint checksum mismatch")
                self.control = envelope["control"]
                self.simulation = _restore_engine(envelope["engine"], self.directory)
                self.control["status"] = "paused"
            else:
                execution = self.config.get("execution", {})
                self.simulation = self.simulation_factory(self.config, history_path=str(self.directory / "run.sqlite"),
                                        backend=self.config.get("storage", {}).get("backend", "memory"), workers=execution.get("workers", 1), run_id=self.run_id)


            # A semantic result and its command acknowledgement share the run ledger
            # transaction. Reconcile a lost manager/HTTP ACK before processing retries.
            with self.journal:
                for response in self.simulation.history.command_results():
                    if response.get("run_id") != self.run_id:
                        continue
                    self.control["processed"][response["command_id"]] = response
                    self.journal.update_command(response['command_id'], status=response['status'], response=response)
            active = self.simulation.history.get_metadata("active_control_command")
            if active and active.get("operation") in {"step", "step_timestamp", "advance", "intervene"}:
                response = self.apply_semantic(active)
                with self.journal:
                    self.journal.update_command(response['command_id'], status=response['status'], response=response)
            if self.simulation.run_status == "COMPLETED":
                self.control["status"] = "completed"



            self.publish(save=True)
            self.last_runtime_time = self.simulation.time
            self.last_runtime_revision = self.simulation.revision

            while self.control["status"] not in TERMINAL_STATES:
                pending = self.journal.pending_commands(self.run_id, controls_only=True)
                for command in pending:
                    request = json.loads(command["request"])
                    operation = command["operation"]
                    try:
                        if request.get("generation") is not None and int(request["generation"]) != self.control["generation"]:
                            raise ValueError(f"Stale control generation: refresh generation {self.control['generation']}")
                        if request.get("revision") is not None and int(request["revision"]) != self.simulation.revision:
                            raise ValueError("The selected revision is stale; refresh before applying this operation")
                        if operation in {"start", "continue", "resume"}:
                            self.control["status"] = "running"
                        elif operation == "pause":
                            self.control["status"] = "paused"
                        elif operation == "script":
                            if self.control["status"] != "paused":
                                raise ValueError("Pause the run before submitting scripted research commands")
                            from .commands import execute_script_command
                            self.simulation.inject_random_values(request.get("draws", []))
                            desired = {"status": "paused", "generation": self.control["generation"] + 1, "pacing": self.control["pacing"]}
                            step = request["step"]
                            payload = {key: value for key, value in step.items() if key != "op"}
                            if step["op"] == "submit":
                                payload = step["intent"]
                            semantic_response = execute_script_command(self.simulation, step["op"], payload, command["id"], desired_control=desired)
                            self.control.update(semantic_response.get("control", desired))
                        elif operation in {"step", "step_timestamp", "advance", "intervene"}:
                            if operation != "intervene" and self.control["status"] != "paused":
                                raise ValueError("Pause the run before stepping or advancing to a time")
                            desired = {"status": self.control["status"], "generation": self.control["generation"] + 1, "pacing": self.control["pacing"]}
                            target = request.get("time", str(self.simulation.next_event_time())) if operation == "advance" else str(self.simulation.next_event_time())
                            active = {"id": command["id"], "operation": operation, "request": request, "target": str(target), "desired_control": desired}
                            existing = self.simulation.history.begin_command(active)
                            if existing is None:
                                semantic_response = self.apply_semantic(active)
                            else:
                                semantic_response = existing
                                self.control.update(existing.get("control", desired))
                        elif operation == "stop":
                            self.control["status"] = "stopped"
                        elif operation == "terminate":
                            # Do not create a checkpoint or erase already committed
                            # audit data. This run cannot subsequently be resumed.
                            self.control["status"] = "terminated"
                        elif operation == "checkpoint":
                            name = request.get("name") or f"revision-{self.simulation.revision}"
                            if not isinstance(name, str) or not name or any(not (char.isalnum() or char in "-_") for char in name):
                                raise ValueError("Checkpoint names may contain letters, digits, hyphens and underscores")
                            self.simulation.checkpoint(self.directory / "checkpoints" / f"{name}.json")
                        elif operation == "pace":
                            pace = request.get("pacing", 1)
                            if pace not in (0, 0.25, 1, 4):
                                raise ValueError("Pacing must be 0 (fastest), 0.25, 1 or 4")
                            self.control["pacing"] = pace
                        else:
                            raise ValueError(f"Unknown operation {operation!r}")
                        if operation in {"step", "step_timestamp", "advance", "intervene", "script"}:
                            response = semantic_response
                        else:
                            self.control["generation"] += 1
                            response = {"command_id": command["id"], "run_id": self.run_id, "status": "applied", **self.boundary()}
                            response["status"] = "applied"
                            response["run_status"] = self.control["status"]
                            response["control"] = {key: self.control[key] for key in ("status", "generation", "pacing")}
                            self.simulation.history.finish_command(response, response["control"])
                    except (ValueError, KeyError, RuntimeError) as error:
                        response = {"command_id": command["id"], "run_id": self.run_id, "status": "rejected", "error": str(error), **self.boundary()}
                        response["status"] = "rejected"
                        self.simulation._active_control_command = None
                        self.simulation.history.finish_command(response, {key: self.control[key] for key in ("status", "generation", "pacing")})
                    self.control["processed"][command["id"]] = response
                    # The runtime and command journals already make this boundary
                    # restartable. Serializing the whole world on pause/continue
                    # needlessly keeps CPUs busy after the semantic stop and delays
                    # publication of the new control generation.
                    self.publish(save=operation in {"checkpoint", "stop"})
                    with self.journal:
                        self.journal.update_command(command['id'], status=response['status'], response=response)
                    if self.control["status"] in TERMINAL_STATES:
                        break
                if self.control["status"] == "running":
                    started = time.monotonic()
                    old_time = self.simulation.time
                    horizon = exact_time(self.config.get("horizon", self.config.get("simulation", {}).get("horizon", 1800)))
                    target = min(horizon, old_time + 1)
                    self.simulation.advance_until(target, max_events=250, return_snapshot=False, should_yield=self.controls_waiting)
                    if not self.controls_waiting() and self.simulation.time < target and (not self.simulation.queue or self.simulation.queue[0][0] > target) and self.simulation.run_status != "COMPLETED":
                        self.simulation.advance_until(target, return_snapshot=False, should_yield=self.controls_waiting)
                    if self.simulation.run_status == "COMPLETED" or (self.simulation.time >= horizon and (not self.simulation.queue or self.simulation.queue[0][0] > horizon)):
                        self.control["status"] = "completed"
                    save = not self.controls_waiting() and (self.simulation.time - self.last_runtime_time >= exact_time(self.config.get("checkpoint_interval", 30))
                            or self.simulation.revision - self.last_runtime_revision >= int(self.config.get("checkpoint_transactions", 50000))
                            or self.control["status"] == "completed")
                    self.publish(save=save)
                    if save:
                        self.last_runtime_time, self.last_runtime_revision = self.simulation.time, self.simulation.revision
                    if self.control["pacing"]:
                        wait = max(0, float(self.simulation.time - old_time) / self.control["pacing"] - (time.monotonic() - started))
                        # Short waits keep run-control receipt responsive.
                        deadline = time.monotonic() + wait
                        while time.monotonic() < deadline:
                            if ((1,) if self.journal.controls_waiting(self.run_id,controls_only=False) else None):
                                break
                            time.sleep(min(0.025, max(0, deadline - time.monotonic())))
                elif self.control["status"] == "paused":
                    time.sleep(0.025)
            self.publish(save=self.control["status"] != "terminated")
        except BaseException as error:
            with self.journal:
                self.journal.update_run(self.run_id, status='failed', error=f'{type(error).__name__}: {error}')
            (self.directory / "failure.log").write_text(traceback.format_exc())
        finally:
            self.close()


    def apply_semantic(self, active):
        self.simulation._active_control_command = active
        operation, request = active["operation"], active["request"]
        if operation == "step":
            self.simulation.step(timestamp=False, return_snapshot=False)
        elif operation in {"step_timestamp", "advance"}:
            self.simulation.advance_until(active["target"], return_snapshot=False)
        elif operation == "intervene":
            if request.get("apply_now") and exact_time(request.get("time", self.simulation.time)) != self.simulation.time:
                raise ValueError("Apply now requires the current simulation time")
            self.simulation.intervene(request["change"], at=request.get("time"), id=active["id"])
            if request.get("apply_now"):
                self.simulation.advance_until(self.simulation.time, return_snapshot=False)
        response = self.simulation.history.command_result(active["id"])
        if response is None:
            desired = active["desired_control"]
            response = {"command_id": active["id"], "run_id": self.run_id, "status": "applied",
                        "time": str(self.simulation.time), "revision": str(self.simulation.revision),
                        "generation": desired["generation"], "run_status": desired["status"],
                        "pacing": desired["pacing"], "control": desired}
            self.simulation.history.finish_command(response, desired)
        self.control.update(response.get("control", active["desired_control"]))
        self.control["processed"][active["id"]] = response
        self.simulation._active_control_command = None
        return response


    def boundary(self):
        return {"time": str(self.simulation.time), "revision": str(self.simulation.revision),
                "generation": self.control["generation"], "status": self.control["status"], "pacing": self.control["pacing"],
                "workers": self.simulation.workers, "worker_budget": getattr(self.simulation, "_runtime_worker_budget", {})}


    def publish(self, save=False):
        if save:
            payload = {"schema": "zombie-sim/managed-checkpoint-v1", "engine": self.simulation.serialize(), "control": self.control}
            payload["checksum"] = hashlib.sha256(canonical(payload).encode()).hexdigest()
            _atomic_json(self.checkpoint, payload)
        with self.journal:
            self.journal.update_run(self.run_id, status=self.control['status'], generation=self.control['generation'], frontier=self.boundary(), error=None)
            self.journal.heartbeat(self.run_id, os.getpid(), time.time())


    def controls_waiting(self):
        return ((1,) if self.journal.controls_waiting(self.run_id,controls_only=True) else None) is not None


    def close(self):
        if self._closed:
            return
        if self.journal is None:
            self._closed = True
            return
        with self.journal:
            for pending in self.journal.pending_commands(self.run_id, controls_only=True):
                response = {"command_id": pending["id"], "run_id": self.run_id, "status": "rejected",
                            "error": "The run worker stopped before this command could be applied.",
                            "time": str(self.simulation.time) if self.simulation else "0", "revision": str(self.simulation.revision) if self.simulation else "0"}
                self.journal.update_command(pending['id'], status='rejected', response=response)
        if self.simulation is not None:
            self.simulation.close()
        with self.journal:
            self.journal.remove_lease(self.run_id, os.getpid())
        self.journal.close()
        self.lease_file.close()
        self._closed = True


def _run_worker(root, run_id):
    """Pickleable process entry point; resources belong to the child worker."""
    return RunWorker(root, run_id).run()


class RunRepository:
    """Own workspace registration and an injected catalog, never expose SQL."""
    def __init__(self, root="experiments", *, read_only=False, history_factory=History, catalog=None):
        self.root = Path(root).absolute()
        self.read_only = read_only
        self.history_factory = history_factory
        self.lock = threading.RLock()
        from .persistence.catalog import SQLiteRunCatalog
        if not read_only:self.root.mkdir(parents=True,exist_ok=True)
        self.catalog=catalog if catalog is not None else SQLiteRunCatalog(self.root / "manager.sqlite",read_only=read_only)
        if not read_only:self.register_existing()

    def require_writable(self):
        if self.read_only:
            raise ValueError("Read-only run managers cannot modify experiments")

    def close(self):
        self.catalog.close()

    def run_rows(self):
        with self.lock:
            return self.catalog.run_rows()

    def pending_commands(self):
        with self.lock:
            return [dict(row) for row in self.catalog.pending_commands()]

    def unfinished_creations(self):
        with self.lock:
            return [dict(row) for row in self.catalog.unfinished_creations()]

    def command_exists(self, command_id):
        with self.lock:
            return self.catalog.command(command_id) is not None

    def lease_count(self):
        with self.lock:
            return self.catalog.lease_count()

    def row(self, run_id):
        # All uses of the shared journal connection participate in one lock,
        # including read paths called by concurrent HTTP/WebSocket threads.
        with self.lock:
            row = self.catalog.run(run_id)
        if row is None:
            raise KeyError(f"Unknown run {run_id}")
        return row


    @staticmethod
    def _ledger_head(history):
        row = history.head()
        if row is None:
            raise RunInitializing("Run initialization has not published a complete revision yet")
        return int(row[0]), str(exact_time({"n": row[1], "d": row[2]}))


    def register_existing(self):
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
            if self.catalog.run(identity):
                continue
            history = self.history_factory(directory / "run.sqlite", read_only=True)
            try:
                # Registration needs only the committed cursor and durable
                # control metadata. Scene and runtime checksums remain checked
                # by their normal replay/restore paths when a run is opened.
                revision, committed_time = self._ledger_head(history)
                control = history.get_metadata("control_state", {}) or {}
            finally:
                history.close()
            status = manifest.get("status", "interrupted")
            if control.get("status") == "terminated" or status not in TERMINAL_STATES:
                status = control.get("status", status)
            if status not in TERMINAL_STATES:
                status = "interrupted"
            generation = int(control.get("generation", 0))
            frontier = {"time": committed_time, "revision": str(revision), "generation": generation, "status": status, "pacing": 0}
            with self.catalog:
                self.catalog.insert_run(identity, str(directory), manifest['config'], status, generation=generation, frontier=frontier, parent=(manifest.get('parent') if manifest.get('parent') else None))


class WorkerSupervisor:
    """Own coordinator processes and observe their durable cleanup evidence."""
    def __init__(self, repository, *, process_factory=None):
        self.repository = repository
        self.process_factory = process_factory
        self.processes = {}

    def close(self, stop):
        for run_id, process in (() if self.repository.read_only else self.processes.items()):
            if process.is_alive():
                if self.repository.row(run_id)["status"] not in TERMINAL_STATES:
                    stop(run_id)
                process.join(timeout=10)

    def resource_status(self, run):
        """Observe cleanup independently of the durable command receipt.

        A normal worker releases its database lease only after closing the
        simulation (including its process pool), then releases its file lock.
        Owned process liveness also covers the small gap before process exit.
        A leftover lease is deliberately inconclusive: a PID can be stale or
        reused, and neither signaling nor deleting that lease is a read action.
        """
        with self.repository.lock:
            process = self.processes.get(run["id"])
            lease = self.repository.catalog.lease(run['id'])
            requested = ((1,) if self.repository.catalog.controls_waiting(run['id'],controls_only=False, operation='terminate') else None) is not None
        process_active = process is not None and process.is_alive()
        lock_active, lock_verified = ((False, False) if process_active
                                      else self.lock_status(run["directory"]))
        worker_active = bool(process_active or lock_active)
        inactive = run["status"] in TERMINAL_STATES or run["status"] == "interrupted"
        cleanup_complete = bool(inactive and not worker_active and lease is None and lock_verified)
        if inactive:
            phase = "stopped" if cleanup_complete else "stopping"
        elif requested:
            phase = "termination_requested"
        else:
            phase = run["status"]
        return {"phase": phase, "cleanup_complete": cleanup_complete, "worker_active": worker_active}


    @staticmethod
    def lock_status(directory):
        """Inspect Linux flock ownership without briefly taking a worker lock.

        Acquiring and releasing a probe lock can race a coordinator's startup
        LOCK_NB and make it exit. /proc/locks exposes the same inode read-only.
        As with process handles, this observes workers in this PID namespace;
        the journal lease remains required evidence of normal pool cleanup.
        """
        try:
            identity = (Path(directory) / "worker.lock").stat()
        except FileNotFoundError:
            return False, True  # Imported histories can have no worker lock.
        except OSError:
            return False, False
        try:
            expected = (os.major(identity.st_dev), os.minor(identity.st_dev), identity.st_ino)
            for line in Path("/proc/locks").read_text().splitlines():
                fields = line.split()
                if "FLOCK" not in fields:
                    continue
                device = fields[fields.index("FLOCK") + 4].split(":")
                actual = (int(device[0], 16), int(device[1], 16), int(device[2]))
                if actual == expected:
                    return True, True
            return False, True
        except (OSError, AttributeError, ValueError, IndexError):
            # Unavailable or unreadable ownership is never proof of cleanup.
            return False, False


    def launch(self, run_id):
        self.repository.require_writable()
        if self.repository.row(run_id)["status"] == "terminated":
            raise ValueError("Terminated runs cannot be resumed; create a new experiment")
        old = self.processes.get(run_id)
        if old is not None and old.is_alive():
            if self.repository.row(run_id)["status"] in {"stopped", "failed", "interrupted"}:
                old.join(timeout=2)
                if old.is_alive():
                    raise ValueError("The previous worker is still saving its final boundary; retry resume shortly")
            else:
                return
        lease = self.repository.catalog.lease(run_id)
        if lease:
            try:
                os.kill(lease[0], 0)
                return
            except ProcessLookupError:
                pass
        factory = self.process_factory or multiprocessing.get_context("spawn").Process
        process = factory(target=_run_worker, args=(str(self.repository.root), run_id), daemon=False)
        process.start()
        self.processes[run_id] = process


class HistoryQueryService:
    """Own compact snapshot caches and persistent read-only WAL metadata readers."""
    def __init__(self, repository, history_provider, worker_status, visualization):
        self.repository = repository
        self.history = history_provider
        self.worker_status = worker_status
        self.visualization = visualization
        # Keep only compact scene projections. Locks are striped by run so
        # simultaneous viewers share a reconstruction without holding the
        # journal/control lock during replay or copying a scene.
        self._snapshot_cache = OrderedDict()
        self._snapshot_cache_capacity = 8
        self._snapshot_cache_lock = threading.Lock()
        self._snapshot_build_locks = tuple(threading.Lock() for _ in range(64))
        self._snapshot_builds = 0
        self._snapshot_hits = 0
        # Keep SQLite's WAL index attached between metadata polls. Opening and
        # closing the last reader can otherwise rescan a large retained WAL on
        # every unchanged head query, even without reconstructing any state.
        self._head_readers = OrderedDict()
        self._head_reader_capacity = 8
        self._head_reader_lock = threading.Lock()
        self._head_all_readers = set()
        self._head_readers_closed = False
        self._head_opened = 0
        self._head_closed = 0

    _ledger_head = staticmethod(RunRepository._ledger_head)

    def _close_head_reader(self, reader):
        with reader.lock:
            if reader.history is not None:
                reader.history.close()
                reader.history = None
                with self._head_reader_lock:
                    self._head_closed += 1
            with self._head_reader_lock:
                self._head_all_readers.discard(reader)


    @contextmanager
    def _head_reader(self, run_id):
        retired = None
        with self._head_reader_lock:
            if self._head_readers_closed:
                raise RuntimeError("Run manager is closed")
            reader = self._head_readers.get(run_id)
            if reader is None:
                if len(self._head_readers) >= self._head_reader_capacity:
                    idle = next((identity for identity, item in self._head_readers.items() if not item.users), None)
                    if idle is not None:
                        retired = self._head_readers.pop(idle)
                        retired.cached = False
                reader = _HeadReader()
                self._head_all_readers.add(reader)
                if len(self._head_readers) < self._head_reader_capacity:
                    reader.cached = True
                    self._head_readers[run_id] = reader
                # If all cached readers are busy, this request owns a temporary
                # reader instead of growing the cache or closing an active one.
            if reader.cached:
                self._head_readers.move_to_end(run_id)
            reader.users += 1
        if retired is not None:
            self._close_head_reader(retired)
        try:
            yield reader
        finally:
            with self._head_reader_lock:
                reader.users -= 1
                release = not reader.cached and not reader.users
            if release:
                self._close_head_reader(reader)


    def _open_head_reader(self, run_id, reader):
        # Callers hold this reader's lock. Connections execute only completed
        # metadata SELECTs: no BEGIN and no open cursor survives the query.
        if self._head_readers_closed:
            raise RuntimeError("Run manager is closed")
        if reader.history is None:
            reader.history = self.history(run_id)
            with self._head_reader_lock:
                self._head_opened += 1
        return reader.history


    def head_diagnostics(self):
        with self._head_reader_lock:
            return {"entries": len(self._head_readers), "capacity": self._head_reader_capacity,
                    "opened": self._head_opened, "closed": self._head_closed,
                    "active_connections": self._head_opened - self._head_closed}


    def _read_control(self, run_id, history):
        run = dict(self.repository.row(run_id))
        control = {"status": run["status"], "generation": run["generation"],
                   "pacing": json.loads(run["frontier"]).get("pacing", 1)}
        durable = history.get_metadata("control_state", {}) or {}
        # The ledger receipt may precede manager publication while a command
        # performs optional checkpoint work. It remains an ACK, not cleanup.
        if int(durable.get("generation", -1)) > control["generation"]:
            control.update({key: durable[key] for key in ("status", "generation", "pacing") if key in durable})
            run.update(status=control["status"], generation=control["generation"])
        control["resource_status"] = self.worker_status(run)
        return control


    def read_head(self, run_id):
        """Read a committed version and control state without replaying history."""
        with self._head_reader(run_id) as reader, reader.lock:
            history = self._open_head_reader(run_id, reader)
            revision, committed_time = self._ledger_head(history)
            control = self._read_control(run_id, history)
            return {"run_id": run_id, "revision": str(revision), "time": committed_time,
                    "generation": int(control["generation"]), "status": control["status"],
                    "resource_status": control["resource_status"]}


    def snapshot_diagnostics(self):
        """Local counters for verifying reader reuse; no simulation semantics."""
        with self._snapshot_cache_lock:
            return {"builds": self._snapshot_builds, "hits": self._snapshot_hits,
                    "entries": len(self._snapshot_cache), "capacity": self._snapshot_cache_capacity}


    def snapshot(self, run_id, time=None, revision=None, generation=0, *, cancel_event=None):
        # Terminal HTTP-only viewers need the same persistent metadata reader
        # as streams. Pin its lifetime, not its lock or a read transaction,
        # while the separate projection connection reconstructs the scene.
        _check_view_cancelled(cancel_event)
        with self._head_reader(run_id) as reader:
            with _view_lock(reader.lock, cancel_event):
                self._open_head_reader(run_id, reader)
            _check_view_cancelled(cancel_event)
            return self._snapshot(run_id, time, revision, generation, cancel_event=cancel_event)


    def _snapshot(self, run_id, time=None, revision=None, generation=0, *, cancel_event=None):
        history = self.history(run_id)
        try:
            _check_view_cancelled(cancel_event)
            if cancel_event is not None:
                # Only this request's private connection may be interrupted.
                # Cached metadata readers and other viewers remain unaffected.
                history.set_cancellation(cancel_event)
            frontier, committed_time = self._ledger_head(history)
            selected_revision = frontier if revision is None else int(revision)
            if not 0 <= selected_revision <= frontier:
                raise ValueError(f"Revision must lie between 0 and committed frontier {frontier}")
            selected_time = None if time is None else str(exact_time(time))
            if time is not None and not 0 <= exact_time(time) <= exact_time(committed_time):
                raise ValueError("Replay time must lie within the committed history")
            mode = "replay" if time is not None or revision is not None else "live"
            key = (run_id, selected_revision, selected_time, mode)
            build_lock = self._snapshot_build_locks[hash(run_id) % len(self._snapshot_build_locks)]
            with _view_lock(build_lock, cancel_event):
                with self._snapshot_cache_lock:
                    cached = self._snapshot_cache.get(key)
                    if cached is not None:
                        self._snapshot_cache.move_to_end(key)
                        self._snapshot_hits += 1
                if cached is None:
                    check = lambda: _check_view_cancelled(cancel_event)
                    state = (history.state_at(selected_time, selected_revision) if cancel_event is None
                             else history.state_at(selected_time, selected_revision, check_cancelled=check))
                    check()
                    # Decode, projection and copying are atomic stages. Check
                    # between them instead of claiming arbitrary interruption.
                    state = self.visualization.project_state(state, selected_time)
                    check()
                    cached = self.visualization.view_bundle(state, run_id=run_id, mode=mode,
                                         sequence=frontier, frontier=frontier)
                    check()
                    with self._snapshot_cache_lock:
                        self._snapshot_cache[key] = cached
                        self._snapshot_builds += 1
                        while len(self._snapshot_cache) > self._snapshot_cache_capacity:
                            self._snapshot_cache.popitem(last=False)
            # Cache-owned objects never escape. Request/control fields are
            # refreshed even when replaying an unchanged, older revision.
            _check_view_cancelled(cancel_event)
            bundle = copy.deepcopy(cached)
            _check_view_cancelled(cancel_event)
            bundle.update(sequence=str(frontier), committed_frontier=str(frontier), query_generation=str(generation))
            bundle["control"] = self._read_control(run_id, history)
            _check_view_cancelled(cancel_event)
            return bundle
        except Exception:
            _check_view_cancelled(cancel_event)
            raise
        finally:
            history.close()


    def close(self):
        with self._head_reader_lock:
            self._head_readers_closed = True
            readers = list(self._head_all_readers)
            self._head_readers.clear()
            for reader in readers:
                reader.cached = False
        for reader in readers:
            self._close_head_reader(reader)


class RunManager:
    def __init__(self, root="experiments", *, read_only=False, repository=None,
                 workers=None, configuration=None, metrics=None, comparison=None,
                 timeline=None, visualization=None):
        from .config import ConfigurationService
        from .metrics import MetricsService
        from .comparison import ComparisonService
        from .timeline import TimelineService
        from .visualization import VisualizationService
        self.repository = repository if repository is not None else RunRepository(root, read_only=read_only)
        self.root = self.repository.root
        self.read_only = self.repository.read_only
        # Compatibility attributes share, rather than duplicate, repository ownership.
        self.catalog = self.repository.catalog
        self.lock = self.repository.lock
        self.workers = workers if workers is not None else WorkerSupervisor(self.repository)
        self.processes = self.workers.processes
        self.configuration = configuration if configuration is not None else ConfigurationService()
        self.metrics = metrics if metrics is not None else MetricsService()
        self.comparisons = comparison if comparison is not None else ComparisonService(self.metrics)
        self.timelines = timeline if timeline is not None else TimelineService()
        self.visualization = visualization if visualization is not None else VisualizationService(projector=lambda *args, **kwargs: project_state(*args, **kwargs))
        self.queries = HistoryQueryService(self.repository, lambda run_id: self.history(run_id), self.workers.resource_status, self.visualization)
        # Historical diagnostics expose the same cache objects, never copies.
        self._head_readers = self.queries._head_readers
        self._snapshot_build_locks = self.queries._snapshot_build_locks


    def list_runs(self):
        rows = self.repository.run_rows()
        result = []
        for row in rows:
            item = dict(row)
            item["config"] = json.loads(item["config"])
            item["frontier"] = json.loads(item["frontier"])
            with self.lock:
                process = self.processes.get(item["id"])
            if process is not None and not process.is_alive() and item["status"] in {"running", "paused", "initializing"}:
                item["status"] = "interrupted"
                item["error"] = "Worker exited. Resume from the saved boundary."
            item["resource_status"] = self._resource_status(item)
            result.append(item)
        return result


    def _resource_status(self, run):
        return self.workers.resource_status(run)

    @staticmethod
    def _worker_lock_status(directory):
        return WorkerSupervisor.lock_status(directory)

    def _row(self, run_id):
        return self.repository.row(run_id)

    def launch_worker(self, run_id):
        return self.workers.launch(run_id)

    def create(self, config, command_id=None, *, start=False, parent=None):
        self._require_writable()
        resolved = self.configuration.resolve(config)
        if hasattr(resolved, "to_dict"):
            resolved = resolved.to_dict()
        command_id = command_id or str(uuid.uuid4())
        with self.lock:
            existing = self.catalog.command(command_id)
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
            with self.catalog:
                self.catalog.insert_run(run_id, str(directory), resolved, 'initializing', parent=(parent if parent else None))
                self.catalog.insert_command(command_id, run_id, 'create', {'config': config, 'start': start}, 'applied', response)
            directory.mkdir(parents=True, exist_ok=True)
            for name in ("checkpoints", "exports", "views", "artifacts"):
                (directory / name).mkdir(exist_ok=True)
            _atomic_json(directory / "manifest.json", {"run_id": run_id, "config": resolved, "parent": parent, "created": time.time()})
            self.launch_worker(run_id)
            if start:
                self.command(run_id, "start", {"command_id": command_id + ":start"}, wait=False)
            return response


    def command(self, run_id, operation, request=None, *, wait=True):
        self._require_writable()
        request = dict(request or {})
        command_id = request.setdefault("command_id", str(uuid.uuid4()))
        with self.lock:
            run = self._row(run_id)
            old = self.catalog.command(command_id)
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
            with self.catalog:
                self.catalog.insert_command(command_id, run_id, operation, request, 'pending', None)
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
            row = self.catalog.command(command_id)
            if row is None:
                raise KeyError(command_id)
            if row["status"] == "pending" and row["operation"] not in {"create", "branch"}:
                try:
                    history = self.history(row["run_id"])
                    try:
                        durable = history.command_result(command_id)
                    finally:
                        history.close()
                except (ValueError, OSError):
                    durable = None
                if durable:
                    if self.read_only:
                        return durable
                    with self.catalog:
                        self.catalog.update_command(command_id, status=durable['status'], response=durable)
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
                            self.catalog.update_run(row['run_id'], generation=acknowledged, status=status, frontier=frontier)
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
            history = self.repository.history_factory(path, read_only=True)
            if history.revision < 0:
                history.close()
                raise RunInitializing("Run initialization has not published a complete revision yet")
            return history
        except Exception as error:
            if run["status"] == "initializing" and "no such table" in str(error):
                raise RunInitializing("Run initialization is still creating its history") from error
            raise


    @staticmethod
    def _ledger_head(history):
        return RunRepository._ledger_head(history)

    def _close_head_reader(self, reader):
        return self.queries._close_head_reader(reader)


    def _head_reader(self, run_id):
        return self.queries._head_reader(run_id)


    def _open_head_reader(self, run_id, reader):
        return self.queries._open_head_reader(run_id, reader)


    def head_diagnostics(self):
        return self.queries.head_diagnostics()


    def _read_control(self, run_id, history):
        return self.queries._read_control(run_id, history)


    def read_head(self, run_id):
        return self.queries.read_head(run_id)


    def snapshot_diagnostics(self):
        return self.queries.snapshot_diagnostics()


    def snapshot(self, run_id, time=None, revision=None, generation=0, *, cancel_event=None):
        return self.queries.snapshot(run_id, time, revision, generation, cancel_event=cancel_event)


    def _snapshot(self, run_id, time=None, revision=None, generation=0, *, cancel_event=None):
        return self.queries._snapshot(run_id, time, revision, generation, cancel_event=cancel_event)


    def save_cohort(self, run_id, definition):
        self._require_writable()
        definition = copy.deepcopy(definition)
        name = definition.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Cohort name must contain text")
        definition["name"] = name.strip()
        if not isinstance(definition.get("mode"), str) or definition["mode"] not in {"fixed", "dynamic"}:
            raise ValueError("Cohort mode must be fixed or dynamic")
        predicate = definition.get("predicate", {})
        if not isinstance(predicate, dict):
            raise ValueError("Cohort filters must be an object")
        unknown = set(predicate) - {"type", "role", "status", "model_assignment", "region"}
        if unknown:
            raise ValueError(f"Unknown cohort predicates: {', '.join(sorted(unknown))}")
        from .registry import ROLES
        choices = {"type": {"", "Human", "Zombie"}, "status": {"", "HEALTHY", "INFECTED", "ACTIVE", "DEAD"},
                   "role": {"", None, *ROLES}}
        for field, allowed in choices.items():
            if field in predicate and (not isinstance(predicate[field], str) and predicate[field] is not None
                                       or predicate[field] not in allowed):
                raise ValueError(f"Invalid cohort {field} filter")
        if "model_assignment" in predicate and not isinstance(predicate["model_assignment"], str):
            raise ValueError("Cohort model filter must be a model ID string")
        if "include_dead" in definition and not isinstance(definition["include_dead"], bool):
            raise ValueError("Include dead identities must be true or false")
        region = predicate.get("region")
        if region is not None and (not isinstance(region, list) or len(region) != 4
                or not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in region)
                or not region[0] <= region[2] or not region[1] <= region[3]):
            raise ValueError("Cohort region must be [xmin, ymin, xmax, ymax] with finite ordered bounds")
        revision = definition.get("reference_revision")
        if revision is not None and (isinstance(revision, bool) or not isinstance(revision, (str, int))
                                     or not str(revision).isdigit()):
            raise ValueError("Cohort reference revision must be a nonnegative integer")
        reference_time = definition.get("reference_time")
        if reference_time is not None:
            try:
                reference_time = str(exact_time(reference_time))
            except (ValueError, TypeError, ZeroDivisionError, OverflowError):
                raise ValueError("Cohort reference time must be a finite simulation time") from None
        state = self.snapshot(run_id, time=reference_time, revision=revision)["state"]
        if revision is not None and int(revision) != int(state.get("revision", 0)):
            raise ValueError("Cohort reference time and revision must identify the same selected state")
        if definition.get("mode") == "fixed" and "members" not in definition:
            dynamic = dict(definition, mode="dynamic")
            definition["members"] = self.visualization.cohort_members(state, dynamic)
        elif definition.get("mode") == "fixed":
            members = definition["members"]
            if not isinstance(members, list) or any(isinstance(x, bool) or not isinstance(x, (str, int)) for x in members):
                raise ValueError("Fixed cohort members must be a list of agent IDs")
            members = [str(x) for x in members]
            if len(set(members)) != len(members) or any(x not in state["agents"] for x in members):
                raise ValueError("Fixed cohort members must be distinct IDs present at the reference cursor")
            definition["members"] = members
        if "id" in definition and (not isinstance(definition["id"], str) or not definition["id"].strip()):
            raise ValueError("Cohort ID must contain text")
        definition.setdefault("id", uuid.uuid4().hex)
        definition.setdefault("predicate", {})
        definition.setdefault("include_dead", True)
        definition["reference_revision"] = str(state.get("revision", 0))
        definition["reference_time"] = str(state.get("time", 0))
        with self.lock, self.catalog:
            self.catalog.save_view(run_id, definition)
        return definition


    def branch(self, run_id, request):
        """Stage a complete child before publishing its durable reserved identity."""
        self._require_writable()
        from .engine import Simulation
        from .runtime import restore_revision, branch as branch_engine, serialize, checkpoint, close
        command_id = request.get("command_id") or str(uuid.uuid4())
        with self.lock:
            parent = self._row(run_id)
            previous = self.catalog.command(command_id)
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
                with self.catalog:
                    self.catalog.insert_command(command_id, run_id, 'branch', request, 'pending', response)
            directory = self.root / "runs" / child_id
            if not (directory / "worker-checkpoint.json").exists():
                source = Path(parent["directory"]) / "run.sqlite"
                reader = self.repository.history_factory(source, read_only=True)
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
                    with self.catalog:
                        self.catalog.update_command(command_id, response=response)
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
                with self.catalog:
                    self.catalog.update_command(command_id, response=response)
                os.replace(stage, directory)
                lineage = {"parent_run_id": run_id, "revision": str(revision), "seed": request.get("seed"), "history": str(source)}
                with self.catalog:
                    self.catalog.insert_run(child_id, str(directory), resolved, 'paused', generation=0, frontier=frontier, parent=lineage, replace=True)
            elif not self.catalog.run(child_id):
                manifest = json.loads((directory / "manifest.json").read_text())
                with self.catalog:
                    self.catalog.insert_run(child_id, str(directory), manifest['config'], 'paused', parent={'parent_run_id': run_id})
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
            with self.catalog:
                self.catalog.update_command(command_id, status='applied', response=response)
            self.launch_worker(child_id)
            return response


    def cohort_view(self, run_id, time=None, revision=None, *, cancel_event=None):
        """A read-only cohort result explicitly bound to the projected cursor."""
        bundle = self.snapshot(run_id, time=time, revision=revision, cancel_event=cancel_event)
        result = self.cohorts(run_id, bundle["state"], cancel_event=cancel_event)
        _check_view_cancelled(cancel_event)
        return {"run_id": run_id, "cursor": {"time": bundle["time"], "revision": bundle["revision"]},
                "cohorts": result}


    def cohorts(self, run_id, state=None, *, cancel_event=None):
        check = lambda: _check_view_cancelled(cancel_event)
        check()
        if state is None:
            state = self.snapshot(run_id, cancel_event=cancel_event)["state"]
        with _view_lock(self.lock, cancel_event):
            definitions = self.catalog.views(run_id)
        for definition in definitions:
            definition.setdefault("name", "Unnamed cohort")
            definition.setdefault("predicate", {})
            definition.setdefault("include_dead", True)
        if not definitions:
            return []
        # The displayed state's run ID/lineage selects the actual run entry.
        # A child starts at its branch boundary; inherited-prefix replay still
        # belongs to the historical source run, including nested branches.
        history = self.history(run_id)
        try:
            if cancel_event is not None:
                history.set_cancellation(cancel_event)
            from .cohort_survival import run_entry
            entry = run_entry(history,state,check_cancelled=check)
        except Exception:
            check()
            raise
        finally:
            history.close()
        # Enrich legacy labels without rewriting any saved definition. Their
        # original membership was selected at the recorded revision boundary.
        legacy = [definition for definition in definitions if "reference_time" not in definition]
        if legacy:
            history = self.history(run_id)
            try:
                if cancel_event is not None:
                    history.set_cancellation(cancel_event)
                times = {}
                for definition in legacy:
                    check()
                    reference = definition["reference_revision"]
                    if reference not in times:
                        row = history.boundary(reference)
                        times[reference] = str(exact_time({"n": row[0], "d": row[1]})) if row else None
                    definition["reference_time"] = times[reference]
            except Exception:
                check()
                raise
            finally:
                history.close()
        result = []
        episodes = state.get("episodes", {})
        for definition in definitions:
            check()
            summary = self.visualization.cohort_summary(state, definition, check_cancelled=check)
            members = set(summary["members"])
            reference = int(definition["reference_revision"])
            selected = [episode for episode in episodes.values() if str(episode.get("agent_id", episode.get("agent"))) in members]
            summary.update(member_ids=summary["members"],
                           cures=sum(episode.get("outcome") == "CURED" for episode in selected),
                           conversions=sum(episode.get("outcome") == "CONVERTED" for episode in selected),
                           new_incidence=sum(int(episode.get("onset_revision", 0)) > reference for episode in selected))
            agents = [state["agents"][identity] for identity in members if identity in state["agents"]]
            from .cohort_survival import survival_counts
            summary.update(survival_counts(agents, entry, missing=len(members) - len(agents), check_cancelled=check))
            result.append(summary)
        check()
        return result


    def restart_checkpoint(self, run_id, name):
        """Restart the current committed boundary from a named exact checkpoint."""
        self._require_writable()
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


    def comparison(self, sources, *, cancel_event=None):
        """Compare captured run frontiers without changing their execution."""
        check = lambda: _check_view_cancelled(cancel_event)

        def open_history(run_id):
            check()
            history = self.history(run_id)
            try:
                if cancel_event is not None:
                    history.set_cancellation(cancel_event)
                check()
                return history
            except BaseException:
                history.close()
                raise

        return self.comparisons.compare(sources, open_history, check_cancelled=check)


    def timeline(self, run_id, revision=None, agent=None, *, time=None, limit=500,
                 before_sequence=None, after_sequence=None, cancel_event=None):
        """Read-only event pages, pinned to an exact source cursor."""
        history = self.history(run_id)
        check = lambda: _check_view_cancelled(cancel_event)
        try:
            check()
            if cancel_event is not None:
                history.set_cancellation(cancel_event)
            return self.timelines.page(history, run_id, revision, agent, time=time, limit=limit,
                              before_sequence=before_sequence, after_sequence=after_sequence,
                              check_cancelled=check)
        except Exception:
            check()
            raise
        finally:
            history.close()


    def _require_writable(self):
        return self.repository.require_writable()

    def close(self):
        # Explicit server shutdown saves managed runs. A browser disconnect does
        # not call this method and cannot stop a run.
        self.workers.close(lambda run_id: self.command(run_id, "stop", wait=True))
        self.queries.close()
        self.metrics.close()
        self.repository.close()
