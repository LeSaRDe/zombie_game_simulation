"""Independent live adapter/optimizer checks; no acceptance-suite imports."""
from copy import deepcopy
import json
import math
import random
from pathlib import Path
import numpy as np
import gymnasium
from pettingzoo import AECEnv
from zombie_sim.learning import ControlledAgentEnv, DecisionBatchAEC, LearnedModel, build_network, reward_terms
from zombie_sim.policies import generate_candidates, select_utility_index


def scenario(horizon=3,**extra):
    base={'scenario':'adapter_check_v1','world':{'length':40,'width':40},'horizon':horizon,
          'placement':{'minimum_separation':0,'cross_type_separation':0},
          'agents':[{'id':'1','type':'Human','x':10,'y':10},{'id':'2','type':'Human','x':12,'y':10},{'id':'3','type':'Zombie','x':30,'y':30}]}
    base.update(extra);return base


def wait_index(env):
    return next(i for i,c in enumerate(env.current_candidates) if c.intent['action']=='wait')


def main():
    results={}
    before={"life":100,"type":"Human"}
    event={"kind":"action_completed","time":"3","actor":"1","target":"2","action":"first_aid","outcome":"SUCCEEDED","occurrence":"occ"}
    terms=reward_terms([event],"1","Human",0,3,before,before,{"occ":{"healing":28}})
    assert math.isclose(sum(t["value"] for t in terms),.31)
    terms=reward_terms([dict(event,action="treat_infection")],"1","Human",0,3,before,before,{"occ":{"cure":True}})
    assert math.isclose(sum(t["value"] for t in terms),2.03)
    results["actual_healing_and_cure_rewards"]=True
    env=ControlledAgentEnv(scenario(),actor_id='1',decision_limit=1)
    assert isinstance(env,gymnasium.Env)
    obs,info=env.reset(seed=101);assert env.observation_space.contains(obs)
    obs2,reward,term,trunc,info=env.step(wait_index(env))
    assert not term and trunc and info['elapsed']>0 and obs2['action_mask'].sum()>0
    assert env.observation_space.contains(obs2)
    results['external_truncation_bootstrap_observation']=True;env.close()
    report_cfg=scenario(horizon=20)
    report_cfg['agents']=[{'id':'1','type':'Human','x':10,'y':10,'infected':True}]
    env=ControlledAgentEnv(report_cfg,actor_id='1')
    obs,_=env.reset(seed=101)
    report=next(i for i,c in enumerate(env.current_candidates) if c.intent['action']=='signal')
    env.step(report)
    assert env.memories['1']['last_reports']['help']==0
    env.step(wait_index(env));env.step(wait_index(env))
    assert not any(c.intent['action']=='signal' for c in env.current_candidates), 'Utility report cadence was lost by adapter'
    results['selected_action_memory_committed']=True;env.close()
    env=ControlledAgentEnv(scenario(horizon=2),actor_id='1')
    obs,_=env.reset(seed=101)
    for _ in range(10):
        obs,reward,term,trunc,info=env.step(wait_index(env))
        if term:break
    assert term and not trunc and info['termination_reason']=='task_horizon'
    results['finite_horizon_termination']=True;env.close()
    cfg=scenario(horizon=5,incubation_duration=1)
    cfg['agents'][0]['infected']=True
    env=ControlledAgentEnv(cfg,actor_id='1')
    obs,_=env.reset(seed=101)
    obs,reward,term,trunc,info=env.step(wait_index(env))
    assert term and not trunc and info['termination_reason']=='conversion'
    assert any(t['name']=='human_episode_end' and t['value']==-10 for t in info['reward_terms'])
    results['conversion_controller_episode_end']=True
    run_id=env.sim.state['run_id'];old_episode=info['controller_episode_id']
    obs,info=env.reset(options={'continue_identity':'1','family':'Zombie'})
    assert env.sim.state['run_id']==run_id and str(env.sim.time)=='1' and info['controller_episode_id']!=old_episode
    assert env.memories['1']['type']=='Zombie' and env.retired_controller_memories[0]['memory']['type']=='Human'
    obs,reward,term,trunc,info=env.step(wait_index(env))
    assert not term and not trunc and info['time']==2
    results['new_zombie_controller_same_identity']=True;env.close()
    aec=DecisionBatchAEC(scenario(),controlled_ids=['1','2'])
    assert isinstance(aec,AECEnv)
    aec.reset(seed=101)
    assert aec.agents==['1','2']
    before_revision=aec._env.sim.revision
    second=deepcopy(aec.observe('2'))
    first=aec.agent_selection
    action=next(i for i,c in enumerate(aec._candidates[first]) if c.intent['action']=='wait')
    aec.step(action)
    assert aec._env.sim.revision==before_revision,'First AEC submission leaked into simultaneous batch'
    assert all(np.array_equal(second[k],aec.observe('2')[k]) for k in second)
    for who in aec.agent_iter(max_iter=100):
        obs,reward,term,trunc,info=aec.last()
        assert aec.observation_space(who).contains(obs)
        action=None if term or trunc else next(i for i,c in enumerate(aec._candidates[who]) if c.intent['action']=='wait')
        aec.step(action)
    assert not aec.agents,'AEC failed to retire terminal controllers'
    results['aec_frozen_batch_and_dead_steps']=True;aec.close()
    dense=scenario(horizon=4)
    dense['agents']=[dict(id='doctor',type='Human',role='DOCTOR',x=10,y=10)]
    dense['agents'] += [dict(id=f'p{i:03}',type='Human',x=11,y=10,life=99,stamina=0) for i in range(130)]
    dense['agents'] += [dict(id='urgent',type='Human',x=11,y=10,life=10,stamina=0)]
    env=ControlledAgentEnv(dense,actor_id='doctor');env.reset(seed=1)
    full=generate_candidates(env.raw_observation,env.memories['doctor'])
    chosen=full[select_utility_index(full,random.Random(1))]
    assert len(full)>128 and chosen.intent['target']=='urgent'
    _,_,diagnostics=LearnedModel(build_network()).decide(env.raw_observation,None,random.Random(1))
    assert diagnostics['candidate_count']==128
    _,_,_,_,info=env.step_intent(chosen.intent,reason=chosen.reason)
    assert info['intent']['target']=='urgent' and env.sim.state['agents']['urgent']['life']==38
    results['dense_full_baseline_and_learned_cap']=True;env.close()
    Path('artifacts/model_checks').mkdir(parents=True,exist_ok=True)
    Path('artifacts/model_checks/adapters.json').write_text(json.dumps(results,indent=2)+'\n')
    print(json.dumps(results,sort_keys=True))

if __name__=='__main__':main()
