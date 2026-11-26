"""Preserve an exactly completed isolated run before retiring its capture worker.

This operator tool reads the real command acknowledgement and entire SQLite
ledger. It never advances a simulation, rewrites a result, or changes assertions.
Only the explicitly identified writable-ledger owner may be stopped. Failed
validation/copy always resumes that process; optional termination occurs only
after a durable, verified backup and its manifest have been published.
"""
from __future__ import annotations
import argparse
import fcntl
from fractions import Fraction
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time
import uuid
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.archive_checkpoint import digest, process_identity, stopped_coordinator, sync_directory


def completion(connection, command_id, expected_time):
    frontier = connection.execute("SELECT revision,time_n,time_d,checksum FROM commits ORDER BY revision DESC LIMIT 1").fetchone()
    row = connection.execute("SELECT status,revision,payload FROM control_commands WHERE command_id=?", (command_id,)).fetchone()
    if not frontier or not row or row[0] != "applied":
        return None
    acknowledgement = json.loads(zlib.decompress(row[2]))
    expected = Fraction(str(expected_time))
    if (Fraction(int(frontier[1]), int(frontier[2])) != expected
            or Fraction(str(acknowledgement["time"])) != expected
            or acknowledgement.get("run_status") != "completed"
            or acknowledgement.get("status") != "applied"
            or row[1] != frontier[0]
            or int(acknowledgement["revision"]) != frontier[0]):
        raise ValueError("Command acknowledgement does not prove exact completed frontier")
    active = connection.execute("SELECT payload FROM metadata WHERE key='active_control_command'").fetchone()
    if active is None or json.loads(zlib.decompress(active[0])) is not None:
        raise ValueError("The completed command remains active")
    if connection.execute("SELECT MAX(revision) FROM runtime_commits").fetchone()[0] != frontier[0]:
        raise ValueError("World and runtime frontiers differ")
    return {"revision": frontier[0], "time": str(expected), "commit_checksum": frontier[3],
            "command_acknowledgement": acknowledgement}


def write_manifest(path, value):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".partial")
    with temporary.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    sync_directory(path.parent)


def interrupted(signum, _frame):
    """Unwind process-stop contexts on ordinary operator cancellation."""
    raise SystemExit(128 + signum)


def preserve(ledger, destination, command_id, expected_time, pid, *, wait_seconds=0, terminate=False):
    ledger = Path(ledger).absolute()
    destination = Path(destination).absolute()
    if ledger.is_symlink() or destination == ledger or ledger.parent in destination.parents:
        raise ValueError("Backup must be outside the unredirected live-run directory")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = destination.with_suffix(destination.suffix + ".preservation.json")
    with destination.with_suffix(destination.suffix + ".preservation.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if destination.exists() or manifest.exists():
            raise FileExistsError("Refusing to replace a preserved ledger or its provenance")
        expected_identity = process_identity(pid, ledger)
        started = time.time()
        deadline = time.monotonic() + wait_seconds
        reader = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True, timeout=2)
        try:
            while True:
                proof = completion(reader, command_id, expected_time)
                if proof is not None:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("Exact completed command acknowledgement is not durable yet")
                current = process_identity(pid, ledger)
                if current["start_ticks"] != expected_identity["start_ticks"]:
                    raise ValueError("Coordinator PID changed while waiting")
                time.sleep(1)
            result = {"schema": "zombie-sim/completed-run-preservation-v1", "status": "COPYING",
                      "source": str(ledger), "path": str(destination), "coordinator_pid": pid,
                      "process_identity": expected_identity, "started_at_unix": started,
                      "completion_observed_at_unix": time.time(), **proof}
            # A hard SIGKILL cannot unwind a Python finally block. Persist the
            # exact owned PID/start generation before stopping it so an operator
            # can identify and resume that same process after an abrupt loss.
            write_manifest(destination.with_suffix(destination.suffix + ".preservation.intent.json"),
                           {**result, "status": "STOP_INTENT", "hard_kill_recovery":
                            "Verify the recorded PID start_ticks and writable ledger identity before SIGCONT; never signal a reused PID."})
            with stopped_coordinator(pid, ledger, expected_identity, result):
                if completion(reader, command_id, expected_time) != proof:
                    raise ValueError("Completed frontier changed before preservation")
                partial = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".partial")
                writer = sqlite3.connect(partial)
                try:
                    reader.backup(writer)
                    if writer.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                        raise ValueError("Preserved SQLite ledger failed quick_check")
                    if completion(writer, command_id, expected_time) != proof:
                        raise ValueError("Backup does not contain the exact completed command")
                    result["table_counts"] = {name: writer.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
                                              for (name,) in writer.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()}
                    writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                finally:
                    writer.close()
                with partial.open("rb") as stream:
                    os.fsync(stream.fileno())
                result.update(bytes=partial.stat().st_size, sha256=digest(partial), status="VERIFIED")
                os.link(partial, destination)
                partial.unlink()
                sync_directory(destination.parent)
                result["verified_at_unix"] = time.time()
                write_manifest(manifest, result)
                if terminate:
                    current = process_identity(pid, ledger)
                    if current["start_ticks"] != expected_identity["start_ticks"] or completion(reader, command_id, expected_time) != proof:
                        raise ValueError("Identity or completed frontier changed before capture-worker termination")
                    # SIGTERM becomes effective when the context finally resumes
                    # this stopped process. All simulation data is already saved.
                    os.kill(pid, signal.SIGTERM)
                    result["capture_worker_termination_requested"] = True
            result["finished_at_unix"] = time.time()
            write_manifest(manifest, result)
            return result
        finally:
            reader.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    parser.add_argument("destination")
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--expected-time", required=True)
    parser.add_argument("--coordinator", required=True, type=int)
    parser.add_argument("--wait-seconds", type=float, default=0)
    parser.add_argument("--terminate-after-backup", action="store_true")
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, interrupted)
    print(json.dumps(preserve(args.ledger, args.destination, args.command_id, args.expected_time,
                              args.coordinator, wait_seconds=args.wait_seconds, terminate=args.terminate_after_backup)), flush=True)
