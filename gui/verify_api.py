"""Independent local HTTP workflow check; never imports a supplied test suite."""
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
jar = http.cookiejar.CookieJar()
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def request(path, data=None, raw=False):
    request = urllib.request.Request(BASE + path, data=json.dumps(data).encode() if data is not None else None,
                                     headers={"Content-Type": "application/json"})
    try:
        with client.open(request, timeout=60) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        raise AssertionError(f"{path}: {error.code}: {error.read().decode()}") from error
    return body if raw else json.loads(body)


def wait_run(run_id, status="paused"):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        run = next(row for row in request("/api/runs") if row["id"] == run_id)
        if run["status"] == status:
            return run
        if run["status"] in {"failed", "interrupted"}:
            raise AssertionError(run)
        time.sleep(.05)
    raise AssertionError(f"Run {run_id} did not reach {status}")


def command(run_id, operation, **fields):
    row = next(row for row in request("/api/runs") if row["id"] == run_id)
    result = request(f"/api/runs/{run_id}/commands", {"operation": operation,
                      "command_id": str(uuid.uuid4()), "generation": row["generation"], **fields})
    deadline = time.monotonic() + 30
    while result["status"] == "pending" and time.monotonic() < deadline:
        time.sleep(.05)
        result = request("/api/commands/" + result["command_id"])
    assert result["status"] == "applied", result
    return result


def main():
    assert b"/assets/" in request("/", raw=True)
    metadata = request("/api/config")
    config = metadata["presets"]["small"]
    config.update(horizon=10, incubation_duration=5, seed=42, interventions_enabled=True)
    config["population"].update(humans=2, zombies=1, infected=1)
    assert request("/api/config/validate", config)["valid"]
    assert request("/api/config/preview", config)["view"]["metrics"]["populations"]["total"] == 3
    create = {"command_id": str(uuid.uuid4()), "config": config, "start": False}
    first = request("/api/runs", create)
    assert request("/api/runs", create)["run_id"] == first["run_id"]
    run_id = first["run_id"]
    wait_run(run_id)
    initial = request(f"/api/runs/{run_id}/view")
    assert initial["state"]["run_id"] == run_id
    assert initial["metrics"]["populations"] == {"healthy": 1, "infected": 1, "zombies": 1, "dead": 0, "total": 3}
    stepped = command(run_id, "step")
    assert int(stepped["revision"]) > 0
    command(run_id, "checkpoint")
    request(f"/api/runs/{run_id}/cohorts", {"name": "Initially infected", "mode": "fixed", "predicate": {"status": "INFECTED"}, "reference_revision": "0"})
    command(run_id, "intervene", time=stepped["time"], change={"kind": "add_resource", "resource": "FOOD", "quantity": 3, "x": 5, "y": 5})
    command(run_id, "advance", time="3")
    live = request(f"/api/runs/{run_id}/view")
    assert live["time"] == "3", live["time"]
    original = request(f"/api/runs/{run_id}/view?time=0&revision=0")
    assert original["revision"] == "0"
    metrics = request(f"/api/runs/{run_id}/metrics?end=3&revision={live['revision']}")
    assert len(metrics["samples"]) == 4
    assert all(row["total"] == 3 for row in metrics["samples"])
    assert request(f"/api/runs/{run_id}/cohorts")[0]["denominator"] == 1
    exports = {}
    for format in ("json", "csv", "svg", "parquet", "animation"):
        payload = request(f"/api/runs/{run_id}/export?format={format}&revision={live['revision']}&end=3", raw=True)
        assert len(payload) > 20, format
        exports[format] = len(payload)
    row = wait_run(run_id)
    branch_request = {"command_id": str(uuid.uuid4()), "revision": live["revision"], "generation": row["generation"], "seed": 43}
    child = request(f"/api/runs/{run_id}/branch", branch_request)
    assert request(f"/api/runs/{run_id}/branch", branch_request)["run_id"] == child["run_id"]
    wait_run(child["run_id"])
    child_view = request(f"/api/runs/{child['run_id']}/view")
    assert child_view["state"]["run_id"] == child["run_id"]
    assert child_view["time"] == "3"
    assert request(f"/api/runs/{run_id}/view")["revision"] == live["revision"]
    historical = request(f"/api/runs/{run_id}/branch", {"command_id": str(uuid.uuid4()), "revision": "0", "generation": row["generation"], "seed": 44})["run_id"]
    wait_run(historical)
    assert request(f"/api/runs/{historical}/view")["time"] == "0"
    command(historical, "stop")
    command(child["run_id"], "advance", time="6")
    child_cohort = request(f"/api/runs/{child['run_id']}/view")
    assert child_cohort["metrics"]["populations"]["zombies"] == 2
    command(child["run_id"], "stop")
    command(run_id, "stop")
    config.update(horizon=4)
    live_run = request("/api/runs", {"command_id": str(uuid.uuid4()), "config": config, "start": True})["run_id"]
    wait_run(live_run, "running")
    command(live_run, "pause")
    wait_run(live_run, "paused")
    command(live_run, "pace", pacing=0)
    command(live_run, "continue")
    wait_run(live_run, "completed")
    assert request(f"/api/runs/{live_run}/view")["time"] == "4"
    print(json.dumps({"status": "passed", "run_id": run_id, "child_run_id": child["run_id"],
                      "live_run_id": live_run, "live_horizon": "4", "parent_revision": live["revision"], "child_time": child_cohort["time"], "export_bytes": exports}, indent=2))


if __name__ == "__main__":
    main()
