"""All 29 ontology action contracts, admission, reservations and resolution.

Reducers mutate the coordinator's staged state; the outer admission/completion
commits all consequences together. No policy is permitted to bypass this layer.
"""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import json
import math

from .domain import RESOURCES, capabilities, profile, status
from .geometry import blocking, contains, distance_to, nearest_point, overlap, point, point_blocked, rect, segment_clear, segment_intersects
from .registry import ACTIONS

ATTACKS={"melee","power_strike","claw","bite","spit"}
AGENT_ACTIONS=ATTACKS|{"first_aid","transfer","treat_infection","prophylaxis","mark_target"}
BARRIER_ACTIONS={"open_gate","close_gate","repair_barrier","smash","demolish"}
SELF_ACTIONS={"move","wait","rest","signal","drop","eat","guard","recon","build_barricade","rally","dash","scream"}


class ActionError(ValueError):
    pass


def _clock(value):
    if isinstance(value,bool):
        raise ActionError("Time must be a finite nonnegative number")
    try:
        result=Fraction(str(value))
    except (ValueError,ZeroDivisionError,TypeError):
        raise ActionError("Time must be a finite nonnegative number") from None
    if result<0:
        raise ActionError("Time must be nonnegative")
    return result


def _stamp(value):
    value=Fraction(value)
    return str(value.numerator) if value.denominator==1 else str(value)


def _number(value,label,minimum=None,maximum=None,integer=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ActionError(label+" must be finite")
    if integer and not isinstance(value,int):
        raise ActionError(label+" must be an integer")
    if minimum is not None and value<minimum or maximum is not None and value>maximum:
        raise ActionError(label+" is outside its permitted range")
    return value


class ActionSystemMixin:
    def _finalize_action_evidence(self):
        """Capture the final atomic after-state, after all coupled consequences."""
        for collection,identifier in tuple(self._dirty):
            if collection!="occurrences":continue
            occurrence=self.occurrences.get(identifier)
            if not occurrence or occurrence.get("result")=="IN_PROGRESS" or occurrence.get("resolved_at")!=_stamp(self.time):continue
            occurrence["actor_after_end"]=self._capture_action_agent(occurrence["actor"],after=True)
            occurrence["target_after_end"]=self._capture_action_agent(occurrence.get("target"),after=True)

    def _capture_action_agent(self,identifier,after=False,admission=False):
        if identifier is None or str(identifier) not in self.state["agents"]:
            return None
        if admission and getattr(self,"_batching",False):
            cached=getattr(self,"_admission_boundary_agents",{}).get(str(identifier))
            if cached is not None:
                return deepcopy(cached)
        agent=deepcopy(self._view_agent(str(identifier)))
        agent["at_time"]=_stamp(self.time)
        agent["revision"]=self.revision+int(after)
        return agent

    def _perceived(self,actor,target,barrier=False):
        if str(actor["id"])==str(target.get("id")):
            return True
        destination=nearest_point(actor,target)
        reach=profile(actor,_stamp(self.time))["sense_r"]
        return distance_to(actor,target)<=reach and segment_clear(point(actor),destination,self.state["barriers"],ignore_id=target.get("id") if barrier else None)

    def _target(self,actor,action,identifier,reach):
        if action in AGENT_ACTIONS:
            if identifier is None:
                if action in {"first_aid","treat_infection","prophylaxis"}:
                    identifier=actor["id"]
                else:
                    raise ActionError("An agent target is required")
            if str(identifier) not in self.state["agents"]:
                raise ActionError("Agent target unavailable")
            target=self._view_agent(str(identifier))
            if target["life"]<=0:
                raise ActionError("Target must be alive")
            if not self._perceived(actor,target):
                raise ActionError("Target is not currently perceived")
            if reach is not None and distance_to(actor,target)>reach:
                raise ActionError("Target is out of reach")
            if action in ATTACKS:
                if str(target["id"])==str(actor["id"]):
                    raise ActionError("Self attacks are forbidden")
                if target["type"]==actor["type"] and not self.config.get("allow_intraspecies_combat",False):
                    raise ActionError("Same-type combat is disabled")
            elif action in {"first_aid","transfer","treat_infection","prophylaxis"}:
                if target["type"]!="Human":
                    raise ActionError("Target must be a living Human")
                if action=="transfer" and str(target["id"])==str(actor["id"]):
                    raise ActionError("Transfer requires another Human")
            return str(identifier),target,"agents"
        if action in BARRIER_ACTIONS:
            if str(identifier) not in self.state["barriers"]:
                raise ActionError("Barrier target unavailable")
            target=self.state["barriers"][str(identifier)]
            if not self._perceived(actor,target,True) or distance_to(actor,target)>reach:
                raise ActionError("Barrier is not currently reachable and perceived")
            return str(identifier),target,"barriers"
        if action in {"pickup","feed"}:
            collection="stockpiles" if action=="pickup" else "remains"
            if str(identifier) not in self.state[collection]:
                raise ActionError("Resource target unavailable")
            target=self.state[collection][str(identifier)]
            if not self._perceived(actor,target) or distance_to(actor,target)>reach:
                raise ActionError("Resource is not currently reachable and perceived")
            return str(identifier),target,collection
        if identifier is not None and str(identifier)!=str(actor["id"]):
            raise ActionError("This action has no other entity target")
        return None,actor,"agents"

    def _path_parameters(self,actor,action,parameters,duration,p):
        path=parameters.get("path")
        if not isinstance(path,list) or len(path)<2:
            raise ActionError("Movement needs at least two timed path points")
        cleaned=[]
        for index,item in enumerate(path):
            if not isinstance(item,dict) or not {"x","y","offset"}<=set(item):
                raise ActionError("Each path point needs x, y and offset")
            x=_number(item["x"],"path.x",0,self.state["world"]["length"])
            y=_number(item["y"],"path.y",0,self.state["world"]["width"])
            offset=_clock(item["offset"])
            if point_blocked((x,y),self.state["barriers"]):
                raise ActionError("Movement point is blocked")
            cleaned.append({"x":float(x),"y":float(y),"offset":_stamp(offset)})
        if _clock(cleaned[0]["offset"])!=0 or distance_to(actor,cleaned[0])>1e-9:
            raise ActionError("Movement must begin at the current position at offset zero")
        if _clock(cleaned[-1]["offset"])!=duration:
            raise ActionError("Last path offset must equal the action duration")
        cleaned[0]["x"],cleaned[0]["y"]=float(actor["x"]),float(actor["y"])
        speed=p["base_speed"]*p.get("dash_multiplier",1.5) if action=="dash" else p["speed"]
        distance=0.
        for a,b in zip(cleaned,cleaned[1:]):
            dt=_clock(b["offset"])-_clock(a["offset"])
            if dt<=0:
                raise ActionError("Path offsets must strictly increase")
            length=distance_to(a,b)
            if length>speed*float(dt)+1e-9:
                raise ActionError("A path segment exceeds the instantaneous speed limit")
            if not segment_clear(point(a),point(b),self.state["barriers"]):
                raise ActionError("A path segment crosses blocking geometry")
            distance+=length
        parameters["path"]=cleaned
        return distance

    def _gate_clear(self,gate):
        if any(a["life"]>0 and contains(gate,self._view_agent(a["id"])) for a in self.state["agents"].values()):
            return False
        return not any(b.get("type")=="Barricade" and b.get("integrity",0)>0 and overlap(gate,b) for b in self.state["barriers"].values())

    def _construction_footprint(self,actor,parameters):
        center=parameters.get("center")
        if isinstance(center,(list,tuple)) and len(center)==2:
            center={"x":center[0],"y":center[1]}
        if not isinstance(center,dict) or "x" not in center or "y" not in center:
            raise ActionError("Barricade center requires x and y")
        cx=_number(center["x"],"center.x");cy=_number(center["y"],"center.y")
        length=_number(parameters.get("length"),"barricade length",2,8)
        orientation=parameters.get("orientation")
        if orientation not in ("x","y"):
            raise ActionError("Barricade orientation must be x or y")
        if distance_to(actor,(cx,cy))>2:
            raise ActionError("Barricade center is out of reach")
        footprint=[cx-length/2,cy-.5,cx+length/2,cy+.5] if orientation=="x" else [cx-.5,cy-length/2,cx+.5,cy+length/2]
        x0,y0,x1,y1=footprint; world=self.state["world"]
        if not 0<=x0<x1<=world["length"] or not 0<=y0<y1<=world["width"]:
            raise ActionError("Entire barricade must lie in world bounds")
        for barrier in self.state["barriers"].values():
            intact=barrier.get("type")!="Barricade" or barrier.get("integrity",0)>0
            if not intact:
                continue
            if overlap(footprint,barrier,strict=True) and not (barrier.get("type")=="Gate" and barrier.get("mode") in ("OPEN","BREACHED")):
                raise ActionError("Barricade interior overlaps an intact barrier")
        for agent in self.state["agents"].values():
            if agent["life"]>0 and contains(footprint,self._view_agent(agent["id"])):
                raise ActionError("Barricade footprint is occupied by a living agent")
        for collection,key in (("stockpiles","inventory"),("remains","biomass")):
            for entity in self.state[collection].values():
                value=entity.get(key,{}) if key=="inventory" else entity.get(key,0)
                nonempty=sum(value.values())>0 if isinstance(value,dict) else value>0
                if nonempty and contains(footprint,entity):
                    raise ActionError("Barricade footprint contains a nonempty resource")
        # A blocker anywhere in the convex hull of observer and footprint can
        # hide its interior even when all four corner rays are clear. Strict SAT
        # preserves legal shared wall edges while excluding such occlusion.
        vertices=sorted(set([point(actor),(x0,y0),(x0,y1),(x1,y0),(x1,y1)]))
        def turn(a,b,c):
            return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
        lower=[]
        for vertex in vertices:
            while len(lower)>1 and turn(lower[-2],lower[-1],vertex)<=0:lower.pop()
            lower.append(vertex)
        upper=[]
        for vertex in reversed(vertices):
            while len(upper)>1 and turn(upper[-2],upper[-1],vertex)<=0:upper.pop()
            upper.append(vertex)
        hull=lower[:-1]+upper[:-1]
        axes=[(1.,0.),(0.,1.)]+[(b[1]-a[1],a[0]-b[0]) for a,b in zip(hull,hull[1:]+hull[:1])]
        for barrier in self.state["barriers"].values():
            if not blocking(barrier):continue
            bx0,by0,bx1,by1=rect(barrier)
            corners=[(bx0,by0),(bx0,by1),(bx1,by0),(bx1,by1)]
            intersects=True
            for nx,ny in axes:
                av=[nx*x+ny*y for x,y in hull];bv=[nx*x+ny*y for x,y in corners]
                if max(av)<=min(bv) or max(bv)<=min(av):
                    intersects=False;break
            if intersects:
                raise ActionError("Part of the proposed footprint is occluded")
        # Corner rays also reject tangent contacts and sensing-range violations.
        # and every corner ray is clear. Shared wall-edge endpoints may be seen.
        sense=profile(actor,_stamp(self.time))["sense_r"]
        for corner in ((x0,y0),(x0,y1),(x1,y0),(x1,y1)):
            if distance_to(actor,corner)>sense:
                raise ActionError("Entire barricade footprint must be visible")
            endpoint=(math.nextafter(corner[0],float(actor["x"])),math.nextafter(corner[1],float(actor["y"])))
            if not segment_clear(point(actor),endpoint,self.state["barriers"]):
                raise ActionError("Barricade footprint is occluded")
        parameters.update(center={"x":cx,"y":cy},length=length,orientation=orientation,footprint=footprint)
        return footprint

    def _knowledge_payload(self,actor,action,parameters):
        kind=parameters.get("kind","WARNING")
        if action=="signal" and kind not in ("WARNING","REQUEST_HELP","RESOURCE_REPORT","DIRECTION"):
            raise ActionError("Unknown signal kind")
        payload=deepcopy(parameters.get("payload",{}))
        if not isinstance(payload,dict) or len(json.dumps(payload,allow_nan=False))>2048:
            raise ActionError("Communication payload must be a bounded mapping")
        allowed={"entity_id","position","resource","resource_type","quantity","observed_at","type"}
        if set(payload)-allowed:
            raise ActionError("Communication payload contains unsupported fields")
        if not payload:
            parameters["payload"]={}
            return
        if "observed_at" not in payload:
            raise ActionError("Communication requires the original observation time")
        observed=_clock(payload["observed_at"])
        if observed>self.time:
            raise ActionError("Communication cannot cite a future observation")
        resource=payload.get("resource",payload.get("resource_type"))
        if resource is not None and resource not in RESOURCES:
            raise ActionError("Communication resource type is invalid")
        if "quantity" in payload:
            _number(payload["quantity"],"reported quantity",0,integer=True)
        if "position" in payload:
            pos=payload["position"]
            if not isinstance(pos,dict) or not {"x","y"}<=set(pos):
                raise ActionError("Payload position needs x and y")
            _number(pos["x"],"payload.x",0,self.state["world"]["length"])
            _number(pos["y"],"payload.y",0,self.state["world"]["width"])
        identifier=str(payload["entity_id"]) if payload.get("entity_id") is not None else None
        candidates=[]
        if observed==self.time:
            candidates.append(actor)
            candidates.extend(self._view_agent(aid) for aid in self.state["agents"] if aid!=actor["id"] and self._perceived(actor,self._view_agent(aid)))
            for collection in ("stockpiles","remains"):
                candidates.extend(entity for entity in self.state[collection].values() if self._perceived(actor,entity))
        # Trust recorded inputs, not arbitrary claims in model-returned memory.
        for decision in getattr(self,"decisions",[]):
            if str(decision.get("actor"))!=str(actor["id"]):
                continue
            observation=decision.get("observation",{})
            if _clock(observation.get("time",0))!=observed:
                continue
            candidates.append(observation.get("self_state",{}))
            local=observation.get("local_agents",{})
            candidates.extend(local.values() if isinstance(local,dict) else local)
            for collection in ("stockpiles","remains"):
                local=observation.get("local_environment",{}).get(collection,{})
                candidates.extend(local.values() if isinstance(local,dict) else local)
        matching=[entity for entity in candidates if identifier is None or str(entity.get("id"))==identifier]
        if "position" in payload:
            matching=[entity for entity in matching if "x" in entity and distance_to(entity,payload["position"])<=1e-9]
        if identifier is None and "position" in payload and observed==self.time and self._perceived(actor,payload["position"]):
            matching.append(payload["position"])
        # A received dated report can be repeated without claiming fresh sight.
        for signal in self.state.get("signals",{}).values():
            report=signal.get("payload",{})
            if str(actor["id"]) in map(str,signal.get("recipients",[])) and actor["type"]==signal.get("sender_type_at_emission"):
                if report.get("observed_at") is not None and _clock(report["observed_at"])==observed and (identifier is None or str(report.get("entity_id"))==identifier):
                    if "position" not in payload or report.get("position")==payload["position"]:
                        matching.append(report)
        if not matching:
            raise ActionError("Payload lacks an authentic local observation or received report")
        if action=="signal" and kind=="RESOURCE_REPORT" and resource is not None and "quantity" in payload:
            if not any(entity.get("inventory",{}).get(resource)==payload["quantity"] or entity.get("quantity")==payload["quantity"] and entity.get("resource",entity.get("resource_type"))==resource for entity in matching):
                raise ActionError("Reported resource quantity differs from the dated observation")
        payload["observed_at"]=_stamp(observed)
        parameters["payload"]=payload

    def _action_plan(self,actor,action,target_id,parameters,completion=False,occurrence=None):
        p=profile(actor,_stamp(self.time));definition=ACTIONS[action]
        parameters=deepcopy(parameters)
        duration=_clock(parameters.get("duration",p.get("dash_duration",definition["duration"]) if action=="dash" else p.get("treatment_duration",definition["duration"]) if action=="treat_infection" else definition["duration"]))
        if action in ("move","wait","rest"):
            if not _clock(definition["duration_min"])<=duration<=_clock(definition["duration_max"]):
                raise ActionError("Action duration is outside the catalog bounds")
        else:
            expected=_clock(p.get("dash_duration",1)) if action=="dash" else _clock(p.get("treatment_duration",4)) if action=="treat_infection" else _clock(definition["duration"])
            if duration!=expected:
                raise ActionError("Action duration must match its resolved contract")
        parameters["duration"]=_stamp(duration)
        reach=p.get("spit_range",12) if action=="spit" else definition.get("reach")
        target_id,target,collection=self._target(actor,action,target_id,reach)
        reservations=[]
        def reserve(collection,holder,kind,resource,quantity):
            if completion:
                return
            obj=self.state[collection][str(holder)]
            if kind=="inventory":
                available=obj.get("inventory",{}).get(resource,0)-obj.get("reserved",{}).get(resource,0)
            elif kind=="biomass":
                available=obj.get("biomass",0)-obj.get("reserved_biomass",0)
            else:
                available=obj.get("spit_charges",0)-obj.get("reserved_charges",0)
            if available<quantity:
                raise ActionError("Insufficient unreserved resource")
            reservations.append({"collection":collection,"holder":str(holder),"kind":kind,"resource":resource,"quantity":quantity})
        travel_cost=0.
        if action in ("move","dash") and not completion:
            travel_cost=self._path_parameters(actor,action,parameters,duration,p)*p["movement_cost"]
        if action in ("pickup","drop","transfer"):
            resource=parameters.get("resource",parameters.get("resource_type"))
            if resource not in RESOURCES:
                raise ActionError("A portable resource type is required")
            quantity=_number(parameters.get("quantity"),"resource quantity",1,integer=True)
            parameters["resource"]=resource
            recipient=actor if action=="pickup" else target if action=="transfer" else None
            if recipient and sum(recipient.get("inventory",{}).values())+quantity>recipient["carry_capacity"]:
                raise ActionError("Recipient cannot carry the entire quantity")
            reserve("stockpiles" if action=="pickup" else "agents",target_id if action=="pickup" else actor["id"],"inventory",resource,quantity)
        elif action=="eat":
            if actor.get("hunger",0)<=0:
                raise ActionError("Eating requires positive hunger")
            reserve("agents",actor["id"],"inventory","FOOD",1)
        elif action in ("first_aid","treat_infection","prophylaxis"):
            if action=="first_aid" and target["life"]>=100:
                raise ActionError("First aid requires an injured target")
            if action=="treat_infection":
                episode=self.state["episodes"].get(target.get("infection_episode"))
                if not episode or self.time>=_clock(episode["conversion_due_at"]):
                    raise ActionError("Treatment requires a living infected Human before its deadline")
            if action=="prophylaxis" and target.get("infection_episode"):
                raise ActionError("Prophylaxis requires an uninfected Human")
            reserve("agents",actor["id"],"inventory","MEDICAL_SUPPLY",int(p.get("treatment_cost",1)) if action=="treat_infection" else 1)
        elif action=="feed":
            if actor["life"]>=100 and actor["stamina"]>=100:
                raise ActionError("Feeding requires lost life or stamina")
            reserve("remains",target_id,"biomass","BIOMASS",1)
        elif action=="spit":
            reserve("agents",actor["id"],"charge","SPIT_CHARGE",1)
        elif action in BARRIER_ACTIONS:
            kind=target.get("type")
            if action=="open_gate" and (kind!="Gate" or target.get("mode")!="CLOSED"):
                raise ActionError("Opening requires a CLOSED gate")
            if action=="close_gate" and (kind!="Gate" or target.get("mode")!="OPEN" or not self._gate_clear(target)):
                raise ActionError("Closing requires an unoccupied OPEN gate without an overlapping barricade")
            if action in ("smash","demolish") and not (kind=="Gate" and target.get("mode")=="CLOSED" or kind=="Barricade" and target.get("integrity",0)>0):
                raise ActionError("Barrier attack requires a CLOSED gate or intact barricade")
            if action=="repair_barrier":
                if kind not in ("Gate","Barricade") or target.get("integrity",0)>=target.get("max_integrity",0) or kind=="Barricade" and target.get("integrity",0)<=0:
                    raise ActionError("Repair requires a damaged gate or intact damaged barricade")
                if kind=="Gate" and target.get("mode")=="BREACHED" and not self._gate_clear(target):
                    raise ActionError("Breached gate restoration requires an unoccupied footprint")
                reserve("agents",actor["id"],"inventory","MATERIAL",int(p.get("repair_material_cost",1)))
        elif action=="build_barricade":
            self._construction_footprint(actor,parameters)
            reserve("agents",actor["id"],"inventory","MATERIAL",int(p.get("build_material_cost",2)))
        elif action in ("signal","scream") and not completion:
            self._knowledge_payload(actor,action,parameters)
        if completion and occurrence is not None:
            for reservation_id in occurrence.get("reservations",[]):
                reservation=self.state["reservations"].get(reservation_id)
                if reservation is None or reservation.get("occurrence_id")!=occurrence["id"]:
                    raise ActionError("Occurrence no longer owns its resource reservation")
                obj=self.state[reservation["collection"]].get(reservation["holder"])
                q=reservation["quantity"]
                if obj is None:
                    raise ActionError("Reservation holder disappeared")
                if reservation["kind"]=="inventory" and (obj.get("inventory",{}).get(reservation["resource"],0)<q or obj.get("reserved",{}).get(reservation["resource"],0)<q):
                    raise ActionError("Reserved inventory is no longer available")
                if reservation["kind"]=="biomass" and (obj.get("biomass",0)<q or obj.get("reserved_biomass",0)<q):
                    raise ActionError("Reserved biomass is no longer available")
                if reservation["kind"]=="charge" and (obj.get("spit_charges",0)<q or obj.get("reserved_charges",0)<q):
                    raise ActionError("Reserved charge is no longer available")
        return {"parameters":parameters,"target":target_id,"duration":duration,"cost":float(definition["cost"]),"cooldown":float(definition["cooldown"]),"reservations":reservations,"travel_cost":travel_cost,"target_collection":collection}

    def submit_intents(self,intents):
        if isinstance(intents,dict):
            intents=[intents]
        if not isinstance(intents,(list,tuple)):
            raise ValueError("Intents must be a mapping or a batch of mappings")
        if getattr(self,"_batching",False):
            token=(_stamp(self.time),self.revision)
            if getattr(self,"_admission_boundary_token",None)!=token:
                self._admission_boundary_token=token
                self._admission_boundary_agents={};self._admission_boundary_entities={}
            # Admission arbitration stages several changes into one revision.
            # Boundary evidence must describe the committed pre-batch state,
            # while reservation checks below still see all staged winners.
            for intent in intents:
                if not isinstance(intent,dict):continue
                parameters=intent.get("parameters",{})
                target=intent.get("target",parameters.get("target") if isinstance(parameters,dict) else None)
                for identifier in (intent.get("actor",intent.get("agent_id")),target):
                    identifier=str(identifier)
                    if identifier in self.state["agents"] and identifier not in self._admission_boundary_agents:
                        self._admission_boundary_agents[identifier]=self._capture_action_agent(identifier)
                if target is not None:
                    target=str(target)
                    for collection in ("barriers","stockpiles","remains"):
                        key=(collection,target)
                        if target in self.state[collection] and key not in self._admission_boundary_entities:
                            self._admission_boundary_entities[key]=deepcopy(self.state[collection][target])
        prepared=[];results={}
        for index,intent in enumerate(intents):
            intent=deepcopy(intent) if isinstance(intent,dict) else {}
            intent.setdefault("id",self._id("intent"))
            identifier=str(intent["id"]);actor=str(intent.get("actor",intent.get("agent_id","")))
            action=intent.get("action",intent.get("name"));parameters=intent.get("parameters",{})
            key=json.dumps([actor,action,intent.get("target"),parameters],sort_keys=True,default=str)
            prepared.append((self._random("admission",_stamp(self.time)+":"+key),actor,identifier,index,intent))
        for priority,aid,identifier,index,intent in sorted(prepared,key=lambda row:(row[0],row[1],row[2])):
            action=intent.get("action",intent.get("name"));audit=None;admitting=False
            try:
                if identifier in self.intents:
                    raise ActionError("Intent identity was already processed")
                if aid not in self.state["agents"]:
                    raise ActionError("Unknown actor")
                actor=self._view_agent(aid)
                if actor["life"]<=0 or actor.get("active_action"):
                    raise ActionError("Actor must be living and idle")
                if action not in ACTIONS or action not in capabilities(actor):
                    raise ActionError("Action is not granted by the actor's type and role")
                if self.time<_clock(actor.get("cooldowns",{}).get(action,0)):
                    raise ActionError("Action is still on cooldown")
                parameters=intent.get("parameters",{})
                if not isinstance(parameters,dict):
                    raise ActionError("Action parameters must be a mapping")
                if intent.get("proposed_at") is not None and _clock(intent["proposed_at"])!=self.time:
                    raise ActionError("Intent proposal time differs from admission time")
                plan=self._action_plan(actor,action,intent.get("target",parameters.get("target")),parameters)
                if float(actor["stamina"])+1e-9<plan["cost"]+plan["travel_cost"]:
                    raise ActionError("Insufficient stamina for the complete action plan")
                occurrence_id=self._id("action")
                occurrence={"id":occurrence_id,"intent_id":identifier,"actor":aid,"action":action,"target":plan["target"],"target_collection":plan["target_collection"],"parameters":plan["parameters"],"start_at":_stamp(self.time),"planned_end":_stamp(self.time+plan["duration"]),"duration":_stamp(plan["duration"]),"cost":plan["cost"],"cooldown":plan["cooldown"],"result":"IN_PROGRESS","reservations":[],"admission_priority":priority,"actor_start":self._capture_action_agent(aid,admission=True),"target_start":self._capture_action_agent(plan["target"],admission=True)}
                admitting=True
                if plan["target_collection"] in ("barriers","stockpiles","remains"):
                    key=(plan["target_collection"],plan["target"])
                    cached=getattr(self,"_admission_boundary_entities",{}).get(key) if getattr(self,"_batching",False) else None
                    occurrence["environment_start"]=deepcopy(cached if cached is not None else self.state[plan["target_collection"]][plan["target"]])
                actual=self._touch(aid);actual["stamina"]=max(0.,float(actual["stamina"])-plan["cost"])
                actual["active_action"]=occurrence_id
                if action in ("move","dash"):
                    actual["_travelled"]=0.0
                for record in plan["reservations"]:
                    rid=self._id("reservation");record.update(id=rid,occurrence_id=occurrence_id,actor=aid)
                    holder=self.state[record["collection"]][record["holder"]]
                    if record["kind"]=="inventory":
                        holder.setdefault("reserved",{})[record["resource"]]=holder.get("reserved",{}).get(record["resource"],0)+record["quantity"]
                    else:
                        key="reserved_biomass" if record["kind"]=="biomass" else "reserved_charges"
                        holder[key]=holder.get(key,0)+record["quantity"]
                    self.state["reservations"][rid]=record;occurrence["reservations"].append(rid)
                    self._mark(record["collection"],record["holder"]);self._mark("reservations",rid)
                self.occurrences[occurrence_id]=occurrence;self._mark("occurrences",occurrence_id)
                occurrence["actor_after_start"]=self._capture_action_agent(aid,after=True)
                outcome={"id":identifier,"actor":aid,"status":"ADMITTED","occurrence_id":occurrence_id}
                self.intents[identifier]={**deepcopy(intent),"id":identifier,"actor":aid,"action":action,"parameters":plan["parameters"],"outcome":outcome,"proposed_at":_stamp(self.time)}
                self._mark("intents",identifier)
                self._schedule(self.time+plan["duration"],5,"complete",aid,occurrence=occurrence_id)
                self._commit("action_started",actor=aid,target=plan["target"],action=action,occurrence=occurrence_id,intent_id=identifier,arbitration_priority=priority)
                results[index]=outcome
            except (ActionError,KeyError,ValueError,TypeError,OverflowError) as exc:
                if admitting:
                    raise
                audit=str(exc)
                outcome={"id":identifier,"actor":aid,"status":"REJECTED","reason":"PRECONDITION_FAILED"}
                if identifier not in self.intents:
                    self.intents[identifier]={**deepcopy(intent),"id":identifier,"actor":aid,"outcome":outcome,"audit_reason":audit,"proposed_at":_stamp(self.time)}
                    self._mark("intents",identifier)
                self._commit("intent_rejected",actor=aid,intent_id=identifier,action=action,reason="PRECONDITION_FAILED",audit_reason=audit)
                results[index]=outcome
        return [results[index] for index in range(len(intents))]

    def _release(self,occurrence,consume=False):
        records=[]
        for reservation_id in list(occurrence.get("reservations",[])):
            record=self.state["reservations"].get(reservation_id)
            if record is None:
                continue
            if record.get("occurrence_id")!=occurrence["id"]:
                raise RuntimeError("Reservation belongs to a different occurrence")
            holder=self.state[record["collection"]].get(record["holder"])
            if holder is None:
                raise RuntimeError("Reservation holder disappeared")
            quantity=record["quantity"];resource=record["resource"]
            if record["kind"]=="inventory":
                holder["reserved"][resource]-=quantity
                if consume:holder["inventory"][resource]-=quantity
            elif record["kind"]=="biomass":
                holder["reserved_biomass"]-=quantity
                if consume:holder["biomass"]-=quantity
            else:
                holder["reserved_charges"]-=quantity
                if consume:
                    holder["spit_charges"]-=quantity
                    if holder.get("next_charge_at") is None and holder["life"]>0 and holder.get("role")=="SPITTER":
                        holder["next_charge_at"]=_stamp(self.time+_clock(profile(holder,_stamp(self.time))["recharge_interval"]))
                        self._schedule(holder["next_charge_at"],2,"recharge",holder["id"],generation=holder.get("_generation",0))
            self._mark(record["collection"],record["holder"])
            records.append(deepcopy(record))
            del self.state["reservations"][reservation_id];self._mark("reservations",reservation_id)
        occurrence.setdefault("released_reservations",[]).extend(records)
        if consume:occurrence.setdefault("spent_resources",[]).extend(records)
        occurrence["reservations"]=[]
        self._mark("occurrences",occurrence["id"])
        return records

    def _resolve(self,occurrence_id):
        occurrence=self.occurrences.get(str(occurrence_id))
        if not occurrence or occurrence["result"]!="IN_PROGRESS":
            return
        aid,action=occurrence["actor"],occurrence["action"]
        actor=self._touch(aid)
        occurrence["actor_before_end"]=self._capture_action_agent(aid)
        occurrence["target_before_end"]=self._capture_action_agent(occurrence.get("target"))
        if actor["life"]<=0:
            self._finish(occurrence,"CANCELLED_BY_DEATH")
            self._commit("action_cancelled",actor=aid,action=action,occurrence=occurrence["id"],outcome="CANCELLED_BY_DEATH")
            return
        if actor.get("active_action")!=occurrence["id"] or action not in capabilities(actor):
            self._finish(occurrence,"CANCELLED_BY_INTERVENTION")
            self._commit("action_cancelled",actor=aid,action=action,occurrence=occurrence["id"],outcome="CANCELLED_BY_INTERVENTION")
            return
        try:
            self._action_plan(self._view_agent(aid),action,occurrence.get("target"),occurrence["parameters"],completion=True,occurrence=occurrence)
        except (ActionError,ValueError,KeyError,TypeError) as exc:
            occurrence["audit_reason"]=str(exc)
            self._finish(occurrence,"FAILED_PRECONDITION")
            occurrence["actor_after_end"]=self._capture_action_agent(aid,after=True)
            occurrence["target_after_end"]=self._capture_action_agent(occurrence.get("target"),after=True)
            self._mark("occurrences",occurrence["id"])
            self._commit("action_completed",actor=aid,target=occurrence.get("target"),action=action,occurrence=occurrence["id"],outcome="FAILED_PRECONDITION")
            return
        p=profile(actor,_stamp(self.time));parameters=occurrence["parameters"];target_id=occurrence.get("target")
        from .parallel import consume_prepared_effect
        prepared=consume_prepared_effect(self,occurrence,actor,p)
        result="SUCCEEDED";reciprocal=None
        if action in ATTACKS:
            target=self.state["agents"][target_id]
            other=self.occurrences.get(target.get("active_action"))
            if other and other["result"]=="IN_PROGRESS" and other["action"] in ATTACKS and other.get("target")==aid and _clock(other["start_at"])<_clock(occurrence["planned_end"]) and _clock(occurrence["start_at"])<_clock(other["planned_end"]):
                reciprocal=other
                # Both attempts resolve in the winner's atomic transaction.
                # The losing attempt's pre-state precedes the winner's damage.
                reciprocal["actor_before_end"]=deepcopy(occurrence["target_before_end"])
                reciprocal["target_before_end"]=deepcopy(occurrence["actor_before_end"])
            if action=="spit":
                self._release(occurrence,consume=True)
            probability=min(1.,max(0.,.5+.45*p["combat_skill"])) if action in ("melee","power_strike") else min(.95,max(0.,.6+.3*p["attack_skill"]+p.get("rally_bonus",0)))
            hit=self._bernoulli(occurrence,"hit",probability)
            occurrence["hit"]=bool(hit)
            if hit:
                raw=p["melee_damage"] if action=="melee" else p["strike_damage"] if action=="power_strike" else p["claw_damage"] if action=="claw" else p["bite_damage"] if action=="bite" else p["spit_damage"]
                occurrence["damage"]=self._damage(target_id,raw,occurrence["id"])
                if action in ("bite","spit") and self.state["agents"][target_id]["life"]>0 and self.state["agents"][target_id]["type"]=="Human" and not self.state["agents"][target_id].get("infection_episode"):
                    self._expose(target_id,p["virulence"] if action=="bite" else p["spit_potency"],occurrence)
            else:
                result="MISSED"
            if reciprocal and reciprocal["result"]=="IN_PROGRESS":
                self._finish(reciprocal,"CANCELLED_BY_CONFLICT")
                reciprocal["conflict_winner"]=occurrence["id"];self._mark("occurrences",reciprocal["id"])
        elif action in ("pickup","drop","transfer"):
            resource,quantity=parameters["resource"],parameters["quantity"]
            self._release(occurrence,consume=True)
            if action=="pickup":
                actor["inventory"][resource]=actor["inventory"].get(resource,0)+quantity
                self._mark("agents",aid)
            elif action=="transfer":
                target=self._touch(target_id);target["inventory"][resource]=target["inventory"].get(resource,0)+quantity
            else:
                occurrence["stockpile_id"]=self._drop(actor,{resource:quantity})
        elif action=="eat":
            self._release(occurrence,consume=True)
            actor["hunger"]=prepared["hunger"] if prepared is not None else max(0.,actor["hunger"]-40)
            actor["_hunger_generation"]=actor.get("_hunger_generation",0)+1
            actor["starvation_started_at"]=None;actor["next_starvation_damage_at"]=None
            self._schedule_starvation(actor)
        elif action=="first_aid":
            target=self._touch(target_id);self._release(occurrence,consume=True)
            if prepared is not None:
                occurrence["healing"]=prepared["healing"];target["life"]=prepared["life"]
            else:
                healing=10+math.floor(20*p["medical_skill"]+.5)
                occurrence["healing"]=min(100-target["life"],healing);target["life"]+=occurrence["healing"]
        elif action=="treat_infection":
            target=self._touch(target_id);self._release(occurrence,consume=True)
            episode_id=target["infection_episode"];episode=self.state["episodes"][episode_id]
            episode.update(outcome="CURED",ended_at=_stamp(self.time),end_revision=self.revision+1)
            target["infection_episode"]=None
            self._effects_buffer.append({"kind":"cure","agent_id":target_id,"actor":aid,"target":target_id,"episode_id":episode_id,"action_id":occurrence["id"],"before_state":deepcopy(occurrence["target_before_end"]),"after_state":self._capture_action_agent(target_id,after=True)})
            occurrence["episode_id"]=episode_id;occurrence["cure"]=True
            self._mark("episodes",episode_id)
        elif action=="prophylaxis":
            self._release(occurrence,consume=True)
            self._effect(target_id,"prophylaxis",p["prophylaxis_resistance"],p["prophylaxis_duration"],occurrence["id"])
        elif action=="feed":
            self._release(occurrence,consume=True)
            occurrence["healing"]=min(100-actor["life"],p["feed_healing"])
            actor["life"]+=occurrence["healing"];actor["stamina"]=min(100.,actor["stamina"]+p["feed_energy"])
        elif action in ("open_gate","close_gate"):
            gate=self.state["barriers"][target_id];gate["mode"]="OPEN" if action=="open_gate" else "CLOSED"
            self._mark("barriers",target_id);self._geometry_changed()
        elif action in ("smash","demolish"):
            barrier=self.state["barriers"][target_id]
            if prepared is not None:
                barrier["integrity"]=prepared["integrity"];occurrence["integrity_damage"]=prepared["integrity_damage"]
            else:
                amount=min(barrier["integrity"],20 if action=="smash" else p["demolish_damage"])
                barrier["integrity"]-=amount;occurrence["integrity_damage"]=amount
            if barrier["type"]=="Gate" and barrier["integrity"]==0:barrier["mode"]="BREACHED"
            self._mark("barriers",target_id);self._geometry_changed()
        elif action=="repair_barrier":
            self._release(occurrence,consume=True);barrier=self.state["barriers"][target_id]
            if prepared is not None:
                barrier["integrity"]=prepared["integrity"];occurrence["integrity_restored"]=prepared["integrity_restored"]
            else:
                amount=min(barrier["max_integrity"]-barrier["integrity"],p["repair_amount"])
                barrier["integrity"]+=amount;occurrence["integrity_restored"]=amount
            if barrier["type"]=="Gate" and barrier["mode"]=="BREACHED" and barrier["integrity"]>0:
                barrier["mode"]="OPEN"
            self._mark("barriers",target_id);self._geometry_changed()
        elif action=="build_barricade":
            self._release(occurrence,consume=True);identifier=self._id("barricade")
            self.state["barriers"][identifier]={"id":identifier,"type":"Barricade","footprint":parameters["footprint"],"integrity":p["build_integrity"],"max_integrity":p["build_integrity"],"creator_id":aid,"created_at":_stamp(self.time)}
            occurrence["barrier_id"]=identifier;self._mark("barriers",identifier);self._geometry_changed()
        elif action in ("guard","recon"):
            self._effect(aid,action,p["guard_resistance"] if action=="guard" else p["recon_radius"],p["guard_duration"] if action=="guard" else p["recon_duration"],occurrence["id"])
        elif action=="rally":
            for target in list(self.state["agents"].values()):
                if target["id"]!=aid and target["life"]>0 and target["type"]=="Zombie" and distance_to(actor,self._view_agent(target["id"]))<=p["rally_radius"]:
                    self._effect(target["id"],"rallied",p["rally_hit_bonus"],p["rally_duration"],occurrence["id"])
            self._broadcast(aid,"RALLY",{"position":{"x":actor["x"],"y":actor["y"]},"observed_at":_stamp(self.time)},p["rally_radius"],p["rally_duration"],occurrence["id"])
        elif action=="mark_target":
            target=self._view_agent(target_id)
            payload={"entity_id":target_id,"type":target["type"],"position":{"x":target["x"],"y":target["y"]},"observed_at":_stamp(self.time)}
            self._broadcast(aid,"TARGET_REPORT",payload,p["mark_radius"],10,occurrence["id"])
        elif action in ("signal","scream"):
            payload=parameters.get("payload",{}) or {"position":{"x":actor["x"],"y":actor["y"]},"observed_at":_stamp(self.time)}
            self._broadcast(aid,"HUNT_CUE" if action=="scream" else parameters.get("kind","WARNING"),payload,p["call_radius"] if action=="scream" else 40,p["call_ttl"] if action=="scream" else 8,occurrence["id"])
        self._finish(occurrence,result)
        occurrence["actor_after_end"]=self._capture_action_agent(aid,after=True)
        occurrence["target_after_end"]=self._capture_action_agent(target_id,after=True)
        self._mark("occurrences",occurrence["id"])
        self._finalize_action_evidence()
        self._commit("action_completed",actor=aid,target=target_id,action=action,occurrence=occurrence["id"],outcome=result)
