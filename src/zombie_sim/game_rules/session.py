"""Isolated planning workspace and immutable transition results.

A GameRuleSet receives no Simulation, repository, database, or publisher. Its
scratch drafts are discarded after typed changes and causal events are built.
"""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from ..domain import status
from ..domain_model import DomainEvent
from ..domain_model.values import JsonObject, freeze_json, thaw_json
from ..state_management import WorldDraft, WorldAggregate, RuntimeSnapshot, install_runtime_fields
from .primitives import stamp
from .handlers import ActionHandlerRegistry
from .action_lifecycle import ActionLifecycle
from .continuous import ContinuousEvolution
from .observations import ObservationBuilder
from .randomness import EventRandom
from .scheduling import ScheduleRules
from .interventions import InterventionRules
from .lifecycle import DamageRules, ResourceRules, InfectionRules, DeathRules, ConversionRules, EffectRules, SignalRules, GeometryRules


@dataclass(frozen=True)
class RuleRequest:
    kind: str
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True, init=False)
class TransitionPlan:
    expected_revision: int
    time: str
    changes: tuple
    events: tuple
    runtime: RuntimeSnapshot
    _metadata: JsonObject
    _result: object
    _queue_delta: object
    read_set: frozenset = frozenset()
    _diagnostics: JsonObject = field(default_factory=JsonObject)

    def __init__(self, expected_revision, time, changes, events, runtime,
                 metadata=None, result=None, queue_delta=(), read_set=frozenset(), diagnostics=None):
        for name, value in (('expected_revision', expected_revision), ('time', time),
                            ('changes', tuple(changes)), ('events', tuple(events)), ('runtime', runtime),
                            ('_metadata', JsonObject.from_record(metadata or {})),
                            ('_result', freeze_json(result)), ('_queue_delta', freeze_json(queue_delta)),
                            ('read_set', frozenset(read_set)),
                            ('_diagnostics', JsonObject.from_record(diagnostics or {}))):
            object.__setattr__(self, name, value)

    @property
    def metadata(self): return self._metadata.to_record()
    @property
    def result(self): return thaw_json(self._result)
    @property
    def queue_delta(self): return tuple(thaw_json(self._queue_delta))
    @property
    def diagnostics(self): return self._diagnostics.to_record()


class ObservationEvidence:
    """Only already selected dated inputs; no historical query capability."""
    def __init__(self, records=()):
        self.records = deepcopy(list(records))
    def append(self, record): self.records.append(deepcopy(record))
    def __iter__(self): return iter(self.records)
    def observations_at(self, actor, at):
        return [deepcopy(r['observation']) for r in self.records
                if str(r.get('actor')) == str(actor) and r.get('observation', {}).get('time') == at]


class ReadProjection:
    """Local observation evaluation over a dated immutable world."""
    def __init__(self, world, runtime):
        self.state = world
        self.time = runtime.time
        self.horizon = runtime.horizon
        self.revision = runtime.revision
        self.occurrences = world['occurrences']
        self.continuous = ContinuousEvolution(self)
        self.observations = ObservationBuilder(self)
        self._position_cache = {}
        self._spatial_index = world.world.spatial_index

    def update(self, world, runtime, changed=()):
        self.state = world; self.time = runtime.time; self.horizon = runtime.horizon; self.revision = runtime.revision
        self.occurrences = world['occurrences']
        self._spatial_index = world.world.spatial_index
        self._runtime_spatial_dirty = set()
        self._position_cache = {}

    def _evaluate(self, agent, at): return self.continuous._evaluate(agent, at)
    def _path_position(self, occurrence, time): return self.continuous._path_position(occurrence, time)
    def _position_at(self, aid): return self.continuous._position_at(aid)
    def _view_agent(self, aid): return self.observations._view_agent(aid)
    def _nearby(self, point, radius): return self.observations._nearby(point, radius)
    def _public(self, agent): return self.observations._public(agent)
    def observe(self, aid): return self.observations.observe(aid)
    def snapshot(self): return self.observations.snapshot()


@install_runtime_fields
class PlanningSession:
    """One non-publishing workspace; only declared runtime fields are writable."""
    def __init__(self, world, runtime, handlers, *, evidence=(), prepared_agents=None, queue_delta=()):
        self._runtime_state = runtime.fork()
        self.state = WorldDraft(world)
        self.occurrences, self.intents = self.state['occurrences'], self.state['intents']
        self.action_handlers = handlers
        self.continuous = ContinuousEvolution(self)
        self.observations = ObservationBuilder(self)
        self.actions = ActionLifecycle(self)
        self.randomness = EventRandom(self)
        self.scheduling = ScheduleRules(self)
        self.interventions = InterventionRules(self)
        self.damage = DamageRules(self); self.resources = ResourceRules(self)
        self.infection = InfectionRules(self); self.death = DeathRules(self)
        self.conversion = ConversionRules(self); self.effects = EffectRules(self)
        self.signals = SignalRules(self); self.geometry = GeometryRules(self)
        self.decisions = ObservationEvidence(evidence)
        self.random_draws = []
        self._dirty = set()
        self._effects_buffer = []
        self._deferred_events = []
        self._batching = False
        self._runtime_queue_delta = deepcopy(list(queue_delta))
        self._position_cache = {}
        self._committed_records = None
        self._spatial_index = world.world.spatial_index
        self._runtime_dependency_retries = 0
        for key, agent in (prepared_agents or {}).items():
            self.state['agents'][key] = deepcopy(agent)
            self._mark('agents', key)

    def _id(self, prefix):
        self._counter += 1
        self._identity_counters[prefix] = self._identity_counters.get(prefix, 0) + 1
        return f'{prefix}-{self._identity_counters[prefix]}'

    def _mark(self, collection, key):
        self._dirty.add((collection, str(key)))
        if collection == 'agents':
            self._runtime_spatial_dirty = set(getattr(self, '_runtime_spatial_dirty', ())) | {str(key)}
            self._position_cache.pop(str(key), None)

    def _commit(self, kind, **details):
        if not self._batching:
            self._dirty.update(self.state.changed_keys())
            self._finalize_action_evidence()
        event = {'id':self._id('event'), 'time':stamp(self.time), 'revision':self.revision+1,
                 'kind':kind, 'causes':details.pop('causes', []), **deepcopy(details)}
        if self._batching:
            self._deferred_events.append(event)
            for effect in self._effects_buffer:
                self._deferred_events.append({'id':self._id('event'), 'time':stamp(self.time), 'revision':self.revision+1, 'causes':[event['id']], **effect})
            self._effects_buffer.clear()
            return event
        if self._committed_records is not None:
            raise RuntimeError('A rule request may publish only one atomic semantic boundary')
        for collection, key in sorted(self._dirty):
            if collection == 'agents' and key in self.state[collection]:
                self.state[collection][key].update(last_state_event_id=event['id'], revision=self.revision+1)
                self.state[collection][key]['status'] = status(self.state[collection][key])
        records = [*self._deferred_events, event]
        for effect in self._effects_buffer:
            records.append({'id':self._id('event'), 'time':stamp(self.time), 'revision':self.revision+1, 'causes':[event['id']], **effect})
        self._committed_records = records
        self._effects_buffer.clear(); self._deferred_events.clear()
        return event

    def consume_prepared_effect(self, occurrence, actor, properties):
        from ..parallel import effect_task
        proposal = self._prepared_effects.pop(occurrence['id'], None)
        if proposal is None: return None
        target_id = occurrence.get('target')
        target = self._view_agent(target_id) if target_id in self.state['agents'] else self.state['barriers'].get(target_id)
        current = effect_task(occurrence, actor, target, properties)
        if current is None or current['fingerprint'] != proposal['fingerprint']:
            self.parallel_effect_stats['fallback'] = self.parallel_effect_stats.get('fallback', 0) + 1
            return None
        self.parallel_effect_stats['consumed'] = self.parallel_effect_stats.get('consumed', 0) + 1
        return deepcopy(proposal['effect'])

    def apply_decisions(self, rows):
        self._batching = True
        self.execution_counters['policy_calls'] += len(rows)
        proposals = []
        agents = []
        try:
            for observation, (intent, memory, diagnostics) in rows:
                aid = observation['self_state']['id']; agents.append(aid)
                self.memories[aid] = deepcopy(memory)
                intent = deepcopy(intent) if isinstance(intent,dict) else {}
                intent['actor'] = aid
                if 'id' not in intent: intent['id'] = self._id('intent')
                decision_id = self._id('decision'); intent['decision_id'] = decision_id
                decision = dict(id=decision_id, time=stamp(self.time), actor=aid, observation=observation,
                                intent=deepcopy(intent), diagnostics=deepcopy(diagnostics))
                if diagnostics.get('fallback_reason'): decision['fallback_reason'] = diagnostics['fallback_reason']
                self.decisions.append(decision); self._commit('decision', **decision); proposals.append(intent)
            results = self.submit_intents(proposals)
            for result in results:
                if result['status'] == 'REJECTED':
                    for decision in reversed(self._deferred_events):
                        if decision.get('kind') == 'decision' and decision['intent']['id'] == result['id']:
                            decision['fallback_reason'] = 'REJECTION_LIMIT'
                            decision['diagnostics']['fallback_reason'] = 'REJECTION_LIMIT'; break
                    self.submit_intents([dict(actor=result['actor'], action='wait', parameters={'duration':'1'}, fallback_for=result['id'])])
        finally: self._batching = False
        return agents

    def finish_plan(self, result=None, metadata=None):
        if self._committed_records is None: raise RuntimeError('Rule request did not finalize a semantic boundary')
        dirty = set(self._dirty)
        changes = self.state.changes(dirty)
        self._dirty.clear()
        return TransitionPlan(self.revision, stamp(self.time), changes,
                              tuple(DomainEvent.from_record(event) for event in self._committed_records),
                              self._runtime_state.snapshot(), {**self.state.metadata_changes(), **(metadata or {})}, deepcopy(result),
                              tuple(deepcopy(self._runtime_queue_delta)),
                              frozenset(dirty) | frozenset((name, key) for name, table in self.state.tables.items() for key in table.drafts),
                              {'dependency_retries':self._runtime_dependency_retries})

    def submit_intents(self, intents):
        'Arbitrate and publish an externally supplied decision batch atomically.'
        return self.actions.submit_intents(intents)


    def _submit_intents_inner(self, intents):
        return self.actions._submit_intents_inner(intents)


    def _finalize_action_evidence(self):
        'Capture the final atomic after-state, after all coupled consequences.'
        return self.actions._finalize_action_evidence()


    def _capture_action_agent(self, identifier, after=False, admission=False):
        return self.actions._capture_action_agent(identifier, after, admission)


    def _perceived(self, actor, target, barrier=False):
        return self.actions._perceived(actor, target, barrier)


    def _target(self, actor, action, identifier, reach):
        return self.actions._target(actor, action, identifier, reach)


    def _path_parameters(self, actor, action, parameters, duration, p):
        return self.actions._path_parameters(actor, action, parameters, duration, p)


    def _gate_clear(self, gate):
        return self.actions._gate_clear(gate)


    def _construction_footprint(self, actor, parameters):
        return self.actions._construction_footprint(actor, parameters)


    def _knowledge_payload(self, actor, action, parameters):
        return self.actions._knowledge_payload(actor, action, parameters)


    def _action_plan(self, actor, action, target_id, parameters, completion=False, occurrence=None):
        return self.actions._action_plan(actor, action, target_id, parameters, completion, occurrence)


    def _action_plan_checked(self, actor, action, target_id, parameters, completion=False, occurrence=None):
        return self.actions._action_plan_checked(actor, action, target_id, parameters, completion, occurrence)


    def _release(self, occurrence, consume=False):
        return self.actions._release(occurrence, consume)


    def _resolve(self, occurrence_id):
        return self.actions._resolve(occurrence_id)


    def _evaluate(self, a, at):
        return self.continuous._evaluate(a, at)


    def _touch(self, aid):
        return self.continuous._touch(aid)


    def _path_position(self, occurrence, time):
        return self.continuous._path_position(occurrence, time)


    def _position_at(self, aid):
        return self.continuous._position_at(aid)


    def _view_agent(self, aid):
        return self.observations._view_agent(aid)


    def observe(self, aid):
        return self.observations.observe(aid)


    def snapshot(self):
        return self.observations.snapshot()


    def _nearby(self, position, radius):
        "Conservative swept-path buckets, followed by exact-time filtering.\n\nA movement's entire recorded path is in its broad-phase envelope. Thus\ntime advancing never requires scanning every agent to update the grid.\nAdmission, interruption, relocation and lifecycle writes invalidate only\ntheir actors. Candidates still use exact trajectory coordinates and LOS."
        return self.observations._nearby(position, radius)


    def _random(self, domain, key):
        return self.randomness._random(domain, key)


    def _bernoulli(self, occurrence, channel, probability):
        return self.randomness._bernoulli(occurrence, channel, probability)


    def _schedule(self, time, phase, kind, agent=None, **fields):
        return self.scheduling._schedule(time, phase, kind, agent, **fields)


    def _schedule_decision(self, aid, when):
        return self.scheduling._schedule_decision(aid, when)


    def _schedule_starvation(self, a):
        return self.scheduling._schedule_starvation(a)


    def _dispatch(self, event):
        return self.scheduling._dispatch(event)


    def intervene(self, change, at=None, id=None):
        return self.interventions.intervene(change, at, id)


    def _apply_intervention(self, iid):
        return self.interventions._apply_intervention(iid)


    def _damage(self, targetid, raw, source, bypass=False):
        return self.damage._damage(targetid, raw, source, bypass)


    def _drop(self, a, quantities):
        return self.resources._drop(a, quantities)


    def _close_episode(self, a, outcome):
        return self.infection._close_episode(a, outcome)


    def _expose(self, targetid, potency, occurrence):
        return self.infection._expose(targetid, potency, occurrence)


    def _die(self, a, source, before_state=None):
        return self.death._die(a, source, before_state)


    def _convert(self, a):
        return self.conversion._convert(a)


    def _effect(self, agentid, kind, value, duration, source):
        return self.effects._effect(agentid, kind, value, duration, source)


    def _broadcast(self, actorid, kind, payload, radius, ttl, source):
        return self.signals._broadcast(actorid, kind, payload, radius, ttl, source)


    def _finish(self, occurrence, result):
        return self.actions._finish(occurrence, result)


    def _geometry_changed(self):
        'Schedule actual future contacts, ending motion 0.01 m before contact.'
        return self.geometry._geometry_changed()


    def _public(self, agent): return self.observations._public(agent)


class GameRuleSet:
    def __init__(self, handlers=None):
        self.handlers = handlers or ActionHandlerRegistry()

    def __setattr__(self, name, value):
        if name == 'handlers' and hasattr(self, name):
            raise AttributeError('Rule bindings are frozen; compose a new GameRuleSet explicitly')
        object.__setattr__(self, name, value)

    def plan(self, request, world, runtime, *, config=None, evidence=(), prepared_agents=None, queue_delta=()):
        session = PlanningSession(world, runtime, self.handlers, evidence=evidence,
                                  prepared_agents=prepared_agents, queue_delta=queue_delta)
        if config is not None: session.config = deepcopy(config)
        result = None; metadata = None
        data = request.payload
        if request.kind == 'admit': result = session.submit_intents(data['intents'])
        elif request.kind == 'event':
            session._dispatch(data['event'])
            if session._committed_records is None:
                session._commit('scheduler_advanced', scheduled_kind=data['event']['kind'])
        elif request.kind == 'intervene': result = session.intervene(data['change'], data.get('at'), data.get('id'))
        elif request.kind == 'decision_batch':
            session.apply_decisions(data['rows'])
            session._commit('decision_batch', agents=sorted(set(data['agents'])))
        elif request.kind == 'metadata':
            metadata = deepcopy(data['metadata'])
            if 'config' in data: session.config = deepcopy(data['config'])
            if 'seed' in data: session.seed = data['seed']
            session._active_control_command = None
            session.run_status = 'PAUSED'; session.termination_reason = None
            event = deepcopy(data['event']); kind = event.pop('kind')
            event.pop('time',None); event.pop('revision',None)
            session._commit(kind, **event)
        elif request.kind == 'clock': session._commit(data.get('kind','clock_advanced'), **data.get('details',{}))
        else: raise ValueError(f'Unknown rule request {request.kind!r}')
        return session.finish_plan(result, metadata)
