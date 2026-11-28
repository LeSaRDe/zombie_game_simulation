"""Behavior-preserving service extraction checks against retained Python sources.

The baseline is optional for future checkouts; all ownership, extension and real
export-worker checks run independently. Only disposable histories are written.
"""
from __future__ import annotations
import importlib
import json
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
BASELINE = ROOT / 'artifacts/oop-refactor/baseline-package/zombie_sim'
from zombie_sim.application import RunManager
from zombie_sim.config import ConfigurationService
from zombie_sim.config_io import ConfigurationCodec
from zombie_sim.engine import Simulation
from zombie_sim.export_jobs import ExportJobs, ExportService, ExportRendererRegistry, FORMATS
from zombie_sim.metrics import MetricsService
from zombie_sim.read_tasks import ReadOperationRegistry, ReadPool
from zombie_sim.services import WorkspaceServices
from zombie_sim.storage import canonical
from zombie_sim.testing_browser_exports import read_artifact


class ExtendedReadOperations(ReadOperationRegistry):
    def __init__(self, manager):
        super().__init__(manager)
        self.register('workspace_run_count', lambda: len(self.manager.list_runs()))


def baseline_modules():
    name = '_zombie_oop_baseline'
    package = types.ModuleType(name)
    package.__path__ = [str(BASELINE)]
    sys.modules[name] = package
    # These unchanged wire/ontology dependencies intentionally use the same
    # authoritative inputs. Every compared algorithm comes from retained source.
    for module in ('storage', 'domain', 'geometry', 'registry', 'runtime'):
        sys.modules[name + '.' + module] = importlib.import_module('zombie_sim.' + module)
    return {module: importlib.import_module(name + '.' + module)
            for module in ('config', 'config_io', 'visualization', 'metrics', 'comparison',
                           'timeline', 'cohort_survival', 'application', 'export_jobs')}


class ServiceChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old = baseline_modules() if BASELINE.is_dir() else None

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='zombie-oop-services-')
        self.root = Path(self.temporary.name)
        self.config = {
            'seed': 73, 'horizon': 4, 'incubation_duration': 2,
            'decision_mode': 'scripted', 'execution': {'workers': 1},
            'agents': [{'id': 'walker', 'type': 'Human', 'x': 10, 'y': 10},
                       {'id': 'infected', 'type': 'Human', 'x': 50, 'y': 50, 'infected': True}],
        }
        for identity in ('first', 'second'):
            directory = self.root / 'runs' / identity
            directory.mkdir(parents=True)
            simulation = Simulation(self.config, history_path=directory / 'run.sqlite', run_id=identity)
            try:
                simulation.submit_intents([{'actor': 'walker', 'action': 'move', 'parameters': {
                    'duration': 4, 'path': [{'x': 10, 'y': 10, 'offset': 0}, {'x': 18, 'y': 10, 'offset': 4}]}}])
                simulation.advance_until(4, return_snapshot=False)
                (directory / 'manifest.json').write_text(canonical({
                    'run_id': identity, 'config': simulation.config, 'status': 'terminated'}))
            finally:
                simulation.close()
        self.workspace = WorkspaceServices(self.root)
        self.manager = self.workspace.manager

    def tearDown(self):
        self.workspace.close()
        self.temporary.cleanup()

    def same(self, left, right):
        self.assertEqual(canonical(left), canonical(right))

    def test_configuration_round_trip_and_injected_agent_factory(self):
        made = []
        from zombie_sim.domain import make_agent
        def factory(*args, **kwargs):
            made.append(args[0])
            return make_agent(*args, **kwargs)
        configuration = ConfigurationService(agent_factory=factory)
        world = configuration.initialize(self.config)
        self.assertEqual(made, ['walker', 'infected'])
        self.assertEqual(set(world['agents']), set(made))
        for format in ('json', 'toml'):
            encoded = configuration.dumps(self.config, format)
            self.same(configuration.loads(encoded, format), self.config)
        isolated = ConfigurationService()
        configuration.defaults['horizon'] = 17
        self.assertNotEqual(configuration.defaults['horizon'], isolated.defaults['horizon'])

    @unittest.skipUnless(BASELINE.is_dir(), 'Retained pre-refactor sources are unavailable')
    def test_configuration_and_projected_views_are_byte_equivalent(self):
        current = ConfigurationService()
        for config in ({}, self.config, {'preset': 'baseline'}):
            self.same(current.resolve(config), self.old['config'].resolve_config(config))
        self.same(current.initialize(self.config), self.old['config'].initialize_world(self.config))
        for format in ('json', 'toml'):
            self.assertEqual(current.dumps(self.config, format), self.old['config_io'].dumps(self.config, format))
        invalid = {**self.config, 'agents': [{'id': 'outside', 'type': 'Human', 'x': -1, 'y': 0}]}
        messages = []
        for resolver in (current.resolve, self.old['config'].resolve_config):
            with self.assertRaises(ValueError) as caught:
                resolver(invalid)
            messages.append(str(caught.exception))
        self.assertEqual(messages[0], messages[1])
        old = self.old['application'].RunManager(self.root, read_only=True)
        try:
            for time_cursor in ('0', '1/3', '1', '2', '3', '4'):
                self.same(self.manager.snapshot('first', time_cursor), old.snapshot('first', time_cursor))
            history = self.manager.history('first')
            try:
                self.assertEqual(self.workspace.visualization.replay_animation(history, end='4'),
                                 self.old['visualization'].replay_animation(history, end='4'))
            finally:
                history.close()
        finally:
            old.close()

    @unittest.skipUnless(BASELINE.is_dir(), 'Retained pre-refactor sources are unavailable')
    def test_analysis_queries_are_byte_equivalent(self):
        old = self.old['application'].RunManager(self.root, read_only=True)
        self.manager.save_cohort('first', {'name': 'Human entry', 'mode': 'fixed', 'predicate': {'type': 'Human'},
                                           'reference_time': '0', 'reference_revision': '0'})
        history = self.manager.history('first')
        try:
            for end in ('1/3', '1', '2', '4', '1', '4'):
                self.same(self.workspace.metrics.sampled_metrics(history, end=end, interval='1/3'),
                          self.old['metrics'].sampled_metrics(history, end=end, interval='1/3'))
            for cursor in ('0', '1/3', '2', '4'):
                self.same(self.manager.cohort_view('first', cursor), old.cohort_view('first', cursor))
                self.same(self.manager.timeline('first', time=cursor, limit=3), old.timeline('first', time=cursor, limit=3))
            sources = [{key: self.manager.read_head(identity)[key] for key in ('run_id', 'time', 'revision')}
                       for identity in ('first', 'second')]
            self.same(self.manager.comparison(sources), old.comparison(sources))
        finally:
            history.close()
            old.close()

    def test_metric_caches_are_owned_and_return_detached_results(self):
        first, second = MetricsService(capacity=2), MetricsService(capacity=1)
        history = self.manager.history('first')
        try:
            result = first.sampled_metrics(history, end='2')
            result['samples'][0]['healthy'] = -100
            self.assertGreaterEqual(first.sampled_metrics(history, end='2')['samples'][0]['healthy'], 0)
            self.assertGreater(first.metric_cache_info()['entries'], 0)
            self.assertEqual(second.metric_cache_info()['entries'], 0)
            second.close()
            self.assertGreater(first.metric_cache_info()['entries'], 0)
            first.close()
            self.assertEqual(first.metric_cache_info()['entries'], 0)
        finally:
            history.close()

    def test_read_operation_extension_runs_in_owned_child(self):
        readers = ReadPool(self.root, size=1, registry_factory=ExtendedReadOperations)
        try:
            self.assertEqual(readers.call('workspace_run_count'), 2)
            view = readers.call('snapshot', 'first', '1/3')
            self.assertEqual(view['time'], '1/3')
            self.assertEqual(readers.status()['active'], 0)
        finally:
            readers.close()
        self.assertEqual(readers.status()['processes'], [])

    def test_export_strategies_and_real_pool_jobs(self):
        service = ExportService(visualization=self.workspace.visualization)
        jobs = self.workspace.exports
        for format in FORMATS:
            request = {'format': format, 'time': '2', 'interval': ['0', '4'], 'sample_interval': '1', 'cohort': 'all'}
            prepared = service.prepare(self.manager, 'first', request)
            payload, metadata = service.render(*prepared, format)
            if self.old:
                old_prepared = self.old['export_jobs'].prepare_export(self.manager, 'first', request)
                self.same(prepared, old_prepared)
                old_payload, old_metadata = self.old['export_jobs'].render_export(*old_prepared, format)
                self.assertEqual(payload, old_payload)
                self.same(metadata, old_metadata)
            job = jobs.create('first', request)
            deadline = time.monotonic() + 30
            while job['status'] not in {'COMPLETED', 'FAILED', 'CANCELLED'} and time.monotonic() < deadline:
                time.sleep(.01)
                job = jobs.get(job['id'])
            self.assertEqual(job['status'], 'COMPLETED', job)
            artifact = read_artifact({'path': str(jobs.path(job['id'])), 'provenance_path': str(jobs.path(job['id'], True))})
            self.assertEqual(float(artifact['source_scene']['agents']['walker']['x']), 14)
            self.assertEqual(jobs.path(job['id']).read_bytes(), payload)
        jobs.arm_pause('first')
        job = jobs.create('first', {'format': 'replay_animation', 'time': '2', 'interval': ['0', '4']})
        result = jobs.cancel(job['id'])
        self.assertEqual((result['status'], result['active_tasks']), ('CANCELLED', 0))
        class ExactCursorRenderer:
            def render(self, source_scene, rows, frames, provenance):
                return provenance['time'].encode()
        registry = ExportRendererRegistry.builtins()
        registry.register('exact_cursor', ExactCursorRenderer())
        custom = ExportService(renderers=registry)
        prepared = custom.prepare(self.manager, 'first', {'format': 'exact_cursor', 'time': '1/3', 'interval': ['0', '1']})
        self.assertEqual(custom.render(*prepared, 'exact_cursor')[0], b'1/3')

    def test_owned_run_worker_checkpoints_and_releases_lease(self):
        from zombie_sim.application import RunWorker
        from zombie_sim.command_recovery import reply
        receipt = reply(self.manager, self.manager.create(self.config, 'oop-worker-create'))
        identity = receipt['run_id']
        advanced = self.manager.command(identity, 'advance', {'command_id': 'oop-worker-advance', 'time': '1'})
        self.assertEqual(advanced['status'], 'applied')
        checkpoint = self.manager.command(identity, 'checkpoint', {'command_id': 'oop-worker-checkpoint', 'name': 'oop-boundary'})
        self.assertEqual(checkpoint['status'], 'applied')
        directory = Path(self.manager._row(identity)['directory'])
        self.assertTrue((directory / 'checkpoints/oop-boundary.json').is_file())
        terminated = self.manager.command(identity, 'terminate', {'command_id': 'oop-worker-terminate'})
        self.assertEqual(terminated['status'], 'applied')
        process = self.manager.processes[identity]
        process.join(timeout=10)
        self.assertFalse(process.is_alive())
        self.assertEqual(self.manager.repository.lease_count(), 0)
        status = next(run for run in self.manager.list_runs() if run['id'] == identity)
        self.assertTrue(status['resource_status']['cleanup_complete'])
        unused = RunWorker(self.root, 'not-launched')
        unused.close()
        unused.close()
        with self.assertRaisesRegex(RuntimeError, 'closed'):
            unused.run()

    def test_live_view_session_preserves_ack_and_terminal_race(self):
        import asyncio
        from copy import deepcopy
        from types import SimpleNamespace
        from zombie_sim.server import LiveViewSession
        from issue1_stream_check import FakeSocket, head, bundle
        for terminal_race in (True, False):
            current = head(status="running" if terminal_race else "paused")
            calls = {"snapshots": 0, "idle": 0}
            def snapshot(operation, identity, *, cancel_event):
                self.assertEqual(operation, 'snapshot')
                self.assertFalse(cancel_event.is_set())
                calls['snapshots'] += 1
                if terminal_race and calls['snapshots'] == 1:
                    current.update(head(revision=9, generation=2, status="terminated"))
                    return bundle(current, revision=7)
                return bundle(current)
            def idle():
                calls['idle'] += 1
                if calls['idle'] == 1:
                    current['generation'] = 2
                    return {'ping': True}
                raise RuntimeError('Fixture disconnect')
            shutdown = SimpleNamespace(draining=False, sockets=set())
            session = LiveViewSession(SimpleNamespace(read_head=lambda _: deepcopy(current)),
                                      SimpleNamespace(call=snapshot), shutdown, 'local-token', lambda _: True)
            socket = FakeSocket('local-token', None if terminal_race else idle)
            # The collaborators here are synchronous fakes. Real thread/process
            # execution is covered by the reader/export and service-drain tests.
            from unittest.mock import patch
            async def dispatch(function, *args, **kwargs):
                return function(*args, **kwargs)
            with patch('zombie_sim.server.asyncio.to_thread', dispatch):
                asyncio.run(asyncio.wait_for(session.run(socket, 'fixture'), timeout=3))
            self.assertEqual(socket.acks, ['9'] if terminal_race else ['7', '7'])
            self.assertEqual(calls['snapshots'], 2)
            self.assertEqual(socket.closes, [1000])
            self.assertTrue(session.cancel_event.is_set())
            self.assertEqual(shutdown.sockets, set())

    def test_lazy_pool_creation_has_one_owner_under_concurrency(self):
        from concurrent.futures import ThreadPoolExecutor
        created = []
        class Reader:
            closed = 0
            def close(self):
                self.closed += 1
        def factory(root):
            reader = Reader()
            created.append(reader)
            return reader
        workspace = WorkspaceServices(self.root / 'independent', readers_factory=factory)
        try:
            with ThreadPoolExecutor(max_workers=8) as executor:
                readers = list(executor.map(lambda _: workspace.readers, range(32)))
            self.assertEqual(len(created), 1)
            self.assertTrue(all(reader is created[0] for reader in readers))
        finally:
            workspace.close()
        self.assertEqual(created[0].closed, 1)

    def test_workspace_closes_shared_resources_once(self):
        self.assertIs(self.workspace.queries, self.manager.queries)
        self.assertIs(self.workspace.metrics, self.manager.comparisons.metrics)
        self.manager.snapshot('first')
        self.workspace.close()
        self.workspace.close()
        self.assertEqual(self.manager.head_diagnostics()['active_connections'], 0)
        for name in ('readers', 'exports', 'shutdown'):
            with self.assertRaisesRegex(RuntimeError, 'closed'):
                getattr(self.workspace, name)


if __name__ == '__main__':
    unittest.main(verbosity=2)
