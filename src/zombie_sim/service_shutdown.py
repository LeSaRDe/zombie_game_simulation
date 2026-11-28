"""Drain real work before Uvicorn starts its final transport shutdown."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid

LOGGER = logging.getLogger('zombie_sim.shutdown')


class ShutdownCoordinator:
    def __init__(self, manager, readers, exports):
        self.manager=manager; self.readers=readers; self.exports=exports
        self.draining=False; self.phase='running'; self.mode=None; self.controls_open=True
        self.active_mutations=0; self.sockets=set(); self.task=None
        self.started=None; self.error=None; self.outcomes={}; self.operations=set()
        self.identity=uuid.uuid4().hex; self.exit_callback=None
        self.readers_closed=False; self.exports_closed=False

    def status(self):
        return {'draining':self.draining,'phase':self.phase,'mode':self.mode,
                'elapsed_seconds':round(time.monotonic()-self.started,1) if self.started else 0,
                'controls_open':self.controls_open,'active_mutations':self.active_mutations,'viewers':len(self.sockets),
                'readers':self.readers.status(),'exports':self.exports.status(),
                'pending_operations':len(self.operations),'runs':dict(self.outcomes),'error':self.error,
                'complete':self.phase=='ready','retryable':self.phase=='incomplete'}

    def start(self, mode='save', timeout=900):
        if mode not in {'save','terminate'}:raise ValueError('Shutdown mode must be save or terminate')
        if not isinstance(timeout,(int,float)) or isinstance(timeout,bool) or not 0 < timeout <= 86400:
            raise ValueError('Shutdown timeout must be between 0 and 86400 seconds')
        if self.mode is not None and self.mode != mode:raise ValueError(f'Shutdown already uses {self.mode}; retry with the same mode')
        if self.phase=='ready' or (self.task is not None and not self.task.done()):return self.status()
        self.draining=True; self.mode=mode; self.started=time.monotonic(); self.error=None
        self.phase='closing_viewers_and_readers'
        self.readers.start_draining(); self.exports.start_draining()
        self.task=asyncio.create_task(self._run(timeout))
        return self.status()

    async def _operation(self, function, *args, **kwargs):
        task=asyncio.create_task(asyncio.to_thread(function,*args,**kwargs))
        self.operations.add(task)
        def done(value):
            self.operations.discard(value)
            if not value.cancelled():value.exception()
        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def _run(self, timeout):
        try:
            await asyncio.wait_for(self._drain(),timeout)
            self.phase='ready'
        except asyncio.TimeoutError:
            previous=self.phase;self.phase='incomplete'
            self.error=f'Overall shutdown budget exhausted during {previous}. Writer work was not killed. Retry shutdown in {self.mode} mode to reconcile this same service and its durable commands.'
            LOGGER.warning(self.error)
        except Exception as error:
            previous=self.phase;self.phase='incomplete'
            self.error=f'{previous}: {type(error).__name__}: {error}. Retry shutdown in {self.mode} mode.'
            LOGGER.exception('Service shutdown incomplete')

    async def _drain(self):
        # A timed-out writer call remains tracked. Retrying waits for it instead
        # of starting a competing checkpoint or branch operation.
        if self.operations:await asyncio.gather(*(asyncio.shield(task) for task in tuple(self.operations)),return_exceptions=True)
        for websocket in tuple(self.sockets):
            try:await asyncio.wait_for(websocket.close(code=1001,reason='Workspace service shutting down'),1)
            except Exception:pass
        self.phase='draining_readers_and_exports'
        if not self.readers_closed:
            await self._operation(self.readers.close); self.readers_closed=True
        if not self.exports_closed:
            await self._operation(self.exports.close); self.exports_closed=True
        # This event-loop fence is atomic with HTTP admission. Once closed,
        # only this coordinator can enqueue new commands; requests admitted
        # before the fence remain counted until their effects are reserved.
        self.controls_open=False
        self.phase='reconciling_accepted_commands'
        while self.active_mutations:await asyncio.sleep(.05)
        while True:
            commands=await self._operation(self.manager.repository.pending_commands)
            if not commands:break
            for command in commands:
                # Creation/branch reservations can outlive their original HTTP
                # handler. Reconcile the original ID instead of overlooking it.
                if command['operation'] in {'create','branch'}:
                    import json
                    request=json.loads(command['request'])
                    if command['operation']=='create':
                        await self._operation(self.manager.create,request['config'],command['id'],start=request.get('start',False))
                    else:await self._operation(self.manager.branch,command['run_id'],request)
                else:
                    import json
                    # Re-submit the same stored command to recover an accepted
                    # request whose worker never started or exited.
                    result=await self._operation(self.manager.command_result,command['id'])
                    if result['status']=='pending':
                        await self._operation(self.manager.command,command['run_id'],command['operation'],json.loads(command['request']),wait=False)
            await asyncio.sleep(.1)
        for creation in await self._operation(self.manager.repository.unfinished_creations):
            import json
            request=json.loads(creation['request'])
            await self._operation(self.manager.create,request['config'],creation['id'],start=request.get('start',False))
        self.phase='saving_runs' if self.mode=='save' else 'terminating_runs'
        rows=await self._operation(self.manager.list_runs)
        for row in rows:
            identifier=row['id']; old=self.outcomes.get(identifier,{})
            inactive={'completed','terminated','stopped','failed','interrupted'}
            if row['status'] in inactive and not old.get('command_id'):
                self.outcomes[identifier]={'status':row['status'],'command_id':None,'cleanup_complete':row['resource_status']['cleanup_complete']}
                continue
            command_id=old.get('command_id') or f'shutdown:{self.identity}:{identifier}:{self.mode}'
            self.outcomes[identifier]={'status':'pending','command_id':command_id,'cleanup_complete':False}
            try:
                result=await self._operation(self.manager.command,identifier,'stop' if self.mode=='save' else 'terminate',{'command_id':command_id},wait=False)
            except ValueError:
                # Natural completion can win the race after list_runs. There
                # is no shutdown receipt to retry when admission never wrote
                # the synthetic ID; preserve that immutable terminal outcome.
                current=await self._operation(self.manager._row,identifier)
                recorded=self.manager.repository.command_exists(command_id)
                if current['status'] in {'completed','terminated'} and not recorded:
                    self.outcomes[identifier]={'status':current['status'],'command_id':None,'cleanup_complete':False}
                    continue
                raise
            while result['status']=='pending':
                await asyncio.sleep(.1)
                result=await self._operation(self.manager.command_result,command_id)
            self.outcomes[identifier].update(status=result['status'],receipt=result)
            if result['status']!='applied':raise RuntimeError(f'{identifier}: {result.get("error", "shutdown command rejected")} (request {command_id})')
        self.phase='waiting_for_worker_cleanup'
        while True:
            rows=await self._operation(self.manager.list_runs)
            for row in rows:
                self.outcomes.setdefault(row['id'],{}).update(run_status=row['status'],cleanup_complete=row['resource_status']['cleanup_complete'])
            leases=self.manager.repository.lease_count()
            if not leases and all(row['resource_status']['cleanup_complete'] for row in rows):break
            await asyncio.sleep(.1)
        while self.sockets:await asyncio.sleep(.05)

    def request_exit(self):
        if self.phase!='ready':raise ValueError('Service drain is not complete; inspect shutdown status and retry')
        if self.exit_callback:self.exit_callback()
