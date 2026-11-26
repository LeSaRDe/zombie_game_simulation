"""Validate and import explicit reachable-state scenarios.

This is the production counterpart of checkpoint-like scenario authoring. It
accepts live effects, prior deaths and dated infection episodes while retaining
the ordinary geometry/configuration validator and ontology state invariants.
It never executes a transition to arrange a desired test result.
"""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import math

from .config import ConfigError, _validate_profile
from .domain import RESOURCES, make_agent, profile, status
from .geometry import point_blocked
from .registry import ROLES


class StateValidationError(ConfigError):
    def __init__(self,code,path,message):
        self.code,self.path=code,path
        super().__init__(f"{path}: {message}")


def _fail(code,path,message):raise StateValidationError(code,path,message)


def _numeric(value,path,minimum=0,maximum=None,integer=False,code="INVALID_DOMAIN"):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        _fail(code,path,"expected a finite number")
    if integer and type(value) is not int:_fail(code,path,"expected an integer")
    if value<minimum or maximum is not None and value>maximum:_fail(code,path,"outside the allowed domain")
    return value


def _time(value,path,positive=False,code="INVALID_DOMAIN"):
    try:
        if isinstance(value,bool):raise ValueError()
        result=Fraction(str(value))
        if result<0 or positive and result<=0:raise ValueError()
        return result
    except (ValueError,TypeError,ZeroDivisionError):_fail(code,path,"expected a finite positive time" if positive else "expected a finite nonnegative time")


def _stocks(stock,reserved,path):
    if not isinstance(stock,dict) or not isinstance(reserved,dict):_fail("INVALID_DOMAIN",path,"stock and reservations must be mappings")
    if set(stock)-set(RESOURCES) or set(reserved)-set(RESOURCES):_fail("INVALID_DOMAIN",path,"unknown portable resource")
    total={r:stock.get(r,0) for r in RESOURCES};held={r:reserved.get(r,0) for r in RESOURCES}
    for resource in RESOURCES:
        _numeric(total[resource],path+"."+resource,integer=True)
        _numeric(held[resource],path+".reserved."+resource,maximum=total[resource],integer=True,code="INVALID_RESERVATION")
    return total,held


def initialize_explicit_world(config):
    if "agents" not in config:_fail("INVALID_REFERENCE","state_import","explicit agents are required")
    now=_time(config.get("time",0),"time")
    agents={};episodes={};provided=config.get("episodes",{})
    for item in provided.values() if isinstance(provided,dict) else provided:
        item=deepcopy(item);identifier=str(item["id"])
        if identifier in episodes:_fail("DUPLICATE_ID","episodes.id","duplicate episode identity")
        if "agent" in item:item["agent_id"]=str(item.pop("agent"))
        episodes[identifier]=item
    for original in config["agents"]:
        raw=deepcopy(original);identifier=str(raw.pop("id"));kind=raw.pop("type","Human");role=raw.pop("role",None)
        path="agents."+identifier
        if identifier in agents:_fail("DUPLICATE_ID",path,"duplicate agent identity")
        if kind not in ("Human","Zombie"):_fail("INVALID_TYPE_STATUS",path+".type","unknown biological type")
        if role is not None and (role not in ROLES or ROLES[role]["type"]!=kind):_fail("INCOMPATIBLE_ROLE",path+".role","role does not match biological type")
        life=_numeric(raw.get("life",100),path+".life",maximum=100,integer=True)
        _numeric(raw.get("stamina",100.),path+".stamina",maximum=100)
        for field,limit in (("x",config["world"]["length"]),("y",config["world"]["width"])):
            _numeric(raw.get(field,0.),path+"."+field,maximum=limit,code="INVALID_GEOMETRY")
        if kind=="Zombie" and any(k in raw for k in ("hunger","inventory","carry_capacity","starvation_started_at")):
            _fail("INVALID_TYPE_STATUS",path,"Zombie has Human-only state")
        infection=raw.pop("initial_infection",None);raw.pop("infected",None)
        declared_status=raw.pop("status",None)
        if life==0:
            if role is not None or raw.get("active_action") or raw.get("effects") or raw.get("cooldowns") or raw.get("model_assignment"):
                _fail("INVALID_TYPE_STATUS",path,"dead state has active role, model, action, effect or cooldown")
            raw["model_assignment"]=None
        agent=make_agent(identifier,kind,role,**raw)
        agent["type_profile"]=deepcopy(config["profiles"].get(kind,{}))
        agent["role_profile"]=deepcopy(config["profiles"].get(role,{}))
        _validate_profile(agent.get("profile",{}),path+".profile")
        p=profile(agent,str(now))
        if life>0 and point_blocked(agent,config["barriers"]):_fail("INVALID_GEOMETRY",path,"living position is on or inside a closed barrier")
        if life>0 and (not isinstance(agent.get("model_assignment"),dict) or not agent["model_assignment"].get("model_id")):
            _fail("INVALID_REFERENCE",path+".model_assignment","living agent requires an identified model")
        if kind=="Human":
            _numeric(agent["hunger"],path+".hunger",maximum=100)
            _numeric(agent["carry_capacity"],path+".carry_capacity",integer=True)
            agent["inventory"],agent["reserved"]=_stocks(raw.get("inventory",{}),raw.get("reserved",{}),path+".inventory")
            if sum(agent["inventory"].values())>agent["carry_capacity"]:_fail("INVENTORY_CAPACITY",path+".inventory","mass exceeds carry capacity")
            if life==0 and sum(agent["inventory"].values()):_fail("INVALID_TYPE_STATUS",path+".inventory","dead inventory must have been dropped")
            if any(agent["reserved"].values()):_fail("INVALID_RESERVATION",path+".reserved","idle state cannot retain action reservations; use a complete runtime checkpoint")
        if infection is not None:
            if life==0 or kind!="Human":_fail("INVALID_EPISODE",path,"only a living Human can have an active infection")
            onset=_time(infection.get("onset_at",now),path+".infection.onset_at",code="INVALID_EPISODE")
            duration=_time(infection.get("incubation_duration",config["incubation_duration"]),path+".infection.incubation_duration",positive=True,code="INVALID_EPISODE")
            if not onset<=now<=onset+duration:_fail("INVALID_EPISODE",path+".infection","current time lies outside the episode")
            episode_id=str(infection.get("id",f"episode:initial:{identifier}"))
            if episode_id in episodes:_fail("DUPLICATE_ID",path+".infection.id","duplicate episode identity")
            episodes[episode_id]={"id":episode_id,"agent_id":identifier,"source_kind":"INITIAL_CONDITION",
                "source_agent_id":None,"source_event_id":"initialization","onset_at":str(onset),"onset_revision":0,
                "incubation_duration":str(duration),"conversion_due_at":str(onset+duration),"outcome":"ONGOING","ended_at":None,"end_revision":None}
            agent["infection_episode"]=episode_id
        episode=agent.get("infection_episode")
        if episode:
            if kind!="Human" or life==0 or episode not in episodes:_fail("INVALID_EPISODE",path+".infection_episode","active episode reference is invalid")
            ep=episodes[episode]
            if ep.get("agent_id")!=identifier or ep.get("outcome") not in (None,"ONGOING") or ep.get("ended_at") is not None:_fail("INVALID_EPISODE",path+".infection_episode","episode is closed or belongs to another identity")
        actual=status(agent)
        if declared_status is not None and declared_status!=actual:
            code="INVALID_EPISODE" if kind=="Human" and {declared_status,actual}=={"HEALTHY","INFECTED"} else "INVALID_TYPE_STATUS"
            _fail(code,path+".status","declared status disagrees with life/type/infection")
        agent["status"]=actual;agent["_evaluated_at"]=str(now)
        if agent.get("active_action"):_fail("INVALID_REFERENCE",path+".active_action","use a complete runtime checkpoint to restore an active occurrence")
        for action,end in agent["cooldowns"].items():_time(end,path+".cooldowns."+action)
        for name,effect in agent["effects"].items():
            effect.setdefault("kind",name);effect.setdefault("start_at",str(now))
            start=_time(effect["start_at"],path+".effects."+name+".start_at")
            end=_time(effect["end_at"],path+".effects."+name+".end_at")
            if not start<=now<end:_fail("INVALID_DOMAIN",path+".effects."+name,"active effect does not contain current time")
        if role=="SPITTER":
            _numeric(agent["spit_charges"],path+".spit_charges",maximum=int(p["max_spit_charges"]),integer=True)
            _numeric(agent.get("reserved_charges",0),path+".reserved_charges",maximum=agent["spit_charges"],integer=True,code="INVALID_RESERVATION")
            if agent["spit_charges"]<p["max_spit_charges"] and not agent.get("next_charge_at"):
                agent["next_charge_at"]=str(now+Fraction(str(p.get("recharge_interval",30))))
        agents[identifier]=agent
    for identifier,episode in episodes.items():
        path="episodes."+identifier
        owner=episode.get("agent_id")
        if owner not in agents:_fail("INVALID_REFERENCE",path,"unknown agent")
        onset=_time(episode["onset_at"],path+".onset_at",code="INVALID_EPISODE")
        duration=_time(episode["incubation_duration"],path+".incubation_duration",positive=True,code="INVALID_EPISODE")
        if _time(episode["conversion_due_at"],path+".conversion_due_at",code="INVALID_EPISODE")!=onset+duration:_fail("INVALID_EPISODE",path,"deadline differs from onset plus duration")
        if episode.get("outcome") is None:episode["outcome"]="ONGOING"
        if episode["outcome"] not in {"ONGOING","CURED","CONVERTED","HOST_DIED"}:_fail("INVALID_EPISODE",path+".outcome","unknown episode outcome")
        if episode["outcome"]=="ONGOING" and agents[owner].get("infection_episode")!=identifier:_fail("INVALID_EPISODE",path,"orphan active episode")
        if episode["outcome"]!="ONGOING":
            end=_time(episode.get("ended_at"),path+".ended_at",code="INVALID_EPISODE")
            if not onset<=end<=now:_fail("INVALID_EPISODE",path+".ended_at","closure lies outside the recorded history")
            if episode["outcome"]=="CONVERTED" and end!=onset+duration:_fail("INVALID_EPISODE",path,"conversion must close at the incubation deadline")
            if episode["outcome"]=="CURED" and end>=onset+duration:_fail("INVALID_EPISODE",path,"cure must precede the incubation deadline")
    stockpiles={}
    for original in config["stockpiles"]:
        stock=deepcopy(original);stock["inventory"],stock["reserved"]=_stocks(stock.get("inventory",{}),stock.get("reserved",{}),"stockpiles."+stock["id"])
        if any(stock["reserved"].values()):_fail("INVALID_RESERVATION","stockpiles."+stock["id"],"restore reservations together with their pending actions from a runtime checkpoint")
        stockpiles[stock["id"]]=stock
    remains={};sources=set()
    for original in config.get("remains",[]):
        item=deepcopy(original);identifier=str(item["id"]);path="remains."+identifier
        source=item.get("source_agent_id")
        if source not in agents or agents[source]["life"]!=0:_fail("INVALID_REFERENCE",path+".source_agent_id","remains must reference a dead identity")
        if source in sources or identifier in remains:_fail("DUPLICATE_ID",path,"duplicate remains identity or death")
        sources.add(source)
        _numeric(item.get("biomass"),path+".biomass",integer=True)
        item.setdefault("reserved_biomass",0)
        _numeric(item["reserved_biomass"],path+".reserved_biomass",maximum=item["biomass"],integer=True,code="INVALID_RESERVATION")
        for coordinate in ("x","y"):
            if item[coordinate]!=agents[source][coordinate]:_fail("INVALID_GEOMETRY",path,"remains position differs from the frozen death location")
        remains[identifier]=item
    if config.get("reservations"):_fail("INVALID_RESERVATION","reservations","a complete runtime checkpoint is required for pending reservations")
    return {"time":str(now),"revision":0,"world":deepcopy(config["world"]),"agents":agents,
            "barriers":{item["id"]:deepcopy(item) for item in config["barriers"]},
            "shelters":{item["id"]:deepcopy(item) for item in config["shelters"]},"stockpiles":stockpiles,
            "remains":remains,"episodes":episodes,"signals":deepcopy(config.get("signals",{})),
            "reservations":deepcopy(config.get("reservations",{})),
            "initialization":{"sampler":"validated_explicit_state_v1","approximate":False,"proposals":0},
            "scenario_fingerprint":config["fingerprint"],"source_provenance":deepcopy(config["provenance"])}
