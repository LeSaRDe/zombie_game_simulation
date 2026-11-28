"""Optional FastAPI transport; imports do not burden headless installations."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import secrets
import threading
from urllib.parse import urlsplit

from .application import RunManager, RunInitializing, ViewCancelled, TERMINAL_STATES
from .storage import canonical
from .visualization import events_csv, sampled_metrics, world_svg, replay_animation

LOGGER = logging.getLogger("zombie_sim.server")


class HTTPReadController:
    """Bind a browser request's disconnect lifetime to a cancellable reader."""
    def __init__(self, readers):
        self.readers = readers

    async def read(self, request, operation, *args, **kwargs):
        from fastapi.responses import Response
        cancelled = threading.Event()
        work = asyncio.create_task(asyncio.to_thread(self.readers.call, operation, *args, cancel_event=cancelled, **kwargs))
        async def watch_disconnect():
            while True:
                if (await request.receive())["type"] == "http.disconnect":
                    cancelled.set(); return
        disconnected = asyncio.create_task(watch_disconnect())
        try:return await asyncio.shield(work)
        except ViewCancelled:return Response(status_code=499)
        except asyncio.CancelledError:
            cancelled.set()
            work.add_done_callback(lambda task: None if task.cancelled() else task.exception())
            raise
        finally:
            cancelled.set();disconnected.cancel()
            await asyncio.gather(disconnected,return_exceptions=True)


class ConfigurationHTTPController:
    """Configuration exchange and metadata backed by the workspace service."""
    def __init__(self, configuration, readers):
        self.configuration = configuration
        self.readers = readers

    def metadata(self):
        from .model_catalog import model_catalog
        return {"presets": {"small": self.configuration.defaults, "baseline": self.configuration.baseline_config()},
                "fields": [{"path": "seed", "type": "integer", "min": 0, "label": "Random seed"},
                           {"path": "horizon", "type": "number", "min": 0.001, "unit": "seconds", "label": "Run horizon"},
                           {"path": "incubation_duration", "type": "number", "min": 0.001, "unit": "seconds", "label": "Incubation duration"},
                           {"path": "world.length", "type": "number", "min": 1, "unit": "metres", "label": "World length"},
                           {"path": "world.width", "type": "number", "min": 1, "unit": "metres", "label": "World width"},
                           {"path": "population.humans", "type": "integer", "min": 0, "label": "Humans"},
                           {"path": "population.zombies", "type": "integer", "min": 0, "label": "Zombies"},
                           {"path": "population.infected", "type": "integer", "min": 0, "label": "Initially infected humans"},
                           {"path": "human_model", "type": "text", "label": "Human decision model"},
                           {"path": "zombie_model", "type": "text", "label": "Zombie decision model"},
                           {"path": "execution.workers", "type": "integer", "min": 1, "label": "Workers"}],
                "models": model_catalog(),
                "schema_version": "zombie-sim/config-v1"}


    def validate(self, body):
        return {"valid": True, "resolved": self.configuration.resolve(body)}


    def preview(self, body):
        return self.readers.call("preview",body)


    def import_config(self, body):
        return {"config": self.configuration.loads(body["text"], body.get("format", "json"))}


    def export_config(self, body):
        return {"text": self.configuration.dumps(body["config"], body.get("format", "json"))}


class RunHTTPController:
    """Transport-level run commands and their durable acknowledgement policy."""
    def __init__(self, manager, receipts=None):
        from .command_recovery import CommandReceiptService
        self.manager = manager
        self.receipts = receipts if receipts is not None else CommandReceiptService()

    def create(self, body):
        from fastapi.responses import JSONResponse
        wait_for_initialization = body.get("wait_for_initialization", True)
        if not isinstance(wait_for_initialization, bool):
            raise ValueError("wait_for_initialization must be a boolean")
        receipt = self.manager.create(body["config"], body.get("command_id"), start=body.get("start", False))
        if wait_for_initialization:
            return self.receipts.reply(self.manager, receipt)
        # The GUI can show genuine initialization immediately after identity
        # reservation. This transport acknowledgement neither finalizes nor
        # rewrites the durable creation receipt's initial time/revision.
        run = self.manager._row(receipt["run_id"])
        return JSONResponse({"status": "accepted", "command_id": receipt["command_id"],
                             "run_id": receipt["run_id"], "generation": run["generation"],
                             "run_status": run["status"]}, status_code=202)


    def command(self, run_id, body):
        return self.receipts.reply(self.manager,self.manager.command(run_id, body["operation"], body, wait=False))


    def command_result(self, command_id):
        return self.receipts.reply(self.manager,self.manager.command_result(command_id))


    def branch(self, run_id, body):
        return self.receipts.reply(self.manager,self.manager.branch(run_id, body))


class LiveViewSession:
    """One acknowledged snapshot in flight, with a per-subscriber cancellation token."""
    def __init__(self, manager, readers, shutdown, session, origin_policy):
        self.manager = manager
        self.readers = readers
        self.shutdown = shutdown
        self.session = session
        self.origin_policy = origin_policy
        self.cancel_event = threading.Event()
        self.acknowledged_head = None

    async def run(self, websocket, run_id):
        if not self.origin_policy(websocket.headers.get("origin")) or websocket.cookies.get("zombie_session") != self.session:
            await websocket.close(code=1008); return
        if self.shutdown.draining:
            await websocket.close(code=1001); return
        await websocket.accept()
        self.shutdown.sockets.add(websocket)
        try:
            while not self.shutdown.draining:
                # Revision and control checks do not reconstruct the world. A
                # paused reader must not replay a large ledger on every poll.
                head = await asyncio.to_thread(self.manager.read_head, run_id)
                head_key = canonical(head)
                if head_key != self.acknowledged_head:
                    bundle = await asyncio.to_thread(self.readers.call, "snapshot", run_id, cancel_event=self.cancel_event)
                    control = bundle.get("control", {})
                    if control.get("status") in TERMINAL_STATES:
                        # Termination may overtake a slow reconstruction. Its
                        # fresh control receipt must not label an older scene
                        # as the final boundary and close the stream early.
                        final_head = await asyncio.to_thread(self.manager.read_head, run_id)
                        if (str(final_head["revision"]) != bundle["committed_frontier"]
                                or final_head["status"] != control["status"]
                                or int(final_head["generation"]) != int(control["generation"])):
                            continue
                        head_key = canonical(final_head)
                    await websocket.send_json(bundle)
                    # Exactly one outstanding complete snapshot. Slow subscribers
                    # consume no growing buffer and resynchronize on reconnect.
                    reply = await asyncio.wait_for(websocket.receive_json(), timeout=10)
                    if str(reply.get("ack")) == bundle["sequence"]:
                        self.acknowledged_head = head_key
                        if control.get("status") in TERMINAL_STATES:
                            # The retained scene remains available through view
                            # queries. Cleanup progress is lightweight /runs
                            # metadata, not a reason to keep replaying history.
                            await websocket.close(code=1000)
                            return
                else:
                    # Observe disconnects even when a paused run has no new
                    # revision, so an idle viewer does not pin server shutdown.
                    try:
                        await asyncio.wait_for(websocket.receive_json(), timeout=0.25)
                    except asyncio.TimeoutError:
                        pass
        except Exception:
            try:
                await websocket.close()
            except Exception:
                pass

        finally:
            self.cancel_event.set()
            self.shutdown.sockets.discard(websocket)


class WorkspaceHTTPApplication:
    """Assemble the optional HTTP transport around a workspace composition root."""
    def __init__(self, experiments_dir="experiments", assets=None, *, services=None):
        from .services import WorkspaceServices
        self.services = services if services is not None else WorkspaceServices(experiments_dir)
        self.assets = assets

    def build(self):
        try:
            from fastapi import FastAPI, Request, WebSocket, HTTPException, Body
            from fastapi.responses import FileResponse, JSONResponse, Response
            from fastapi.staticfiles import StaticFiles
        except ImportError as error:
            raise RuntimeError("Install the GUI extra: pip install 'zombie-sim[gui]'") from error
        # FastAPI resolves annotation names in module globals.
        globals().update(Request=Request, WebSocket=WebSocket)
        workspace = self.services
        manager = workspace.manager
        readers = workspace.readers
        assets = self.assets
        reads = HTTPReadController(readers)
        configurations_controller = ConfigurationHTTPController(workspace.configuration, readers)
        runs_controller = RunHTTPController(manager)
        session = secrets.token_urlsafe(32)

        @asynccontextmanager
        async def lifespan(app):
            yield
            if app.state.shutdown.phase != "ready":
                app.state.shutdown.start(app.state.shutdown.mode or "save", 900)
                await app.state.shutdown.task
                if app.state.shutdown.phase != "ready":
                    raise RuntimeError(app.state.shutdown.error)
            await asyncio.to_thread(workspace.close)

        app = FastAPI(title="Zombie simulation research workspace", version="0.1.0", lifespan=lifespan)
        app.state.services = workspace
        app.state.manager = manager
        app.state.session_token = session
        from .export_jobs import register_export_routes
        register_export_routes(app, manager, jobs=workspace.exports)
        shutdown = workspace.shutdown
        app.state.shutdown = shutdown
        app.state.readers = readers

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
            safe_status = request.method == "GET" and (request.url.path in {"/api/runs", "/api/launcher", "/api/shutdown"} or request.url.path.startswith("/api/commands/"))
            shutdown_control = request.url.path in {"/api/shutdown", "/api/shutdown/exit", "/api/launcher/drain", "/api/launcher/exit"}
            terminal_control = False
            if request.method == "POST" and request.url.path.endswith("/commands"):
                try:terminal_control = (await request.json()).get("operation") in {"stop", "terminate"}
                except (ValueError, AttributeError):pass
            if shutdown.draining and request.url.path.startswith("/api/") and not (safe_status or shutdown_control or (terminal_control and shutdown.controls_open)):
                return JSONResponse({"code":"SERVICE_DRAINING","error":"Workspace shutdown is in progress. Inspect shutdown status or retry shutdown; new simulation and analysis work is disabled."},status_code=503)
            mutation = request.method not in {"GET", "HEAD", "OPTIONS"} and not shutdown_control
            if mutation:shutdown.active_mutations += 1
            try:
                response = await call_next(request)
            except Exception as error:
                reference = secrets.token_hex(6)
                LOGGER.exception("API request failed [%s]: %s %s", reference, request.method, request.url.path)
                response = JSONResponse({"error": f"{type(error).__name__}: {error}",
                                         "code": "INTERNAL_ERROR", "reference": reference}, status_code=500)
            finally:
                if mutation:shutdown.active_mutations -= 1
            if request.method == "GET":
                response.set_cookie("zombie_session", session, httponly=True, samesite="strict")
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response

        @app.exception_handler(ValueError)
        async def invalid(request, error):
            from .config import ConfigError
            code = getattr(error, "code", None) or ("INCOMPATIBLE_ROLE" if "incompatible or unknown role" in str(error) else "INVALID_DOMAIN") if isinstance(error, ConfigError) else "INVALID_REQUEST"
            issues = [{"path": str(error).split(":", 1)[0], "code": code, "message": str(error)}]
            return JSONResponse({"error": str(error), "code": code, "issues": issues}, status_code=422)

        @app.exception_handler(ViewCancelled)
        async def cancelled_reader(request, error):
            return JSONResponse({"error":str(error),"code":"READER_CANCELLED"},status_code=499)

        @app.exception_handler(RunInitializing)
        async def initializing(request, error):
            return JSONResponse({"error": str(error), "code": "RUN_INITIALIZING"},
                                status_code=503, headers={"Retry-After": "1"})

        @app.exception_handler(KeyError)
        async def missing(request, error):
            return JSONResponse({"error": str(error.args[0]) if error.args else str(error), "code": "NOT_FOUND"}, status_code=404)

        @app.get("/api/shutdown")
        async def shutdown_status():return shutdown.status()

        @app.post("/api/shutdown")
        async def begin_shutdown(body: dict = Body(...)):
            return shutdown.start(body.get("mode","save"),body.get("timeout",900))

        @app.post("/api/shutdown/exit")
        async def exit_service():
            shutdown.request_exit()
            return {"status":"exiting"}

        async def read_request(request, operation, *args, **kwargs):
            return await reads.read(request, operation, *args, **kwargs)

        @app.get("/api/config")
        def configurations():
            return configurations_controller.metadata()

        @app.post("/api/config/validate")
        def validate(body: dict = Body(...)):
            return configurations_controller.validate(body)

        @app.post("/api/config/preview")
        def preview(body: dict = Body(...)):
            return configurations_controller.preview(body)

        @app.post("/api/config/import")
        def import_config(body: dict = Body(...)):
            return configurations_controller.import_config(body)

        @app.post("/api/config/export")
        def export_config(body: dict = Body(...)):
            return configurations_controller.export_config(body)

        @app.get("/api/runs")
        def runs():
            return manager.list_runs()

        @app.post("/api/runs")
        def create(body: dict = Body(...)):
            return runs_controller.create(body)

        @app.get("/api/runs/{run_id}/view")
        async def view(request: Request, run_id: str, time: str | None = None, revision: int | None = None, generation: int = 0):
            return await read_request(request,"snapshot",run_id,time,revision,generation)

        @app.post("/api/runs/{run_id}/commands")
        def command(run_id: str, body: dict = Body(...)):
            return runs_controller.command(run_id, body)

        @app.get("/api/commands/{command_id}")
        def command_result(command_id: str):
            return runs_controller.command_result(command_id)

        @app.post("/api/runs/{run_id}/branch")
        def branch(run_id: str, body: dict = Body(...)):
            return runs_controller.branch(run_id, body)

        @app.get("/api/runs/{run_id}/events")
        async def events(request: Request, run_id: str, start: int = 0, end: int | None = None, kind: str | None = None,
                         agent_id: str | None = None, limit: int = 1000, latest: bool = True):
            return await read_request(request,"events",run_id,start,end,kind,agent_id,max(1,min(limit,5000)),latest=latest)

        @app.get("/api/runs/{run_id}/metrics")
        async def metrics(request: Request, run_id: str, end: str | None = None, interval: str = "1", revision: int | None = None):
            return await read_request(request,"metrics",run_id,end,interval,revision=revision)

        @app.get("/api/runs/{run_id}/cohorts")
        async def cohorts(request: Request, run_id: str, revision: int | None = None,
                          time: str | None = None, with_cursor: bool = False):
            result = await read_request(request,"cohort_view",run_id,time,revision)
            return result if with_cursor or isinstance(result,Response) else result["cohorts"]

        @app.post("/api/runs/{run_id}/cohorts")
        def save_cohort(run_id: str, body: dict = Body(...)):
            return manager.save_cohort(run_id, body)

        @app.post("/api/comparison")
        async def comparison(request: Request, body: dict = Body(...)):
            return await read_request(request,"comparison",body.get("sources"))

        @app.get("/api/runs/{run_id}/timeline")
        async def timeline(request: Request, run_id: str, revision: int | None = None, agent: str | None = None,
                           time: str | None = None, limit: int = 500,
                           before_sequence: str | None = None, after_sequence: str | None = None):
            return await read_request(request,"timeline",run_id,revision,agent,time=time,limit=limit,
                                      before_sequence=before_sequence,after_sequence=after_sequence)

        @app.get("/api/runs/{run_id}/observations/{agent_id}")
        async def observation(request: Request, run_id: str, agent_id: str, revision: int | None = None, decision_index: int | None = None):
            return await read_request(request,"observation",run_id,agent_id,revision,decision_index)

        @app.get("/api/runs/{run_id}/export")
        async def export(request: Request, run_id: str, format: str = "json", time: str | None = None, revision: int | None = None, start: str = "0", end: str | None = None):
            result = await read_request(request,"legacy_export",run_id,format,time,revision,start,end)
            if isinstance(result,Response):return result
            payload,media_type,filename=result
            return Response(payload,media_type=media_type,headers={"Content-Disposition":f'attachment; filename="{filename}"'})

        @app.websocket("/api/runs/{run_id}/stream")
        async def stream(websocket: WebSocket, run_id: str):
            return await LiveViewSession(manager, readers, shutdown, session, local_origin).run(websocket, run_id)

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



def create_app(experiments_dir="experiments", assets=None, *, services=None):
    """Compatibility entry point for the optional workspace HTTP application."""
    return WorkspaceHTTPApplication(experiments_dir, assets, services=services).build()


def serve(experiments_dir="experiments", host="127.0.0.1", port=8765):
    try:
        import uvicorn
    except ImportError as error:
        raise RuntimeError("Install the GUI extra: pip install 'zombie-sim[gui]'") from error
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("This release supports loopback hosting only")
    run_service(create_app(experiments_dir), host=host, port=port)


def run_service(app, **options):
    """Keep the listener/status alive while safe drain precedes Uvicorn exit."""
    import uvicorn
    class DrainingServer(uvicorn.Server):
        def handle_exit(self, sig, frame):
            # Repeated signals are retries, never permission to kill a writer.
            coordinator=app.state.shutdown
            coordinator.start(coordinator.mode or "save",900)
            if not getattr(self,"drain_waiter",None) or self.drain_waiter.done():
                async def finish():
                    last_phase=None;last_report=0
                    import time
                    while True:
                        state=coordinator.status();now=time.monotonic()
                        if state['phase']!=last_phase or now-last_report>=4:
                            print(f"Shutdown: {state['phase'].replace('_',' ')} — {state['elapsed_seconds']:.1f}s; "
                                  f"{state['active_mutations']} accepted requests, {state['readers']['active']} readers, "
                                  f"{state['exports']['active']} exports, {state['viewers']} viewers.",flush=True)
                            last_phase=state['phase'];last_report=now
                        if coordinator.task.done():break
                        await asyncio.sleep(.2)
                    await coordinator.task
                    if coordinator.phase=="ready":self.should_exit=True
                    else:LOGGER.error("%s Status remains available at /api/shutdown",coordinator.error)
                self.drain_waiter=asyncio.create_task(finish())
    server=DrainingServer(uvicorn.Config(app,timeout_graceful_shutdown=5,**options))
    app.state.shutdown.exit_callback=lambda:setattr(server,'should_exit',True)
    server.run()
