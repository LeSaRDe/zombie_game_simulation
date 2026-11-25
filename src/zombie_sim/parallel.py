"""Deterministic conflict partitioning and pure process-worker materialization.

Workers receive detached records, never a live store. Effect publication, target
checks, reservations and all commits stay with the authoritative coordinator.
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from fractions import Fraction
import json
import math
import multiprocessing

from .domain import profile, status


def _token(value):
    if isinstance(value,list):return tuple(_token(v) for v in value)
    if isinstance(value,dict):return tuple(sorted((k,_token(v)) for k,v in value.items()))
    return value


def conflict_components(access_entries):
    """Return stable lists of input indices coupled by read/write conflicts.

    Each entry is a mapping with `reads` and `writes` token collections. Tokens
    represent concrete entities or versioned predicates/spatial queries. The
    coordinator must supply the same token for overlapping predicates; this helper
    does not infer geometry from arbitrary names. Read/read access commutes.
    """
    parent=list(range(len(access_entries)))
    def find(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]];i=parent[i]
        return i
    def join(i,j):
        a,b=find(i),find(j)
        if a!=b:parent[max(a,b)]=min(a,b)
    readers={};writers={}
    for i,entry in enumerate(access_entries):
        reads={_token(t) for t in entry.get("reads",())}
        writes={_token(t) for t in entry.get("writes",())}
        for token in reads:
            for previous in writers.get(token,()):join(i,previous)
        for token in writes:
            for previous in readers.get(token,()):join(i,previous)
            for previous in writers.get(token,()):join(i,previous)
        for token in reads:readers.setdefault(token,[]).append(i)
        for token in writes:writers.setdefault(token,[]).append(i)
    groups={}
    for i in range(len(parent)):groups.setdefault(find(i),[]).append(i)
    return sorted(groups.values(),key=lambda group:group[0])


def _time(value):
    if isinstance(value,bool):raise ValueError("Boolean is not a semantic time")
    value=Fraction(str(value))
    if value<0:raise ValueError("Semantic time must be nonnegative")
    return value


def _stamp(value):
    return str(value.numerator) if value.denominator==1 else str(value)


def _path_at(occurrence,at):
    points=occurrence["parameters"]["path"]
    offset=max(Fraction(0),at-_time(occurrence["start_at"]));travelled=0.0
    for left,right in zip(points,points[1:]):
        start,end=_time(left["offset"]),_time(right["offset"])
        if end<=start:raise ValueError("A path segment must have positive elapsed time")
        length=math.hypot(float(right["x"])-float(left["x"]),float(right["y"])-float(left["y"]))
        if offset>=end:
            travelled+=length;continue
        fraction=min(1.0,max(0.0,float((offset-start)/(end-start))))
        return (float(left["x"])+(float(right["x"])-float(left["x"]))*fraction,
                float(left["y"])+(float(right["y"])-float(left["y"]))*fraction),travelled+length*fraction
    return (float(points[-1]["x"]),float(points[-1]["y"])),travelled


def materialize_agent(task):
    """Pure anchor evaluation for one agent at an already scheduled frontier."""
    agent=deepcopy(task["agent"]);at=_time(task["time"])
    previous=_time(agent.get("_evaluated_at",0))
    if at<previous:raise ValueError("Cannot materialize an agent before its anchor")
    occurrence=deepcopy(task.get("occurrence"));episode=deepcopy(task.get("episode"))
    source_revision=agent.get("revision",0)
    p=profile(agent,_stamp(at))
    if at>previous and agent["life"]>0:
        elapsed=float(at-previous)
        if agent["type"]=="Human":
            before_hunger=Fraction(str(agent.get("hunger",20)))
            rate=Fraction(str(p.get("hunger_rate",.05)))
            agent["hunger"]=float(min(Fraction(100),before_hunger+rate*(at-previous)))
            if agent["hunger"]==100 and before_hunger<100 and rate>0:
                agent["starvation_started_at"]=_stamp(previous+(100-before_hunger)/rate)
            if agent["hunger"]==100:
                agent["next_starvation_damage_at"]=agent.get("_starvation_due_at",agent.get("next_starvation_damage_at"))
        if occurrence:
            end=min(at,_time(occurrence["planned_end"]));start=_time(occurrence["start_at"])
            if occurrence["action"]=="rest":
                duration=float(max(Fraction(0),end-max(previous,start)))
                agent["stamina"]=min(100.0,float(agent["stamina"])+float(p.get("rest_rate",4 if agent["type"]=="Human" else 3))*duration)
            elif occurrence["action"] in ("move","dash"):
                coords,travelled=_path_at(occurrence,end)
                used=max(0.0,travelled-float(agent.get("_travelled",0)))
                agent["stamina"]=max(0.0,float(agent["stamina"])-used*float(p.get("movement_cost",.1)))
                agent["x"],agent["y"]=coords;agent["_travelled"]=travelled
        agent["_evaluated_at"]=_stamp(at)
    effective=profile(agent,_stamp(at))
    effective.update(status=status(agent),action_state="DEAD" if agent["life"]==0 else "BUSY" if agent.get("active_action") else "IDLE",
                     current_action=occurrence.get("action") if occurrence else None)
    if agent["type"]=="Human":
        effective["infection_progress"]=min(1.0,max(0.0,float((at-_time(episode["onset_at"]))/Fraction(str(episode["incubation_duration"]))))) if episode else 0.0
    return {"id":str(agent["id"]),"agent":agent,"effective":effective,"time":_stamp(at),"source_revision":source_revision}


def materialize_agents(tasks,workers=1,pool=None):
    """Evaluate frozen independent actors in order, optionally using real processes.

    A caller-supplied executor is reused and remains owned by that caller. Passing
    no executor creates a bounded spawn pool for this batch. Results have no target
    effects and must be validated/published by the coordinator in canonical order.
    """
    if isinstance(workers,bool) or not isinstance(workers,int) or workers<1:
        raise ValueError("workers must be a positive integer")
    tasks=list(tasks)
    if workers==1 or not tasks:
        return [materialize_agent(task) for task in tasks]
    if pool is not None:
        return list(pool.map(materialize_agent,tasks))
    with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context("spawn")) as executor:
        return list(executor.map(materialize_agent,tasks))


PREPARABLE_ACTIONS=frozenset({"eat","first_aid","smash","demolish","repair_barrier"})


def _entity_inputs(entity):
    if entity is None:return None
    keys=("id","type","role","life","stamina","x","y","hunger","inventory","reserved","infection_episode","integrity","max_integrity","mode","footprint")
    return {key:deepcopy(entity.get(key)) for key in keys}


def effect_task(occurrence,actor,target,actor_profile):
    """Capture only concrete inputs to the deterministic effect calculation."""
    action=occurrence["action"]
    if action not in PREPARABLE_ACTIONS:return None
    payload={"action":action,"actor":_entity_inputs(actor),"target":_entity_inputs(target),
             "parameters":deepcopy(occurrence.get("parameters",{})),
             "profile":{key:actor_profile.get(key) for key in ("medical_skill","demolish_damage","repair_amount")}}
    import hashlib
    fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    return {"occurrence":occurrence["id"],"fingerprint":fingerprint,"input":payload}


def compute_effect(task):
    """Compute actual bounded changes; allocate no IDs and perform no mutations."""
    data=task["input"];action=data["action"];actor=data["actor"];target=data["target"];p=data["profile"]
    if action=="eat":
        effect={"hunger":max(0.0,actor["hunger"]-40)}
    elif action=="first_aid":
        healing=min(100-target["life"],10+math.floor(20*p["medical_skill"]+.5))
        effect={"life":target["life"]+healing,"healing":healing}
    elif action in ("smash","demolish"):
        amount=min(target["integrity"],20 if action=="smash" else p["demolish_damage"])
        effect={"integrity":target["integrity"]-amount,"integrity_damage":amount}
    elif action=="repair_barrier":
        amount=min(target["max_integrity"]-target["integrity"],p["repair_amount"])
        effect={"integrity":target["integrity"]+amount,"integrity_restored":amount}
    else:
        raise ValueError(f"Unsupported prepared effect {action}")
    return {"occurrence":task["occurrence"],"fingerprint":task["fingerprint"],"effect":effect}


def completion_access(occurrence):
    """Deliberately conservative effect access declarations.

    Unsupported effects write the shared opaque-effects token, coupling them to
    every candidate in that frontier. All effects read geometry; any barrier
    write therefore couples all simultaneous LOS/range consumers. This leaves
    only proven independent supported components eligible for workers.
    """
    action=occurrence["action"];actor=str(occurrence["actor"]);target=occurrence.get("target")
    reads=[("opaque_effects",),("geometry",),("agent",actor)]
    writes=[("agent",actor)]
    if action not in PREPARABLE_ACTIONS:writes.append(("opaque_effects",))
    if target is not None:
        token=("barrier",str(target)) if action in ("smash","demolish","repair_barrier") else ("agent",str(target))
        reads.append(token);writes.append(token)
    if action in ("smash","demolish","repair_barrier"):writes.append(("geometry",))
    return {"reads":reads,"writes":writes}


def prepare_effect_groups(entries,workers=1,pool=None):
    """Compute singleton independent effects; coupled/unsupported work stays serial.

    Entries contain `access` and optionally a supported `task`. Worker failure
    yields serial fallback rather than partially published effects.
    """
    groups=conflict_components([entry["access"] for entry in entries])
    eligible=[group[0] for group in groups if len(group)==1 and entries[group[0]].get("task") is not None]
    tasks=[entries[i]["task"] for i in eligible]
    stats={"submitted":len(tasks),"prepared":0,"consumed":0,"fallback":0,
           "unsupported":sum(entry.get("task") is None for entry in entries),
           "conflicted":sum(len(group) for group in groups if len(group)>1),
           "worker_batches":int(workers>1 and len(tasks)>1)}
    try:
        if workers>1 and len(tasks)>1:
            if pool is not None:prepared=list(pool.map(compute_effect,tasks))
            else:
                with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context("spawn")) as executor:
                    prepared=list(executor.map(compute_effect,tasks))
        else:prepared=[compute_effect(task) for task in tasks]
    except Exception:
        # No worker proposal has been published. Existing handlers remain the
        # authoritative fallback; do not retry a partially committed action.
        stats["fallback"]+=len(tasks);prepared=[]
    stats["prepared"]=len(prepared)
    return {item["occurrence"]:item for item in prepared},stats


def consume_prepared_effect(simulation,occurrence,actor,actor_profile):
    """Verify the reads immediately after completion validation, before mutation."""
    proposals=getattr(simulation,"_prepared_effects",{})
    proposal=proposals.pop(occurrence["id"],None)
    if proposal is None:return None
    target_id=occurrence.get("target")
    if target_id in simulation.state["agents"]:target=simulation._view_agent(target_id)
    else:target=simulation.state["barriers"].get(target_id)
    current=effect_task(occurrence,actor,target,actor_profile)
    stats=getattr(simulation,"parallel_effect_stats",None)
    if stats is None:
        stats=simulation.parallel_effect_stats={"consumed":0,"fallback":0}
    if current is None or current["fingerprint"]!=proposal["fingerprint"]:
        stats["fallback"]=stats.get("fallback",0)+1
        return None
    stats["consumed"]=stats.get("consumed",0)+1
    return deepcopy(proposal["effect"])
