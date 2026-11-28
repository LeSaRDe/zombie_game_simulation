"""ContinuousEvolution: isolated semantic evaluation over a planning/read workspace."""
from __future__ import annotations
from fractions import Fraction
import math
from ..domain import profile
from .primitives import clock, stamp, point


class ContinuousEvolution:
    def __init__(self, context):
        self.context = context

    def _evaluate(self, a, at):
        context = self.context
        previous = clock(a.get("_evaluated_at", 0))
        if at <= previous or a["life"] == 0:
            return a
        elapsed = float(at-previous)
        p = profile(a, stamp(at))
        if a["type"] == "Human":
            before_hunger=Fraction(str(a.get("hunger",20)))
            rate=Fraction(str(p.get("hunger_rate",.05)))
            a["hunger"]=float(min(Fraction(100),before_hunger+rate*(at-previous)))
            if a["hunger"]==100 and before_hunger<100 and rate>0:
                a["starvation_started_at"]=stamp(previous+(100-before_hunger)/rate)
            if a["hunger"]==100:
                a["next_starvation_damage_at"]=a.get("_starvation_due_at",a.get("next_starvation_damage_at"))
        active = context.occurrences.get(a.get("active_action"))
        if active:
            end = min(at, clock(active["planned_end"]))
            start = clock(active["start_at"])
            if active["action"] == "rest":
                a["stamina"] = min(100., float(a["stamina"]) + float(p.get("rest_rate", 4 if a["type"] == "Human" else 3))*float(max(Fraction(0), end-max(previous,start))))
            elif active["action"] in {"move", "dash"}:
                coords, travelled = context._path_position(active, end)
                used = max(0., travelled-float(a.get("_travelled", 0)))
                a["stamina"] = max(0., float(a["stamina"])-used*float(p.get("movement_cost", .1)))
                a["x"], a["y"] = coords
                a["_travelled"] = travelled
        a["_evaluated_at"] = stamp(at)
        return a

    def _touch(self, aid):
        context = self.context
        a = context.state["agents"][str(aid)]
        context._evaluate(a, context.time)
        context._mark("agents", aid)
        return a

    def _path_position(self, occurrence, time):
        context = self.context
        points = occurrence["parameters"]["path"]
        offset = max(Fraction(0), time-clock(occurrence["start_at"]))
        travelled = 0.
        for left, right in zip(points, points[1:]):
            t0, t1 = clock(left["offset"]), clock(right["offset"])
            length = math.dist(point(left), point(right))
            if offset >= t1:
                travelled += length
                continue
            fraction = min(1., max(0., float((offset-t0)/(t1-t0))))
            return ((float(left["x"])+(float(right["x"])-float(left["x"]))*fraction,
                     float(left["y"])+(float(right["y"])-float(left["y"]))*fraction), travelled+length*fraction)
        return point(points[-1]), travelled

    def _position_at(self,aid):
        context = self.context
        if aid not in context._position_cache:
            agent=context.state["agents"][aid];occurrence=context.occurrences.get(agent.get("active_action"))
            context._position_cache[aid]=context._path_position(occurrence,context.time)[0] if occurrence and occurrence["action"] in {"move","dash"} else point(agent)
        return context._position_cache[aid]
