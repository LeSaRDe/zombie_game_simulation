"""Exercise real I12 service drain, supervised cancellation and safe retry.

All workspaces/processes belong to this script. SIGSTOP models uncooperative
read/native work; the service terminates only its own read-only children. Writer
SIGSTOP models an atomic checkpoint delay and is always resumed by this driver.
"""
from __future__ import annotations

try:
    from implementation_checks.check_output import artifact_output
except ModuleNotFoundError:
    from check_output import artifact_output

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.simulation_launcher import Launcher,LauncherError,API,process_identity


def until(function, timeout=90, label='condition'):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=function()
        if value:return value
        time.sleep(.05)
    raise AssertionError(f'Timed out: {label}')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));return sock.getsockname()[1]


def query(workspace, sql):
    with sqlite3.connect((workspace/'manager.sqlite').as_uri()+'?mode=ro',uri=True) as db:return db.execute(sql).fetchall()


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def config(name):return tomllib.loads((ROOT/'configs'/f'{name}.toml').read_text())


def create(launcher, cfg, wait=True):
    return launcher.api.request('/api/runs',{'config':cfg,'command_id':str(uuid.uuid4()),'wait_for_initialization':wait},timeout=120)['run_id']


def command(launcher, rid, op, **extra):
    request={'operation':op,'command_id':str(uuid.uuid4()),**extra}
    result=launcher.api.request(f'/api/runs/{rid}/commands',request)
    return until(lambda: (value if (value:=launcher.api.request('/api/commands/'+request['command_id']))['status']!='pending' else None),label=op)


def row(launcher,rid):return next(value for value in launcher.api.request('/api/runs') if value['id']==rid)


def request(port, path, payload=None):
    api=API(port);api.request('/api/launcher')
    try:return api.request(path,payload,timeout=90)
    except LauncherError as error:return {'error':str(error)}


def owned_child(pid,parent):
    fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
    assert int(fields[1])==parent,(pid,parent,fields[1])


def stop_readers(launcher):
    status=launcher.api.request('/api/shutdown')
    pids=status['readers']['processes']+status['exports']['readers']['processes']
    assert pids
    for pid in pids:
        owned_child(pid,launcher.record['pid']);os.kill(pid,signal.SIGSTOP)
    return pids


def retained_prefix(workspace,rid):
    directory=Path(query(workspace,f"SELECT directory FROM runs WHERE id='{rid}'")[0][0])
    with sqlite3.connect((directory/'run.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        return directory,db.execute('SELECT * FROM commits ORDER BY revision').fetchall()


def assert_prefix(directory,prefix):
    with sqlite3.connect((directory/'run.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        assert db.execute('SELECT * FROM commits ORDER BY revision').fetchmany(len(prefix))==prefix


def basic_and_busy(scratch,output):
    workspace=scratch/'busy';launcher=Launcher(workspace,free_port(),60);launcher.connect(start=True)
    rid=create(launcher,config('small'))
    # Genuine lifecycle and 24-agent retained history. Advance explicitly while
    # paused so no assertion depends on wall-clock race or implicit playback.
    command(launcher,rid,'start');command(launcher,rid,'pause')
    command(launcher,rid,'continue');command(launcher,rid,'pause')
    advanced=command(launcher,rid,'advance',time='12')
    assert advanced['status']=='applied',advanced
    view=launcher.api.request(f'/api/runs/{rid}/view');assert len(view['state']['agents'])==24
    history_dir,prefix=retained_prefix(workspace,rid)
    # Each panel/read family executes successfully before its uncooperative case.
    agent=next(iter(view['state']['agents']))
    paths=[f'/api/runs/{rid}/view',f'/api/runs/{rid}/metrics?interval=1',f'/api/runs/{rid}/cohorts?with_cursor=true',
           f'/api/runs/{rid}/timeline',f'/api/runs/{rid}/events',f'/api/runs/{rid}/export?format=svg']
    for path in paths:launcher.api.request(path) if '/export?' not in path else None
    comparison_id=create(launcher,config('small'))
    comparison_view=launcher.api.request(f'/api/runs/{comparison_id}/view')
    comparison={'sources':[{'run_id':rid,'time':view['time'],'revision':view['revision'],'cohort':'all'},
                           {'run_id':comparison_id,'time':comparison_view['time'],'revision':comparison_view['revision'],'cohort':'all'}]}
    launcher.api.request('/api/comparison',comparison)
    saved=launcher.api.request(f'/api/runs/{rid}/exports',{'format':'scene_png'})
    until(lambda:launcher.api.request('/api/export-jobs/'+saved['id'])['status']=='COMPLETED',label='export complete')
    completed=workspace/'exports'/f'{saved["id"]}.png';before_export=digest(completed)
    reader_pids=stop_readers(launcher)
    executor=ThreadPoolExecutor(max_workers=10)
    futures=[executor.submit(request,launcher.port,path) for path in paths]
    futures.append(executor.submit(request,launcher.port,'/api/comparison',comparison))
    # Export preparation is also supervised, independently of analysis readers.
    futures += [executor.submit(request,launcher.port,f'/api/runs/{rid}/exports',{'format':'replay_animation','sample_interval':'0.01'}) for _ in range(3)]
    busy=until(lambda:(state if (state:=launcher.api.request('/api/shutdown'))['readers']['active']==2 and state['readers']['queued']>=2 else None),label='read workers busy')
    transcript=io.StringIO();started=time.monotonic()
    with redirect_stdout(transcript):launcher.shutdown()
    elapsed=time.monotonic()-started
    executor.shutdown(wait=True)
    assert elapsed<15,elapsed
    assert all(not process_identity(pid) for pid in reader_pids)
    assert query(workspace,'SELECT count(*) FROM worker_leases')[0][0]==0
    assert query(workspace,'SELECT status FROM runs')[0][0]=='stopped'
    assert_prefix(history_dir,prefix);assert digest(completed)==before_export
    assert not list((workspace/'exports').glob('*.partial*'))
    assert 'draining readers' in transcript.getvalue() and 'worker cleanup complete' in transcript.getvalue()
    launcher.shutdown()
    # Reopen and resume a saved run; terminate must not request another save.
    launcher.connect(start=True);command(launcher,rid,'continue');command(launcher,rid,'pause')
    checkpoint=history_dir/'worker-checkpoint.json';checkpoint_hash=digest(checkpoint)
    started=time.monotonic()
    with redirect_stdout(transcript):launcher.shutdown(terminate=True)
    assert query(workspace,'SELECT status FROM runs')[0][0]=='terminated'
    assert digest(checkpoint)==checkpoint_hash
    (output/'busy-transcript.log').write_text(transcript.getvalue())
    return {'agents':24,'simulation_time':view['time'],'commits_before_drain':len(prefix),'busy':busy,
            'cancelled_readers':reader_pids,'save_shutdown_seconds':round(elapsed,3),'terminate_shutdown_seconds':round(time.monotonic()-started,3),
            'accepted_reads':[future.result() if isinstance(future.result(),dict) and 'error' in future.result() else 'returned before drain' for future in futures],
            'history_prefix_preserved':True,'completed_export_preserved':True,'resumed_saved_run':True,'termination_checkpoint_unchanged':True}


def timeout_retry(scratch,output):
    workspace=scratch/'retry';launcher=Launcher(workspace,free_port(),60);launcher.connect(start=True)
    rid=create(launcher,config('small'));worker=query(workspace,'SELECT pid FROM worker_leases')[0][0]
    owned_child(worker,launcher.record['pid']);os.kill(worker,signal.SIGSTOP)
    try:
        state=launcher.api.request('/api/launcher/drain',{'instance':launcher.record['instance'],'mode':'save','timeout':.3})
        incomplete=until(lambda:(s if (s:=launcher.api.request('/api/shutdown'))['phase']=='incomplete' else None),timeout=5,label='truthful timeout')
        assert incomplete['retryable'] and not incomplete['complete'];assert process_identity(worker)
        commands=query(workspace,"SELECT id FROM commands WHERE operation='stop'")
        assert len(commands)==1,commands
        try:launcher.api.request('/api/runs',{'config':config('small')})
        except LauncherError as error:assert '503' in str(error)
        else:raise AssertionError('Draining admitted creation')
        # The launcher retries the same instance/command, with progress heartbeat
        # while the writer remains safely suspended for longer than five seconds.
        resume=threading.Timer(5.2,lambda:os.kill(worker,signal.SIGCONT));resume.start()
        transcript=io.StringIO()
        with redirect_stdout(transcript):launcher.shutdown()
        resume.join();assert query(workspace,"SELECT id FROM commands WHERE operation='stop'")==commands
        assert transcript.getvalue().count('Shutdown:')>=4,transcript.getvalue()
        (output/'retry-transcript.log').write_text(transcript.getvalue())
        return {'incomplete':incomplete,'same_stop_command_reconciled':True,'writer_not_killed':True,'heartbeat':transcript.getvalue()}
    finally:
        if process_identity(worker):os.kill(worker,signal.SIGCONT)
        if launcher.owns_process(launcher.record):launcher.shutdown()


def baseline_initialization(scratch,output):
    workspace=scratch/'baseline';launcher=Launcher(workspace,free_port(),180);launcher.connect(start=True)
    rid=create(launcher,config('baseline'),wait=False)
    before=row(launcher,rid);started=time.monotonic();transcript=io.StringIO()
    with redirect_stdout(transcript):launcher.shutdown(terminate=True)
    history,prefix=retained_prefix(workspace,rid)
    assert query(workspace,'SELECT status FROM runs')[0][0]=='terminated'
    checkpoint=json.loads((history/'worker-checkpoint.json').read_text())
    assert checkpoint['control']['status']=='paused' and checkpoint['control']['generation']==0
    assert not checkpoint['control']['processed'],'shutdown rewrote the initialization checkpoint'
    from zombie_sim.storage import History
    db=History(history/'run.sqlite',read_only=True)
    try:state=db.state_at();assert len(state['agents'])==1000
    finally:db.close()
    (output/'baseline-transcript.log').write_text(transcript.getvalue())
    return {'agents':1000,'initial_status':before['status'],'simulation_time':str(state['time']),'seconds':round(time.monotonic()-started,3),'commits':len(prefix),'only_initialization_checkpoint':True}


def foreground(scratch,output):
    workspace=scratch/'foreground';port=free_port();log=(output/'foreground.log').open('w')
    process=subprocess.Popen([sys.executable,'-m','zombie_sim.cli','gui','--experiments-dir',str(workspace),'--port',str(port)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1'))
    try:
        api=API(port)
        def ready():
            if process.poll() is not None:raise AssertionError((output/'foreground.log').read_text())
            try:return api.request('/api/config',timeout=.5)
            except LauncherError:return None
        until(ready,timeout=15,label='foreground service')
        rid=api.request('/api/runs',{'config':config('small')})['run_id']
        api.request('/api/runs/'+rid+'/view');before=time.monotonic();process.send_signal(signal.SIGINT)
        process.wait(timeout=30)
        assert process.returncode==0,process.returncode
        assert query(workspace,'SELECT status FROM runs')[0][0]=='stopped'
        assert not Launcher.port_is_open(port)
        return {'signal':'SIGINT','exit_code':process.returncode,'seconds':round(time.monotonic()-before,3),'saved':True}
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM);process.wait(timeout=60)
        log.close()


def main():
    output=artifact_output(ROOT/'artifacts/issue12');output.mkdir(exist_ok=True)
    scratch=Path(tempfile.mkdtemp(prefix='zombie-i12-check-'))
    report={'status':'RUNNING','scratch':str(scratch),'checks':{},'limitations':['Baseline initializes all 1000 agents at time 0; this is not an 1800-second baseline performance claim.','Reader/native stalls use exact owned child SIGSTOP; authoritative writer is resumed rather than killed.']}
    try:
        for name,check in [('busy_service',basic_and_busy),('timeout_retry',timeout_retry),('baseline_initialization',baseline_initialization),('foreground',foreground)]:
            print('Checking',name,flush=True);report['checks'][name]=check(scratch,output)
            (output/'report.json').write_text(json.dumps(report,indent=2,default=str))
        report['status']='PASS';shutil.rmtree(scratch);report['scratch_removed']=True
    except BaseException as error:
        report['status']='FAIL';report['error']=repr(error)
        for record_path in scratch.glob('*/.launcher/server.json'):
            record=json.loads(record_path.read_text());cleanup=Launcher(record_path.parents[1],record['port'],60)
            try:
                if cleanup.owns_process(record):cleanup.shutdown()
            except Exception as cleanup_error:report.setdefault('cleanup_errors',[]).append(str(cleanup_error))
        raise
    finally:(output/'report.json').write_text(json.dumps(report,indent=2,default=str))
    print(json.dumps(report,indent=2,default=str))

if __name__=='__main__':main()
