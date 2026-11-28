"""Command-line workflows sharing engine, configuration and history services."""
from __future__ import annotations

import argparse
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import csv
import itertools
import json
from pathlib import Path
import sys
import time
import tomllib
import uuid

from .storage import History, canonical, exact_time
from .visualization import events_csv, populations, project_state, resources, sampled_metrics, world_svg
from .interrupts import deferred_sigint


def _print(value):
    # Public JSON materializes branch-local runtime mappings before encoding.
    print(json.dumps(deepcopy(value), indent=2, default=str))


def _worker_count(value):
    if value=="auto":return value
    try:
        count=int(value)
        if count>0:return count
    except ValueError:
        pass
    raise argparse.ArgumentTypeError("Use a positive worker count or 'auto'")




def _directory(value, root="experiments"):
    path = Path(value)
    if path.is_file():
        return path.parent
    if path.is_dir():
        return path
    path = Path(root) / "runs" / value
    if not path.is_dir():
        database = Path(root) / "manager.sqlite"
        if database.exists():
            from .persistence.catalog import SQLiteRunCatalog
            catalog=SQLiteRunCatalog(database,read_only=True)
            try:
                row=catalog.run(value)
                if row and Path(row["directory"]).is_dir():
                    return Path(row["directory"])
            finally:
                catalog.close()
        raise ValueError(f"Unknown run {value!r}; supply its run directory")
    return path


def _history(value, root="experiments"):
    directory = _directory(value, root)
    path = directory / "run.sqlite"
    if not path.exists():
        raise ValueError(f"No durable history at {path}")
    return History(path, read_only=True)


@contextmanager
def _run_lease(directory):
    """Share the GUI coordinator lease before mutating an existing run."""
    import fcntl
    with (Path(directory) / "worker.lock").open("a+") as lease:
        try:
            fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError("This run has an active coordinator; stop/save it in the GUI before CLI resume") from error
        try:
            yield
        finally:
            fcntl.flock(lease.fileno(), fcntl.LOCK_UN)






def _continuation_status(directory, journal, root):
    """Read terminal decisions under the lease, before opening any writer."""
    statuses = [journal.get_metadata("control_state", {}).get("status")]
    for filename, key in (("manifest.json", None), ("worker-checkpoint.json", "control")):
        path = directory / filename
        if path.exists():
            document = json.loads(path.read_text())
            statuses.append((document.get(key, {}) if key else document).get("status"))
    candidates = {Path(root) / "manager.sqlite", directory / "manager.sqlite"}
    if directory.parent.name == "runs":
        candidates.add(directory.parent.parent / "manager.sqlite")
    for path in candidates:
        if not path.exists():
            continue
        from .persistence.catalog import SQLiteRunCatalog
        catalog=SQLiteRunCatalog(path,read_only=True)
        try:
            row=catalog.run_by_directory(directory.absolute())
            if row:
                statuses.append(row["status"])
        finally:
            catalog.close()
    if "terminated" in statuses:
        raise ValueError("This run is terminated and cannot be resumed; its history remains available for replay or branching.")
    return "completed" if "completed" in statuses else None




def _experiment_job(job):
    config, output, workers, backend = job
    return _headless_run(config, output, workers, backend)




class HeadlessRunController:
    """Own headless execution, continuation and durable finalization workflows."""
    def finish(self, simulation, directory, manifest, status, *, started=None, save=True, register=False):
        """Publish the durable frontier even on save failure, then always release resources."""
        from .application import _atomic_json, _journal
        try:
            try:
                if save:
                    simulation.checkpoint(directory / "checkpoint.json")
            except BaseException as error:
                status = "failed"
                manifest["error"] = str(error)
                raise
            finally:
                # A failure may leave speculative coordinator state. Report only
                # the ledger boundary, without rolling back or inventing a save.
                state = simulation.history.state_at()
                if status != "failed":
                    manifest.pop("error", None)
                manifest.update(status=status, time=str(state["time"]), revision=simulation.history.revision,
                                execution=simulation.execution_diagnostics(),
                                populations=populations(state), resources=resources(state))
                if started is not None:
                    manifest["elapsed_wall_seconds"] = time.monotonic() - started
                _atomic_json(directory / "manifest.json", manifest)
                manager_path = directory.parent.parent / "manager.sqlite" if directory.parent.name == "runs" else directory / "manager.sqlite"
                if (register and directory.parent.name == "runs") or manager_path.exists():
                    manager = _journal(manager_path)
                    try:
                        frontier = {"time": manifest["time"], "revision": str(manifest["revision"]), "status": status}
                        with manager:
                            if register:
                                manager.insert_run(manifest["run_id"],str(directory.absolute()),manifest["config"],status,frontier=frontier,replace=True)
                            else:
                                manager.update_run(manifest["run_id"],status=status,frontier=frontier)
                    finally:
                        manager.close()
        finally:
            simulation.close()
        return manifest


    def run(self, config, output, workers=None, backend=None, until=None):
        from .engine import Simulation
        from .application import _atomic_json
        with deferred_sigint() as interrupted:
            directory = Path(output)
            directory.mkdir(parents=True, exist_ok=True)
            if (directory / "run.sqlite").exists():
                raise ValueError(f"Run history already exists in {directory}; use resume or a fresh output directory")
            identity = directory.name if len(directory.name) == 32 and all(c in "0123456789abcdef" for c in directory.name) else uuid.uuid4().hex
            simulation = Simulation(config, history_path=str(directory / "run.sqlite"), workers=workers, backend=backend, run_id=identity)
            manifest = {"run_id": simulation.state.get("run_id", directory.name), "config": simulation.config,
                        "created": time.time(), "status": "running"}
            started = time.monotonic()
            try:
                _atomic_json(directory / "manifest.json", manifest)
                simulation.advance_until(until if until is not None else simulation.config["horizon"],
                                         return_snapshot=False, should_yield=interrupted)
            except BaseException as error:
                manifest["error"] = str(error)
                self.finish(simulation, directory, manifest, "failed", started=started, save=False, register=True)
                raise
            status = "completed" if simulation.run_status == "COMPLETED" else "interrupted"
            return self.finish(simulation, directory, manifest, status, started=started, register=True)


    def resume(self, directory, until, root):
        from .engine import Simulation
        from .runtime import restore_revision
        with _run_lease(directory), deferred_sigint() as interrupted:
            journal = History(directory / "run.sqlite", read_only=True)
            try:
                if _continuation_status(directory, journal, root) == "completed":
                    state = journal.state_at()
                    return {"status": "completed", "time": str(state["time"]), "revision": journal.revision,
                            "message": "This run is already complete; create a branch for a new experiment."}
                has_runtime = journal.runtime_at() is not None
            finally:
                journal.close()
            managed = directory / "worker-checkpoint.json"
            if has_runtime:
                simulation = restore_revision(Simulation, directory / "run.sqlite", output_history_path=directory / "run.sqlite")
            elif managed.exists():
                simulation = Simulation.from_serialized(json.loads(managed.read_text())["engine"], history_path=str(directory / "run.sqlite"))
            else:
                simulation = Simulation.restore(directory / "checkpoint.json", history_path=directory / "run.sqlite")
            manifest = {"run_id": simulation.state["run_id"], "config": simulation.config}
            try:
                manifest_path = directory / "manifest.json"
                if manifest_path.exists():
                    manifest.update(json.loads(manifest_path.read_text()))
                if simulation.run_status == "COMPLETED":
                    simulation.close()
                    return {"status": "completed", "time": str(simulation.time), "revision": simulation.revision}
                active = simulation.history.get_metadata("active_control_command")
                if active and not interrupted():
                    simulation._active_control_command = active
                    operation = active["operation"]
                    if operation == "step":
                        simulation.step(return_snapshot=False, should_yield=interrupted)
                    elif operation in {"step_timestamp", "advance"}:
                        simulation.advance_until(active["target"], return_snapshot=False, should_yield=interrupted)
                    elif operation == "intervene":
                        simulation.intervene(active["request"]["change"], at=active["request"].get("time"), id=active["id"])
                simulation.advance_until(until or simulation.config["horizon"], return_snapshot=False, should_yield=interrupted)
            except BaseException as error:
                manifest["error"] = str(error)
                self.finish(simulation, directory, manifest, "failed", save=False)
                raise
            status = "completed" if simulation.run_status == "COMPLETED" else "interrupted"
            result = self.finish(simulation, directory, manifest, status)
            return {key: result[key] for key in ("status", "time", "revision", "populations")}


_headless_controller = HeadlessRunController()


def _finish_headless(simulation, directory, manifest, status, *, started=None, save=True, register=False):
    """Compatibility entry point; see :class:`HeadlessRunController`."""
    return _headless_controller.finish(simulation, directory, manifest, status, started=started, save=save, register=register)


def _headless_run(config, output, workers=None, backend=None, until=None):
    """Compatibility entry point; see :class:`HeadlessRunController`."""
    return _headless_controller.run(config, output, workers, backend, until)


def _resume_headless(directory, until, root):
    """Compatibility entry point; see :class:`HeadlessRunController`."""
    return _headless_controller.resume(directory, until, root)


class SimulationCLI:
    """Parse researcher commands and dispatch through explicit application services."""
    def __init__(self, *, configuration=None, runs=None, output=None):
        from .config import ConfigurationService
        self.configuration = configuration if configuration is not None else ConfigurationService()
        self.runs = runs if runs is not None else HeadlessRunController()
        self.output = output if output is not None else _print

    def load_configuration(self, path):
        path = Path(path)
        if path.suffix.lower() == ".json":
            return self.configuration.resolve(json.loads(path.read_text()))
        return self.configuration.resolve(path)


    def run(self, argv=None):
        parser = argparse.ArgumentParser(prog="zombie-sim", description="Ontology-based asynchronous human/zombie simulation")
        parser.add_argument("--experiments-dir", default="experiments")
        sub = parser.add_subparsers(dest="command", required=True)
        validate = sub.add_parser("validate", help="Resolve a scenario and validate parameters")
        validate.add_argument("config"); validate.add_argument("--preview", action="store_true")
        run = sub.add_parser("run", help="Execute a scenario with durable history")
        run.add_argument("config"); run.add_argument("--seed", type=int); run.add_argument("--workers", type=_worker_count)
        run.add_argument("--backend", choices=("memory", "sqlite")); run.add_argument("--until")
        run.add_argument("--output")
        inspect = sub.add_parser("inspect"); inspect.add_argument("run")
        replay = sub.add_parser("replay"); replay.add_argument("run"); replay.add_argument("--time"); replay.add_argument("--revision", type=int); replay.add_argument("--output")
        resume = sub.add_parser("resume"); resume.add_argument("run"); resume.add_argument("--until")
        branch = sub.add_parser("branch"); branch.add_argument("run"); branch.add_argument("--revision", type=int, required=True); branch.add_argument("--interventions"); branch.add_argument("--output"); branch.add_argument("--seed", type=int)
        experiment = sub.add_parser("experiment"); experiment.add_argument("config"); experiment.add_argument("--jobs", type=_worker_count, default="auto")
        export = sub.add_parser("export"); export.add_argument("run"); export.add_argument("--format", choices=("json", "csv", "svg", "parquet", "ttl"), default="json"); export.add_argument("--time"); export.add_argument("--revision", type=int); export.add_argument("--output")
        analyze = sub.add_parser("analyze"); analyze.add_argument("run"); analyze.add_argument("--interval", default="1"); analyze.add_argument("--output")
        train = sub.add_parser("train"); train.add_argument("config"); train.add_argument("--output", default="training/model"); train.add_argument("--decisions", type=int)
        evaluate = sub.add_parser("evaluate"); evaluate.add_argument("model_artifact"); evaluate.add_argument("--experiment", required=True); evaluate.add_argument("--seeds", default="2000,2001,2002"); evaluate.add_argument("--output")
        gui = sub.add_parser("gui"); gui.add_argument("--experiments-dir", dest="gui_root"); gui.add_argument("--port", type=int, default=8765); gui.add_argument("--host", default="127.0.0.1")
        args = parser.parse_args(argv)
        try:
            if args.command == "validate":
                config = self.load_configuration(args.config)
                result = {"valid": True, "fingerprint": config["fingerprint"], "resolved": config}
                if args.preview:
                    from .config import initialize_world
                    result["initialization"] = initialize_world(config)["initialization"]
                self.output(result)
            elif args.command == "run":
                config = self.load_configuration(args.config)
                if args.seed is not None:
                    config["seed"] = args.seed
                output = args.output or str(Path(args.experiments_dir) / "runs" / uuid.uuid4().hex)
                result = self.runs.run(config, output, args.workers, args.backend, args.until)
                result["directory"] = str(Path(output).absolute())
                self.output(result)
            elif args.command == "inspect":
                history = _history(args.run, args.experiments_dir)
                try:
                    state = history.state_at()
                    self.output({"time": state.get("time"), "revision": history.revision, "populations": populations(state), "resources": resources(state), "events": history.event_count(), "ledger_bytes": history.storage_bytes()})
                finally:
                    history.close()
            elif args.command in {"replay", "export", "analyze"}:
                history = _history(args.run, args.experiments_dir)
                try:
                    if args.command == "analyze":
                        data = sampled_metrics(history, interval=args.interval)
                        content = canonical(data)
                    else:
                        frontier = history.state_at()
                        if args.time is not None and not 0 <= exact_time(args.time) <= exact_time(frontier.get("time", 0)):
                            raise ValueError("Replay/export time must lie within the committed history")
                        if args.revision is not None and not 0 <= args.revision <= history.revision:
                            raise ValueError("Replay/export revision must lie within the committed history")
                        state = project_state(history.state_at(args.time, args.revision), args.time)
                        if args.command == "replay" or args.format == "json":
                            content = canonical(state)
                        elif args.format == "csv":
                            content = events_csv(history.events(end=state.get("revision", args.revision)))
                        elif args.format == "svg":
                            content = world_svg(state)
                        elif args.format == "ttl":
                            from .ontology_export import export_snapshot
                            content = export_snapshot(state, events=history.events(end=state.get("revision", args.revision)))
                        else:
                            try:
                                import pyarrow as pa
                                import pyarrow.parquet as pq
                            except ImportError as error:
                                raise ValueError("Parquet exports require the analysis extra (pyarrow)") from error
                            records = history.events(end=state.get("revision", args.revision))
                            rows = [{"revision": str(r.get("ledger_revision")), "sequence": str(r.get("ledger_sequence")), "time": str(r.get("time", "0")), "kind": str(r.get("kind", "event")), "payload_json": canonical(r)} for r in records]
                            path = Path(args.output or _directory(args.run, args.experiments_dir) / "exports" / "events.parquet")
                            path.parent.mkdir(parents=True, exist_ok=True)
                            pq.write_table(pa.Table.from_pylist(rows), path, compression="zstd")
                            self.output({"output": str(path.absolute()), "rows": len(rows)})
                            return 0
                    if args.output:
                        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
                        Path(args.output).write_text(content)
                        self.output({"output": str(Path(args.output).absolute())})
                    else:
                        print(content)
                finally:
                    history.close()
            elif args.command == "resume":
                directory = _directory(args.run, args.experiments_dir)
                self.output(self.runs.resume(directory, args.until, args.experiments_dir))
            elif args.command == "branch":
                from .engine import Simulation
                from .runtime import restore_revision
                directory = _directory(args.run, args.experiments_dir)
                output = Path(args.output or Path(args.experiments_dir) / "runs" / uuid.uuid4().hex)
                if output.exists():
                    raise ValueError("Branch destination must be a new directory")
                simulation = restore_revision(Simulation, directory / "run.sqlite", revision=args.revision)
                try:
                    if hasattr(simulation, "branch"):
                        child = simulation.branch(output, seed=args.seed)
                    else:
                        raise ValueError("This engine does not expose counterfactual branching")
                    try:
                        if args.interventions:
                            changes = json.loads(Path(args.interventions).read_text())
                            for i, change in enumerate(changes if isinstance(changes, list) else [changes]):
                                child.intervene(change.get("change", change), at=change.get("time"), id=f"branch:{i}")
                        child.checkpoint(output / "checkpoint.json")
                        self.output({"branch": str(output.absolute()), "revision": child.revision, "parent": str(directory.absolute())})
                    finally:
                        child.close()
                finally:
                    simulation.close()
            elif args.command == "experiment":
                config_path = Path(args.config)
                settings = tomllib.loads(config_path.read_text())
                base = self.load_configuration(config_path.parent / settings["scenario"])
                grid = settings.get("grid", {})
                keys = list(grid)
                combinations = list(itertools.product(*(grid[key] for key in keys))) if keys else [()]
                directory = Path(settings.get("output", Path(args.experiments_dir) / f"experiment-{uuid.uuid4().hex[:12]}"))
                jobs = []
                for index, combination in enumerate(combinations):
                    for seed in settings.get("seeds", [base["seed"]]):
                        config = json.loads(canonical(base))
                        config["seed"] = seed
                        for dotted, value in zip(keys, combination):
                            node = config
                            parts = dotted.split(".")
                            for part in parts[:-1]:
                                node = node.setdefault(part, {})
                            node[parts[-1]] = value
                        jobs.append((config, str(directory / f"instance-{index}" / f"seed-{seed}"), settings.get("workers", "auto"), settings.get("backend", "memory")))
                from .hardware import worker_budget
                run_workers=worker_budget(args.jobs,population=len(jobs))["workers"]
                jobs=[(config,output,worker_budget(workers,concurrent_runs=run_workers)["workers"],backend) for config,output,workers,backend in jobs]
                if run_workers > 1:
                    with ProcessPoolExecutor(max_workers=run_workers) as executor:
                        results = list(executor.map(_experiment_job, jobs))
                else:
                    results = [_experiment_job(job) for job in jobs]
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "experiment-results.json").write_text(canonical(results))
                self.output({"directory": str(directory.absolute()), "runs": len(results), "results": results})
            elif args.command == "train":
                from .learning import TrainingConfig
                from .training_pipeline import TrainingPipeline
                config_path = Path(args.config)
                settings = tomllib.loads(config_path.read_text())
                scenario = self.load_configuration(config_path.parent / settings["scenario"]) if "scenario" in settings and isinstance(settings["scenario"], str) and settings["scenario"].endswith((".toml", ".json")) else self.load_configuration(args.config)
                options = settings.get("training", {})
                if args.decisions is not None:
                    options["decisions"] = args.decisions
                self.output(TrainingPipeline(scenario, args.output, TrainingConfig(**options), configuration=self.configuration).run())
            elif args.command == "evaluate":
                from .training_pipeline import EvaluationPipeline
                result = EvaluationPipeline(self.load_configuration(args.experiment), args.model_artifact, seeds=[int(s) for s in args.seeds.split(",")], configuration=self.configuration).run()
                if args.output:
                    Path(args.output).write_text(canonical(result))
                self.output(result)
            elif args.command == "gui":
                from .server import serve
                serve(args.gui_root or args.experiments_dir, args.host, args.port)
            return 0
        except (ValueError, OSError, RuntimeError, KeyError) as error:
            print(f"zombie-sim: {error}", file=sys.stderr)
            return 2


_default_service = SimulationCLI()


def _configuration(path):
    """Compatibility entry point; see :class:`SimulationCLI`."""
    return _default_service.load_configuration(path)


def main(argv=None):
    """Compatibility entry point; see :class:`SimulationCLI`."""
    return _default_service.run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
