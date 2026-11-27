"""Real open/closed browser tabs drain with the production CLI service."""
from __future__ import annotations
import argparse,json,os,socket,sqlite3,subprocess,sys,tempfile
from pathlib import Path
from issue2_check import Api,until,NODE_MODULES,ROOT

def check(output,engine,tabs,mode):
    output.mkdir(parents=True,exist_ok=True)
    report={"passed":False,"engine":engine,"tabs":tabs,"mode":mode}
    try:
        with tempfile.TemporaryDirectory(prefix='zombie-browser-shutdown-') as workspace:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1',NODE_PATH=NODE_MODULES)
            with (output/'service.log').open('w') as log:
                service=subprocess.Popen([sys.executable,'-m','zombie_sim.cli','gui','--experiments-dir',workspace,'--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                api=Api(port);report.update(port=port,workspace=workspace,pid=service.pid)
                try:
                    def ready():
                        if service.poll() is not None:raise AssertionError('service exited')
                        try:return isinstance(api.call('/api/runs'),list)
                        except OSError:return False
                    until(ready)
                    with (output/'browser.log').open('w') as browserlog:
                        result=subprocess.run([str(ROOT/'.runtimeenv/bin/node'),str(ROOT/'gui/verify_shutdown_browser.cjs'),api.base,str(output),engine,tabs,mode],cwd=ROOT,env=env,stdout=browserlog,stderr=subprocess.STDOUT,timeout=180)
                    report['browser']=json.loads((output/'browser.json').read_text())
                    assert result.returncode==0,(output/'browser.log').read_text()
                    service.wait(timeout=30)
                    assert service.returncode==0
                    report['normal_service_exit']=True
                finally:
                    if service.poll() is None:
                        service.terminate()
                        try:service.wait(timeout=45)
                        except subprocess.TimeoutExpired:report['forced_cleanup']=True;service.kill();service.wait(timeout=5)
                    with sqlite3.connect(Path(workspace)/'manager.sqlite') as db:
                        report['worker_leases']=db.execute('SELECT * FROM worker_leases').fetchall()
                        report['pending_commands']=db.execute("SELECT id FROM commands WHERE status='pending'").fetchall()
                    with socket.socket() as probe:report['endpoint_closed']=probe.connect_ex(('127.0.0.1',port))!=0
                    report['application_shutdown_completed']='Application shutdown complete.' in (output/'service.log').read_text()
                    assert not report.get('forced_cleanup') and report['worker_leases']==[] and report['pending_commands']==[] and report['endpoint_closed'] and report['application_shutdown_completed']
        report['workspace_removed']=not Path(workspace).exists()
        report['passed']=report.get('normal_service_exit',False) and report['workspace_removed']
    except BaseException as error:report['error']=repr(error);raise
    finally:(output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'report':str(output/'verification.json')}))
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--engine',choices=('chromium','firefox'),default='chromium');parser.add_argument('--tabs',choices=('open','closed'),default='open');parser.add_argument('--mode',choices=('save','terminate'),default='terminate');parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();check(args.output.absolute(),args.engine,args.tabs,args.mode)
