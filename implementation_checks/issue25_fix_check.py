"""Verify I25 in real browsers with disposable services and read-only ledger audits."""
from __future__ import annotations
import argparse
import hashlib
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


def audit(workspace, identity=None, through=None):
    root=Path(workspace)
    with sqlite3.connect((root/'manager.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        commands=db.execute('SELECT id,run_id,operation,status FROM commands ORDER BY created,id').fetchall()
    result={'commands':commands}
    if identity:
        with sqlite3.connect((root/'runs'/identity/'run.sqlite').as_uri()+'?mode=ro',uri=True) as db:
            db.execute('BEGIN')
            head=db.execute('SELECT revision,time_n,time_d,seconds FROM commits ORDER BY revision DESC LIMIT 1').fetchone()
            revision=head[0] if through is None else int(through)
            prefix=db.execute('SELECT revision,checksum FROM commits WHERE revision<=? ORDER BY revision',(revision,)).fetchall()
        result.update(head={'revision':str(head[0]),'time':f'{head[1]}/{head[2]}','seconds':head[3]},through=str(revision),prefix_count=len(prefix),prefix_sha256=hashlib.sha256(json.dumps(prefix).encode()).hexdigest())
    return result


def serve(workspace,port):
    from zombie_sim.server import create_app, run_service
    app=create_app(workspace)
    @app.get('/fixture/audit')
    def read_audit(run_id:str|None=None,through:str|None=None):
        return audit(workspace,run_id,through)
    run_service(app,host='127.0.0.1',port=port,log_level='warning')


def check(output,engine):
    output.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'engine':engine,'purpose':'post-fix independent I25 verification'}
    try:
        with tempfile.TemporaryDirectory(prefix='zombie-issue25-fix-') as workspace:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1',NODE_PATH=NODE_MODULES)
            with (output/'service.log').open('w') as log:
                service=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--serve',workspace,'--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                api=Api(port)
                try:
                    def available():
                        if service.poll() is not None:raise AssertionError('Service exited before startup')
                        try:return isinstance(api.call('/api/runs'),list)
                        except OSError:return False
                    until(available)
                    ids={}
                    for name,horizon,advance in [('primary',600,'3'),('alternate',600,'2'),('completion',5,'2')]:
                        config={'scenario':f'issue25_{name}','seed':25,'horizon':horizon,'world':{'length':300,'width':300},'execution':{'workers':1},'placement':{'minimum_separation':0,'cross_type_separation':0},'agents':[{'id':'h1','type':'Human','x':20,'y':20},{'id':'h2','type':'Human','x':25,'y':20},{'id':'z1','type':'Zombie','x':200,'y':200},{'id':'z2','type':'Zombie','x':205,'y':200}]}
                        identity=api.call('/api/runs',{'config':config,'command_id':str(uuid.uuid4())})['run_id'];ids[name]=identity
                        api.command(identity,'advance',time=advance)
                        if name=='primary':
                            api.call(f'/api/runs/{identity}/cohorts',{'name':'All initial identities','mode':'fixed','predicate':{},'include_dead':True,'reference_time':'0','reference_revision':'0'})
                    api.command(ids['primary'],'start')
                    report.update(run_ids=ids,before=audit(workspace,ids['primary']))
                    (output/'fixture.json').write_text(json.dumps(ids))
                    with (output/'browser.log').open('w') as browser_log:
                        result=subprocess.run([str(ROOT/'.runtimeenv/bin/node'),str(ROOT/'implementation_checks/issue25_fix_browser.cjs'),api.base,str(output),engine],cwd=ROOT,env=env,stdout=browser_log,stderr=subprocess.STDOUT,timeout=360)
                    report['browser']=json.loads((output/'browser.json').read_text())
                    assert result.returncode==0,(output/'browser.log').read_text()
                    report['after']=audit(workspace,ids['primary'],report['before']['through'])
                    assert report['before']['prefix_sha256']==report['after']['prefix_sha256'],'Existing ledger history changed'
                    assert report['after']['head']['seconds']>report['before']['head']['seconds']
                    assert api.row(ids['primary'])['status']=='terminated'
                    assert api.row(ids['completion'])['status']=='completed'
                    report['verification_passed']=True
                finally:
                    if service.poll() is None:
                        api.call('/api/shutdown',{'mode':'terminate','timeout':60})
                        until(lambda:api.call('/api/shutdown')['complete'],timeout=65)
                        report['shutdown']=api.call('/api/shutdown')
                        api.call('/api/shutdown/exit',{});service.wait(timeout=15)
                    report['service_returncode']=service.returncode
                    assert service.returncode==0
                    with sqlite3.connect((Path(workspace)/'manager.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                        report['worker_leases']=db.execute('SELECT * FROM worker_leases').fetchall()
                    assert report['worker_leases']==[]
        report['workspace_removed']=not Path(workspace).exists()
        report['passed']=report.get('verification_passed',False) and report['workspace_removed']
    finally:
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'report':str(output/'verification.json')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine',choices=('chromium','firefox'),default='chromium')
    parser.add_argument('--output',type=Path)
    parser.add_argument('--serve');parser.add_argument('--port',type=int)
    args=parser.parse_args()
    if args.serve:serve(args.serve,args.port)
    else:check(args.output.absolute(),args.engine)
