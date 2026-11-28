"""I09 real-browser comparison checks with independent source-history oracles.

Only disposable managed simulations and a disposable loopback service are used.
The oracle reads committed states directly; it never calls production comparison
or metric sampling helpers to calculate expected populations or source cursors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from fractions import Fraction

from issue2_check import Api, until
from issue5_check import NODE_MODULES, ROOT


def nonzero_origin_fixture(workspace):
    """Static archived query fixture, distinct from the actual engine branch.

    Its first available observation is 2.5 s. Healthy agents have zero hunger
    growth and no actions, infections or pending biological deadlines, so the
    subsequent observation at 4.5 s preserves all population inputs. This is
    reader coverage for an imported partial history, not a simulated branch.
    """
    from zombie_sim.config import initialize_world, resolve_config
    from zombie_sim.storage import History, canonical
    identity = "issue9-origin-archive"
    directory = Path(workspace) / "runs" / identity
    directory.mkdir(parents=True)
    config = resolve_config({"scenario": "issue9_archived_nonzero_origin", "seed": 619, "horizon": 10,
                             "profiles": {"Human": {"hunger_rate": 0}},
                             "population": {"humans": 3, "zombies": 0, "infected": 0},
                             "execution": {"workers": 1}})
    state = initialize_world(config)
    state.update(time="5/2", revision=0, intents={}, occurrences={})
    history = History(directory / "run.sqlite", initial=state)
    try:
        history.append("9/2", delta=[["set", ["time"], "9/2"], ["set", ["revision"], 1]])
    finally:
        history.close()
    (directory / "manifest.json").write_text(canonical({"run_id": identity, "config": config, "status": "terminated"}))
    return {"run_id": identity, "kind": "static archived query fixture, not an engine branch",
            "origin": "5/2", "endpoint": "9/2", "population": 3}


def population_counts(state):
    counts = {"healthy": 0, "infected": 0, "zombies": 0, "dead": 0}
    for agent in state["agents"].values():
        # Durable states store life/type/episode; the human-readable status is
        # derived by presentation. Reconstruct the ontology's categories from
        # those authoritative fields without calling production population code.
        if agent["life"] == 0:
            bucket = "dead"
        elif agent["type"] == "Zombie":
            bucket = "zombies"
        elif agent.get("infection_episode"):
            assert agent["type"] == "Human"
            bucket = "infected"
        else:
            assert agent["type"] == "Human"
            bucket = "healthy"
        counts[bucket] += 1
    return dict(counts, total=len(state["agents"]))


def comparison_oracle(manager, data, request):
    sources = request["sources"]
    assert 2 <= len(sources) <= 4 and len({row["run_id"] for row in sources}) == len(sources)
    canonical = [dict(run_id=row["run_id"], time=str(Fraction(row["time"])), revision=str(int(row["revision"]))) for row in sources]
    assert data["sources"] == canonical
    assert data["sample_limit"] == 2000
    assert data["definition"] and data["version"]
    readers = {}
    try:
        origins = []; commits = {}
        for source in sources:
            identity = source["run_id"]
            history = readers[identity] = manager.history(identity)
            rows = history.connection.execute("SELECT revision,time_n,time_d FROM commits ORDER BY revision").fetchall()
            times = {revision: Fraction(int(numerator), int(denominator)) for revision, numerator, denominator in rows}
            cap = int(source["revision"])
            assert cap in times
            assert times[rows[0][0]] <= Fraction(source["time"]) <= times[cap]
            commits[identity] = times
            origins.append({"run_id": identity, "time": str(times[rows[0][0]])})
        assert data["origins"] == origins
        start = max(Fraction(row["time"]) for row in origins)
        end = min(Fraction(row["time"]) for row in sources)
        assert data["common_interval"] == {"start": str(start), "end": str(end)}
        if start > end:
            assert data["status"] == "no_overlap" and data["sample_times"] == [] and data["runs"] == []
            return {"passed": True, "status": "no_overlap", "common_interval": data["common_interval"], "origins": origins}
        assert data["status"] == "ready" and not data["errors"]
        spacing = Fraction(data["sample_interval"])
        assert spacing >= 1
        expected_times = []
        at = start
        while at < end:
            expected_times.append(str(at)); at += spacing
            assert len(expected_times) < 2000
        expected_times.append(str(end))
        assert data["sample_times"] == expected_times
        assert 1 <= len(expected_times) <= 2000
        assert [row["run_id"] for row in data["runs"]] == [row["run_id"] for row in sources]
        checked = []
        for source, row, origin in zip(sources, data["runs"], origins):
            identity = source["run_id"]; cap = int(source["revision"])
            history = readers[identity]
            assert row["origin"] == origin["time"]
            assert row["requested_cursor"] == {"time": str(Fraction(source["time"])), "revision": str(cap)}
            assert len(row["samples"]) == len(expected_times)
            expected_samples = []
            for at, sample in zip(expected_times, row["samples"]):
                source_revision = max(revision for revision, instant in commits[identity].items() if revision <= cap and instant <= Fraction(at))
                state = history.state_at(at, cap)
                assert int(state["revision"]) == source_revision
                expected = dict(time=at, revision=str(source_revision), **population_counts(state))
                assert {key: sample[key] for key in expected} == expected
                assert sample["seconds"] == float(Fraction(at))
                expected_samples.append(expected)
            assert row["cursor"] == {"time": str(end), "revision": expected_samples[-1]["revision"]}
            checked.append({"run_id": identity, "requested_cursor": row["requested_cursor"], "cursor": row["cursor"], "samples": expected_samples})
        return {"passed": True, "status": "ready", "common_interval": data["common_interval"],
                "sample_times": expected_times, "sample_interval": data["sample_interval"], "runs": checked}
    finally:
        for history in readers.values(): history.close()


def serve(workspace, port):
    import uvicorn
    from zombie_sim.server import create_app
    archived_fixture = nonzero_origin_fixture(workspace)
    app = create_app(workspace); manager = app.state.manager
    lock = threading.Lock(); requests = []; active = {}; maximum = {}
    class Trace:
        def __init__(self, app): self.app = app
        async def __call__(self, scope, receive, send):
            key = None
            if scope["type"] == "http" and scope["path"].startswith("/api/"):
                key = scope["path"]
                with lock:
                    requests.append({"method": scope["method"], "path": key, "at": time.monotonic()})
                    active[key] = active.get(key, 0) + 1; maximum[key] = max(maximum.get(key, 0), active[key])
            try: await self.app(scope, receive, send)
            finally:
                if key:
                    with lock: active[key] -= 1
    app.add_middleware(Trace)
    @app.get("/__issue9/diagnostics")
    def diagnostics():
        with lock: trace = list(requests); running = dict(active); peaks = dict(maximum)
        return {"pid": os.getpid(), "requests": trace, "active": running, "maximum": peaks, "runs": manager.list_runs(), "archived_query_fixture": archived_fixture}
    @app.get("/__issue9/audit")
    def audit():
        result = []
        for row in manager.list_runs():
            digest = hashlib.sha256(); sizes = {}; ledger = Path(row["directory"]) / "run.sqlite"
            if ledger.exists():
                with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as database:
                    for table in ("commits", "runtime_commits", "events", "participants", "control_commands", "metadata"):
                        count = 0; digest.update(table.encode())
                        for record in database.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                            count += 1
                            for value in record:
                                encoded = value if isinstance(value, bytes) else repr(value).encode()
                                digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
                        sizes[table] = count
            with manager.lock:
                commands = manager.catalog.command_count(row["id"])
            result.append({"id": row["id"], "status": row["status"], "generation": row["generation"], "frontier": row["frontier"],
                           "commands": commands, "history_and_runtime_digest": digest.hexdigest(), "rows": sizes})
        return sorted(result, key=lambda row: row["id"])
    @app.post("/__issue9/oracle")
    def oracle(body: dict): return comparison_oracle(manager, body["data"], body["request"])
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True); report = {"passed": False, "engine": engine}
    def interrupted(number, frame): raise RuntimeError(f"Verification interrupted by signal {number}")
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-issue9-") as workspace:
            with socket.socket() as listener: listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1", NODE_PATH=NODE_MODULES)
            with (output / "service.log").open("w") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace, "--port", str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                report.update(workspace=workspace, port=port, service_pid=process.pid); api = Api(port)
                try:
                    def ready():
                        if process.poll() is not None: raise AssertionError("Test service exited")
                        try: return api.call("/__issue9/diagnostics")
                        except OSError: return None
                    report["archived_query_fixture"] = until(ready)["archived_query_fixture"]
                    configs = {
                        "alpha": {"scenario": "issue9_alpha", "seed": 123, "horizon": 40, "population": {"humans": 16, "zombies": 4, "infected": 2}, "incubation_duration": 3},
                        "beta": {"scenario": "issue9_beta", "seed": 321, "horizon": 24, "population": {"humans": 8, "zombies": 2, "infected": 1}, "incubation_duration": 2},
                        "short": {"scenario": "issue9_short", "seed": 456, "horizon": 1, "population": {"humans": 6, "zombies": 2, "infected": 0}},
                        "spare": {"scenario": "issue9_spare", "seed": 789, "horizon": 30, "population": {"humans": 5, "zombies": 1, "infected": 0}},
                    }
                    runs = {"archive": report["archived_query_fixture"]["run_id"]}
                    for name, config in configs.items():
                        config.update(execution={"workers": 1}, checkpoint_interval=1000)
                        started = time.monotonic(); receipt = api.call("/api/runs", {"config": config, "command_id": str(uuid.uuid4()), "wait_for_initialization": False}); runs[name] = receipt["run_id"]
                        until(lambda: next(row for row in api.call("/api/runs") if row["id"] == runs[name])["status"] == "paused", timeout=120)
                        report.setdefault("initialization_seconds", {})[name] = time.monotonic() - started
                    report["initial_audit"] = api.call("/__issue9/audit")
                    with (output / "browser.log").open("w") as browser_log:
                        result = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue9.cjs"), api.base, str(output), json.dumps(runs), engine], cwd=ROOT, env=env, stdout=browser_log, stderr=subprocess.STDOUT, timeout=660)
                    report["browser"] = json.loads((output / "browser.json").read_text())
                    assert result.returncode == 0, (output / "browser.log").read_text()
                    report["final_audit"] = api.call("/__issue9/audit"); report["diagnostics"] = api.call("/__issue9/diagnostics"); report["passed"] = True
                finally:
                    if process.poll() is None:
                        try:
                            for row in api.call("/api/runs"):
                                if row["status"] not in {"terminated", "completed", "stopped", "failed"}: api.command(row["id"], "terminate")
                            report["cleanup_runs"] = until(lambda: (rows if all(row["resource_status"]["cleanup_complete"] for row in rows) else None) if (rows := api.call("/api/runs")) else True, timeout=60)
                        finally: process.terminate()
                    try: process.wait(timeout=30)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                    report["service_exited"] = process.poll() is not None
    finally:
        report["workspace_removed"] = not Path(report["workspace"]).exists() if "workspace" in report else True
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output / "verification.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve"); parser.add_argument("--port", type=int)
    parser.add_argument("--engine", choices=("chromium", "firefox"), default="chromium")
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue9")
    args = parser.parse_args()
    if args.serve: serve(args.serve, args.port)
    else: check(args.output.absolute(), args.engine)
