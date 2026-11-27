"""TOML configuration resolution, validation, and accountable initial placement."""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
import tomllib
from .domain import RESOURCES, TYPE_PROFILES, make_agent, profile
from .geometry import contains, distance_to, overlap, point_blocked, rect, route
from .registry import ROLES, baseline_graph, provenance

class ConfigError(ValueError):
    """An invalid scenario; messages name the offending field or relationship."""

class PlacementError(ConfigError):
    """Sampling budget exhausted, without asserting mathematical infeasibility."""

DEFAULTS = {
    "scenario": "small_v0.1", "seed": 20261106, "horizon": 1800.0,
    "role_assignment_order": "canonical_v2",
    "incubation_duration": 300.0, "allow_intraspecies_combat": False,
    "world": {"length": 100.0, "width": 100.0, "boundary_policy": "CLOSED"},
    "population": {"humans": 16, "zombies": 4, "infected": 0, "human_roles": {}, "zombie_roles": {}},
    "placement": {"sampler": "exact", "max_attempts": 10000, "max_point_attempts": 10000, "allow_approximate": False, "burn_in": 10, "minimum_separation": 2.0, "cross_type_separation": 15.0},
    "profiles": {}, "barriers": [], "shelters": [], "stockpiles": [],
    "storage": {"backend": "memory"}, "execution": {"workers": "auto"},
    "checkpoint_interval": 300.0, "checkpoint_transactions": 250000,
}


def _merge(base, update):
    for key,value in update.items():
        if isinstance(value,dict) and isinstance(base.get(key),dict):
            _merge(base[key],value)
        else:
            base[key]=deepcopy(value)
    return base


def semantic_config(config):
    """Return modeled scenario inputs, excluding operational execution choices.

    Backends, pool budgets, checkpoint cadence, telemetry, and provenance do not
    change a world's laws or initial conditions and cannot change its identity.
    """
    execution_only={"execution","storage","backend","workers","checkpoint_interval",
                    "checkpoint_transactions","telemetry","profiling","gui","visualization",
                    "history_path","output","fingerprint","semantic_fingerprint","provenance","preset"}
    def canonical_value(value):
        # JSON and TOML may spell the same modeled number as 5 or 5.0.
        # Identity follows its value, without modifying resolved runtime inputs.
        if isinstance(value,float) and math.isfinite(value) and value.is_integer():
            return int(value)
        if isinstance(value,dict):return {key:canonical_value(child) for key,child in value.items()}
        if isinstance(value,(list,tuple)):return [canonical_value(child) for child in value]
        return deepcopy(value)
    return {key:canonical_value(value) for key,value in config.items() if key not in execution_only}


def baseline_config():
    graph=baseline_graph()
    one=lambda node,key,default=None: graph[node].get(key,[default])[0]
    scenario="scenario"
    result=deepcopy(DEFAULTS)
    result["placement"].update(sampler="relocation",allow_approximate=True,burn_in=20)
    result["placement"]["approval"]={"decision":"D5","approved":True,"date":"2026-11-25","scope":"Baseline constrained relocation approximation explicitly approved by user"}
    result.update(scenario=one(scenario,"label"),seed=one(scenario,"seed"),horizon=one(scenario,"horizon"),incubation_duration=one(scenario,"incubation_duration"),allow_intraspecies_combat=one(scenario,"allow_intraspecies_combat"))
    result["world"].update(length=one("world","length"),width=one("world","width"))
    result["population"].update(humans=one(scenario,"initial_humans"),zombies=one(scenario,"initial_zombies"),infected=one(scenario,"initial_infected"))
    for node in graph[scenario]["allocation"]:
        role=one(node,"roleDefinition")
        if role:
            result["population"]["human_roles" if one(node,"biologicalType") == "Human" else "zombie_roles"][role]=one(node,"count")
    def rectangle(node):
        return [one(node,key) for key in ("xmin","ymin","xmax","ymax")]
    for node in graph[scenario]["hasEnvironmentState"]:
        entity=one(node,"ofEntity"); geometry=one(node,"geometry"); classes=graph[node]["a"]
        if "StockpileState" in classes:
            result["stockpiles"].append({"id":entity,"x":one(geometry,"x"),"y":one(geometry,"y"),"inventory":{one(s,"resourceType"):one(s,"quantity") for s in graph[node].get("stock",[])},"reserved":{}})
        else:
            kind="Gate" if "GateState" in classes else "Obstacle"
            item={"id":entity,"type":kind,"footprint":rectangle(geometry)}
            if kind=="Gate":
                item.update(mode=one(node,"gateMode"),integrity=one(node,"integrity"),max_integrity=one(node,"max_integrity"))
            result["barriers"].append(item)
    for node,data in graph.items():
        if "Shelter" in data.get("a",[]):
            result["shelters"].append({"id":node,"interior":rectangle(one(node,"geometry")),"walls":data["hasWall"],"gates":data["hasGate"]})
            for barrier in result["barriers"]:
                if barrier["id"] in data["hasGate"]:
                    barrier["shelter_id"]=node
    return result


def _number(value,path,minimum=None,maximum=None,integer=False,positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ConfigError(f"{path}: expected a finite {'integer' if integer else 'number'}")
    if integer and not isinstance(value,int):
        raise ConfigError(f"{path}: expected an integer")
    if minimum is not None and value<minimum or maximum is not None and value>maximum or positive and value<=0:
        raise ConfigError(f"{path}: value {value} is outside its allowed domain")


def _validate_profile(values,path):
    probability={"combat_skill","medical_skill","infection_resistance","attack_skill","virulence","spit_potency","prophylaxis_resistance","rally_hit_bonus"}
    integers={"melee_damage","claw_damage","bite_damage","feed_healing","carry_capacity","strike_damage","build_integrity","build_material_cost","repair_amount","repair_material_cost","demolish_damage","spit_damage","max_spit_charges","treatment_cost","max_life"}
    allowed=set().union(*(p.keys() for p in TYPE_PROFILES.values())) | set().union(*(set(p)-{"actions","type","registry_version"} for p in ROLES.values()))
    for key,value in values.items():
        if key not in allowed:
            raise ConfigError(f"{path}.{key}: unknown profile property")
        _number(value,f"{path}.{key}",minimum=0,maximum=1 if key in probability else .8 if key in ("base_damage_resistance","guard_resistance") else None,integer=key in integers,positive=key in ("base_speed","recharge_interval","treatment_duration","dash_duration","guard_duration","recon_duration","prophylaxis_duration","rally_duration","call_ttl"))
        if key in ("max_life","max_stamina") and value !=100:
            raise ConfigError(f"{path}.{key}: ontology v0.1 fixes the cap at 100")


def validate_config(config):
    from .domain import decision_model_assignment
    def validate_model(field,assignment,kind):
        try:
            decision_model_assignment(assignment["model_id"],assignment.get("version"),assignment.get("parameters"),agent_type=kind)
        except (ValueError, OSError, ImportError, KeyError, TypeError) as error:
            help_text = (" Install the model's required dependencies in the service's Python environment."
                         if isinstance(error, ImportError) else "")
            failure = ConfigError(f"{field}: {error}{help_text}")
            failure.code = getattr(error,"code","MODEL_UNAVAILABLE")
            raise failure from error
    for field,kind in (("human_model","Human"),("zombie_model","Zombie")):
        validate_model(field,{"model_id":config.get(field,kind+"DefaultModel")},kind)
    for index,agent in enumerate(config.get("agents",[])):
        assignment=agent.get("model_assignment")
        if assignment is not None:
            validate_model(f"agents[{index}].model_assignment",assignment,agent.get("type","Human"))
    if config.get("role_assignment_order") not in {"canonical_v2","legacy_insertion_v1"}:
        raise ConfigError("role_assignment_order must be canonical_v2 or legacy_insertion_v1")
    for key in ("length","width"):
        _number(config["world"][key],f"world.{key}",positive=True)
    if config["world"].get("boundary_policy","CLOSED")!="CLOSED":
        raise ConfigError("world.boundary_policy: only CLOSED is defined by ontology v0.1")
    for key in ("horizon","incubation_duration","checkpoint_interval"):
        _number(config[key],key,positive=True)
    _number(config["seed"],"seed",minimum=0,integer=True)
    pop=config["population"]
    for key in ("humans","zombies","infected"):
        _number(pop[key],f"population.{key}",minimum=0,integer=True)
    if pop["infected"]>pop["humans"]:
        raise ConfigError("population.infected must not exceed population.humans")
    for kind,key,total in (("Human","human_roles",pop["humans"]),("Zombie","zombie_roles",pop["zombies"])):
        for role,count in pop[key].items():
            if role not in ROLES or ROLES[role]["type"]!=kind:
                raise ConfigError(f"population.{key}.{role}: incompatible or unknown role")
            _number(count,f"population.{key}.{role}",minimum=0,integer=True)
        if sum(pop[key].values())>total:
            raise ConfigError(f"population.{key}: role allocations exceed {kind} count")
    from .role_allocation import validate_role_allocation
    validate_role_allocation(config, ConfigError)
    placement=config["placement"]
    if placement["sampler"] not in ("exact","relocation"):
        raise ConfigError("placement.sampler must be exact or relocation")
    if placement["sampler"]=="relocation" and placement.get("allow_approximate") is not True:
        raise ConfigError("placement.allow_approximate must explicitly be true to opt into relocation sampling; finite sweeps do not guarantee joint uniformity (D5)")
    for key in ("max_attempts","max_point_attempts"):
        _number(placement[key],f"placement.{key}",integer=True,positive=True)
    _number(placement["burn_in"],"placement.burn_in",minimum=0,integer=True)
    for key in ("minimum_separation","cross_type_separation"):
        _number(placement[key],f"placement.{key}",minimum=0)
    if placement["cross_type_separation"]<placement["minimum_separation"]:
        raise ConfigError("placement.cross_type_separation must be at least minimum_separation")
    for key,values in config["profiles"].items():
        if key not in TYPE_PROFILES and key not in ROLES:
            raise ConfigError(f"profiles.{key}: unknown type or role")
        _validate_profile(values,f"profiles.{key}")
    all_ids=set(); barrier_ids=set(); length,width=config["world"]["length"],config["world"]["width"]
    for collection in ("barriers","shelters","stockpiles"):
        for index,item in enumerate(config[collection]):
            path=f"{collection}[{index}]"
            identifier=str(item.get("id",""))
            if not identifier or identifier in all_ids:
                raise ConfigError(f"{path}.id: IDs must be nonempty and unique across environment entities")
            item["id"]=identifier; all_ids.add(identifier)
            if collection in ("barriers","shelters"):
                footprint=item.get("footprint" if collection=="barriers" else "interior")
                if not isinstance(footprint,(list,tuple,dict)):
                    raise ConfigError(f"{path}: rectangle is required")
                try:
                    x0,y0,x1,y1=rect(footprint)
                except (KeyError,TypeError,ValueError):
                    raise ConfigError(f"{path}: footprint must be [xmin,ymin,xmax,ymax]") from None
                if not all(math.isfinite(v) for v in (x0,y0,x1,y1)) or not 0<=x0<x1<=length or not 0<=y0<y1<=width:
                    raise ConfigError(f"{path}: rectangle must have positive area and lie inside world bounds")
                if collection=="barriers":
                    barrier_ids.add(identifier); kind=item.get("type","Obstacle"); item["type"]=kind
                    if kind not in ("Obstacle","Gate","Barricade"):
                        raise ConfigError(f"{path}.type: unknown barrier type")
                    if kind in ("Gate","Barricade"):
                        _number(item.get("max_integrity"),f"{path}.max_integrity",positive=True,integer=True)
                        _number(item.get("integrity"),f"{path}.integrity",minimum=0,maximum=item["max_integrity"],integer=True)
                    if kind=="Gate" and (item.get("mode") not in ("OPEN","CLOSED","BREACHED") or (item.get("mode")=="BREACHED") != (item["integrity"]==0)):
                        raise ConfigError(f"{path}: gate mode and integrity disagree")
            else:
                for coordinate,limit in (("x",length),("y",width)):
                    _number(item.get(coordinate),f"{path}.{coordinate}",minimum=0,maximum=limit)
                for resource,quantity in item.get("inventory",item.get("resources",{})).items():
                    if resource not in RESOURCES:
                        raise ConfigError(f"{path}.inventory.{resource}: invalid portable resource")
                    _number(quantity,f"{path}.inventory.{resource}",minimum=0,integer=True)
                if point_blocked(item,config["barriers"]):
                    raise ConfigError(f"{path}: stockpile lies inside a blocking footprint")
    for i,a in enumerate(config["barriers"]):
        for b in config["barriers"][i+1:]:
            if overlap(a,b,strict=True) and not (a["type"]=="Gate" and a["mode"]!="CLOSED" or b["type"]=="Gate" and b["mode"]!="CLOSED"):
                raise ConfigError(f"barriers {a['id']} and {b['id']}: interiors overlap")
    for shelter in config["shelters"]:
        for key in ("walls","gates"):
            if not shelter.get(key) or not set(shelter[key])<=barrier_ids:
                raise ConfigError(f"shelters.{shelter['id']}.{key}: must reference existing barriers")
        by_id={b["id"]:b for b in config["barriers"]}
        if any(by_id[i]["type"]!="Gate" for i in shelter["gates"]) or any(by_id[i]["type"]!="Obstacle" for i in shelter["walls"]):
            raise ConfigError(f"shelters.{shelter['id']}: wall/gate references have incorrect types")
    shelter_ids={s["id"] for s in config["shelters"]}
    for barrier in config["barriers"]:
        if barrier["type"]=="Gate":
            shelter_id=barrier.get("shelter_id")
            if shelter_id not in shelter_ids:
                raise ConfigError(f"barriers.{barrier['id']}.shelter_id: a gate must reference an existing shelter")
            owner=next(s for s in config["shelters"] if s["id"]==shelter_id)
            if barrier["id"] not in owner["gates"]:
                raise ConfigError(f"barriers.{barrier['id']}: shelter and gate references must agree")
    for shelter in config["shelters"]:
        x0,y0,x1,y1=rect(shelter["interior"])
        enclosing=[b for b in config["barriers"] if b["id"] in shelter["walls"]+shelter["gates"]]
        if any(overlap(b,shelter["interior"],strict=True) for b in enclosing):
            raise ConfigError(f"shelters.{shelter['id']}: enclosing barriers cannot occupy the open interior")
        for horizontal,fixed,lower,upper in ((True,y0,x0,x1),(True,y1,x0,x1),(False,x0,y0,y1),(False,x1,y0,y1)):
            intervals=[]
            for barrier in enclosing:
                bx0,by0,bx1,by1=rect(barrier)
                if horizontal and by0<=fixed<=by1:
                    intervals.append((max(lower,bx0),min(upper,bx1)))
                elif not horizontal and bx0<=fixed<=bx1:
                    intervals.append((max(lower,by0),min(upper,by1)))
            cursor=lower
            for left,right in sorted(intervals):
                if right<left:
                    continue
                if left>cursor:
                    break
                cursor=max(cursor,right)
            if cursor<upper:
                raise ConfigError(f"shelters.{shelter['id']}: walls and gates do not enclose every side of the interior")
    if not isinstance(config["allow_intraspecies_combat"],bool):
        raise ConfigError("allow_intraspecies_combat must be boolean")
    if config.get("storage",{}).get("backend","memory") not in ("memory","sqlite"):
        raise ConfigError("storage.backend must be memory or sqlite")
    workers=config.get("execution",{}).get("workers","auto")
    if workers != "auto":
        _number(workers,"execution.workers",integer=True,positive=True)
    execution=config.get("execution",{})
    _number(execution.get("parallel_min_agents",32),"execution.parallel_min_agents",integer=True,positive=True)
    if execution.get("completion_order","native") not in {"native","reverse","seeded_shuffle","shuffle"}:
        raise ConfigError("execution.completion_order must be native, reverse, or seeded_shuffle")
    return config


def resolve_config(config=None):
    if config is None:
        config={}
    if isinstance(config,(str,Path)):
        with Path(config).open("rb") as stream:
            config=tomllib.load(stream)
    if not isinstance(config,dict):
        raise ConfigError("configuration must be a mapping or TOML path")
    def finite_tree(value,path="config"):
        if isinstance(value,float) and not math.isfinite(value):
            raise ConfigError(path+": expected finite number")
        if isinstance(value,dict):
            for key,child in value.items():finite_tree(child,path+"."+str(key))
        elif isinstance(value,(list,tuple)):
            for index,child in enumerate(value):finite_tree(child,f"{path}[{index}]")
    finite_tree(config)
    values=deepcopy(config)
    # Frozen pre-v2 configurations carry a fingerprint but no ordering marker.
    # Reinitializing one retains its historical shuffle input; exact restores
    # bypass configuration resolution entirely and keep their stored state.
    if "fingerprint" in values and "role_assignment_order" not in values:
        values["role_assignment_order"]="legacy_insertion_v1"
    values.pop("fingerprint",None); values.pop("provenance",None)
    semantic=values.pop("semantic",None)
    if semantic is not None:
        if not isinstance(semantic,dict):raise ConfigError("semantic must be a mapping")
        _merge(values,semantic)
    execution=values.get("execution",{})
    if "backend" in execution:values.setdefault("storage",{})["backend"]=execution["backend"]
    if "checkpoint_interval" in execution:values["checkpoint_interval"]=execution["checkpoint_interval"]
    if "backend" in values:values.setdefault("storage",{})["backend"]=values.pop("backend")
    if "workers" in values:
        values.setdefault("execution",{})["workers"]=values.pop("workers")
    baseline=values.get("preset") in ("baseline","baseline_v0.1") or values.get("scenario")=="baseline_v0.1"
    result=_merge(baseline_config() if baseline else deepcopy(DEFAULTS),values)
    # Explicit agent scenarios derive their population rather than inheriting defaults.
    if "agents" in result:
        agents=list(result["agents"].values()) if isinstance(result["agents"],dict) else result["agents"]
        result["agents"]=agents
        counts={"humans":0,"zombies":0,"infected":0,"human_roles":{},"zombie_roles":{}}
        for agent in agents:
            kind=agent.get("type","Human")
            if kind not in ("Human","Zombie"):
                raise ConfigError(f"agents.{agent.get('id','?')}.type: must be Human or Zombie")
            counts["humans" if kind=="Human" else "zombies"]+=1
            if kind=="Human" and (agent.get("infected") or agent.get("infection_episode")):
                counts["infected"]+=1
            role=agent.get("role")
            if role:
                roles=counts["human_roles" if kind=="Human" else "zombie_roles"]
                roles[role]=roles.get(role,0)+1
        result["population"]=counts
    validate_config(result)
    # Use the same modeled numeric values after JSON/TOML round trips, including
    # in observations and durable records; transport number spelling is not a
    # distinct initial condition. Integer-domain validation ran before this.
    result.update(semantic_config(result))
    result["provenance"]=provenance()
    result["provenance"]["role_assignment_order"]=result["role_assignment_order"]
    result["fingerprint"]=hashlib.sha256(json.dumps(semantic_config(result),sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    return result


def validate_connectivity(config):
    """Verify initial exterior access, then reopen each shelter's gate for access."""
    barriers=config["barriers"]; world=config["world"]
    exterior=[s for s in config["stockpiles"] if not any(contains(sh["interior"],s,strict=True) for sh in config["shelters"])]
    candidates=[(0,0),(world["length"],0),(0,world["width"]),(world["length"],world["width"])]
    anchor=next((p for p in candidates if not point_blocked(p,barriers)),None)
    if anchor is None:
        raise ConfigError("geometry: no clear exterior anchor; inspect boundaries and barriers")
    for stock in exterior:
        if not route(anchor,stock,barriers,world):
            raise ConfigError(f"geometry: exterior stockpile {stock['id']} is unreachable")
    for shelter in config["shelters"]:
        opened=deepcopy(barriers)
        for barrier in opened:
            if barrier["id"] in shelter["gates"]:
                barrier["mode"]="OPEN"
        inside=[s for s in config["stockpiles"] if contains(shelter["interior"],s,strict=True)]
        x0,y0,x1,y1=rect(shelter["interior"])
        destinations=inside or [{"id":shelter["id"]+" interior","x":(x0+x1)/2,"y":(y0+y1)/2}]
        for dest in destinations:
            if not route(anchor,dest,opened,world):
                raise ConfigError(f"geometry: opening shelter {shelter['id']} does not make {dest['id']} reachable")


def _place(agents,config):
    placement=config["placement"]; rng=random.Random(str(config["seed"])+":placement:v1")
    world=config["world"]; proposals=0
    def sample(kind):
        nonlocal proposals
        for _ in range(placement["max_point_attempts"]):
            proposals+=1
            p=(rng.random()*world["length"],rng.random()*world["width"])
            if point_blocked(p,config["barriers"]):
                continue
            if kind=="Zombie" and any(contains(s["interior"],p,strict=True) for s in config["shelters"]):
                continue
            return p
        raise PlacementError("Static-region proposal budget exhausted; inspect geometry/population or increase placement.max_point_attempts; no constraints were relaxed")
    def legal(agent,p,placed):
        return all(distance_to(p,other)>=placement["cross_type_separation" if agent["type"]!=other["type"] else "minimum_separation"] for other in placed)
    if placement["sampler"]=="exact":
        for attempt in range(1,placement["max_attempts"]+1):
            placed=[]
            for agent in agents:
                p=sample(agent["type"])
                if not legal(agent,p,placed):
                    break # rejecting the entire configuration retains the exact target distribution
                agent["x"],agent["y"]=p; placed.append(agent)
            else:
                return {"sampler":"exact_joint_rejection_v1","approximate":False,"attempts":attempt,"proposals":proposals}
        raise PlacementError(f"Exact joint placement exhausted {placement['max_attempts']} whole-configuration attempts for {len(agents)} agents. This does not prove infeasibility. Increase the budget, use a smaller scenario, or explicitly opt into placement.sampler='relocation' and placement.allow_approximate=true (D5). No fallback occurred.")
    # Explicit opt-in; randomized sequential initialization followed by conditional relocation.
    placed=[]; ordering=list(agents); rng.shuffle(ordering)
    for agent in ordering:
        for _ in range(placement["max_point_attempts"]):
            p=sample(agent["type"])
            if legal(agent,p,placed):
                agent["x"],agent["y"]=p; placed.append(agent); break
        else:
            raise PlacementError("Relocation initialization exhausted the point budget; increase space/budget or reduce density. Population and constraints were retained.")
    accepted=0
    for _ in range(placement["burn_in"]):
        rng.shuffle(ordering)
        for agent in ordering:
            p=sample(agent["type"])
            if legal(agent,p,(other for other in agents if other is not agent)):
                agent["x"],agent["y"]=p; accepted+=1
    return {"sampler":"conditional_relocation_v1","approximate":True,"explicit_opt_in":True,"proposals":proposals,"burn_in":placement["burn_in"],"accepted_relocations":accepted,"relocation_acceptance_rate":accepted/max(1,len(agents)*placement["burn_in"]),"mixing_guaranteed":False}


def initialize_world(config=None):
    config=resolve_config(config)
    if config.get("state_import"):
        from .initial_state import initialize_explicit_world
        return initialize_explicit_world(config)
    validate_connectivity(config)
    rng=random.Random(str(config["seed"])+":roles:v1")
    agents=[]
    if "agents" in config:
        seen=set()
        for index,spec in enumerate(config["agents"]):
            spec=deepcopy(spec); identifier=str(spec.pop("id",index+1)); kind=spec.pop("type","Human"); role=spec.pop("role",None)
            if not identifier or identifier in seen:
                raise ConfigError(f"agents[{index}].id: IDs must be nonempty and unique")
            seen.add(identifier)
            if any(key in spec for key in ("status","speed","sense_r","action_state","infection_progress","damage_resistance","infection_resistance_effective")):
                raise ConfigError(f"agents.{identifier}: derived state fields cannot be independently configured")
            if kind=="Zombie" and spec.get("infection_episode"):
                raise ConfigError(f"agents.{identifier}: Zombie states cannot have active Human infection episodes")
            for resource in spec.get("inventory",{}):
                if resource not in RESOURCES:
                    raise ConfigError(f"agents.{identifier}.inventory.{resource}: invalid portable resource")
            model=config.get("human_model" if kind=="Human" else "zombie_model")
            if "model_assignment" not in spec and model is not None:
                spec["model_assignment"]={"model_id":model}
            agent=make_agent(identifier,kind,role,**spec)
            agents.append(agent)
        sampling={"sampler":"explicit_coordinates","approximate":False,"proposals":0}
    else:
        for kind,count_key,roles_key in (("Human","humans","human_roles"),("Zombie","zombies","zombie_roles")):
            allocations=config["population"][roles_key].items()
            if config["role_assignment_order"]=="canonical_v2":
                allocations=sorted(allocations)
            roles=[role for role,count in allocations for _ in range(count)]
            roles += [None]*(config["population"][count_key]-len(roles)); rng.shuffle(roles)
            for role in roles:
                assignment = config.get("human_model" if kind == "Human" else "zombie_model")
                options = {"model_assignment": {"model_id": assignment}} if assignment else {}
                agents.append(make_agent(len(agents)+1,kind,role,**options))
        sampling=_place(agents,config)
    episodes={}; infected_ids=set(rng.sample([a["id"] for a in agents if a["type"]=="Human"],config["population"]["infected"])) if "agents" not in config else {a["id"] for a in agents if a.get("infected") or a.get("infection_episode")}
    for agent in agents:
        identifier=agent["id"]; path=f"agents.{identifier}"
        agent["type_profile"]=deepcopy(config["profiles"].get(agent["type"],{}))
        agent["role_profile"]=deepcopy(config["profiles"].get(agent.get("role"),{}))
        configured_profile=agent.get("profile",{})
        _validate_profile(configured_profile,path+".profile"); agent["profile"]=configured_profile
        for key in ("life","stamina"):
            _number(agent[key],path+"."+key,minimum=0,maximum=100,integer=key=="life")
        if agent["life"]==0:
            raise ConfigError(path+".life: initial agents must be living; deaths are recorded transitions")
        for key in ("x","y"):
            _number(agent[key],path+"."+key,minimum=0,maximum=config["world"]["length" if key=="x" else "width"])
        if point_blocked(agent,config["barriers"]):
            raise ConfigError(path+": initial position is inside blocking geometry")
        if agent["type"]=="Zombie" and any(contains(s["interior"],agent,strict=True) for s in config["shelters"]):
            raise ConfigError(path+": initial zombies are excluded from shelter interiors")
        if agent.get("role") and ROLES[agent["role"]]["type"]!=agent["type"]:
            raise ConfigError(path+".role: incompatible biological type")
        if not agent.get("model_assignment") or not isinstance(agent["model_assignment"],dict) or not agent["model_assignment"].get("model_id"):
            raise ConfigError(path+".model_assignment: living agents require an identified decision model")
        if agent["type"]=="Zombie" and any(key in agent for key in ("hunger","inventory","carry_capacity","starvation_started_at","next_starvation_damage_at")):
            raise ConfigError(path+": Zombie states cannot contain Human-only fields")
        if agent.get("role")=="SPITTER":
            _number(agent.get("spit_charges"),path+".spit_charges",minimum=0,maximum=profile(agent)["max_spit_charges"],integer=True)
            if agent.get("reserved_charges",0):
                raise ConfigError(path+": initial Spitter charges cannot be reserved")
        if agent["type"]=="Human":
            if "carry_capacity" in configured_profile or "carry_capacity" in agent["type_profile"] or "carry_capacity" in agent["role_profile"]:
                values=deepcopy(agent); values.pop("carry_capacity",None)
                agent["carry_capacity"]=profile(values)["carry_capacity"]
            _number(agent["hunger"],path+".hunger",minimum=0,maximum=100)
            _number(agent["carry_capacity"],path+".carry_capacity",minimum=0,integer=True)
            for resource in RESOURCES:
                _number(agent["inventory"].get(resource,0),path+".inventory."+resource,minimum=0,integer=True)
                _number(agent["reserved"].get(resource,0),path+".reserved."+resource,minimum=0,maximum=agent["inventory"].get(resource,0),integer=True)
            if sum(agent["inventory"].values())>agent["carry_capacity"]:
                raise ConfigError(path+".inventory: mass exceeds carry_capacity")
            if agent["hunger"]==100:
                agent["starvation_started_at"]="0"; agent["next_starvation_damage_at"]="10"
        if agent.get("active_action") or agent.get("effects") or agent.get("cooldowns") or any(agent.get("reserved",{}).values()):
            raise ConfigError(path+": initial agents cannot have actions, effects, cooldowns or reservations")
        if identifier in infected_ids:
            episode_id=f"episode:initial:{identifier}"
            agent["infection_episode"]=episode_id
            incubation=str(Fraction(str(config["incubation_duration"])))
            episodes[episode_id]={"id":episode_id,"agent_id":identifier,"source_kind":"INITIAL_CONDITION","source_agent_id":None,"source_event_id":"initialization","onset_at":"0","onset_revision":0,"incubation_duration":incubation,"conversion_due_at":incubation,"outcome":None,"ended_at":None,"end_revision":None}
        agent.pop("infected",None)
    if "agents" in config and max(config["placement"]["minimum_separation"], config["placement"]["cross_type_separation"]) > 0:
        for i,a in enumerate(agents):
            for b in agents[i+1:]:
                minimum=config["placement"]["cross_type_separation" if a["type"]!=b["type"] else "minimum_separation"]
                if minimum > 0 and distance_to(a,b)<minimum:
                    raise ConfigError(f"agents.{a['id']} and agents.{b['id']}: initial separation is below {minimum} m; scenario overrides must explicitly declare alternative distances")
    def items(collection):
        return {str(i["id"]):deepcopy(i) for i in config[collection]}
    stockpiles=items("stockpiles")
    for stock in stockpiles.values():
        stock["inventory"]={r:stock.get("inventory",stock.get("resources",{})).get(r,0) for r in RESOURCES}
        stock["reserved"]={r:0 for r in RESOURCES}
    return {"time":"0","revision":0,"world":deepcopy(config["world"]),"agents":{a["id"]:a for a in agents},"barriers":items("barriers"),"shelters":items("shelters"),"stockpiles":stockpiles,"remains":{},"episodes":episodes,"signals":{},"reservations":{},"initialization":sampling,"scenario_fingerprint":config["fingerprint"],"source_provenance":config["provenance"]}
