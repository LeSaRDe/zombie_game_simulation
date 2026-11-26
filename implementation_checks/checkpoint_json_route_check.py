"""Verify actual checkpoint publication through an exclusive future-path link."""
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.archive_checkpoint import digest
from scripts.route_checkpoint_json import route
from zombie_sim.engine import Simulation


def tables(path, exclude_checkpoint=False):
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {name: c.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall()
                for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                if not (exclude_checkpoint and name == "checkpoints")}
    finally:
        c.close()


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        run = root / "run"
        run.mkdir()
        ledger = run / "run.sqlite"
        checkpoint = run / "rolling.json"
        spill = root / "disk" / "rolling.json"
        sim = Simulation({"agents": [{"id": "a", "type": "Human", "x": 10, "y": 10}],
                          "decision_mode": "scripted", "horizon": 5, "execution": {"workers": 1}}, history_path=ledger)
        try:
            sim.advance_until(1, return_snapshot=False)
            sim.checkpoint(checkpoint)
            before = tables(ledger)
            try:
                route(ledger, checkpoint, sim.revision, spill, require_distinct_device=True)
            except ValueError as error:
                assert "different filesystem device" in str(error)
            else:
                raise AssertionError("Capacity routing must reject a same-filesystem target when required")
            route(ledger, checkpoint, sim.revision, spill)
            assert tables(ledger) == before
            partial = checkpoint.with_suffix(".json.partial")
            assert partial.is_symlink() and spill.stat().st_size == 0
            try:
                route(ledger, checkpoint, sim.revision, root / "second.json")
            except (FileExistsError, ValueError):
                pass
            else:
                raise AssertionError("An existing future partial must never be replaced")
            before = tables(ledger, True)
            sim.checkpoint(checkpoint)
            assert tables(ledger, True) == before
            assert checkpoint.is_symlink() and checkpoint.resolve() == spill.resolve()
            assert not partial.exists()
            checksum = digest(spill)
            restored = Simulation.restore(checkpoint)
            try:
                assert restored.state == sim.state and list(restored.events) == list(sim.events)
            finally:
                restored.close()
            sim.advance_until(2, return_snapshot=False)
            sim.checkpoint(checkpoint)
            assert not checkpoint.is_symlink() and digest(spill) == checksum
            replacement = Simulation.restore(checkpoint)
            try:
                assert replacement.state == sim.state and list(replacement.events) == list(sim.events)
            finally:
                replacement.close()
            print({"checkpoint_json_route": "passed", "raw_ledger_unchanged_by_route": True,
                   "checkpoint_restore_verified": True, "subsequent_publication_preserved_spill": True})
        finally:
            sim.close()


if __name__ == "__main__":
    main()
