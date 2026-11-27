"""Independent I26 deterministic placement checks and actual validation HTTP contract."""
from __future__ import annotations
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
from unittest.mock import patch
from urllib.error import HTTPError

from zombie_sim.config import ConfigError, baseline_config, initialize_world, resolve_config
from zombie_sim.config_io import dumps, loads
from issue2_check import Api, until, ROOT


def check(output):
    report={"passed":False,"checks":[],"scope":"ordinary explicit initial positions; historical state contracts retained"}
    cases=[]
    def case(name,config,valid,*text):
        before=deepcopy(config)
        try:
            with patch('zombie_sim.config._place',side_effect=AssertionError('Validate must not sample')):
                result=resolve_config(config)
            assert valid,(name,'unexpected validation success')
            report['checks'].append({'name':name,'valid':True,'fingerprint':result['fingerprint']})
        except ConfigError as error:
            assert not valid,(name,str(error))
            for expected in text:assert expected in str(error),(name,expected,str(error))
            report['checks'].append({'name':name,'valid':False,'message':str(error),'code':getattr(error,'code',None)})
        assert config==before,(name,'validation mutated caller input')
        cases.append((name,deepcopy(config),valid,text))

    standard={'world':{'length':100,'width':100},'agents':[{'id':'human','type':'Human','x':0,'y':0},{'id':'zombie','type':'Zombie','x':15,'y':0}]}
    case('inclusive cross-type boundary',standard,True)
    case('omitted coordinates and IDs use existing zero defaults',{'agents':[{'type':'Human'}]},True)
    case('explicit array same-type boundary',{'agents':[{'id':'a','x':0,'y':0},{'id':'b','x':2,'y':0}]},True)
    case('explicit map',{'agents':{'first':{'id':'a','x':0,'y':0},'second':{'id':'b','x':2,'y':0}}},True)
    case('zero separation remains explicit supported override',{'agents':[{'id':'a'},{'id':'b','type':'Zombie'}],'placement':{'minimum_separation':0,'cross_type_separation':0}},True)
    for axis in ['x','y']:
        for value,label in [(-.1,'negative'),(100.1,'outside')]:
            case(axis+' '+label,{'agents':[{'id':'boundary',axis:value}]},False,'agents.boundary.'+axis,'outside world.','bounds [0, 100.0]')
    case('non-numeric coordinate',{'agents':[{'id':'typed','x':'5'}]},False,'agents.typed.x','expected a finite')
    case('boolean coordinate',{'agents':[{'id':'typed','x':True}]},False,'agents.typed.x','expected a finite')
    case('malformed agent collection',{'agents':None},False,'agents: expected an array or map')
    case('malformed agent record',{'agents':[None]},False,'agents[0]: expected an agent object')
    case('same-type shrink conflict',{'world':{'length':20,'width':20},'agents':[{'id':'a','x':2,'y':2},{'id':'b','x':3,'y':2}]},False,'agents.a and agents.b','1 m','minimum_separation = 2.0 m')
    case('cross-type shrink conflict',{'world':{'length':20,'width':20},'agents':[{'id':'a','x':2,'y':2},{'id':'b','type':'Zombie','x':4,'y':2}]},False,'agents.a and agents.b','2 m','cross_type_separation = 15.0 m')
    case('cross-type near-boundary distance remains distinguishable',{'agents':[{'id':'a','x':0,'y':0},{'id':'b','type':'Zombie','x':math.nextafter(15.,0.),'y':0}]},False,'14.999999999999998 m','cross_type_separation = 15.0 m')
    case('semantic override owns world bounds',{'world':{'length':100},'semantic':{'world':{'length':20}},'agents':[{'id':'semantic','x':21,'y':2}]},False,'agents.semantic.x','world.length bounds [0, 20]')
    barrier={'id':'wall','type':'Obstacle','footprint':{'xmin':10,'ymin':10,'xmax':15,'ymax':15}}
    case('closed barrier boundary',{'barriers':[barrier],'agents':[{'id':'edge','x':10,'y':12}]},False,'agents.edge','blocking barrier wall')
    case('closed barrier interior',{'barriers':[barrier],'agents':[{'id':'inside','x':12,'y':12}]},False,'agents.inside','blocking barrier wall')
    base=baseline_config()
    shelter=deepcopy(base);shelter['agents']=[{'id':'sheltered','type':'Zombie','x':200,'y':200}]
    case('initial Zombie shelter restriction',shelter,False,'agents.sheltered','inside shelter shelter1')
    shelter['agents'][0]['type']='Human'
    case('initial Human may occupy shelter',shelter,True)
    original=deepcopy(base);original['world']={'length':200,'width':200}
    case('resolver never implicitly rescales baseline geometry',original,False,'barriers[0]','inside world bounds')
    case('unchanged baseline validates without generating positions',base,True)

    # Historical states can contain nearby agents and Zombies already in shelters.
    imported=deepcopy(shelter);imported['state_import']=True
    imported['agents']=[{'id':'h','type':'Human','x':200,'y':200},{'id':'z','type':'Zombie','x':200,'y':200}]
    case('historical positions are not initial placement rules',imported,True)
    history=initialize_world(imported)
    assert history['agents']['h']['x']==history['agents']['z']['x']==200
    assert history['initialization']['sampler']=='validated_explicit_state_v1'
    dead={'state_import':True,'time':'10','agents':[{'id':'dead','life':0,'x':10,'y':10}],
          'remains':[{'id':'body','source_agent_id':'dead','x':10,'y':10,'biomass':4}],
          'barriers':[{'id':'later-wall','type':'Obstacle','footprint':[9,9,11,11]}]}
    case('historical death position and remains may be under later barrier',dead,True)
    state=initialize_world(dead);assert state['remains']['body']['x']==state['agents']['dead']['x']==10
    report['historical_initialization']=['coincident Human/Zombie inside shelter','dead agent/remains inside later barrier']

    # Validate is not a placement proof for generated populations.
    case('generated feasibility is deferred',{'world':{'length':1,'width':1},'population':{'humans':2,'zombies':0}},True)
    for name,config,valid,text in cases:
        if not valid or config.get('state_import') or name in {'unchanged baseline validates without generating positions','generated feasibility is deferred'}:continue
        state=initialize_world(config)
        assert len(state['agents'])==len(config['agents'])
    report['initialization_consistent_with_valid_explicit_cases']=True

    resolved=resolve_config(standard)
    roundtrips=[]
    for fmt in ['json','toml']:
        encoded=dumps(resolved,fmt)
        loaded=loads(encoded,fmt)
        again=resolve_config(loaded)
        assert again['fingerprint']==resolved['fingerprint']
        assert again['agents']==resolved['agents']
        roundtrips.append(fmt)
    report['roundtrips']=roundtrips

    with tempfile.TemporaryDirectory(prefix='zombie-issue26-validation-') as workspace:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        output.parent.mkdir(parents=True,exist_ok=True)
        with output.with_suffix('.service.log').open('w') as log:
            service=subprocess.Popen([sys.executable,'-m','zombie_sim.cli','gui','--experiments-dir',workspace,'--port',str(port)],cwd=ROOT,
                env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1'),stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
            client=Api(port)
            def ready():
                if service.poll() is not None:raise AssertionError('Disposable validation service exited')
                try:return isinstance(client.call('/api/runs'),list)
                except OSError:return False
            until(ready)
            report['http']=[]
            try:
                for name,config,valid,text in cases:
                    try:payload=client.call('/api/config/validate',config);status=200
                    except HTTPError as error:payload=json.loads(error.response_body);status=error.code
                    assert status==(200 if valid else 422),(name,payload)
                    if not valid:
                        for expected in text:assert expected in payload['error'],(name,payload)
                        assert payload['issues'][0]['path']
                    report['http'].append({'name':name,'status':status,'code':payload.get('code')})
                assert client.call('/api/runs')==[]
                with sqlite3.connect((Path(workspace)/'manager.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                    assert db.execute('SELECT COUNT(*) FROM commands').fetchone()[0]==0
                report['runs_created']=0;report['commands_created']=0
            finally:
                if service.poll() is None:
                    client.call('/api/shutdown',{'mode':'terminate','timeout':45})
                    until(lambda:client.call('/api/shutdown')['complete'],timeout=50)
                    report['service_drained']=client.call('/api/shutdown')['complete']
                    client.call('/api/shutdown/exit',{});service.wait(timeout=15)
                report['service_returncode']=service.returncode
                assert service.returncode==0
                with sqlite3.connect((Path(workspace)/'manager.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                    report['worker_leases']=db.execute('SELECT * FROM worker_leases').fetchall()
                assert report['worker_leases']==[]
    report['workspace_removed']=not Path(workspace).exists()
    report['passed']=True
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'passed':True,'checks':len(cases),'http_checks':len(report['http']),'report':str(output)}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();check(args.output)
