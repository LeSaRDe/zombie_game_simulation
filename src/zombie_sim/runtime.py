"""Exact runtime continuation, verified checkpoints, branches, and read projections.

No constructor is called during restoration: populations are never resampled and
model memory, occurrence reservations, priorities, clocks, and counters survive.
"""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import hashlib
import heapq
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid

from .domain import action_status, profile, status
from .storage import History, MemoryStore, SQLiteStore, canonical, exact_time, _pack

SCHEMA = "zombie-sim/runtime-v1"
_EPHEMERAL = {"store", "history", "_pool", "_temporary", "_closed", "_spatial_time", "_spatial_cells", "_position_cache",
              "_source_history_path", "_admission_boundary_agents", "_admission_boundary_entities", "_admission_boundary_token"}


def _stamp(value):
    value=exact_time(value)
    return str(value.numerator) if value.denominator==1 else str(value)


def _encode(value):
    if isinstance(value,Fraction):
        return {"$runtime_type":"fraction","numerator":value.numerator,"denominator":value.denominator}
    if isinstance(value,Path):
        return {"$runtime_type":"path","value":str(value)}
    if isinstance(value,set):
        encoded=[_encode(v) for v in value]
        return {"$runtime_type":"set","items":sorted(encoded,key=canonical)}
    if isinstance(value,tuple):
        return {"$runtime_type":"tuple","items":[_encode(v) for v in value]}
    if isinstance(value,list):
        return [_encode(v) for v in value]
    if isinstance(value,dict):
        if not all(isinstance(k,str) for k in value):
            return {"$runtime_type":"mapping","items":[[_encode(k),_encode(v)] for k,v in value.items()]}
        if "$runtime_type" in value:
            return {"$runtime_type":"mapping","items":[[k,_encode(v)] for k,v in value.items()]}
        return {k:_encode(v) for k,v in value.items()}
    if value is None or isinstance(value,(str,bool,int)):
        return value
    if isinstance(value,float) and math.isfinite(value):
        return value
    raise TypeError(f"Runtime state must have an explicit JSON codec; unsupported {type(value).__name__}")


def _decode(value):
    if isinstance(value,list):
        return [_decode(v) for v in value]
    if not isinstance(value,dict):
        return value
    kind=value.get("$runtime_type")
    if kind=="fraction":
        return Fraction(int(value["numerator"]),int(value["denominator"]))
    if kind=="path":
        return Path(value["value"])
    if kind in ("set","tuple"):
        items=[_decode(v) for v in value["items"]]
        return set(items) if kind=="set" else tuple(items)
    if kind=="mapping":
        return {_decode(k):_decode(v) for k,v in value["items"]}
    if kind is not None:
        raise ValueError(f"Unsupported runtime codec {kind!r}")
    return {k:_decode(v) for k,v in value.items()}


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def serialize(sim):
    """Return a detached JSON object for a committed coordinator boundary."""
    if getattr(sim,"_dirty",None):
        raise ValueError("Runtime snapshots require a committed boundary; pending state writes exist")
    if sim.revision!=sim.history.revision:
        raise ValueError("Runtime revision differs from durable history; cannot checkpoint an uncommitted boundary")
    attributes={k:_encode(v) for k,v in vars(sim).items() if k not in _EPHEMERAL and k not in ("occurrences","intents","events","decisions","random_draws") and not k.startswith("_runtime_")}
    payload={"schema":SCHEMA,"attributes":attributes,"history_path":str(Path(sim.history_path).absolute()),
             "history_revision":int(sim.revision),"state_sha256":_digest(sim.state),"attributes_sha256":_digest(attributes),
             "event_history":"ledger"}
    return json.loads(canonical(payload))


def _validated_payload(payload):
    if not isinstance(payload,dict) or payload.get("schema")!=SCHEMA:
        raise ValueError("Unsupported or missing runtime checkpoint schema")
    if _digest(payload["attributes"])!=payload.get("attributes_sha256"):
        raise ValueError("Runtime checkpoint checksum mismatch")
    attributes=_decode(payload["attributes"])
    if _digest(attributes["state"])!=payload.get("state_sha256"):
        raise ValueError("Runtime state checksum mismatch")
    if int(attributes["revision"])!=int(payload["history_revision"]):
        raise ValueError("Checkpoint runtime and ledger revisions disagree")
    if int(attributes["state"].get("revision",0))!=int(attributes["revision"]):
        raise ValueError("Checkpoint state and coordinator revisions disagree")
    if exact_time(attributes["time"])<exact_time(attributes["state"].get("time",0)):
        raise ValueError("Checkpoint clock predates its committed state")
    for queued in attributes.get("queue",[]):
        if len(queued)!=5 or exact_time(queued[0])<exact_time(attributes["time"]):
            raise ValueError("Checkpoint has a malformed or past pending event")
    return attributes


def _copy_history(source,destination,revision,state):
    """Copy a verified prefix to a new database without changing its revisions."""
    source,destination=Path(source),Path(destination)
    if source.resolve()==destination.resolve():
        raise ValueError("History prefix copy requires a different destination")
    if not source.is_file():
        raise FileNotFoundError(f"Checkpoint history is unavailable: {source}; retain the checkpoint's .history.sqlite sidecar")
    if destination.exists() and destination.stat().st_size:
        raise ValueError(f"History destination already exists: {destination}")
    read=History(source,read_only=True)
    try:
        if read.revision<revision:
            raise ValueError("Checkpoint revision is beyond the source history")
        prefix_state=read.state_at(revision=revision)
        if _digest(prefix_state)!=_digest(state):
            raise ValueError("Checkpoint state does not match its source ledger revision")
        destination.parent.mkdir(parents=True,exist_ok=True)
        target=sqlite3.connect(destination)
        try:
            read.connection.backup(target)
            with target:
                target.execute("DELETE FROM participants WHERE sequence IN (SELECT sequence FROM events WHERE revision>?)",(revision,))
                target.execute("DELETE FROM events WHERE revision>?",(revision,))
                target.execute("DELETE FROM commits WHERE revision>?",(revision,))
                tables={row[0] for row in target.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "runtime_commits" in tables:
                    target.execute("DELETE FROM runtime_commits WHERE revision>?",(revision,))
                if "control_commands" in tables:
                    target.execute("DELETE FROM control_commands WHERE revision>? OR revision IS NULL OR status='pending'",(revision,))
                target.execute("DELETE FROM metadata WHERE key IN ('active_control_command','control_state')")
                # Checkpoint paths belong to the source run and cannot be reused.
                target.execute("DELETE FROM checkpoints")
                target.execute("DELETE FROM live_entities")
                target.execute("DELETE FROM live_state")
                target.execute("INSERT INTO live_state VALUES(1,?,?)",(revision,_pack(state)))
            target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            target.close()
    finally:
        read.close()


def from_serialized(SimulationClass,payload,history_path=None,backend=None,workers=None):
    attributes=_validated_payload(payload)
    sim=SimulationClass.__new__(SimulationClass)
    sim.__dict__.update(attributes)
    sim.time=exact_time(sim.time);sim.horizon=exact_time(sim.horizon)
    sim._last_checkpoint=exact_time(sim._last_checkpoint)
    sim._pool=None;sim._closed=False
    sim._temporary=tempfile.TemporaryDirectory(prefix="zombie-sim-restored-") if history_path is None else None
    target=Path(history_path) if history_path is not None else Path(sim._temporary.name)/"history.sqlite"
    source=Path(payload["history_path"])
    sim._source_history_path=str(source.absolute())
    try:
        if not target.exists() or target.stat().st_size==0:
            _copy_history(source,target,sim.revision,sim.state)
        else:
            reader=History(target,read_only=True)
            try:
                if reader.revision!=sim.revision:
                    raise ValueError(f"Continuation ledger is at revision {reader.revision}, checkpoint is at {sim.revision}. Restore to a fresh destination or choose the matching checkpoint; newer durable history is never overwritten.")
                if _digest(reader.state_at())!=payload["state_sha256"]:
                    raise ValueError("Continuation ledger state differs from checkpoint")
            finally:
                reader.close()
        sim.backend=backend or sim.backend
        if sim.backend not in ("memory","sqlite"):
            raise ValueError("backend must be memory or sqlite")
        sim.workers=int(workers if workers is not None else sim.workers)
        if sim.workers<1:
            raise ValueError("workers must be positive")
        sim.history_path=str(target.absolute())
        if sim.backend=="sqlite":
            sim.store=SQLiteStore(target)
            sim.history=sim.store.history
        else:
            sim.history=History(target)
            sim.store=MemoryStore(initial=sim.state,history=sim.history)
        sim.occurrences=sim.state.setdefault("occurrences",{})
        sim.intents=sim.state.setdefault("intents",{})
        if any(name not in attributes for name in ("events","decisions","random_draws")):
            for name,records in _recorded_histories(sim.history,sim.revision).items():
                if name not in attributes:
                    setattr(sim,name,records)
        sim._dirty=set(sim._dirty)
        sim._decision_due=set(sim._decision_due)
        sim.queue=[tuple(row) for row in sim.queue]
        heapq.heapify(sim.queue)
        if sim.store.version!=sim.revision:
            raise ValueError("Restored store revision does not match coordinator")
        if sim.history.runtime_at() is None:
            initialize_history(sim)
        else:
            mark_committed(sim)
        return sim
    except BaseException:
        if hasattr(sim,"store"):
            sim.store.close()
        if sim._temporary:
            sim._temporary.cleanup()
        raise


def _recorded_histories(history,revision):
    records=[{key:value for key,value in event.items() if key not in ("ledger_sequence","ledger_revision")}
             for event in history.events(end=revision)]
    return {"events":records,
            "decisions":[{key:value for key,value in event.items() if key not in ("kind","revision","causes")}
                         for event in records if event.get("kind")=="decision"],
            "random_draws":[{key:value for key,value in event.items() if key not in ("id","kind","revision","causes")}
                            for event in records if event.get("kind")=="random_draw"]}


def restore_revision(SimulationClass,history_path,revision=None,output_history_path=None,backend=None,workers=None):
    """Restore a committed runtime journal boundary without initialization.

    The default is an independent verified prefix. A caller can continue the
    latest source ledger by explicitly passing it as output_history_path;
    restoring an earlier revision never truncates an existing destination.
    """
    source=Path(history_path).absolute()
    history=History(source,read_only=True)
    try:
        selected=history.revision if revision is None else revision
        if isinstance(selected,bool) or not isinstance(selected,int) or not 0<=selected<=history.revision:
            raise ValueError(f"Runtime revision must be an integer between 0 and {history.revision}")
        kernel=history.runtime_at(selected)
        if not kernel or kernel.get("schema")!="zombie-sim/runtime-journal-v1":
            raise ValueError("This ledger has no complete runtime journal at the selected revision; restore its matching explicit checkpoint instead")
        attributes=_decode(kernel["attributes"])
        if int(attributes.get("revision",-1))!=selected:
            raise ValueError("Runtime journal revision does not match the requested state revision")
        state=history.state_at(revision=selected)
        if int(state.get("revision",-1))!=selected:
            raise ValueError("World journal revision does not match the selected runtime boundary")
        queue=[_decode(value) for value in kernel.get("queue",{}).values()]
        serials=[entry[3] for entry in queue]
        if len(serials)!=len(set(serials)):
            raise ValueError("Runtime journal contains duplicate pending event serials")
        attributes.update(state=state,queue=queue,memories={key:_decode(value) for key,value in kernel.get("memories",{}).items()},
                          _dirty=set(),_effects_buffer=[],_deferred_events=[],_batching=False,
                          _decision_due={(str(entry[4]["agent"]),_stamp(entry[0])) for entry in queue if entry[4].get("kind")=="decision"})
        encoded={key:_encode(value) for key,value in attributes.items()}
        payload={"schema":SCHEMA,"attributes":encoded,"history_path":str(source),"history_revision":selected,
                 "state_sha256":_digest(state),"attributes_sha256":_digest(encoded),"event_history":"ledger"}
    finally:
        history.close()
    sim=from_serialized(SimulationClass,payload,history_path=output_history_path,backend=backend,workers=workers)
    if not any(agent["life"]>0 for agent in sim.state["agents"].values()):
        sim.run_status,sim.termination_reason="COMPLETED","NO_LIVING_AGENTS"
    elif sim.time>=sim.horizon and not any(exact_time(entry[0])<=sim.horizon for entry in sim.queue):
        sim.run_status,sim.termination_reason="COMPLETED","HORIZON"
    else:
        sim.run_status,sim.termination_reason="PAUSED",None
    return sim


def checkpoint(sim,path=None):
    """Durably save runtime and a portable history prefix; return the JSON path."""
    if path is None:
        path=Path(sim.history_path).parent/"checkpoints"/f"revision-{sim.revision}.json"
    path=Path(path).absolute();path.parent.mkdir(parents=True,exist_ok=True)
    sim._last_checkpoint=exact_time(sim.time);sim._since_checkpoint=0
    payload=serialize(sim)
    sidecar=path.with_suffix(".history.sqlite")
    if sidecar.resolve()==Path(sim.history_path).resolve():
        raise ValueError("Checkpoint sidecar would replace the live ledger; choose another checkpoint path")
    temporary=sidecar.with_name(sidecar.name+"."+uuid.uuid4().hex+".partial")
    _copy_history(sim.history_path,temporary,sim.revision,sim.state)
    with temporary.open("rb") as stream:
        os.fsync(stream.fileno())
    os.replace(temporary,sidecar)
    payload["history_path"]=str(sidecar)
    payload["history_sha256"]=hashlib.sha256(sidecar.read_bytes()).hexdigest()
    # History.save_checkpoint provides atomic replacement, file/directory fsync,
    # and a verified envelope. The runtime digest separately checks typed values.
    return sim.history.save_checkpoint(payload,path)


def restore(SimulationClass,path,history_path=None,backend=None,workers=None):
    path=Path(path)
    envelope=json.loads(path.read_text())
    if "document" not in envelope or _digest(envelope["document"])!=envelope.get("checksum"):
        raise ValueError("Checkpoint envelope checksum mismatch")
    payload=envelope["document"]["payload"]
    # Sidecars are portable together with the JSON even after directory moves.
    sidecar=Path(payload["history_path"])
    moved=path.with_suffix(".history.sqlite")
    if not sidecar.is_file() and moved.is_file():
        sidecar=moved;payload["history_path"]=str(sidecar)
    if payload.get("history_sha256") and hashlib.sha256(sidecar.read_bytes()).hexdigest()!=payload["history_sha256"]:
        raise ValueError("Checkpoint history sidecar checksum mismatch")
    return from_serialized(SimulationClass,payload,history_path=history_path,backend=backend,workers=workers)


def branch(sim,output,seed=None,run_id=None):
    """Create a separately stored continuation with immutable parent provenance."""
    output=Path(output)
    if output.exists():
        raise ValueError("Branch destination must be new; existing runs are never replaced")
    output.mkdir(parents=True)
    payload=serialize(sim)
    child=from_serialized(type(sim),payload,history_path=output/"run.sqlite")
    parent={"run_id":sim.state.get("run_id"),"history_path":str(Path(getattr(sim,"_source_history_path",sim.history_path)).absolute()),
            "time":_stamp(sim.time),"revision":sim.revision,"state_sha256":payload["state_sha256"],
            "seed":sim.seed,"counterfactual_seed":sim.seed if seed is None else int(seed),
            "pending_priorities":"inherited from parent; subsequent random draws use the child's seed"}
    if seed is not None:
        if isinstance(seed,bool) or not isinstance(seed,int) or seed<0:
            child.store.close()
            raise ValueError("Branch seed must be a nonnegative integer")
        child.seed=int(seed);child.config["seed"]=int(seed)
        from .config import resolve_config
        child.config=resolve_config(child.config)
        child.state["scenario_fingerprint"]=child.config["fingerprint"]
    child.state["run_id"]=run_id or uuid.uuid4().hex
    child.state["lineage"]=parent
    child.state["time"]=_stamp(child.time)
    child._active_control_command=None
    # The lineage is itself an explicit atomic committed intervention. Preserve
    # all parent revisions and schedule values before this new child boundary.
    patch=[["set",["run_id"],child.state["run_id"]],["set",["lineage"],parent],["set",["time"],_stamp(child.time)],
           ["set",["scenario_fingerprint"],child.state.get("scenario_fingerprint")],["set",["revision"],child.revision+1]]
    event={"id":child._id("event"),"kind":"branch_created","time":_stamp(child.time),"revision":child.revision+1,"parent":parent}
    child.run_status="PAUSED";child.termination_reason=None
    runtime_delta,command_result=capture_delta(child,child.revision+1,[event])
    child.store.commit_delta(patch,expected_version=child.revision,records=[event],
                             runtime_delta=runtime_delta,command_result=command_result)
    child.events.append(event)
    child.revision+=1;child.state["revision"]=child.revision
    child._since_checkpoint+=1
    mark_committed(child)
    child.history.set_metadata("lineage",parent)
    child._source_history_path=child.history_path
    (output/"manifest.json").write_text(canonical({"run_id":child.state["run_id"],"parent":parent,"config":child.config,"status":"paused"}))
    return child


def close(sim):
    if getattr(sim,"_closed",False):
        return
    if getattr(sim,"_pool",None) is not None:
        sim._pool.shutdown(wait=True,cancel_futures=True)
        sim._pool=None
    if getattr(sim,"store",None) is not None:
        sim.store.close()
    if getattr(sim,"_temporary",None) is not None:
        sim._temporary.cleanup()
    sim._closed=True


# The runtime journal is deliberately separate from the researcher world. It
# records only continuation state, with queue mutations supplied by the engine.
JOURNAL_SCHEMA = "zombie-sim/runtime-journal-v1"
_JOURNAL_EXCLUDED = {"state", "events", "decisions", "random_draws", "queue", "memories", "occurrences", "intents",
                     "_decision_due", "_dirty", "_effects_buffer", "_deferred_events", "config"}


def _journal_attributes(sim, *, include_config=False):
    result = {key: _encode(value) for key, value in vars(sim).items()
              if key not in _EPHEMERAL and key not in _JOURNAL_EXCLUDED and not key.startswith("_runtime")}
    if include_config:
        result["config"] = _encode(sim.config)
    return result


def initialize_history(sim):
    document = {"schema": JOURNAL_SCHEMA, "attributes": _journal_attributes(sim, include_config=True),
                "queue": {str(row[3]): _encode(row) for row in sim.queue},
                "memories": {str(key): _encode(value) for key, value in sim.memories.items()}}
    sim.history.initialize_runtime(document, revision=sim.revision)
    mark_committed(sim)


def capture_delta(sim, next_revision, records):
    """Prepare continuation changes for the very same world commit transaction."""
    attributes = _journal_attributes(sim, include_config=getattr(sim, "_runtime_config_marker", None) != id(sim.config))
    attributes["revision"] = int(next_revision)
    attributes["time"] = _encode(sim.time)
    attributes["_batching"] = False
    attributes["_since_checkpoint"] = int(sim._since_checkpoint) + 1
    patch = [["set", ["attributes", key], value] for key, value in attributes.items()]
    patch.extend(deepcopy(getattr(sim, "_runtime_queue_delta", [])))
    memory_ids = {str(key) for collection, key in sim._dirty if collection == "agents"}
    memory_ids.update(str(record["actor"]) for record in records if record.get("kind") == "decision" and record.get("actor") is not None)
    for key in sorted(memory_ids):
        patch.append(["set", ["memories", key], _encode(sim.memories[key])] if key in sim.memories else ["remove", ["memories", key]])
    command_result = None
    command = getattr(sim, "_active_control_command", None)
    if command:
        operation = command["operation"]
        kinds = {record.get("kind") for record in records}
        completed = operation == "step" or (operation == "intervene" and "intervention_scheduled" in kinds)
        if operation in {"advance", "step_timestamp"}:
            target = min(exact_time(command["target"]), sim.horizon)
            completed = ("clock_advanced" in kinds and sim.time >= target) or not any(a["life"] > 0 for a in sim.state["agents"].values())
        if completed:
            control = deepcopy(command["desired_control"])
            if (not any(a["life"] > 0 for a in sim.state["agents"].values())
                    or (sim.time >= sim.horizon and (not sim.queue or sim.queue[0][0] > sim.horizon))):
                control["status"] = "completed"
            command_result = {"command_id": command["id"], "run_id": sim.state.get("run_id"), "status": "applied",
                              "time": _stamp(sim.time), "revision": str(next_revision), "generation": control["generation"],
                              "run_status": control["status"], "pacing": control["pacing"], "control": control}
            patch.append(["set", ["attributes", "_active_control_command"], None])
    sim._runtime_command_result = command_result
    return patch, command_result


def mark_committed(sim):
    sim._runtime_queue_delta = []
    sim._runtime_config_marker = id(sim.config)
    if getattr(sim, "_runtime_command_result", None) is not None:
        sim._active_control_command = None
    sim._runtime_command_result = None


def _path_position(occurrence,time):
    points=occurrence["parameters"]["path"]
    if not points:
        raise ValueError("Recorded motion has an empty path")
    elapsed=max(Fraction(0),time-exact_time(occurrence["start_at"]))
    travelled=0.0
    for left,right in zip(points,points[1:]):
        t0,t1=exact_time(left["offset"]),exact_time(right["offset"])
        length=math.hypot(float(right["x"])-float(left["x"]),float(right["y"])-float(left["y"]))
        if elapsed>=t1:
            travelled+=length;continue
        fraction=max(0.,min(1.,float((elapsed-t0)/(t1-t0))))
        return (float(left["x"])+(float(right["x"])-float(left["x"]))*fraction,float(left["y"])+(float(right["y"])-float(left["y"]))*fraction,travelled+length*fraction)
    return float(points[-1]["x"]),float(points[-1]["y"]),travelled


def materialize_snapshot(state,time=None):
    """Evaluate continuous anchors on a detached view, without executing events.

    Callers choose the last causal boundary at/before the requested time. Passing
    a time beyond a known unresolved action or biological deadline is an error,
    because that would require event processing rather than interpolation.
    """
    view=deepcopy(state)
    if not view:
        return view
    at=exact_time(view.get("time",0) if time is None else time)
    if at<exact_time(view.get("time",0)):
        raise ValueError("Projection time predates its source state; select an earlier history boundary")
    occurrences=view.get("occurrences",{})
    for agent in view.get("agents",{}).values():
        previous=exact_time(agent.get("_evaluated_at",view.get("time",0)))
        active=agent.get("active_action")
        occurrence=active if isinstance(active,dict) else occurrences.get(active)
        alive=agent["life"]>0
        if alive:
            if occurrence and at>exact_time(occurrence["planned_end"]):
                raise ValueError("Projection crosses an unresolved action completion; select the next committed state")
            episode=view.get("episodes",{}).get(agent.get("infection_episode"))
            if episode and at>exact_time(episode["conversion_due_at"]):
                raise ValueError("Projection crosses an unresolved conversion deadline")
            for deadline in (agent.get("_starvation_due_at",agent.get("next_starvation_damage_at")),agent.get("next_charge_at")):
                if deadline is not None and at>exact_time(deadline):
                    raise ValueError("Projection crosses an unresolved biological deadline")
            properties=profile(agent,_stamp(at))
            if at>previous:
                elapsed=float(at-previous)
                if agent["type"]=="Human":
                    before_hunger=Fraction(str(agent.get("hunger",20)))
                    rate=Fraction(str(properties.get("hunger_rate",.05)))
                    agent["hunger"]=float(min(Fraction(100),before_hunger+rate*(at-previous)))
                    if agent["hunger"]==100 and before_hunger<100 and rate>0:
                        agent["starvation_started_at"]=_stamp(previous+(100-before_hunger)/rate)
                    if agent["hunger"]==100:
                        agent["next_starvation_damage_at"]=agent.get("_starvation_due_at",agent.get("next_starvation_damage_at"))
                if occurrence:
                    end=min(at,exact_time(occurrence["planned_end"]))
                    start=exact_time(occurrence["start_at"])
                    if occurrence["action"]=="rest":
                        agent["stamina"]=min(100.,float(agent["stamina"])+properties["rest_rate"]*float(max(Fraction(0),end-max(previous,start))))
                    elif occurrence["action"] in ("move","dash"):
                        x,y,travelled=_path_position(occurrence,end)
                        distance=max(0.,travelled-float(agent.get("_travelled",0)))
                        agent["x"],agent["y"]=x,y
                        agent["stamina"]=max(0.,float(agent["stamina"])-distance*properties["movement_cost"])
                        agent["_travelled"]=travelled
                agent["_evaluated_at"]=_stamp(at)
        properties=profile(agent,_stamp(at))
        if alive and occurrence and occurrence["action"]=="dash":
            properties["speed"]=properties["base_speed"]*properties.get("dash_multiplier",1.5)
        agent.update(properties)
        agent["status"]=status(agent);agent["action_state"]=action_status(agent)
        if agent["type"]=="Human":
            episode=view.get("episodes",{}).get(agent.get("infection_episode"))
            agent["infection_progress"]=float(max(Fraction(0),min(Fraction(1),(at-exact_time(episode["onset_at"]))/exact_time(episode["incubation_duration"])))) if episode else 0.
    view["time"]=_stamp(at)
    return view
