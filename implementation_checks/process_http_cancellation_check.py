"""Actual HTTP disconnects cancel and join the assigned process for every reader.

Supersedes the in-process callback instrumentation in the historical I2/I6–I9
fixtures. Production HTTP routes, ASGI middleware, ReadPool and operation
implementations remain active. A test-only registry inserts uncooperative work
while holding a real private history connection; killing that exact read-only
child is the required recovery, not a cooperative callback inside a dead child.
"""
from __future__ import annotations
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

from zombie_sim.read_tasks import ReadOperationRegistry, ReadPool
from issue2_check import Api, until
from launcher_check import process_alive

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = ('snapshot', 'metrics', 'cohort_view', 'timeline', 'comparison')


def publish(path, value):
    temporary = path.with_suffix(path.suffix + '.partial')
    temporary.write_text(json.dumps(value))
    os.replace(temporary, path)


class GatedReadOperations(ReadOperationRegistry):
    def execute(self, operation, args, kwargs):
        directory = Path(self.manager.root) / 'cancellation-gates'
        for candidate in sorted(directory.glob(operation + '-*.gate.json')):
            claim = candidate.with_suffix('.claimed')
            try:
                with claim.open('x'): pass
            except FileExistsError:
                continue
            spec = json.loads(candidate.read_text())
            private = self.manager.history(spec['run_id'])
            marker = candidate.with_suffix('.entered')
            try:
                cursor = private.head()  # The child owns a real open reader.
                publish(marker, {'pid': os.getpid(), 'operation': operation,
                                 'run_id': spec['run_id'], 'cursor': cursor})
                deadline = time.monotonic() + 60
                while not candidate.with_suffix('.release').exists():
                    if time.monotonic() > deadline:
                        raise TimeoutError('Disposable uncooperative reader gate was not released')
                    time.sleep(.01)
            finally:
                private.close()
                candidate.with_suffix('.closed').touch()
            break
        return super().execute(operation, args, kwargs)


def serve(workspace, port):
    import uvicorn
    from fastapi import Body
    from zombie_sim.server import create_app
    from zombie_sim.services import WorkspaceServices
    services = WorkspaceServices(workspace, readers_factory=lambda root: ReadPool(root, size=2, registry_factory=GatedReadOperations))
    app = create_app(workspace, services=services)
    root = Path(workspace)
    gates = root / 'cancellation-gates'; gates.mkdir()

    @app.post('/__process_test/gate')
    def arm(body: dict = Body(...)):
        name = body['operation'] + '-' + body['name']
        path = gates / (name + '.gate.json')
        assert not path.exists()
        publish(path, body)
        return {'path': str(path)}

    @app.get('/__process_test/status')
    def status():
        return {'pool': services.readers.status(), 'leases': services.manager.catalog.lease_count()}

    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')


def audit(workspace, identities):
    result = {}
    for identity in identities:
        path = Path(workspace) / 'runs' / identity / 'run.sqlite'
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            tables = {}
            for table in ('commits', 'events', 'runtime_commits', 'control_commands'):
                rows = db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
                tables[table] = hashlib.sha256(repr(rows).encode()).hexdigest()
            result[identity] = tables
    with sqlite3.connect((Path(workspace)/'manager.sqlite').as_uri()+'?mode=ro', uri=True) as db:
        result['catalog'] = {table: hashlib.sha256(repr(db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()).encode()).hexdigest()
                             for table in ('commands', 'runs', 'views', 'worker_leases')}
    return result


def check(output):
    output.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'operations': [], 'replaces': ['issue2_disconnect_check', 'issue6_disconnect_check',
              'issue7_disconnect_check', 'issue8_disconnect_check', 'issue9_disconnect_check'],
              'scope': 'real HTTP/ASGI + process cancellation, exact child identity, private history, unchanged independent response and durable audit'}
    with TemporaryDirectory(prefix='deep-oop-http-cancel-') as workspace:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
        env = {**os.environ, 'PYTHONPATH': str(ROOT/'src')+':'+str(ROOT/'implementation_checks'), 'PYTHONDONTWRITEBYTECODE': '1'}
        connections = []; owned_pids = set()
        with (output/'service.log').open('w') as log:
            service = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve', workspace, '--port', str(port)],
                                       cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            api = Api(port)
            try:
                def ready():
                    if service.poll() is not None: raise AssertionError('Disposable service exited')
                    try: return api.call('/__process_test/status')
                    except OSError: return None
                until(ready, timeout=15, description='disposable process-reader service')
                identities = []; sources = []
                for seed in (41, 42):
                    identity = api.call('/api/runs', {'config': {'seed': seed, 'horizon': 3,
                        'agents': [{'id':'a','type':'Human','x':10,'y':10}], 'decision_mode':'scripted',
                        'execution': {'workers': 1}}, 'command_id': 'create-'+str(seed)})['run_id']
                    api.command(identity, 'step'); api.command(identity, 'terminate')
                    until(lambda: api.row(identity)['resource_status']['cleanup_complete'], description='writer cleanup')
                    row = api.row(identity); identities.append(identity)
                    sources.append({'run_id': identity, 'time': str(row['frontier']['time']), 'revision': str(row['frontier']['revision'])})
                identity = identities[0]
                api.call(f'/api/runs/{identity}/cohorts', {'name':'all identities', 'mode':'dynamic', 'predicate':{}, 'include_dead':True})
                initial_audit = audit(workspace, identities)
                for operation in OPERATIONS:
                    path = {'snapshot': f'/api/runs/{identity}/view', 'metrics': f'/api/runs/{identity}/metrics',
                            'cohort_view': f'/api/runs/{identity}/cohorts?with_cursor=true', 'timeline': f'/api/runs/{identity}/timeline',
                            'comparison': '/api/comparison'}[operation]
                    body = {'sources': sources} if operation == 'comparison' else None
                    expected = api.call(path, body)
                    def begin(name):
                        gate = Path(api.call('/__process_test/gate', {'operation': operation, 'name': name, 'run_id': identity})['path'])
                        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=20); connections.append(connection)
                        cookie = '; '.join(cookie.name+'='+cookie.value for processor in api.opener.handlers
                                           if hasattr(processor, 'cookiejar') for cookie in processor.cookiejar)
                        connection.request('GET' if body is None else 'POST', path, body=None if body is None else json.dumps(body),
                                           headers={'Content-Type':'application/json', 'Cookie':cookie})
                        marker = gate.with_suffix('.entered')
                        until(marker.exists, timeout=10, description=name+' owned reader entry')
                        record = json.loads(marker.read_text()); owned_pids.add(record['pid'])
                        assert process_alive(record['pid'])
                        return connection, gate, record['pid']
                    obsolete, old_gate, old_pid = begin('obsolete')
                    independent, keep_gate, keep_pid = begin('independent')
                    assert old_pid != keep_pid
                    old_status = api.call('/__process_test/status')['pool']; assert old_status['active'] == 2
                    obsolete.sock.shutdown(socket.SHUT_RDWR); obsolete.close()
                    until(lambda: not process_alive(old_pid), timeout=5, description='exact cancelled child exit')
                    assert process_alive(keep_pid), 'Cancelling one request killed an independent reader'
                    status = until(lambda: (value if (value:=api.call('/__process_test/status'))['pool']['active']==1 else None),
                                   timeout=5, description='cancelled request releases its slot')
                    assert old_pid not in status['pool']['processes'] and not old_gate.with_suffix('.closed').exists()
                    assert status['pool']['cancelled'] == old_status['cancelled'] + 1
                    keep_gate.with_suffix('.release').touch()
                    response = independent.getresponse(); actual = json.loads(response.read())
                    assert response.status == 200 and actual == expected
                    independent.close(); assert keep_gate.with_suffix('.closed').exists()
                    retry = api.call(path, body); assert retry == expected
                    status = until(lambda: (value if not (value:=api.call('/__process_test/status'))['pool']['active'] else None),
                                   timeout=5, description='reader requests quiesce')
                    processes = set(status['pool']['processes']); owned_pids.update(processes)
                    assert keep_pid in processes and old_pid not in processes and len(processes)==2
                    assert status['pool']['queued']==0 and status['leases']==0
                    assert audit(workspace, identities)==initial_audit
                    report['operations'].append({'operation':operation,'cancelled_pid':old_pid,'independent_pid':keep_pid,
                        'replacement_pid':next(pid for pid in processes if pid != keep_pid),'exact_child_joined':True,
                        'independent_result_unchanged':True,'retry_result_unchanged':True,'private_reader_closed':True,
                        'no_active_or_queued_reads':True,'no_writer_lease':True,'durable_audit_unchanged':True})
                report['passed'] = True
            finally:
                for connection in connections: connection.close()
                for gate in (Path(workspace)/'cancellation-gates').glob('*.gate.json'): gate.with_suffix('.release').touch()
                if service.poll() is None:
                    service.terminate(); service.wait(timeout=30)
                until(lambda: not any(process_alive(pid) for pid in owned_pids), timeout=10, description='all owned reader processes exit')
                report['service_and_readers_exited'] = True
                (output/'verification.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--output',type=Path)
    parser.add_argument('--serve');parser.add_argument('--port',type=int);args=parser.parse_args()
    if args.serve: serve(args.serve,args.port)
    else: check(args.output)
