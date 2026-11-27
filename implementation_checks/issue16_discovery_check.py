"""Verify registration costs and audit retention without reconstructing scenes."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

from zombie_sim.application import RunManager
from zombie_sim.storage import History, canonical, _pack


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report = {"passed": False, "checks": []}
    with tempfile.TemporaryDirectory(prefix="zombie-i16-") as tmp:
        root = Path(tmp)
        identities = ["long", "stale", "stopped", "branch", "corrupt"]
        for identity in identities:
            directory = root / "runs" / identity
            directory.mkdir(parents=True)
            manifest = {"run_id": identity, "config": {"seed": 42}, "status": "running",
                        "time": "0", "revision": 0}
            if identity == "stopped": manifest["status"] = "stopped"
            if identity == "branch": manifest["parent"] = {"run_id": "retained-parent", "revision": 8}
            (directory / "manifest.json").write_text(canonical(manifest))
            history = History(directory / "run.sqlite", initial={"run_id": identity, "time": "0", "revision": 0,
                "agents": {str(i): {"id": str(i), "type": "Human"} for i in range(1000)}})
            count = 20000 if identity == "long" else 10
            with history.connection:
                for revision in range(1, count + 1):
                    blob = _pack([["set", ["revision"], revision], ["set", ["time"], f"{revision}/3"]])
                    history.connection.execute("INSERT INTO commits VALUES(?,?,?,?,?,?,?,?)",
                        (revision, f"fixture:{revision}", str(revision), "3", revision / 3,
                         blob, None, hashlib.sha256(blob).hexdigest()))
                if identity == "corrupt":
                    history.connection.execute("UPDATE commits SET checksum='tampered' WHERE revision=10")
            if identity == "stale":
                history.set_metadata("control_state", {"status": "terminated", "generation": 9, "pacing": 2})
            history.close()
        files = list((root / "runs").glob("*/*.json")) + list((root / "runs").glob("*/run.sqlite"))
        before = {str(path): digest(path) for path in files}
        with patch.object(History, "state_at", side_effect=AssertionError("Startup reconstructed a scene")), \
             patch.object(History, "runtime_at", side_effect=AssertionError("Startup restored a runtime")):
            start = time.monotonic()
            manager = RunManager(root)
            report["first_registration_seconds"] = time.monotonic() - start
            rows = {row["id"]: row for row in manager.list_runs()}
            assert rows["long"]["frontier"]["revision"] == "20000"
            assert rows["long"]["frontier"]["time"] == "20000/3"
            assert rows["long"]["status"] == "interrupted"
            assert rows["stale"]["status"] == "terminated" and rows["stale"]["generation"] == 9
            assert rows["stopped"]["status"] == "stopped"
            assert json.loads(rows["branch"]["parent"])["run_id"] == "retained-parent"
            manager.close()
        report["checks"].append("First registration: 20,001-commit/1,000-identity history; no scene/runtime reads; exact rational frontier; durable termination and lineage")
        with patch.object(History, "__init__", side_effect=AssertionError("Indexed startup opened a history")):
            start = time.monotonic(); manager = RunManager(root)
            report["indexed_startup_seconds"] = time.monotonic() - start
            assert len(manager.list_runs()) == 5
            manager.close()
        report["checks"].append("Indexed startup opens no history")
        manager = RunManager(root, read_only=True)
        try:
            assert manager.read_head("long")["revision"] == "20000"
            for fn in (lambda: manager.create({}), lambda: manager.launch_worker("long"),
                       lambda: manager.command("long", "start"), lambda: manager.save_cohort("long", {}),
                       lambda: manager.branch("long", {}), lambda: manager.restart_checkpoint("long", "x")):
                try: fn()
                except ValueError as error: assert "Read-only" in str(error)
                else: raise AssertionError("Read-only manager accepted mutation")
            try: manager.snapshot("corrupt")
            except ValueError as error: assert "checksum" in str(error)
            else: raise AssertionError("Opening corrupt history skipped validation")
        finally: manager.close()
        report["checks"].append("Read-only managers cannot mutate; deferred scene integrity checks still reject corruption")
        assert before == {str(path): digest(path) for path in files}
        report["checks"].append("All source manifests and SQLite history bytes retained")
        report["passed"] = True
    output = Path("artifacts/issue16-discovery.json")
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__": main()
