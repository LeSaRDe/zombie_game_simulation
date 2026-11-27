"""I05 role-percentage configuration workflows against a disposable real local service.

Role-percentage editing is exercised in the browser, while validation, preview,
creation and copied-run workflows use the production API and engine.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from fractions import Fraction
import hashlib
from http.cookiejar import CookieJar
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
import tomllib
from urllib.request import HTTPCookieProcessor, Request, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]
NODE_MODULES = "/home/fmeng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
ORDER = {"Human": ["unassigned", "DOCTOR", "WARRIOR", "SCOUT", "ENGINEER"],
         "Zombie": ["unassigned", "TYRANT", "RUNNER", "SPITTER", "SCREAMER"]}


def allocation_oracle(config):
    """Independent Fraction arithmetic checks actual browser-exported inputs."""
    metadata = config.get("gui", {}).get("role_allocation")
    if metadata is None:
        return False
    for kind, order in ORDER.items():
        population, role_map = ("humans", "human_roles") if kind == "Human" else ("zombies", "zombie_roles")
        group = metadata[kind]
        assert group["tie_order"] == order
        shares = [Fraction(int(group["targets"][role]["numerator"]), int(group["targets"][role]["denominator"])) for role in order]
        assert sum(shares) == 1
        total = config["population"][population]
        quotas = [total * share for share in shares]
        counts = [quota.numerator // quota.denominator for quota in quotas]
        for index in sorted(range(5), key=lambda index: (-(quotas[index] - counts[index]), index))[:total-sum(counts)]:
            counts[index] += 1
        actual = config["population"][role_map]
        assert counts == [total-sum(actual.values())] + [actual.get(role, 0) for role in order[1:]]
    return True


def backend_checks(config):
    from zombie_sim.config import resolve_config, initialize_world
    from zombie_sim.config_io import dumps, loads
    valid = resolve_config(config)
    assert allocation_oracle(valid)
    without = deepcopy(config); without.pop("gui", None)
    assert resolve_config(without)["fingerprint"] == valid["fingerprint"], "Editor metadata changed modeled identity"
    for format in ("json", "toml"):
        roundtrip = resolve_config(loads(dumps(config, format), format))
        assert roundtrip["population"] == valid["population"]
        assert roundtrip["gui"]["role_allocation"] == valid["gui"]["role_allocation"]
        assert roundtrip["fingerprint"] == valid["fingerprint"]
    mutations = []
    def bad(label, change):
        value = deepcopy(config); change(value); mutations.append((label, value))
    allocation = lambda c: c["gui"]["role_allocation"]
    human = lambda c: allocation(c)["Human"]
    target = lambda c: human(c)["targets"]["DOCTOR"]
    bad("count mismatch", lambda c: c["population"]["human_roles"].update(DOCTOR=2))
    bad("incompatible role", lambda c: c["population"]["human_roles"].update(TYRANT=1))
    bad("negative count", lambda c: c["population"]["human_roles"].update(DOCTOR=-1))
    bad("fractional count", lambda c: c["population"]["human_roles"].update(DOCTOR=1.5))
    bad("boolean count", lambda c: c["population"]["human_roles"].update(DOCTOR=True))
    bad("zero denominator", lambda c: target(c).update(denominator="0"))
    bad("negative numerator", lambda c: target(c).update(numerator="-1"))
    bad("noncanonical integer text", lambda c: target(c).update(numerator="01"))
    bad("number instead of exact string", lambda c: target(c).update(numerator=1))
    bad("nonfinite target string", lambda c: target(c).update(numerator="NaN"))
    bad("target over one", lambda c: target(c).update(numerator="11", denominator="10"))
    bad("unreduced fraction", lambda c: target(c).update(numerator="2", denominator="20"))
    bad("shares do not sum to one", lambda c: target(c).update(numerator="1", denominator="5"))
    bad("missing category", lambda c: human(c)["targets"].pop("SCOUT"))
    bad("unknown category", lambda c: human(c)["targets"].update(NONE={"numerator":"0", "denominator":"1"}))
    bad("missing biological type", lambda c: allocation(c).pop("Zombie"))
    bad("wrong tie order", lambda c: human(c)["tie_order"].reverse())
    bad("unsupported method", lambda c: allocation(c).update(method="random"))
    bad("unsupported version", lambda c: allocation(c).update(schema_version=2))
    bad("boolean version", lambda c: allocation(c).update(schema_version=True))
    bad("metadata is not an object", lambda c: c["gui"].update(role_allocation=[]))
    checks = []
    for label, value in mutations:
        operations = {
            "resolve": lambda: resolve_config(value),
            "JSON import": lambda: loads(json.dumps(value), "json"),
            "JSON export": lambda: dumps(value, "json"),
            "TOML import": lambda: loads(raw_toml(value), "toml"),
            "TOML export": lambda: dumps(value, "toml"),
        }
        for entrypoint, operation in operations.items():
            try:
                operation()
            except (ValueError, TypeError) as error:
                checks.append({"case": label, "entrypoint": entrypoint, "error": str(error)})
            else:
                raise AssertionError(f"{entrypoint} accepted {label}")
    counts = []
    for seed in (401, 402):
        seeded = deepcopy(config); seeded["seed"] = seed
        state = initialize_world(resolve_config(seeded))
        observation = {kind: {role: sum(agent["type"] == kind and agent.get("role") == role for agent in state["agents"].values()) for role in order[1:]} for kind, order in ORDER.items()}
        counts.append(observation)
    assert counts[0] == counts[1], "Role count allocation changed with seed"
    return {"metadata_excluded_from_fingerprint": True, "json_toml_roundtrip": True,
            "rejection_checks": checks, "initialization_role_counts_by_seed": counts}


def raw_toml(config):
    """Serialize malformed test values without production validation."""
    def value(item):
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, (int, float, str)):
            return json.dumps(item, ensure_ascii=False, allow_nan=False)
        if isinstance(item, list):
            return "[" + ", ".join(value(child) for child in item) + "]"
        if isinstance(item, dict):
            return "{ " + ", ".join(json.dumps(str(key)) + " = " + value(child) for key, child in item.items() if child is not None) + " }"
        raise TypeError(type(item).__name__)
    return "\n".join(json.dumps(key) + " = " + value(item) for key, item in config.items() if item is not None) + "\n"


def until(function, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = function()
        if result:
            return result
        time.sleep(.05)
    raise AssertionError("Timed out waiting for disposable I05 fixture")


def serve(workspace, port):
    import uvicorn
    from zombie_sim.server import create_app
    app = create_app(workspace)
    manager = app.state.manager
    lock = threading.Lock()
    requests = []

    class TraceRequests:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope["type"] == "http" and scope["path"].startswith("/api/"):
                with lock:
                    requests.append({"method": scope["method"], "path": scope["path"]})
            await self.app(scope, receive, send)

    app.add_middleware(TraceRequests)

    @app.get("/__issue5/diagnostics")
    def diagnostics():
        with lock:
            trace = list(requests)
        return {"pid": os.getpid(), "requests": trace, "runs": manager.list_runs()}

    @app.get("/__issue5/audit")
    def audit():
        result = []
        for row in manager.list_runs():
            digest = hashlib.sha256()
            ledger = Path(row["directory"]) / "run.sqlite"
            if ledger.exists():
                with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True) as database:
                    for table in ("commits", "runtime_commits", "events"):
                        digest.update(table.encode())
                        for record in database.execute(f"SELECT * FROM {table} ORDER BY rowid"):
                            for value in record:
                                encoded = value if isinstance(value, bytes) else repr(value).encode()
                                digest.update(len(encoded).to_bytes(8, "big")); digest.update(encoded)
            with manager.lock:
                commands = manager.connection.execute("SELECT COUNT(*) FROM commands WHERE run_id=?", (row["id"],)).fetchone()[0]
            result.append({"id": row["id"], "status": row["status"], "generation": row["generation"],
                           "frontier": row["frontier"], "commands": commands, "history_digest": digest.hexdigest()})
        return result

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


class Api:
    def __init__(self, port):
        self.base = f"http://127.0.0.1:{port}"
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def call(self, path, body=None):
        request = Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                          headers={"Content-Type": "application/json"})
        with self.opener.open(request, timeout=60) as response:
            return json.load(response)


def check(output, engine="chromium"):
    output.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "engine": engine}
    try:
        with tempfile.TemporaryDirectory(prefix="zombie-issue5-") as workspace:
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), NODE_PATH=NODE_MODULES,
                       PYTHONDONTWRITEBYTECODE="1")
            with (output / "service.log").open("w") as log:
                process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve", workspace, "--port", str(port)],
                                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                api = Api(port)
                report.update(workspace=workspace, port=port, service_pid=process.pid)
                try:
                    def ready():
                        if process.poll() is not None:
                            raise AssertionError("Fixture service exited; inspect service.log")
                        try:
                            return api.call("/__issue5/diagnostics")
                        except OSError:
                            return None
                    until(ready)
                    config = {"scenario": "issue5_source_copy", "seed": 123, "horizon": 33, "incubation_duration": 17,
                              "world": {"length": 90, "width": 80},
                              "population": {"humans": 16, "zombies": 4, "human_roles": {"DOCTOR": 3, "WARRIOR": 2, "SCOUT": 1, "ENGINEER": 1}, "zombie_roles": {"TYRANT": 1, "RUNNER": 1}}, "execution": {"workers": 1},
                              "checkpoint_interval": 1000}
                    source = api.call("/api/runs", {"config": config, "command_id": str(uuid.uuid4())})["run_id"]
                    until(lambda: next(row for row in api.call("/api/runs") if row["id"] == source)["status"] == "paused")
                    report["source_before"] = next(row for row in api.call("/__issue5/audit") if row["id"] == source)
                    result = subprocess.run([str(ROOT / ".runtimeenv/bin/node"), str(ROOT / "gui/verify_issue5.cjs"),
                                             api.base, str(output), source, engine], cwd=ROOT, env=env,
                                            text=True, capture_output=True, timeout=360)
                    (output / "browser.log").write_text(result.stdout + result.stderr)
                    report["browser"] = json.loads((output / "browser.json").read_text())
                    assert result.returncode == 0, result.stdout + result.stderr
                    report["fraction_oracle_observations"] = sum(allocation_oracle(case["config"]) for case in report["browser"]["allocation_cases"])
                    report["backend"] = backend_checks(report["browser"]["payload"])
                    report["cli_parity"] = []
                    for format in ("json", "toml"):
                        exported = output / f"role-draft-export.{format}"
                        cli = subprocess.run([sys.executable, "-m", "zombie_sim.cli", "validate", str(exported)],
                                             cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
                        (output / f"cli-{format}.json").write_text(cli.stdout)
                        assert cli.returncode == 0, cli.stderr
                        resolved = json.loads(cli.stdout)["resolved"]
                        expected = report["browser"]["preview"]["resolved"]
                        for key in ("population", "gui", "fingerprint"):
                            assert resolved[key] == expected[key], f"CLI {format} disagreed on {key}"
                        report["cli_parity"].append({"format": format, "population": resolved["population"], "fingerprint": resolved["fingerprint"]})
                    report["source_after"] = next(row for row in api.call("/__issue5/audit") if row["id"] == source)
                    assert report["source_before"] == report["source_after"], "Configuration workflows changed the copied source run"
                    report["diagnostics"] = api.call("/__issue5/diagnostics")
                    report["passed"] = True
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            process.kill(); process.wait(timeout=5)
                    report["service_exited"] = process.poll() is not None
        report["workspace_removed"] = not Path(report["workspace"]).exists()
    finally:
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed": report["passed"], "report": str(output / "verification.json")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve")
    parser.add_argument("--port", type=int)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts/issue5")
    parser.add_argument("--engine", choices=("chromium", "firefox"), default="chromium")
    args = parser.parse_args()
    if args.serve:
        serve(args.serve, args.port)
    else:
        check(args.output.absolute(), args.engine)
