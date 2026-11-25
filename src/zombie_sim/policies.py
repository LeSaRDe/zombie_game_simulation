"""Observation-only utility policies and versioned, pluggable model registry.

The candidate generator is also the declared action discretization for learning.
It never accepts a Simulation, state store, or privileged feasibility callback.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import math
import random
from typing import Any, Callable

from .registry import ACTIONS

MODEL_VERSION = "1.0.0"
OBSERVATION_VERSION = "local_v0.1"
ACTION_NAMES = (
    "move", "wait", "rest", "signal", "melee", "pickup", "drop", "transfer",
    "eat", "first_aid", "open_gate", "close_gate", "claw", "bite", "feed", "smash",
    "treat_infection", "prophylaxis", "power_strike", "guard", "recon", "mark_target",
    "build_barricade", "repair_barrier", "rally", "demolish", "dash", "spit", "scream",
)
ROLES = {"DOCTOR": ("treat_infection", "prophylaxis"), "WARRIOR": ("power_strike", "guard"),
         "SCOUT": ("recon", "mark_target"), "ENGINEER": ("build_barricade", "repair_barrier"),
         "TYRANT": ("rally", "demolish"), "RUNNER": ("dash",), "SPITTER": ("spit",), "SCREAMER": ("scream",)}
DURATION = dict(zip(ACTION_NAMES, (2,1,3,.5,1,1,.5,1,2,3,1,1,1,1.5,3,2,4,4,1.5,1,2,.5,8,5,2,3,1,1,2)))
COST = dict(zip(ACTION_NAMES, (0,0,0,1,6,1,0,1,0,4,1,1,6,10,0,10,6,6,15,8,6,1,12,8,15,18,12,8,15)))
DURATION.update({name: spec["duration"] for name, spec in ACTIONS.items() if isinstance(spec.get("duration"), (int, float))})
COST.update({name: spec.get("stamina_cost", spec.get("cost", COST[name])) for name, spec in ACTIONS.items()})
DEFAULT_PARAMETERS = {
    "memory_ttl": 90.0, "report_interval": 12.0, "move_duration": 3.0,
    "rest_below": 95.0, "eat_threshold": 35.0, "flee_distance": 20.0,
    "weights": {"survival": 4.0, "infection": 4.0, "damage": 2.2, "recovery": 2.0,
                "resource": 1.4, "ally": 2.0, "risk": -1.0, "travel": -.15,
                "stamina": -.25, "exploration": .55, "communication": .8, "barrier": 1.3,
                "waiting": .12},
}


def number(value: Any, default: float = 0.0) -> float:
    try:
        if isinstance(value, dict) and "numerator" in value:
            return float(Fraction(value["numerator"], value["denominator"]))
        result = float(Fraction(value)) if isinstance(value, str) else float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError, ZeroDivisionError):
        return default


def records(value: Any) -> list[dict]:
    if isinstance(value, dict):
        return [dict(v, id=v.get("id", k)) for k, v in value.items() if isinstance(v, dict)]
    return [v for v in (value or []) if isinstance(v, dict)]


def identifier(entity: dict) -> Any:
    return entity.get("id", entity.get("ID", entity.get("entity_id")))


def position(entity: dict) -> tuple[float, float]:
    p = entity.get("position", entity)
    if isinstance(p, (list, tuple)):
        return number(p[0]), number(p[1])
    return number(p.get("x")), number(p.get("y"))


def attr(entity: dict, key: str, default: Any = 0) -> Any:
    for source in (entity, entity.get("human", {}), entity.get("zombie", {}), entity.get("role_properties", {}), entity.get("profile", {})):
        if key in source:
            return source[key]
    return default


def available(entity: dict, resource: str) -> int:
    inv = attr(entity, "inventory", entity.get("resources", entity.get("stocks", entity.get("stock", {}))))
    if isinstance(inv, dict) and "total" in inv:
        inv = inv["total"]
    raw = inv.get(resource, 0) if isinstance(inv, dict) else 0
    if isinstance(raw, dict):
        return int(raw.get("available", raw.get("quantity", raw.get("total", 0)) - raw.get("reserved", 0)))
    reserved = entity.get("reserved", attr(entity, "reserved_inventory", {}))
    return max(0, int(raw) - int(reserved.get(resource, 0) if isinstance(reserved, dict) else 0))


def held_quantity(entity: dict, resource: str) -> int:
    """Capacity counts reserved inventory as still physically carried."""
    inv=attr(entity,"inventory",entity.get("resources",entity.get("stocks",entity.get("stock",{}))))
    if isinstance(inv,dict) and "total" in inv:inv=inv["total"]
    raw=inv.get(resource,0) if isinstance(inv,dict) else 0
    if isinstance(raw,dict):
        return max(0,int(raw.get("total",raw.get("quantity",number(raw.get("available",0))+number(raw.get("reserved",0))))))
    return max(0,int(raw))


def bounds(observation: dict) -> tuple[float, float]:
    b = observation.get("world", observation.get("bounds", observation.get("time_and_bounds", {})))
    return number(b.get("length", 1000), 1000), number(b.get("width", 1000), 1000)


def rectangle(entity: dict) -> tuple[float, float, float, float] | None:
    f = entity.get("footprint", entity.get("rect"))
    if f is None and len(entity.get("visible_segments",[])) == 4:
        # A complete observed rectangular perimeter determines a rectangle;
        # a single visible face never licenses inventing its unseen extent.
        points = [tuple(p) for segment in entity["visible_segments"] for p in segment]
        unique=set(points)
        if len(unique)==4 and all(points.count(p)==2 for p in unique):
            x0,y0=min(p[0] for p in points),min(p[1] for p in points)
            x1,y1=max(p[0] for p in points),max(p[1] for p in points)
            if unique=={(x0,y0),(x0,y1),(x1,y0),(x1,y1)}:
                f=[x0,y0,x1,y1]
    if isinstance(f, (tuple, list)) and len(f) == 4:
        return tuple(map(float, f))
    if isinstance(f, dict):
        for names in (("xmin", "ymin", "xmax", "ymax"), ("x_min", "y_min", "x_max", "y_max"), ("x1", "y1", "x2", "y2")):
            if all(k in f for k in names):
                return tuple(number(f[k]) for k in names)
    return None


def barrier_active(b: dict) -> bool:
    if b.get("mode") in ("OPEN", "BREACHED") or number(b.get("integrity", 1)) <= 0:
        return False
    return b.get("blocks_movement", True)


def distance(a: dict, b: dict) -> float:
    x, y = position(a)
    r = rectangle(b)
    if r:
        return math.hypot(max(r[0]-x, 0, x-r[2]), max(r[1]-y, 0, y-r[3]))
    if b.get("visible_segments"):
        distances=[]
        for start,end in b["visible_segments"]:
            dx,dy=end[0]-start[0],end[1]-start[1]
            t=max(0,min(1,((x-start[0])*dx+(y-start[1])*dy)/max(1e-20,dx*dx+dy*dy)))
            distances.append(math.hypot(x-start[0]-t*dx,y-start[1]-t*dy))
        return min(distances)
    u, v = position(b)
    return math.hypot(x-u, y-v)


def capabilities(agent: dict) -> set[str]:
    if number(agent.get("life", 100)) <= 0:
        return set()
    base = set(ACTION_NAMES[:4])
    base.update(ACTION_NAMES[4:12] if agent.get("type") == "Human" else ACTION_NAMES[12:16])
    base.update(ROLES.get(agent.get("role"), ()))
    return base


def initialize_memory(agent: dict) -> dict:
    return {"version": MODEL_VERSION, "owner": identifier(agent), "type": agent.get("type"),
            "geometry": {}, "resources": {}, "sightings": {}, "reports": [], "objective": None,
            "route": [], "recent_failures": [], "last_reports": {}, "visits": {}, "decisions": 0}


def update_memory(observation: dict, memory: dict | None, parameters: dict) -> dict:
    a = observation["self_state"]
    if not memory or memory.get("type") != a.get("type") or memory.get("owner") != identifier(a):
        memory = initialize_memory(a)
    m = deepcopy(memory)
    observed_at = deepcopy(observation.get("time", observation.get("time_and_bounds", {}).get("time", 0)))
    now = number(observed_at)
    env = observation.get("local_environment", {})
    for b in records(env.get("barriers", {})):
        m["geometry"][str(identifier(b))] = {"entity": deepcopy(b), "seen_at": observed_at}
    for b in records(env.get("stockpiles", {})) + records(env.get("remains", {})):
        m["resources"][str(identifier(b))] = {"entity": deepcopy(b), "seen_at": observed_at}
    for b in records(observation.get("local_agents", {})):
        m["sightings"][str(identifier(b))] = {"entity": deepcopy(b), "seen_at": observed_at}
    ttl = number(parameters.get("memory_ttl", 90))
    for key in ("sightings", "resources"):
        m[key] = {k: v for k, v in m[key].items() if now-number(v["seen_at"]) <= ttl}
    reports = {json.dumps(v, sort_keys=True): v for v in m.get("reports", [])}
    for report in records(observation.get("received_signals", [])):
        reports[json.dumps(report, sort_keys=True)] = deepcopy(report)
    m["reports"] = [r for r in reports.values() if now-number(r.get("emitted_at", r.get("time", now))) <= ttl][-32:]
    m["recent_failures"] = (m.get("recent_failures", []) + deepcopy(observation.get("recent_failures", [])))[-8:]
    x,y = position(a)
    cell = f"{int(x//10)},{int(y//10)}"
    m["visits"][cell] = m["visits"].get(cell, 0)+1
    m["decisions"] += 1
    return m


@dataclass
class Candidate:
    intent: dict
    features: dict[str, float]
    reason: str
    duration: float
    stamina_cost: float
    score: float = 0.0

    def as_dict(self) -> dict:
        return {"intent": deepcopy(self.intent), "features": dict(self.features), "reason": self.reason,
                "duration": self.duration, "stamina_cost": self.stamina_cost, "score": self.score}


def _segment_clear(start, end, barriers):
    # Liang-Barsky on known closed footprints or individually observed edges.
    for b in barriers:
        if not barrier_active(b):
            continue
        r = rectangle(b)
        footprints=[r] if r is not None else [(min(u[0],v[0]),min(u[1],v[1]),max(u[0],v[0]),max(u[1],v[1])) for u,v in b.get("visible_segments",[]) if u[0]==v[0] or u[1]==v[1]]
        for r in footprints:
            lo, hi = 0.0, 1.0
            for s, d, low, high in ((start[0], end[0]-start[0], r[0], r[2]), (start[1], end[1]-start[1], r[1], r[3])):
                if abs(d) < 1e-14:
                    if s < low or s > high:
                        lo, hi = 1, 0
                        break
                else:
                    u,v = sorted(((low-s)/d, (high-s)/d))
                    lo, hi = max(lo,u), min(hi,v)
            if lo <= hi:
                return False
    return True


def _route(start, goal, barriers, world_bounds):
    """Use shared geometry routing; the supplied map contains observed geometry only."""
    from .geometry import route
    local = []
    for b in barriers:
        r = rectangle(b)
        if r is not None:
            local.append(dict(b, footprint=list(r)))
        else:
            for i,(u,v) in enumerate(b.get("visible_segments",[])):
                if u[0]==v[0] or u[1]==v[1]:
                    local.append(dict(b,id=f"{identifier(b)}:observed-edge:{i}",footprint=[min(u[0],v[0]),min(u[1],v[1]),max(u[0],v[0]),max(u[1],v[1])]))
    return [start] + route(start, goal, local, {"length": world_bounds[0], "width": world_bounds[1]})


def generate_candidates(observation: dict, memory: dict | None = None, parameters: dict | None = None) -> list[Candidate]:
    p = deepcopy(DEFAULT_PARAMETERS)
    if parameters:
        p.update({k:v for k,v in parameters.items() if k != "weights"})
        p["weights"].update(parameters.get("weights", {}))
    a = observation["self_state"]
    m = memory or initialize_memory(a)
    now = number(observation.get("time", 0)); aid = identifier(a)
    own_type = a.get("type", "Human"); role = a.get("role")
    own_stamina = number(a.get("stamina", 100)); own_life = number(a.get("life", 100))
    known = [v["entity"] for v in m.get("geometry", {}).values()]
    env = observation.get("local_environment", {})
    visible_barriers = records(env.get("barriers", {}))
    by_id = {str(identifier(b)): b for b in known + visible_barriers}
    barriers = list(by_id.values())
    neighbors = sorted(records(observation.get("local_agents", {})), key=lambda b: str(identifier(b)))
    allies = [b for b in neighbors if b.get("type") == own_type and number(b.get("life",100)) > 0]
    enemies = sorted([b for b in neighbors if b.get("type") != own_type and number(b.get("life",100)) > 0], key=lambda b: (distance(a,b), str(identifier(b))))
    nearest = distance(a,enemies[0]) if enemies else math.inf
    danger = max(0., 1-nearest/15)
    allowed = capabilities(a); cooldown = a.get("cooldown_until", a.get("cooldowns", {}))
    result: list[Candidate] = []

    def add(action, reason, target=None, parameters=None, **features):
        if action not in allowed or now < number(cooldown.get(action, 0)) or own_stamina < COST[action]:
            return
        intent = {"actor": aid, "action": action, "parameters": parameters or {}}
        if target is not None:
            intent["target"] = identifier(target) if isinstance(target, dict) else target
        duration = number(intent["parameters"].get("duration", attr(a,"treatment_duration",DURATION[action]) if action=="treat_infection" else DURATION[action]))
        fs = {k: max(-1., min(1., number(v))) for k,v in features.items()}
        fs.setdefault("travel", duration/8); fs.setdefault("stamina", COST[action]/20)
        score = sum(p["weights"].get(k,0)*v for k,v in fs.items())
        result.append(Candidate(intent, fs, reason, duration, COST[action], score))

    def go(goal, reason, action="move", **features):
        start = position(a); length,width = bounds(observation)
        goal = (min(length,max(0,goal[0])), min(width,max(0,goal[1])))
        if math.dist(start, goal) < .1:
            return
        speed = number(attr(a,"speed",attr(a,"base_speed",2 if own_type=="Human" else 1.6)))
        dt = number(p["move_duration"])
        if action == "dash":
            speed = number(attr(a,"base_speed",3.2))*number(attr(a,"dash_multiplier",1.5)); dt = number(attr(a,"dash_duration",1))
            if own_stamina < 18:
                return
        cost_rate = number(attr(a,"movement_cost",.1 if own_type=="Human" else .08))
        limit = min(speed*dt, max(0,own_stamina-COST[action])/max(cost_rate,1e-9))
        if limit < .1 or speed <= 0:
            return
        path = _route(start, goal, barriers, (length,width))
        if not path:
            return
        pts = [{"x":start[0],"y":start[1],"offset":0.0}]; total = 0.
        for dest in path[1:]:
            d = math.dist((pts[-1]["x"],pts[-1]["y"]), dest)
            if d < 1e-9:
                continue
            take = min(d,limit-total)
            prev=pts[-1]
            x=prev["x"]+(dest[0]-prev["x"])*take/d; y=prev["y"]+(dest[1]-prev["y"])*take/d
            total += take
            pts.append({"x":x,"y":y,"offset":total/speed})
            if total >= limit-1e-9:
                break
        if len(pts)<2:
            return
        duration = dt if action=="dash" else max(.25,total/speed)
        if pts[-1]["offset"] < duration:
            pts.append(dict(pts[-1],offset=duration))
        add(action,reason,parameters={"duration":duration,"path":pts},**features)

    add("wait", "Hold position briefly while observable operations or cooldowns resolve", parameters={"duration":1}, waiting=1 if a.get("stamina",100)>=95 else .1)
    rest_rate=number(attr(a,"rest_rate",4),4)
    if own_stamina < p["rest_below"] and rest_rate>0:
        add("rest", "Recover stamina before the next costly action",parameters={"duration":min(5,max(1,(100-own_stamina)/rest_rate))},recovery=(100-own_stamina)/70,risk=danger)
    if own_life<=0:
        return []
    # Waiting for an ally's gate operation is preferable to walking against it.
    if any(b.get("current_action", b.get("action")) in ("open_gate","close_gate") for b in allies):
        add("wait", "Allow the observed gate operation to finish", parameters={"duration":1}, waiting=1,ally=.3)
    last = m.get("last_reports",{})
    if enemies and now-number(last.get(str(identifier(enemies[0])), -1e9)) >= number(p["report_interval"]):
        enemy = enemies[0]; ep = position(enemy)
        payload = {"entity_id":identifier(enemy),"position":{"x":ep[0],"y":ep[1]},"observed_at":observation.get("time",0)}
        if allies:
            add("signal", "Warn visible allies about a newly observed opponent", parameters={"kind":"WARNING","payload":payload},communication=.8,ally=.1)
        if role == "SCOUT":
            add("mark_target", "Share a new directly visible threat at extended range", enemy, communication=1,ally=.3)
        if role == "SCREAMER":
            add("scream", "Broadcast a fresh hunt sighting", parameters={"payload":payload},communication=1,ally=.4)
    if own_type == "Human":
        hunger=number(attr(a,"hunger",0)); capacity=int(attr(a,"carry_capacity",10))
        mass=sum(held_quantity(a,r) for r in ("FOOD","MEDICAL_SUPPLY","MATERIAL"))
        medicine=available(a,"MEDICAL_SUPPLY"); food=available(a,"FOOD"); materials=available(a,"MATERIAL")
        if food and hunger>0:
            add("eat","Eat before hunger threatens survival",survival=max(0,(hunger-p["eat_threshold"])/max(1,100-p["eat_threshold"])),resource=min(hunger,40)/80,risk=danger*.3)
        patients=[a]+[b for b in allies if distance(a,b)<=1.5]
        if medicine:
            for b in patients:
                injury=(100-number(b.get("life",100)))/100
                if injury>0:
                    add("first_aid","Restore injury without changing infection",b,recovery=min(1,injury*1.8),survival=injury*.5,ally=.3*injury if b is not a else 0,risk=danger*.5)
                if b.get("status")=="INFECTED":
                    deadline=number(attr(b,"conversion_due_at",attr(b,"infection_deadline",now+300)))
                    if now+number(attr(a,"treatment_duration",4))<deadline and medicine>=int(attr(a,"treatment_cost",1)):
                        add("treat_infection","Cure an infection with positive completion slack",b,infection=.75+max(0,1-(deadline-now)/60)*.25,ally=.3 if b is not a else 0)
                elif danger>0 and number(attr(b,"infection_resistance_effective",.2))<.8:
                    add("prophylaxis","Protect an uninfected ally facing visible exposure",b,infection=.35+danger*.35,ally=.2 if b is not a else 0,risk=danger*.2)
        if role=="DOCTOR" and medicine>=int(attr(a,"treatment_cost",1)):
            for patient in allies:
                if patient.get("status")!="INFECTED" or distance(a,patient)<=1.5:
                    continue
                deadline=number(attr(patient,"conversion_due_at",now+300))
                plan=_route(position(a),position(patient),barriers,bounds(observation))
                travel=sum(math.dist(left,right) for left,right in zip(plan,plan[1:]))/max(.001,number(attr(a,"speed",2)))
                if len(plan)>1 and now+travel+number(attr(a,"treatment_duration",4))<deadline:
                    go(position(patient),"Reach a curable patient with positive travel-and-treatment slack",infection=.75+max(0,1-(deadline-now-travel)/60)*.25,ally=.2)
        if role=="DOCTOR" and medicine==0 and any(b.get("status")=="INFECTED" for b in [a]+allies):
            immediate_supply=any(distance(a,b)<=1.5 and available(b,"MEDICAL_SUPPLY")>0 for b in records(env.get("stockpiles",{})))
            if not immediate_supply and now-number(last.get("help",-1e9))>=number(p["report_interval"]):
                add("signal","Request medicine for a locally observed infection",parameters={"kind":"REQUEST_HELP","payload":{"entity_id":aid,"resource":"MEDICAL_SUPPLY","quantity":1,"observed_at":observation.get("time",0)}},infection=.25,communication=.7,ally=.4)
        for b in allies:
            if distance(a,b)<=1.5:
                bmass=sum(held_quantity(b,r) for r in ("FOOD","MEDICAL_SUPPLY","MATERIAL"))
                if bmass<int(attr(b,"carry_capacity",10)):
                    if medicine and b.get("role")=="DOCTOR" and available(b,"MEDICAL_SUPPLY")==0 and role!="DOCTOR":
                        add("transfer","Give medicine to an equipped healer",b,{"resource":"MEDICAL_SUPPLY","quantity":1},ally=.9,resource=.3)
                    if food and number(attr(b,"hunger",0))>max(hunger+20,65):
                        add("transfer","Feed a more urgently hungry ally",b,{"resource":"FOOD","quantity":1},ally=.8,survival=.2)
        wants={"FOOD":max(.2,(hunger-20)/80) if food<2 else 0,
               "MEDICAL_SUPPLY":(.9 if role=="DOCTOR" else .45) if medicine<2 else 0,
               "MATERIAL":.8 if role=="ENGINEER" and materials<3 else 0}
        visible_stocks=records(env.get("stockpiles",{}))
        visible_stock_ids={str(identifier(v)) for v in visible_stocks}
        remembered_stocks=[v["entity"] for v in m.get("resources",{}).values() if str(identifier(v["entity"])) not in visible_stock_ids and "biomass" not in v["entity"]]
        for stock in visible_stocks+remembered_stocks:
            direct=str(identifier(stock)) in visible_stock_ids
            for resource,value in wants.items():
                if value<=0 or available(stock,resource)<=0:
                    continue
                if mass<capacity:
                    if direct and distance(a,stock)<=1.5:
                        add("pickup",f"Collect useful {resource.lower()}",stock,{"resource":resource,"quantity":1},resource=value,risk=danger*.3)
                    else:
                        go(position(stock),f"Travel to observed {resource.lower()}",resource=value*.8,risk=danger*.4)
                elif direct and distance(a,stock)<=1.5:
                    disposable=[r for r in wants if available(a,r)>0 and wants[r]<value]
                    if disposable:
                        low=min(disposable,key=lambda r:wants[r])
                        add("drop","Free inventory capacity for a more valuable resource",parameters={"resource":low,"quantity":1},resource=value+.1)
        if a.get("status")=="INFECTED" and role!="DOCTOR":
            doctors=[b for b in allies if b.get("role")=="DOCTOR" and available(b,"MEDICAL_SUPPLY")>0]
            if doctors:
                doc=min(doctors,key=lambda b:distance(a,b)); go(position(doc),"Reach a visible doctor before conversion",infection=.9)
            elif now-number(last.get("help",-1e9))>=number(p["report_interval"]):
                add("signal","Request treatment using own observed infection",parameters={"kind":"REQUEST_HELP","payload":{"entity_id":aid,"observed_at":observation.get("time",0)}},infection=.35,communication=.7)
        for enemy in enemies[:4]:
            d=distance(a,enemy); resist=number(enemy.get("damage_resistance",0)); hp=number(enemy.get("life",100))
            if d<=1.5:
                skill=number(attr(a,"combat_skill",.35)); hit=.5+.45*skill
                normal=number(attr(a,"melee_damage",16))*(1-resist)
                add("melee","Fight the reachable threat with a fast attack",enemy,damage=min(1,hit*normal/25),survival=.9 if hp<=normal else .3+(1-own_life/100)*.1)
                strong=number(attr(a,"strike_damage",34))*(1-resist)
                add("power_strike","Use a heavy strike when its finishing damage is valuable",enemy,damage=min(1,hit*strong/30),survival=.55 if normal<hp<=strong else .15)
            if 1.5<d<7 and role=="WARRIOR" and not any(e.get("kind")=="guard" for e in records(a.get("effects",[]))):
                add("guard","Prepare resistance before imminent contact",survival=.35,ally=.1,recovery=.1)
        if enemies:
            if (role!="WARRIOR" or own_life<35 or own_stamina<12) and nearest<p["flee_distance"]:
                ex,ey=position(enemies[0]); x,y=position(a); dx,dy=x-ex,y-ey
                norm=math.hypot(dx,dy) or 1
                go((x+dx/norm*20,y+dy/norm*20),"Increase separation from a visible threat",survival=.4+danger*.4,risk=.05)
            elif role=="WARRIOR" and nearest>1.5:
                go(position(enemies[0]),"Intercept a threat near vulnerable allies",survival=.1,ally=.6 if allies else .1,damage=.25)
        if role=="SCOUT" and nearest>8 and number(a.get("sense_r",55))<number(attr(a,"recon_radius",85)):
            add("recon","Expand sensing into locally unexplored space",exploration=1,communication=.25)
        for b in visible_barriers:
            if distance(a,b)>2:
                continue
            r=rectangle(b)
            gate=b.get("kind",b.get("type")) in ("Gate","gate") or "mode" in b
            if gate and b.get("mode")=="CLOSED":
                add("open_gate","Open an observed doorway for passage",b,barrier=.65,risk=danger)
            if gate and b.get("mode")=="OPEN" and enemies and r:
                inside=lambda e:r[0]<=position(e)[0]<=r[2] and r[1]<=position(e)[1]<=r[3]
                occupied=any(inside(v) for v in [a]+neighbors)
                overlap=any(barrier_active(v) and rectangle(v) and rectangle(v)[0]<r[2] and rectangle(v)[2]>r[0] and rectangle(v)[1]<r[3] and rectangle(v)[3]>r[1] for v in visible_barriers if v is not b)
                if not occupied and not overlap:
                    add("close_gate","Close an unoccupied doorway against a visible threat",b,survival=.65,barrier=.6)
            integrity=number(b.get("integrity",100)); maximum=number(b.get("max_integrity",100))
            if materials>=int(attr(a,"repair_material_cost",1)) and integrity<maximum and (gate or integrity>0):
                add("repair_barrier","Restore a damaged useful defense",b,barrier=(maximum-integrity)/maximum,survival=.15 if enemies else 0)
            if role=="ENGINEER" and materials>=int(attr(a,"build_material_cost",2)) and gate and b.get("mode") in ("OPEN","BREACHED") and r:
                cx,cy=(r[0]+r[2])/2,(r[1]+r[3])/2; orientation="x" if r[2]-r[0]>=r[3]-r[1] else "y"
                span=min(8,max(2,(r[2]-r[0]) if orientation=="x" else (r[3]-r[1])))
                footprint=(cx-span/2,cy-.5,cx+span/2,cy+.5) if orientation=="x" else (cx-.5,cy-span/2,cx+.5,cy+span/2)
                occupied=any(footprint[0]<=position(v)[0]<=footprint[2] and footprint[1]<=position(v)[1]<=footprint[3] for v in [a]+neighbors+records(env.get("stockpiles",{}))+records(env.get("remains",{})))
                intersects=any(barrier_active(v) and rectangle(v) and rectangle(v)[0]<footprint[2] and rectangle(v)[2]>footprint[0] and rectangle(v)[1]<footprint[3] and rectangle(v)[3]>footprint[1] for v in visible_barriers if v is not b)
                length,width=bounds(observation)
                corners=[(footprint[i],footprint[j]) for i in (0,2) for j in (1,3)]
                visible=all(0<=u<=length and 0<=v<=width and math.dist(position(a),(u,v))<=number(attr(a,"sense_r",40)) and _segment_clear(position(a),(u,v),[v for v in visible_barriers if v is not b]) for u,v in corners)
                if not occupied and not intersects and visible and math.dist(position(a),(cx,cy))<=2 and enemies:
                    add("build_barricade","Defend a breached or open entrance outside the planned route",parameters={"center":{"x":cx,"y":cy},"orientation":orientation,"length":span},barrier=1,survival=.6 if b.get("mode")=="BREACHED" else .2)
    else:
        for enemy in enemies[:4]:
            d=distance(a,enemy); hp=number(enemy.get("life",100)); resistance=number(enemy.get("damage_resistance",0))
            hit=min(.95,.6+.3*number(attr(a,"attack_skill",.4)))
            if d<=1.5:
                damage=number(attr(a,"claw_damage",14))*(1-resistance)
                add("claw","Prefer fast damage against a reachable opponent",enemy,damage=min(1,hit*damage/25),survival=.25 if hp<=damage else .05)
                infection=number(attr(a,"virulence",.45))*(1-number(attr(enemy,"infection_resistance_effective",.2))) if enemy.get("status")=="HEALTHY" else 0
                add("bite","Trade a slower strike for a new infection opportunity",enemy,damage=.15,infection=infection*.8)
            elif d>1.5:
                go(position(enemy),"Pursue a directly observed human",damage=.3,infection=.12)
                go(position(enemy),"Dash toward prey while preserving attack stamina",action="dash",damage=.45,infection=.12)
            if d<=number(attr(a,"spit_range",12)) and number(attr(a,"spit_charges",0))>0:
                infection=.3*(1-number(attr(enemy,"infection_resistance_effective",.2))) if enemy.get("status")=="HEALTHY" else 0
                add("spit","Use an available ranged charge on visible prey",enemy,damage=.2,infection=infection+.15 if d>1.5 else infection)
        for remains in records(env.get("remains",{})):
            if number(remains.get("biomass",0))-number(remains.get("reserved_biomass",remains.get("reserved",0)))<=0 or own_life>=100 and own_stamina>=100:
                continue
            recovery=min(1,(100-own_life)/70+(100-own_stamina)/100)
            if distance(a,remains)<=1.5:
                add("feed","Recover life and stamina from available remains",remains,recovery=recovery,survival=(100-own_life)/180)
            else:
                go(position(remains),"Reach known remains for recovery",recovery=recovery*.7)
        for b in visible_barriers:
            if distance(a,b)<=2 and barrier_active(b) and ("mode" in b or b.get("kind",b.get("type")) in ("Barricade","barricade")):
                integrity=number(b.get("integrity",100))
                add("smash","Break a blocking gate or barricade",b,barrier=.75 if integrity<=20 else .4)
                add("demolish","Use heavy demolition against a durable barrier",b,barrier=.95 if integrity>20 else .4)
        nearby=[b for b in allies if distance(a,b)<=number(attr(a,"rally_radius",30))]
        if enemies and nearby:
            add("rally","Improve attacks by observable allies entering combat",ally=min(1,len(nearby)*.35),damage=.2)
        if not enemies:
            remembered=[v for v in m.get("sightings",{}).values() if v["entity"].get("type")=="Human"]
            if remembered:
                sight=max(remembered,key=lambda v:number(v["seen_at"]))
                go(position(sight["entity"]),"Investigate a dated human sighting",infection=.08,damage=.12)
            elif m.get("reports"):
                report=m["reports"][-1]; loc=report.get("payload",{}).get("position",report.get("position_at_emission",report.get("position")))
                if loc:
                    go(position({"position":loc}),"Investigate a dated signal or noise location",exploration=.8)
    # Local frontier headings are deterministic; memory penalizes repeated cells.
    x,y=position(a)
    for angle in range(0,360,45):
        dx,dy=math.cos(math.radians(angle))*10,math.sin(math.radians(angle))*10
        cell=f"{int((x+dx)//10)},{int((y+dy)//10)}"
        novelty=1/(1+m.get("visits",{}).get(cell,0))
        go((x+dx,y+dy),"Explore an unvisited local frontier",exploration=novelty,risk=danger*.7)
    return result


def select_utility_index(candidates: list[Candidate], rng: random.Random) -> int:
    """The shared seeded tie rule for deployed utility and learning baselines."""
    best=max(c.score for c in candidates)
    return rng.choice([i for i,c in enumerate(candidates) if abs(c.score-best)<1e-12])


def commit_action_memory(observation: dict, memory: dict, intent: dict, reason: str | None = None) -> dict:
    """Record the selected candidate consistently for every controller adapter."""
    result=deepcopy(memory)
    result["objective"]=reason or intent["action"]
    result["route"]=deepcopy(intent.get("parameters",{}).get("path",[]))
    if intent["action"] in ("signal","mark_target","scream"):
        payload=intent.get("parameters",{}).get("payload",{})
        key=str(intent.get("target",payload.get("entity_id","help")))
        if intent.get("parameters",{}).get("kind")=="REQUEST_HELP":key="help"
        result.setdefault("last_reports",{})[key]=number(observation.get("time",0))
    return result


class UtilityModel:
    version=MODEL_VERSION
    applicable_types=("Human","Zombie")
    def __init__(self, parameters: dict | None = None):
        self.parameters=deepcopy(DEFAULT_PARAMETERS)
        if parameters:
            self.parameters.update({k:v for k,v in parameters.items() if k!="weights"})
            self.parameters["weights"].update(parameters.get("weights",{}))
    def initialize_memory(self, agent):
        return initialize_memory(agent)
    def decide(self, observation, memory, rng):
        if observation["self_state"].get("type") not in self.applicable_types:
            raise ValueError("Decision model is incompatible with the current biological type")
        m=update_memory(observation,memory,self.parameters)
        candidates=generate_candidates(observation,m,self.parameters)
        if not candidates:
            raise ValueError("No candidates for nonliving agent")
        chosen=candidates[select_utility_index(candidates,rng)]
        m=commit_action_memory(observation,m,chosen.intent,chosen.reason)
        ranked=sorted(candidates,key=lambda c:c.score,reverse=True)
        diagnostics={"model_version":self.version,"chosen_score":chosen.score,"reason":chosen.reason,
                     "candidate_count":len(candidates),"ranked_candidates":[c.as_dict() for c in ranked]}
        return deepcopy(chosen.intent),m,diagnostics
    def decide_batch(self, observations, memories, rngs):
        return [self.decide(o,m,r) for o,m,r in zip(observations,memories,rngs,strict=True)]
    def manifest(self):
        encoded=json.dumps(self.parameters,sort_keys=True,separators=(",",":")).encode()
        return {"model_id":getattr(self,"model_id","utility/v1"),"model_version":self.version,
                "applicable_types":["Human"] if isinstance(self,HumanDefaultModel) else ["Zombie"] if isinstance(self,ZombieDefaultModel) else ["Human","Zombie"],"observation_version":OBSERVATION_VERSION,
                "action_vocabulary":"ontology_v0.1","encoder_version":"candidate_v1",
                "parameter_checksum":hashlib.sha256(encoded).hexdigest(),"parameters":deepcopy(self.parameters),
                "dependencies":[],"deterministic":True,"restartable":True}


class HumanDefaultModel(UtilityModel):
    applicable_types=("Human",)
    model_id="defaultHuman/v1"


class ZombieDefaultModel(UtilityModel):
    applicable_types=("Zombie",)
    model_id="defaultZombie/v1"


class RandomLegalModel(UtilityModel):
    """Random observable candidates; admission may still fail after state changes."""
    model_id="randomLegal/v1"
    def decide(self,observation,memory,rng):
        m=update_memory(observation,memory,self.parameters)
        candidates=generate_candidates(observation,m,self.parameters)
        c=rng.choice(candidates)
        m=commit_action_memory(observation,m,c.intent,c.reason)
        return deepcopy(c.intent),m,{"model_version":self.version,"reason":"Uniform observable candidate","candidate_count":len(candidates)}


_REGISTRY: dict[str, Callable] = {}

def register_model(name: str, factory: Callable, *, replace: bool = False) -> None:
    if not name or not callable(factory):
        raise ValueError("A model requires a nonempty name and callable factory")
    if name in _REGISTRY and not replace:
        raise ValueError(f"Model already registered: {name}")
    _REGISTRY[name]=factory


@lru_cache(maxsize=16)
def _cached_learned_model(path,manifest_stamp,parameters_json):
    from .learning import LearnedModel
    return LearnedModel.load(path,json.loads(parameters_json))


def create_model(name: str, parameters: dict | None = None):
    if name.startswith("ppo:"):
        path=Path(name[4:]).resolve()
        return _cached_learned_model(str(path),(path/"manifest.json").stat().st_mtime_ns,json.dumps(parameters,sort_keys=True,allow_nan=False))
    if name not in _REGISTRY:
        raise ValueError(f"Unknown decision model {name!r}; registered: {', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[name](parameters)


def registered_models() -> tuple[str,...]:
    return tuple(sorted(_REGISTRY))


def choose(observation: dict, memory: dict | None, rng: random.Random, model_id: str | None = None, parameters: dict | None = None):
    name=model_id or ("defaultHuman" if observation["self_state"]["type"]=="Human" else "defaultZombie")
    return create_model(name,parameters).decide(deepcopy(observation),memory,rng)


for _names,_factory in ((("defaultHuman/v1","defaultHuman","HumanDefaultModel"),HumanDefaultModel),
                        (("defaultZombie/v1","defaultZombie","ZombieDefaultModel"),ZombieDefaultModel),
                        (("randomLegal/v1","randomLegal"),RandomLegalModel)):
    for _name in _names:
        register_model(_name,_factory)
