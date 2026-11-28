"""Ontology lifecycle rules. Each operates only on an isolated plan workspace."""
from copy import deepcopy
from fractions import Fraction
import math
from ..domain import profile
from .primitives import clock, stamp, point, half_up, _segment_contact, RESOURCES

class DamageRules:
    def __init__(self, context):
        self.context = context

    def _damage(self, targetid, raw, source, bypass=False):
        context = self.context
        a=context._touch(targetid)
        if a["life"] == 0:
            return 0
        resistance=float(profile(a,stamp(context.time))["damage_resistance"])
        mitigated=half_up(raw if bypass else Fraction(str(raw))*(1-Fraction(str(resistance))))
        actual=min(a["life"],mitigated)
        origin=context.occurrences.get(source,{}) if isinstance(source,str) else source
        context._effects_buffer.append({"kind":"damage","actor":origin.get("actor") if isinstance(origin,dict) else None,
                                     "target":str(targetid),"target_type":a["type"],"source":source if isinstance(source,str) else source.get("id"),
                                     "raw_damage":raw,"mitigated_damage":mitigated,"actual_damage":actual})
        before=deepcopy(a)
        a["life"]-=actual
        if a["life"]==0:
            context._die(a,source if isinstance(source,str) else source["id"],before_state=before)
        return actual



class ResourceRules:
    def __init__(self, context):
        self.context = context

    def _drop(self, a, quantities):
        context = self.context
        quantities={r:int(q) for r,q in quantities.items() if int(q)>0}
        if not quantities:
            return None
        sid=context._id("stockpile")
        context.state["stockpiles"][sid]={"id":sid,"x":a["x"],"y":a["y"],
                                       "inventory":{r:quantities.get(r,0) for r in RESOURCES},
                                       "reserved":{r:0 for r in RESOURCES},"created_at":stamp(context.time)}
        context._mark("stockpiles",sid)
        context._effects_buffer.append({"kind":"inventory_drop","agent":a["id"],"stockpile":sid,"quantities":quantities})
        return sid



class InfectionRules:
    def __init__(self, context):
        self.context = context

    def _close_episode(self,a,outcome):
        context = self.context
        eid=a.get("infection_episode")
        if eid:
            ep=context.state["episodes"][eid]
            ep.update(outcome=outcome,ended_at=stamp(context.time),end_revision=context.revision+1)
            context._mark("episodes",eid)
        a["infection_episode"]=None
        return eid


    def _expose(self,targetid,potency,occurrence):
        context = self.context
        a=context._touch(targetid)
        if a["life"]==0 or a["type"]!="Human" or a.get("infection_episode"):
            return False
        resistance=float(profile(a,stamp(context.time))["infection_resistance_effective"])
        if not context._bernoulli(occurrence,"infection",float(Fraction(str(potency))*(1-Fraction(str(resistance))))):
            return False
        eid=context._id("episode")
        duration=clock(context.config.get("incubation_duration",300))
        context.state["episodes"][eid]={"id":eid,"episode_id":eid,"agent_id":str(targetid),
                                      "source_kind":occurrence["action"],"source_agent_id":occurrence["actor"],
                                      "source_event_id":occurrence["id"],"onset_at":stamp(context.time),
                                      "onset_revision":context.revision+1,
                                      "incubation_duration":stamp(duration),"conversion_due_at":stamp(context.time+duration),
                                      "ended_at":None,"end_revision":None,"outcome":"ONGOING"}
        a["infection_episode"]=eid
        context._mark("episodes",eid)
        context._schedule(context.time+duration,3,"conversion",a["id"],episode=eid)
        context._effects_buffer.append({"kind":"infection","actor":occurrence["actor"],"target":str(targetid),"episode":eid})
        return True



class DeathRules:
    def __init__(self, context):
        self.context = context

    def _die(self,a,source,before_state=None):
        context = self.context
        if a.get("death_at") is not None:
            return
        before=before_state or deepcopy(a)
        active=context.occurrences.get(a.get("active_action"))
        if active:
            active["actor_before_end"]={**deepcopy(before),"at_time":stamp(context.time),"revision":context.revision}
            if active.get("target") in context.state["agents"]:
                active.setdefault("target_before_end",context._capture_action_agent(active["target"]))
            context._finish(active,"CANCELLED_BY_DEATH")
        eid=context._close_episode(a,"HOST_DIED")
        if a["type"]=="Human":
            context._drop(a,a["inventory"])
            a["inventory"]={r:0 for r in RESOURCES}
            a["reserved"]={r:0 for r in RESOURCES}
            a["starvation_started_at"]=a["next_starvation_damage_at"]=None
            a.pop("_starvation_due_at",None)
        old_model=deepcopy(a.get("model_assignment"))
        old_memory=context.memories.pop(a["id"],{})
        a.update(role=None,model_assignment=None,effects={},cooldowns={},active_action=None,
                 death_at=stamp(context.time),death_cause=source,status="DEAD")
        a["_generation"]+=1
        a["_hunger_generation"]=a.get("_hunger_generation",0)+1
        a["next_charge_at"]=None
        a.pop("_travelled",None)
        if active:
            active["actor_after_end"]=context._capture_action_agent(a["id"],after=True)
        rid=context._id("remains")
        context.state["remains"][rid]={"id":rid,"source_agent_id":a["id"],"x":a["x"],"y":a["y"],
                                    "biomass":4,"reserved_biomass":0,"created_at":stamp(context.time)}
        context._mark("remains",rid)
        context._mark("agents",a["id"])
        context._effects_buffer.append({"kind":"death","agent_id":a["id"],"agent":a["id"],"source":source,
                                     "episode_id":eid,"before_state":before,"after_state":deepcopy(a),
                                     "retired_model":old_model,"retired_memory":old_memory,"remains":rid})



class ConversionRules:
    def __init__(self, context):
        self.context = context

    def _convert(self,a):
        context = self.context
        from ..domain import decision_model_assignment
        assignment=decision_model_assignment(context.config.get("zombie_model","ZombieDefaultModel"),agent_type="Zombie")
        before=deepcopy(a)
        eid=a["infection_episode"]
        active=context.occurrences.get(a.get("active_action"))
        if active:
            context._finish(active,"CANCELLED_BY_CONVERSION")
        context._close_episode(a,"CONVERTED")
        context._drop(a,a["inventory"])
        old_model=deepcopy(a.get("model_assignment"))
        old_memory=context.memories.pop(a["id"],{})
        for key in ("hunger","inventory","reserved","carry_capacity","starvation_started_at",
                    "next_starvation_damage_at","_starvation_due_at","type_profile","role_profile","profile"):
            a.pop(key,None)
        a.update(type="Zombie",status="ACTIVE",role=None,effects={},cooldowns={},active_action=None,
                 profile={},type_profile=deepcopy(context.config.get("profiles",{}).get("Zombie",{})),
                 model_assignment=assignment)
        a["_generation"]+=1
        a["_hunger_generation"]=a.get("_hunger_generation",0)+1
        if active:
            active["actor_after_end"]=context._capture_action_agent(a["id"],after=True)
        context._mark("agents",a["id"])
        context._effects_buffer.append({"kind":"conversion","agent_id":a["id"],"agent":a["id"],"episode_id":eid,
                                     "before_state":before,"after_state":deepcopy(a),
                                     "retired_model":old_model,"retired_memory":old_memory})
        context._schedule_decision(a["id"],context.time)



class EffectRules:
    def __init__(self, context):
        self.context = context

    def _effect(self,agentid,kind,value,duration,source):
        context = self.context
        a=context._touch(agentid)
        if a["life"]==0:
            return None
        end=context.time+clock(duration)
        matching=next((key for key,e in a["effects"].items() if e["kind"]==kind and float(e["value"])==float(value)),None)
        key=matching or (kind if kind not in a["effects"] else context._id(kind))
        if matching:
            end=max(end,clock(a["effects"][key]["end_at"]))
        a["effects"][key]={"kind":kind,"value":value,"start_at":stamp(context.time),"end_at":stamp(end),"source":source}
        context._schedule(end,0,"expire",agentid,effect=key)
        context._effects_buffer.append({"kind":"effect_applied","agent":agentid,"effect":deepcopy(a["effects"][key])})
        return key



class SignalRules:
    def __init__(self, context):
        self.context = context

    def _broadcast(self,actorid,kind,payload,radius,ttl,source):
        context = self.context
        a=context._touch(actorid)
        recipients=[]
        for other in context._nearby(point(a),float(radius)):
            if other==actorid:
                continue
            candidate=context._view_agent(other)
            if candidate["life"]>0 and math.dist(point(a),point(candidate))<=float(radius):
                recipients.append(other)
        sid=context._id("signal")
        context.state["signals"][sid]={"id":sid,"sender_id":actorid,"sender_type_at_emission":a["type"],
                                     "position_at_emission":[a["x"],a["y"]],"radius":float(radius),
                                     "kind":kind,"payload":deepcopy(payload),"emitted_at":stamp(context.time),
                                     "expires_at":stamp(context.time+clock(ttl)),"recipients":recipients,"source":source}
        context._mark("signals",sid)
        context._schedule(context.time+clock(ttl),0,"signal_expire",signal=sid)
        context._effects_buffer.append({"kind":"signal_emitted","agent":actorid,"signal":sid,"recipients":recipients})
        return sid



class GeometryRules:
    def __init__(self, context):
        self.context = context

    def _geometry_changed(self):
        """Schedule actual future contacts, ending motion 0.01 m before contact."""
        context = self.context
        from ..geometry import blocking
        for occurrence in list(context.occurrences.values()):
            if occurrence["result"]!="IN_PROGRESS" or occurrence["action"] not in {"move","dash"}:
                continue
            a=context._touch(occurrence["actor"])
            now_offset=context.time-clock(occurrence["start_at"])
            remaining=[{"x":a["x"],"y":a["y"],"offset":stamp(now_offset)}]
            remaining.extend(p for p in occurrence["parameters"]["path"] if clock(p["offset"])>now_offset)
            travelled=0.
            collision=None
            for left,right in zip(remaining,remaining[1:]):
                length=math.dist(point(left),point(right))
                for b in context.state["barriers"].values():
                    if not blocking(b):
                        continue
                    interval=_segment_contact(point(left),point(right),list(map(float,b["footprint"])))
                    if interval is not None:
                        distance=travelled+length*float(interval[0])
                        if collision is None or distance<collision:
                            collision=distance
                travelled+=length
            if collision is None:
                continue
            stop_distance=max(0.,collision-.01)
            covered=0.
            stop=context.time
            for left,right in zip(remaining,remaining[1:]):
                length=math.dist(point(left),point(right))
                if covered+length>=stop_distance and length>0:
                    fraction=(stop_distance-covered)/length
                    stop=clock(occurrence["start_at"])+clock(left["offset"])+(clock(right["offset"])-clock(left["offset"]))*Fraction(str(fraction))
                    break
                covered+=length
            if stop<=context.time:
                context._finish(occurrence,"PARTIAL_BLOCKED")
            else:
                context._schedule(stop,0,"blocked",a["id"],occurrence=occurrence["id"])



