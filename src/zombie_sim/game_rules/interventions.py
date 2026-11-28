"""InterventionRules: isolated semantic evaluation over a planning/read workspace."""
from __future__ import annotations
from copy import deepcopy
from ..geometry import point_blocked
from .primitives import clock, stamp, RESOURCES


class InterventionRules:
    def __init__(self, context):
        self.context = context

    def intervene(self,change,at=None,id=None):
        context = self.context
        if not context.config.get("interventions_enabled",False):
            raise ValueError("This frozen scenario does not authorize interventions")
        when=context.time if at is None else clock(at)
        if when<context.time:
            raise ValueError("Interventions cannot alter committed history")
        iid=id
        if iid is not None and iid in context.state["interventions"]:
            if context.state["interventions"][iid]["change"]!=change:
                raise ValueError("Intervention identity already names a different command")
            return deepcopy(context.state["interventions"][iid])
        if change.get("kind")=="replace_model":
            from ..domain import decision_model_assignment
            agent=context.state["agents"][str(change["agent"])]
            if agent["life"]==0:
                raise ValueError("Dead identities cannot receive active assignments")
            decision_model_assignment(change["model_id"],change.get("model_version"),agent_type=agent["type"])
        iid=iid or context._id("intervention")
        item={"id":iid,"at":stamp(when),"change":deepcopy(change),"status":"PENDING"}
        context.state["interventions"][iid]=item
        context._mark("interventions",iid)
        context._schedule(when,4,"intervention",intervention=iid)
        context._commit("intervention_scheduled",intervention=iid)
        return deepcopy(item)

    def _apply_intervention(self,iid):
        context = self.context
        from ..registry import ROLES
        from ..policies import create_model
        item=context.state["interventions"][iid]
        change=item["change"]
        # Validation failures must not leave half a role/capacity/resource change.
        rollback=(context.state.fork(),deepcopy(context.memories),list(context.queue),context._serial,
                  set(context._decision_due),list(context._effects_buffer),set(context._dirty),context._counter,
                  deepcopy(context._identity_counters),deepcopy(context._runtime_queue_delta))
        try:
            kind=change["kind"]
            if kind=="add_resource":
                resource=change.get("resource",change.get("resource_type"))
                quantity=change["quantity"]
                if resource not in RESOURCES or type(quantity) is not int or quantity<=0:
                    raise ValueError("Resource addition requires a portable resource and positive integer quantity")
                sid=change.get("stockpile")
                if sid in context.state["stockpiles"]:
                    context.state["stockpiles"][sid]["inventory"][resource]+=quantity
                    context._mark("stockpiles",sid)
                else:
                    x,y=float(change["x"]),float(change["y"])
                    if not 0<=x<=context.state["world"]["length"] or not 0<=y<=context.state["world"]["width"] or point_blocked((x,y),context.state["barriers"]):
                        raise ValueError("Resource location is not traversable")
                    actual=context._drop({"id":"intervention","x":x,"y":y},{resource:quantity})
                    if sid:
                        context.state["stockpiles"][sid]=context.state["stockpiles"].pop(actual)
                        context.state["stockpiles"][sid]["id"]=sid
                        context._mark("stockpiles",actual);context._mark("stockpiles",sid)
            elif kind in {"replace_role","replace_model"}:
                aid=str(change["agent"])
                a=context._touch(aid)
                if a["life"]==0:
                    raise ValueError("Dead identities cannot receive active assignments")
                if kind=="replace_role":
                    role=change.get("role")
                    if role is not None and (role not in ROLES or ROLES[role]["type"]!=a["type"]):
                        raise ValueError("Incompatible role")
                    old=a.get("role")
                    old_role_actions=set(ROLES.get(old,{}).get("actions",[]))
                    current=context.occurrences.get(a.get("active_action"))
                    if current and current["action"] in old_role_actions:
                        context._finish(current,"CANCELLED_BY_INTERVENTION")
                    a["role"]=role;a["role_profile"]={};a["_generation"]+=1
                    a["effects"]={k:v for k,v in a["effects"].items() if v["kind"] not in {"guard","recon","dash"}}
                    a["next_charge_at"]=None
                    if role=="SPITTER":
                        a.update(spit_charges=int(ROLES[role].get("max_spit_charges",3)),reserved_charges=0)
                    elif old=="SPITTER":
                        a.pop("spit_charges",None);a.pop("reserved_charges",None)
                    if a["type"]=="Human":
                        a["carry_capacity"]=int(ROLES.get(role,{}).get("carry_capacity",10))
                        excess=max(0,sum(a["inventory"].values())-a["carry_capacity"])
                        dropped={}
                        for resource in change.get("drop_order",["MATERIAL","FOOD","MEDICAL_SUPPLY"]):
                            if resource not in RESOURCES:raise ValueError("Invalid capacity-drop resource")
                            amount=min(excess,a["inventory"][resource]-a["reserved"][resource])
                            a["inventory"][resource]-=amount;excess-=amount;dropped[resource]=amount
                        if excess:
                            current=context.occurrences.get(a.get("active_action"))
                            if current:context._finish(current,"CANCELLED_BY_INTERVENTION")
                            for resource in RESOURCES:
                                amount=min(excess,a["inventory"][resource]);a["inventory"][resource]-=amount;excess-=amount;dropped[resource]=dropped.get(resource,0)+amount
                        context._drop(a,dropped)
                else:
                    from ..domain import decision_model_assignment
                    assignment=decision_model_assignment(change["model_id"],change.get("model_version"),agent_type=a["type"])
                    policy=change.get("memory_policy")
                    if policy not in {"reset","preserve"}:
                        raise ValueError("Model replacement requires reset or preserve memory policy")
                    a["model_assignment"]=assignment
                    if policy=="reset":context.memories.pop(aid,None)
            else:
                raise ValueError("Unknown intervention kind")
            item.update(status="APPLIED",effective_time=stamp(context.time),effective_revision=context.revision+1)
        except (KeyError,ValueError,TypeError) as exc:
            (context.state,context.memories,context.queue,context._serial,context._decision_due,context._effects_buffer,
             context._dirty,context._counter,context._identity_counters,context._runtime_queue_delta)=rollback
            context.occurrences,context.intents=context.state["occurrences"],context.state["intents"]
            item=context.state["interventions"][iid]
            item.update(status="REJECTED",reason=str(exc))
        context._mark("interventions",iid)
        context._commit("intervention",intervention=iid,status=item["status"],change=change)
