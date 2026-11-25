"""Independent specification checks; intentionally does not import the supplied suite."""
from copy import deepcopy
from pathlib import Path
from zombie_sim.config import ConfigError, PlacementError, baseline_config, initialize_world, resolve_config, validate_connectivity
from zombie_sim.domain import make_agent, profile
from zombie_sim.geometry import contains, distance_to, point_blocked, route, segment_clear
from zombie_sim.ontology_export import export_snapshot
from zombie_sim.registry import ACTIONS, MANIFEST, ROLES, provenance


def run():
    assert set(ACTIONS)==set(MANIFEST['actions']) and len(ACTIONS)==29
    assert set(ROLES)==set(MANIFEST['roles']) and len(ROLES)==8
    assert provenance()['ontology_source_matches_manifest']
    barrier={'id':'wall','type':'Obstacle','footprint':[4,0,6,8]}
    assert point_blocked((4,2),[barrier])
    assert not segment_clear((0,8),(10,8),[barrier])
    assert not segment_clear((0,5),(10,5),[{'footprint':[4,0,6,8]}])
    assert distance_to((0,2),barrier)==4
    path=route((1,1),(9,1),[barrier],{'length':10,'width':10})
    assert len(path)>1
    for start,end in zip([(1,1)]+path,path):
        assert segment_clear(start,end,[barrier])
    assert not route((1,1),(9,1),[{'id':'wall','footprint':[4,0,6,10]}],{'length':10,'width':10})
    runner=make_agent('1','Zombie','RUNNER')
    assert profile(runner)['speed']==3.2
    runner['active_action']={'action':'dash'}
    assert abs(profile(runner)['speed']-4.8)<1e-12
    warrior=make_agent('2','Human','WARRIOR',effects={'g':{'kind':'guard','value':.6,'start_at':'1','end_at':'5'}})
    assert profile(warrior,'4')['damage_resistance']==.6
    assert profile(warrior,'5')['damage_resistance']==.2
    state=initialize_world('configs/small.toml')
    assert state==initialize_world('configs/small.toml')
    assert len(state['agents'])==24 and len(state['episodes'])==1
    agents=list(state['agents'].values())
    for i,a in enumerate(agents):
        for b in agents[i+1:]:
            assert distance_to(a,b)>=(15 if a['type']!=b['type'] else 2)
    export_snapshot(state,'/tmp/zombie-domain-check.ttl')
    config=baseline_config()
    assert len(config['barriers'])==28 and len(config['shelters'])==4 and len(config['stockpiles'])==10
    assert config['population']['humans']==800 and config['population']['zombies']==200
    totals={r:sum(s['inventory'].get(r,0) for s in config['stockpiles']) for r in ('FOOD','MEDICAL_SUPPLY','MATERIAL')}
    totals['MEDICAL_SUPPLY']+=config['population']['human_roles']['DOCTOR']
    totals['MATERIAL']+=config['population']['human_roles']['ENGINEER']
    assert totals=={'FOOD':600,'MEDICAL_SUPPLY':280,'MATERIAL':400}
    validate_connectivity(config)
    invalid=[{'world':{'length':0}}, {'population':{'infected':17}}, {'placement':{'sampler':'relocation'}}, {'profiles':{'Human':{'medical_skill':1.1}}}, {'world':{'boundary_policy':'WRAP'}}, {'population':{'human_roles':{'TYRANT':1}}}]
    for draft in invalid:
        try: resolve_config(draft)
        except ConfigError: pass
        else: raise AssertionError(f'Invalid scenario accepted: {draft}')
    try:
        initialize_world({'world':{'length':1,'width':1},'population':{'humans':2,'zombies':0},'placement':{'max_attempts':2}})
    except PlacementError as exc:
        assert 'No fallback' in str(exc)
    else:
        raise AssertionError('Impossible constrained placement accepted')
    changed=initialize_world({'agents':[{'id':'1','type':'Human','role':'SCOUT','x':20,'y':20}], 'profiles':{'Human':{'base_speed':1.0}}})
    assert profile(changed['agents']['1'])['speed']==2.6
    print('Domain checks passed: registry, closed geometry, route legality, profiles, exact sampling, baseline geometry/resources/connectivity, validation, actual RDF snapshot.')

if __name__=='__main__':
    run()
