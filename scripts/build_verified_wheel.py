"""Build from clean staging and verify an isolated, dependency-free installation.

Run only after the packaged Python sources, README and GUI build are final.
This script never copies a prior build directory or compiled bytecode cache.
"""
from __future__ import annotations
import argparse
import base64
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile


def digest(content):return hashlib.sha256(content).hexdigest()


def run(command,*,cwd=None,env=None):
    result=subprocess.run(command,cwd=cwd,env=env,text=True,capture_output=True)
    if result.returncode:raise RuntimeError(f"Command failed: {command!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


ISOLATED_CHECK=r'''
import importlib.metadata,importlib.resources,json,pathlib,re,sys,sysconfig
from zombie_sim import Simulation
from zombie_sim.registry import ACTIONS,ROLES,ONTOLOGY_DIR
from zombie_sim.policies import MODEL_VERSION
root=pathlib.Path(sys.argv[1]);result_path=pathlib.Path(sys.argv[2])
import zombie_sim
installed=pathlib.Path(zombie_sim.__file__).parent.resolve()
assert installed.is_relative_to(pathlib.Path(sys.prefix)),(installed,sys.prefix)
assert not any('workspace/zombie_game_simulation' in p for p in sys.path),sys.path
assert len(ACTIONS)==29 and len(ROLES)==8
assert ONTOLOGY_DIR.resolve()==installed/'spec/formal_v0.1'
assert importlib.metadata.version('zombie-sim')=='0.1.0'
config={'preset':'small','seed':451,'horizon':3,'execution':{'workers':1},
        'agents':[{'id':'h','type':'Human','x':10,'y':10,'stamina':80}]}
simulation=Simulation(config,history_path=root/'run.sqlite',decision_mode='scripted')
try:
    assert simulation.state['agents']['h']['model_assignment']['version']==MODEL_VERSION
    simulation.submit_intents({'id':'wait','actor':'h','action':'wait','parameters':{'duration':'1'}})
    simulation.advance_until('1',return_snapshot=False)
    occurrence=next(iter(simulation.occurrences.values()))
    assert occurrence['result']=='SUCCEEDED' and occurrence['resolved_at']=='1'
    saved=simulation.checkpoint(root/'core.checkpoint.json')
finally:simulation.close()
resumed=Simulation.restore(saved,history_path=root/'restored.sqlite')
try:
    resumed.submit_intents({'id':'move','actor':'h','action':'move','parameters':{
        'duration':'1','path':[{'x':10,'y':10,'offset':'0'},{'x':12,'y':10,'offset':'1'}]}})
    resumed.advance_until('2',return_snapshot=False)
    agent=resumed.snapshot()['agents']['h']
    assert agent['x']==12 and abs(agent['stamina']-79.8)<1e-12,agent
    assert next(o for o in resumed.occurrences.values() if o['intent_id']=='move')['result']=='SUCCEEDED'
finally:resumed.close()
resources=importlib.resources.files('zombie_sim')
index=resources.joinpath('static/index.html').read_text()
references=re.findall(r'(?:src|href)="(/assets/[^"?#]+)',index)
assert references,index
assets=[]
for reference in references:
    content=resources.joinpath('static'+reference).read_bytes()
    assert content
    assets.append({'path':reference,'bytes':len(content)})
third_party=sorted({module.__name__.split('.')[0] for module in tuple(sys.modules.values())
                    if getattr(module,'__file__',None) and '/site-packages/' in str(module.__file__)})
assert third_party==['zombie_sim'],third_party
report={'isolated_core_import':True,'isolated_path':str(installed),'python':sys.version,
        'python_executable':sys.executable,'isolated_prefix':sys.prefix,
        'registry_actions':len(ACTIONS),'registry_roles':len(ROLES),'utility_model_version':MODEL_VERSION,
        'bundled_ontology_path':str(ONTOLOGY_DIR),'core_scripted_execution':True,
        'checkpoint_restore_and_continuation':True,'loaded_third_party_roots':third_party,
        'core_dependency_policy':'fresh venv, --no-deps install, isolated Python; stdlib only',
        'installed_static_index_loaded':True,'installed_static_assets_loaded':assets}
result_path.write_text(json.dumps(report,indent=2)+'\n')
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--builder',default='.venv-training/bin/python')
    parser.add_argument('--isolated-python',default='/usr/bin/python3.12')
    parser.add_argument('--output',default='artifacts/distributions')
    args=parser.parse_args()
    source=Path(__file__).resolve().parents[1];output=(source/args.output).resolve();output.mkdir(parents=True,exist_ok=True)
    # Preserve the venv executable path rather than dereferencing its symlink.
    builder=Path(os.path.abspath(source/args.builder))
    stage=Path(tempfile.mkdtemp(prefix='zombie-sim-final-wheel-'));package=source/'src/zombie_sim'
    manifest={}
    for path in sorted(package.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix in {'.pyc','.pyo'}:continue
        relative=path.relative_to(source)
        destination=stage/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,destination)
        manifest[str(path.relative_to(source/'src'))] = digest(path.read_bytes())
    for name in ('pyproject.toml','README.md'):
        shutil.copy2(source/name,stage/name)
    readme_sha=digest((source/'README.md').read_bytes())
    ontology=[]
    for path in sorted((package/'spec').rglob('*')):
        if path.is_file():
            original=source/'ontology'/path.relative_to(package/'spec')
            if not original.is_file() or original.read_bytes()!=path.read_bytes():raise AssertionError(f'Bundled ontology differs from {original}')
            ontology.append(str(path.relative_to(package)))
    build_command=[str(builder),'-c',"import json,setuptools,setuptools.build_meta,setuptools.command.bdist_wheel,wheel; print(json.dumps({'python':__import__('sys').version,'setuptools':setuptools.__version__,'wheel':wheel.__version__,'wheel_module':wheel.__file__})); print(setuptools.build_meta.build_wheel('wheels'))"]
    build_log=run(build_command,cwd=stage)
    (stage/'build.log').write_text(build_log)
    wheels=list((stage/'wheels').glob('*.whl'))
    if len(wheels)!=1:raise AssertionError(f'Expected one clean wheel, got {wheels}')
    wheel=wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        packaged={name for name in archive.namelist() if name.startswith('zombie_sim/') and not name.endswith('/')}
        if packaged!=manifest.keys():raise AssertionError({'missing':sorted(manifest.keys()-packaged),'extra':sorted(packaged-manifest.keys())})
        for name,checksum in manifest.items():
            if digest(archive.read(name))!=checksum:raise AssertionError(f'Wheel source mismatch: {name}')
        if any('__pycache__' in name or name.endswith(('.pyc','.pyo')) for name in archive.namelist()):raise AssertionError('Compiled cache packaged')
        record_name=next(name for name in archive.namelist() if name.endswith('.dist-info/RECORD'))
        record_rows=list(csv.reader(io.StringIO(archive.read(record_name).decode())))
        for name,encoded,size in record_rows:
            if not encoded:continue
            content=archive.read(name);expected='sha256='+base64.urlsafe_b64encode(hashlib.sha256(content).digest()).decode().rstrip('=')
            if encoded!=expected or int(size)!=len(content):raise AssertionError(f'Wheel RECORD mismatch: {name}')
        metadata=archive.read(next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))).decode()
        if metadata.split('\n\n',1)[1].rstrip('\n')!=(source/'README.md').read_text().rstrip('\n'):raise AssertionError('Wheel README metadata differs')
    environment={key:value for key,value in os.environ.items() if key not in {'PYTHONPATH','PYTHONHOME','ZOMBIE_ONTOLOGY_DIR'}}
    isolated=stage/'isolated';run([args.isolated_python,'-m','venv','--without-pip',str(isolated)],env=environment)
    install_command=[sys.executable,'-m','pip','--python',str(isolated/'bin/python'),'install','--no-index','--no-deps','--no-compile','--disable-pip-version-check',str(wheel)]
    (stage/'install.log').write_text(run(install_command,cwd=stage,env=environment))
    isolated_check=stage/'isolated_check.py';isolated_check.write_text(ISOLATED_CHECK)
    isolated_report=stage/'isolated_core.json'
    run([str(isolated/'bin/python'),'-I',str(isolated_check),str(stage),str(isolated_report)],cwd=stage,env=environment)
    result=json.loads(isolated_report.read_text());installed=Path(result['isolated_path'])
    for name,checksum in manifest.items():
        if digest((installed.parent/name).read_bytes())!=checksum:raise AssertionError(f'Installed source mismatch: {name}')
        if digest((source/'src'/name).read_bytes())!=checksum:raise AssertionError(f'Workspace changed during packaging: {name}')
    if digest((source/'README.md').read_bytes())!=readme_sha:raise AssertionError('README changed during packaging')
    final=output/wheel.name;temporary=output/(wheel.name+'.partial');shutil.copy2(wheel,temporary);os.replace(temporary,final)
    build_versions=json.loads(build_log.splitlines()[0])
    report={'wheel':str(final),'sha256':digest(final.read_bytes()),'bytes':final.stat().st_size,
            'built_at':datetime.now(timezone.utc).isoformat(),'build_command':build_command,'build_versions':build_versions,
            'install_command':install_command,'clean_staging':str(stage),'packaged_files':len(manifest),
            'all_packaged_source_bytes_current':True,'all_installed_source_bytes_current':True,
            'record_hashes_verified':len(record_rows)-1,'readme_current':True,'readme_sha256':readme_sha,
            'bundled_ontology_matches_authoritative_sources':ontology,'packaged_sha256':manifest,**result}
    (output/'wheel_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    shutil.copy2(isolated_report,output/'isolated_core.json')
    (output/'staging.json').write_text(json.dumps({'stage':str(stage),'source':str(source),'wheel_dir':str(output)},indent=2)+'\n')
    shutil.copy2(stage/'build.log',output/'build.log');shutil.copy2(stage/'install.log',output/'install.log')
    print(json.dumps({'status':'PASS','wheel':str(final),'sha256':report['sha256'],'packaged_files':len(manifest),'verification':str(output/'wheel_verification.json')},indent=2))


if __name__=='__main__':main()
