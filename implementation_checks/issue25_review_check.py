"""Reproduce I25 without changing production code or any user experiment."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import uuid

from issue2_check import Api, until, ROOT, NODE_MODULES


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True)
    report={"passed":False,"engine":engine,"purpose":"pre-fix reproduction for review"}
    with tempfile.TemporaryDirectory(prefix="zombie-issue25-review-") as workspace:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1',NODE_PATH=NODE_MODULES)
        with (output/'service.log').open('w') as log:
            service=subprocess.Popen([sys.executable,'-m','zombie_sim.cli','gui','--experiments-dir',workspace,'--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            api=Api(port)
            try:
                def available():
                    if service.poll() is not None:raise AssertionError('Service exited before startup')
                    try:return isinstance(api.call('/api/runs'),list)
                    except OSError:return False
                until(available)
                config={'scenario':'issue25_live_analysis_review','seed':25,'horizon':600,'world':{'length':300,'width':300},'execution':{'workers':1},
                    'placement':{'minimum_separation':0,'cross_type_separation':0},
                    'agents':[{'id':'h1','type':'Human','x':20,'y':20},{'id':'h2','type':'Human','x':25,'y':20},
                              {'id':'z1','type':'Zombie','x':200,'y':200},{'id':'z2','type':'Zombie','x':205,'y':200}]}
                run_id=api.call('/api/runs',{'config':config,'command_id':str(uuid.uuid4())})['run_id']
                api.command(run_id,'advance',time='3')
                api.call(f'/api/runs/{run_id}/cohorts',{'name':'All initial identities','mode':'fixed','predicate':{},'include_dead':True,'reference_time':'0','reference_revision':'0'})
                api.command(run_id,'start')
                def commands():
                    with sqlite3.connect((Path(workspace)/'manager.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                        return db.execute('SELECT id,operation,status,response FROM commands ORDER BY created,id').fetchall()
                report.update(run_id=run_id,commands_before=commands(),before=api.row(run_id))
                with (output/'browser.log').open('w') as browser_log:
                    result=subprocess.run([str(ROOT/'.runtimeenv/bin/node'),str(ROOT/'implementation_checks/issue25_review_browser.cjs'),api.base,str(output),run_id,engine],cwd=ROOT,env=env,stdout=browser_log,stderr=subprocess.STDOUT,timeout=150)
                report['browser']=json.loads((output/'browser.json').read_text())
                assert result.returncode==0,(output/'browser.log').read_text()
                report.update(commands_after=commands(),after=api.row(run_id))
                assert report['commands_after']==report['commands_before'],'Analysis clicks changed execution commands'
                assert report['after']['status']=='running'
                report['reproduction_passed']=True
            finally:
                if service.poll() is None:
                    status=api.call('/api/shutdown',{'mode':'terminate','timeout':60})
                    until(lambda:api.call('/api/shutdown')['complete'],timeout=65)
                    report['shutdown']=api.call('/api/shutdown')
                    api.call('/api/shutdown/exit',{})
                    service.wait(timeout=15)
                report['service_returncode']=service.returncode
                assert service.returncode==0
                with sqlite3.connect((Path(workspace)/'manager.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                    report['worker_leases']=db.execute('SELECT * FROM worker_leases').fetchall()
                assert report['worker_leases']==[]
    report['workspace_removed']=not Path(workspace).exists()
    report['passed']=report.get('reproduction_passed',False) and report['workspace_removed']
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'report':str(output/'verification.json')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=('chromium','firefox'),default='chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();check(args.output.absolute(),args.engine)
