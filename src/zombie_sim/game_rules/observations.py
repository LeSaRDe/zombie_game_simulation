"""ObservationBuilder: isolated semantic evaluation over a planning/read workspace."""
from __future__ import annotations
from copy import deepcopy
from fractions import Fraction
import math
from ..domain import profile, status
from ..geometry import segment_clear, distance_to
from .primitives import clock, stamp, point, _visible_surface


class ObservationBuilder:
    def __init__(self, context):
        self.context = context

    def _view_agent(self, aid):
        context = self.context
        a = context._evaluate(deepcopy(context.state["agents"][str(aid)]), context.time)
        a.update(profile(a, stamp(context.time)))
        a["status"] = status(a)
        a["action_state"] = "DEAD" if a["life"] == 0 else "BUSY" if a.get("active_action") else "IDLE"
        active = context.occurrences.get(a.get("active_action"))
        a["current_action"] = active["action"] if active else None
        if active and active["action"] == "dash":
            a["speed"] = float(Fraction(str(a["base_speed"]))*Fraction(str(a.get("dash_multiplier",1.5))))
        ep = context.state["episodes"].get(a.get("infection_episode"))
        if a["type"] == "Human":
            a["infection_progress"] = min(1., float((context.time-clock(ep["onset_at"]))/clock(ep["incubation_duration"]))) if ep else 0.
            if ep:
                a.update({k:ep[k] for k in ("onset_at","incubation_duration","conversion_due_at")})
        return a

    def snapshot(self):
        context = self.context
        result = deepcopy(context.state)
        result["agents"] = {aid: context._view_agent(aid) for aid in context.state["agents"]}
        result.update(time=stamp(context.time), revision=context.revision)
        return result

    def observe(self, aid):
        context = self.context
        observer = context._view_agent(aid)
        radius = float(observer["sense_r"])
        here = point(observer)
        visible = {}
        for other in context._nearby(here,radius):
            if other == str(aid):
                continue
            if context.state["agents"][other]["life"] == 0:
                continue
            location=context._position_cache[other]
            if math.dist(here,location)>radius or not segment_clear(here,location,context.state["barriers"]):
                continue
            a = context._view_agent(other)
            if a["life"] > 0:
                visible[other] = context._public(a)
        environment = {"barriers": {}, "stockpiles": {}, "remains": {}}
        for name in ("stockpiles", "remains"):
            for key, obj in context.state[name].items():
                nonempty = sum(obj.get("inventory",{}).values()) > 0 if name == "stockpiles" else obj["biomass"] > 0
                if nonempty and math.dist(here,point(obj)) <= radius and segment_clear(here,point(obj),context.state["barriers"]):
                    environment[name][key] = deepcopy(obj)
                    if name=="stockpiles":
                        environment[name][key]["available"]={resource:quantity-obj.get("reserved",{}).get(resource,0)
                                                               for resource,quantity in obj["inventory"].items()}
        for key, b in context.state["barriers"].items():
            if distance_to(here,b) > radius:
                continue
            portions=_visible_surface(here,radius,b,context.state["barriers"])
            if portions:
                # Only visible surface segments are exposed, not hidden corners.
                environment["barriers"][key] = {k: deepcopy(v) for k,v in b.items() if k != "footprint"}
                environment["barriers"][key]["visible_segments"] = portions
        signals = []
        for signal in context.state["signals"].values():
            if str(aid) not in signal["recipients"] or context.time >= clock(signal["expires_at"]):
                continue
            view = {k:deepcopy(v) for k,v in signal.items() if k not in {"recipients","payload"}}
            if observer["type"] == signal["sender_type_at_emission"]:
                view["payload"] = deepcopy(signal["payload"])
            else:
                view["kind"] = "NOISE"
            signals.append(view)
        return {"time":stamp(context.time),"task_horizon":stamp(context.horizon),"revision":context.revision,"world":deepcopy(context.state["world"]),
                "self_state":context._public(observer),"local_agents":visible,"local_environment":environment,
                "received_signals":signals}

    @staticmethod
    def _public(a):
        return {k:deepcopy(v) for k,v in a.items() if not k.startswith("_") and k not in {"memory","model_memory"}}

    def _nearby(self,position,radius):
        """Conservative swept-path buckets, followed by exact-time filtering.

        A movement's entire recorded path is in its broad-phase envelope. Thus
        time advancing never requires scanning every agent to update the grid.
        Admission, interruption, relocation and lifecycle writes invalidate only
        their actors. Candidates still use exact trajectory coordinates and LOS.
        """
        context = self.context
        cell_size = context._spatial_index.cell_size
        if getattr(context, '_spatial_time', None) != context.time:
            context._spatial_time = context.time
            context._position_cache = {}
        index = context._spatial_index
        for aid in getattr(context, '_runtime_spatial_dirty', ()):
            context._position_cache.pop(aid, None)
            agent = context.state['agents'].get(aid)
            if agent is None:
                index = index.with_agent(aid, None)
                continue
            occurrence = context.occurrences.get(agent.get('active_action'))
            path = occurrence['parameters']['path'] if occurrence and occurrence['action'] in {'move', 'dash'} else [agent]
            index = index.with_agent(aid, tuple((float(p['x']), float(p['y'])) for p in path))
        context._spatial_index = index
        context._runtime_spatial_dirty = set()
        candidates = index.candidates(position, radius)
        # Match the established point-grid order after exact-time evaluation.
        for aid in candidates:
            context._position_at(aid)
        return sorted(candidates, key=lambda aid: (
            math.floor(context._position_cache[aid][0]/cell_size),
            math.floor(context._position_cache[aid][1]/cell_size), index.order[aid]))
