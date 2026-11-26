#!/usr/bin/env python3
"""Serve a workspace owned by the friendly simulation launcher.

The additional endpoint identifies this exact service instance. Simulation
creation, control, persistence and shutdown still use the existing application.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import closing, contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import sys


REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "src"))
SCHEMA = "zombie-sim/launcher-v1"


class ServiceError(RuntimeError):
    """A service cannot safely take ownership of the requested workspace."""


def absolute_workspace(value):
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("--workspace must be an absolute directory")
    return path.resolve()


def port_number(value):
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("--port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("--port must be between 1 and 65535")
    return port


def _pid_exists(pid):
    if not isinstance(pid, int) or pid <= 0:
        raise ServiceError("An existing worker lease contains an invalid process ID.")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def check_existing_workers(workspace):
    """Refuse active or ambiguous leases without signaling or rewriting them.

    A held per-run lock proves a coordinator still owns that run. A live PID
    without a held lock is ambiguous (for example PID reuse); do not adopt it or
    silently remove its lease. A dead lease is left for ordinary application
    recovery. Native GUI services do not share the launcher's service lock, so
    callers must not run an idle native GUI service against the same workspace.
    """
    import fcntl

    database = workspace / "manager.sqlite"
    if not database.exists():
        return
    try:
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=5)) as connection:
            rows = connection.execute(
                "SELECT runs.id,runs.directory,worker_leases.pid FROM runs "
                "LEFT JOIN worker_leases ON worker_leases.run_id=runs.id"
            ).fetchall()
    except sqlite3.Error as error:
        raise ServiceError(f"Cannot inspect existing workspace safely: {error}") from error

    for run_id, directory, pid in rows:
        lock_path = Path(directory) / "worker.lock"
        try:
            descriptor = os.open(lock_path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        except FileNotFoundError:
            descriptor = None
        if descriptor is not None:
            try:
                os.set_inheritable(descriptor, False)
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ServiceError(
                        f"Run {run_id} still has an active coordinator. Stop it in its "
                        "existing service, wait for worker exit, then try again."
                    ) from error
                finally:
                    # Unlocking this descriptor never releases another owner's lock.
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        if pid is not None and _pid_exists(pid):
            raise ServiceError(
                f"Run {run_id} has an unresolved lease for live PID {pid}. "
                "The launcher will not adopt or signal that process. Inspect the "
                "original service or choose a different workspace."
            )


@contextmanager
def workspace_service_lock(workspace, *, instance, port):
    """Keep one launcher service per workspace for the complete server lifetime."""
    try:
        import fcntl
    except ImportError as error:
        raise ServiceError("The launcher requires POSIX file locks (Linux/macOS).") from error

    directory = workspace / ".launcher"
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        directory / "service.lock",
        os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        # Python already defaults to non-inheritable descriptors. Make the
        # invariant explicit so spawned simulation workers cannot retain this lock.
        os.set_inheritable(descriptor, False)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ServiceError(
                f"Another launcher service already owns {workspace}. "
                "Use its existing connection or shut it down before changing ports."
            ) from error
        record = {
            "schema": SCHEMA, "workspace": str(workspace), "instance": instance,
            "pid": os.getpid(), "port": port,
        }
        os.ftruncate(descriptor, 0)
        content = (json.dumps(record, sort_keys=True) + "\n").encode()
        offset = 0
        while offset < len(content):
            offset += os.write(descriptor, content[offset:])
        os.fsync(descriptor)
        yield
    finally:
        # The persistent file is only a lock target/provenance record, not proof
        # that a process is still running. Never unlink it while other callers
        # might already have the same inode open.
        os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=absolute_workspace, required=True)
    parser.add_argument("--port", type=port_number, required=True)
    parser.add_argument("--instance", required=True, help="Unique launcher instance identity")
    args = parser.parse_args(argv)
    if not args.instance.strip() or len(args.instance) > 256:
        parser.error("--instance must be a nonempty identity of at most 256 characters")
    try:
        import uvicorn
        from fastapi import Body, HTTPException
        from fastapi.responses import JSONResponse
        from zombie_sim.server import create_app

        with workspace_service_lock(args.workspace, instance=args.instance, port=args.port):
            check_existing_workers(args.workspace)
            app = create_app(str(args.workspace))
            mutation_condition = asyncio.Condition()
            gate = {"draining": False, "active": 0}

            @app.middleware("http")
            async def guard_mutations(request, call_next):
                if request.method in {"GET", "HEAD", "OPTIONS"} or request.url.path == "/api/launcher/drain":
                    return await call_next(request)

                # Read only the stop/terminate payload needed by the gate. The
                # cached request body remains available to the ordinary handler.
                terminal_control = False
                if request.method == "POST" and re.fullmatch(r"/api/runs/[^/]+/commands", request.url.path):
                    try:
                        body = await request.json()
                        terminal_control = isinstance(body, dict) and body.get("operation") in {"stop", "terminate"}
                    except (ValueError, UnicodeError):
                        pass

                async with mutation_condition:
                    if gate["draining"] and not terminal_control:
                        return JSONResponse(
                            {"code": "LAUNCHER_DRAINING", "error":
                             "This workspace is shutting down. New runs and resume commands "
                             "are disabled. Finish shutdown (or retry it), then restart the service."},
                            status_code=503,
                        )
                    gate["active"] += 1
                try:
                    return await call_next(request)
                finally:
                    async with mutation_condition:
                        gate["active"] -= 1
                        mutation_condition.notify_all()

            @app.get("/api/launcher")
            def launcher_identity():
                return {
                    "schema": SCHEMA,
                    "workspace": str(args.workspace),
                    "instance": args.instance,
                    "pid": os.getpid(),
                    "draining": gate["draining"],
                }

            @app.post("/api/launcher/drain")
            async def drain(body: dict = Body(...)):
                # The existing application middleware checks the same local
                # session cookie as other mutation endpoints. Instance matching
                # prevents a stale launcher from draining a replacement service.
                if body.get("instance") != args.instance:
                    raise HTTPException(409, "Launcher instance changed; reconnect before shutdown.")
                async with mutation_condition:
                    gate["draining"] = True
                    await mutation_condition.wait_for(lambda: gate["active"] == 0)
                return launcher_identity()

            print(f"Simulation workspace: {args.workspace}", flush=True)
            print(f"GUI: http://127.0.0.1:{args.port}", flush=True)
            uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
        return 0
    except ImportError as error:
        print(
            "Simulation service: GUI dependencies are missing. From the repository, "
            "install them with your selected Python: python -m pip install -e '.[gui]' "
            f"({error})", file=sys.stderr, flush=True,
        )
        return 2
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
        print(f"Simulation service: {error}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
