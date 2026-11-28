"""Check runtime memory publication using real committed clock boundaries.

Historical synthetic memory events are not ontology events. The same memory
assertions now use the shared clock commit and immutable memory change tokens.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from zombie_sim.engine import Simulation
from zombie_sim.runtime import capture_delta,mark_committed,_decode
from zombie_sim import runtime
from zombie_sim.core import runtime_service

with TemporaryDirectory() as directory:
    sim=Simulation({'agents':[{'id':'a','type':'Human','x':10,'y':10}], 'decision_mode':'scripted','horizon':10}, history_path=Path(directory)/'run.sqlite')
    original=runtime_service._memory_encode
    try:
        sim.memories['a']={'visited':[{'x':i,'y':i} for i in range(1000)],'counter':0}
        sim._commit('clock_advanced')
        assert _decode(sim.history.runtime_at()['memories']['a'])==sim.memories['a']
        original=runtime_service._memory_encode;calls=[]
        def tracked(*args):
            calls.append(args[1]);return original(*args)
        runtime_service._memory_encode=tracked
        sim.submit_intents([{'actor':'a','action':'wait','parameters':{'duration':'1'}}]);sim.advance_until(1,return_snapshot=False)
        assert not calls,calls
        sim.memories['a']['counter']=1
        sim._commit('clock_advanced')
        assert calls==['a'],calls
        assert _decode(sim.history.runtime_at()['memories']['a'])['counter']==1
        before=sim._runtime_committed_memories['a']
        sim.memories['a']={'counter':2}
        runtime.capture_delta(sim,sim.revision+1,[])
        assert sim._runtime_committed_memories['a'] is before
        sim._commit('clock_advanced')
        assert _decode(sim.history.runtime_at()['memories']['a'])=={'counter':2}
        sim.memories.pop('a');sim._commit('clock_advanced')
        assert 'a' not in sim.history.runtime_at()['memories']
        print('Memory journal preserves replacement, in-place edits and removal; unrelated completions encode zero unchanged maps; capture does not advance durable markers.')
    finally:
        runtime_service._memory_encode=original;sim.close()
