"""Closed-rectangle collision predicates and deterministic visibility routing."""
from __future__ import annotations
import heapq
import math


def point(value):
    if isinstance(value, dict):
        if "position" in value:
            return point(value["position"])
        return float(value["x"]), float(value["y"])
    return float(value[0]), float(value[1])


def rect(value):
    if isinstance(value, dict):
        if "footprint" in value:
            return rect(value["footprint"])
        return tuple(float(value[k]) for k in ("xmin", "ymin", "xmax", "ymax"))
    return tuple(float(v) for v in value)


def blocking(barrier):
    kind = barrier.get("type", barrier.get("kind", "Obstacle"))
    if kind.lower() == "gate":
        return barrier.get("mode", "CLOSED") == "CLOSED"
    if kind.lower() == "barricade":
        return barrier.get("integrity", 0) > 0
    return barrier.get("blocks_movement", True)


def contains(footprint, p, *, strict=False):
    x0, y0, x1, y1 = rect(footprint); x, y = point(p)
    return x0 < x < x1 and y0 < y < y1 if strict else x0 <= x <= x1 and y0 <= y <= y1


def overlap(a, b, *, strict=False):
    a0,b0,a1,b1 = rect(a); c0,d0,c1,d1 = rect(b)
    return max(a0,c0) < min(a1,c1) and max(b0,d0) < min(b1,d1) if strict else max(a0,c0) <= min(a1,c1) and max(b0,d0) <= min(b1,d1)


def _values(barriers):
    return barriers.values() if isinstance(barriers, dict) else barriers


def point_blocked(p, barriers):
    return any(blocking(b) and contains(b, p) for b in _values(barriers))


def segment_intersects(a, b, footprint):
    """Liang–Barsky slab intersection including tangent and endpoint contact."""
    ax,ay = point(a); bx,by = point(b); x0,y0,x1,y1 = rect(footprint)
    low, high = 0.0, 1.0
    for start, delta, minimum, maximum in ((ax,bx-ax,x0,x1),(ay,by-ay,y0,y1)):
        if delta == 0:
            if not minimum <= start <= maximum:
                return False
            continue
        entry, leave = sorted(((minimum-start)/delta,(maximum-start)/delta))
        low, high = max(low,entry), min(high,leave)
        if low > high:
            return False
    return True


def segment_clear(a, b, barriers, ignore_id=None):
    return not any(blocking(ob) and (ignore_id is None or str(ob.get("id", ob.get("entity_id"))) != str(ignore_id)) and segment_intersects(a,b,ob) for ob in _values(barriers))


def nearest_point(p, target):
    if isinstance(target, dict) and ("footprint" in target or "xmin" in target):
        x,y = point(p); x0,y0,x1,y1 = rect(target)
        return max(x0,min(x1,x)), max(y0,min(y1,y))
    return point(target)


def distance_to(p, target):
    a,b = point(p), nearest_point(p,target)
    return math.hypot(a[0]-b[0],a[1]-b[1])


def route(start, goal, barriers, bounds):
    """Shortest visibility-graph polyline with a small positive corner clearance.

    Returns waypoints excluding start, or [] when no route is found. Geometry
    predicates remain exact closed-footprint checks; clearance only selects legal
    route candidates and is not a collision tolerance.
    """
    start,goal = point(start),point(goal)
    width,height = (bounds["length"],bounds["width"]) if isinstance(bounds,dict) else bounds
    legal = lambda p: 0 <= p[0] <= width and 0 <= p[1] <= height and not point_blocked(p,barriers)
    if not legal(start) or not legal(goal):
        return []
    if segment_clear(start,goal,barriers):
        return [goal]
    eps = max(width,height,1) * 1e-8
    vertices = [start,goal]
    for barrier in _values(barriers):
        if not blocking(barrier):
            continue
        x0,y0,x1,y1 = rect(barrier)
        for p in ((x0-eps,y0-eps),(x0-eps,y1+eps),(x1+eps,y0-eps),(x1+eps,y1+eps)):
            if legal(p) and p not in vertices:
                vertices.append(p)
    distances = {0: 0}; previous = {}; queue = [(0,0)]; visited = set()
    while queue:
        length,index = heapq.heappop(queue)
        if index in visited:
            continue
        if index == 1:
            result=[]
            while index:
                result.append(vertices[index]); index=previous[index]
            return result[::-1]
        visited.add(index)
        for j,p in enumerate(vertices):
            if j in visited or j == index or not segment_clear(vertices[index],p,barriers):
                continue
            candidate=length+distance_to(vertices[index],p)
            if candidate < distances.get(j,float("inf")):
                distances[j]=candidate; previous[j]=index
                heapq.heappush(queue,(candidate,j))
    return []
