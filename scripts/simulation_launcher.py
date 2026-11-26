"""Friendly local simulation controls. Run ./simulate for the interactive menu.

All run mutations use the existing HTTP command journal. Only launcher-owned,
identity-verified services can be signalled; run history is never deleted.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import http.cookiejar
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
TERMINAL = {'completed', 'terminated'}


class LauncherError(Exception):
    pass


class CommandRejected(LauncherError):
    def __init__(self, response):
        super().__init__(response.get('error', 'The command was rejected.'))
        self.response = response


def say(message):
    print(message, flush=True)


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise LauncherError(f'Cannot read {path}: {error}') from error


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x') as output:
            json.dump(data, output, indent=2, allow_nan=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        temporary.replace(path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def process_identity(pid):
    """Linux PID identity, including start ticks to reject PID reuse."""
    try:
        proc = Path('/proc') / str(int(pid))
        fields = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if fields[0] == 'Z':
            return None
        return {'start_ticks': fields[19], 'uid': proc.stat().st_uid,
                'argv': (proc / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')}
    except (OSError, ValueError, IndexError):
        return None


class API:
    def __init__(self, port):
        self.url = f'http://127.0.0.1:{port}'
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, endpoint, payload=None, timeout=40):
        data = None if payload is None else json.dumps(payload, allow_nan=False).encode()
        request = urllib.request.Request(self.url + endpoint, data=data,
                                         headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read().decode(errors='replace')
            try:
                body = json.loads(body).get('error', body)
            except (ValueError, AttributeError):
                pass
            raise LauncherError(f'Service returned HTTP {error.code}: {str(body)[:500]}') from error
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise LauncherError(f'Cannot read the service at {self.url}: {error}') from error


class Launcher:
    def __init__(self, workspace, port=8767, timeout=900):
        self.workspace = Path(workspace).expanduser().resolve()
        self.port, self.timeout = port, timeout
        self.private = self.workspace / '.launcher'
        self.record_path = self.private / 'server.json'
        self.api = None
        self.record = None

    @contextmanager
    def startup_lock(self):
        import fcntl
        self.private.mkdir(parents=True, exist_ok=True)
        with (self.private / 'startup.lock').open('a+') as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise LauncherError('Another launcher is starting this workspace. Retry shortly.') from error
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def owns_process(self, record):
        identity = process_identity(record.get('pid', 0))
        return bool(identity and identity['uid'] == os.getuid()
                    and identity['start_ticks'] == record.get('start_ticks')
                    and str(ROOT / 'scripts/launcher_service.py') in identity['argv']
                    and '--instance' in identity['argv']
                    and record.get('instance') in identity['argv'])

    def verify_service(self, record):
        api = API(int(record['port']))
        info = api.request('/api/launcher', timeout=3)
        if (info.get('schema') != 'zombie-sim/launcher-v1'
                or info.get('workspace') != str(self.workspace)
                or info.get('instance') != record.get('instance')
                or info.get('pid') != record.get('pid')
                or not self.owns_process(record)):
            raise LauncherError('Service identity does not match this workspace. Nothing was stopped.')
        self.api, self.record = api, record
        return api

    def connect(self, *, start=False):
        with self.startup_lock():
            if self.record_path.exists():
                record = read_json(self.record_path)
                if record.get('workspace') != str(self.workspace):
                    raise LauncherError('Saved launcher metadata belongs to a different workspace.')
                if self.owns_process(record):
                    # A live but unreachable service must never be replaced by a second writer.
                    return self.verify_service(record)
            if not start:
                raise LauncherError('This workspace has no running launcher service. Use ./simulate gui or start.')
            candidate = API(self.port)
            try:
                candidate.request('/api/launcher', timeout=2)
            except LauncherError as error:
                # Distinguish a closed TCP port from an occupied/unrecognized HTTP service.
                import socket
                with socket.socket() as probe:
                    probe.settimeout(1)
                    occupied = probe.connect_ex(('127.0.0.1', self.port)) == 0
                if occupied:
                    raise LauncherError(f'Port {self.port} is occupied by another service. '
                                        'It was left untouched. Choose a different --port and workspace.') from error
            else:
                raise LauncherError(f'Port {self.port} already hosts a service not owned by this launcher '
                                    'record. It was left untouched. Choose another --port/workspace.')
            self._start_service()
            return self.api

    def _start_service(self):
        instance = uuid.uuid4().hex
        log_path = self.private / 'service.log'
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONDONTWRITEBYTECODE='1')
        # New session prevents Ctrl+C in the menu from interrupting live workers.
        process, record = None, None
        try:
            with log_path.open('ab', buffering=0) as log:
                process = subprocess.Popen(
                    [sys.executable, str(ROOT / 'scripts/launcher_service.py'),
                     '--workspace', str(self.workspace), '--port', str(self.port), '--instance', instance],
                    cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    start_new_session=True, close_fds=True)
            identity = process_identity(process.pid)
            if identity is None:
                raise LauncherError(f'The service could not start. See {log_path}')
            record = {'schema': 'zombie-sim/launcher-v1', 'workspace': str(self.workspace),
                      'pid': process.pid, 'start_ticks': identity['start_ticks'],
                      'instance': instance, 'port': self.port, 'log': str(log_path)}
            write_json(self.record_path, record)
        except BaseException:
            # If publishing ownership fails, do not leave an unrecorded child.
            # This Popen handle is the unreaped child just created here (no PID reuse).
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    say(f'Startup cleanup is pending for service PID {process.pid}; log: {log_path}')
            raise
        say('Starting the local simulation service…')
        deadline = time.monotonic() + min(self.timeout, 40)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                tail = log_path.read_text(errors='replace')[-1600:]
                raise LauncherError(f'The service did not start.\n{tail}\nLog: {log_path}')
            try:
                self.verify_service(record)
                say(f'Ready: {self.api.url}\nWorkspace: {self.workspace}')
                return
            except LauncherError:
                time.sleep(.2)
        raise LauncherError(f'Service startup is still pending. Log: {log_path}\n'
                            'Do not start a second service for this workspace.')

    def rows(self):
        return self.api.request('/api/runs')

    def show_runs(self):
        rows = self.rows()
        if not rows:
            say('No simulations yet. Choose Start a small simulation.')
            return rows
        say('\n  #  Run ID         Status         Time (s)  Scenario')
        for index, row in enumerate(rows, 1):
            say(f"{index:3}  {row['id'][:12]:12}   {row['status']:13}  "
                f"{str(row.get('frontier', {}).get('time', '0')):>8}  "
                f"{row['config'].get('scenario', 'simulation')}")
        say('Use a run number or an unambiguous ID prefix.\n')
        return rows

    def select_run(self, value=None):
        rows = self.rows() if value else self.show_runs()
        if not rows:
            raise LauncherError('There are no runs in this workspace.')
        if value is None:
            if not sys.stdin.isatty():
                raise LauncherError('Supply a run ID or number; use ./simulate list to see runs.')
            value = input('Which run? (Enter to cancel): ').strip()
            if not value:
                return None
        # Exact IDs take precedence over menu numbers and prefixes.
        matches = [row for row in rows if row['id'] == value]
        if not matches and value.isdigit() and 1 <= int(value) <= len(rows):
            matches = [rows[int(value) - 1]]
        if not matches:
            matches = [row for row in rows if row['id'].startswith(value)]
        if len(matches) != 1:
            raise LauncherError('That selection is missing or ambiguous. Use ./simulate list and a longer ID.')
        return matches[0]

    def saved_request(self, kind, endpoint, payload):
        command_id = payload['command_id']
        record = {'schema': 'zombie-sim/launcher-command-v1', 'workspace': str(self.workspace),
                  'kind': kind, 'endpoint': endpoint, 'payload': payload,
                  'command_id': command_id, 'status': 'pending'}
        path = self.private / 'requests' / (command_id + '.json')
        write_json(path, record)
        say(f'Request reference: {command_id}')
        return record

    def wait_result(self, command_id, *, deadline=None):
        deadline = deadline or time.monotonic() + self.timeout
        next_message = time.monotonic() + 5
        while time.monotonic() < deadline:
            response = self.api.request('/api/commands/' + command_id)
            if response['status'] != 'pending':
                if response['status'] != 'applied':
                    raise CommandRejected(response)
                return response
            if time.monotonic() >= next_message:
                say('Still waiting for the run to finish its current work/checkpoint…')
                next_message = time.monotonic() + 10
            time.sleep(.25)
        raise LauncherError('The command is still pending; it has not been cancelled.')

    def leases(self):
        path = self.workspace / 'manager.sqlite'
        if not path.exists():
            return []
        try:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
                return db.execute('SELECT run_id,pid FROM worker_leases').fetchall()
        except sqlite3.Error as error:
            raise LauncherError(f'Cannot verify worker cleanup: {error}') from error

    def pending_for_run(self, run_id):
        path = self.workspace / 'manager.sqlite'
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            return bool(db.execute(
                "SELECT 1 FROM commands WHERE run_id=? AND status='pending' "
                "AND operation NOT IN ('create','branch') LIMIT 1", (run_id,)).fetchone())

    def wait_worker(self, run_id, *, allow_failed=False):
        deadline = time.monotonic() + self.timeout
        announced = False
        while time.monotonic() < deadline:
            if not any(identity == run_id for identity, _ in self.leases()):
                row = next(row for row in self.rows() if row['id'] == run_id)
                if row['status'] == 'failed' and not allow_failed:
                    raise LauncherError(row.get('error') or 'Worker finalization failed; inspect the service log.')
                return
            if not announced:
                say('Finishing worker cleanup; existing history is being kept…')
                announced = True
            time.sleep(.25)
        raise LauncherError('Worker cleanup is still pending. The service was left running.')

    def execute_saved(self, record):
        command_id = record['command_id']
        path = self.private / 'requests' / (command_id + '.json')
        try:
            self.api.request(record['endpoint'], record['payload'])
            result = self.wait_result(command_id)
            if record['kind'] == 'start':
                result = self.wait_result(command_id + ':start')
            operation = record['payload'].get('operation')
            if operation in {'stop', 'terminate'}:
                self.wait_worker(result['run_id'])
            record.update(status='applied', response=result)
            write_json(path, record)
            row = next(row for row in self.rows() if row['id'] == result['run_id'])
            say(f"Run {row['id']} — {row['status']} at {row.get('frontier', {}).get('time', '?')} s.")
            if operation == 'terminate':
                say('Terminated without requesting another checkpoint. Existing history was retained.')
            elif operation == 'stop':
                say('Saved and stopped. Use resume to continue this run later.')
            return result
        except CommandRejected as error:
            record.update(status='rejected', response=error.response, last_error=str(error))
            write_json(path, record)
            say('This request was rejected. Check the current run status before issuing a new command; '
                'retrying this reference will keep its original result.')
            raise
        except (LauncherError, KeyboardInterrupt) as error:
            record.update(status='unresolved', last_error=str(error) or 'Interrupted while waiting')
            write_json(path, record)
            say(f'Keep this reference. To reconcile the same request, use: retry {command_id}')
            raise

    def start_run(self, scenario='small', *, workers=None, seed=None, horizon=None, browser=True):
        from zombie_sim.config import resolve_config
        path = ROOT / 'configs' / f'{scenario}.toml' if scenario in {'small', 'baseline'} else Path(scenario).expanduser()
        if not path.is_file():
            raise LauncherError(f'Configuration file not found: {path}')
        from zombie_sim.config_io import loads
        config = loads(path.read_text(), 'json' if path.suffix.lower() == '.json' else 'toml')
        if workers is not None:
            config.setdefault('execution', {})['workers'] = workers
        if seed is not None:
            config['seed'] = seed
        if horizon is not None:
            config['horizon'] = horizon
        config = resolve_config(config)
        self.connect(start=True)
        if config.get('population', {}).get('humans', 0) + config.get('population', {}).get('zombies', 0) >= 1000:
            say('Starting a large scenario. Initialization and checkpoints may take several minutes.')
        payload = {'config': config, 'command_id': str(uuid.uuid4()), 'start': True}
        result = self.execute_saved(self.saved_request('start', '/api/runs', payload))
        self.open_gui(browser=browser)
        return result

    def control(self, operation, value=None, *, shutting_down=False):
        self.connect()
        row = self.select_run(value)
        if row is None:
            return
        pending = self.pending_for_run(row['id'])
        if not pending and ((operation == 'stop' and row['status'] == 'stopped')
                            or (operation == 'terminate' and row['status'] == 'terminated')):
            if operation in {'stop', 'terminate'}:
                self.wait_worker(row['id'])
            say(f"Run {row['id']} is already {row['status']}. No new command was needed.")
            return
        if row['status'] in TERMINAL:
            raise LauncherError(f"This run is {row['status']}; create a new simulation instead.")
        if not pending and operation == 'terminate' and row['status'] in {'stopped', 'failed', 'interrupted'}:
            self.wait_worker(row['id'], allow_failed=True)
            say(f"Run {row['id']} is already inactive ({row['status']}). No worker was restarted or checkpoint written.")
            return
        payload = {'operation': operation, 'command_id': str(uuid.uuid4())}
        if not shutting_down:
            payload['generation'] = row['generation']
        return self.execute_saved(self.saved_request('control', f"/api/runs/{row['id']}/commands", payload))

    def retry(self, command_id):
        self.connect()
        try:
            command_id = str(uuid.UUID(command_id))
        except ValueError as error:
            raise LauncherError('Use the full request reference printed when the command was submitted.') from error
        record = read_json(self.private / 'requests' / (command_id + '.json'))
        if (record.get('schema') != 'zombie-sim/launcher-command-v1'
                or record.get('workspace') != str(self.workspace)
                or record.get('command_id') != command_id
                or record.get('payload', {}).get('command_id') != command_id):
            raise LauncherError('The saved request does not belong to this workspace.')
        if record.get('kind') == 'start':
            valid = record.get('endpoint') == '/api/runs' and record['payload'].get('start') is True
        else:
            parts = record.get('endpoint', '').split('/')
            valid = (record.get('kind') == 'control' and len(parts) == 5 and parts[1:3] == ['api', 'runs']
                     and parts[4] == 'commands' and record['payload'].get('operation') in
                     {'pause', 'continue', 'stop', 'terminate', 'checkpoint'})
        if not valid:
            raise LauncherError('Unsupported saved request. No request was sent.')
        return self.execute_saved(record)

    def requests(self):
        paths = sorted((self.private / 'requests').glob('*.json'))
        records = [read_json(path) for path in paths]
        unresolved = [record for record in records if record.get('status') != 'applied']
        if not unresolved:
            say('No unresolved launcher requests.')
        for record in unresolved:
            say(f"{record['command_id']}  {record['payload'].get('operation', 'start')}  {record['status']}")

    def open_gui(self, *, browser=True):
        say(f'GUI: {self.api.url}')
        if browser:
            if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
                say('Open that address in your browser on this computer.')
            else:
                try:
                    if not webbrowser.open(self.api.url, new=2):
                        say('Could not open a browser automatically; use the address above.')
                except webbrowser.Error:
                    say('Could not open a browser automatically; use the address above.')

    def shutdown(self, *, terminate=False):
        self.connect()
        operation = 'terminate' if terminate else 'stop'
        say('Ending active runs in this launcher workspace ' +
            ('without requesting new checkpoints.' if terminate else 'and saving resumable runs.'))
        self.api.request('/api/launcher/drain', {'instance': self.record['instance']})
        # Earlier HTTP handlers can have queued commands. Reconcile those before
        # deciding a saved run is inactive, so a queued resume cannot be missed.
        database = self.workspace / 'manager.sqlite'
        with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
            pending = [row[0] for row in db.execute(
                "SELECT id FROM commands WHERE status='pending' AND operation NOT IN ('create','branch') ORDER BY created,id")]
        for command_id in pending:
            try:
                self.wait_result(command_id)
            except CommandRejected:
                pass
        for row in self.rows():
            if row['status'] not in TERMINAL | {'stopped', 'failed'}:
                self.control(operation, row['id'], shutting_down=True)
            else:
                self.wait_worker(row['id'], allow_failed=True)
        if self.leases():
            raise LauncherError('Worker leases remain. Service shutdown was cancelled; inspect the run status/log.')
        # Refresh identity at the last possible moment; never signal a foreign service.
        self.verify_service(self.record)
        pid = self.record['pid']
        pidfd = os.pidfd_open(pid) if hasattr(os, 'pidfd_open') else None
        try:
            if not self.owns_process(self.record):
                raise LauncherError('Service process identity changed. Nothing was signalled.')
            if pidfd is not None and hasattr(signal, 'pidfd_send_signal'):
                signal.pidfd_send_signal(pidfd, signal.SIGTERM)
            else:
                os.kill(pid, signal.SIGTERM)
        finally:
            if pidfd is not None:
                os.close(pidfd)
        say('Stopping the web service. Close its browser tabs if shutdown is waiting…')
        deadline = time.monotonic() + self.timeout
        while self.owns_process(self.record):
            if time.monotonic() >= deadline:
                raise LauncherError('The service is still shutting down. It has not been force-killed. '
                                    f"See {self.record['log']}")
            time.sleep(.25)
        say(f'All runs and the web service are stopped. History is kept in {self.workspace}')


def menu(launcher):
    say('\nZombie Simulation — start, inspect, and stop your runs')
    say(f'Workspace: {launcher.workspace}\nLeaving this menu does not stop running simulations.')
    while True:
        say('\n  1  Start a small simulation\n  2  Start the 1,000-agent baseline\n'
            '  3  Start from a configuration file\n  4  Show simulations\n'
            '  5  Pause a run\n  6  Continue a saved or paused run\n'
            '  7  Stop and save a run\n  8  Terminate a run without another save\n'
            '  9  Open the GUI\n 10  Shut down all runs and the web service\n'
            ' 11  Review/retry an unresolved request\n  0  Leave the menu')
        try:
            choice = input('\nChoose a number: ').strip()
            if choice == '0':
                say('Menu closed. Any running simulations continue. Use ./simulate shutdown to stop everything.')
                return 0
            if choice in {'1', '2', '3'}:
                scenario = {'1': 'small', '2': 'baseline'}.get(choice)
                if scenario is None:
                    scenario = input('Configuration file (.toml or .json; Enter to cancel): ').strip()
                if scenario:
                    launcher.start_run(scenario)
            elif choice == '4':
                launcher.connect(start=True)
                launcher.show_runs()
            elif choice in {'5', '6', '7', '8'}:
                launcher.control({'5': 'pause', '6': 'continue', '7': 'stop', '8': 'terminate'}[choice])
            elif choice == '9':
                launcher.connect(start=True)
                launcher.open_gui()
            elif choice == '10':
                say('  1  Save runs for later, then shut down (default)\n'
                    '  2  Terminate runs without another checkpoint, then shut down\n  0  Cancel')
                mode = input('Choose [1]: ').strip() or '1'
                if mode in {'1', '2'}:
                    launcher.shutdown(terminate=mode == '2')
            elif choice == '11':
                launcher.requests()
                reference = input('Request reference to retry (Enter to cancel): ').strip()
                if reference:
                    launcher.retry(reference)
            else:
                say('Please choose one of the numbers above.')
        except (EOFError, KeyboardInterrupt):
            say('\nMenu closed. Runs were not force-stopped. Use ./simulate shutdown when ready.')
            return 0
        except (LauncherError, ValueError, OSError) as error:
            say(f'\nCould not finish: {error}')


def worker_argument(value):
    if value == 'auto':
        return value
    try:
        count = int(value)
        if count > 0:
            return count
    except ValueError:
        pass
    raise argparse.ArgumentTypeError('Choose auto or a positive integer.')


def main(argv=None):
    parser = argparse.ArgumentParser(prog='./simulate', description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--workspace', type=Path, default=ROOT / 'runs/launcher', help='Persistent workspace (default: runs/launcher)')
    parser.add_argument('--port', type=int, default=8767, help='Local HTTP port for a new service (default: 8767)')
    parser.add_argument('--timeout', type=float, default=900, help='Seconds to wait for commands/cleanup (default: 900)')
    sub = parser.add_subparsers(dest='action')
    sub.add_parser('menu', help='Interactive menu (the default)')
    start = sub.add_parser('start', help='Create and start a simulation')
    start.add_argument('scenario', nargs='?', default='small', help='small, baseline, or a TOML/JSON path')
    start.add_argument('--workers', type=worker_argument)
    start.add_argument('--seed', type=int)
    start.add_argument('--horizon', type=float)
    start.add_argument('--no-browser', action='store_true')
    sub.add_parser('list', help='Show run IDs, states and simulated times')
    for name in ('pause', 'resume', 'stop', 'terminate'):
        command = sub.add_parser(name, help={'pause': 'Pause a run', 'resume': 'Continue a paused/stopped run',
                                           'stop': 'Save and stop a run', 'terminate': 'End a run without another checkpoint'}[name])
        command.add_argument('run', nargs='?', help='Run ID/prefix or list number; omitted prompts interactively')
    gui = sub.add_parser('gui', help='Start/reuse the local service and open the GUI')
    gui.add_argument('--no-browser', action='store_true')
    shutdown = sub.add_parser('shutdown', help='Save all runs and shut down the owned web service')
    shutdown.add_argument('--terminate', action='store_true', help='Terminate active runs instead of saving; already stopped runs stay unchanged')
    retry = sub.add_parser('retry', help='Reconcile an exact saved request without duplicating its effects')
    retry.add_argument('command_id')
    sub.add_parser('requests', help='Show unresolved request references')
    args = parser.parse_args(argv)
    if sys.version_info < (3, 12):
        parser.error('Python 3.12 or later is required.')
    if sys.platform != 'linux':
        parser.error('This launcher currently supports Linux process identity and file leases.')
    if not 1 <= args.port <= 65535 or not 0 < args.timeout <= 86400:
        parser.error('Use a port from 1 to 65535 and a timeout between 0 and 86400 seconds.')
    launcher = Launcher(args.workspace, args.port, args.timeout)
    try:
        if args.action in {None, 'menu'}:
            if not sys.stdin.isatty():
                parser.print_help()
                return 0
            return menu(launcher)
        if args.action == 'start':
            launcher.start_run(args.scenario, workers=args.workers, seed=args.seed,
                               horizon=args.horizon, browser=not args.no_browser)
        elif args.action == 'list':
            launcher.connect()
            launcher.show_runs()
        elif args.action in {'pause', 'resume', 'stop', 'terminate'}:
            launcher.control('continue' if args.action == 'resume' else args.action, args.run)
        elif args.action == 'gui':
            launcher.connect(start=True)
            launcher.open_gui(browser=not args.no_browser)
        elif args.action == 'shutdown':
            launcher.shutdown(terminate=args.terminate)
        elif args.action == 'retry':
            launcher.retry(args.command_id)
        elif args.action == 'requests':
            launcher.requests()
        return 0
    except KeyboardInterrupt:
        say('\nStopped waiting. A submitted command may still complete. Use requests/retry to check it.')
        return 130
    except (LauncherError, ValueError, OSError) as error:
        say(f'Could not finish: {error}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
