"""Run named deep-OOP qualification gates and retain exact commands/results.

No skipped gate is a passing release. The full baseline needs an explicit wall
budget; list mode prints commands without executing or claiming conformance.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
GATES = ("audit", "harness", "formal-harness", "architecture", "core", "integration",
         "statistical", "browser", "performance", "training", "differential", "baseline")


def source_hashes():
    result = {}
    for directory in ("src/zombie_sim", "tests", "gui/src"):
        for path in sorted((ROOT / directory).rglob("*")):
            if path.suffix in {".py", ".ts", ".tsx"} and "__pycache__" not in path.parts:
                result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def commands(gate, output, baseline_timeout):
    runtime = str(ROOT / ".runtimeenv/bin/python")
    acceptance = [runtime, "-m", "tests.run_acceptance", "--adapter", "zombie_sim.testing:create_adapter"]
    report = lambda name: ["--report", str(output / (name + ".json"))]
    if gate == "audit":
        return [[runtime, "-m", "tests.audit_suite"]]
    if gate in {"harness", "architecture", "formal-harness"}:
        folder = {"harness": "tests/harness", "architecture": "tests/architecture", "formal-harness": "tests/formal_harness"}[gate]
        python = str(ROOT / "ontology/formal_v0.1/.venv/bin/python") if gate == "formal-harness" else runtime
        return [[python, "-m", "unittest", "discover", "-s", folder, "-v"]]
    if gate == "integration":
        return [acceptance + ["--match", selected, "--timeout", "180"] + report(selected)
                for selected in ("LIF_worked_population_accounting_K", "POL_", "FORMAL_actual")]
    if gate == "differential":
        return [[runtime, "scripts/deep_oop_differential.py", "--output", str(output / "differential-default")],
                [runtime, "scripts/deep_oop_differential.py", "--corpus", str(ROOT / "artifacts/deep-oop-refactor/legacy-custom-corpus-v2"),
                 "--output", str(output / "differential-custom")]]
    if gate == "baseline":
        return [acceptance + ["--match", "BASELINE_full_default_model_run", "--timeout",
                              str(baseline_timeout) if baseline_timeout else "EXPLICIT_BUDGET_REQUIRED"] + report(gate)]
    if gate == "training":
        acceptance[0] = str(ROOT / ".venv-training/bin/python")
    timeout = "60" if gate == "core" else "300" if gate == "browser" else "180"
    return [acceptance + ["--tier", gate, "--timeout", timeout] + report(gate)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", choices=(*GATES, "all"), action="append", required=True)
    parser.add_argument("--output", type=Path, required=True, help="New evidence directory; never overwritten")
    parser.add_argument("--baseline-timeout", type=int, help="Per-case wall seconds for the genuine full baseline")
    parser.add_argument("--list", action="store_true", help="Show commands only; not conformance evidence")
    args = parser.parse_args()
    selected = list(GATES) if "all" in args.gate else list(dict.fromkeys(args.gate))
    if args.baseline_timeout is not None and args.baseline_timeout <= 60:
        parser.error("Full baseline needs an explicitly assessed budget greater than the default 60 seconds")
    if "baseline" in selected and not args.baseline_timeout and not args.list:
        parser.error("Choose --baseline-timeout after checking disk/RAM capacity; a bounded prefix is not the baseline")
    output = args.output.resolve()
    if args.list:
        for gate in selected:
            for command in commands(gate, output, args.baseline_timeout):
                extra = (f" ZOMBIE_ACCEPTANCE_RPC_TIMEOUT={args.baseline_timeout or 'EXPLICIT_BUDGET_REQUIRED'}"
                         f" ZOMBIE_ACCEPTANCE_RETAIN_HISTORY={shlex.quote(str(output / 'baseline-history'))}") if gate == "baseline" else ""
                print(f"{gate}: PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1{extra} {shlex.join(command)}")
        print("Framework conformance: NOT RUN.")
        return 0
    output.mkdir(parents=True, exist_ok=False)
    before = source_hashes()
    report = {"schema": "deep-oop-qualification-v1", "started_utc": datetime.now(timezone.utc).isoformat(),
              "selected_gates": selected, "mandatory_gates": list(GATES), "results": [],
              "source_hashes": before, "status": "RUNNING"}
    report_path = output / "qualification.json"
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")
    for gate in selected:
        for index, command in enumerate(commands(gate, output, args.baseline_timeout)):
            path = output / f"{gate}-{index + 1}.log"
            start = time.monotonic()
            print(f"RUN {gate}: {shlex.join(command)}", flush=True)
            command_environment = environment.copy()
            if gate == "baseline":
                command_environment["ZOMBIE_ACCEPTANCE_RPC_TIMEOUT"] = str(args.baseline_timeout)
                command_environment["ZOMBIE_ACCEPTANCE_RETAIN_HISTORY"] = str(output / "baseline-history")
            try:
                with path.open("w") as log:
                    completed = subprocess.run(command, cwd=ROOT, env=command_environment, stdout=log, stderr=subprocess.STDOUT)
                code, error = completed.returncode, None
            except OSError as exc:
                code, error = None, str(exc)
            report["results"].append({"gate": gate, "command": command, "log": str(path),
                "elapsed_seconds": time.monotonic() - start, "returncode": code, "error": error,
                "status": "PASS" if code == 0 else "FAIL"})
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            print(f'{report["results"][-1]["status"]} {gate}', flush=True)
    after = source_hashes()
    report["changed_during_verification"] = [path for path in sorted(before.keys() | after.keys()) if before.get(path) != after.get(path)]
    report["missing_mandatory_gates"] = sorted(set(GATES) - set(selected))
    report["scope"] = "full" if not report["missing_mandatory_gates"] else "partial"
    all_pass = all(result["status"] == "PASS" for result in report["results"])
    report["status"] = "INVALIDATED_BY_SOURCE_CHANGES" if report["changed_during_verification"] else "PASS" if all_pass else "FAIL"
    report["release_complete"] = report["status"] == "PASS" and report["scope"] == "full"
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f'Qualification: {report["status"]} ({report["scope"]}); release_complete={report["release_complete"]}', flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
