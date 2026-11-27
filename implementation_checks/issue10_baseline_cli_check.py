"""Execute the guide's exact 0.5-second baseline CLI example in a temporary run."""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

from zombie_sim.storage import History

ROOT = Path(__file__).resolve().parents[1]


def inside(agent, footprint, strict=False):
    x0, y0, x1, y1 = (float(footprint[k]) for k in ("xmin", "ymin", "xmax", "ymax")) if isinstance(footprint, dict) else map(float, footprint)
    x, y = float(agent["x"]), float(agent["y"])
    return x0 < x < x1 and y0 < y < y1 if strict else x0 <= x <= x1 and y0 <= y <= y1


def main():
    output = ROOT / "artifacts/issue10-baseline-cli"
    output.mkdir(parents=True, exist_ok=True)
    scratch = Path(tempfile.mkdtemp(prefix="zombie-issue10-baseline-")).resolve()
    run_dir = scratch / "baseline-check"
    started = time.monotonic()
    report = {"status": "RUNNING", "workspace": str(scratch), "commands": [],
              "limits": "Only initialization and advancement to 0.5 simulated seconds; not the full 1800-second baseline or a performance guarantee."}

    def command(arguments, label):
        argv = [sys.executable, "-m", "zombie_sim.cli", *arguments]
        before = time.monotonic()
        result = subprocess.run(argv, cwd=ROOT,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(ROOT / "src")),
            capture_output=True, text=True, timeout=600)
        (output / f"{label}.log").write_text(result.stdout + "\n" + result.stderr)
        report["commands"].append({"argv": argv, "returncode": result.returncode,
                                   "elapsed_seconds": round(time.monotonic() - before, 3)})
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    try:
        validation = command(["validate", "configs/baseline.toml"], "validate")
        assert validation["valid"]
        manifest = command(["run", "configs/baseline.toml", "--workers", "1", "--until", "0.5",
                            "--output", str(run_dir)], "run")
        assert manifest["status"] == "interrupted" and Fraction(manifest["time"]) == Fraction(1, 2)
        assert Fraction(str(manifest["config"]["horizon"])) == 1800
        assert (run_dir / "checkpoint.json").is_file()
        assert (run_dir / "checkpoint.history.sqlite").is_file()
        history = History(run_dir / "run.sqlite", read_only=True)
        try:
            initial = history.state_at(revision=0)
            final = history.state_at()
            revision = history.revision
            initialization = initial["initialization"]
            agents = list(initial["agents"].values())
            counts = Counter(agent["type"] for agent in agents)
            infected = sum(bool(agent.get("infection_episode")) for agent in agents)
            assert counts == {"Human": 800, "Zombie": 200} and infected == 20
            assert len(final["agents"]) == 1000
            assert initialization["sampler"] == "conditional_relocation_v1"
            assert initialization["approximate"] and initialization["explicit_opt_in"]
            assert manifest["config"]["placement"]["approval"]["approved"]
            # Independent pairwise Euclidean and closed-rectangle checks, without
            # calling the production sampler or its collision predicates.
            minimum_pair = math.inf
            minimum_cross = math.inf
            for index, first in enumerate(agents):
                assert 0 <= first["x"] <= initial["world"]["length"]
                assert 0 <= first["y"] <= initial["world"]["width"]
                for barrier in initial["barriers"].values():
                    kind = barrier.get("type", "Obstacle")
                    blocks = barrier.get("mode", "CLOSED") == "CLOSED" if kind == "Gate" else barrier.get("blocks_movement", True)
                    assert not (blocks and inside(first, barrier["footprint"]))
                if first["type"] == "Zombie":
                    assert not any(inside(first, shelter["interior"], True) for shelter in initial["shelters"].values())
                for second in agents[index + 1:]:
                    distance = math.hypot(float(first["x"]) - float(second["x"]), float(first["y"]) - float(second["y"]))
                    minimum_pair = min(minimum_pair, distance)
                    assert distance >= 2
                    if first["type"] != second["type"]:
                        minimum_cross = min(minimum_cross, distance)
                        assert distance >= 15
            report.update(initial_populations=dict(counts), initial_infected_humans=infected,
                          final_identity_count=len(final["agents"]), time=manifest["time"],
                          revision=revision, initialization=initialization,
                          placement_approval=manifest["config"]["placement"]["approval"],
                          pairwise_constraints_checked=499500,
                          minimum_pair_metres=minimum_pair, minimum_cross_type_metres=minimum_cross,
                          geometry_and_zombie_shelter_exclusion_checked=True,
                          checkpoint_files={p.name: p.stat().st_size for p in run_dir.iterdir() if p.is_file()},
                          process_exited=True, workers_requested=1, status="PASS")
        finally:
            history.close()
    except BaseException as error:
        report.update(status="FAIL", error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        shutil.rmtree(scratch)
        report["temporary_workspace_removed"] = not scratch.exists()
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (output / "verification.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"status": report["status"], "report": str(output / "verification.json")}))


if __name__ == "__main__":
    main()
