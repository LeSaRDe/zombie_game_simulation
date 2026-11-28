"""I12 accepted writes, queued exports, retained history and final admission races.

Delays/instrumentation exist exclusively in this disposable fixture process.
The retained histories use 20,000 checksum-valid no-op revisions at time zero;
they measure replay retention, not a 20,000-step scientific simulation.
"""
from __future__ import annotations

try:
    from implementation_checks.check_output import artifact_output
except ModuleNotFoundError:
    from check_output import artifact_output

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'implementation_checks')]
from issue12_check import API,LauncherError,config,until,free_port,query,process_identity
from zombie_sim.read_tasks import _worker as real_reader
from zombie_sim.application import _run_worker as real_writer


def held_reader(root, pipe, registry_factory=None):
    from zombie_sim.read_tasks import ReadOperationRegistry
    class HeldRegistry(registry_factory or ReadOperationRegistry):
        def execute(self, operation, args, kwargs):
            marker=Path(root)/('hold-'+operation)
            if marker.exists():
                (Path(root)/f'entered-{operation}-{os.getpid()}').touch()
                while marker.exists():time.sleep(.05) # deliberately ignores cancellation
            return super().execute(operation,args,kwargs)
    real_reader(root,pipe,HeldRegistry)


def held_writer(root,rid):
    from zombie_sim import application
    original=application._atomic_json
    def atomic(path,value):
        marker=Path(root)/'hold-checkpoint'
        if Path(path).name=='worker-checkpoint.json' and value.get('control',{}).get('status')=='stopped' and marker.exists():
            (Path(root)/'entered-checkpoint').touch()
            while marker.exists():time.sleep(.05)
        return original(path,value)
    application._atomic_json=atomic
    real_writer(root,rid)


def serve(workspace,port):
    from fastapi import Body
    from zombie_sim import read_tasks,application
    from zombie_sim.server import create_app,run_service
    read_tasks._worker=held_reader;application._run_worker=held_writer
    app=create_app(workspace);manager=app.state.manager
    original_branch=manager.branch;original_create=manager.create;original_command=manager.command
    flags={'natural':False}
    def wait_marker(name):
        marker=Path(workspace)/('hold-'+name)
        if marker.exists():
            (Path(workspace)/('entered-'+name)).touch()
            while marker.exists():time.sleep(.05)
    def branch(*args,**kwargs):wait_marker('branch');return original_branch(*args,**kwargs)
    def create(*args,**kwargs):wait_marker('create');return original_create(*args,**kwargs)
    def command(rid,operation,*args,**kwargs):
        if flags['natural'] and operation in {'stop','terminate'}:
            flags['natural']=False
            original_command(rid,'pace',{'command_id':uuid.uuid4().hex,'pacing':0})
            original_command(rid,'start',{'command_id':uuid.uuid4().hex})
            until(lambda:manager._row(rid)['status']=='completed',timeout=30,label='natural horizon completion before stop admission')
        return original_command(rid,operation,*args,**kwargs)
    manager.branch=branch;manager.create=create;manager.command=command
    @app.post('/fixture/export-gate')
    def gate(body:dict=Body(...)):
        getattr(app.state.exports,body['operation'])(body['run_id']);return {'ok':True}
    @app.post('/fixture/natural')
    def natural():flags['natural']=True;return {'ok':True}
    @app.get('/fixture/jobs')
    def jobs():return [app.state.exports.get(key) for key in app.state.exports.jobs]
    run_service(app,host='127.0.0.1',port=port,log_level='warning')


def service(workspace,output,label):
    workspace.mkdir(parents=True,exist_ok=True);port=free_port();log=(output/(label+'.log')).open('w')
    process=subprocess.Popen([sys.executable,__file__,'--serve',str(workspace),str(port)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                             env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1'))
    api=API(port)
    def ready():
        if process.poll() is not None:raise AssertionError((output/(label+'.log')).read_text())
        try:return api.request('/api/config',timeout=.5)
        except LauncherError:return None
    until(ready,timeout=20,label=label+' startup')
    return process,api,log


def finish(process,api):
    api.request('/api/shutdown/exit',{});process.wait(timeout=15);assert process.returncode==0


def async_request(port,path,body):
    api=API(port);api.request('/api/config')
    return api.request(path,body,timeout=90)


def accepted_writes(root,output):
    workspace=root/'accepted';process,api,log=service(workspace,output,'accepted')
    try:
        rid=api.request('/api/runs',{'config':config('small')})['run_id']
        before={row[0] for row in query(workspace,'SELECT id FROM commands')}
        for marker in ('hold-branch','hold-create','hold-checkpoint'):(workspace/marker).touch()
        create_id,branch_id=uuid.uuid4().hex,uuid.uuid4().hex
        with ThreadPoolExecutor(max_workers=2) as executor:
            creation=executor.submit(async_request,api.url.rsplit(':',1)[1],'/api/runs',{'config':config('small'),'command_id':create_id,'wait_for_initialization':False})
            branch=executor.submit(async_request,api.url.rsplit(':',1)[1],f'/api/runs/{rid}/branch',{'command_id':branch_id,'revision':0})
            until(lambda:(workspace/'entered-create').exists() and (workspace/'entered-branch').exists(),label='accepted create/branch')
            # A command body starts before the fence but finishes afterward.
            # Admission must inspect the current fence after awaiting its body.
            import http.client
            cookies=next(handler.cookiejar for handler in api.opener.handlers if hasattr(handler,'cookiejar'))
            slow_id=uuid.uuid4().hex
            slow_body=json.dumps({'operation':'terminate','command_id':slow_id}).encode()
            slow=http.client.HTTPConnection('127.0.0.1',int(api.url.rsplit(':',1)[1]),timeout=5)
            slow.putrequest('POST',f'/api/runs/{rid}/commands')
            slow.putheader('Content-Type','application/json');slow.putheader('Content-Length',str(len(slow_body)))
            slow.putheader('Cookie','; '.join(f'{cookie.name}={cookie.value}' for cookie in cookies));slow.endheaders()
            slow.send(slow_body[:1]);time.sleep(.1)
            api.request('/api/shutdown',{'mode':'save','timeout':.5})
            incomplete=until(lambda:(s if (s:=api.request('/api/shutdown'))['phase']=='incomplete' else None),timeout=5,label='accepted mutation timeout')
            assert incomplete['active_mutations']==2 and not incomplete['controls_open']
            slow.send(slow_body[1:]);slow_response=slow.getresponse();assert slow_response.status==503;slow_response.read();slow.close()
            assert not query(workspace,f"SELECT id FROM commands WHERE id='{slow_id}'")
            # Late terminal admission cannot create a fresh worker after fence.
            late_id=uuid.uuid4().hex
            try:api.request(f'/api/runs/{rid}/commands',{'operation':'terminate','command_id':late_id})
            except LauncherError as error:assert '503' in str(error)
            else:raise AssertionError('Late terminal mutation admitted after fence')
            assert not query(workspace,f"SELECT id FROM commands WHERE id='{late_id}'")
            (workspace/'hold-create').unlink();(workspace/'hold-branch').unlink()
            child_create=creation.result()['run_id'];child_branch=branch.result()['run_id']
        api.request('/api/shutdown',{'mode':'save','timeout':.5})
        until(lambda:(workspace/'entered-checkpoint').exists(),label='real checkpoint work')
        incomplete_checkpoint=until(lambda:(s if (s:=api.request('/api/shutdown'))['phase']=='incomplete' else None),timeout=5,label='checkpoint timeout')
        assert any(process_identity(pid) for _,pid in query(workspace,'SELECT run_id,pid FROM worker_leases'))
        (workspace/'hold-checkpoint').unlink()
        api.request('/api/shutdown',{'mode':'save','timeout':60})
        final=until(lambda:(s if (s:=api.request('/api/shutdown'))['complete'] else None),label='accepted writes reconcile')
        assert len(final['runs'])==3,final
        assert {row[0] for row in query(workspace,'SELECT id FROM runs')}=={rid,child_create,child_branch}
        assert query(workspace,"SELECT count(*) FROM commands WHERE status='pending'")[0][0]==0
        assert len(query(workspace,"SELECT id FROM commands WHERE operation='stop'"))==3
        assert not query(workspace,'SELECT * FROM worker_leases')
        assert all(value['cleanup_complete'] for value in final['runs'].values())
        # Even ready-phase commands are rejected, including inactive→new-worker.
        try:api.request(f'/api/runs/{rid}/commands',{'operation':'stop','command_id':uuid.uuid4().hex})
        except LauncherError as error:assert '503' in str(error)
        else:raise AssertionError('Ready phase admitted command')
        finish(process,api)
        return {'accepted_create_id':create_id,'accepted_branch_id':branch_id,'mutation_timeout':incomplete,
                'checkpoint_timeout':incomplete_checkpoint,'final':final,'late_mutation_rejected':True,'slow_body_terminal_mutation_rejected':True,'original_commands_preserved':before.issubset({r[0] for r in query(workspace,'SELECT id FROM commands')})}
    finally:
        for marker in workspace.glob('hold-*'):marker.unlink(missing_ok=True)
        if process.poll() is None:process.send_signal(signal.SIGTERM);process.wait(timeout=90)
        log.close()


def long_history(workspace):
    from zombie_sim.config import resolve_config,initialize_world
    from zombie_sim.storage import History,canonical,_pack
    cfg=resolve_config(config('small'))
    for identity in ('long-a','long-b'):
        directory=workspace/'runs'/identity;directory.mkdir(parents=True)
        state=initialize_world(cfg);state['run_id']=identity
        (directory/'manifest.json').write_text(canonical({'run_id':identity,'config':cfg,'status':'completed' if identity=='long-a' else 'running'}))
        history=History(directory/'run.sqlite',initial=state)
        with history.connection:
            for revision in range(1,20001):
                blob=_pack([['set',['revision'],revision]])
                history.connection.execute('INSERT INTO commits VALUES(?,?,?,?,?,?,?,?)',(revision,f'retained:{revision}','0','1',0,blob,None,hashlib.sha256(blob).hexdigest()))
        history.close()


def long_reads_and_exports(root,output):
    workspace=root/'long';long_history(workspace);process,api,log=service(workspace,output,'long')
    try:
        originals={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (workspace/'runs').glob('*/run.sqlite')}
        views={rid:api.request(f'/api/runs/{rid}/view') for rid in ('long-a','long-b')}
        assert all(view['revision']=='20000' for view in views.values())
        for endpoint in ('metrics','cohorts','timeline'):api.request('/api/runs/long-a/'+endpoint)
        comparison={'sources':[{'run_id':rid,'revision':'20000','time':'0'} for rid in views]}
        assert api.request('/api/comparison',comparison)['status']=='ready'
        # Pin four real export jobs before starting two blocked renders, leaving
        # two queued executor jobs. Their child ignores cancellation completely.
        api.request('/fixture/export-gate',{'operation':'arm_pause','run_id':'long-a'})
        jobs=[api.request('/api/runs/long-a/exports',{'format':'chart_png'}) for _ in range(4)]
        (workspace/'hold-render_export').touch()
        api.request('/fixture/export-gate',{'operation':'release','run_id':'long-a'})
        until(lambda:len(list(workspace.glob('entered-render_export-*')))==2,label='two uncooperative render children')
        state=api.request('/api/shutdown');assert state['exports']['active']==4,state
        pids=state['exports']['readers']['processes']
        started=time.monotonic();api.request('/api/shutdown',{'mode':'save','timeout':30})
        final=until(lambda:(s if (s:=api.request('/api/shutdown'))['complete'] else None),timeout=10,label='long-history drain')
        statuses=api.request('/fixture/jobs');assert all(job['status']=='CANCELLED' and job['active_tasks']==0 for job in statuses)
        assert all(not process_identity(pid) for pid in pids)
        assert not list((workspace/'exports').iterdir())
        finish(process,api)
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==value for path,value in originals.items())
        assert final['runs']['long-b']['run_status']=='interrupted' and final['runs']['long-b']['command_id'] is None
        assert not list((workspace/'runs').glob('*/worker-checkpoint.json'))
        return {'runs':2,'agents_per_run':24,'retained_revisions_per_run':20001,'simulation_time':'0','fixture_kind':'checksum-valid no-op retention fixture',
                'panel_reads_passed':['world','metrics','cohorts','comparison','timeline'],'active_and_queued_exports':4,'cancelled_export_pids':pids,
                'seconds':round(time.monotonic()-started,3),'final':final,'source_files_unchanged':True}
    finally:
        for marker in workspace.glob('hold-*'):marker.unlink(missing_ok=True)
        if process.poll() is None:process.send_signal(signal.SIGTERM);process.wait(timeout=60)
        log.close()


def horizon_race(root,output):
    workspace=root/'horizon';process,api,log=service(workspace,output,'horizon')
    try:
        cfg=config('small');cfg['horizon']=.1
        rid=api.request('/api/runs',{'config':cfg})['run_id']
        api.request('/fixture/natural',{})
        api.request('/api/shutdown',{'mode':'save','timeout':30})
        final=until(lambda:(s if (s:=api.request('/api/shutdown'))['complete'] else None),timeout=15,label='natural completion race')
        assert final['runs'][rid]['run_status']=='completed'
        assert final['runs'][rid]['command_id'] is None
        assert not query(workspace,"SELECT id FROM commands WHERE operation='stop'")
        finish(process,api)
        return {'natural_completion_won':True,'no_synthetic_stop_receipt':True,'final':final}
    finally:
        if process.poll() is None:process.send_signal(signal.SIGTERM);process.wait(timeout=60)
        log.close()



def lost_ack_and_validation(root,output):
    workspace=root/'receipt';process,api,log=service(workspace,output,'receipt')
    try:
        from urllib.request import Request
        from urllib.error import HTTPError
        invalid=config('small');invalid['state_import']=True
        request=Request(api.url+'/api/config/preview',data=json.dumps(invalid).encode(),headers={'Content-Type':'application/json'})
        try:api.opener.open(request)
        except HTTPError as error:
            validation=json.load(error);assert error.code==422 and validation['code']=='INVALID_REFERENCE',validation
        else:raise AssertionError('Invalid explicit state preview was accepted')
        assert api.request('/api/config/preview',config('small'))['view']['state']['agents']
        rid=api.request('/api/runs',{'config':config('small')})['run_id']
        command_id=uuid.uuid4().hex
        api.request(f'/api/runs/{rid}/commands',{'operation':'terminate','command_id':command_id})
        until(lambda:api.request('/api/commands/'+command_id)['status']=='applied',label='durable terminate receipt')
        until(lambda:not query(workspace,'SELECT * FROM worker_leases'),label='terminated worker exit')
        directory=Path(query(workspace,'SELECT directory FROM runs')[0][0])
        originals={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (directory/'run.sqlite',directory/'worker-checkpoint.json')}
        # Retain the real ledger receipt and published terminal status; remove
        # only the manager ACK to reproduce the documented crash window.
        with sqlite3.connect(workspace/'manager.sqlite') as db:
            db.execute("UPDATE commands SET status='pending',response=NULL WHERE id=?",(command_id,))
        api.request('/api/shutdown',{'mode':'save','timeout':30})
        final=until(lambda:(s if (s:=api.request('/api/shutdown'))['complete'] else None),timeout=10,label='lost terminal ACK recovery')
        assert query(workspace,f"SELECT status FROM commands WHERE id='{command_id}'")==[('applied',)]
        assert not query(workspace,"SELECT id FROM commands WHERE operation='stop'")
        finish(process,api)
        assert all(hashlib.sha256(Path(path).read_bytes()).hexdigest()==value for path,value in originals.items())
        return {'structured_preview_error':validation,'terminal_receipt_reconciled':command_id,'history_and_checkpoint_unchanged':True,'final':final}
    finally:
        if process.poll() is None:process.send_signal(signal.SIGTERM);process.wait(timeout=60)
        log.close()


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--serve':serve(sys.argv[2],int(sys.argv[3]));return
    output=artifact_output(ROOT/'artifacts/issue12-concurrency');output.mkdir(exist_ok=True);scratch=Path(tempfile.mkdtemp(prefix='zombie-i12-concurrent-'))
    report={'status':'RUNNING','scratch':str(scratch),'checks':{}}
    try:
        for label,function in [('accepted_writes_and_checkpoint',accepted_writes),('long_history_exports',long_reads_and_exports),('natural_completion_race',horizon_race),('lost_ack_and_validation',lost_ack_and_validation)]:
            print('Checking',label,flush=True);report['checks'][label]=function(scratch,output)
            (output/'report.json').write_text(json.dumps(report,indent=2))
        report['status']='PASS';shutil.rmtree(scratch);report['scratch_removed']=True
    except BaseException as error:report['status']='FAIL';report['error']=repr(error);raise
    finally:(output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
