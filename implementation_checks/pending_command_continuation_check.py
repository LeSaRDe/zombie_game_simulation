"""Resume a genuinely interrupted command and compare the uninterrupted run."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.continue_preserved_run import continue_run, digest
from zombie_sim.commands import execute_script_command
from zombie_sim.faults import arm, clear
from zombie_sim.storage import History
from zombie_sim.testing import ControlledSimulation


def create(path):
    sim = ControlledSimulation({"agents": [
        {"id": "a", "type": "Human", "x": 10, "y": 10},
        {"id": "b", "type": "Human", "x": 20, "y": 10}],
        "decision_mode": "scripted", "horizon": 1, "execution": {"workers": 1}}, history_path=path,
        run_id="continuation-proof")
    sim.submit_intents([{"actor": aid, "action": "wait", "parameters": {"duration": 1}} for aid in ("a", "b")])
    return sim


def main():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "interrupted.sqlite"
        sim = create(source)
        try:
            arm("before_history_commit", occurrence=2)
            try:
                execute_script_command(sim, "advance", {"to": "1"}, "pending")
            except OSError:
                pass
            else:
                raise AssertionError("Actual transaction fault did not interrupt the command")
            finally:
                clear()
        finally:
            sim.close()
        source_hash = digest(source)
        result = continue_run(source, root / "continued.sqlite", source_hash, "pending")
        assert result["restored"]["run_status"] == "PAUSED"
        assert result["restored"]["pending_events_through_horizon"] == 1
        assert result["status"] == "COMPLETED_VERIFIED" and result["termination_reason"] == "HORIZON"
        assert result["final_prefix_rows_verified"] == result["copied_prefix_rows_verified"]
        reference = create(root / "reference.sqlite")
        try:
            receipt = execute_script_command(reference, "advance", {"to": "1"}, "pending")
            saved = History(root / "continued.sqlite", read_only=True)
            try:
                assert saved.state_at() == reference.state
                assert saved.command_result("pending") == receipt
                assert saved.events() == reference.history.events()
            finally:
                saved.close()
        finally:
            reference.close()
        assert digest(source) == source_hash
        print({"pending_command_continuation": "passed", "uninterrupted_state_events_receipt_match": True,
               "source_unchanged": True, "appended_revisions": result["appended_revisions"]})


if __name__ == "__main__":
    main()
