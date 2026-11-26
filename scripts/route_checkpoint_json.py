"""Place only the next checkpoint JSON output on a separate filesystem.

The engine's normal open/fsync/os.replace publication follows this exclusively
created future temporary-path link. No existing partial, checkpoint, ledger,
registration, process, cadence, or serialized content is changed by this tool.
The destination JSON is an operational spill, not a portable checkpoint bundle.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.archive_checkpoint import check_files, registered, sync_directory


def route(ledger, checkpoint, registered_revision, destination, *, require_distinct_device=False):
    ledger = Path(ledger).absolute()
    checkpoint = Path(checkpoint).absolute()
    destination = Path(destination).absolute()
    temporary = checkpoint.with_suffix(checkpoint.suffix + ".partial")
    if ledger.is_symlink() or checkpoint.parent != ledger.parent:
        raise ValueError("Expected an unredirected live ledger and its adjacent rolling checkpoint")
    if destination == ledger or ledger.parent in destination.parents:
        raise ValueError("JSON spill must be outside the live-run directory")
    row, _ = check_files(ledger, checkpoint, registered_revision)
    if os.path.lexists(temporary):
        raise FileExistsError("A checkpoint JSON partial already exists; it will never be replaced")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_device = checkpoint.parent.stat().st_dev
    destination_device = destination.parent.stat().st_dev
    if require_distinct_device and source_device == destination_device:
        raise ValueError("The requested capacity spill is not on a different filesystem device")
    # The future writer may open with truncation only after our exclusive target
    # and its directory are durable. An existing destination is never reused.
    with destination.open("xb") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(destination.parent)
    if registered(ledger, checkpoint) != row:
        raise ValueError("Checkpoint generation changed before future-path routing")
    temporary.symlink_to(destination)  # Exclusive: fails if a writer raced us.
    sync_directory(checkpoint.parent)
    result = {"schema": "zombie-sim/future-checkpoint-json-route-v1", "status": "PREPARED",
              "prepared_at_unix": time.time(), "ledger": str(ledger), "checkpoint": str(checkpoint),
              "registered_revision_before": registered_revision, "registered_checksum_before": row[2],
              "future_temporary_path": str(temporary), "spill_target": str(destination),
              "source_device": source_device, "destination_device": destination_device,
              "scope": "Only the next JSON serialization is redirected; the live ledger and sidecar remain unchanged.",
              "portability": "Operational spill JSON, not a standalone portable checkpoint after scratch cleanup."}
    manifest = destination.with_suffix(destination.suffix + ".route.json")
    with manifest.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(manifest.parent)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("ledger")
    parser.add_argument("checkpoint")
    parser.add_argument("registered_revision", type=int)
    parser.add_argument("destination")
    parser.add_argument("--require-distinct-device", action="store_true")
    args = parser.parse_args()
    print(json.dumps(route(args.ledger, args.checkpoint, args.registered_revision, args.destination,
                           require_distinct_device=args.require_distinct_device)), flush=True)
