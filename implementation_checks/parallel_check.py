"""Independent checks of actual process computation and conflict partitioning."""
from copy import deepcopy
import json
from pathlib import Path
from zombie_sim.domain import make_agent
from zombie_sim.parallel import conflict_components,materialize_agents


def main():
    entries=[{'writes':['a']},{'reads':['a'],'writes':['b']},{'reads':['b']},{'reads':['z']},{'reads':['z']}]
    assert conflict_components(entries)==[[0,1,2],[3],[4]]
    actor=make_agent('1',x=1,y=1,stamina=50)
    actor.update(active_action='action1',_evaluated_at='0')
    rest={'id':'action1','action':'rest','start_at':'0','planned_end':'5','parameters':{'duration':5}}
    movement={'id':'action2','action':'move','start_at':'0','planned_end':'5','parameters':{'duration':5,'path':[{'x':1,'y':1,'offset':'0'},{'x':11,'y':1,'offset':'5'}]}}
    moving=deepcopy(actor);moving['id']='2';moving['active_action']='action2'
    tasks=[{'agent':actor,'occurrence':rest,'time':'5/2'},{'agent':moving,'occurrence':movement,'time':'5/2'}]
    original=deepcopy(tasks)
    serial=materialize_agents(tasks,1);parallel=materialize_agents(tasks,2)
    assert serial==parallel and tasks==original
    assert serial[0]['agent']['stamina']==60 and serial[1]['agent']['x']==6 and serial[1]['agent']['stamina']==49.5
    assert serial[0]['agent']['hunger']==20.125
    result={'process_workers':2,'serial_process_equal':True,'inputs_unchanged':True,'conflict_components':conflict_components(entries),'mid_action_hunger_rest_movement':True}
    Path('artifacts/model_checks/parallel.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,sort_keys=True))

if __name__=='__main__':main()
