"""Independent ontology-driven end-to-end action checks through public intents."""
from copy import deepcopy
from zombie_sim.engine import Simulation
from zombie_sim.registry import ACTIONS


def agent(identifier,kind='Human',role=None,x=10,y=10,**values):
    return dict(id=str(identifier),type=kind,role=role,x=x,y=y,**values)


def make(agents,**config):
    return Simulation({'agents':agents,'world':{'length':100,'width':100},'placement':{'minimum_separation':0,'cross_type_separation':0},'seed':20261106,'horizon':60,'decision_mode':'scripted',**config})


def gate(mode='CLOSED',integrity=200):
    barriers=[{'id':'g','type':'Gate','shelter_id':'s','footprint':[24,20,26,21],'mode':mode,'integrity':integrity,'max_integrity':200}]
    for name,fp in [('n',[20,29,30,30]),('w',[20,21,21,29]),('e',[29,21,30,29]),('sw',[20,20,24,21]),('se',[26,20,30,21])]:
        barriers.append({'id':name,'type':'Obstacle','footprint':fp})
    return {'barriers':barriers,'shelters':[{'id':'s','interior':[21,21,29,29],'walls':['n','w','e','sw','se'],'gates':['g']}]}


def run(action,actors,parameters=None,target=None,**cfg):
    sim=make(actors,**cfg)
    try:
        result=sim.submit_intents([{'actor':'1','action':action,'parameters':parameters or {},**({'target':str(target)} if target is not None else {})}])[0]
        assert result['status']=='ADMITTED',(action,result,sim.intents[result['id']].get('audit_reason'))
        occurrence=sim.occurrences[result['occurrence_id']]
        sim.advance_until(occurrence['planned_end'])
        assert occurrence['result'] in ('SUCCEEDED','MISSED'),(action,occurrence['result'],occurrence.get('audit_reason'))
        assert not sim.state['reservations'],action
        assert sim.state['agents']['1']['active_action'] is None,action
        assert occurrence.get('actor_start') and occurrence.get('actor_after_start') and occurrence.get('actor_before_end') and occurrence.get('actor_after_end')
        return sim.snapshot(),deepcopy(occurrence)
    finally:
        sim.close()


def main():
    covered=set()
    for name in ('wait','rest'):
        s,o=run(name,[agent(1,stamina=50)],{'duration':2});covered.add(name)
        assert s['agents']['1']['stamina']==(58 if name=='rest' else 50)
    s,o=run('move',[agent(1)],{'duration':1,'path':[{'x':10,'y':10,'offset':0},{'x':12,'y':10,'offset':1}]});covered.add('move');assert s['agents']['1']['x']==12
    s,o=run('dash',[agent(1,'Zombie','RUNNER')],{'duration':1,'path':[{'x':10,'y':10,'offset':0},{'x':14,'y':10,'offset':1}]});covered.add('dash');assert abs(s['agents']['1']['stamina']-87.68)<1e-9
    for name,kind,role in [('melee','Human',None),('power_strike','Human','WARRIOR'),('claw','Zombie',None),('bite','Zombie',None),('spit','Zombie','SPITTER')]:
        s,o=run(name,[agent(1,kind,role),agent(2,'Zombie' if kind=='Human' else 'Human',x=11)],target='2');covered.add(name)
        assert s['agents']['2']['life']<100 or o['result']=='MISSED'
        if name=='spit':assert s['agents']['1']['spit_charges']==2
    for name in ('signal','scream'):
        s,o=run(name,[agent(1,'Zombie','SCREAMER') if name=='scream' else agent(1)],{});covered.add(name);assert len(s['signals'])==1
    s,o=run('mark_target',[agent(1,role='SCOUT'),agent(2,'Zombie',x=15)],target='2');covered.add('mark_target');assert len(s['signals'])==1
    s,o=run('pickup',[agent(1)],{'resource':'FOOD','quantity':2},target='stock',stockpiles=[{'id':'stock','x':11,'y':10,'inventory':{'FOOD':2}}]);covered.add('pickup');assert s['agents']['1']['inventory']['FOOD']==2 and s['stockpiles']['stock']['inventory']['FOOD']==0
    s,o=run('drop',[agent(1,inventory={'FOOD':2})],{'resource':'FOOD','quantity':1});covered.add('drop');assert s['agents']['1']['inventory']['FOOD']==1 and sum(p['inventory']['FOOD'] for p in s['stockpiles'].values())==1
    s,o=run('transfer',[agent(1,inventory={'FOOD':2}),agent(2,x=11)],{'resource':'FOOD','quantity':1},target='2');covered.add('transfer');assert s['agents']['1']['inventory']['FOOD']==1 and s['agents']['2']['inventory']['FOOD']==1
    s,o=run('eat',[agent(1,hunger=40,inventory={'FOOD':1})]);covered.add('eat');assert abs(s['agents']['1']['hunger']-.1)<1e-9
    s,o=run('first_aid',[agent(1,inventory={'MEDICAL_SUPPLY':1}),agent(2,x=11,life=50)],target='2');covered.add('first_aid');assert s['agents']['2']['life']==64
    s,o=run('treat_infection',[agent(1,role='DOCTOR'),agent(2,x=11,infected=True)],target='2');covered.add('treat_infection');assert s['agents']['2']['infection_episode'] is None and next(iter(s['episodes'].values()))['outcome']=='CURED'
    s,o=run('prophylaxis',[agent(1,role='DOCTOR')],target='1');covered.add('prophylaxis');assert s['agents']['1']['infection_resistance_effective']==.8
    for name,role,key,value in [('guard','WARRIOR','damage_resistance',.6),('recon','SCOUT','sense_r',85)]:
        s,o=run(name,[agent(1,role=role)]);covered.add(name);assert s['agents']['1'][key]==value
    s,o=run('rally',[agent(1,'Zombie','TYRANT'),agent(2,'Zombie',x=12)]);covered.add('rally');assert s['agents']['2']['rally_bonus']==.1
    s,o=run('build_barricade',[agent(1,role='ENGINEER',inventory={'MATERIAL':2})],{'center':{'x':11.5,'y':10},'orientation':'y','length':2});covered.add('build_barricade');assert len(s['barriers'])==1 and s['agents']['1']['inventory']['MATERIAL']==0
    s,o=run('repair_barrier',[agent(1,role='ENGINEER',inventory={'MATERIAL':1})],target='b',barriers=[{'id':'b','type':'Barricade','footprint':[11,9,12,11],'integrity':40,'max_integrity':100,'creator_id':'1'}]);covered.add('repair_barrier');assert s['barriers']['b']['integrity']==100
    for name,kind,role,mode in [('open_gate','Human',None,'CLOSED'),('close_gate','Human',None,'OPEN'),('smash','Zombie',None,'CLOSED'),('demolish','Zombie','TYRANT','CLOSED')]:
        s,o=run(name,[agent(1,kind,role,x=25,y=19)],target='g',**gate(mode));covered.add(name)
        assert s['barriers']['g']['mode']==('OPEN' if name=='open_gate' else 'CLOSED')
        if name in ('smash','demolish'):assert s['barriers']['g']['integrity']==(180 if name=='smash' else 140)
    sim=make([agent(1,'Zombie',life=50),agent(2,x=11,life=1)])
    try:
        for attempt in range(10):
            r=sim.submit_intents({'actor':'1','action':'claw','target':'2'})[0]
            assert r['status']=='ADMITTED',r
            sim.advance_until(sim.occurrences[r['occurrence_id']]['planned_end'])
            if sim.state['remains']:break
            sim.advance_until(sim.state['agents']['1']['cooldowns']['claw'])
        assert sim.state['remains']
        rid=next(iter(sim.state['remains']))
        r=sim.submit_intents({'actor':'1','action':'feed','target':rid})[0];assert r['status']=='ADMITTED',r
        end=sim.occurrences[r['occurrence_id']]['planned_end'];sim.advance_until(end)
        assert sim.state['remains'][rid]['biomass']==3 and sim.state['agents']['1']['life']==58
        covered.add('feed')
    finally:sim.close()
    assert covered==set(ACTIONS),(set(ACTIONS)-covered)
    print('All 29 actions passed independent public-admission/completion checks.')

def boundaries():
    from fractions import Fraction
    from tempfile import TemporaryDirectory
    from pathlib import Path
    sim=make([agent(1),agent(2,x=10,y=11)],stockpiles=[{'id':'s','x':10.5,'y':10,'inventory':{'FOOD':1}}])
    try:
        responses=sim.submit_intents([{'actor':str(i),'action':'pickup','target':'s','parameters':{'resource':'FOOD','quantity':1}} for i in (1,2)])
        assert sorted(r['status'] for r in responses)==['ADMITTED','REJECTED']
        loser=next(r['actor'] for r in responses if r['status']=='REJECTED')
        assert sim.state['agents'][loser]['stamina']==100
        sim.advance_until(1)
        assert sum(a['inventory']['FOOD'] for a in sim.state['agents'].values())==1
        assert not sim.state['reservations']
    finally:sim.close()
    sim=make([agent(1),agent(2,'Zombie',x=11)],seed=19)
    try:
        results=sim.submit_intents([{'actor':'1','action':'melee','target':'2'},{'actor':'2','action':'claw','target':'1'}])
        sim.advance_until(1)
        assert sorted(sim.occurrences[r['occurrence_id']]['result'] for r in results)==['CANCELLED_BY_CONFLICT','MISSED']
        assert all(a['life']==100 and a['stamina']==94 for a in sim.state['agents'].values())
        assert sum(draw['channel']=='hit' for draw in sim.random_draws)==1
    finally:sim.close()
    sim=make([agent(1,role='SCOUT',profile={'base_sense_r':.5,'recon_duration':.5}),agent(2,'Zombie',x=11)])
    try:
        sim.submit_intents({'actor':'1','action':'recon'});sim.advance_until(2)
        results=sim.submit_intents([{'actor':'1','action':'melee','target':'2'},{'actor':'2','action':'bite','target':'1'}])
        assert all(r['status']=='ADMITTED' for r in results)
        sim.advance_until(3)
        assert sim.occurrences[results[0]['occurrence_id']]['result']=='FAILED_PRECONDITION'
        assert sim.occurrences[results[1]['occurrence_id']]['result']=='IN_PROGRESS'
        sim.advance_until('7/2')
        assert sim.occurrences[results[1]['occurrence_id']]['result'] in ('SUCCEEDED','MISSED')
    finally:sim.close()
    sim=make([agent(1,role='DOCTOR'),agent(2,x=11,infected=True)],incubation_duration=4)
    try:
        r=sim.submit_intents({'actor':'1','action':'treat_infection','target':'2'})[0]
        sim.advance_until(4)
        assert sim.state['agents']['2']['type']=='Zombie'
        assert sim.occurrences[r['occurrence_id']]['result']=='FAILED_PRECONDITION'
        assert sim.state['agents']['1']['inventory']['MEDICAL_SUPPLY']==1
        assert not sim.state['reservations']
    finally:sim.close()
    sim=make([agent(1,role='DOCTOR',infected=True)],incubation_duration=.5,stockpiles=[{'id':'s','x':11,'y':10,'inventory':{'FOOD':1}}])
    try:
        r=sim.submit_intents({'actor':'1','action':'pickup','target':'s','parameters':{'resource':'FOOD','quantity':1}})[0]
        sim.advance_until(1)
        assert sim.occurrences[r['occurrence_id']]['result']=='CANCELLED_BY_CONVERSION'
        assert sim.state['stockpiles']['s']['inventory']['FOOD']==1
        assert not sim.state['reservations']
        assert sum(p['inventory']['MEDICAL_SUPPLY'] for p in sim.state['stockpiles'].values())==1
    finally:sim.close()
    sim=make([agent(1),agent(2,'Zombie',x=90,y=90)],barriers=[{'id':'b','type':'Obstacle','footprint':[11,9,13,11]}])
    try:
        r=sim.submit_intents({'actor':'1','action':'move','parameters':{'duration':2,'path':[{'x':10,'y':10,'offset':0},{'x':14,'y':10,'offset':2}]}})[0]
        assert r['status']=='REJECTED' and sim.state['agents']['1']['stamina']==100
        sim.memories['1']={'sightings':{'2':{'entity':{'id':'2','x':90,'y':90},'seen_at':0}}}
        r=sim.submit_intents({'actor':'1','action':'signal','parameters':{'kind':'WARNING','payload':{'entity_id':'2','position':{'x':90,'y':90},'observed_at':0}}})[0]
        assert r['status']=='REJECTED'
    finally:sim.close()
    sim=make([agent(1,role='ENGINEER',inventory={'MATERIAL':2})],barriers=[{'id':'b','type':'Obstacle','footprint':[10.5,9.9,10.6,10.1]}])
    try:
        r=sim.submit_intents({'actor':'1','action':'build_barricade','parameters':{'center':{'x':11.5,'y':10},'orientation':'y','length':8}})[0]
        assert r['status']=='REJECTED'
    finally:sim.close()
    sim=make([agent(1,role='ENGINEER',x=25,y=19,profile={'repair_amount':0},inventory={'MATERIAL':1})],**gate('BREACHED',0))
    try:
        r=sim.submit_intents({'actor':'1','action':'repair_barrier','target':'g'})[0]
        assert r['status']=='ADMITTED',r
        sim.advance_until(sim.occurrences[r['occurrence_id']]['planned_end'])
        assert sim.state['barriers']['g']['integrity']==0 and sim.state['barriers']['g']['mode']=='BREACHED'
    finally:sim.close()
    with TemporaryDirectory() as directory:
        sim=make([agent(1)])
        clone=None
        try:
            sim.submit_intents({'actor':'1','action':'move','parameters':{'duration':2,'path':[{'x':10,'y':10,'offset':0},{'x':14,'y':10,'offset':2}]}})
            sim.advance_until('1/2')
            path=sim.checkpoint(Path(directory)/'busy.json')
            clone=Simulation.restore(path,backend='sqlite')
            sim.advance_until(2);clone.advance_until(2)
            assert sim.state==clone.state and sim.queue==clone.queue and sim.events==clone.events
        finally:
            if clone:clone.close()
            sim.close()
    print('Boundary checks passed: contention, winning miss, invalid-first reciprocity, deadline precedence, conversion release/drop, collision, knowledge provenance, footprint visibility, busy checkpoint continuation.')

if __name__=='__main__':
    main()
    boundaries()

