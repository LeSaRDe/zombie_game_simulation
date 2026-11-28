"""Exercise the real ./simulate menu through a PTY, including option 10 modes."""
from __future__ import annotations

try:
    from implementation_checks.check_output import artifact_output
except ModuleNotFoundError:
    from check_output import artifact_output

import hashlib
import json
import os
from pathlib import Path
import pty
import select
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from issue12_check import ROOT,Launcher,free_port,query,process_identity


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run_cli(workspace,port,args,output,label,answers=None):
    argv=[str(ROOT/'simulate'),'--workspace',str(workspace),'--port',str(port),'--timeout','60',*args]
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(ROOT/'src'),ZOMBIE_SIM_PYTHON=sys.executable)
    if answers is None:
        completed=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=90)
        code=completed.returncode;text=completed.stdout+completed.stderr
    else:
        master,slave=pty.openpty();process=subprocess.Popen(argv,cwd=ROOT,env=env,stdin=slave,stdout=slave,stderr=slave,close_fds=True)
        os.close(slave);os.write(master,answers.encode());chunks=[];deadline=time.monotonic()+90
        try:
            while process.poll() is None or select.select([master],[],[],0)[0]:
                if time.monotonic()>deadline:raise TimeoutError('Menu did not complete')
                if not select.select([master],[],[],.1)[0]:continue
                try:chunk=os.read(master,65536)
                except OSError:break
                if not chunk:break
                chunks.append(chunk)
            code=process.wait(timeout=5);text=b''.join(chunks).decode(errors='replace')
        finally:os.close(master)
    (output/(label+'.log')).write_text(text)
    assert code==0 and 'Could not finish:' not in text,(label,code,text)
    return text


def main():
    output=artifact_output(ROOT/'artifacts/issue12-menu');output.mkdir(exist_ok=True);scratch=Path(tempfile.mkdtemp(prefix='zombie-i12-menu-'))
    report={'status':'RUNNING','checks':{},'scratch':str(scratch)}
    try:
        for option,expected in [('1','stopped'),('2','terminated')]:
            workspace=scratch/('save' if option=='1' else 'terminate');port=free_port();launcher=Launcher(workspace,port,60)
            try:
                run_cli(workspace,port,['start','small','--workers','1','--no-browser'],output,option+'-start')
                run_cli(workspace,port,['pause','1'],output,option+'-pause')
                rid,directory,status=query(workspace,'SELECT id,directory,status FROM runs')[0];assert status=='paused'
                directory=Path(directory);checkpoint=directory/'worker-checkpoint.json'
                record=json.loads((workspace/'.launcher/server.json').read_text());identity=process_identity(record['pid'])
                before_checkpoint=digest(checkpoint);before_history=digest(directory/'run.sqlite')
                menu=run_cli(workspace,port,['menu'],output,option+'-list-requests-leave',answers='4\n11\n\n0\n')
                assert 'paused' in menu and 'No unresolved launcher requests.' in menu and 'Menu closed.' in menu
                assert process_identity(record['pid'])==identity and Launcher.port_is_open(port)
                assert digest(checkpoint)==before_checkpoint and digest(directory/'run.sqlite')==before_history
                requests=run_cli(workspace,port,['requests'],output,option+'-requests-cli');assert 'No unresolved launcher requests.' in requests
                started=time.monotonic()
                closed=run_cli(workspace,port,['menu'],output,option+'-shutdown-menu',answers=f'10\n{option}\n0\n')
                assert 'Shutdown:' in closed and 'All runs and the web service are stopped.' in closed
                assert query(workspace,'SELECT status FROM runs')==[(expected,)] and not query(workspace,'SELECT * FROM worker_leases')
                assert not process_identity(record['pid']) and not Launcher.port_is_open(port)
                after_checkpoint=digest(checkpoint)
                assert (after_checkpoint!=before_checkpoint) if option=='1' else (after_checkpoint==before_checkpoint)
                report['checks'][option]={'menu_path':f'10 → {option} → 0','agents':24,'result':expected,
                    'list_requests_leave_preserved_service_and_history':True,'cli_requests_passed':True,
                    'checkpoint_changed':after_checkpoint!=before_checkpoint,'phase_output':True,'service_and_workers_exited':True,
                    'seconds':round(time.monotonic()-started,3)}
            finally:
                path=workspace/'.launcher/server.json'
                if path.exists() and launcher.owns_process(json.loads(path.read_text())):launcher.shutdown(terminate=option=='2')
        report['status']='PASS';shutil.rmtree(scratch);report['scratch_removed']=True
    except BaseException as error:report['status']='FAIL';report['error']=repr(error);raise
    finally:(output/'report.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
