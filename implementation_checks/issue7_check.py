"""I07 browser workflows with disposable real runs and independent cohort oracles."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from issue5_check import Api, until, NODE_MODULES, ROOT


def lifecycle_fixture(workspace):
    """Public engine actions produce a stable history for exact browser replay."""
    from zombie_sim.engine import Simulation
    from zombie_sim.storage import canonical
    directory = Path(workspace) / "runs" / "issue7-lifecycle"
    directory.mkdir(parents=True)
    config = {
        "scenario": "issue7_lifecycle", "seed": 267, "horizon": 4,
        "incubation_duration": 2, "execution": {"workers": 1},
        "placement": {"minimum_separation": 0, "cross_type_separation": 0},
        "profiles": {"Human": {"infection_resistance": 0},
                     "Zombie": {"attack_skill": 1, "virulence": 1},
                     "DOCTOR": {"medical_skill": 1, "treatment_duration": .5}},
        "agents": [
            {"id": "doctor", "type": "Human", "role": "DOCTOR", "x": 30, "y": 30, "inventory": {"MEDICAL_SUPPLY": 2}},
            {"id": "patient", "type": "Human", "x": 31, "y": 30, "infected": True},
            {"id": "converter", "type": "Human", "x": 80, "y": 80, "infected": True},
            {"id": "mortal", "type": "Human", "x": 11, "y": 10, "life": 10},
            {"id": "killer", "type": "Zombie", "x": 10, "y": 10},
            {"id": "mover", "type": "Human", "x": 50, "y": 50},
            {"id": "susceptible", "type": "Human", "x": 61, "y": 60},
            {"id": "biter", "type": "Zombie", "x": 60, "y": 60},
        ],
    }
    simulation = Simulation(config, history_path=directory / "run.sqlite", decision_mode="scripted", run_id="issue7-lifecycle")
    try:
        replies = simulation.submit_intents([
            {"actor": "doctor", "action": "treat_infection", "target": "patient"},
            {"actor": "killer", "action": "claw", "target": "mortal"},
            {"actor": "biter", "action": "bite", "target": "susceptible"},
            {"actor": "mover", "action": "move", "parameters": {"duration": 2, "path": [{"x": 50, "y": 50, "offset": 0}, {"x": 54, "y": 50, "offset": 2}]}},
        ])
        assert all(reply["status"] == "ADMITTED" for reply in replies), replies
        observations = []
        for end in ("1/4", "1/2", "1", "3/2", "2", "7/2", "4"):
            simulation.advance_until(end, return_snapshot=False)
            state = simulation.snapshot()
            observations.append({"time": state["time"], "revision": state["revision"],
                                 "agents": {key: {field: agent.get(field) for field in ("type", "status", "life", "stamina", "x", "infection_episode")} for key, agent in state["agents"].items()}})
        by_time = {str(row["time"]): row["agents"] for row in observations}
        assert by_time["1/2"]["patient"]["status"] == "HEALTHY"
        assert by_time["1"]["mortal"]["status"] == "DEAD"
        assert by_time["3/2"]["susceptible"]["status"] == "INFECTED"
        assert by_time["2"]["converter"]["type"] == "Zombie"
        assert by_time["7/2"]["susceptible"]["type"] == "Zombie"
        assert by_time["1/2"]["mover"]["x"] == 51
        (directory / "manifest.json").write_text(canonical({"run_id": "issue7-lifecycle", "config": simulation.config, "status": "completed"}))
        return {"run_id": "issue7-lifecycle", "observations": observations, "public_intents": replies}
    finally:
        simulation.close()


def selected_ids(state, definition):
    """Predicate oracle deliberately does not call cohort_members/summary."""
    result = []
    predicate = definition.get("predicate", {})
    for identity, agent in state["agents"].items():
        status = "DEAD" if agent["life"] == 0 else "ACTIVE" if agent["type"] == "Zombie" else "INFECTED" if agent.get("infection_episode") else "HEALTHY"
        if not definition.get("include_dead", True) and status == "DEAD":
            continue
        model = agent.get("model_assignment") or {}
        values = {"type": agent["type"], "status": status, "role": agent.get("role"),
                  "model_assignment": model.get("model_id") if isinstance(model, dict) else model}
        if any(value != "" and str(values[key]) != str(value) for key, value in predicate.items() if key in values):
            continue
        region = predicate.get("region")
        if region is not None and not (region[0] <= agent["x"] <= region[2] and region[1] <= agent["y"] <= region[3]):
            continue
        result.append(str(identity))
    return sorted(result)


def cohort_oracle(manager, run_id, data):
    from zombie_sim.storage import exact_time
    from zombie_sim.visualization import project_state
    history = manager.history(run_id)
    try:
        cursor = data["cursor"]
        state = project_state(history.state_at(cursor["time"], int(cursor["revision"])), cursor["time"])
        assert str(state["revision"]) == str(cursor["revision"])
        checked = []
        for row in data["cohorts"]:
            definition = row["definition"]
            reference = project_state(history.state_at(definition["reference_time"], int(definition["reference_revision"])), definition["reference_time"])
            assert exact_time(reference["time"]) == exact_time(definition["reference_time"])
            expected = selected_ids(reference if definition["mode"] == "fixed" else state, definition)
            if definition["mode"] == "fixed":
                assert sorted(definition["members"]) == expected, (definition["name"], "fixed reference IDs")
            assert sorted(row["members"]) == expected, (definition["name"], "membership", row["members"], expected)
            assert sorted(row["member_ids"]) == expected
            agents = [state["agents"][identity] for identity in expected]
            counts = {"healthy": 0, "infected": 0, "zombies": 0, "dead": 0}
            for agent in agents:
                bucket = "dead" if agent["life"] == 0 else "zombies" if agent["type"] == "Zombie" else "infected" if agent.get("infection_episode") else "healthy"
                counts[bucket] += 1
            counts["total"] = len(expected)
            assert row["populations"] == counts
            assert row["denominator"] == row["present"] == len(expected)
            for field in ("life", "stamina"):
                assert row[f"mean_{field}_denominator"] == len(agents)
                if agents:
                    assert math.isclose(row[f"mean_{field}"], sum(agent[field] for agent in agents) / len(agents), rel_tol=1e-12, abs_tol=1e-12)
                else:
                    assert row[f"mean_{field}"] is None
            checked.append({"id": definition["id"], "name": definition["name"], "mode": definition["mode"], "members": expected, "populations": counts,
                            "mean_life": row["mean_life"], "mean_stamina": row["mean_stamina"],
                            "reference_time": definition["reference_time"], "reference_revision": definition["reference_revision"]})
        return {"passed": True, "cursor": cursor, "cohorts": checked}
    finally:
        history.close()


def serve(workspace, port):
    import uvicorn
    from zombie_sim.server import create_app
    app = create_app(workspace); manager = app.state.manager
    lock = threading.Lock(); requests = []; active = {}; maximum = {}
    class Trace:
        def __init__(self, app): self.app = app
        async def __call__(self, scope, receive, send):
            key = None
            if scope["type"] == "http" and scope["path"].startswith("/api/"):
                key = scope["path"]
                with lock:
                    requests.append({"method": scope["method"], "path": key, "query": scope.get("query_string", b"").decode()})
                    active[key] = active.get(key, 0) + 1; maximum[key] = max(maximum.get(key, 0), active[key])
            try: await self.app(scope, receive, send)
            finally:
                if key:
                    with lock: active[key] -= 1
    app.add_middleware(Trace)
    @app.get("/__issue7/diagnostics")
    def diagnostics():
        with lock: trace = list(requests); running = dict(active); peaks = dict(maximum)
        return {"pid": os.getpid(), "requests": trace, "active": running, "maximum": peaks, "runs": manager.list_runs()}
    @app.get("/__issue7/audit")
    def audit():
        result = []
        for row in manager.list_runs():
            digest = hashlib.sha256(); sizes = {}; ledger = Path(row["directory"]) / "run.sqlite"
            if ledger.exists():
                with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as db:
                    for table in ("commits", "runtime_commits", "events", "control_commands", "metadata"):
                        count = 0; digest.update(table.encode())
                        for record in db.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                            count += 1
                            for value in record:
                                encoded = value if isinstance(value, bytes) else repr(value).encode()
                                digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
                        sizes[table] = count
            with manager.lock:
                commands = manager.catalog.command_count(row["id"])
            result.append({"id": row["id"], "status": row["status"], "generation": row["generation"], "frontier": row["frontier"],
                           "commands": commands, "history_and_runtime_digest": digest.hexdigest(), "rows": sizes})
        return result
    @app.post("/__issue7/oracle")
    def oracle(body: dict): return cohort_oracle(manager, body["run_id"], body["data"])
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True); report = {"passed": False, "engine": engine}
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-issue7-") as workspace:
            report["lifecycle_fixture"] = lifecycle_fixture(workspace)
            with socket.socket() as listener: listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", NODE_PATH=NODE_MODULES)
            with (output / "service.log").open("w") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace, "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                report.update(workspace=workspace, port=port, service_pid=process.pid); api = Api(port)
                try:
                    def ready():
                        if process.poll() is not None: raise AssertionError("Test service exited")
                        try: return api.call("/__issue7/diagnostics")
                        except OSError: return None
                    until(ready)
                    from zombie_sim.config import baseline_config
                    configs = {"small": {"scenario": "issue7_small", "seed": 123, "horizon": 20, "execution": {"workers": 1}, "checkpoint_interval": 1000}, "baseline": baseline_config()}
                    configs["baseline"].update(horizon=3, checkpoint_interval=1000); configs["baseline"]["execution"] = {"workers": 1}
                    runs = {"lifecycle": "issue7-lifecycle"}
                    for name, config in configs.items():
                        started = time.monotonic(); receipt = api.call("/api/runs", {"config": config, "command_id": str(uuid.uuid4()), "wait_for_initialization": False}); runs[name] = receipt["run_id"]
                        until(lambda: next(row for row in api.call("/api/runs") if row["id"] == runs[name])["status"] == "paused", timeout=240)
                        report.setdefault("initialization_seconds", {})[name] = time.monotonic() - started
                    report["initial_audit"] = api.call("/__issue7/audit")
                    result = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue7.cjs"), api.base, str(output), json.dumps(runs), engine], cwd=ROOT, env=env, text=True, capture_output=True, timeout=420)
                    (output / "browser.log").write_text(result.stdout + result.stderr)
                    report["browser"] = json.loads((output / "browser.json").read_text())
                    assert result.returncode == 0, result.stdout + result.stderr
                    report["final_audit"] = api.call("/__issue7/audit"); report["diagnostics"] = api.call("/__issue7/diagnostics"); report["passed"] = True
                finally:
                    if process.poll() is None: process.terminate()
                    try: process.wait(timeout=30)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                    report["service_exited"] = process.poll() is not None
        report["workspace_removed"] = not Path(report["workspace"]).exists()
    finally:
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output / "verification.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve"); parser.add_argument("--port", type=int)
    parser.add_argument("--engine", choices=("chromium", "firefox"), default="chromium")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue7")
    args = parser.parse_args()
    if args.serve: serve(args.serve, args.port)
    else: check(args.output.absolute(), args.engine)
