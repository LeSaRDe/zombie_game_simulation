"""Canonical agent state and derived profiles (ontology sections 4–7)."""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
from .registry import ROLES, TYPE_ACTIONS

RESOURCES = ("FOOD", "MEDICAL_SUPPLY", "MATERIAL")
TYPE_PROFILES = {
    "Human": {"base_speed": 2.0, "base_sense_r": 40.0, "movement_cost": .10, "rest_rate": 4.0, "base_damage_resistance": 0.0, "max_life": 100, "max_stamina": 100.0, "hunger_rate": .05, "combat_skill": .35, "melee_damage": 16, "medical_skill": .20, "infection_resistance": .20, "carry_capacity": 10},
    "Zombie": {"base_speed": 1.6, "base_sense_r": 35.0, "movement_cost": .08, "rest_rate": 3.0, "base_damage_resistance": 0.0, "max_life": 100, "max_stamina": 100.0, "attack_skill": .40, "virulence": .45, "claw_damage": 14, "bite_damage": 6, "feed_healing": 8, "feed_energy": 12.0},
}


def status(agent):
    if agent["life"] == 0:
        return "DEAD"
    if agent["type"] == "Zombie":
        return "ACTIVE"
    return "INFECTED" if agent.get("infection_episode") else "HEALTHY"


def action_status(agent):
    return "DEAD" if agent["life"] == 0 else "BUSY" if agent.get("active_action") else "IDLE"


def capabilities(agent):
    if agent["life"] == 0:
        return []
    return sorted(set(TYPE_ACTIONS[agent["type"]]) | set(ROLES.get(agent.get("role"), {}).get("actions", [])))


def profile(agent, time=None):
    """Return freshly derived facts; callers cannot mutate canonical profile state."""
    result = deepcopy(TYPE_PROFILES[agent["type"]])
    result.update(agent.get("type_profile", {}))
    role = ROLES.get(agent.get("role"), {})
    result.update({k: v for k,v in role.items() if isinstance(v,(int,float)) and not isinstance(v,bool)})
    result.update(agent.get("role_profile", {}))
    result.update(agent.get("profile", {}))
    result["speed"] = result["base_speed"]
    result["sense_r"] = result["base_sense_r"]
    result["damage_resistance"] = result["base_damage_resistance"]
    result["rally_bonus"] = 0.0
    if agent["type"] == "Human":
        result["infection_resistance_effective"] = result["infection_resistance"]
        if "carry_capacity" in agent:
            result["carry_capacity"] = agent["carry_capacity"]
    effects = agent.get("effects", {})
    for effect in effects.values() if isinstance(effects,dict) else effects:
        if not isinstance(effect,dict):
            continue
        if time is not None:
            now=Fraction(str(time))
            if now < Fraction(str(effect.get("start_at",0))) or (effect.get("end_at") is not None and now >= Fraction(str(effect["end_at"]))):
                continue
        kind = effect.get("kind",effect.get("type", "")).lower()
        value = effect.get("value",effect.get("strength"))
        if kind == "guard" and agent.get("role") == "WARRIOR":
            result["damage_resistance"] = max(result["damage_resistance"],float(value if value is not None else effect.get("resistance",.6)))
        elif kind == "recon" and agent.get("role") == "SCOUT":
            result["sense_r"] = max(result["sense_r"],float(value if value is not None else effect.get("radius",85)))
        elif kind == "prophylaxis" and agent["type"] == "Human":
            result["infection_resistance_effective"] = max(result["infection_resistance_effective"],float(value if value is not None else effect.get("resistance",.8)))
        elif kind in ("rally", "rallied") and agent["type"] == "Zombie":
            result["rally_bonus"] = max(result["rally_bonus"],float(value if value is not None else effect.get("hit_bonus",.1)))
    active = agent.get("active_action")
    if agent.get("role") == "RUNNER" and isinstance(active,dict) and active.get("action",active.get("name")) == "dash":
        result["speed"] *= result.get("dash_multiplier",1.5)
    if agent["life"] == 0:
        result["speed"] = result["sense_r"] = 0.0
    return result


def decision_model_assignment(model_id,version=None,parameters=None,*,agent_type=None):
    """Resolve new assignments to their real implementation version.

    A bare major version is an explicit compatible-family request. Full pinned
    versions must match exactly; old stored assignments are never rewritten.
    """
    from .policies import create_model
    if not isinstance(model_id,str) or not model_id:
        raise ValueError("Decision model ID must be a nonempty string")
    model=create_model(model_id,parameters)
    applicable=getattr(model,"applicable_types",None)
    if applicable is None and callable(getattr(model,"manifest",None)):
        applicable=model.manifest().get("applicable_types")
    if agent_type is not None and (not isinstance(applicable,(list,tuple,set,frozenset)) or agent_type not in applicable):
        error=ValueError(f"Model {model_id} is incompatible with biological type {agent_type}; declared applicability is {applicable!r}")
        error.code="INCOMPATIBLE_MODEL"
        raise error
    actual=str(model.version)
    if version is not None and str(version) not in {actual,actual.split(".",1)[0]}:
        raise ValueError(f"Model {model_id} version {version} unavailable; installed version is {actual}")
    result={"model_id":model_id,"version":actual}
    if parameters is not None:result["parameters"]=deepcopy(parameters)
    if version is not None and str(version)!=actual:result["requested_version"]=str(version)
    return result


def make_agent(identifier, kind="Human", role=None, **overrides):
    agent = {"id": str(identifier), "type": kind, "role": role, "life": 100,
             "stamina": 100.0, "x": 0.0, "y": 0.0, "created_at": "0",
             "infection_episode": None, "cooldowns": {}, "effects": {},
             "active_action": None, "model_assignment": None,
             "profile": {}, "last_state_event_id": "initialization", "revision": 0}
    if kind == "Human":
        agent.update(hunger=20.0,inventory={r:0 for r in RESOURCES},reserved={r:0 for r in RESOURCES},carry_capacity=ROLES.get(role,{}).get("carry_capacity",10),starvation_started_at=None,next_starvation_damage_at=None)
        if role == "DOCTOR":
            agent["inventory"]["MEDICAL_SUPPLY"] = 1
        elif role == "ENGINEER":
            agent["inventory"]["MATERIAL"] = 1
    elif role == "SPITTER":
        agent.update(spit_charges=ROLES[role]["max_spit_charges"],reserved_charges=0,next_charge_at=None)
    agent.update(deepcopy(overrides))
    if "model_assignment" not in overrides:
        agent["model_assignment"]=decision_model_assignment(kind+"DefaultModel",agent_type=kind)
    elif isinstance(agent["model_assignment"],dict) and agent["model_assignment"].get("model_id"):
        assignment=agent["model_assignment"]
        agent["model_assignment"]={**assignment,**decision_model_assignment(assignment["model_id"],assignment.get("version"),assignment.get("parameters"),agent_type=kind)}
    if kind == "Human":
        agent["inventory"] = {r:agent["inventory"].get(r,0) for r in RESOURCES}
        agent["reserved"] = {r:agent["reserved"].get(r,0) for r in RESOURCES}
    return agent
