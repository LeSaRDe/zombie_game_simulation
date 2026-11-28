"""Exact event clock, action transactions, lifecycle and local observations.

Rules originate in ontology/zombie_game_ontology_v0.1.md §§3–16. No
acceptance-suite code or fixtures are imported by this implementation.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import heapq
import json
import math
import multiprocessing
import os
from pathlib import Path
import random
import tempfile
import time as wall_clock
import uuid

from .config import resolve_config, initialize_world
from .domain import profile, capabilities, status
from .geometry import point_blocked, segment_clear, distance_to
from .persistence import PersistenceBundleFactory
from .state_management import RuntimeState, RuntimeSnapshot, WorldAggregate, StateCoordinator, install_runtime_fields
from .game_rules import GameRuleSet, RuleRequest, ReadProjection
from .runtime import materialize_snapshot
from .interrupts import BoundaryProcessPool as ProcessPoolExecutor, ignore_worker_sigint


def clock(value):
    if isinstance(value, bool):
        raise ValueError("A Boolean is not a semantic time")
    result = Fraction(str(value))
    if result < 0:
        raise ValueError("Semantic time must be nonnegative")
    return result


def stamp(value):
    value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else str(value)


def point(obj):
    return float(obj["x"]), float(obj["y"])


def half_up(value):
    return max(0, math.floor(Fraction(str(value)) + Fraction(1,2)))


def _segment_contact(a,b,rectangle):
    """Closed rectangle intersection interval, including tangential contacts."""
    lower,upper=0.,1.
    for origin,delta,minimum,maximum in ((a[0],b[0]-a[0],rectangle[0],rectangle[2]),
                                        (a[1],b[1]-a[1],rectangle[1],rectangle[3])):
        if delta==0:
            if origin<minimum or origin>maximum:return None
            continue
        lo,hi=(minimum-origin)/delta,(maximum-origin)/delta
        if lo>hi:lo,hi=hi,lo
        lower=max(lower,lo);upper=min(upper,hi)
        if lower>upper:return None
    return lower,upper


def _visible_surface(here,radius,barrier,barriers):
    """Clip surfaces at circle and occluder silhouette boundaries.

    Midpoint classification is valid only after splitting at every visibility
    transition. Endpoints outside the closed LOS contract are moved inward.
    """
    from .geometry import blocking
    x0,y0,x1,y1=map(float,barrier["footprint"])
    corners=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
    facing=[here[1]<y0,here[0]>x1,here[1]>y1,here[0]<x0]
    occluders=[b for b in barriers.values() if b["id"]!=barrier["id"] and blocking(b) and distance_to(here,b)<=radius]
    portions=[]
    cross=lambda a,b:a[0]*b[1]-a[1]*b[0]
    for index,(u,v) in enumerate(zip(corners,corners[1:]+corners[:1])):
        if blocking(barrier) and not facing[index]:continue
        d=(v[0]-u[0],v[1]-u[1]);offset=(u[0]-here[0],u[1]-here[1])
        a=d[0]**2+d[1]**2
        if not a:continue
        b=2*(offset[0]*d[0]+offset[1]*d[1]);c=offset[0]**2+offset[1]**2-radius**2
        discriminant=b*b-4*a*c
        if discriminant<0:continue
        root=math.sqrt(discriminant)
        lower=max(0.,(-b-root)/(2*a));upper=min(1.,(-b+root)/(2*a))
        if lower>=upper:continue
        cuts={lower,upper}
        for obstacle in occluders:
            ox0,oy0,ox1,oy1=obstacle["footprint"]
            for corner in ((ox0,oy0),(ox1,oy0),(ox1,oy1),(ox0,oy1)):
                ray=(corner[0]-here[0],corner[1]-here[1]);denominator=cross(d,ray)
                if not denominator:continue
                t=cross((-offset[0],-offset[1]),ray)/denominator
                scale=cross((-offset[0],-offset[1]),d)/denominator
                if scale>=0 and lower<t<upper:cuts.add(t)
        coordinates=lambda t:(u[0]+d[0]*t,u[1]+d[1]*t)
        clear=lambda t:segment_clear(here,coordinates(t),occluders)
        ordered=sorted(cuts)
        for start,end in zip(ordered,ordered[1:]):
            middle=(start+end)/2
            if not clear(middle):continue
            # Closed obstacles hide tangent rays too. No hidden endpoint is
            # exposed merely because the open interior of a segment is visible.
            if not clear(start):start+=(end-start)*1e-9
            if not clear(end):end-=(end-start)*1e-9
            if start<end and clear(start) and clear(end):
                portions.append([coordinates(start),coordinates(end)])
    return portions


RESOURCES = ("FOOD", "MEDICAL_SUPPLY", "MATERIAL")
ATTACKS = {"melee", "power_strike", "claw", "bite", "spit"}
# duration, admission energy, cooldown, reach. Role-controlled values are resolved
# below from the imported per-agent profile, not from a decision policy.
RULES = {
    "move": (None, 0, 0, None), "wait": (None, 0, 0, None), "rest": (None, 0, 0, None),
    "signal": (.5, 1, 2, None), "melee": (1, 6, 1, 1.5),
    "pickup": (1, 1, 0, 1.5), "drop": (.5, 0, 0, None), "transfer": (1, 1, 0, 1.5),
    "eat": (2, 0, 0, None), "first_aid": (3, 4, 2, 1.5),
    "open_gate": (1, 1, 0, 2), "close_gate": (1, 1, 0, 2),
    "claw": (1, 6, 1, 1.5), "bite": (1.5, 10, 2, 1.5),
    "feed": (3, 0, 1, 1.5), "smash": (2, 10, 2, 2),
    "treat_infection": (4, 6, 2, 1.5), "prophylaxis": (4, 6, 2, 1.5),
    "power_strike": (1.5, 15, 6, 1.5), "guard": (1, 8, 8, None),
    "recon": (2, 6, 20, None), "mark_target": (.5, 1, 3, None),
    "build_barricade": (8, 12, 2, 2), "repair_barrier": (5, 8, 1, 2),
    "rally": (2, 15, 20, None), "demolish": (3, 18, 6, 2),
    "dash": (1, 12, 8, None), "spit": (1, 8, 8, 12), "scream": (2, 15, 30, None),
}


def _policy_call(task):
    from .policies import choose
    observation, memory, seed, model, parameters = task
    try:
        result=choose(observation, memory, random.Random(seed), model, parameters)
        if (not isinstance(result,(list,tuple)) or len(result)!=3 or not isinstance(result[0],dict)
                or result[0].get("action") not in RULES or not isinstance(result[0].get("parameters",{}),dict)
                or not isinstance(result[2],dict)):
            return ({"actor":observation["self_state"]["id"],"action":"wait","parameters":{"duration":"1"}},
                    memory,{"fallback_reason":"INVALID_MODEL_OUTPUT","message":"Model violated the typed decision contract"})
        return result
    except Exception as exc:
        return ({"actor": observation["self_state"]["id"], "action": "wait", "parameters": {"duration": "1"}},
                memory, {"fallback": type(exc).__name__, "fallback_reason":"MODEL_UNAVAILABLE" if isinstance(exc,FileNotFoundError) else "MODEL_EXCEPTION", "message": str(exc)})


def _observe_policy_chunk(task):
    """Evaluate detached local neighborhoods, including LOS, in a real worker."""
    started=wall_clock.process_time()
    from types import SimpleNamespace
    state = dict(task['state']); state.setdefault('run_id', 'detached-worker')
    view = ReadProjection(WorldAggregate.from_record(state).read_view(),
                          SimpleNamespace(time=task['time'], horizon=task['horizon'], revision=task['revision']))
    rows=[]
    for aid,memory,seed,model,parameters in task["controllers"]:
        observation=view.observe(aid)
        rows.append((observation,_policy_call((observation,memory,seed,model,parameters))))
    return {"rows":rows,"pid":os.getpid(),"cpu_seconds":wall_clock.process_time()-started}


@install_runtime_fields
class Simulation:
    """One authoritative coordinator; workers never own mutable world state."""

    def __init__(self, config=None, *, history_path=None, backend=None, workers=None, decision_mode=None,run_id=None,service_factory=None,persistence_factory=None,rule_set=None,_restored=None):
        from .core import SimulationServiceFactory
        from .core.migration import validate_simulation_subclass
        validate_simulation_subclass(type(self), Simulation)
        self._runtime_state = RuntimeState()
        self._runtime_persistence_factory = persistence_factory or PersistenceBundleFactory()
        self._runtime_rules = rule_set or GameRuleSet()
        self._runtime_service_factory = service_factory or SimulationServiceFactory()
        if _restored is not None:
            self._initialize_restored(_restored, history_path, backend, workers)
            return
        from .execution.rule_bindings import rule_manifest
        bindings = rule_manifest(self._runtime_rules)
        if bindings is not None:
            self.rule_bindings = bindings
        self.config = resolve_config(config or {"preset": "small"})
        self.state = initialize_world(self.config)
        self.state["run_id"]=run_id or uuid.uuid4().hex
        self.time = clock(self.state.get("time", 0))
        self.revision = 0
        self.seed = int(self.config.get("seed", 20261106))
        execution = self.config.get("execution", {})
        self.backend = backend or self.config.get("storage",{}).get("backend", "memory")
        from .hardware import worker_budget
        self.worker_request=workers if workers is not None else execution.get("workers", "auto")
        self._runtime_worker_budget = worker_budget(self.worker_request, population=len(self.state["agents"]))
        self.workers = self._runtime_worker_budget["workers"]
        self._runtime_service_factory.validate_workers(self.workers)
        if self._runtime_service_factory.is_custom:
            self.service_bindings = self._runtime_service_factory.manifest()
        self.decision_mode = decision_mode or self.config.get("decision_mode", "model")
        self.horizon = clock(self.config.get("horizon", 1800))
        self.events, self.decisions, self.random_draws = [], [], []
        self.execution_counters={"policy_calls":0,"bernoulli_calls":0}
        self.queue, self._serial, self._counter = [], 0, 0
        self._runtime_queue_delta=[]
        self._identity_counters={}
        self._batching=False
        self._deferred_events=[]
        self._prepared_boundary=None
        self.memories, self._dirty, self._decision_due = {}, set(), set()
        self._effects_buffer = []
        self._pool = None
        self.run_status, self.termination_reason = "PAUSED", None
        self._last_checkpoint = self.time
        self._since_checkpoint = 0
        self.state.setdefault("occurrences", {})
        self.state.setdefault("intents", {})
        for name in ("agents", "barriers", "stockpiles", "remains", "episodes", "signals", "reservations", "interventions"):
            self.state.setdefault(name, {})
        self.occurrences, self.intents = self.state["occurrences"], self.state["intents"]
        for aid, a in self.state["agents"].items():
            if a.get("life",0)>0 and a.get("model_memory") is not None:
                self.memories[aid]=deepcopy(a.pop("model_memory"))
            a.pop("infected",None)
            a.setdefault("_evaluated_at", stamp(self.time))
            a.setdefault("_generation", 0)
            a.setdefault("cooldowns", {})
            a.setdefault("effects", {})
            a.setdefault("active_action", None)
            a.setdefault("infection_episode", None)
            if self.config.get("state_import"):
                for effect_id,effect in a["effects"].items():
                    if clock(effect["end_at"])>=self.time:
                        self._schedule(effect["end_at"],0,"expire",aid,effect=effect_id)
            if a["type"] == "Human" and a["life"]>0:
                self._schedule_starvation(a)
            if a.get("infection_episode"):
                ep = self.state["episodes"][a["infection_episode"]]
                self._schedule(ep["conversion_due_at"], 3, "conversion", aid, episode=a["infection_episode"])
            if a.get("role") == "SPITTER":
                if a.get("next_charge_at"):
                    self._schedule(a["next_charge_at"], 2, "recharge", aid, generation=a["_generation"])
            if a["life"] > 0:
                self._schedule_decision(aid, self.time)
        self.state["time"] = stamp(self.time)
        self.state["revision"] = 0
        self._temporary = tempfile.TemporaryDirectory(prefix="zombie-sim-") if history_path is None else None
        path = Path(history_path) if history_path else Path(self._temporary.name) / "history.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        initial = self._runtime_initial_state
        self._runtime_persistence = self._runtime_persistence_factory.create(initial, path, self.backend)
        self.store = self._runtime_persistence.store
        self.history = self._runtime_persistence.history
        self._runtime_state_coordinator = StateCoordinator(WorldAggregate.from_record(initial), self._runtime_persistence)
        self._runtime_initial_state = None
        self.occurrences, self.intents = self.world_view['occurrences'], self.world_view['intents']
        self.history_path = str(path)
        self._dirty.clear()
        from .runtime import initialize_history
        initialize_history(self)
        from .history_sequence import attach_histories
        attach_histories(self)

    @property
    def state_coordinator(self):
        return self._runtime_state_coordinator

    @property
    def world_view(self):
        return self.state_coordinator.view()

    @property
    def state(self):
        if not hasattr(self, '_runtime_state_coordinator'):
            return self._runtime_initial_state
        return self.state_coordinator.current_world.to_record()

    @state.setter
    def state(self, value):
        if hasattr(self, '_runtime_state_coordinator'):
            raise AttributeError('Committed state is owned by StateCoordinator; submit a rule request')
        self._runtime_initial_state = value

    @property
    def _projection(self):
        projection = getattr(self, '_runtime_projection', None)
        if projection is None:
            projection = ReadProjection(self.world_view, self._runtime_state)
            projection.observations = self._runtime_service_factory.create("observations", projection)
            projection.continuous = self._runtime_service_factory.create("continuous", projection)
            self._runtime_projection = projection
        elif projection.revision != self.revision or projection.time != self.time:
            projection.update(self.world_view, self._runtime_state, getattr(self, '_runtime_projection_dirty', ()))
            self._runtime_projection_dirty = set()
        return projection

    @classmethod
    def _from_runtime_attributes(cls, attributes, *, history_path, backend=None, workers=None,
                                 service_factory=None, persistence_factory=None, rule_set=None):
        return cls(history_path=history_path, backend=backend, workers=workers,
                   service_factory=service_factory, persistence_factory=persistence_factory,
                   rule_set=rule_set, _restored=attributes)

    def _initialize_restored(self, attributes, history_path, backend, workers):
        self._runtime_state = RuntimeState.from_attributes(attributes)
        self.backend = backend or self.backend
        from .hardware import worker_budget
        request = workers if workers is not None else self.worker_request
        self._runtime_worker_budget = worker_budget(request, population=len(attributes['state']['agents']))
        self.worker_request = request; self.workers = self._runtime_worker_budget['workers']
        self._runtime_service_factory.validate_workers(self.workers)
        self.history_path = str(Path(history_path).absolute())
        self._runtime_persistence = self._runtime_persistence_factory.restore(self.history_path, self.backend, initial=attributes['state'])
        self.store = self._runtime_persistence.store; self.history = self._runtime_persistence.history
        self._runtime_state_coordinator = StateCoordinator(WorldAggregate.from_record(attributes['state']), self._runtime_persistence)
        self.occurrences, self.intents = self.world_view['occurrences'], self.world_view['intents']
        self._runtime_queue_delta = []
        self._pool = None; self._closed = False; self._temporary = None
        from .history_sequence import attach_histories
        attach_histories(self)
        from .domain_model import ScheduledTask
        self.queue = [row if isinstance(row, ScheduledTask) else ScheduledTask.from_record(row) for row in self.queue]
        heapq.heapify(self.queue)

    def _run_rule(self, kind, payload=None):
        """Calculate in isolation, commit world/runtime/evidence, then publish."""
        from .execution.commit_context import CommitContext
        payload = payload or {}
        evidence = []
        proposals = payload.get('intents', [])
        if isinstance(proposals, dict): proposals = [proposals]
        if kind == 'decision_batch':
            proposals = [{**row[1][0], 'actor': row[0]['self_state']['id']}
                         for row in payload['rows'] if isinstance(row[1][0], dict)]
        for intent in proposals:
            if not isinstance(intent, dict): continue
            parameters = intent.get('parameters', {})
            if not isinstance(parameters, dict): continue
            report = parameters.get('payload', {})
            if isinstance(report, dict) and report.get('observed_at') is not None and hasattr(self.decisions, 'observations_at'):
                aid = intent.get('actor', intent.get('agent_id'))
                for observation in self.decisions.observations_at(aid, str(report['observed_at'])):
                    evidence.append({'actor':aid, 'observation':observation})
        plan = self._runtime_rules.plan(RuleRequest(kind, payload), self.world_view,
                self._runtime_state.snapshot(), evidence=evidence,
                prepared_agents=getattr(self, '_runtime_prepared_agents', {}),
                queue_delta=getattr(self, '_runtime_queue_delta', []))
        transaction = self.state_coordinator.begin(plan)
        staged = CommitContext(self, plan, transaction.next_world)
        records = [event.to_record() for event in plan.events]
        runtime_delta, command_result = self.services.runtime.capture_delta(staged, self.revision + 1, records)
        try:
            result = transaction.commit(runtime_delta, command_result)
        except BaseException:
            self.run_status, self.termination_reason = 'FAILED', 'STORAGE_ERROR'
            raise
        self._runtime_state = staged._runtime_state
        self.revision = result.revision
        self._since_checkpoint += 1
        self._dirty.clear(); self._batching = False
        self._runtime_prepared_agents = {}
        self._runtime_projection_dirty = set(getattr(self, '_runtime_projection_dirty', ())) | {
            (change.collection, change.identity) for change in plan.changes}
        self._runtime_dependency_retries = getattr(self, '_runtime_dependency_retries', 0) + plan.diagnostics.get('dependency_retries', 0)
        self._runtime_command_result = command_result
        self.occurrences, self.intents = self.world_view['occurrences'], self.world_view['intents']
        for sequence in (self.events, self.decisions, self.random_draws):
            if hasattr(sequence, 'publish'): sequence.publish(records, result.last_sequence)
        if getattr(staged, '_runtime_pending_journal_schema', None) is not None:
            self._runtime_pending_journal_schema = staged._runtime_pending_journal_schema
        self.services.runtime.mark_committed(self)
        return plan.result

    def _scheduled_boundary(self):
        from .execution.scheduled_boundary import ScheduledBoundary
        return ScheduledBoundary(self)

    def _commit_metadata(self, metadata, event, *, config=None, seed=None):
        payload = {'metadata':metadata, 'event':event}
        if config is not None: payload['config'] = config
        if seed is not None: payload['seed'] = seed
        return self._run_rule('metadata', payload)

    @property
    def services(self):
        """Lazily compose behavior, including for restored and worker views."""
        from .core import SimulationServices
        services = self.__dict__.get("_runtime_services")
        if services is None:
            services = SimulationServices(self, self.__dict__.get("_runtime_service_factory"))
            self._runtime_services = services
        return services

    def _finalize_action_evidence(self):
        'Capture the final atomic after-state, after all coupled consequences.'
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._finalize_action_evidence")

    def _capture_action_agent(self, identifier, after=False, admission=False):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._capture_action_agent")

    def _perceived(self, actor, target, barrier=False):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._perceived")

    def _target(self, actor, action, identifier, reach):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._target")

    def _path_parameters(self, actor, action, parameters, duration, p):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._path_parameters")

    def _gate_clear(self, gate):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._gate_clear")

    def _construction_footprint(self, actor, parameters):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._construction_footprint")

    def _knowledge_payload(self, actor, action, parameters):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._knowledge_payload")

    def _action_plan(self, actor, action, target_id, parameters, completion=False, occurrence=None):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._action_plan")

    def _action_plan_checked(self, actor, action, target_id, parameters, completion=False, occurrence=None):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._action_plan_checked")

    def submit_intents(self, intents):
        'Arbitrate and publish an externally supplied decision batch atomically.'
        return self._run_rule('admit', {'intents':intents})

    def _submit_intents_inner(self, intents):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._submit_intents_inner")

    def _release(self, occurrence, consume=False):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._release")

    def _resolve(self, occurrence_id):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._resolve")

    @classmethod
    def initialize(cls, config=None, **options):
        return cls(config, **options)

    def _id(self, prefix):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._id")

    def _random(self, domain, key):
        return self.services.randomness.value(self.seed, domain, key)

    def inject_random_values(self, draws):
        'Set explicit keyed variates for controlled, reproducible experiments.\n\nThis supplies numbers, never outcomes. Ordinary handlers still decide\nwhether a draw occurs and calculate/record its actual probability.'
        self._keyed_random_values = self.services.randomness.controlled_values(draws, self._keyed_random_values)

    def _schedule(self, time, phase, kind, agent=None, **fields):
        return self.services.scheduler._schedule(time, phase, kind, agent, **fields)

    def _schedule_decision(self, aid, when):
        return self.services.scheduler._schedule_decision(aid, when)

    def _mark(self, collection, key):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._mark")

    def _evaluate(self, a, at):
        return self._projection._evaluate(a, at)

    def _touch(self, aid):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._touch")

    def _view_agent(self, aid):
        return self._projection._view_agent(aid)

    def snapshot(self):
        return self._projection.snapshot()

    def _commit(self, kind, **details):
        return self._run_rule('clock', {'kind':kind, 'details':details})

    def _path_position(self, occurrence, time):
        return self._projection._path_position(occurrence, time)

    def observe(self, aid):
        return self._projection.observe(aid)

    @staticmethod
    def _public(a):
        from .core.observations import ObservationService
        return ObservationService._public(a)

    def _nearby(self, position, radius):
        "Conservative swept-path buckets, followed by exact-time filtering.\n\nA movement's entire recorded path is in its broad-phase envelope. Thus\ntime advancing never requires scanning every agent to update the grid.\nAdmission, interruption, relocation and lifecycle writes invalidate only\ntheir actors. Candidates still use exact trajectory coordinates and LOS."
        return self._projection._nearby(position, radius)

    def _position_at(self, aid):
        return self._projection._position_at(aid)

    def _schedule_starvation(self, a):
        return self.services.scheduler._schedule_starvation(a)

    def next_decision_batch(self):
        return self.services.decisions.next_decision_batch()

    def next_event_time(self):
        return self.services.scheduler.next_event_time()

    def _decide(self, aids):
        return self.services.decisions._decide(aids)

    def _decide_inner(self, aids):
        return self.services.decisions._decide_inner(aids)

    def _observation_tasks(self, controllers):
        'Freeze only neighborhood records needed by each observer chunk.\n\nWorkers receive no store or coordinator, and policies receive only the\nusual visibility-filtered observation produced inside that worker.'
        return self.services.decisions._observation_tasks(controllers)

    def execution_diagnostics(self):
        'Measured execution metadata, deliberately outside semantic history.'
        return self.services.decisions.execution_diagnostics()

    def _prepare_completions(self, current):
        'Parallelize the independent continuous phase, then commit canonically.\n\nConservative action conflicts are still resolved by the coordinator;\nonly single-agent anchor calculations have disjoint write sets here.'
        return self.services.decisions._prepare_completions(current)

    def advance_until(self, until, max_events=None, return_snapshot=True, should_yield=None):
        return self.services.scheduler.advance_until(until, max_events, return_snapshot, should_yield)

    def _checkpoint_if_due(self):
        'Enforce cadence within a long headless advance at committed boundaries.'
        return self.services.scheduler._checkpoint_if_due()

    def step(self, timestamp=False, return_snapshot=True, should_yield=None):
        return self.services.scheduler.step(timestamp, return_snapshot, should_yield)

    def _dispatch(self, event):
        return self._run_rule('event', {'event':event})

    def _bernoulli(self, occurrence, channel, probability):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._bernoulli")

    def _damage(self, targetid, raw, source, bypass=False):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._damage")

    def _drop(self, a, quantities):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._drop")

    def _close_episode(self, a, outcome):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._close_episode")

    def _die(self, a, source, before_state=None):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._die")

    def _convert(self, a):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._convert")

    def _expose(self, targetid, potency, occurrence):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._expose")

    def _effect(self, agentid, kind, value, duration, source):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._effect")

    def _broadcast(self, actorid, kind, payload, radius, ttl, source):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._broadcast")

    def _finish(self, occurrence, result):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._finish")

    def _geometry_changed(self):
        'Schedule actual future contacts, ending motion 0.01 m before contact.'
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._geometry_changed")

    def intervene(self, change, at=None, id=None):
        return self._run_rule('intervene', {'change':change,'at':at,'id':id})

    def _apply_intervention(self, iid):
        from .core.migration import unsupported_extension
        unsupported_extension("Simulation._apply_intervention")

    def serialize(self):
        from .runtime import serialize
        return serialize(self)

    @classmethod
    def from_serialized(cls,payload,history_path=None,backend=None,workers=None,service_factory=None,persistence_factory=None,rule_set=None):
        from .runtime import from_serialized
        return from_serialized(cls,payload,history_path,backend,workers,service_factory=service_factory,persistence_factory=persistence_factory,rule_set=rule_set)

    def checkpoint(self,path=None):
        from .runtime import checkpoint
        return checkpoint(self,path)

    @classmethod
    def restore(cls,path,**options):
        from .runtime import restore
        return restore(cls,path,**options)

    @classmethod
    def restore_revision(cls,history_path,revision=None,**options):
        """Resume a committed journal boundary, including private model memory."""
        from .runtime import restore_revision
        return restore_revision(cls,history_path,revision=revision,**options)

    def branch(self,output,seed=None):
        from .runtime import branch
        return branch(self,output,seed)

    def close(self):
        from .runtime import close
        return close(self)

    def __enter__(self):
        return self

    def __exit__(self,*exc):
        self.close()
