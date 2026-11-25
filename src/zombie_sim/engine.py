"""Exact event clock, action transactions, lifecycle and local observations.

Rules originate in ontology/zombie_game_ontology_v0.1.md §§3–16. No
acceptance-suite code or fixtures are imported by this implementation.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from fractions import Fraction
import hashlib
import heapq
import json
import math
import multiprocessing
from pathlib import Path
import random
import tempfile
import uuid

from .config import resolve_config, initialize_world
from .domain import profile, capabilities, status
from .geometry import point_blocked, segment_clear, distance_to
from .storage import MemoryStore, SQLiteStore, History
from .actions import ActionSystemMixin
from .runtime import materialize_snapshot


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
        return choose(observation, memory, random.Random(seed), model, parameters)
    except Exception as exc:
        return ({"actor": observation["self_state"]["id"], "action": "wait", "parameters": {"duration": "1"}},
                memory, {"fallback": type(exc).__name__, "message": str(exc)})


class Simulation(ActionSystemMixin):
    """One authoritative coordinator; workers never own mutable world state."""

    def __init__(self, config=None, *, history_path=None, backend=None, workers=None, decision_mode=None,run_id=None):
        self.config = resolve_config(config or {"preset": "small"})
        self.state = initialize_world(self.config)
        self.state["run_id"]=run_id or uuid.uuid4().hex
        self.time = clock(self.state.get("time", 0))
        self.revision = 0
        self.seed = int(self.config.get("seed", 20261106))
        execution = self.config.get("execution", {})
        self.backend = backend or self.config.get("storage",{}).get("backend", "memory")
        self.workers = int(workers or execution.get("workers", self.config.get("workers", 1)))
        self.decision_mode = decision_mode or self.config.get("decision_mode", "model")
        self.horizon = clock(self.config.get("horizon", 1800))
        self.events, self.decisions, self.random_draws = [], [], []
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
            a.pop("infected",None)
            a.setdefault("_evaluated_at", stamp(self.time))
            a.setdefault("_generation", 0)
            a.setdefault("cooldowns", {})
            a.setdefault("effects", {})
            a.setdefault("active_action", None)
            a.setdefault("infection_episode", None)
            if a["type"] == "Human":
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
        if self.backend == "sqlite":
            self.store = SQLiteStore(path, initial=self.state)
            self.history = self.store.history
        elif self.backend == "memory":
            self.history = History(path, initial=self.state)
            self.store = MemoryStore(initial=self.state, history=self.history)
        else:
            raise ValueError("backend must be memory or sqlite")
        self.history_path = str(path)
        self._dirty.clear()
        from .runtime import initialize_history
        initialize_history(self)

    @classmethod
    def initialize(cls, config=None, **options):
        return cls(config, **options)

    def _id(self, prefix):
        self._counter += 1
        self._identity_counters[prefix]=self._identity_counters.get(prefix,0)+1
        return f"{prefix}-{self._identity_counters[prefix]}"

    def _random(self, domain, key):
        digest = hashlib.sha256(f"{self.seed}:{domain}:{key}".encode()).digest()
        return int.from_bytes(digest[:8], "big") / 2**64

    def _schedule(self, time, phase, kind, agent=None, **fields):
        time = clock(time)
        if time < self.time:
            raise ValueError("Cannot schedule in the past")
        self._serial += 1
        key = f"{kind}:{agent}:{fields.get('occurrence', '')}:{stamp(time)}:{self._serial}"
        priority = self._random("event-arbitration", key)
        row=(time, phase, priority, self._serial, {"kind": kind, "agent": agent, **fields})
        heapq.heappush(self.queue,row)
        from .runtime import _encode
        self._runtime_queue_delta.append(["set",["queue",str(self._serial)],_encode(row)])

    def _schedule_decision(self, aid, when):
        token = (aid, stamp(when))
        if self.decision_mode not in {"scripted","external"} and token not in self._decision_due:
            self._decision_due.add(token)
            self._schedule(when, 6, "decision", aid)

    def _mark(self, collection, key):
        self._dirty.add((collection, str(key)))

    def _evaluate(self, a, at):
        previous = clock(a.get("_evaluated_at", 0))
        if at <= previous or a["life"] == 0:
            return a
        elapsed = float(at-previous)
        p = profile(a, stamp(at))
        if a["type"] == "Human":
            before_hunger=Fraction(str(a.get("hunger",20)))
            rate=Fraction(str(p.get("hunger_rate",.05)))
            a["hunger"]=float(min(Fraction(100),before_hunger+rate*(at-previous)))
            if a["hunger"]==100 and before_hunger<100 and rate>0:
                a["starvation_started_at"]=stamp(previous+(100-before_hunger)/rate)
            if a["hunger"]==100:
                a["next_starvation_damage_at"]=a.get("_starvation_due_at",a.get("next_starvation_damage_at"))
        active = self.occurrences.get(a.get("active_action"))
        if active:
            end = min(at, clock(active["planned_end"]))
            start = clock(active["start_at"])
            if active["action"] == "rest":
                a["stamina"] = min(100., float(a["stamina"]) + float(p.get("rest_rate", 4 if a["type"] == "Human" else 3))*float(max(Fraction(0), end-max(previous,start))))
            elif active["action"] in {"move", "dash"}:
                coords, travelled = self._path_position(active, end)
                used = max(0., travelled-float(a.get("_travelled", 0)))
                a["stamina"] = max(0., float(a["stamina"])-used*float(p.get("movement_cost", .1)))
                a["x"], a["y"] = coords
                a["_travelled"] = travelled
        a["_evaluated_at"] = stamp(at)
        return a

    def _touch(self, aid):
        a = self.state["agents"][str(aid)]
        self._evaluate(a, self.time)
        self._mark("agents", aid)
        return a

    def _view_agent(self, aid):
        a = self._evaluate(deepcopy(self.state["agents"][str(aid)]), self.time)
        a.update(profile(a, stamp(self.time)))
        a["status"] = status(a)
        a["action_state"] = "DEAD" if a["life"] == 0 else "BUSY" if a.get("active_action") else "IDLE"
        active = self.occurrences.get(a.get("active_action"))
        a["current_action"] = active["action"] if active else None
        if active and active["action"] == "dash":
            a["speed"] = float(a["base_speed"])*float(a.get("dash_multiplier",1.5))
        ep = self.state["episodes"].get(a.get("infection_episode"))
        if a["type"] == "Human":
            a["infection_progress"] = min(1., float((self.time-clock(ep["onset_at"]))/clock(ep["incubation_duration"]))) if ep else 0.
            if ep:
                a.update({k:ep[k] for k in ("onset_at","incubation_duration","conversion_due_at")})
        return a

    def snapshot(self):
        result = deepcopy(self.state)
        result["agents"] = {aid: self._view_agent(aid) for aid in self.state["agents"]}
        result.update(time=stamp(self.time), revision=self.revision)
        return result

    def _commit(self, kind, **details):
        if not self._batching:
            self._finalize_action_evidence()
        event = {"id": self._id("event"), "time": stamp(self.time), "revision": self.revision+1,
                 "kind": kind, "causes": details.pop("causes", []), **deepcopy(details)}
        if self._batching:
            self._deferred_events.append(event)
            for effect in self._effects_buffer:
                self._deferred_events.append({"id":self._id("event"),"time":stamp(self.time),"revision":self.revision+1,
                                             "causes":[event["id"]],**effect})
            self._effects_buffer.clear()
            return event
        self.state["time"], self.state["revision"] = stamp(self.time), self.revision+1
        delta = [["set", ["time"], stamp(self.time)], ["set", ["revision"], self.revision+1]]
        for collection, key in sorted(self._dirty):
            if key in self.state[collection]:
                if collection == "agents":
                    self.state[collection][key].update(last_state_event_id=event["id"],revision=self.revision+1)
                    self.state[collection][key]["status"] = status(self.state[collection][key])
                delta.append(["set", [collection, key], deepcopy(self.state[collection][key])])
            else:
                delta.append(["remove", [collection, key]])
        try:
            records=[*self._deferred_events,event]
            for effect in self._effects_buffer:
                records.append({"id":self._id("event"),"time":stamp(self.time),"revision":self.revision+1,
                                "causes":[event["id"]],**effect})
            from .runtime import capture_delta,mark_committed
            runtime_delta,command_result=capture_delta(self,self.revision+1,records)
            self.store.commit_delta(delta, expected_version=self.revision, records=records,
                                    runtime_delta=runtime_delta,command_result=command_result)
        except Exception:
            self.state = self.store.read_view()
            self.intents, self.occurrences = self.state["intents"], self.state["occurrences"]
            self.run_status, self.termination_reason = "FAILED", "STORAGE_ERROR"
            raise
        self.revision += 1
        self.events.extend(records)
        self._deferred_events.clear()
        self._effects_buffer.clear()
        self._dirty.clear()
        self._since_checkpoint += 1
        mark_committed(self)
        return event

    def _path_position(self, occurrence, time):
        points = occurrence["parameters"]["path"]
        offset = max(Fraction(0), time-clock(occurrence["start_at"]))
        travelled = 0.
        for left, right in zip(points, points[1:]):
            t0, t1 = clock(left["offset"]), clock(right["offset"])
            length = math.dist(point(left), point(right))
            if offset >= t1:
                travelled += length
                continue
            fraction = min(1., max(0., float((offset-t0)/(t1-t0))))
            return ((float(left["x"])+(float(right["x"])-float(left["x"]))*fraction,
                     float(left["y"])+(float(right["y"])-float(left["y"]))*fraction), travelled+length*fraction)
        return point(points[-1]), travelled

    def observe(self, aid):
        observer = self._view_agent(aid)
        radius = float(observer["sense_r"])
        here = point(observer)
        visible = {}
        for other in self._nearby(here,radius):
            if other == str(aid):
                continue
            if self.state["agents"][other]["life"] == 0:
                continue
            location=self._position_cache[other]
            if math.dist(here,location)>radius or not segment_clear(here,location,self.state["barriers"]):
                continue
            a = self._view_agent(other)
            if a["life"] > 0:
                visible[other] = self._public(a)
        environment = {"barriers": {}, "stockpiles": {}, "remains": {}}
        for name in ("stockpiles", "remains"):
            for key, obj in self.state[name].items():
                nonempty = sum(obj.get("inventory",{}).values()) > 0 if name == "stockpiles" else obj["biomass"] > 0
                if nonempty and math.dist(here,point(obj)) <= radius and segment_clear(here,point(obj),self.state["barriers"]):
                    environment[name][key] = deepcopy(obj)
        for key, b in self.state["barriers"].items():
            if distance_to(here,b) > radius:
                continue
            portions=_visible_surface(here,radius,b,self.state["barriers"])
            if portions:
                # Only visible surface segments are exposed, not hidden corners.
                environment["barriers"][key] = {k: deepcopy(v) for k,v in b.items() if k != "footprint"}
                environment["barriers"][key]["visible_segments"] = portions
        signals = []
        for signal in self.state["signals"].values():
            if str(aid) not in signal["recipients"] or self.time >= clock(signal["expires_at"]):
                continue
            view = {k:deepcopy(v) for k,v in signal.items() if k not in {"recipients","payload"}}
            if observer["type"] == signal["sender_type_at_emission"]:
                view["payload"] = deepcopy(signal["payload"])
            else:
                view["kind"] = "NOISE"
            signals.append(view)
        return {"time":stamp(self.time),"task_horizon":stamp(self.horizon),"revision":self.revision,"world":deepcopy(self.state["world"]),
                "self_state":self._public(observer),"local_agents":visible,"local_environment":environment,
                "received_signals":signals}

    @staticmethod
    def _public(a):
        return {k:deepcopy(v) for k,v in a.items() if not k.startswith("_") and k not in {"memory","model_memory"}}

    def _nearby(self,position,radius):
        """Uniform-grid broad phase rebuilt at exact query times, never stale."""
        cell_size=50.
        if getattr(self,"_spatial_time",None)!=self.time:
            self._spatial_time=self.time
            self._spatial_cells={};self._position_cache={}
            for aid,a in self.state["agents"].items():
                occurrence=self.occurrences.get(a.get("active_action"))
                location=self._path_position(occurrence,self.time)[0] if occurrence and occurrence["action"] in {"move","dash"} else point(a)
                self._position_cache[aid]=location
                cell=(math.floor(location[0]/cell_size),math.floor(location[1]/cell_size))
                self._spatial_cells.setdefault(cell,[]).append(aid)
        lowx,highx=math.floor((position[0]-radius)/cell_size),math.floor((position[0]+radius)/cell_size)
        lowy,highy=math.floor((position[1]-radius)/cell_size),math.floor((position[1]+radius)/cell_size)
        return [aid for x in range(lowx,highx+1) for y in range(lowy,highy+1) for aid in self._spatial_cells.get((x,y),[])]

    def _schedule_starvation(self,a):
        generation = a.setdefault("_hunger_generation",0)
        rate = Fraction(str(profile(a,stamp(self.time)).get("hunger_rate",.05)))
        hunger = Fraction(str(a.get("hunger",20)))
        if rate == 0 and hunger < 100:
            return
        begins = self.time+(100-hunger)/rate if hunger < 100 else self.time
        a["starvation_started_at"] = stamp(begins) if hunger == 100 else None
        due = begins+10
        a["_starvation_due_at"] = stamp(due)
        a["next_starvation_damage_at"] = stamp(due) if hunger == 100 else None
        self._schedule(due,2,"starvation",a["id"],generation=generation)

    def next_decision_batch(self):
        return [self.observe(aid) for aid,a in self.state["agents"].items() if a["life"] > 0 and not a.get("active_action")]

    def next_event_time(self):
        return self.queue[0][0] if self.queue else self.horizon

    def _decide(self, aids):
        self._batching=True
        try:
            self._decide_inner(aids)
        finally:
            self._batching=False
        self._commit("decision_batch",agents=sorted(set(aids)))

    def _decide_inner(self, aids):
        aids = sorted(set(aids))
        tasks, observations = [], []
        for aid in aids:
            a = self.state["agents"][aid]
            if a["life"] == 0 or a.get("active_action"):
                continue
            observation = self.observe(aid)
            assignment = a.get("model_assignment") or {}
            model = assignment.get("model_id", "HumanDefaultModel" if a["type"] == "Human" else "ZombieDefaultModel")
            seed = int(self._random("policy",f"{aid}:{stamp(self.time)}")*2**64)
            tasks.append((observation,deepcopy(self.memories.get(aid,{})),seed,model,assignment.get("parameters")))
            observations.append(observation)
        if self.workers > 1 and len(tasks) >= 8:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(self.workers,mp_context=multiprocessing.get_context("spawn"))
            choices = list(self._pool.map(_policy_call,tasks))
        else:
            choices = list(map(_policy_call,tasks))
        proposals = []
        for observation, (intent,memory,diagnostics) in zip(observations,choices):
            aid = observation["self_state"]["id"]
            self.memories[aid] = deepcopy(memory)
            intent = deepcopy(intent) if isinstance(intent,dict) else {}
            intent["actor"] = aid
            intent.setdefault("id",self._id("intent"))
            decision={"id":self._id("decision"),"time":stamp(self.time),"actor":aid,
                      "observation":observation,"intent":deepcopy(intent),"diagnostics":deepcopy(diagnostics)}
            self.decisions.append(decision)
            self._commit("decision",**decision)
            proposals.append(intent)
        results = self.submit_intents(proposals)
        for result in results:
            if result["status"] == "REJECTED":
                self.submit_intents([{"actor":result["actor"],"action":"wait","parameters":{"duration":"1"},"fallback_for":result["id"]}])

    def _prepare_completions(self,current):
        """Parallelize the independent continuous phase, then commit canonically.

        Conservative action conflicts are still resolved by the coordinator;
        only single-agent anchor calculations have disjoint write sets here.
        """
        if self._prepared_boundary==self.time:
            return
        from .parallel import materialize_agents
        aids=set()
        for event in [current,*[entry[4] for entry in self.queue if entry[0]==self.time and entry[1]==5]]:
            occurrence=self.occurrences.get(event.get("occurrence"))
            if occurrence and occurrence["result"]=="IN_PROGRESS":
                aids.add(occurrence["actor"])
        tasks=[]
        for aid in sorted(aids):
            a=self.state["agents"][aid]
            tasks.append({"agent":deepcopy(a),"occurrence":deepcopy(self.occurrences.get(a.get("active_action"))),
                          "episode":deepcopy(self.state["episodes"].get(a.get("infection_episode"))),"time":stamp(self.time)})
        use_workers=self.workers if len(tasks)>=8 else 1
        if use_workers>1 and self._pool is None:
            self._pool=ProcessPoolExecutor(use_workers,mp_context=multiprocessing.get_context("spawn"))
        for result in materialize_agents(tasks,workers=use_workers,pool=self._pool if use_workers>1 else None):
            self.state["agents"][result["id"]]=result["agent"]
            self._mark("agents",result["id"])
        # Compute bounded deterministic action effects for genuinely disjoint
        # components. Completion validation and all publication remain serial.
        from .parallel import PREPARABLE_ACTIONS, completion_access, effect_task, prepare_effect_groups
        entries=[]
        for event in [current,*[entry[4] for entry in self.queue if entry[0]==self.time and entry[1]==5]]:
            occurrence=self.occurrences.get(event.get("occurrence"))
            if not occurrence or occurrence["result"]!="IN_PROGRESS":
                continue
            task=None
            if occurrence["action"] in PREPARABLE_ACTIONS:
                actor=self._view_agent(occurrence["actor"])
                target_id=occurrence.get("target")
                target=self._view_agent(target_id) if target_id in self.state["agents"] else self.state["barriers"].get(target_id)
                try:
                    task=effect_task(occurrence,actor,target,profile(actor,stamp(self.time)))
                except (KeyError,TypeError,ValueError):
                    pass  # The ordinary completion validator supplies the outcome.
            entries.append({"access":completion_access(occurrence),"task":task})
        effect_workers=self.workers if len(entries)>1 else 1
        if effect_workers>1 and self._pool is None:
            self._pool=ProcessPoolExecutor(effect_workers,mp_context=multiprocessing.get_context("spawn"))
        self._prepared_effects,statistics=prepare_effect_groups(entries,workers=effect_workers,pool=self._pool if effect_workers>1 else None)
        if not hasattr(self,"parallel_effect_stats"):
            self.parallel_effect_stats={}
        for key,value in statistics.items():
            self.parallel_effect_stats[key]=self.parallel_effect_stats.get(key,0)+value
        self._prepared_boundary=self.time

    def advance_until(self, until, max_events=None,return_snapshot=True):
        until = min(clock(until),self.horizon)
        if until < self.time:
            raise ValueError("Use history replay to inspect the past")
        count = 0
        self.run_status = "RUNNING"
        while self.queue and self.queue[0][0] <= until:
            if max_events is not None and count >= max_events:
                break
            when,phase,priority,serial,event = heapq.heappop(self.queue)
            self._runtime_queue_delta.append(["remove",["queue",str(serial)]])
            self.time = when
            previous_revision=self.revision
            if phase==5:
                self._prepare_completions(event)
            if phase == 6:
                batch = [event["agent"]]
                while self.queue and self.queue[0][0] == when and self.queue[0][1] == 6:
                    queued=heapq.heappop(self.queue)
                    self._runtime_queue_delta.append(["remove",["queue",str(queued[3])]])
                    batch.append(queued[4]["agent"])
                for aid in batch:
                    self._decision_due.discard((aid,stamp(when)))
                if when < self.horizon:
                    self._decide(batch)
            else:
                self._dispatch(event)
            if self.revision==previous_revision:
                self._commit("scheduler_advanced",scheduled_kind=event["kind"])
            count += 1
            self._checkpoint_if_due()
            if not any(a["life"] > 0 for a in self.state["agents"].values()):
                self.run_status,self.termination_reason="COMPLETED","NO_LIVING_AGENTS"
                break
        if max_events is None and self.run_status != "COMPLETED":
            self.time = until
            self._commit("clock_advanced")
        if self.time >= self.horizon and (not self.queue or self.queue[0][0]>self.horizon):
            self.run_status,self.termination_reason="COMPLETED","HORIZON"
        elif self.run_status == "RUNNING":
            self.run_status="PAUSED"
        self._checkpoint_if_due()
        return self.snapshot() if return_snapshot else {"time":stamp(self.time),"revision":self.revision,"status":self.run_status}

    def _checkpoint_if_due(self):
        """Enforce cadence within a long headless advance at committed boundaries."""
        interval=clock(self.config.get("checkpoint_interval",30))
        transactions=int(self.config.get("checkpoint_transactions",50000))
        if self.time-self._last_checkpoint>=interval or self._since_checkpoint>=transactions:
            self.checkpoint(str(Path(self.history_path).with_suffix(".checkpoint.json")))

    def step(self, timestamp=False,return_snapshot=True):
        if not self.queue:
            return self.snapshot()
        return self.advance_until(self.queue[0][0],max_events=None if timestamp else 1,return_snapshot=return_snapshot)

    def _dispatch(self,event):
        kind,aid=event["kind"],event.get("agent")
        if kind == "complete":
            self._resolve(event["occurrence"])
        elif kind == "starvation":
            a=self._touch(aid)
            if a["life"] > 0 and a["type"]=="Human" and a.get("_hunger_generation",0)==event["generation"]:
                a["hunger"]=100.
                a["starvation_started_at"]=a.get("starvation_started_at") or stamp(self.time-10)
                self._damage(aid,1,"starvation",bypass=True)
                if a["life"] > 0:
                    a["next_starvation_damage_at"]=stamp(self.time+10)
                    a["_starvation_due_at"]=stamp(self.time+10)
                    self._schedule(self.time+10,2,"starvation",aid,generation=event["generation"])
                self._commit("starvation",agent=aid)
        elif kind == "conversion":
            a=self._touch(aid)
            if a["life"] > 0 and a.get("infection_episode")==event["episode"]:
                self._convert(a)
                self._commit("conversion",agent=aid,episode=event["episode"])
        elif kind == "recharge":
            a=self._touch(aid)
            if a["life"]>0 and a.get("role")=="SPITTER" and a["_generation"]==event["generation"]:
                p=profile(a,stamp(self.time)); maximum=int(p.get("max_spit_charges",3))
                a["spit_charges"]=min(maximum,a["spit_charges"]+1)
                a["next_charge_at"]=None
                if a["spit_charges"]<maximum:
                    a["next_charge_at"]=stamp(self.time+clock(p.get("recharge_interval",30)))
                    self._schedule(a["next_charge_at"],2,"recharge",aid,generation=a["_generation"])
                self._commit("recharge",agent=aid)
        elif kind == "expire":
            a=self._touch(aid)
            effect=a["effects"].get(event["effect"])
            if effect and clock(effect["end_at"])<=self.time:
                del a["effects"][event["effect"]]
                self._commit("effect_expired",agent=aid,effect=event["effect"])
        elif kind == "intervention":
            self._apply_intervention(event["intervention"])
        elif kind == "blocked":
            occurrence=self.occurrences.get(event["occurrence"])
            if occurrence and occurrence["result"]=="IN_PROGRESS":
                self._finish(occurrence,"PARTIAL_BLOCKED")
                self._commit("movement_blocked",occurrence=occurrence["id"])
        elif kind == "signal_expire":
            sid=event["signal"]
            if sid in self.state["signals"]:
                del self.state["signals"][sid]
                self._mark("signals",sid)
                self._commit("signal_expired",signal=sid)

    def _bernoulli(self, occurrence, channel, probability):
        probability=min(1.,max(0.,float(probability)))
        raw=self._random(channel,occurrence["id"])
        result=raw < probability
        record={"occurrence":occurrence["id"],"channel":channel,"probability":probability,
                "value":raw,"outcome":result,"time":stamp(self.time)}
        self.random_draws.append(record)
        self._effects_buffer.append({"kind":"random_draw",**record})
        return result

    def _damage(self, targetid, raw, source, bypass=False):
        a=self._touch(targetid)
        if a["life"] == 0:
            return 0
        resistance=float(profile(a,stamp(self.time))["damage_resistance"])
        mitigated=half_up(raw if bypass else Fraction(str(raw))*(1-Fraction(str(resistance))))
        actual=min(a["life"],mitigated)
        origin=self.occurrences.get(source,{}) if isinstance(source,str) else source
        self._effects_buffer.append({"kind":"damage","actor":origin.get("actor") if isinstance(origin,dict) else None,
                                     "target":str(targetid),"target_type":a["type"],"source":source if isinstance(source,str) else source.get("id"),
                                     "raw_damage":raw,"mitigated_damage":mitigated,"actual_damage":actual})
        before=deepcopy(a)
        a["life"]-=actual
        if a["life"]==0:
            self._die(a,source if isinstance(source,str) else source["id"],before_state=before)
        return actual

    def _drop(self, a, quantities):
        quantities={r:int(q) for r,q in quantities.items() if int(q)>0}
        if not quantities:
            return None
        sid=self._id("stockpile")
        self.state["stockpiles"][sid]={"id":sid,"x":a["x"],"y":a["y"],
                                       "inventory":{r:quantities.get(r,0) for r in RESOURCES},
                                       "reserved":{r:0 for r in RESOURCES},"created_at":stamp(self.time)}
        self._mark("stockpiles",sid)
        self._effects_buffer.append({"kind":"inventory_drop","agent":a["id"],"stockpile":sid,"quantities":quantities})
        return sid

    def _close_episode(self,a,outcome):
        eid=a.get("infection_episode")
        if eid:
            ep=self.state["episodes"][eid]
            ep.update(outcome=outcome,ended_at=stamp(self.time),end_revision=self.revision+1)
            self._mark("episodes",eid)
        a["infection_episode"]=None
        return eid

    def _die(self,a,source,before_state=None):
        if a.get("death_at") is not None:
            return
        before=before_state or deepcopy(a)
        active=self.occurrences.get(a.get("active_action"))
        if active:
            active["actor_before_end"]={**deepcopy(before),"at_time":stamp(self.time),"revision":self.revision}
            if active.get("target") in self.state["agents"]:
                active.setdefault("target_before_end",self._capture_action_agent(active["target"]))
            self._finish(active,"CANCELLED_BY_DEATH")
        eid=self._close_episode(a,"HOST_DIED")
        if a["type"]=="Human":
            self._drop(a,a["inventory"])
            a["inventory"]={r:0 for r in RESOURCES}
            a["reserved"]={r:0 for r in RESOURCES}
            a["starvation_started_at"]=a["next_starvation_damage_at"]=None
            a.pop("_starvation_due_at",None)
        old_model=deepcopy(a.get("model_assignment"))
        old_memory=self.memories.pop(a["id"],{})
        a.update(role=None,model_assignment=None,effects={},cooldowns={},active_action=None,
                 death_at=stamp(self.time),death_cause=source,status="DEAD")
        a["_generation"]+=1
        a["_hunger_generation"]=a.get("_hunger_generation",0)+1
        a["next_charge_at"]=None
        a.pop("_travelled",None)
        if active:
            active["actor_after_end"]=self._capture_action_agent(a["id"],after=True)
        rid=self._id("remains")
        self.state["remains"][rid]={"id":rid,"source_agent_id":a["id"],"x":a["x"],"y":a["y"],
                                    "biomass":4,"reserved_biomass":0,"created_at":stamp(self.time)}
        self._mark("remains",rid)
        self._mark("agents",a["id"])
        self._effects_buffer.append({"kind":"death","agent_id":a["id"],"agent":a["id"],"source":source,
                                     "episode_id":eid,"before_state":before,"after_state":deepcopy(a),
                                     "retired_model":old_model,"retired_memory":old_memory,"remains":rid})

    def _convert(self,a):
        before=deepcopy(a)
        eid=a["infection_episode"]
        active=self.occurrences.get(a.get("active_action"))
        if active:
            self._finish(active,"CANCELLED_BY_CONVERSION")
        self._close_episode(a,"CONVERTED")
        self._drop(a,a["inventory"])
        old_model=deepcopy(a.get("model_assignment"))
        old_memory=self.memories.pop(a["id"],{})
        for key in ("hunger","inventory","reserved","carry_capacity","starvation_started_at",
                    "next_starvation_damage_at","_starvation_due_at","type_profile","role_profile","profile"):
            a.pop(key,None)
        a.update(type="Zombie",status="ACTIVE",role=None,effects={},cooldowns={},active_action=None,
                 profile={},type_profile=deepcopy(self.config.get("profiles",{}).get("Zombie",{})),
                 model_assignment={"model_id":"ZombieDefaultModel","version":"1"})
        a["_generation"]+=1
        a["_hunger_generation"]=a.get("_hunger_generation",0)+1
        if active:
            active["actor_after_end"]=self._capture_action_agent(a["id"],after=True)
        self._mark("agents",a["id"])
        self._effects_buffer.append({"kind":"conversion","agent_id":a["id"],"agent":a["id"],"episode_id":eid,
                                     "before_state":before,"after_state":deepcopy(a),
                                     "retired_model":old_model,"retired_memory":old_memory})
        self._schedule_decision(a["id"],self.time)

    def _expose(self,targetid,potency,occurrence):
        a=self._touch(targetid)
        if a["life"]==0 or a["type"]!="Human" or a.get("infection_episode"):
            return False
        resistance=float(profile(a,stamp(self.time))["infection_resistance_effective"])
        if not self._bernoulli(occurrence,"infection",float(potency)*(1-resistance)):
            return False
        eid=self._id("episode")
        duration=clock(self.config.get("incubation_duration",300))
        self.state["episodes"][eid]={"id":eid,"episode_id":eid,"agent_id":str(targetid),
                                      "source_kind":occurrence["action"],"source_agent_id":occurrence["actor"],
                                      "source_event_id":occurrence["id"],"onset_at":stamp(self.time),
                                      "onset_revision":self.revision+1,
                                      "incubation_duration":stamp(duration),"conversion_due_at":stamp(self.time+duration),
                                      "ended_at":None,"end_revision":None,"outcome":"ONGOING"}
        a["infection_episode"]=eid
        self._mark("episodes",eid)
        self._schedule(self.time+duration,3,"conversion",a["id"],episode=eid)
        self._effects_buffer.append({"kind":"infection","actor":occurrence["actor"],"target":str(targetid),"episode":eid})
        return True

    def _effect(self,agentid,kind,value,duration,source):
        a=self._touch(agentid)
        if a["life"]==0:
            return None
        end=self.time+clock(duration)
        matching=next((key for key,e in a["effects"].items() if e["kind"]==kind and float(e["value"])==float(value)),None)
        key=matching or (kind if kind not in a["effects"] else self._id(kind))
        if matching:
            end=max(end,clock(a["effects"][key]["end_at"]))
        a["effects"][key]={"kind":kind,"value":value,"start_at":stamp(self.time),"end_at":stamp(end),"source":source}
        self._schedule(end,0,"expire",agentid,effect=key)
        self._effects_buffer.append({"kind":"effect_applied","agent":agentid,"effect":deepcopy(a["effects"][key])})
        return key

    def _broadcast(self,actorid,kind,payload,radius,ttl,source):
        a=self._touch(actorid)
        recipients=[]
        for other in self._nearby(point(a),float(radius)):
            if other==actorid:
                continue
            candidate=self._view_agent(other)
            if candidate["life"]>0 and math.dist(point(a),point(candidate))<=float(radius):
                recipients.append(other)
        sid=self._id("signal")
        self.state["signals"][sid]={"id":sid,"sender_id":actorid,"sender_type_at_emission":a["type"],
                                     "position_at_emission":[a["x"],a["y"]],"radius":float(radius),
                                     "kind":kind,"payload":deepcopy(payload),"emitted_at":stamp(self.time),
                                     "expires_at":stamp(self.time+clock(ttl)),"recipients":recipients,"source":source}
        self._mark("signals",sid)
        self._schedule(self.time+clock(ttl),0,"signal_expire",signal=sid)
        self._effects_buffer.append({"kind":"signal_emitted","agent":actorid,"signal":sid,"recipients":recipients})
        return sid

    def _finish(self,occurrence,result):
        if occurrence["result"]!="IN_PROGRESS":
            return
        a=self._touch(occurrence["actor"])
        occurrence.setdefault("actor_before_end",self._capture_action_agent(a["id"]))
        if occurrence.get("target") in self.state["agents"]:
            occurrence.setdefault("target_before_end",self._capture_action_agent(occurrence["target"]))
        self._release(occurrence)
        occurrence.update(result=result,resolved_at=stamp(self.time))
        if a.get("active_action")==occurrence["id"]:
            a["active_action"]=None
        a.pop("_travelled",None)
        cooldown=clock(occurrence.get("cooldown",0))
        if cooldown and a["life"]>0:
            a["cooldowns"][occurrence["action"]]=stamp(self.time+cooldown)
        occurrence["actor_after_end"]=self._capture_action_agent(a["id"],after=True)
        targetid=occurrence.get("target")
        if targetid in self.state["agents"]:
            occurrence["target_after_end"]=self._capture_action_agent(targetid,after=True)
        self._mark("occurrences",occurrence["id"])
        self._effects_buffer.append({"kind":"action_result","actor":a["id"],"target":targetid,
                                     "occurrence":occurrence["id"],"action":occurrence["action"],"result":result})
        if a["life"]>0:
            self._schedule_decision(a["id"],self.time)

    def _geometry_changed(self):
        """Schedule actual future contacts, ending motion 0.01 m before contact."""
        from .geometry import blocking
        for occurrence in list(self.occurrences.values()):
            if occurrence["result"]!="IN_PROGRESS" or occurrence["action"] not in {"move","dash"}:
                continue
            a=self._touch(occurrence["actor"])
            now_offset=self.time-clock(occurrence["start_at"])
            remaining=[{"x":a["x"],"y":a["y"],"offset":stamp(now_offset)}]
            remaining.extend(p for p in occurrence["parameters"]["path"] if clock(p["offset"])>now_offset)
            travelled=0.
            collision=None
            for left,right in zip(remaining,remaining[1:]):
                length=math.dist(point(left),point(right))
                for b in self.state["barriers"].values():
                    if not blocking(b):
                        continue
                    interval=_segment_contact(point(left),point(right),list(map(float,b["footprint"])))
                    if interval is not None:
                        distance=travelled+length*float(interval[0])
                        if collision is None or distance<collision:
                            collision=distance
                travelled+=length
            if collision is None:
                continue
            stop_distance=max(0.,collision-.01)
            covered=0.
            stop=self.time
            for left,right in zip(remaining,remaining[1:]):
                length=math.dist(point(left),point(right))
                if covered+length>=stop_distance and length>0:
                    fraction=(stop_distance-covered)/length
                    stop=clock(occurrence["start_at"])+clock(left["offset"])+(clock(right["offset"])-clock(left["offset"]))*Fraction(str(fraction))
                    break
                covered+=length
            if stop<=self.time:
                self._finish(occurrence,"PARTIAL_BLOCKED")
            else:
                self._schedule(stop,0,"blocked",a["id"],occurrence=occurrence["id"])

    def intervene(self,change,at=None,id=None):
        if not self.config.get("interventions_enabled",False):
            raise ValueError("This frozen scenario does not authorize interventions")
        when=self.time if at is None else clock(at)
        if when<self.time:
            raise ValueError("Interventions cannot alter committed history")
        iid=id or self._id("intervention")
        if iid in self.state["interventions"]:
            if self.state["interventions"][iid]["change"]!=change:
                raise ValueError("Intervention identity already names a different command")
            return deepcopy(self.state["interventions"][iid])
        item={"id":iid,"at":stamp(when),"change":deepcopy(change),"status":"PENDING"}
        self.state["interventions"][iid]=item
        self._mark("interventions",iid)
        self._schedule(when,4,"intervention",intervention=iid)
        self._commit("intervention_scheduled",intervention=iid)
        return deepcopy(item)

    def _apply_intervention(self,iid):
        from .registry import ROLES
        from .policies import create_model
        item=self.state["interventions"][iid]
        change=item["change"]
        # Validation failures must not leave half a role/capacity/resource change.
        rollback=(deepcopy(self.state),deepcopy(self.memories),list(self.queue),self._serial,
                  set(self._decision_due),list(self._effects_buffer),set(self._dirty),self._counter,
                  deepcopy(self._identity_counters),deepcopy(self._runtime_queue_delta))
        try:
            kind=change["kind"]
            if kind=="add_resource":
                resource=change.get("resource",change.get("resource_type"))
                quantity=change["quantity"]
                if resource not in RESOURCES or type(quantity) is not int or quantity<=0:
                    raise ValueError("Resource addition requires a portable resource and positive integer quantity")
                sid=change.get("stockpile")
                if sid in self.state["stockpiles"]:
                    self.state["stockpiles"][sid]["inventory"][resource]+=quantity
                    self._mark("stockpiles",sid)
                else:
                    x,y=float(change["x"]),float(change["y"])
                    if not 0<=x<=self.state["world"]["length"] or not 0<=y<=self.state["world"]["width"] or point_blocked((x,y),self.state["barriers"]):
                        raise ValueError("Resource location is not traversable")
                    actual=self._drop({"id":"intervention","x":x,"y":y},{resource:quantity})
                    if sid:
                        self.state["stockpiles"][sid]=self.state["stockpiles"].pop(actual)
                        self.state["stockpiles"][sid]["id"]=sid
                        self._mark("stockpiles",actual);self._mark("stockpiles",sid)
            elif kind in {"replace_role","replace_model"}:
                aid=str(change["agent"])
                a=self._touch(aid)
                if a["life"]==0:
                    raise ValueError("Dead identities cannot receive active assignments")
                if kind=="replace_role":
                    role=change.get("role")
                    if role is not None and (role not in ROLES or ROLES[role]["type"]!=a["type"]):
                        raise ValueError("Incompatible role")
                    old=a.get("role")
                    old_role_actions=set(ROLES.get(old,{}).get("actions",[]))
                    current=self.occurrences.get(a.get("active_action"))
                    if current and current["action"] in old_role_actions:
                        self._finish(current,"CANCELLED_BY_INTERVENTION")
                    a["role"]=role;a["role_profile"]={};a["_generation"]+=1
                    a["effects"]={k:v for k,v in a["effects"].items() if v["kind"] not in {"guard","recon","dash"}}
                    a["next_charge_at"]=None
                    if role=="SPITTER":
                        a.update(spit_charges=int(ROLES[role].get("max_spit_charges",3)),reserved_charges=0)
                    elif old=="SPITTER":
                        a.pop("spit_charges",None);a.pop("reserved_charges",None)
                    if a["type"]=="Human":
                        a["carry_capacity"]=int(ROLES.get(role,{}).get("carry_capacity",10))
                        excess=max(0,sum(a["inventory"].values())-a["carry_capacity"])
                        dropped={}
                        for resource in change.get("drop_order",["MATERIAL","FOOD","MEDICAL_SUPPLY"]):
                            if resource not in RESOURCES:raise ValueError("Invalid capacity-drop resource")
                            amount=min(excess,a["inventory"][resource]-a["reserved"][resource])
                            a["inventory"][resource]-=amount;excess-=amount;dropped[resource]=amount
                        if excess:
                            current=self.occurrences.get(a.get("active_action"))
                            if current:self._finish(current,"CANCELLED_BY_INTERVENTION")
                            for resource in RESOURCES:
                                amount=min(excess,a["inventory"][resource]);a["inventory"][resource]-=amount;excess-=amount;dropped[resource]=dropped.get(resource,0)+amount
                        self._drop(a,dropped)
                else:
                    create_model(change["model_id"])
                    policy=change.get("memory_policy")
                    if policy not in {"reset","preserve"}:
                        raise ValueError("Model replacement requires reset or preserve memory policy")
                    a["model_assignment"]={"model_id":change["model_id"],"version":str(change.get("model_version","1"))}
                    if policy=="reset":self.memories.pop(aid,None)
            else:
                raise ValueError("Unknown intervention kind")
            item.update(status="APPLIED",effective_time=stamp(self.time),effective_revision=self.revision+1)
        except (KeyError,ValueError,TypeError) as exc:
            (self.state,self.memories,self.queue,self._serial,self._decision_due,self._effects_buffer,
             self._dirty,self._counter,self._identity_counters,self._runtime_queue_delta)=rollback
            self.occurrences,self.intents=self.state["occurrences"],self.state["intents"]
            item=self.state["interventions"][iid]
            item.update(status="REJECTED",reason=str(exc))
        self._mark("interventions",iid)
        self._commit("intervention",intervention=iid,status=item["status"],change=change)

    def serialize(self):
        from .runtime import serialize
        return serialize(self)

    @classmethod
    def from_serialized(cls,payload,history_path=None,backend=None,workers=None):
        from .runtime import from_serialized
        return from_serialized(cls,payload,history_path,backend,workers)

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
