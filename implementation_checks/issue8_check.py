"""I08 real-browser workflows checked against direct ledger queries.

All runs and the HTTP service live in a disposable workspace. The event oracle
does not call the production timeline or its paging/filtering helpers.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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


def ledger_records(history, revision):
    from zombie_sim.storage import _unpack
    return [dict(_unpack(payload), ledger_sequence=str(sequence), ledger_revision=str(at))
            for sequence, at, payload in history.connection.execute(
                "SELECT sequence,revision,payload FROM events WHERE revision<=? ORDER BY sequence", (int(revision),))]


def direct_ids(record):
    result = {str(record[key]) for key in ("actor", "target", "agent", "agent_id", "target_id")
              if record.get(key) is not None}
    result.update(str(identity) for identity in record.get("targets", []))
    return result


def occurrence_id(record):
    return record.get("occurrence", record.get("action_id"))


def matches(record, identity, occurrences):
    if identity is None:
        return True
    occurrence = occurrences.get(occurrence_id(record), {})
    return str(identity) in direct_ids(record) or str(identity) in {
        str(occurrence.get("actor")), str(occurrence.get("target"))}


def event_oracle(manager, run_id, data, request):
    from zombie_sim.storage import exact_time
    history = manager.history(run_id)
    try:
        cursor = data["cursor"]
        state = history.state_at(cursor["time"], int(cursor["revision"]))
        assert str(state["revision"]) == str(cursor["revision"])
        assert exact_time(state["time"]) <= exact_time(cursor["time"])
        occurrences = state.get("occurrences", {})
        rows = ledger_records(history, cursor["revision"])
        identity = request.get("agent")
        selected = [row for row in rows if matches(row, identity, occurrences)]
        before, after = request.get("before_sequence"), request.get("after_sequence")
        window = [row for row in selected if (before is None or int(row["ledger_sequence"]) < int(before))
                  and (after is None or int(row["ledger_sequence"]) > int(after))]
        limit = request.get("limit", 500)
        expected = window[:limit] if after is not None else window[-limit:]
        expected = [dict(row, type=str(row.get("kind", "event")).upper(),
                         revision_before=str(max(0, int(row["ledger_revision"]) - 1)),
                         revision_after=row["ledger_revision"]) for row in expected]
        assert data["run_id"] == run_id and data["agent"] == identity
        assert data["records"] == expected, "Page content/order differs from independent full-ledger selection"
        refs = {occurrence_id(row) for row in expected} & occurrences.keys()
        assert data["occurrences"] == {key: occurrences[key] for key in refs}, "Occurrence payload is incomplete or includes unrelated history"
        page = data["page"]
        assert page["limit"] == limit and page["loaded_count"] == len(expected)
        assert page["first_sequence"] == (expected[0]["ledger_sequence"] if expected else None)
        assert page["last_sequence"] == (expected[-1]["ledger_sequence"] if expected else None)
        if expected:
            assert page["has_older"] == any(int(row["ledger_sequence"]) < int(expected[0]["ledger_sequence"]) for row in selected)
            assert page["has_newer"] == any(int(row["ledger_sequence"]) > int(expected[-1]["ledger_sequence"]) for row in selected)
        else:
            assert not selected or before is not None or after is not None
        return {"passed": True, "cursor": cursor, "agent": identity,
                "total_records_at_cursor": len(rows), "matching_records_at_cursor": len(selected),
                "sequences": [row["ledger_sequence"] for row in expected],
                "occurrences_returned": len(refs), "occurrences_in_history": len(occurrences),
                "payload_bytes": len(json.dumps(data).encode()),
                "target_records": sum(str(row.get("target", row.get("target_id"))) == identity for row in expected) if identity else 0,
                "actor_records": sum(str(row.get("actor", row.get("agent_id", row.get("agent")))) == identity for row in expected) if identity else 0,
                "occurrence_only_records": sum(identity not in direct_ids(row) for row in expected) if identity else 0,
                "old_earliest_window_last_sequence": rows[min(5000, len(rows)) - 1]["ledger_sequence"] if rows else None}
    finally:
        history.close()


def candidates(manager, run_id):
    history = manager.history(run_id)
    try:
        state = history.state_at(); occurrences = state.get("occurrences", {})
        rows = ledger_records(history, state["revision"])
        candidates = []; late = []
        for identity in state["agents"]:
            eligible = [row for row in rows if matches(row, identity, occurrences)][-500:]
            target = [row for row in eligible if str(row.get("target", row.get("target_id"))) == identity]
            linked = [row for row in eligible if identity not in direct_ids(row)]
            if eligible and int(eligible[-1]["ledger_sequence"]) > 5000:
                late.append({"identity": identity, "last_sequence": eligible[-1]["ledger_sequence"],
                             "matching_records": len(eligible)})
            if target and linked:
                candidates.append({"identity": identity, "target_sequence": target[-1]["ledger_sequence"],
                                   "linked_sequence": linked[-1]["ledger_sequence"], "matching_records": len(eligible)})
        candidates.sort(key=lambda row: min(int(row["target_sequence"]), int(row["linked_sequence"])), reverse=True)
        late.sort(key=lambda row: int(row["last_sequence"]), reverse=True)
        return {"candidates": candidates, "late": late,
                "living": [identity for identity, agent in state["agents"].items() if agent["life"] > 0],
                "identities": list(state["agents"]), "event_count": len(rows)}
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
    @app.get("/__issue8/diagnostics")
    def diagnostics():
        with lock: trace = list(requests); running = dict(active); peaks = dict(maximum)
        return {"pid": os.getpid(), "requests": trace, "active": running, "maximum": peaks, "runs": manager.list_runs()}
    @app.get("/__issue8/audit")
    def audit():
        result = []
        for row in manager.list_runs():
            digest = hashlib.sha256(); sizes = {}; ledger = Path(row["directory"]) / "run.sqlite"
            if ledger.exists():
                with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as db:
                    for table in ("commits", "runtime_commits", "events", "participants", "control_commands", "metadata"):
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
    @app.post("/__issue8/oracle")
    def oracle(body: dict): return event_oracle(manager, body["run_id"], body["data"], body["request"])
    @app.get("/__issue8/candidates/{run_id}")
    def participants(run_id: str): return candidates(manager, run_id)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True); report = {"passed": False, "engine": engine}
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-issue8-") as workspace:
            with socket.socket() as listener: listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", NODE_PATH=NODE_MODULES)
            with (output / "service.log").open("w") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace, "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                report.update(workspace=workspace, port=port, service_pid=process.pid); api = Api(port)
                try:
                    def ready():
                        if process.poll() is not None: raise AssertionError("Test service exited")
                        try: return api.call("/__issue8/diagnostics")
                        except OSError: return None
                    until(ready)
                    from zombie_sim.config import baseline_config
                    configs = {"small": {"scenario": "issue8_small", "seed": 123, "horizon": 230, "execution": {"workers": 1}, "checkpoint_interval": 1000}, "baseline": baseline_config()}
                    configs["baseline"].update(horizon=3, checkpoint_interval=1000); configs["baseline"]["execution"] = {"workers": 1}
                    runs = {}
                    for name, config in configs.items():
                        started = time.monotonic(); receipt = api.call("/api/runs", {"config": config, "command_id": str(uuid.uuid4()), "wait_for_initialization": False}); runs[name] = receipt["run_id"]
                        until(lambda: next(row for row in api.call("/api/runs") if row["id"] == runs[name])["status"] == "paused", timeout=240)
                        report.setdefault("initialization_seconds", {})[name] = time.monotonic() - started
                    report["initial_audit"] = api.call("/__issue8/audit")
                    result = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue8.cjs"), api.base, str(output), json.dumps(runs), engine], cwd=ROOT, env=env, text=True, capture_output=True, timeout=480)
                    (output / "browser.log").write_text(result.stdout + result.stderr)
                    report["browser"] = json.loads((output / "browser.json").read_text())
                    assert result.returncode == 0, result.stdout + result.stderr
                    report["final_audit"] = api.call("/__issue8/audit"); report["diagnostics"] = api.call("/__issue8/diagnostics"); report["passed"] = True
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
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue8")
    args = parser.parse_args()
    if args.serve: serve(args.serve, args.port)
    else: check(args.output.absolute(), args.engine)
