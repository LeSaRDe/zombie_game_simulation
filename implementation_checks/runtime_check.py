"""Independent checks for exact committed-revision continuation and branching."""
from pathlib import Path
from tempfile import TemporaryDirectory
from zombie_sim.engine import Simulation
from zombie_sim.runtime import restore_revision, branch


def assert_continuation(a,b):
    assert a.state==b.state
    assert a.events==b.events
    assert a.memories==b.memories
    assert a.decisions==b.decisions
    assert a.random_draws==b.random_draws
    assert sorted(a.queue)==sorted(b.queue)


def main():
    with TemporaryDirectory() as directory:
        root=Path(directory)
        sim=Simulation({'agents':[{'id':'1','type':'Human','x':10,'y':10}],
            'decision_mode':'scripted','horizon':10},history_path=root/'live.sqlite')
        clones=[]
        try:
            sim.submit_intents({'actor':'1','action':'move','parameters':{'duration':2,
                'path':[{'x':10,'y':10,'offset':0},{'x':14,'y':10,'offset':2}]}})
            admission_revision=sim.revision
            sim.advance_until('1/2')
            clone=restore_revision(Simulation,sim.history_path,admission_revision,backend='sqlite');clones.append(clone)
            clone.advance_until('1/2');assert_continuation(sim,clone)
            sim.advance_until(2);clone.advance_until(2);assert_continuation(sim,clone)
            child=branch(clone,root/'child',seed=987);clones.append(child)
            reopened=restore_revision(Simulation,child.history_path);clones.append(reopened)
            assert child.seed==reopened.seed==987
            assert_continuation(child,reopened)
            try:restore_revision(Simulation,sim.history_path,admission_revision,output_history_path=sim.history_path)
            except ValueError as exc:assert 'never overwritten' in str(exc)
            else:raise AssertionError('An older boundary overwrote newer durable history')
        finally:
            for clone in clones:clone.close()
            sim.close()
        sim=Simulation({'agents':[{'id':'1','type':'Human','x':10,'y':10},
            {'id':'2','type':'Zombie','x':11,'y':10},{'id':'3','type':'Human','role':'WARRIOR','x':10,'y':11}],
            'placement':{'minimum_separation':0,'cross_type_separation':0},'horizon':5,'decision_mode':'model'},
            history_path=root/'model.sqlite')
        try:
            sim.advance_until(5)
            for revision in (0,1,2,sim.revision-2):
                clone=restore_revision(Simulation,sim.history_path,revision)
                try:clone.advance_until(5);assert_continuation(sim,clone)
                finally:clone.close()
            # Runtime journal corruption is a hard failure, independently of the
            # world journal's valid state and checksum.
            sim.history.connection.execute("UPDATE runtime_commits SET checksum='bad' WHERE revision=1")
            sim.history.connection.commit()
            try:restore_revision(Simulation,sim.history_path,1)
            except ValueError as exc:assert 'checksum' in str(exc).lower()
            else:raise AssertionError('Corrupt continuation journal was accepted')
        finally:sim.close()
    print('Exact revision restore passed: fractional busy motion, SQLite continuation, branch seed/lineage, model memories/decisions/draws, prefix protection, runtime checksum rejection.')


if __name__=='__main__':main()
