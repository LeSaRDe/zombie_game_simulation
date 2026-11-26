"""Exercise all real encoders and cancellation against an immutable live ledger."""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from zombie_sim.engine import Simulation
from zombie_sim.storage import History,canonical
from zombie_sim.export_jobs import ExportJobs,FORMATS
from zombie_sim.testing_browser_exports import read_artifact


def main():
    with TemporaryDirectory() as directory:
        root=Path(directory);path=root/'run.sqlite'
        sim=Simulation({'agents':[{'id':'h','type':'Human','x':10,'y':10}], 'horizon':5,'execution':{'workers':1}},history_path=path,decision_mode='scripted',run_id='actual-export-run')
        sim.submit_intents([{'actor':'h','action':'move','parameters':{'duration':4,'path':[{'x':10,'y':10,'offset':0},{'x':18,'y':10,'offset':4}]}}])
        sim.advance_until(4,return_snapshot=False);before=canonical(sim.snapshot());events=canonical(sim.events)
        class Source:
            def __init__(self):self.root=root
            def history(self,run_id):assert run_id=='actual-export-run';return History(path,read_only=True)
        service=ExportJobs(Source());results={}
        try:
            for format in FORMATS:
                job=service.create('actual-export-run',{'format':format,'time':'2','interval':['0','4'],'sample_interval':'1','cohort':'all'})
                until=time.monotonic()+15
                while job['status'] not in {'COMPLETED','FAILED','CANCELLED'} and time.monotonic()<until:
                    time.sleep(.01);job=service.get(job['id'])
                assert job['status']=='COMPLETED',job
                artifact=read_artifact({'path':str(service.path(job['id'])),'provenance_path':str(service.path(job['id'],True))},{'actual-export-run':'run'})
                assert float(artifact['source_scene']['agents']['h']['x'])==14,artifact
                assert artifact['provenance']['time']=='2' and artifact['provenance']['run_alias']=='run'
                results[format]={'bytes':artifact['bytes'],'decoded':list(artifact['decoded'])}
            service.arm_pause('actual-export-run')
            job=service.create('actual-export-run',{'format':'replay_animation','time':'2','interval':['0','4']})
            job=service.cancel(job['id']);assert job['status']=='CANCELLED' and job['active_tasks']==0,job
            assert canonical(sim.snapshot())==before and canonical(sim.events)==events
            print({'formats':results,'cancelled_active_tasks':job['active_tasks'],'history_unchanged':True})
        finally:service.close();sim.close()


if __name__=='__main__':main()
