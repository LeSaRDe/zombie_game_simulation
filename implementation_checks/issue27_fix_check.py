"""Independent I27 browser verification with exact clocks and disposable services."""
from __future__ import annotations
import argparse
import csv
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
from issue26_fix_check import audit
from issue25_fix_check import audit as prefix_audit

EXACT = '127500000000000017/2500000000000000'
NEAR = '510000000000000067/10000000000000000'


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'engine': engine, 'purpose': 'I27 independent post-fix browser verification'}
    try:
        with tempfile.TemporaryDirectory(prefix='zombie-issue27-fix-') as workspace:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT/'src'), PYTHONDONTWRITEBYTECODE='1', NODE_PATH=NODE_MODULES)
            with (output/'service.log').open('w') as log:
                service = subprocess.Popen([sys.executable, '-m', 'zombie_sim.cli', 'gui', '--experiments-dir', workspace, '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                api = Api(port)
                try:
                    def ready():
                        if service.poll() is not None: raise AssertionError('Disposable service exited before startup')
                        try: return isinstance(api.call('/api/runs'), list)
                        except OSError: return False
                    until(ready)
                    ids={}; revisions={}
                    for name,seed in [('primary',27),('other',28),('active',29),('commands',30)]:
                        config={'scenario':f'issue27_{name}','seed':seed,'horizon':600,'interventions_enabled':True,
                                'world':{'length':300,'width':300},'execution':{'workers':1},
                                'placement':{'minimum_separation':0,'cross_type_separation':0},
                                'agents':[{'id':'h','type':'Human','x':20,'y':20},{'id':'z','type':'Zombie','x':250,'y':250}]}
                        identity=api.call('/api/runs',{'config':config,'command_id':str(uuid.uuid4())})['run_id'];ids[name]=identity
                        if name=='active': api.command(identity,'advance',time='3')
                        else:
                            api.command(identity,'advance',time=NEAR)
                            near=api.row(identity)['frontier'];assert near['time']==NEAR,near
                            api.command(identity,'advance',time=EXACT)
                            final=api.row(identity)['frontier'];assert final['time']==EXACT,final
                            revisions[name]={'near':str(near['revision']),'exact':str(final['revision'])}
                            assert revisions[name]['near']!=revisions[name]['exact']
                            api.call(f'/api/runs/{identity}/cohorts',{'name':'Fractional reference','mode':'fixed','predicate':{},'include_dead':True,'reference_time':EXACT,'reference_revision':final['revision']})
                    api.command(ids['active'],'start')
                    report['before']={name:audit(workspace,ids[name]) for name in ['primary','other']}
                    report['active_prefix_before']=prefix_audit(workspace,ids['active'])
                    (output/'fixture.json').write_text(json.dumps({'ids':ids,'revisions':revisions,'exact':EXACT,'near':NEAR})+'\n')
                    with (output/'browser.log').open('w') as browser_log:
                        result=subprocess.run([str(ROOT/'.runtimeenv/bin/node'),str(ROOT/'implementation_checks/issue27_fix_browser.cjs'),api.base,str(output),engine],cwd=ROOT,env=env,stdout=browser_log,stderr=subprocess.STDOUT,timeout=480)
                    report['browser']=json.loads((output/'browser.json').read_text())
                    assert result.returncode==0,report['browser'].get('error','')[:3000]
                    report['after']={name:audit(workspace,ids[name]) for name in ['primary','other']}
                    assert report['before']==report['after'],'Read-only selections changed source histories or commands'
                    report['active_prefix_after']=prefix_audit(workspace,ids['active'],report['active_prefix_before']['through'])
                    assert report['active_prefix_before']['prefix_sha256']==report['active_prefix_after']['prefix_sha256']
                    assert report['active_prefix_after']['head']['seconds']>report['active_prefix_before']['head']['seconds']
                    report['runs']=api.call('/api/runs')
                    for export in report['browser'].get('exports',[]):
                        if export['format']=='table_csv':
                            rows=list(csv.DictReader(Path(export['path']).open()))
                            assert rows and all(row['time']==EXACT for row in rows),rows
                            report['csv_exact_time_oracle']={'rows':len(rows),'time':EXACT}
                            sidecar=json.loads(Path(export['provenance_path']).read_text())
                            assert sidecar['provenance']['time']==EXACT
                            assert sidecar['provenance']['interval']==[EXACT,EXACT]
                            assert sidecar['source_scene']['time']==EXACT
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
        if 'workspace' in locals():report['workspace_removed']=not Path(workspace).exists()
        (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'report':str(output/'verification.json')}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--engine',choices=('chromium','firefox'),default='chromium');p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();check(a.output.absolute(),a.engine)
