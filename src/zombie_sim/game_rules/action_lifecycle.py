"""ActionService owns actions behavior behind an explicit context port."""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
from .primitives import clock, stamp
import json
import math
from ..domain import RESOURCES, capabilities, profile
from ..geometry import blocking, contains, distance_to, nearest_point, overlap, point, point_blocked, rect, segment_clear
from ..registry import ACTIONS
from ..actions import ActionError, _clock, _stamp, _number, ATTACKS, AGENT_ACTIONS, BARRIER_ACTIONS


class ActionLifecycle:
    def __init__(self, context):
        self.context = context
        self.handlers = context.action_handlers

    def _finalize_action_evidence(self):
        """Capture the final atomic after-state, after all coupled consequences."""
        context = self.context
        for collection,identifier in tuple(context._dirty):
            if collection!="occurrences":continue
            occurrence=context.occurrences.get(identifier)
            if not occurrence or occurrence.get("result")=="IN_PROGRESS" or occurrence.get("resolved_at")!=_stamp(context.time):continue
            occurrence["actor_after_end"]=context._capture_action_agent(occurrence["actor"],after=True)
            occurrence["target_after_end"]=context._capture_action_agent(occurrence.get("target"),after=True)

    def _capture_action_agent(self,identifier,after=False,admission=False):
        context = self.context
        if identifier is None or str(identifier) not in context.state["agents"]:
            return None
        if admission and getattr(context,"_batching",False):
            cached=getattr(context,"_admission_boundary_agents",{}).get(str(identifier))
            if cached is not None:
                return deepcopy(cached)
        agent=deepcopy(context._view_agent(str(identifier)))
        agent["at_time"]=_stamp(context.time)
        agent["revision"]=context.revision+int(after)
        return agent

    def _perceived(self,actor,target,barrier=False):
        context = self.context
        if str(actor["id"])==str(target.get("id")):
            return True
        destination=nearest_point(actor,target)
        reach=profile(actor,_stamp(context.time))["sense_r"]
        return distance_to(actor,target)<=reach and segment_clear(point(actor),destination,context.state["barriers"],ignore_id=target.get("id") if barrier else None)

    def _target(self,actor,action,identifier,reach):
        context = self.context
        if action in AGENT_ACTIONS:
            if identifier is None:
                if action in {"first_aid","treat_infection","prophylaxis"}:
                    identifier=actor["id"]
                else:
                    raise ActionError("An agent target is required")
            if str(identifier) not in context.state["agents"]:
                raise ActionError("Agent target unavailable")
            target=context._view_agent(str(identifier))
            if target["life"]<=0:
                raise ActionError("Target must be alive")
            if not context._perceived(actor,target):
                raise ActionError("Target is not currently perceived")
            if reach is not None and distance_to(actor,target)>reach:
                raise ActionError("Target is out of reach")
            if action in ATTACKS:
                if str(target["id"])==str(actor["id"]):
                    raise ActionError("Self attacks are forbidden")
                if target["type"]==actor["type"] and not context.config.get("allow_intraspecies_combat",False):
                    raise ActionError("Same-type combat is disabled")
            elif action in {"first_aid","transfer","treat_infection","prophylaxis"}:
                if target["type"]!="Human":
                    raise ActionError("Target must be a living Human")
                if action=="transfer" and str(target["id"])==str(actor["id"]):
                    raise ActionError("Transfer requires another Human")
            return str(identifier),target,"agents"
        if action in BARRIER_ACTIONS:
            if str(identifier) not in context.state["barriers"]:
                raise ActionError("Barrier target unavailable")
            target=context.state["barriers"][str(identifier)]
            if not context._perceived(actor,target,True) or distance_to(actor,target)>reach:
                raise ActionError("Barrier is not currently reachable and perceived")
            return str(identifier),target,"barriers"
        if action in {"pickup","feed"}:
            collection="stockpiles" if action=="pickup" else "remains"
            if str(identifier) not in context.state[collection]:
                raise ActionError("Resource target unavailable")
            target=context.state[collection][str(identifier)]
            if not context._perceived(actor,target) or distance_to(actor,target)>reach:
                raise ActionError("Resource is not currently reachable and perceived")
            return str(identifier),target,collection
        if identifier is not None and str(identifier)!=str(actor["id"]):
            raise ActionError("This action has no other entity target")
        return None,actor,"agents"

    def _path_parameters(self,actor,action,parameters,duration,p):
        context = self.context
        path=parameters.get("path")
        if not isinstance(path,list) or len(path)<2:
            raise ActionError("Movement needs at least two timed path points")
        cleaned=[]
        for index,item in enumerate(path):
            if not isinstance(item,dict) or not {"x","y","offset"}<=set(item):
                raise ActionError("Each path point needs x, y and offset")
            x=_number(item["x"],"path.x",0,context.state["world"]["length"])
            y=_number(item["y"],"path.y",0,context.state["world"]["width"])
            offset=_clock(item["offset"])
            if point_blocked((x,y),context.state["barriers"]):
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
            if not segment_clear(point(a),point(b),context.state["barriers"]):
                raise ActionError("A path segment crosses blocking geometry")
            distance+=length
        parameters["path"]=cleaned
        return distance

    def _gate_clear(self,gate):
        context = self.context
        if any(a["life"]>0 and contains(gate,context._view_agent(a["id"])) for a in context.state["agents"].values()):
            return False
        return not any(b.get("type")=="Barricade" and b.get("integrity",0)>0 and overlap(gate,b) for b in context.state["barriers"].values())

    def _construction_footprint(self,actor,parameters):
        context = self.context
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
        x0,y0,x1,y1=footprint; world=context.state["world"]
        if not 0<=x0<x1<=world["length"] or not 0<=y0<y1<=world["width"]:
            raise ActionError("Entire barricade must lie in world bounds")
        for barrier in context.state["barriers"].values():
            intact=barrier.get("type")!="Barricade" or barrier.get("integrity",0)>0
            if not intact:
                continue
            if overlap(footprint,barrier,strict=True) and not (barrier.get("type")=="Gate" and barrier.get("mode") in ("OPEN","BREACHED")):
                raise ActionError("Barricade interior overlaps an intact barrier")
        for agent in context.state["agents"].values():
            if agent["life"]>0 and contains(footprint,context._view_agent(agent["id"])):
                raise ActionError("Barricade footprint is occupied by a living agent")
        for collection,key in (("stockpiles","inventory"),("remains","biomass")):
            for entity in context.state[collection].values():
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
        for barrier in context.state["barriers"].values():
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
        sense=profile(actor,_stamp(context.time))["sense_r"]
        for corner in ((x0,y0),(x0,y1),(x1,y0),(x1,y1)):
            if distance_to(actor,corner)>sense:
                raise ActionError("Entire barricade footprint must be visible")
            endpoint=(math.nextafter(corner[0],float(actor["x"])),math.nextafter(corner[1],float(actor["y"])))
            if not segment_clear(point(actor),endpoint,context.state["barriers"]):
                raise ActionError("Barricade footprint is occluded")
        parameters.update(center={"x":cx,"y":cy},length=length,orientation=orientation,footprint=footprint)
        return footprint

    def _knowledge_payload(self,actor,action,parameters):
        context = self.context
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
        if observed>context.time:
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
            _number(pos["x"],"payload.x",0,context.state["world"]["length"])
            _number(pos["y"],"payload.y",0,context.state["world"]["width"])
        identifier=str(payload["entity_id"]) if payload.get("entity_id") is not None else None
        candidates=[]
        if observed==context.time:
            candidates.append(actor)
            nearby=([identifier] if identifier in context.state["agents"] else []) if identifier is not None else context._nearby(point(actor),float(actor["sense_r"]))
            for aid in nearby:
                if aid==str(actor["id"]):
                    continue
                entity=context._view_agent(aid)
                if context._perceived(actor,entity):
                    candidates.append(entity)
            for collection in ("stockpiles","remains"):
                entities=([context.state[collection][identifier]] if identifier in context.state[collection] else []) if identifier is not None else context.state[collection].values()
                candidates.extend(entity for entity in entities if context._perceived(actor,entity))
        # Trust recorded inputs, not arbitrary claims in model-returned memory.
        # Index by actor and exact observation time. Scanning the full history
        # for every report becomes quadratic in long runs. This index contains
        # references to durable evidence, is ephemeral, and rebuilds on restore.
        decisions=getattr(context,"decisions",[])
        if hasattr(decisions,"observations_at"):
            observed_inputs=decisions.observations_at(actor["id"],_stamp(observed))
        else:
            observed_inputs=[record.get("observation",{}) for record in decisions
                             if str(record.get("actor"))==str(actor["id"]) and _clock(record.get("observation",{}).get("time",0))==observed]
        for observation in observed_inputs:
            candidates.append(observation.get("self_state",{}))
            local=observation.get("local_agents",{})
            candidates.extend(local.values() if isinstance(local,dict) else local)
            for collection in ("stockpiles","remains"):
                local=observation.get("local_environment",{}).get(collection,{})
                candidates.extend(local.values() if isinstance(local,dict) else local)
        matching=[entity for entity in candidates if identifier is None or str(entity.get("id"))==identifier]
        if "position" in payload:
            matching=[entity for entity in matching if "x" in entity and distance_to(entity,payload["position"])<=1e-9]
        if identifier is None and "position" in payload and observed==context.time and context._perceived(actor,payload["position"]):
            matching.append(payload["position"])
        # A received dated report can be repeated without claiming fresh sight.
        for signal in context.state.get("signals",{}).values():
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
        context = self.context
        plan=context._action_plan_checked(actor,action,target_id,parameters,completion,occurrence)
        observed=plan.pop("_read_dependencies",{})
        declared=deepcopy(observed)
        from ..faults import omit_dependency
        omit_dependency(declared,actor=actor["id"],action=action,completion=completion)
        valid=set(observed)<=set(declared)
        for dependency in declared.values():
            obj=context.state[dependency["collection"]][dependency["holder"]]
            resource=dependency["resource"]
            current=(obj.get("inventory",{}).get(resource,0)-obj.get("reserved",{}).get(resource,0)
                     if dependency["kind"]=="inventory" else obj.get("biomass",0)-obj.get("reserved_biomass",0)
                     if dependency["kind"]=="biomass" else obj.get("spit_charges",0)-obj.get("reserved_charges",0))
            valid=valid and current==dependency["available"]
        if not valid:
            # Reject the detached plan before spending or publishing anything.
            # The coordinator rebuilds it from authoritative current resource reads.
            context._runtime_dependency_retries=getattr(context,"_runtime_dependency_retries",0)+1
            plan=context._action_plan_checked(actor,action,target_id,parameters,completion,occurrence)
            plan.pop("_read_dependencies",None)
        return plan

    def _action_plan_checked(self, actor, action, target_id, parameters, completion=False, occurrence=None):
        return self.handlers[action].validate_admission(self.context, actor, target_id, parameters,
                                                       completion=completion, occurrence=occurrence)

    def submit_intents(self,intents):
        """Arbitrate and publish an externally supplied decision batch atomically."""
        context = self.context
        if context._batching:
            return context._submit_intents_inner(intents)
        context._batching=True
        try:
            result=context._submit_intents_inner(intents)
        finally:
            context._batching=False
        context._commit("admission_batch",intents=[item["id"] for item in result])
        return result

    def _submit_intents_inner(self,intents):
        context = self.context
        if isinstance(intents,dict):
            intents=[intents]
        if not isinstance(intents,(list,tuple)):
            raise ValueError("Intents must be a mapping or a batch of mappings")
        if getattr(context,"_batching",False):
            token=(_stamp(context.time),context.revision)
            if getattr(context,"_admission_boundary_token",None)!=token:
                context._admission_boundary_token=token
                context._admission_boundary_agents={};context._admission_boundary_entities={}
            # Admission arbitration stages several changes into one revision.
            # Boundary evidence must describe the committed pre-batch state,
            # while reservation checks below still see all staged winners.
            for intent in intents:
                if not isinstance(intent,dict):continue
                parameters=intent.get("parameters",{})
                target=intent.get("target",parameters.get("target") if isinstance(parameters,dict) else None)
                for identifier in (intent.get("actor",intent.get("agent_id")),target):
                    identifier=str(identifier)
                    if identifier in context.state["agents"] and identifier not in context._admission_boundary_agents:
                        context._admission_boundary_agents[identifier]=context._capture_action_agent(identifier)
                if target is not None:
                    target=str(target)
                    for collection in ("barriers","stockpiles","remains"):
                        key=(collection,target)
                        if target in context.state[collection] and key not in context._admission_boundary_entities:
                            context._admission_boundary_entities[key]=deepcopy(context.state[collection][target])
        prepared=[];results={}
        for index,intent in enumerate(intents):
            intent=deepcopy(intent) if isinstance(intent,dict) else {}
            if "id" not in intent:
                intent["id"]=context._id("intent")
            identifier=str(intent["id"]);actor=str(intent.get("actor",intent.get("agent_id","")))
            action=intent.get("action",intent.get("name"));parameters=intent.get("parameters",{})
            key=json.dumps([actor,action,intent.get("target"),parameters],sort_keys=True,default=str)
            prepared.append((context._random("admission",_stamp(context.time)+":"+key),actor,identifier,index,intent))
        for priority,aid,identifier,index,intent in sorted(prepared,key=lambda row:(row[0],row[1],row[2])):
            action=intent.get("action",intent.get("name"));audit=None;admitting=False
            try:
                if identifier in context.intents:
                    raise ActionError("Intent identity was already processed")
                if aid not in context.state["agents"]:
                    raise ActionError("Unknown actor")
                actor=context._view_agent(aid)
                if actor["life"]<=0 or actor.get("active_action"):
                    raise ActionError("Actor must be living and idle")
                if action not in ACTIONS or action not in capabilities(actor):
                    raise ActionError("Action is not granted by the actor's type and role")
                if context.time<_clock(actor.get("cooldowns",{}).get(action,0)):
                    raise ActionError("Action is still on cooldown")
                parameters=intent.get("parameters",{})
                if not isinstance(parameters,dict):
                    raise ActionError("Action parameters must be a mapping")
                if intent.get("proposed_at") is not None and _clock(intent["proposed_at"])!=context.time:
                    raise ActionError("Intent proposal time differs from admission time")
                plan=context._action_plan(actor,action,intent.get("target",parameters.get("target")),parameters)
                if float(actor["stamina"])+1e-9<plan["cost"]+plan["travel_cost"]:
                    raise ActionError("Insufficient stamina for the complete action plan")
                occurrence_id=context._id("action")
                occurrence={"id":occurrence_id,"intent_id":identifier,"actor":aid,"action":action,"target":plan["target"],"target_collection":plan["target_collection"],"parameters":plan["parameters"],"start_at":_stamp(context.time),"planned_end":_stamp(context.time+plan["duration"]),"duration":_stamp(plan["duration"]),"cost":plan["cost"],"cooldown":plan["cooldown"],"result":"IN_PROGRESS","reservations":[],"admission_priority":priority,"actor_start":context._capture_action_agent(aid,admission=True),"target_start":context._capture_action_agent(plan["target"],admission=True)}
                admitting=True
                if plan["target_collection"] in ("barriers","stockpiles","remains"):
                    key=(plan["target_collection"],plan["target"])
                    cached=getattr(context,"_admission_boundary_entities",{}).get(key) if getattr(context,"_batching",False) else None
                    occurrence["environment_start"]=deepcopy(cached if cached is not None else context.state[plan["target_collection"]][plan["target"]])
                actual=context._touch(aid);actual["stamina"]=max(0.,float(actual["stamina"])-plan["cost"])
                actual["active_action"]=occurrence_id
                if action in ("move","dash"):
                    actual["_travelled"]=0.0
                for record in plan["reservations"]:
                    rid=context._id("reservation");record.update(id=rid,occurrence_id=occurrence_id,actor=aid)
                    holder=context.state[record["collection"]][record["holder"]]
                    if record["kind"]=="inventory":
                        holder.setdefault("reserved",{})[record["resource"]]=holder.get("reserved",{}).get(record["resource"],0)+record["quantity"]
                    else:
                        key="reserved_biomass" if record["kind"]=="biomass" else "reserved_charges"
                        holder[key]=holder.get(key,0)+record["quantity"]
                    context.state["reservations"][rid]=record;occurrence["reservations"].append(rid)
                    context._mark(record["collection"],record["holder"]);context._mark("reservations",rid)
                context.occurrences[occurrence_id]=occurrence;context._mark("occurrences",occurrence_id)
                occurrence["actor_after_start"]=context._capture_action_agent(aid,after=True)
                outcome={"id":identifier,"actor":aid,"status":"ADMITTED","occurrence_id":occurrence_id}
                context.intents[identifier]={**deepcopy(intent),"id":identifier,"actor":aid,"action":action,
                    "parameters":deepcopy(parameters),"resolved_parameters":deepcopy(plan["parameters"]),
                    "outcome":outcome,"proposed_at":_stamp(context.time)}
                context._mark("intents",identifier)
                context._schedule(context.time+plan["duration"],5,"complete",aid,occurrence=occurrence_id)
                context._commit("action_started",actor=aid,target=plan["target"],action=action,occurrence=occurrence_id,intent_id=identifier,arbitration_priority=priority)
                results[index]=outcome
            except (ActionError,KeyError,ValueError,TypeError,OverflowError) as exc:
                if admitting:
                    raise
                audit=str(exc)
                outcome={"id":identifier,"actor":aid,"status":"REJECTED","reason":"PRECONDITION_FAILED"}
                if identifier not in context.intents:
                    context.intents[identifier]={**deepcopy(intent),"id":identifier,"actor":aid,"outcome":outcome,"audit_reason":audit,"proposed_at":_stamp(context.time)}
                    context._mark("intents",identifier)
                context._commit("intent_rejected",actor=aid,intent_id=identifier,action=action,reason="PRECONDITION_FAILED",audit_reason=audit)
                results[index]=outcome
        return [results[index] for index in range(len(intents))]

    def _release(self,occurrence,consume=False):
        context = self.context
        records=[]
        for reservation_id in list(occurrence.get("reservations",[])):
            record=context.state["reservations"].get(reservation_id)
            if record is None:
                continue
            if record.get("occurrence_id")!=occurrence["id"]:
                raise RuntimeError("Reservation belongs to a different occurrence")
            holder=context.state[record["collection"]].get(record["holder"])
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
                        holder["next_charge_at"]=_stamp(context.time+_clock(profile(holder,_stamp(context.time))["recharge_interval"]))
                        context._schedule(holder["next_charge_at"],2,"recharge",holder["id"],generation=holder.get("_generation",0))
            context._mark(record["collection"],record["holder"])
            records.append(deepcopy(record))
            del context.state["reservations"][reservation_id];context._mark("reservations",reservation_id)
        occurrence.setdefault("released_reservations",[]).extend(records)
        if consume:occurrence.setdefault("spent_resources",[]).extend(records)
        occurrence["reservations"]=[]
        context._mark("occurrences",occurrence["id"])
        return records

    def _resolve(self,occurrence_id):
        context = self.context
        occurrence=context.occurrences.get(str(occurrence_id))
        if not occurrence or occurrence["result"]!="IN_PROGRESS":
            return
        aid,action=occurrence["actor"],occurrence["action"]
        actor=context._touch(aid)
        occurrence["actor_before_end"]=context._capture_action_agent(aid)
        occurrence["target_before_end"]=context._capture_action_agent(occurrence.get("target"))
        if actor["life"]<=0:
            context._finish(occurrence,"CANCELLED_BY_DEATH")
            context._commit("action_cancelled",actor=aid,action=action,occurrence=occurrence["id"],outcome="CANCELLED_BY_DEATH")
            return
        if actor.get("active_action")!=occurrence["id"] or action not in capabilities(actor):
            context._finish(occurrence,"CANCELLED_BY_INTERVENTION")
            context._commit("action_cancelled",actor=aid,action=action,occurrence=occurrence["id"],outcome="CANCELLED_BY_INTERVENTION")
            return
        try:
            context._action_plan(context._view_agent(aid),action,occurrence.get("target"),occurrence["parameters"],completion=True,occurrence=occurrence)
        except (ActionError,ValueError,KeyError,TypeError) as exc:
            occurrence["audit_reason"]=str(exc)
            context._finish(occurrence,"FAILED_PRECONDITION")
            occurrence["actor_after_end"]=context._capture_action_agent(aid,after=True)
            occurrence["target_after_end"]=context._capture_action_agent(occurrence.get("target"),after=True)
            context._mark("occurrences",occurrence["id"])
            context._commit("action_completed",actor=aid,target=occurrence.get("target"),action=action,occurrence=occurrence["id"],outcome="FAILED_PRECONDITION")
            return
        target_id=occurrence.get("target")
        result=self.handlers[action].resolve(context, occurrence, actor)
        context._finish(occurrence,result)
        occurrence["actor_after_end"]=context._capture_action_agent(aid,after=True)
        occurrence["target_after_end"]=context._capture_action_agent(target_id,after=True)
        context._mark("occurrences",occurrence["id"])
        context._finalize_action_evidence()
        context._commit("action_completed",actor=aid,target=target_id,action=action,occurrence=occurrence["id"],outcome=result)

    def _finish(self,occurrence,result):
        context = self.context
        if occurrence["result"]!="IN_PROGRESS":
            return
        a=context._touch(occurrence["actor"])
        occurrence.setdefault("actor_before_end",context._capture_action_agent(a["id"]))
        if occurrence.get("target") in context.state["agents"]:
            occurrence.setdefault("target_before_end",context._capture_action_agent(occurrence["target"]))
        context._release(occurrence)
        occurrence.update(result=result,resolved_at=stamp(context.time))
        if a.get("active_action")==occurrence["id"]:
            a["active_action"]=None
        a.pop("_travelled",None)
        cooldown=clock(occurrence.get("cooldown",0))
        if cooldown and a["life"]>0:
            a["cooldowns"][occurrence["action"]]=stamp(context.time+cooldown)
        occurrence["actor_after_end"]=context._capture_action_agent(a["id"],after=True)
        targetid=occurrence.get("target")
        if targetid in context.state["agents"]:
            occurrence["target_after_end"]=context._capture_action_agent(targetid,after=True)
        context._mark("occurrences",occurrence["id"])
        context._effects_buffer.append({"kind":"action_result","actor":a["id"],"target":targetid,
                                     "occurrence":occurrence["id"],"action":occurrence["action"],"result":result})
        if a["life"]>0:
            context._schedule_decision(a["id"],context.time)

