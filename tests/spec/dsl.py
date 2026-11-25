"""Small constructors for test inputs and independent expected observations.

All numbers representing real quantities are decimal strings at the adapter boundary.
These helpers arrange test data; they do not execute or predict simulation transitions.
"""
from copy import deepcopy


def agent(id="h", type="Human", role=None, x="10", y="10", **overrides):
    value = {"id": id, "type": type, "role": role, "x": str(x), "y": str(y),
             "life": 100, "stamina": "100"}
    if type == "Human":
        value.update(hunger="20", inventory={"FOOD": 0, "MEDICAL_SUPPLY": 0, "MATERIAL": 0})
    value.update(overrides)
    return value


def world(*agents, **overrides):
    value = {"length": "100", "width": "100", "agents": list(agents),
             "barriers": [], "stockpiles": [], "remains": []}
    value.update(overrides)
    return value


def intent(id, actor, action, target=None, **parameters):
    value = {"id": id, "actor": actor, "action": action, "parameters": parameters}
    if target is not None:
        value["target"] = target
    return value


def submit(id, actor, action, target=None, **parameters):
    return {"op": "submit", **intent(id, actor, action, target, **parameters)}


def advance(to):
    return {"op": "advance", "to": str(to)}


def snapshot(label="end"):
    return {"op": "snapshot", "label": label}


def check(path, value=None, op="eq", **kwargs):
    return {"path": path, "op": op, "value": value, **kwargs}


def case(id, requirements, setup, steps, checks, *, actions=(), source=(), draws=(), config=None,
         tier="core", description="", kind="simulation", decisions=()):
    return {"id": id, "requirements": list(requirements), "actions": list(actions),
            "source": list(source), "tier": tier, "description": description,
            "decisions": list(decisions),
            "request": {"kind": kind, "setup": deepcopy(setup), "steps": deepcopy(steps),
                        "draws": deepcopy(list(draws)),
                        "config": {"seed": 20261106, "backend": "memory", "workers": 1,
                                   "decision_mode": "scripted", **(config or {})}},
            "checks": deepcopy(checks)}
