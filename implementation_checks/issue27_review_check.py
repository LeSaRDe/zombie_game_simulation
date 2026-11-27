"""Reproduce I27 against unchanged production assets in a disposable workspace."""
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
from issue26_fix_check import audit

EXACT_TIME = '127500000000000017/2500000000000000'


def check(output, engine):
    output.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'engine': engine, 'purpose': 'I27 pre-fix browser reproduction', 'exact_time': EXACT_TIME}
    try:
        with tempfile.TemporaryDirectory(prefix='zombie-issue27-review-') as workspace:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
            env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1', NODE_PATH=NODE_MODULES)
            with (output / 'service.log').open('w') as log:
                service = subprocess.Popen([sys.executable, '-m', 'zombie_sim.cli', 'gui', '--experiments-dir', workspace, '--port', str(port)], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                api = Api(port)
                try:
                    def ready():
                        if service.poll() is not None: raise AssertionError('Disposable service exited before startup')
                        try: return isinstance(api.call('/api/runs'), list)
                        except OSError: return False
                    until(ready)
                    ids = []
                    for seed in [27, 28]:
                        config = {'scenario': f'issue27_fractional_clock_{seed}', 'seed': seed, 'horizon': 100,
                                  'world': {'length': 300, 'width': 300}, 'execution': {'workers': 1},
                                  'placement': {'minimum_separation': 0, 'cross_type_separation': 0},
                                  'agents': [{'id': 'h', 'type': 'Human', 'x': 20, 'y': 20},
                                             {'id': 'z', 'type': 'Zombie', 'x': 250, 'y': 250}]}
                        identity = api.call('/api/runs', {'config': config, 'command_id': str(uuid.uuid4())})['run_id']
                        api.command(identity, 'advance', time=EXACT_TIME)
                        row = api.row(identity)
                        assert row['frontier']['time'] == EXACT_TIME, row['frontier']
                        api.call(f'/api/runs/{identity}/cohorts', {'name': 'Fractional reference', 'mode': 'fixed', 'predicate': {}, 'include_dead': True, 'reference_time': EXACT_TIME, 'reference_revision': row['frontier']['revision']})
                        ids.append(identity)
                    report['before'] = {identity: audit(workspace, identity) for identity in ids}
                    (output / 'fixture.json').write_text(json.dumps({'run_ids': ids, 'exact_time': EXACT_TIME}) + '\n')
                    with (output / 'browser.log').open('w') as browser_log:
                        result = subprocess.run([str(ROOT / '.runtimeenv/bin/node'), str(ROOT / 'implementation_checks/issue27_review_browser.cjs'), api.base, str(output), engine], cwd=ROOT, env=env, stdout=browser_log, stderr=subprocess.STDOUT, timeout=180)
                    report['browser'] = json.loads((output / 'browser.json').read_text())
                    assert result.returncode == 0, report['browser'].get('error', '')[:3000]
                    report['after'] = {identity: audit(workspace, identity) for identity in ids}
                    assert report['before'] == report['after'], 'Read-only navigation changed source histories or commands'
                    report['reproduction_passed'] = True
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
        report['passed'] = report.get('reproduction_passed', False) and report['workspace_removed']
    finally:
        if 'workspace' in locals(): report['workspace_removed'] = not Path(workspace).exists()
        (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'passed': report['passed'], 'report': str(output / 'verification.json')}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('chromium', 'firefox'), default='chromium')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(); check(args.output.absolute(), args.engine)
