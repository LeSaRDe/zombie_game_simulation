"""Typed future work and biological dispatch; no event-loop or storage authority."""
from fractions import Fraction
import heapq
from ..domain_model import ScheduledTask
from ..domain import profile
from .primitives import clock, stamp

class ScheduleRules:
    def __init__(self, context):
        self.context = context

    def _schedule(self, time, phase, kind, agent=None, **fields):
        context = self.context
        time = clock(time)
        if time < context.time:
            raise ValueError("Cannot schedule in the past")
        context._serial += 1
        key = f"{kind}:{agent}:{fields.get('occurrence', '')}:{stamp(time)}:{context._serial}"
        priority = context._random("event-arbitration", key)
        row=ScheduledTask.from_record((time, phase, priority, context._serial, {"kind": kind, "agent": agent, **fields}))
        heapq.heappush(context.queue,row)
        from ..value_codec import encode_value as _encode
        context._runtime_queue_delta.append(["set",["queue",str(context._serial)],_encode(row)])


    def _schedule_decision(self, aid, when):
        context = self.context
        token = (aid, stamp(when))
        if context.decision_mode not in {"scripted","external"} and token not in context._decision_due:
            context._decision_due.add(token)
            context._schedule(when, 6, "decision", aid)


    def _schedule_starvation(self,a):
        context = self.context
        generation = a.setdefault("_hunger_generation",0)
        rate = Fraction(str(profile(a,stamp(context.time)).get("hunger_rate",.05)))
        hunger = Fraction(str(a.get("hunger",20)))
        if rate == 0 and hunger < 100:
            return
        begins = context.time+(100-hunger)/rate if hunger < 100 else context.time
        a["starvation_started_at"] = stamp(begins) if hunger == 100 else None
        due = begins+10
        a["_starvation_due_at"] = stamp(due)
        a["next_starvation_damage_at"] = stamp(due) if hunger == 100 else None
        context._schedule(due,2,"starvation",a["id"],generation=generation)


    def _dispatch(self,event):
        context = self.context
        kind,aid=event["kind"],event.get("agent")
        if kind == "complete":
            context._resolve(event["occurrence"])
        elif kind == "starvation":
            a=context._touch(aid)
            if a["life"] > 0 and a["type"]=="Human" and a.get("_hunger_generation",0)==event["generation"]:
                a["hunger"]=100.
                a["starvation_started_at"]=a.get("starvation_started_at") or stamp(context.time-10)
                context._damage(aid,1,"starvation",bypass=True)
                if a["life"] > 0:
                    a["next_starvation_damage_at"]=stamp(context.time+10)
                    a["_starvation_due_at"]=stamp(context.time+10)
                    context._schedule(context.time+10,2,"starvation",aid,generation=event["generation"])
                context._commit("starvation",agent=aid)
        elif kind == "conversion":
            a=context._touch(aid)
            if a["life"] > 0 and a.get("infection_episode")==event["episode"]:
                context._convert(a)
                context._commit("conversion",agent=aid,episode=event["episode"])
        elif kind == "recharge":
            a=context._touch(aid)
            if a["life"]>0 and a.get("role")=="SPITTER" and a["_generation"]==event["generation"]:
                p=profile(a,stamp(context.time)); maximum=int(p.get("max_spit_charges",3))
                a["spit_charges"]=min(maximum,a["spit_charges"]+1)
                a["next_charge_at"]=None
                if a["spit_charges"]<maximum:
                    a["next_charge_at"]=stamp(context.time+clock(p.get("recharge_interval",30)))
                    context._schedule(a["next_charge_at"],2,"recharge",aid,generation=a["_generation"])
                context._commit("recharge",agent=aid)
        elif kind == "expire":
            a=context._touch(aid)
            effect=a["effects"].get(event["effect"])
            if effect and clock(effect["end_at"])<=context.time:
                del a["effects"][event["effect"]]
                context._commit("effect_expired",agent=aid,effect=event["effect"])
        elif kind == "intervention":
            context._apply_intervention(event["intervention"])
        elif kind == "blocked":
            occurrence=context.occurrences.get(event["occurrence"])
            if occurrence and occurrence["result"]=="IN_PROGRESS":
                context._finish(occurrence,"PARTIAL_BLOCKED")
                context._commit("movement_blocked",occurrence=occurrence["id"])
        elif kind == "signal_expire":
            sid=event["signal"]
            if sid in context.state["signals"]:
                del context.state["signals"][sid]
                context._mark("signals",sid)
                context._commit("signal_expired",signal=sid)

