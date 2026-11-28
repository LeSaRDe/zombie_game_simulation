"""Differential and rejection checks using a real, completed coordinator ledger."""

try:
    from implementation_checks.check_output import artifact_output
except ModuleNotFoundError:
    from check_output import artifact_output

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zombie_sim.testing import FrameworkTestAdapter, normalize_snapshot
from zombie_sim.testing_recovery import RecoveredWorkflowAdapter, RecoveryEvidenceError
from zombie_sim.storage import _pack, _unpack


def main():
    request = {"kind": "workflow", "setup": {"runs": {"sample": {
        "world": {"length": 40, "width": 40, "agents": [{"id": "h", "type": "Human", "x": 10, "y": 10}]},
        "config": {"seed": 17, "horizon": "3", "decision_mode": "model", "workers": 1,
                   "checkpoint_interval": 30},
    }}}, "steps": [
        {"op": "run.create", "run": "sample", "label": "identity"},
        {"op": "run.capture", "run": "sample", "what": "initial_snapshot", "label": "initial"},
        {"op": "run.script", "run": "sample", "steps": [{"op": "advance", "to": "1"}], "label": "first_receipt"},
        {"op": "run.capture", "run": "sample", "what": "semantic_snapshot", "label": "middle"},
        {"op": "run.script", "run": "sample", "steps": [{"op": "advance", "to": "3"}], "label": "last_receipt"},
        {"op": "run.capture", "run": "sample", "what": "semantic_snapshot", "label": "final"},
        {"op": "run.capture", "run": "sample", "what": "status", "label": "status"},
    ]}
    report = {"checks": {}}
    with TemporaryDirectory(prefix="zombie-recovered-workflow-") as temporary:
        root = Path(temporary)
        normal = FrameworkTestAdapter(workdir=root / "normal")
        try:
            expected = normal.execute(deepcopy(request))
        finally:
            normal.close()
        ledger = root / "normal/sample/run-0.sqlite"
        digest_before = hashlib.sha256(ledger.read_bytes()).hexdigest()

        def evaluate(candidate=request, source=ledger, alias="sample"):
            adapter = RecoveredWorkflowAdapter(workdir=root / "reader", ledgers={alias: source})
            try:
                return adapter.execute(deepcopy(candidate))
            finally:
                adapter.close()

        actual = evaluate()
        assert actual["captures"] == expected["captures"], "Recovered captures differ from the normal workflow"
        for field in ("normalization", "workers"):
            assert actual["diagnostics"][field] == expected["diagnostics"][field]
        assert actual["diagnostics"]["evaluation"] == "recovered-capture-evaluation"
        assert actual["captures"]["final"]["agents"]["h"]["model_memory"], "Fixture must exercise actual model memory"
        report["checks"]["all_captures_exactly_equal"] = True
        report["checks"]["common_diagnostics_exactly_equal"] = True
        report["checks"]["recovery_explicitly_identified"] = True
        report["capture_labels"] = list(actual["captures"])
        report["status"] = actual["captures"]["status"]
        report["history"] = actual["diagnostics"]["verified_history"]
        private = deepcopy(expected["captures"]["final"])
        private["ownership_probe"] = {"nested": [{"values": [None, True, 2, 1.25, "text"]}]}
        untouched = deepcopy(private)
        ordinary = normalize_snapshot(private)
        transferred = normalize_snapshot(private, copy_snapshot=False)
        assert transferred == ordinary and private == untouched
        transferred["ownership_probe"]["nested"][0]["values"].append("modified output")
        transferred["agents"]["h"]["model_memory"]["detachment_probe"] = ["modified output"]
        assert private == untouched and ordinary != transferred
        private["ownership_probe"]["nested"][0]["values"].append("modified input")
        assert "modified input" not in transferred["ownership_probe"]["nested"][0]["values"]
        report["checks"]["private_snapshot_path_exact_and_detached"] = True

        def rejects(name, candidate=request, source=ledger, alias="sample"):
            try:
                evaluate(candidate, source, alias)
            except (RecoveryEvidenceError, sqlite3.DatabaseError) as error:
                report["checks"][name] = {"rejected": True, "reason": str(error)}
            else:
                raise AssertionError(f"Invalid recovery evidence was accepted: {name}")

        rejects("missing_ledger", source=root / "absent.sqlite")
        candidate = deepcopy(request)
        candidate["setup"]["runs"]["sample"]["config"]["seed"] += 1
        rejects("mismatched_config", candidate)
        candidate = deepcopy(request)
        candidate["steps"][4]["steps"][0]["to"] = "2"
        rejects("mismatched_command_payload", candidate)
        candidate = deepcopy(request)
        candidate["setup"]["runs"]["different"] = candidate["setup"]["runs"].pop("sample")
        for step in candidate["steps"]:
            step["run"] = "different"
        rejects("mismatched_command_id", candidate, alias="different")
        candidate = deepcopy(request)
        candidate["steps"] = candidate["steps"][:4]
        rejects("early_workflow_cursor", candidate)

        def corrupted_copy(name, mutate):
            path = root / f"{name}.sqlite"
            with sqlite3.connect(f"file:{ledger}?mode=ro", uri=True) as source:
                with sqlite3.connect(path) as destination:
                    source.backup(destination)
                    mutate(destination)
                    destination.commit()
            return path

        rejects("pending_receipt", source=corrupted_copy("pending", lambda db: db.execute(
            "UPDATE control_commands SET status='pending' WHERE command_id='sample-script-1'")))
        rejects("failed_receipt", source=corrupted_copy("failed", lambda db: db.execute(
            "UPDATE control_commands SET status='rejected',payload=? WHERE command_id='sample-script-1'",
            (_pack({"command_id": "sample-script-1", "status": "rejected"}),))))
        rejects("missing_receipt", source=corrupted_copy("missing", lambda db: db.execute(
            "DELETE FROM control_commands WHERE command_id='sample-script-1'")))
        rejects("incomplete_runtime_history", source=corrupted_copy("runtime-gap", lambda db: db.execute(
            "DELETE FROM runtime_commits WHERE revision=(SELECT MAX(revision) FROM runtime_commits)")))
        rejects("corrupt_world_delta", source=corrupted_copy("checksum", lambda db: db.execute(
            "UPDATE commits SET checksum='invalid' WHERE revision=1")))

        def early_terminal(db):
            payload = db.execute("SELECT payload FROM control_commands WHERE command_id='sample-script-1'").fetchone()[0]
            receipt = _unpack(payload)
            receipt["run_status"] = "paused"
            receipt["control"]["status"] = "paused"
            db.execute("UPDATE control_commands SET payload=? WHERE command_id='sample-script-1'", (_pack(receipt),))
        rejects("nonterminal_acknowledgement", source=corrupted_copy("nonterminal", early_terminal))

        def misleading_completed_ack(db):
            payload = db.execute("SELECT payload FROM control_commands WHERE command_id='sample-script-0'").fetchone()[0]
            receipt = _unpack(payload)
            revision = int(receipt["revision"])
            for table in ("commits", "runtime_commits", "events"):
                db.execute(f"DELETE FROM {table} WHERE revision>?", (revision,))
            db.execute("DELETE FROM control_commands WHERE command_id='sample-script-1'")
            db.execute("DELETE FROM metadata WHERE key='script_command:sample-script-1'")
            receipt["run_status"] = "completed"
            receipt["control"]["status"] = "completed"
            db.execute("UPDATE control_commands SET payload=? WHERE command_id='sample-script-0'", (_pack(receipt),))
            db.execute("UPDATE metadata SET payload=? WHERE key='control_state'", (_pack(receipt["control"]),))
        early = deepcopy(request)
        early["steps"] = early["steps"][:4]
        rejects("completed_ack_before_actual_terminal_boundary", early,
                source=corrupted_copy("misleading-completed", misleading_completed_ack))
        assert hashlib.sha256(ledger.read_bytes()).hexdigest() == digest_before
        report["checks"]["source_primary_bytes_unchanged"] = True
        report["passed"] = True
    output = artifact_output(Path("artifacts/recovered-workflow-check.json"))
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
