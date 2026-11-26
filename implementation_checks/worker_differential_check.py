from copy import deepcopy
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zombie_sim.engine import Simulation


def difference(a,b,path=''):
    if type(a)!=type(b):return path,repr(a)[:180],repr(b)[:180]
    if isinstance(a,dict):
        if a.keys()!=b.keys():return path+'.keys',str(a.keys()),str(b.keys())
        for key in a:
            found=difference(a[key],b[key],path+'/'+str(key))
            if found:return found
    elif isinstance(a,list):
        if len(a)!=len(b):return path+'.length',len(a),len(b)
        for i,(left,right) in enumerate(zip(a,b)):
            found=difference(left,right,path+'/'+str(i))
            if found:return found
    elif a!=b:return path,repr(a)[:180],repr(b)[:180]


def run(workers):
    sim=Simulation({'preset':'baseline','execution':{'workers':workers,'completion_order':'seeded_shuffle'},'checkpoint_interval':1800})
    try:
        sim.advance_until(5,return_snapshot=False)
        state=sim.snapshot();state.pop('run_id',None)
        return state,list(sim.events),sim.execution_diagnostics()
    finally:sim.close()


if __name__=='__main__':
    one,events,_=run(1);twenty,other,metrics=run(20)
    first=difference(one,twenty);second=difference(events,other)
    print({'state_difference':first,'event_difference':second,'active_worker_pids':len(metrics['performance']['worker_cpu_seconds'])},flush=True)
    assert first is None and second is None
