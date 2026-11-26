"""Independently exercise exact completion gating, backup, and process cleanup."""
from pathlib import Path
import multiprocessing
import os
import signal
import sqlite3
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import preserve_completed_run as operator
from zombie_sim.commands import execute_script_command
from zombie_sim.engine import Simulation
from zombie_sim.storage import History


def coordinator(pipe, path):
    sim = Simulation({"agents": [{"id": "a", "type": "Human", "x": 10, "y": 10}],
                      "decision_mode": "scripted", "horizon": 2, "execution": {"workers": 1}}, history_path=path)
    try:
        pipe.send("ready")
        while True:
            command = pipe.recv()
            if command == "finish":
                execute_script_command(sim, "advance", {"to": "2"}, "probe")
                pipe.send("completed")
            elif command == "ping":
                pipe.send("alive")
            else:
                break
    finally:
        sim.close()
        pipe.close()


def raw_tables(path):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {name: c.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        c.close()


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        run = root / "run"
        run.mkdir()
        ledger = run / "live.sqlite"
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        process = context.Process(target=coordinator, args=(child, str(ledger)))
        process.start()
        child.close()
        try:
            assert parent.recv() == "ready"
            try:
                operator.preserve(ledger, root / "premature.sqlite", "probe", "2", process.pid)
            except TimeoutError:
                pass
            else:
                raise AssertionError("An unfinished simulation must never be stopped/preserved")
            parent.send("ping")
            assert parent.recv() == "alive"
            parent.send("finish")
            assert parent.recv() == "completed"
            before = raw_tables(ledger)
            original_digest = operator.digest
            try:
                def fail_digest(_):
                    raise RuntimeError("Injected verification failure")
                operator.digest = fail_digest
                try:
                    operator.preserve(ledger, root / "failure.sqlite", "probe", "2", process.pid)
                except RuntimeError as error:
                    assert "Injected" in str(error)
                else:
                    raise AssertionError("Expected verification failure")
            finally:
                operator.digest = original_digest
            parent.send("ping")
            assert parent.recv() == "alive"
            assert raw_tables(ledger) == before
            previous_handler = signal.signal(signal.SIGTERM, operator.interrupted)
            try:
                def cancel_digest(_):
                    os.kill(os.getpid(), signal.SIGTERM)
                operator.digest = cancel_digest
                try:
                    operator.preserve(ledger, root / "cancelled.sqlite", "probe", "2", process.pid)
                except SystemExit as error:
                    assert error.code == 143
                else:
                    raise AssertionError("SIGTERM must unwind the stopped coordinator context")
            finally:
                operator.digest = original_digest
                signal.signal(signal.SIGTERM, previous_handler)
            parent.send("ping")
            assert parent.recv() == "alive"
            assert raw_tables(ledger) == before
            assert (root / "cancelled.sqlite.preservation.intent.json").exists()
            destination = root / "complete.sqlite"
            result = operator.preserve(ledger, destination, "probe", "2", process.pid)
            assert result["status"] == "VERIFIED" and result["time"] == "2"
            assert result["sha256"] == operator.digest(destination)
            assert raw_tables(ledger) == raw_tables(destination) == before
            source = History(ledger, read_only=True)
            saved = History(destination, read_only=True)
            try:
                for revision in range(result["revision"] + 1):
                    assert source.state_at(revision=revision) == saved.state_at(revision=revision)
                    assert source.runtime_at(revision=revision) == saved.runtime_at(revision=revision)
            finally:
                source.close()
                saved.close()
            parent.send("ping")
            assert parent.recv() == "alive"
            terminated = operator.preserve(ledger, root / "terminated.sqlite", "probe", "2", process.pid, terminate=True)
            process.join(5)
            assert process.exitcode == -15 and terminated["capture_worker_termination_requested"]
            assert raw_tables(root / "terminated.sqlite") == before
            print({"completed_run_preservation": "passed", "historical_revisions_verified": result["revision"] + 1,
                   "failed_verification_resumed_coordinator": True, "termination_only_after_verified_backup": True})
        finally:
            if process.is_alive():
                parent.send("close")
                process.join(5)
            parent.close()


if __name__ == "__main__":
    main()
