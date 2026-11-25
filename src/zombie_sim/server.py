"""Optional FastAPI transport; imports do not burden headless installations."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets
from urllib.parse import urlsplit

from .application import RunManager
from .storage import canonical
from .visualization import events_csv, sampled_metrics, world_svg, replay_animation


def create_app(experiments_dir="experiments", assets=None):
    try:
        from fastapi import FastAPI, Request, WebSocket, HTTPException, Body
        from fastapi.responses import FileResponse, JSONResponse, Response
        from fastapi.staticfiles import StaticFiles
    except ImportError as error:
        raise RuntimeError("Install the GUI extra: pip install 'zombie-sim[gui]'") from error
    # FastAPI resolves annotation names in module globals.
    globals().update(Request=Request, WebSocket=WebSocket)
    manager = RunManager(experiments_dir)
    session = secrets.token_urlsafe(32)

    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(manager.close)

    app = FastAPI(title="Zombie simulation research workspace", version="0.1.0", lifespan=lifespan)
    app.state.manager = manager
    app.state.session_token = session

    def local_origin(origin):
        if not origin:
            return True
        return urlsplit(origin).hostname in {"localhost", "127.0.0.1", "::1"}

    @app.middleware("http")
    async def protect(request: Request, call_next):
        if request.url.hostname not in {"localhost", "127.0.0.1", "::1", "testserver"}:
            return JSONResponse({"error": "The local workspace requires a loopback host"}, status_code=403)
        if not local_origin(request.headers.get("origin")):
            return JSONResponse({"error": "Cross-origin requests are disabled"}, status_code=403)
        if request.method not in {"GET", "HEAD", "OPTIONS"} and request.cookies.get("zombie_session") != session:
            return JSONResponse({"error": "Reload the workspace to establish a local session"}, status_code=403)
        response = await call_next(request)
        if request.method == "GET":
            response.set_cookie("zombie_session", session, httponly=True, samesite="strict")
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ValueError)
    async def invalid(request, error):
        return JSONResponse({"error": str(error)}, status_code=422)

    @app.exception_handler(KeyError)
    async def missing(request, error):
        return JSONResponse({"error": str(error)}, status_code=404)

    @app.get("/api/config")
    def configurations():
        from .config import DEFAULTS, baseline_config
        return {"presets": {"small": DEFAULTS, "baseline": baseline_config()},
                "fields": [{"path": "seed", "type": "integer", "min": 0, "label": "Random seed"},
                           {"path": "horizon", "type": "number", "min": 0.001, "unit": "seconds", "label": "Run horizon"},
                           {"path": "incubation_duration", "type": "number", "min": 0.001, "unit": "seconds", "label": "Incubation duration"},
                           {"path": "world.length", "type": "number", "min": 1, "unit": "metres", "label": "World length"},
                           {"path": "world.width", "type": "number", "min": 1, "unit": "metres", "label": "World width"},
                           {"path": "population.humans", "type": "integer", "min": 0, "label": "Humans"},
                           {"path": "population.zombies", "type": "integer", "min": 0, "label": "Zombies"},
                           {"path": "population.infected", "type": "integer", "min": 0, "label": "Initially infected humans"},
                           {"path": "execution.workers", "type": "integer", "min": 1, "label": "Workers"}],
                "schema_version": "zombie-sim/config-v1"}

    @app.post("/api/config/validate")
    def validate(body: dict = Body(...)):
        from .config import resolve_config
        return {"valid": True, "resolved": resolve_config(body)}

    @app.post("/api/config/preview")
    def preview(body: dict = Body(...)):
        from .config import resolve_config, initialize_world
        from .visualization import view_bundle
        resolved = resolve_config(body)
        return {"resolved": resolved, "view": view_bundle(initialize_world(resolved), mode="preview")}

    @app.get("/api/runs")
    def runs():
        return manager.list_runs()

    @app.post("/api/runs")
    def create(body: dict = Body(...)):
        return manager.create(body["config"], body.get("command_id"), start=body.get("start", False))

    @app.get("/api/runs/{run_id}/view")
    def view(run_id: str, time: str | None = None, revision: int | None = None, generation: int = 0):
        return manager.snapshot(run_id, time, revision, generation)

    @app.post("/api/runs/{run_id}/commands")
    def command(run_id: str, body: dict = Body(...)):
        return manager.command(run_id, body["operation"], body, wait=False)

    @app.get("/api/commands/{command_id}")
    def command_result(command_id: str):
        return manager.command_result(command_id)

    @app.post("/api/runs/{run_id}/branch")
    def branch(run_id: str, body: dict = Body(...)):
        return manager.branch(run_id, body)

    @app.get("/api/runs/{run_id}/events")
    def events(run_id: str, start: int = 0, end: int | None = None, kind: str | None = None,
               agent_id: str | None = None, limit: int = 1000, latest: bool = True):
        history = manager.history(run_id)
        try:
            return history.events(start, end, kind, agent_id, max(1, min(limit, 5000)), latest=latest)
        finally:
            history.close()

    @app.get("/api/runs/{run_id}/metrics")
    def metrics(run_id: str, end: str | None = None, interval: str = "1", revision: int | None = None):
        history = manager.history(run_id)
        try:
            frontier = history.revision if revision is None else revision
            result = sampled_metrics(history, end, interval, revision=frontier)
            result["event_counts"] = dict(history.connection.execute("SELECT kind,COUNT(*) FROM events WHERE revision<=? GROUP BY kind", (frontier,)))
            result["revision"] = str(frontier)
            return result
        finally:
            history.close()

    @app.get("/api/runs/{run_id}/cohorts")
    def cohorts(run_id: str, revision: int | None = None):
        return manager.cohorts(run_id, manager.snapshot(run_id, revision=revision)["state"])

    @app.post("/api/runs/{run_id}/cohorts")
    def save_cohort(run_id: str, body: dict = Body(...)):
        return manager.save_cohort(run_id, body)

    @app.get("/api/runs/{run_id}/observations/{agent_id}")
    def observation(run_id: str, agent_id: str, revision: int | None = None):
        history = manager.history(run_id)
        try:
            records = history.events(end=revision, agent_id=agent_id)
            decisions = [record for record in records if record.get("kind") == "decision" or record.get("observation") is not None]
            if not decisions:
                raise ValueError("No recorded decision observation at this cursor")
            selected = decisions[-1]
            if selected.get("observation") is None:
                raise ValueError("This decision records a reconstruction reference; direct observation capture was not enabled")
            return {"perspective": "recorded_observation", "decision": selected.get("id"),
                    "time": selected.get("time"), "revision": selected.get("ledger_revision"), "observation": selected["observation"]}
        finally:
            history.close()

    @app.get("/api/runs/{run_id}/export")
    def export(run_id: str, format: str = "json", time: str | None = None, revision: int | None = None, start: str = "0", end: str | None = None):
        view = manager.snapshot(run_id, time, revision)
        if format == "svg":
            return Response(world_svg(view["state"]), media_type="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{run_id}-{view["revision"]}.svg"'})
        if format == "csv":
            history = manager.history(run_id)
            try:
                return Response(events_csv(history.events(end=revision)), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{run_id}-events.csv"'})
            finally:
                history.close()
        if format == "animation":
            history = manager.history(run_id)
            try:
                return Response(replay_animation(history, start, end or time, run_id=run_id), media_type="text/html", headers={"Content-Disposition": f'attachment; filename="{run_id}-replay.html"'})
            finally:
                history.close()
        if format == "parquet":
            try:
                import pyarrow as pa
                import pyarrow.parquet as pq
            except ImportError as error:
                raise ValueError("Parquet exports require the analysis extra (pyarrow)") from error
            history = manager.history(run_id)
            try:
                records = history.events(end=revision)
                table = pa.Table.from_pylist([{"revision": str(r.get("ledger_revision")), "sequence": str(r.get("ledger_sequence")), "time": str(r.get("time", "0")), "kind": str(r.get("kind", "event")), "payload_json": canonical(r)} for r in records])
                buffer = pa.BufferOutputStream()
                pq.write_table(table, buffer, compression="zstd")
                return Response(buffer.getvalue().to_pybytes(), media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{run_id}-events.parquet"'})
            finally:
                history.close()
        if format != "json":
            raise ValueError("HTTP view exports support json, csv, svg, parquet and animation")
        return Response(canonical(view), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{run_id}-{view["revision"]}.json"'})

    @app.websocket("/api/runs/{run_id}/stream")
    async def stream(websocket: WebSocket, run_id: str):
        if not local_origin(websocket.headers.get("origin")) or websocket.cookies.get("zombie_session") != session:
            await websocket.close(code=1008); return
        await websocket.accept()
        sequence = -1
        try:
            while True:
                bundle = await asyncio.to_thread(manager.snapshot, run_id)
                if int(bundle["sequence"]) != sequence:
                    await websocket.send_json(bundle)
                    # Exactly one outstanding complete snapshot. Slow subscribers
                    # consume no growing buffer and resynchronize on reconnect.
                    reply = await asyncio.wait_for(websocket.receive_json(), timeout=10)
                    if str(reply.get("ack")) != bundle["sequence"]:
                        sequence = -1
                    else:
                        sequence = int(bundle["sequence"])
                await asyncio.sleep(0.1)
        except Exception:
            try:
                await websocket.close()
            except RuntimeError:
                pass

    assets = Path(assets) if assets else Path(__file__).parent / "static"
    if not assets.exists():
        assets = Path(__file__).resolve().parents[2] / "gui" / "dist"
    if (assets / "assets").exists():
        app.mount("/assets", StaticFiles(directory=assets / "assets"), name="assets")

    @app.get("/")
    def index():
        if not (assets / "index.html").exists():
            raise HTTPException(503, "GUI assets are not built. Run pnpm install --frozen-lockfile and pnpm run build in gui/.")
        return FileResponse(assets / "index.html")

    return app


def serve(experiments_dir="experiments", host="127.0.0.1", port=8765):
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError("Install the GUI extra: pip install 'zombie-sim[gui]'") from error
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("This release supports loopback hosting only")
    uvicorn.run(create_app(experiments_dir), host=host, port=port)
