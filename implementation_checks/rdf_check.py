"""Generate and independently SHACL-validate real engine traces.

Uses only the separately authored implementation checks and unchanged ontology;
no supplied acceptance-suite file is imported, read, or executed.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from zombie_sim.engine import Simulation
from zombie_sim.ontology_export import export_history, validate_export
from zombie_sim.registry import provenance
import actions_check

OUTPUT=Path('diagnostics/rdf')
RESULTS={}


def record(name,sim,initial):
    path=OUTPUT/(name+'.ttl')
    export_history([initial,sim.snapshot()],sim.events,path,run_id=name)
    result=validate_export(path,OUTPUT/(name+'.report.txt'))
    RESULTS[name]={"conforms":result['conforms'],"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
                   "actions":sorted({o['action'] for o in sim.occurrences.values()}),
                   "events":len(sim.events),"revision":sim.revision,"time":str(sim.time)}
    print(name,result['conforms'],flush=True)
    if not result['conforms']:
        print(result['report'][:5000],flush=True)


def run(action,actors,parameters=None,target=None,**config):
    sim=actions_check.make(actors,**config)
    try:
        initial=sim.snapshot()
        response=sim.submit_intents({'actor':'1','action':action,'parameters':parameters or {},
                                     **({'target':str(target)} if target is not None else {})})[0]
        assert response['status']=='ADMITTED',response
        occurrence=sim.occurrences[response['occurrence_id']]
        sim.advance_until(occurrence['planned_end'])
        assert occurrence['result'] in ('SUCCEEDED','MISSED'),occurrence['result']
        record(action,sim,initial)
        return sim.snapshot(),deepcopy(occurrence)
    finally:sim.close()


def main():
    OUTPUT.mkdir(parents=True,exist_ok=True)
    actions_check.run=run
    actions_check.main()
    sim=actions_check.make([actions_check.agent(1,'Zombie',life=50),actions_check.agent(2,x=11,life=1)])
    try:
        initial=sim.snapshot()
        for attempt in range(10):
            response=sim.submit_intents({'actor':'1','action':'claw','target':'2'})[0]
            sim.advance_until(sim.occurrences[response['occurrence_id']]['planned_end'])
            if sim.state['remains']:break
            sim.advance_until(sim.state['agents']['1']['cooldowns']['claw'])
        assert sim.state['remains']
        record('death',sim,initial)
        response=sim.submit_intents({'actor':'1','action':'feed','target':next(iter(sim.state['remains']))})[0]
        sim.advance_until(sim.occurrences[response['occurrence_id']]['planned_end'])
        record('feed',sim,initial)
    finally:sim.close()
    for name,action,end in [('conversion',None,300),('cancelled_conversion','pickup',.5)]:
        sim=actions_check.make([actions_check.agent(1,role='DOCTOR',infected=True)],
            horizon=301,incubation_duration=300 if action is None else .5,
            stockpiles=[{'id':'s','x':11,'y':10,'inventory':{'FOOD':1}}])
        try:
            initial=sim.snapshot()
            if action:sim.submit_intents({'actor':'1','action':action,'target':'s','parameters':{'resource':'FOOD','quantity':1}})
            sim.advance_until(end)
            record(name,sim,initial)
        finally:sim.close()
    sim=actions_check.make([actions_check.agent(1,role='DOCTOR'),actions_check.agent(2,x=11,infected=True)],incubation_duration=4)
    try:
        initial=sim.snapshot();sim.submit_intents({'actor':'1','action':'treat_infection','target':'2'});sim.advance_until(4)
        record('treatment_deadline',sim,initial)
    finally:sim.close()
    sim=actions_check.make([actions_check.agent(1,role='WARRIOR'),actions_check.agent(2,'Zombie',x=11)],
                          horizon=4,decision_mode='model')
    try:
        initial=sim.snapshot();sim.advance_until(4)
        record('model_batch',sim,initial)
    finally:sim.close()
    sim=actions_check.make([actions_check.agent(1,'Zombie'),actions_check.agent(2,x=11,life=1)],seed=0)
    try:
        initial=sim.snapshot()
        response=sim.submit_intents({'actor':'2','action':'wait','parameters':{'duration':5}})[0]
        assert response['status']=='ADMITTED',response
        waiting=response['occurrence_id']
        response=sim.submit_intents({'actor':'1','action':'claw','target':'2'})[0]
        assert response['status']=='ADMITTED',response
        sim.advance_until(1)
        assert sim.state['agents']['2']['life']==0
        assert sim.occurrences[waiting]['result']=='CANCELLED_BY_DEATH'
        record('busy_death',sim,initial)
    finally:sim.close()
    (OUTPUT/'manifest.json').write_text(json.dumps({"scope":"actual public-engine action/lifecycle traces; original baseline v0.1 SHACL", "source_provenance":provenance(), "results":RESULTS},indent=2)+'\n')
    assert all(r['conforms'] for r in RESULTS.values()),[name for name,r in RESULTS.items() if not r['conforms']]
    print(f'{len(RESULTS)} actual engine RDF traces conform to unchanged baseline SHACL.',flush=True)


if __name__=='__main__':main()
