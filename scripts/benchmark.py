"""Measured pilot runs with complete history; no acceptance-suite dependency."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import platform
import resource
import time

from zombie_sim import Simulation
from zombie_sim.storage import History
from zombie_sim.visualization import populations


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--until",type=float,default=5)
    parser.add_argument("--output",required=True)
    parser.add_argument("--workers",type=int,default=1)
    parser.add_argument("--backend",choices=("memory","sqlite"),default="memory")
    args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    if (output/"run.sqlite").exists():raise ValueError("Choose a fresh benchmark directory")
    report={"config":args.config,"target_time":args.until,"workers":args.workers,"backend":args.backend,
            "platform":platform.platform(),"python":platform.python_version(),"cpu_count":os.cpu_count(),
            "scope":"Measured pilot; no inference of a completed full baseline"}
    start=time.perf_counter()
    sim=Simulation(args.config,history_path=output/"run.sqlite",workers=args.workers,backend=args.backend)
    report["initialization_seconds"]=time.perf_counter()-start
    report["initialization"]=sim.state.get("initialization")
    report["scenario_fingerprint"]=sim.state.get("scenario_fingerprint")
    start=time.perf_counter()
    cursor=0.
    try:
        while cursor<args.until and sim.run_status!="COMPLETED":
            cursor=min(args.until,cursor+5)
            sim.advance_until(cursor,return_snapshot=False)
            progress={"time":str(sim.time),"revision":sim.revision,
                      "elapsed_seconds":time.perf_counter()-start,
                      "max_rss_mib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024}
            print(json.dumps(progress),flush=True)
        elapsed=time.perf_counter()-start
        report.update(actual_time=str(sim.time),revision=sim.revision,events=len(sim.events),decisions=len(sim.decisions),
                      random_draws=len(sim.random_draws),execution_seconds=elapsed,
                      simulated_seconds_per_wall_second=float(sim.time)/elapsed,
                      committed_events_per_second=len(sim.events)/elapsed,
                      populations=populations(sim.snapshot()),run_status=sim.run_status,
                      peak_rss_mib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024)
        start_checkpoint=time.perf_counter();checkpoint=sim.checkpoint(output/"checkpoint.json")
        report["checkpoint_seconds"]=time.perf_counter()-start_checkpoint
        report["checkpoint_bytes"]=Path(checkpoint).stat().st_size
        report["parallel"]=getattr(sim,"_parallel_telemetry",{})
    finally:sim.close()
    report["history_bytes"]=(output/"run.sqlite").stat().st_size
    history=History(output/"run.sqlite",read_only=True)
    try:
        begin=time.perf_counter()
        history.state_at(time=args.until/2)
        report["midpoint_reconstruction_seconds"]=time.perf_counter()-begin
    finally:history.close()
    (output/"summary.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report,indent=2),flush=True)


if __name__=="__main__":main()
