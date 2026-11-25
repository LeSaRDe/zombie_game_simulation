"""Measured full-population short-horizon pilot, not a full-horizon benchmark."""
import json
import platform
from pathlib import Path
import resource
import time
from zombie_sim.config import baseline_config
from zombie_sim.engine import Simulation


def main():
    output=Path('artifacts/benchmarks');output.mkdir(parents=True,exist_ok=True)
    config=baseline_config();config['horizon']=5.0
    start=time.perf_counter()
    sim=Simulation(config,history_path=str(output/'baseline_1000_5s.sqlite'),workers=1,backend='memory')
    init_seconds=time.perf_counter()-start
    start=time.perf_counter();sim.advance_until(5,return_snapshot=False);run_seconds=time.perf_counter()-start
    state=sim.snapshot();agents=list(state['agents'].values())
    assert len(agents)==1000 and sum(a['type']=='Human' for a in agents)+sum(a['type']=='Zombie' for a in agents)==1000
    assert all(0<=a['life']<=100 and 0<=a['stamina']<=100 for a in agents)
    actions={}
    for d in sim.decisions:actions[d['intent'].get('action')]=actions.get(d['intent'].get('action'),0)+1
    result={'scenario':'baseline_v0.1 full population, shortened pilot','population':1000,'simulated_seconds':5,
            'complete_1800_second_run':False,'backend':'memory','workers':1,'python':platform.python_version(),
            'initialization_seconds':init_seconds,'execution_seconds':run_seconds,'events':len(sim.events),'revisions':sim.revision,
            'decisions':len(sim.decisions),'actions':actions,'peak_rss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            'population_counts':{key:sum(a['status']==key for a in agents) for key in ('HEALTHY','INFECTED','ACTIVE','DEAD')},
            'config_fingerprint':sim.config['fingerprint'],'placement':sim.config['placement'],'parallel_effect_stats':getattr(sim,'parallel_effect_stats',{})}
    sim.close()
    result['history_bytes']=(output/'baseline_1000_5s.sqlite').stat().st_size
    (output/'baseline_1000_5s.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
