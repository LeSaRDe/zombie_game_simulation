"""No-replay receipt recovery and completed-export drain boundary regression."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from issue12_check import config,until
from zombie_sim.application import RunManager
from zombie_sim.command_recovery import reply
from zombie_sim.export_jobs import ExportJobs
from zombie_sim.storage import History


def main():
    report={'status':'RUNNING'}
    with tempfile.TemporaryDirectory(prefix='zombie-i12-metadata-') as scratch:
        manager=RunManager(scratch);exports=None
        try:
            created=manager.create(config('small'),'metadata-create')
            rid=created['run_id']
            until(lambda:manager._row(rid)['status']=='paused')
            advanced=manager.command(rid,'advance',{'command_id':'advance-parent','time':'1'})
            assert advanced['status']=='applied'
            with patch.object(History,'state_at',side_effect=AssertionError('Receipt reconstructed world')):
                creation_receipt=reply(manager,created)
            assert creation_receipt['revision']=='0' and creation_receipt['time']=='0'
            branch=manager.branch(rid,{'command_id':'metadata-branch'})
            child=branch['run_id'];until(lambda:manager._row(child)['status']=='paused')
            advanced=manager.command(child,'advance',{'command_id':'advance-child','time':'2'})
            assert advanced['status']=='applied' and int(advanced['revision'])>int(branch['revision'])
            unpinned={key:value for key,value in branch.items() if key not in {'revision','time'}}
            with patch.object(History,'state_at',side_effect=AssertionError('Receipt reconstructed world')):
                branch_receipt=reply(manager,unpinned)
            assert branch_receipt['revision']==branch['revision'] and branch_receipt['time']==branch['time']
            exports=ExportJobs(manager)
            exported=exports.create(child,{'format':'scene_png'})
            until(lambda:exports.get(exported['id'])['status']=='COMPLETED',label='completed export')
            job=exports.jobs[exported['id']];before={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (job['artifact'],job['sidecar'])}
            # Reproduce the narrow published-COMPLETED / finally-not-yet-counted
            # window. Draining must retain terminal artifacts in this state.
            with exports.lock:job['active_tasks']=1
            exports.start_draining()
            assert exports.get(exported['id'])['status']=='COMPLETED' and not job['cancel'].is_set()
            assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==value for path,value in before.items())
            with exports.lock:job['active_tasks']=0
            exports.close();exports=None
            report.update(status='PASS',creation_receipt=creation_receipt,branch_receipt=branch_receipt,
                          later_child_revision=advanced['revision'],state_at_forbidden=True,completed_export_retained_during_finalization=True)
        finally:
            if exports:exports.close()
            manager.close()
    output=Path(__file__).resolve().parents[1]/'artifacts/issue12-metadata.json';output.write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
