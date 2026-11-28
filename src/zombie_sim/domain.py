"""Canonical agent state and derived profiles (ontology sections 4–7)."""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache
from .registry import ROLES, TYPE_ACTIONS
from .domain_model import Agent, AgentState, RoleRegistry, TimedEffect
from .domain_model.profiles import ProfileValues, ProfileResolver, HUMAN_PROFILE, ZOMBIE_PROFILE

RESOURCES = ("FOOD", "MEDICAL_SUPPLY", "MATERIAL")
TYPE_PROFILES = {"Human": HUMAN_PROFILE.to_record(), "Zombie": ZOMBIE_PROFILE.to_record()}


def status(agent):
    state = agent.current_state if isinstance(agent, Agent) else agent
    if isinstance(state, AgentState):
        return state.status
    return AgentState.classify(state.get("type"), state["life"], state.get("infection_episode"))


def action_status(agent):
    state = agent.current_state if isinstance(agent, Agent) else agent
    if isinstance(state, AgentState):
        return state.action_status
    return AgentState.classify_action(state["life"], state.get("active_action"))


def capabilities(agent):
    state = agent.current_state if isinstance(agent, Agent) else agent
    if isinstance(state, AgentState):
        return list(state.capabilities)
    if state["life"] == 0:
        return []
    registry = RoleRegistry.default()
    role = registry.get(state.get("role"))
    return sorted(set(registry.type_capabilities(state["type"])) | set(role.actions if role else ()))


@lru_cache(maxsize=2048)
def _typed_profile_values(items):
    return ProfileValues.from_record({key: float.fromhex(value) if kind is float else value
                                      for key, kind, value in items})


def _profile_source(record):
    return _typed_profile_values(tuple((key, type(value), value.hex() if type(value) is float else value)
                                       for key, value in record.items()))


def profile(agent, time=None):
    """Compatibility record boundary around the typed domain profile resolver."""
    state = agent.current_state if isinstance(agent, Agent) else agent
    if isinstance(state, AgentState):
        return state.effective_profile(time).to_record()
    effects = state.get("effects", {})
    typed_effects = tuple(TimedEffect.from_record(effect) for effect in (effects.values() if isinstance(effects, dict) else effects) if isinstance(effect, dict))
    active = state.get("active_action")
    action = active.get("action", active.get("name")) if isinstance(active, dict) else None
    return ProfileResolver.resolve(state["type"], state["life"], RoleRegistry.default().get(state.get("role")),
        type_profile=_profile_source(state.get("type_profile", {})),
        role_profile=_profile_source(state.get("role_profile", {})),
        individual_profile=_profile_source(state.get("profile", {})),
        carry_capacity=state.get("carry_capacity"), effects=typed_effects, at=time,
        current_action=action).to_record()


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


class AgentFactory:
    """Create canonical agent records from a validated catalog and model resolver.

    Identity, biology, role and controller assignment remain separate fields.
    A custom assignment resolver can be supplied without changing agent schema.
    """

    def __init__(self, catalog=None, assignment_resolver=None):
        from .registry import DEFAULT_CATALOG
        self.catalog = DEFAULT_CATALOG if catalog is None else catalog
        self.roles = RoleRegistry.from_catalog(self.catalog)
        self.assignment_resolver = assignment_resolver or decision_model_assignment

    def create(self, identifier, kind="Human", role=None, **overrides):
        agent = {"id": str(identifier), "type": kind, "role": role, "life": 100,
                 "stamina": 100.0, "x": 0.0, "y": 0.0, "created_at": "0",
                 "infection_episode": None, "cooldowns": {}, "effects": {},
                 "active_action": None, "model_assignment": None,
                 "profile": {}, "last_state_event_id": "initialization", "revision": 0}
        if kind == "Human":
            agent.update(hunger=20.0,inventory={r:0 for r in RESOURCES},reserved={r:0 for r in RESOURCES},carry_capacity=self.catalog.roles.get(role,{}).get("carry_capacity",10),starvation_started_at=None,next_starvation_damage_at=None)
            if role == "DOCTOR":
                agent["inventory"]["MEDICAL_SUPPLY"] = 1
            elif role == "ENGINEER":
                agent["inventory"]["MATERIAL"] = 1
        elif role == "SPITTER":
            agent.update(spit_charges=self.catalog.roles[role]["max_spit_charges"],reserved_charges=0,next_charge_at=None)
        agent.update(deepcopy(overrides))
        if "model_assignment" not in overrides:
            agent["model_assignment"]=self.assignment_resolver(kind+"DefaultModel",agent_type=kind)
        elif isinstance(agent["model_assignment"],dict) and agent["model_assignment"].get("model_id"):
            assignment=agent["model_assignment"]
            agent["model_assignment"]={**assignment,**self.assignment_resolver(assignment["model_id"],assignment.get("version"),assignment.get("parameters"),agent_type=kind)}
        if kind == "Human":
            agent["inventory"] = {r:agent["inventory"].get(r,0) for r in RESOURCES}
            agent["reserved"] = {r:agent["reserved"].get(r,0) for r in RESOURCES}
        # Scenario seeds are consumed by initial_state before an agent enters
        # the world. They are not durable biological-state properties.
        initialization = {key: agent.pop(key) for key in ("initial_infection",) if key in agent}
        return {**AgentState.from_record(agent, roles=self.roles, trusted=True).to_record(), **initialization}

    def create_agent(self, identifier, run_id, kind="Human", role=None, **overrides):
        """Create a run-scoped typed entity; ``create`` retains the record API."""
        return Agent.from_record(self.create(identifier, kind, role, **overrides), run_id, roles=self.roles)


DEFAULT_AGENT_FACTORY = AgentFactory()


def make_agent(identifier, kind="Human", role=None, **overrides):
    return DEFAULT_AGENT_FACTORY.create(identifier, kind, role, **overrides)
