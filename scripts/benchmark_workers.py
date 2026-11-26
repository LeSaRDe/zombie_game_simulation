"""Measure real simulation throughput and canonical worker-count equivalence."""
from __future__ import annotations
import argparse
import hashlib
import json
import resource
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from zombie_sim.engine import Simulation
from zombie_sim.storage import canonical


def run(workers,until,preset,order="native"):
    begin=time.perf_counter()
    sim=Simulation({"preset":preset,"execution":{"workers":workers,"completion_order":order},"checkpoint_interval":1800})
    initialized=time.perf_counter()-begin
    started=time.perf_counter();cpu=time.process_time()
    try:
        sim.advance_until(until,return_snapshot=False)
        elapsed=time.perf_counter()-started
        advance_cpu=time.process_time()-cpu
        # Keep materialization and canonical equivalence hashes outside both
        # advancement timers. Historical reports included this work in CPU only.
        verification_started=time.perf_counter();verification_cpu_started=time.process_time()
        state=sim.snapshot();state.pop("run_id",None);state.pop("scenario_fingerprint",None)
        events=hashlib.sha256(canonical(sim.events).encode()).hexdigest()
        state_hash=hashlib.sha256(canonical(state).encode()).hexdigest()
        verification_elapsed=time.perf_counter()-verification_started
        verification_cpu=time.process_time()-verification_cpu_started
        result={"workers":workers,"order":order,"time":str(sim.time),"revisions":sim.revision,
                "events":len(sim.events),"state_sha256":state_hash,"events_sha256":events,
                "initialization_seconds":initialized,"advance_seconds":elapsed,
                "coordinator_cpu_seconds":advance_cpu,
                "verification_seconds":verification_elapsed,"verification_cpu_seconds":verification_cpu,
                "revisions_per_second":sim.revision/elapsed,
                "peak_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
                "history_bytes":Path(sim.history_path).stat().st_size,"execution":sim.execution_diagnostics()}
        print(json.dumps(result),flush=True)
        return result
    finally:
        sim.close()


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--workers",default="1,2,4,10")
    parser.add_argument("--until",default="5");parser.add_argument("--preset",default="baseline")
    parser.add_argument("--order",default="native");args=parser.parse_args()
    results=[run(int(w),args.until,args.preset,args.order) for w in args.workers.split(",")]
    reference=results[0]
    assert all(r["state_sha256"]==reference["state_sha256"] and r["events_sha256"]==reference["events_sha256"] for r in results),"Worker count changed semantic output"
