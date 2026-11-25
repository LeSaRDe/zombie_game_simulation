"""Actual independent completion effects: process equivalence and stale fallback."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from zombie_sim.engine import Simulation


class StalePreparedSimulation(Simulation):
    def _prepare_completions(self,current):
        old=getattr(self,'_prepared_boundary',None)
        super()._prepare_completions(current)
        if old!=self.time and self._prepared_effects:
            next(iter(self._prepared_effects.values()))['fingerprint']='deliberately-stale'


def config():
    agents=[]
    for i in range(4):
        x=10+i*20
        agents.append({'id':f'd{i}','type':'Human','role':'DOCTOR','x':x,'y':10,'inventory':{'MEDICAL_SUPPLY':1}})
        agents.append({'id':f'p{i}','type':'Human','x':x+1,'y':10,'life':40})
    return {'scenario':'parallel_effect_check_v1','seed':20261106,'horizon':4,'world':{'length':100,'width':40},
            'placement':{'minimum_separation':0,'cross_type_separation':0},'agents':agents}


def run(workers,stale=False):
    sim=(StalePreparedSimulation if stale else Simulation)(config(),workers=workers,decision_mode='scripted')
    outcomes=sim.submit_intents([{'actor':f'd{i}','action':'first_aid','target':f'p{i}','parameters':{}} for i in range(4)])
    assert all(r['status']!='REJECTED' for r in outcomes),outcomes
    sim.advance_until(3)
    final=sim.snapshot();final.pop('run_id',None)
    events=deepcopy(sim.events);stats=deepcopy(sim.parallel_effect_stats)
    assert all(final['agents'][f'p{i}']['life']==68 for i in range(4)),final['agents']
    assert all(final['agents'][f'd{i}']['inventory']['MEDICAL_SUPPLY']==0 for i in range(4))
    sim.close();return final,events,stats


def main():
    serial,events,stats1=run(1)
    summaries={'1':stats1}
    for count in (2,4):
        state,records,stats=run(count)
        assert state==serial,f'{count}-process final state changed'
        assert records==events,f'{count}-process semantic ledger changed'
        assert stats['worker_batches']==1 and stats['consumed']==4 and stats['fallback']==0,stats
        summaries[str(count)]=stats
    state,records,stats=run(2,True)
    assert state==serial and records==events,'Stale read fallback changed semantics'
    assert stats['fallback']==1 and stats['consumed']==3,stats
    summaries['stale_fallback']=stats
    result={'workers':[1,2,4],'same_semantic_ledger':True,'same_final_state':True,'stale_fingerprint_serial_fallback':True,'statistics':summaries,'excluded_run_identity':'run_id (distinct realizations)',
            'event_digest':hashlib.sha256(json.dumps(events,sort_keys=True).encode()).hexdigest()}
    Path('artifacts/model_checks/effect_parallel.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
