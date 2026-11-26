"""Profile a bounded continuation from an actual saved baseline prefix."""
import argparse
import cProfile
from pathlib import Path
import pstats
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zombie_sim.engine import Simulation


def main():
    parser=argparse.ArgumentParser();parser.add_argument('history');parser.add_argument('--workers',type=int,default=1)
    parser.add_argument('--events',type=int,default=1000);parser.add_argument('--seconds',default='5');args=parser.parse_args()
    started=time.perf_counter();sim=Simulation.restore_revision(args.history,workers=args.workers)
    print('Restored',str(sim.time),'revision',sim.revision,'wall_seconds',time.perf_counter()-started,flush=True)
    profiler=cProfile.Profile()
    try:
        start=time.perf_counter();revision=sim.revision;profiler.enable()
        from fractions import Fraction
        sim.advance_until(sim.time+Fraction(args.seconds),max_events=args.events,return_snapshot=False)
        profiler.disable()
        print('Frontier',str(sim.time),'revisions',sim.revision-revision,'wall_seconds',time.perf_counter()-start,flush=True)
        pstats.Stats(profiler).strip_dirs().sort_stats('cumtime').print_stats(30)
    finally:sim.close()


if __name__=='__main__':main()
