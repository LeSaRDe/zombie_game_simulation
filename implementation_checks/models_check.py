"""Independently authored implementation checks; does not import acceptance suites."""
from copy import deepcopy
import json
from pathlib import Path
import random
from zombie_sim.domain import make_agent, profile, status
from zombie_sim.policies import ACTION_NAMES, choose, initialize_memory, generate_candidates
from zombie_sim.learning import semi_markov_gae, discounted_interval_reward, encode_observation


def agent(i=1,kind='Human',role=None,**kwargs):
    a=make_agent(str(i),kind,role,x=18.5,y=20,**kwargs);a.update(profile(a));a['status']=status(a);return a

def observation(a,neighbors=(),barriers=(),stocks=(),remains=()):
    return {'time':'0','world':{'length':100,'width':100},'self_state':a,'local_agents':{b['id']:b for b in neighbors},
            'local_environment':{'barriers':{b['id']:b for b in barriers},'stockpiles':{b['id']:b for b in stocks},'remains':{b['id']:b for b in remains}},'received_signals':[]}

def build_cases():
    cases={};h=lambda **kw:agent(**kw)
    def enemy(**kw):
        v=agent(2,'Zombie');v.update(x=19.5,y=20,**kw);return v
    def human(**kw):
        v=agent(2,'Human');v.update(x=19.5,y=20,**kw);return v
    gate={'id':'gate','type':'Gate','footprint':[20,19,21,21],'mode':'CLOSED','integrity':200,'max_integrity':200}
    stock={'id':'supplies','x':19,'y':20,'inventory':{'FOOD':4,'MEDICAL_SUPPLY':4,'MATERIAL':4}}
    cases['move']=observation(h())
    ally=agent(3);ally['current_action']='open_gate';cases['wait']=observation(h(),[ally])
    cases['rest']=observation(h(stamina=3))
    cases['signal']=observation(h(infection_episode='ep'))
    cases['melee']=observation(h(),[enemy(life=5)])
    a=h(role='DOCTOR');a['inventory']['MEDICAL_SUPPLY']=0;cases['pickup']=observation(a,stocks=[stock])
    a=h(carry_capacity=1,inventory={'MATERIAL':1});cases['drop']=observation(a,stocks=[stock])
    a=h(inventory={'MEDICAL_SUPPLY':1});b=agent(3,role='DOCTOR');b['inventory']['MEDICAL_SUPPLY']=0;cases['transfer']=observation(a,[b])
    cases['eat']=observation(h(hunger=95,inventory={'FOOD':1}))
    cases['first_aid']=observation(h(life=25,inventory={'MEDICAL_SUPPLY':1}))
    cases['open_gate']=observation(h(),barriers=[gate])
    e=enemy();e['x']=30;cases['close_gate']=observation(h(),[e],barriers=[dict(gate,mode='OPEN')])
    z=agent(kind='Zombie');cases['claw']=observation(z,[human(status='INFECTED')])
    cases['bite']=observation(z,[human()])
    cases['feed']=observation(agent(kind='Zombie',life=30),remains=[{'id':'body','x':19,'y':20,'biomass':4}])
    cases['smash']=observation(z,barriers=[dict(gate,integrity=20)])
    cases['treat_infection']=observation(h(role='DOCTOR',infection_episode='ep'))
    e=enemy();e['x']=30.5;b=agent(3);b['x']=19;cases['prophylaxis']=observation(h(role='DOCTOR'),[b,e])
    cases['power_strike']=observation(h(role='WARRIOR'),[enemy(life=30)])
    e=enemy();e['x']=22.5;cases['guard']=observation(h(role='WARRIOR'),[e])
    cases['recon']=observation(h(role='SCOUT'))
    e=enemy();e['x']=45;cases['mark_target']=observation(h(role='SCOUT'),[e])
    e=enemy();e['x']=30;cases['build_barricade']=observation(h(role='ENGINEER',inventory={'MATERIAL':2}),[e],barriers=[dict(gate,mode='BREACHED',integrity=0)])
    cases['repair_barrier']=observation(h(role='ENGINEER'),barriers=[dict(gate,integrity=20)])
    e=human();e['x']=30;allies=[agent(i,'Zombie') for i in range(3,6)];cases['rally']=observation(agent(kind='Zombie',role='TYRANT'),[e]+allies)
    cases['demolish']=observation(agent(kind='Zombie',role='TYRANT'),barriers=[dict(gate,integrity=100)])
    cases['dash']=observation(agent(kind='Zombie',role='RUNNER'),[e])
    cases['spit']=observation(agent(kind='Zombie',role='SPITTER'),[e])
    cases['scream']=observation(agent(kind='Zombie',role='SCREAMER'),[e])
    return cases


def main():
    outcomes=[]
    for expected,obs in build_cases().items():
        before=deepcopy(obs);intent,memory,diag=choose(obs,None,random.Random(12))
        assert obs==before,'Policy mutated observation'
        assert len(encode_observation(obs,memory))==32
        json.dumps(memory,allow_nan=False)
        assert choose(obs,None,random.Random(12))[0]==intent,'Seeded decision changed'
        outcomes.append({'expected':expected,'selected':intent['action'],'reason':diag['reason'],'score':diag['chosen_score'],'passed':intent['action']==expected})
    assert set(x['expected'] for x in outcomes)==set(ACTION_NAMES)
    zero=agent(stamina=50,profile={'rest_rate':0})
    candidates=generate_candidates(observation(zero))
    assert candidates and all(c.intent['action']!='rest' for c in candidates), 'Zero recovery rate must not divide by zero or promise recovery'
    advantages,returns=semi_markov_gae([1,2],[.3,.4],[.4,5],[2,3],[False,False],[False,True])
    assert abs(advantages[-1]-(2+.99**3*5-.4))<1e-12,'Truncation failed bootstrap'
    terminal,_=semi_markov_gae([2],[.4],[5],[3],[True],[False]);assert abs(terminal[0]-1.6)<1e-12
    whole=discounted_interval_reward([{'rate':.01,'duration':5}],5)
    split=discounted_interval_reward([{'rate':.01,'duration':2}],2)+.99**2*discounted_interval_reward([{'rate':.01,'duration':3}],3)
    assert abs(whole-split)<1e-12,'Time-integrated reward changed under subdivision'
    Path('artifacts/model_checks').mkdir(parents=True,exist_ok=True)
    Path('artifacts/model_checks/action_choices.json').write_text(json.dumps(outcomes,indent=2)+'\n')
    for row in outcomes:
        if not row['passed']:print(row['expected'],row['selected'],row['passed'])
    assert all(row['passed'] for row in outcomes),'See action_choices.json for mismatches'
    print('29 action choices, deterministic memory, observation isolation, time discount and bootstrap checks passed.')

if __name__=='__main__':main()
