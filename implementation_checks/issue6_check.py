"""I06 Statistics integration with disposable real runs and independent history checks."""
from __future__ import annotations
import argparse,hashlib,json,os,socket,sqlite3,subprocess,sys,tempfile,threading,time,uuid
from pathlib import Path
from issue5_check import Api,until,NODE_MODULES,ROOT


def serve(workspace,port):
    import uvicorn
    from zombie_sim.server import create_app
    from zombie_sim.visualization import populations,resources,project_state
    app=create_app(workspace);manager=app.state.manager;lock=threading.Lock();requests=[];active={};maximum={}
    class Trace:
        def __init__(self,app):self.app=app
        async def __call__(self,scope,receive,send):
            key=None
            if scope['type']=='http' and scope['path'].startswith('/api/'):
                key=scope['path']
                with lock:
                    requests.append({'method':scope['method'],'path':key,'query':scope.get('query_string',b'').decode()})
                    active[key]=active.get(key,0)+1;maximum[key]=max(maximum.get(key,0),active[key])
            try:await self.app(scope,receive,send)
            finally:
                if key:
                    with lock:active[key]-=1
    app.add_middleware(Trace)
    @app.get('/__issue6/diagnostics')
    def diagnostics():
        with lock:trace=list(requests);running=dict(active);peaks=dict(maximum)
        return {'pid':os.getpid(),'requests':trace,'active':running,'maximum':peaks,'runs':manager.list_runs()}
    @app.get('/__issue6/audit')
    def audit():
        result=[]
        for row in manager.list_runs():
            digest=hashlib.sha256();ledger=Path(row['directory'])/'run.sqlite';sizes={}
            if ledger.exists():
                with sqlite3.connect(ledger.as_uri()+'?mode=ro',uri=True) as db:
                    for table in ('commits','runtime_commits','events'):
                        count=0;digest.update(table.encode())
                        for record in db.execute(f'SELECT * FROM {table} ORDER BY rowid'):
                            count+=1
                            for value in record:
                                encoded=value if isinstance(value,bytes) else repr(value).encode();digest.update(len(encoded).to_bytes(8,'big'));digest.update(encoded)
                        sizes[table]=count
            with manager.lock:commands=manager.catalog.command_count(row['id'])
            result.append({'id':row['id'],'status':row['status'],'generation':row['generation'],'frontier':row['frontier'],'commands':commands,'history_digest':digest.hexdigest(),'rows':sizes})
        return result
    @app.post('/__issue6/oracle')
    def oracle(body:dict):
        history=manager.history(body['run_id'])
        try:
            data=body['metrics'];checked=[]
            for sample in data['samples']:
                state=project_state(history.state_at(time=sample['time'],revision=int(sample['revision'])),sample['time'])
                expected={**populations(state),'resources':resources(state)}
                for key,value in expected.items():assert sample[key]==value,(sample['time'],sample['revision'],key,sample[key],value)
                checked.append({'time':sample['time'],'revision':sample['revision'],'total':expected['total']})
            expected_events=dict(history.connection.execute('SELECT kind,COUNT(*) FROM events WHERE revision<=? GROUP BY kind',(int(data['revision']),)))
            assert data['event_counts']==expected_events,(data['event_counts'],expected_events)
            return {'passed':True,'samples':checked,'event_counts':expected_events}
        finally:history.close()
    uvicorn.run(app,host='127.0.0.1',port=port,log_level='warning')


def check(output,engine):
    output.mkdir(parents=True,exist_ok=True);report={'passed':False,'engine':engine}
    try:
        with tempfile.TemporaryDirectory(prefix='zombie-issue6-') as workspace:
            with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
            env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1',NODE_PATH=NODE_MODULES)
            with (output/'service.log').open('w') as log:
                process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--serve',workspace,'--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                report.update(workspace=workspace,port=port,service_pid=process.pid);api=Api(port)
                try:
                    def ready():
                        if process.poll() is not None:raise AssertionError('Test service exited')
                        try:return api.call('/__issue6/diagnostics')
                        except OSError:return None
                    until(ready)
                    from zombie_sim.config import baseline_config
                    configs={'small':{'scenario':'issue6_small','seed':123,'horizon':60,'execution':{'workers':1},'checkpoint_interval':1000},'baseline':baseline_config()}
                    configs['baseline'].update(horizon=3,checkpoint_interval=1000);configs['baseline']['execution']={'workers':1}
                    runs={}
                    for name,config in configs.items():
                        started=time.monotonic();receipt=api.call('/api/runs',{'config':config,'command_id':str(uuid.uuid4()),'wait_for_initialization':False});runs[name]=receipt['run_id']
                        until(lambda:next(row for row in api.call('/api/runs') if row['id']==runs[name])['status']=='paused',timeout=240)
                        report.setdefault('initialization_seconds',{})[name]=time.monotonic()-started
                    report['initial_audit']=api.call('/__issue6/audit')
                    result=subprocess.run([str(ROOT/'.runtimeenv/bin/node'),str(ROOT/'gui/verify_issue6.cjs'),api.base,str(output),json.dumps(runs),engine],cwd=ROOT,env=env,text=True,capture_output=True,timeout=360)
                    (output/'browser.log').write_text(result.stdout+result.stderr)
                    report['browser']=json.loads((output/'browser.json').read_text())
                    assert result.returncode==0,result.stdout+result.stderr
                    report['final_audit']=api.call('/__issue6/audit');report['diagnostics']=api.call('/__issue6/diagnostics');report['passed']=True
                finally:
                    if process.poll() is None:process.terminate()
                    try:process.wait(timeout=30)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
                    report['service_exited']=process.poll() is not None
        report['workspace_removed']=not Path(report['workspace']).exists()
    finally:(output/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':report['passed'],'report':str(output/'verification.json')},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--serve');parser.add_argument('--port',type=int);parser.add_argument('--engine',choices=('chromium','firefox'),default='chromium');parser.add_argument('--output',type=Path,default=ROOT/'artifacts/issue6');args=parser.parse_args()
    if args.serve:serve(args.serve,args.port)
    else:check(args.output.absolute(),args.engine)
