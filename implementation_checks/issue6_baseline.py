"""Reproduce I06 Statistics behavior using an isolated pre-fix package copy."""
from pathlib import Path
import argparse,json,os,socket,subprocess,sys,tempfile,uuid
from issue5_check import Api,until,serve,NODE_MODULES,ROOT

def check(output,source):
    output.mkdir(parents=True,exist_ok=True); report={'passed':False,'source':str(source)}
    try:
        with tempfile.TemporaryDirectory(prefix='zombie-issue6-baseline-') as workspace:
            with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            env=dict(os.environ,PYTHONPATH=str(source),PYTHONDONTWRITEBYTECODE='1',NODE_PATH=NODE_MODULES)
            with (output/'service.log').open('w') as log:
                process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--serve',workspace,'--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                report.update(workspace=workspace,port=port,service_pid=process.pid); api=Api(port)
                try:
                    def ready():
                        try:return api.call('/__issue5/diagnostics')
                        except OSError:return None
                    until(ready)
                    config={'scenario':'issue6_baseline_probe','seed':123,'horizon':30,'population':{'humans':16,'zombies':4},'execution':{'workers':1},'checkpoint_interval':1000}
                    run=api.call('/api/runs',{'config':config,'command_id':str(uuid.uuid4())})['run_id']
                    until(lambda:next(r for r in api.call('/api/runs') if r['id']==run)['status']=='paused')
                    result=subprocess.run([str(ROOT/'.runtimeenv/bin/node'),str(ROOT/'gui/verify_issue6_baseline.cjs'),api.base,str(output),run],cwd=ROOT,env=env,text=True,capture_output=True,timeout=150)
                    (output/'browser.log').write_text(result.stdout+result.stderr); report['browser']=json.loads((output/'browser.json').read_text())
                    assert result.returncode==0,result.stdout+result.stderr
                    report['passed']=True
                finally:
                    if process.poll() is None:process.terminate()
                    try:process.wait(timeout=30)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                    report['service_exited']=process.poll() is not None
        report['workspace_removed']=not Path(report['workspace']).exists()
    finally:(output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'report':str(output/'verification.json')},indent=2))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--serve');p.add_argument('--port',type=int);p.add_argument('--source',type=Path);p.add_argument('--output',type=Path,default=ROOT/'artifacts/issue6-baseline');a=p.parse_args()
    if a.serve:serve(a.serve,a.port)
    else:check(a.output.absolute(),a.source)
