from pathlib import Path
from tempfile import TemporaryDirectory
from zombie_sim.engine import Simulation
from zombie_sim.runtime import capture_delta,mark_committed,_decode
from zombie_sim import runtime

with TemporaryDirectory() as directory:
    sim=Simulation({'agents':[{'id':'a','type':'Human','x':10,'y':10}], 'decision_mode':'scripted','horizon':10}, history_path=Path(directory)/'run.sqlite')
    try:
        sim.memories['a']={'visited':[{'x':i,'y':i} for i in range(1000)],'counter':0}
        sim._mark('agents','a');sim._commit('memory_replaced',actor='a')
        assert _decode(sim.history.runtime_at()['memories']['a'])==sim.memories['a']
        original=runtime._memory_encode;calls=[]
        def tracked(*args):
            calls.append(args[1]);return original(*args)
        runtime._memory_encode=tracked
        sim.submit_intents([{'actor':'a','action':'wait','parameters':{'duration':'1'}}]);sim.advance_until(1,return_snapshot=False)
        assert not calls,calls
        sim.memories['a']['counter']=1
        sim._commit('decision',actor='a',observation={})
        assert calls==['a'],calls
        assert _decode(sim.history.runtime_at()['memories']['a'])['counter']==1
        before=sim._runtime_committed_memories['a']
        sim.memories['a']={'counter':2}
        runtime.capture_delta(sim,sim.revision+1,[])
        assert sim._runtime_committed_memories['a'] is before
        sim._commit('memory_replaced',actor='a')
        assert _decode(sim.history.runtime_at()['memories']['a'])=={'counter':2}
        sim.memories.pop('a');sim._commit('memory_removed',actor='a')
        assert 'a' not in sim.history.runtime_at()['memories']
        print('Memory journal preserves replacement, in-place decision and removal; unrelated completions encode zero unchanged maps; capture does not advance durable markers.')
    finally:
        runtime._memory_encode=original;sim.close()
