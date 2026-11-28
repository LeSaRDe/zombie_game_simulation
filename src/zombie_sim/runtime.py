"""Exact runtime continuation, verified checkpoints, branches, and read projections.

Restoration uses an explicit reconstruction constructor: populations are never resampled and
model memory, occurrence reservations, priorities, clocks, and counters survive.
"""
from __future__ import annotations
from copy import deepcopy
from collections.abc import Mapping
from fractions import Fraction
import hashlib
import math
from pathlib import Path

from .domain import action_status, profile, status
from .storage import canonical, exact_time

SCHEMA = "zombie-sim/runtime-v2"
_EPHEMERAL = {"store", "history", "_pool", "_temporary", "_closed", "_spatial_time", "_spatial_cells", "_position_cache",
              "_source_history_path", "_admission_boundary_agents", "_admission_boundary_entities", "_admission_boundary_token"}


class ModelStateUnavailable(ValueError):
    code="MODEL_STATE_UNAVAILABLE"


def _memory_encode(sim,identifier,value):
    try:return _encode(value)
    except TypeError:
        from .policies import create_model
        model_id=sim.state["agents"][identifier]["model_assignment"]["model_id"]
        if create_model(model_id).manifest().get("restartable",True):raise
        return {"$runtime_type":"unavailable_model_memory","model_id":model_id,
                "reason":"Model declares no exact memory codec"}


def _contains_unavailable(value):
    if isinstance(value,Mapping):
        return value.get("$runtime_type")=="unavailable_model_memory" or any(_contains_unavailable(v) for v in value.values())
    if isinstance(value,(list,tuple)):return any(_contains_unavailable(v) for v in value)
    return False


def assert_exact_restart(payload):
    if _contains_unavailable(payload.get("attributes",{}).get("memories",{})):
        raise ModelStateUnavailable("Model memory has no exact restart codec; state and history replay remain available")


def _stamp(value):
    value=exact_time(value)
    return str(value.numerator) if value.denominator==1 else str(value)


def _encode(value):
    from .domain_model import ScheduledTask
    if isinstance(value, ScheduledTask):
        return _encode(value.as_legacy_tuple())
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
    if isinstance(value,Mapping):
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
    if kind=="unavailable_model_memory":return value
    if kind is not None:
        raise ValueError(f"Unsupported runtime codec {kind!r}")
    return {k:_decode(v) for k,v in value.items()}


def _digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _file_digest(path):
    """Hash a history sidecar without allocating memory proportional to its size."""
    checksum=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024**2),b""):
            checksum.update(block)
    return checksum.hexdigest()


def serialize(sim):
    'Return a detached JSON object for a committed coordinator boundary.'
    return sim.services.runtime.serialize(sim)


def _validated_payload(payload):
    if not isinstance(payload,dict) or payload.get("schema") not in {SCHEMA, "zombie-sim/runtime-v1"}:
        raise ValueError("Unsupported or missing runtime checkpoint schema")
    if _digest(payload["attributes"])!=payload.get("attributes_sha256"):
        raise ValueError("Runtime checkpoint checksum mismatch")
    assert_exact_restart(payload)
    attributes=_decode(payload["attributes"])
    from .state_management.runtime_state import RuntimeState
    RuntimeState.from_attributes(attributes)
    assert_exact_restart({"attributes":attributes})
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
    """Compatibility entry point for the persistence-owned prefix exporter."""
    from .persistence.checkpoint import copy_history_prefix
    return copy_history_prefix(source,destination,revision,state)


def from_serialized(SimulationClass, payload, history_path=None, backend=None, workers=None, service_factory=None,persistence_factory=None,rule_set=None):
    from .core import SimulationServiceFactory
    return (service_factory or SimulationServiceFactory()).create("runtime", None).from_serialized(SimulationClass, payload, history_path, backend, workers, service_factory=service_factory,persistence_factory=persistence_factory,rule_set=rule_set)


def _recorded_histories(history,revision):
    from .history_sequence import LedgerRecords
    # Continuation ledgers have already been verified/truncated to this prefix.
    if history.revision!=revision:raise ValueError("History view requires the selected continuation prefix")
    return {"events":LedgerRecords(history),"decisions":LedgerRecords(history,"decision"),
            "random_draws":LedgerRecords(history,"random_draw")}


def restore_revision(SimulationClass, history_path, revision=None, output_history_path=None, backend=None, workers=None, service_factory=None,persistence_factory=None,rule_set=None):
    'Restore a committed runtime journal boundary without initialization.\n\nThe default is an independent verified prefix. A caller can continue the\nlatest source ledger by explicitly passing it as output_history_path;\nrestoring an earlier revision never truncates an existing destination.'
    from .core import SimulationServiceFactory
    return (service_factory or SimulationServiceFactory()).create("runtime", None).restore_revision(SimulationClass, history_path, revision, output_history_path, backend, workers, service_factory=service_factory,persistence_factory=persistence_factory,rule_set=rule_set)


def checkpoint(sim, path=None):
    'Durably save runtime and a portable history prefix; return the JSON path.'
    return sim.services.runtime.checkpoint(sim, path)


def restore(SimulationClass, path, history_path=None, backend=None, workers=None, service_factory=None,persistence_factory=None,rule_set=None):
    from .core import SimulationServiceFactory
    return (service_factory or SimulationServiceFactory()).create("runtime", None).restore(SimulationClass, path, history_path, backend, workers, service_factory=service_factory,persistence_factory=persistence_factory,rule_set=rule_set)


def branch(sim, output, seed=None, run_id=None):
    'Create a separately stored continuation with immutable parent provenance.'
    return sim.services.runtime.branch(sim, output, seed, run_id)


def close(sim):
    return sim.services.runtime.close(sim)


# The runtime journal is deliberately separate from the researcher world. It
# records only continuation state, with queue mutations supplied by the engine.
JOURNAL_SCHEMA = "zombie-sim/runtime-journal-v2"
_JOURNAL_EXCLUDED = {"state", "events", "decisions", "random_draws", "queue", "memories", "occurrences", "intents",
                     "_decision_due", "_dirty", "_effects_buffer", "_deferred_events", "config"}


def _journal_attributes(sim, *, include_config=False):
    result = {key: _encode(value) for key,value in sim._runtime_state.attributes(detach=False).items()
              if key not in _JOURNAL_EXCLUDED}
    if include_config:
        result['config'] = _encode(sim.config)
    return result


def initialize_history(sim):
    return sim.services.runtime.initialize_history(sim)


def capture_delta(sim, next_revision, records):
    'Prepare continuation changes for the very same world commit transaction.'
    return sim.services.runtime.capture_delta(sim, next_revision, records)


def mark_committed(sim):
    return sim.services.runtime.mark_committed(sim)


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
        agent["current_action"]=occurrence.get("action") if occurrence else None
        if agent["type"]=="Human":
            episode=view.get("episodes",{}).get(agent.get("infection_episode"))
            agent["infection_progress"]=float(max(Fraction(0),min(Fraction(1),(at-exact_time(episode["onset_at"]))/exact_time(episode["incubation_duration"])))) if episode else 0.
    view["time"]=_stamp(at)
    return view
