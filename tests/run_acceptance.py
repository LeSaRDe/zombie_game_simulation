"""Run future-framework acceptance tests through an explicitly selected adapter.

Missing adapters, unsupported operations and timeouts are errors, never skips.
"""
import argparse
from collections import Counter
from copy import deepcopy
import importlib
import json
import multiprocessing
import os
from pathlib import Path
import signal
import tempfile
import time
import traceback
import unittest

from tests.assertions import assert_checks, select, ContractFailure
from tests.invariants import validate_trace, validate_snapshot, require
from tests.research_checks import validate_baseline, validate_trials, validate_performance
from tests.policy_checks import validate_policy_result
from tests.formal_checks import validate_formal_export
from tests.suite import load_cases, TIERS


def factory_from_spec(spec):
    module, separator, name = spec.partition(":")
    if not separator or not module or not name or "." in name:
        raise ValueError("Adapter must be importable.module:factory")
    factory = getattr(importlib.import_module(module), name)
    if not callable(factory):
        raise TypeError("Adapter factory is not callable")
    return factory


def _execute_child(factory_spec, request, workdir, connection):
    # Isolate descendants so a timed-out adapter cannot leave simulation/browser
    # workers behind. The factory must not detach workers from this session.
    if os.name == "posix":
        os.setsid()
    adapter = None
    result = None
    try:
        adapter = factory_from_spec(factory_spec)(workdir=Path(workdir))
        response = adapter.execute(deepcopy(request))
        if not isinstance(response, dict):
            raise TypeError("Adapter.execute must return a JSON object")
        json.dumps(response, allow_nan=False)
        result = {"ok": True, "response": response}
    except BaseException:
        result = {"ok": False, "error": traceback.format_exc()}
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except BaseException:
                result = {"ok": False, "error": "Adapter cleanup failed:\n" + traceback.format_exc()}
        try:
            connection.send(result)
        finally:
            connection.close()


def execute_isolated(factory_spec, request, timeout=60):
    ctx = multiprocessing.get_context("spawn")
    with tempfile.TemporaryDirectory(prefix="zombie-acceptance-") as workdir:
        receiving, sending = ctx.Pipe(duplex=False)
        process = ctx.Process(target=_execute_child, args=(factory_spec, request, workdir, sending))
        process.start()
        sending.close()
        try:
            if not receiving.poll(timeout):
                raise TimeoutError(f"Adapter exceeded {timeout} seconds")
            result = receiving.recv()
            if not result["ok"]:
                raise RuntimeError(result["error"])
            return result["response"]
        finally:
            receiving.close()
            process.join(timeout=1)
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            if process.is_alive():
                process.terminate()
                process.join(timeout=2)
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.is_alive():
                process.kill()
                process.join(timeout=2)


def run_case(case, adapter_spec, timeout):
    response = execute_isolated(adapter_spec, case["request"], timeout)
    if case["request"]["kind"] == "simulation":
        validate_trace(response)
    assert_checks(response, case["checks"])
    for key, validator in (("snapshot_paths", validate_snapshot), ("baseline_paths", validate_baseline)):
        for pointer in case.get(key, []):
            snapshots = select(response, pointer)
            if not snapshots:
                raise ContractFailure(f"Missing required snapshot at {pointer}")
            for snapshot in snapshots:
                validator(snapshot)
    for spec in case.get("trial_checks", []):
        values = select(response, spec["path"])
        if len(values) != 1:
            raise ContractFailure(f"Expected one trial collection: {spec['path']}")
        validate_trials(values[0], spec)
    for spec in case.get("performance_checks", []):
        values = select(response, spec["path"])
        require(len(values) == 1, "Missing benchmark capture")
        validate_performance(values[0], spec)
    for key, validator in (("policy_checks", validate_policy_result), ("formal_checks", validate_formal_export)):
        for spec in case.get(key, []):
            values = select(response, spec["path"])
            require(len(values) == 1, f"Missing {key} capture")
            validator(values[0], spec)
    if "baseline_end" in case:
        spec = case["baseline_end"]
        end = select(response, spec["snapshot"])[0]
        status = select(response, spec["status"])[0]
        from tests.assertions import number
        living = sum(a["life"] > 0 for a in end["agents"].values())
        if living:
            require(number(end["time"]) == 1800 and status["termination_reason"] == "HORIZON",
                    "Baseline stopped before horizon while agents remained alive")
        else:
            require(status["termination_reason"] in {"HORIZON", "NO_LIVING_AGENTS"}, "Invalid extinction stop reason")


def make_suite(cases, adapter_spec, timeout):
    suite = unittest.TestSuite()
    for case in cases:
        def run(self, case=case):
            run_case(case, adapter_spec, timeout)
        cls = type("Acceptance", (unittest.TestCase,), {"runTest": run,
                   "__str__": lambda self, id=case["id"]: id})
        suite.addTest(cls())
    return suite


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", default=os.environ.get("ZOMBIE_TEST_ADAPTER"))
    parser.add_argument("--list", action="store_true", help="List contracts only; does not test a framework")
    parser.add_argument("--tier", choices=sorted(TIERS), action="append")
    parser.add_argument("--match", default="", help="Case ID substring")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    all_cases = load_cases()
    cases = [c for c in all_cases if (not args.tier or c["tier"] in args.tier) and args.match in c["id"]]
    if not cases:
        parser.error("Selection contains no cases")
    report = {"suite_version": "0.1", "total_catalog_cases": len(all_cases), "selected_cases": len(cases),
              "scope": "full" if len(cases) == len(all_cases) else "partial", "adapter": args.adapter,
              "executed": 0, "status": "NOT_RUN", "selected_ids": [c["id"] for c in cases],
              "tiers": dict(Counter(c["tier"] for c in cases))}
    def save():
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2) + "\n")
    if args.list:
        for c in cases:
            print(f"{c['id']} [{c['tier']}] " + ", ".join(c["requirements"]))
        print(f"Listed {len(cases)} cases. Framework conformance: NOT RUN.")
        save()
        return 0
    if not args.adapter:
        print("Framework conformance: NOT RUN. No implementation adapter is connected.\n"
              "Use --adapter importable.module:factory (see tests/ADAPTER_CONTRACT.md).")
        save()
        return 2
    try:
        factory_from_spec(args.adapter)
        module = importlib.import_module(args.adapter.partition(":")[0])
        if getattr(module, "CONFORMANCE_TEST_DOUBLE", False):
            raise ValueError("Harness doubles cannot be used for framework conformance")
    except Exception as exc:
        print(f"Framework conformance: NOT RUN. Cannot load adapter: {exc}")
        report["adapter_error"] = str(exc)
        save()
        return 2
    start = time.monotonic()
    result = unittest.TextTestRunner(verbosity=2).run(make_suite(cases, args.adapter, args.timeout))
    report.update(executed=result.testsRun, status="PASS" if result.wasSuccessful() else "FAIL",
                  elapsed_seconds=time.monotonic()-start,
                  failures=[{"id": str(c), "traceback": e} for c, e in result.failures],
                  errors=[{"id": str(c), "traceback": e} for c, e in result.errors],
                  skipped=[{"id": str(c), "reason": e} for c, e in result.skipped])
    if result.skipped:
        report["status"] = "FAIL"
    save()
    print(f"Framework conformance: {report['status']} ({report['scope']} selection).")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
