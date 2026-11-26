"""Resume a real pending command from an immutable retained runtime journal.

The source is verified and copied with SQLite backup, never mutated. Ordinary
restore_revision and execute_script_command complete every pending event under
the existing run configuration. Immutable historical row bytes are compared
against the source after the recovered simulation has closed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import traceback
import zlib


def digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b""):
            value.update(block)
    return value.hexdigest()


def read_only(path):
    return sqlite3.connect(f"file:{Path(path).absolute()}?mode=ro", uri=True)


def compare_rows(source, target, table, predicate="", arguments=()):
    order = "sequence" if table == "events" else "agent_id,sequence" if table == "participants" else "revision"
    query = f'SELECT * FROM "{table}" {predicate} ORDER BY {order}'
    left = source.execute(query, arguments)
    right = target.execute(query, arguments)
    count = 0
    while True:
        a, b = left.fetchmany(128), right.fetchmany(128)
        if a != b:
            raise ValueError(f"Historical {table} rows differ from the retained prefix")
        count += len(a)
        if not a:
            return count


def check_prefix(source, target, revision, event_sequence):
    return {table: compare_rows(source, target, table, "WHERE revision<=?", (revision,))
            for table in ("commits", "runtime_commits", "events")} | {
                "participants": compare_rows(source, target, "participants", "WHERE sequence<=?", (event_sequence,))}


def save_manifest(path, result):
    temporary = path.with_suffix(path.suffix + ".partial")
    with temporary.open("w") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def continue_run(source_path, destination_path, source_sha256, command_id, *, frozen_wheel=None):
    from zombie_sim.commands import execute_script_command
    from zombie_sim.runtime import restore_revision
    from zombie_sim.testing import ControlledSimulation

    source_path, destination_path = Path(source_path).absolute(), Path(destination_path).absolute()
    if source_path == destination_path or destination_path.exists():
        raise FileExistsError("A new continuation primary is required; the retained prefix is immutable")
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = destination_path.with_suffix(destination_path.suffix + ".continuation.json")
    result = {"schema": "zombie-sim/journal-continuation-v1", "status": "VERIFYING_PREFIX",
              "source": str(source_path), "destination": str(destination_path),
              "source_sha256": source_sha256, "command_id": command_id, "started_at_unix": time.time()}
    result["loaded_modules"] = {name: {"path": str(Path(module.__file__).absolute()), "sha256": digest(module.__file__)}
                                for name in ("zombie_sim.engine", "zombie_sim.runtime", "zombie_sim.testing")
                                if (module := sys.modules.get(name)) is not None}
    if frozen_wheel:
        result["frozen_wheel"] = {"path": str(Path(frozen_wheel).absolute()), "sha256": digest(frozen_wheel)}
    save_manifest(manifest, result)
    sim = None
    try:
        if digest(source_path) != source_sha256:
            raise ValueError("Retained prefix checksum does not match its retention evidence")
        source = read_only(source_path)
        try:
            prefix_revision = source.execute("SELECT MAX(revision) FROM commits").fetchone()[0]
            prefix_sequence = source.execute("SELECT MAX(sequence) FROM events").fetchone()[0] or 0
            runtime_patch = json.loads(zlib.decompress(source.execute(
                "SELECT patch FROM runtime_commits ORDER BY revision DESC LIMIT 1").fetchone()[0]))
            recorded_settings = {entry[1][1]: entry[2] for entry in runtime_patch
                                 if entry[0] == "set" and len(entry[1]) == 2 and entry[1][0] == "attributes"
                                 and entry[1][1] in {"seed", "workers", "worker_request", "decision_mode", "backend"}}
            row = source.execute("SELECT payload FROM metadata WHERE key='active_control_command'").fetchone()
            command = json.loads(zlib.decompress(row[0])) if row else None
            if not command or command.get("id") != command_id or command.get("operation") != "advance":
                raise ValueError("Source has no matching actual pending advance command")
            if source.execute("SELECT 1 FROM control_commands WHERE command_id=?", (command_id,)).fetchone():
                raise ValueError("Source command is already acknowledged; this is not pending-command recovery")
            identity = source.execute("SELECT payload FROM metadata WHERE key=?", ("script_command:" + command_id,)).fetchone()
            identity = json.loads(zlib.decompress(identity[0])) if identity else None
            if identity != {"operation": "advance", "payload": command["request"]}:
                raise ValueError("Pending command request differs from its durable identity")
            copied = sqlite3.connect(destination_path)
            try:
                source.backup(copied)
                if copied.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("Copied continuation ledger failed quick_check")
                result["copied_prefix_rows_verified"] = check_prefix(source, copied, prefix_revision, prefix_sequence)
                copied.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                copied.close()
        finally:
            source.close()
        with destination_path.open("rb") as stream:
            os.fsync(stream.fileno())
        result.update(status="RESTORING", prefix_revision=prefix_revision, prefix_event_sequence=prefix_sequence,
                      pending_command=command, copied_at_unix=time.time())
        save_manifest(manifest, result)
        sim = restore_revision(ControlledSimulation, destination_path, output_history_path=destination_path)
        for key, value in recorded_settings.items():
            if getattr(sim, key) != value:
                raise ValueError(f"Recovery changed recorded execution setting {key}")
        result["restored"] = {"run_id": sim.state["run_id"], "seed": sim.seed, "time": str(sim.time),
                              "revision": sim.revision, "run_status": sim.run_status, "workers": sim.workers,
                              "worker_request": sim.worker_request, "horizon": str(sim.horizon),
                              "checkpoint_interval": sim.config.get("checkpoint_interval"),
                              "checkpoint_transactions": sim.config.get("checkpoint_transactions"),
                              "pending_events_through_horizon": sum(entry[0] <= sim.horizon for entry in sim.queue)}
        result.update(status="CONTINUING", restored_at_unix=time.time())
        save_manifest(manifest, result)
        receipt = execute_script_command(sim, "advance", command["request"], command_id,
                                         desired_control=command["desired_control"])
        if sim.run_status != "COMPLETED" or receipt.get("run_status") != "completed":
            raise ValueError("Recovered actual command did not complete the run")
        if str(sim.time) != str(sim.horizon) or any(entry[0] <= sim.horizon for entry in sim.queue):
            raise ValueError("Recovered horizon still has undispatched events")
        result.update(status="COMPLETED_VERIFYING_PREFIX", receipt=receipt, final_revision=sim.revision,
                      final_time=str(sim.time), termination_reason=sim.termination_reason,
                      completed_at_unix=time.time(), final_execution_counters=sim.execution_counters.copy())
        sim.close()
        sim = None
        save_manifest(manifest, result)
        source, target = read_only(source_path), read_only(destination_path)
        try:
            result["final_prefix_rows_verified"] = check_prefix(source, target, prefix_revision, prefix_sequence)
            if target.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("Completed continuation ledger failed quick_check")
            result["appended_revisions"] = result["final_revision"] - prefix_revision
            result["appended_events"] = target.execute("SELECT COUNT(*) FROM events WHERE sequence>?", (prefix_sequence,)).fetchone()[0]
        finally:
            source.close()
            target.close()
        if digest(source_path) != source_sha256:
            raise ValueError("Original retained prefix changed during recovery")
        with destination_path.open("rb") as stream:
            os.fsync(stream.fileno())
        result.update(status="COMPLETED_VERIFIED", final_sha256=digest(destination_path),
                      final_bytes=destination_path.stat().st_size, finished_at_unix=time.time())
        save_manifest(manifest, result)
        return result
    except BaseException:
        result.update(status="FAILED", traceback=traceback.format_exc(), failed_at_unix=time.time())
        save_manifest(manifest, result)
        raise
    finally:
        if sim is not None:
            sim.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--command-id", required=True)
    parser.add_argument("--frozen-wheel")
    args = parser.parse_args()
    print(json.dumps(continue_run(args.source, args.destination, args.source_sha256, args.command_id,
                                  frozen_wheel=args.frozen_wheel)), flush=True)
