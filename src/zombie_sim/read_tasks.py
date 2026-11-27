"""Bounded reusable read-only workers with real, joinable cancellation.

Readers own no writer leases. Cancelling one request replaces only its assigned
child, including when Python/native reconstruction ignores cooperative tokens.
Small pipe messages announce result files, avoiding a blocked large pipe send.
"""
from __future__ import annotations
import multiprocessing
from pathlib import Path
import pickle
import tempfile
import threading
import time
import uuid


def execute(manager, operation, args, kwargs):
    if operation in {'snapshot', 'comparison', 'timeline', 'cohort_view'}:
        return getattr(manager, operation)(*args, **kwargs)
    if operation == 'preview':
        from .config import resolve_config, initialize_world
        from .visualization import view_bundle
        resolved = resolve_config(args[0])
        return {'resolved': resolved, 'view': view_bundle(initialize_world(resolved), mode='preview'), 'artifact_id': uuid.uuid4().hex}
    if operation == 'prepare_export':
        from .export_jobs import prepare_export
        return prepare_export(manager, *args, **kwargs)
    if operation == 'render_export':
        from .export_jobs import render_export
        return render_export(*args, **kwargs)
    run_id = args[0]
    history = manager.history(run_id)
    try:
        if operation == 'events':
            return history.events(*args[1:], **kwargs)
        if operation == 'metrics':
            from .visualization import sampled_metrics
            return sampled_metrics(history, *args[1:], **kwargs)
        if operation == 'observation':
            agent_id, revision, index = args[1:]
            records = history.events(end=revision, agent_id=agent_id)
            decisions = [r for r in records if r.get('kind') == 'decision' or r.get('observation') is not None]
            if not decisions: raise ValueError('No recorded decision observation at this cursor')
            if index is not None and not 0 <= index < len(decisions): raise ValueError("Recorded decision index is outside this agent's history")
            selected = decisions[-1 if index is None else index]
            if selected.get('observation') is None: raise ValueError('This decision records a reconstruction reference; direct observation capture was not enabled')
            return {'perspective':'recorded_observation','decision':selected.get('id'),'time':selected.get('time'),'revision':selected.get('ledger_revision'),'observation':selected['observation']}
        if operation == 'legacy_export':
            from .storage import canonical
            from .visualization import events_csv, world_svg, replay_animation
            format, selected_time, revision, start, end = args[1:]
            view = manager.snapshot(run_id, selected_time, revision)
            if format == 'svg': return world_svg(view['state']), 'image/svg+xml', f'{run_id}-{view["revision"]}.svg'
            if format == 'csv': return events_csv(history.events(end=revision)), 'text/csv', f'{run_id}-events.csv'
            if format == 'animation': return replay_animation(history, start, end or selected_time, run_id=run_id), 'text/html', f'{run_id}-replay.html'
            if format == 'parquet':
                try:
                    import pyarrow as pa
                    import pyarrow.parquet as pq
                except ImportError as error: raise ValueError('Parquet exports require the analysis extra (pyarrow)') from error
                records = history.events(end=revision)
                table = pa.Table.from_pylist([{'revision':str(r.get('ledger_revision')),'sequence':str(r.get('ledger_sequence')),'time':str(r.get('time','0')),'kind':str(r.get('kind','event')),'payload_json':canonical(r)} for r in records])
                buffer = pa.BufferOutputStream(); pq.write_table(table, buffer, compression='zstd')
                return buffer.getvalue().to_pybytes(), 'application/octet-stream', f'{run_id}-events.parquet'
            if format != 'json': raise ValueError('HTTP view exports support json, csv, svg, parquet and animation')
            return canonical(view), 'application/json', f'{run_id}-{view["revision"]}.json'
        raise ValueError(f'Unknown read operation: {operation}')
    finally:
        history.close()


def _worker(root, channel):
    from .application import RunManager
    manager = RunManager(root, read_only=True)
    try:
        while True:
            message = channel.recv()
            if message is None: return
            operation, args, kwargs, destination = message
            try:
                value = (True, execute(manager, operation, args, kwargs))
            except Exception as error:
                from .application import RunInitializing,ViewCancelled
                from .config import ConfigError
                kind=next((name for cls,name in ((RunInitializing,'initializing'),(ViewCancelled,'cancelled'),
                    (ConfigError,'config'),(ValueError,'value'),(KeyError,'missing')) if isinstance(error,cls)),'internal')
                value = (False, {'kind':kind,'type':type(error).__name__,'message':str(error),
                                  'key':str(error.args[0]) if error.args else '',
                                  'code':getattr(error,'code',None),'path':getattr(error,'path',None)})
            with open(destination, 'wb') as stream:
                pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
            channel.send(True)
    except (EOFError, BrokenPipeError, ConnectionResetError):
        pass
    finally:
        manager.close(); channel.close()


class ReadPool:
    def __init__(self, root, size=2, name='analysis'):
        self.root = str(root); self.size = size; self.name = name
        self.condition = threading.Condition(); self.closing = False
        self.slots = [{'process':None,'pipe':None,'busy':False,'pid':None} for _ in range(size)]
        self.temporary = tempfile.TemporaryDirectory(prefix=f'zombie-{name}-')
        self.active = 0; self.waiting = 0; self.cancelled = 0

    def _discard(self, slot):
        process = slot['process']
        if process is not None:
            if process.is_alive(): process.terminate()
            process.join(timeout=1)
            if process.is_alive():
                # This exact owned child is read-only, never a simulation writer.
                process.kill(); process.join(timeout=1)
            if process.is_alive(): raise RuntimeError('Read-only worker exit is still pending')
            pipe=slot['pipe']
            with self.condition:slot.update(process=None,pipe=None,pid=None)
            process.close();pipe.close()

    def call(self, operation, *args, cancel_event=None, **kwargs):
        from .application import ViewCancelled
        def cancelled(): return self.closing or (cancel_event is not None and cancel_event.is_set())
        slot = None; destination = None
        with self.condition:
            self.waiting += 1
            try:
                while slot is None:
                    if cancelled(): raise ViewCancelled('Reader cancelled during service drain or disconnect')
                    slot = next((item for item in self.slots if not item['busy']), None)
                    if slot is None: self.condition.wait(.05)
                slot['busy'] = True; self.active += 1
            finally: self.waiting -= 1
        try:
            if slot['process'] is None:
                context = multiprocessing.get_context('spawn')
                parent, child = context.Pipe()
                process = context.Process(target=_worker, args=(self.root, child), name=f'zombie-{self.name}', daemon=True)
                try:process.start()
                except BaseException:
                    parent.close();child.close();process.close();raise
                child.close()
                with self.condition:slot.update(process=process, pipe=parent,pid=process.pid)
            destination = Path(self.temporary.name) / (uuid.uuid4().hex + '.pickle')
            slot['pipe'].send((operation, args, kwargs, str(destination)))
            while not slot['pipe'].poll(.05):
                if cancelled():
                    self.cancelled += 1
                    self._discard(slot)
                    raise ViewCancelled('Reader cancelled during service drain or disconnect')
                if not slot['process'].is_alive():
                    self._discard(slot); raise RuntimeError('Read-only worker exited before completing its request')
            slot['pipe'].recv()
            if cancelled(): raise ViewCancelled('Reader cancelled during service drain or disconnect')
            with destination.open('rb') as stream: success, value = pickle.load(stream)
            if not success:
                from .application import RunInitializing
                from .config import ConfigError
                types={'initializing':RunInitializing,'cancelled':ViewCancelled,'config':ConfigError,
                       'value':ValueError,'missing':KeyError,'internal':RuntimeError}
                error=types[value['kind']](value['key'] if value['kind']=='missing' else value['message'])
                if value.get('code') is not None:error.code=value['code']
                if value.get('path') is not None:error.path=value['path']
                raise error
            return value
        except (EOFError, BrokenPipeError):
            self._discard(slot)
            raise RuntimeError('Read-only worker connection closed') from None
        finally:
            if destination: destination.unlink(missing_ok=True)
            with self.condition:
                slot['busy'] = False; self.active -= 1; self.condition.notify_all()

    def status(self):
        with self.condition:
            return {'active':self.active,'queued':self.waiting,'capacity':self.size,'cancelled':self.cancelled,
                    'processes':[slot['pid'] for slot in self.slots if slot['pid'] is not None]}

    def start_draining(self):
        with self.condition:
            self.closing = True; self.condition.notify_all()

    def close(self):
        self.start_draining()
        with self.condition:
            while self.active or self.waiting: self.condition.wait(.05)
            for slot in self.slots: self._discard(slot)
        self.temporary.cleanup()
