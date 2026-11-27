"""Independent I26 browser verification using a disposable production service."""
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


def audit(workspace, identity):
    root = Path(workspace)
    with sqlite3.connect((root / 'manager.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        row = db.execute('SELECT status,generation,frontier,config FROM runs WHERE id=?', (identity,)).fetchone()
        commands = db.execute('SELECT id,operation,status,response FROM commands WHERE run_id=? ORDER BY created,id', (identity,)).fetchall()
    with sqlite3.connect((root / 'runs' / identity / 'run.sqlite').as_uri() + '?mode=ro', uri=True) as db:
        history = db.execute('SELECT revision,checksum FROM commits ORDER BY revision').fetchall()
    return {'status': row[0], 'generation': row[1], 'frontier': json.loads(row[2]),
            'config': json.loads(row[3]), 'commands': commands,
            'history_sha256': hashlib.sha256(json.dumps(history).encode()).hexdigest()}


def serve(workspace, port):
    from zombie_sim.server import create_app, run_service
    app = create_app(workspace)
    @app.get('/fixture/audit/{identity}')
    def read_audit(identity: str):
        return audit(workspace, identity)
    run_service(app, host='127.0.0.1', port=port, log_level='warning')


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'engine': engine, 'purpose': 'I26 independent post-fix browser verification'}
    try:
        with tempfile.TemporaryDirectory(prefix='zombie-issue26-fix-') as workspace:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1', NODE_PATH=NODE_MODULES)
            with (output / 'service.log').open('w') as log:
                service = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve', workspace, '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                api = Api(port)
                try:
                    def ready():
                        if service.poll() is not None: raise AssertionError('Service exited before startup')
                        try: return isinstance(api.call('/api/runs'), list)
                        except OSError: return False
                    until(ready)
                    source = {'scenario': 'issue26_copy_source', 'seed': 26, 'horizon': 10,
                              'world': {'length': 100, 'width': 80}, 'execution': {'workers': 1},
                              'barriers': [{'id': 'block', 'footprint': [40, 25, 50, 35]}],
                              'stockpiles': [{'id': 'stock', 'x': 70, 'y': 60, 'inventory': {'FOOD': 7}}],
                              'agents': [{'id': 'h', 'type': 'Human', 'x': 10, 'y': 10},
                                         {'id': 'z', 'type': 'Zombie', 'x': 90, 'y': 70}]}
                    source_id = api.call('/api/runs', {'config': source, 'command_id': str(uuid.uuid4())})['run_id']
                    report['source_before'] = audit(workspace, source_id)
                    (output / 'fixture.json').write_text(json.dumps({'source_id': source_id}) + '\n')
                    with (output / 'browser.log').open('w') as browser_log:
                        result = subprocess.run([str(ROOT / '.runtimeenv/bin/node'), str(ROOT / 'implementation_checks/issue26_fix_browser.cjs'), api.base, str(output), engine], cwd=ROOT, env=env, stdout=browser_log, stderr=subprocess.STDOUT, timeout=480)
                    report['browser'] = json.loads((output / 'browser.json').read_text())
                    assert result.returncode == 0, 'Browser check failed; inspect browser.log. ' + report['browser'].get('error', '')[:3000]
                    report['source_after'] = audit(workspace, source_id)
                    assert report['source_after'] == report['source_before'], 'Copy/edit changed source run'
                    report['runs'] = api.call('/api/runs')
                    assert len(report['runs']) == 2
                    assert report['browser']['launched_run_id'] != source_id
                    report['verification_passed'] = True
                finally:
                    if service.poll() is None:
                        api.call('/api/shutdown', {'mode': 'terminate', 'timeout': 60})
                        until(lambda: api.call('/api/shutdown')['complete'], timeout=65)
                        report['shutdown'] = api.call('/api/shutdown')
                        api.call('/api/shutdown/exit', {})
                        service.wait(timeout=15)
                    report['service_returncode'] = service.returncode
                    assert service.returncode == 0
                    with sqlite3.connect((Path(workspace) / 'manager.sqlite').as_uri() + '?mode=ro', uri=True) as db:
                        report['worker_leases'] = db.execute('SELECT * FROM worker_leases').fetchall()
                    assert report['worker_leases'] == []
        report['workspace_removed'] = not Path(workspace).exists()
        report['passed'] = report.get('verification_passed', False) and report['workspace_removed']
    finally:
        if 'workspace' in locals(): report['workspace_removed'] = not Path(workspace).exists()
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'report': str(output / 'verification.json')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('chromium', 'firefox'), default='chromium')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--serve'); parser.add_argument('--port', type=int)
    args = parser.parse_args()
    if args.serve: serve(args.serve, args.port)
    else: check(args.output.absolute(), args.engine)
