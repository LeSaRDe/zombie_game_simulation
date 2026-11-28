"""Versioned acceptance adapter over the real simulation and public services.

Only request data enters this module. It neither imports acceptance expectations
nor computes alternative action effects. Numeric and naming conversions are the
explicit boundary between the suite's normalized wire schema and production API.
"""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Mapping, Sequence
from fractions import Fraction
import json
import math
from pathlib import Path

from .config import ConfigError, initialize_world, resolve_config
from .domain import TYPE_PROFILES
from .engine import Simulation
from .registry import ROLES

NORMALIZATION_VERSION="zombie-sim/acceptance-normalization-v1"
_PROFILE_FIELDS=set().union(*(set(v) for v in TYPE_PROFILES.values()),
                            *(set(v)-{"actions","type","registry_version"} for v in ROLES.values()))
_REAL_FIELDS=_PROFILE_FIELDS|{"x","y","length","width","stamina","hunger","strength","value","radius",
                             "minimum_separation","cross_type_separation","horizon","checkpoint_interval"}
_SEQUENCES={"rect","footprint","center","position","position_at_emission"}


def _number(value):
    if not isinstance(value,str):return value
    try:return float(Fraction(value))
    except (ValueError,ZeroDivisionError):
        try:return float(value)
        except ValueError:return value


def request_numbers(value,key=None):
    if isinstance(value,dict):return {k:request_numbers(v,k) for k,v in value.items()}
    if isinstance(value,list):return [request_numbers(v,"x" if key in _SEQUENCES else key) for v in value]
    return _number(value) if key in _REAL_FIELDS else value


def normalize_intent(intent):
    intent=request_numbers(deepcopy(intent))
    payload=intent.get("parameters",{}).get("payload",{})
    if isinstance(payload,dict) and isinstance(payload.get("position"),list) and len(payload["position"])==2:
        payload["position"]={"x":payload["position"][0],"y":payload["position"][1]}
    return intent


def fixture_config(setup, config=None):
    """Translate fixture names, preserving all explicit values and invalid data."""
    setup=request_numbers(deepcopy(setup));config=request_numbers(deepcopy(config or {}))
    if setup.get("preset"):
        result={"preset":setup["preset"],**config}
    else:
        result={**config,"world":{"length":setup.get("length",100.),"width":setup.get("width",100.)},
                "placement":{"minimum_separation":0.,"cross_type_separation":0.},
                "agents":deepcopy(setup.get("agents",[])),"barriers":[],"stockpiles":[],
                "shelters":deepcopy(setup.get("shelters",[])),"remains":deepcopy(setup.get("remains",[])),"state_import":True}
        for field in ("episodes","reservations","signals","time"):
            if field in setup:result[field]=deepcopy(setup[field])
        for agent in result["agents"]:
            agent.setdefault("profile",{})
            for key in tuple(agent):
                if key in _PROFILE_FIELDS and key not in {"carry_capacity"}:
                    agent["profile"][key]=agent.pop(key)
            if "infection" in agent:
                episode=agent.pop("infection")
                agent["initial_infection"]=episode
                agent["infected"]=True
            if isinstance(agent.get("model_assignment"),dict) and "model_version" in agent["model_assignment"]:
                agent["model_assignment"]["version"]=agent["model_assignment"].pop("model_version")
        for barrier in setup.get("barriers",[]):
            barrier=deepcopy(barrier)
            if "kind" in barrier:barrier["type"]=barrier.pop("kind")
            if "rect" in barrier:barrier["footprint"]=barrier.pop("rect")
            result["barriers"].append(barrier)
        for stock in setup.get("stockpiles",[]):
            stock=deepcopy(stock)
            if "stock" in stock:stock["inventory"]=stock.pop("stock")
            result["stockpiles"].append(stock)
        for remains in result["remains"]:
            if "source_agent" in remains:remains["source_agent_id"]=remains.pop("source_agent")
    if "backend" in result:result.setdefault("storage",{})["backend"]=result.pop("backend")
    if "workers" in result:result.setdefault("execution",{})["workers"]=result.pop("workers")
    return result


def _wire(value,aliases=None,key=None):
    aliases=aliases or {}
    if isinstance(value,Mapping):
        return {aliases.get(k,k):_wire(v,aliases,k) for k,v in value.items()}
    if isinstance(value,Sequence) and not isinstance(value,(str,bytes)):return [_wire(v,aliases,key) for v in value]
    if isinstance(value,str):return aliases.get(value,value)
    if isinstance(value,float):
        if not math.isfinite(value):raise ValueError("Nonfinite actual engine result")
        return repr(value)
    if isinstance(value,Fraction):return str(value)
    if key in {"revision","onset_revision","end_revision","ledger_revision","ledger_sequence"} and value is not None:
        return str(value)
    return value


def occurrence_aliases(sim):
    return {key:str(value.get("intent_id",key)) for key,value in sim.occurrences.items()}


def normalize_snapshot(sim_or_snapshot, occurrence_aliases=None, *, copy_snapshot=True):
    """Normalize a snapshot while returning a detached JSON-compatible tree.

    A caller owning a fresh private snapshot may omit the preliminary deepcopy;
    _wire still rebuilds every mapping and sequence before field normalization.
    Ordinary callers retain the existing copy behavior by default.
    """
    if isinstance(sim_or_snapshot,Simulation):
        sim=sim_or_snapshot;state=sim.snapshot()
        for aid,agent in state["agents"].items():agent["model_memory"]=deepcopy(sim.memories.get(aid,{}))
        aliases={key:str(value.get("intent_id",key)) for key,value in sim.occurrences.items()}
    else:state=deepcopy(sim_or_snapshot) if copy_snapshot else sim_or_snapshot;aliases=occurrence_aliases or {}
    state=_wire(state,aliases)
    for agent in state.get("agents",{}).values():
        for key in tuple(agent):
            if key.startswith("_"):agent.pop(key)
        assignment=agent.get("model_assignment")
        if isinstance(assignment,dict):assignment["model_version"]=assignment.pop("version",assignment.get("model_version","1"))
        for key in ("role","active_action","infection_episode"):agent.setdefault(key,None)
        for effect in agent.get("effects",{}).values():
            if "value" in effect:effect["magnitude"]=effect["value"]
    for barrier in state.get("barriers",{}).values():
        barrier["kind"]=barrier.pop("type",barrier.get("kind"))
        if "footprint" in barrier:barrier["rect"]=barrier.pop("footprint")
    for stock in state.get("stockpiles",{}).values():stock["stock"]=stock.pop("inventory",stock.get("stock",{}))
    for remains in state.get("remains",{}).values():remains["source_agent"]=remains.pop("source_agent_id",remains.get("source_agent"))
    for episode in state.get("episodes",{}).values():
        episode["agent"]=episode.pop("agent_id",episode.get("agent"))
        if episode.get("outcome") is None:episode["outcome"]="ONGOING"
    state["revision"]=str(state["revision"])
    return state


def normalize_trace(sim,aliases=None):
    aliases=aliases or occurrence_aliases(sim)
    intents={key:{**deepcopy(value),**deepcopy(value.get("outcome",{}))} for key,value in sim.intents.items()}
    events=_wire(sim.events,aliases)
    actual_event_ids={event["id"] for event in events}
    for event in events:
        # Only known heterogeneous edges are translated. Unknown/dangling causal
        # event references remain visible for the independent invariant checker.
        occurrence_causes=[cause for cause in event.get("causes",[]) if cause not in actual_event_ids and cause in aliases.values()]
        intervention_causes=[cause for cause in event.get("causes",[]) if cause not in actual_event_ids and cause in sim.state["interventions"]]
        if occurrence_causes:event["occurrence_causes"]=occurrence_causes
        if intervention_causes:event["intervention_causes"]=intervention_causes
        event["causes"]=[cause for cause in event.get("causes",[]) if cause not in occurrence_causes and cause not in intervention_causes]
    draws=_wire(sim.random_draws,aliases)
    for draw in draws:
        draw["intent"]=draw.get("occurrence")
        source=next((event["id"] for event in events if event.get("kind")=="random_draw" and event.get("occurrence")==draw.get("occurrence") and event.get("channel")==draw.get("channel")),None)
        if source is not None:draw["source_event_id"]=source
    return {"intents":_wire(intents,aliases),"occurrences":_wire(sim.occurrences,aliases),
            "events":events,"random_draws":draws,"interventions":_wire(sim.state["interventions"],aliases)}


class ControlledSimulation(Simulation):
    """Keyed random-value injection; ordinary engine computes every probability."""
    def __init__(self,*args,draws=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.inject_random_values(draws or [])


class FrameworkTestAdapter:
    def __init__(self,*,workdir):
        self.workdir=Path(workdir);self.workdir.mkdir(parents=True,exist_ok=True)
        self.simulations=[]
        self.retention_directory=None
        self._history_retained=False

    def new_simulation(self,setup,config=None,draws=None):
        options=fixture_config(setup,config)
        sim=ControlledSimulation(options,history_path=self.workdir/f"run-{len(self.simulations)}.sqlite",draws=draws)
        self.simulations.append(sim)
        return sim

    def simulation_steps(self,sim,steps,response=None):
        response=response if response is not None else {"snapshots":{},"observations":{}}
        response.setdefault("snapshots",{});response.setdefault("observations",{})
        for step in steps:
            operation=step["op"]
            if operation=="submit":
                intent=normalize_intent({k:v for k,v in step.items() if k!="op"})
                sim.submit_intents([intent])
            elif operation=="submit_batch":sim.submit_intents([normalize_intent(intent) for intent in step["intents"]])
            elif operation=="advance":sim.advance_until(step["to"],return_snapshot=False)
            elif operation=="snapshot":response["snapshots"][step["label"]]=normalize_snapshot(sim)
            elif operation=="observe":response["observations"][step["label"]]=_wire(sim.observe(step["actor"]),occurrence_aliases(sim))
            elif operation=="intervene":sim.intervene(request_numbers(step["change"]),at=step.get("at"),id=step.get("id"))
            else:raise NotImplementedError(f"Unsupported simulation operation {operation}")
        response.update(normalize_trace(sim))
        response["normalization"]={"version":NORMALIZATION_VERSION,"occurrence_aliases":occurrence_aliases(sim)}
        return response

    def execute(self,request):
        kind=request["kind"]
        if kind=="simulation":
            sim=self.new_simulation(request["setup"],request.get("config"),request.get("draws"))
            return self.simulation_steps(sim,request["steps"])
        if kind=="validation":
            try:
                initialize_world(fixture_config(request["setup"],request.get("config")))
                return {"validation":{"valid":True,"issues":[]}}
            except ConfigError as error:
                message=str(error);code=getattr(error,"code",None) or _validation_code(message)
                return {"validation":{"valid":False,"issues":[{"code":code,"message":message,"path":message.split(":",1)[0]}]}}
        from .testing_workflows import execute_workflow
        return execute_workflow(self,request)

    def close(self):
        for sim in reversed(self.simulations):sim.close()
        if self.retention_directory and not self._history_retained:
            _retain_histories(self.workdir,Path(self.retention_directory))
            self._history_retained=True


def _retain_histories(workdir,destination):
    """Opt-in retention of complete primary ledgers after coordinators close.

    SQLite backup includes world/runtime journals and all events. Redundant
    checkpoint sidecars are omitted; no records are filtered from primary files.
    The factory alone enables retention, so nested workflow adapters do not copy
    the same run more than once. No case identifiers or expectations are read.
    """
    import hashlib
    import os
    import sqlite3
    import uuid
    destination=destination.expanduser().absolute();destination.mkdir(parents=True,exist_ok=True)
    retained=[]
    for source in sorted(workdir.rglob("*.sqlite")):
        if source.name.endswith(".history.sqlite"):continue
        reader=sqlite3.connect(f"file:{source.absolute()}?mode=ro",uri=True)
        try:
            if reader.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='commits'").fetchone() is None:continue
            target=destination/source.relative_to(workdir)
            if target.exists():raise FileExistsError(f"Refusing to replace retained history: {target}")
            target.parent.mkdir(parents=True,exist_ok=True)
            partial=target.with_name(target.name+"."+uuid.uuid4().hex+".partial")
            writer=sqlite3.connect(partial)
            try:
                reader.backup(writer)
                revision=writer.execute("SELECT MAX(revision) FROM commits").fetchone()[0]
                if writer.execute("PRAGMA quick_check").fetchone()[0]!="ok":raise ValueError("Retained history failed SQLite integrity verification")
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:writer.close()
            with partial.open("rb") as stream:os.fsync(stream.fileno())
            os.replace(partial,target)
            directory=os.open(target.parent,os.O_RDONLY)
            try:os.fsync(directory)
            finally:os.close(directory)
            digest=hashlib.sha256()
            with target.open("rb") as stream:
                for block in iter(lambda:stream.read(8*1024**2),b""):digest.update(block)
            retained.append({"path":str(target),"revision":revision,"bytes":target.stat().st_size,"sha256":digest.hexdigest()})
        finally:reader.close()
    (destination/"retained-history.json").write_text(json.dumps({"schema":"zombie-sim/retained-acceptance-history-v1","histories":retained},indent=2)+"\n")


def _validation_code(message):
    lower=message.lower()
    if "unique" in lower or "duplicate" in lower:return "DUPLICATE_ID"
    if "incompatible" in lower or "unknown role" in lower:return "INCOMPATIBLE_ROLE"
    if "episode" in lower or "incubation" in lower:return "INVALID_EPISODE"
    if "capacity" in lower:return "INVENTORY_CAPACITY"
    if "gate mode" in lower:return "INVALID_GATE_STATE"
    if "reference" in lower or "source_agent" in lower:return "INVALID_REFERENCE"
    if "reserved" in lower or "reservation" in lower:return "INVALID_RESERVATION"
    if "rectangle" in lower or "footprint" in lower or "position" in lower or ".x:" in lower or ".y:" in lower:return "INVALID_GEOMETRY"
    if ".type" in lower or "status" in lower:return "INVALID_TYPE_STATUS"
    return "INVALID_DOMAIN"


def create_adapter(*,workdir):
    import os
    adapter=FrameworkTestAdapter(workdir=workdir)
    adapter.retention_directory=os.environ.get("ZOMBIE_ACCEPTANCE_RETAIN_HISTORY")
    return adapter
