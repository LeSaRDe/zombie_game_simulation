"""Pure time, geometry and numeric helpers; no coordinator or persistence."""
from fractions import Fraction
import math

def clock(value):
    if isinstance(value, bool):
        raise ValueError("A Boolean is not a semantic time")
    result = Fraction(str(value))
    if result < 0:
        raise ValueError("Semantic time must be nonnegative")
    return result


def stamp(value):
    value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else str(value)


def point(obj):
    return float(obj["x"]), float(obj["y"])


def half_up(value):
    return max(0, math.floor(Fraction(str(value)) + Fraction(1,2)))


def _segment_contact(a,b,rectangle):
    """Closed rectangle intersection interval, including tangential contacts."""
    lower,upper=0.,1.
    for origin,delta,minimum,maximum in ((a[0],b[0]-a[0],rectangle[0],rectangle[2]),
                                        (a[1],b[1]-a[1],rectangle[1],rectangle[3])):
        if delta==0:
            if origin<minimum or origin>maximum:return None
            continue
        lo,hi=(minimum-origin)/delta,(maximum-origin)/delta
        if lo>hi:lo,hi=hi,lo
        lower=max(lower,lo);upper=min(upper,hi)
        if lower>upper:return None
    return lower,upper


def _visible_surface(here,radius,barrier,barriers):
    """Clip surfaces at circle and occluder silhouette boundaries.

    Midpoint classification is valid only after splitting at every visibility
    transition. Endpoints outside the closed LOS contract are moved inward.
    """
    from ..geometry import blocking, distance_to, segment_clear
    x0,y0,x1,y1=map(float,barrier["footprint"])
    corners=[(x0,y0),(x1,y0),(x1,y1),(x0,y1)]
    facing=[here[1]<y0,here[0]>x1,here[1]>y1,here[0]<x0]
    occluders=[b for b in barriers.values() if b["id"]!=barrier["id"] and blocking(b) and distance_to(here,b)<=radius]
    portions=[]
    cross=lambda a,b:a[0]*b[1]-a[1]*b[0]
    for index,(u,v) in enumerate(zip(corners,corners[1:]+corners[:1])):
        if blocking(barrier) and not facing[index]:continue
        d=(v[0]-u[0],v[1]-u[1]);offset=(u[0]-here[0],u[1]-here[1])
        a=d[0]**2+d[1]**2
        if not a:continue
        b=2*(offset[0]*d[0]+offset[1]*d[1]);c=offset[0]**2+offset[1]**2-radius**2
        discriminant=b*b-4*a*c
        if discriminant<0:continue
        root=math.sqrt(discriminant)
        lower=max(0.,(-b-root)/(2*a));upper=min(1.,(-b+root)/(2*a))
        if lower>=upper:continue
        cuts={lower,upper}
        for obstacle in occluders:
            ox0,oy0,ox1,oy1=obstacle["footprint"]
            for corner in ((ox0,oy0),(ox1,oy0),(ox1,oy1),(ox0,oy1)):
                ray=(corner[0]-here[0],corner[1]-here[1]);denominator=cross(d,ray)
                if not denominator:continue
                t=cross((-offset[0],-offset[1]),ray)/denominator
                scale=cross((-offset[0],-offset[1]),d)/denominator
                if scale>=0 and lower<t<upper:cuts.add(t)
        coordinates=lambda t:(u[0]+d[0]*t,u[1]+d[1]*t)
        clear=lambda t:segment_clear(here,coordinates(t),occluders)
        ordered=sorted(cuts)
        for start,end in zip(ordered,ordered[1:]):
            middle=(start+end)/2
            if not clear(middle):continue
            # Closed obstacles hide tangent rays too. No hidden endpoint is
            # exposed merely because the open interior of a segment is visible.
            if not clear(start):start+=(end-start)*1e-9
            if not clear(end):end-=(end-start)*1e-9
            if start<end and clear(start) and clear(end):
                portions.append([coordinates(start),coordinates(end)])
    return portions


RESOURCES = ("FOOD", "MEDICAL_SUPPLY", "MATERIAL")


ATTACKS = {"melee", "power_strike", "claw", "bite", "spit"}


RULES = {
    "move": (None, 0, 0, None), "wait": (None, 0, 0, None), "rest": (None, 0, 0, None),
    "signal": (.5, 1, 2, None), "melee": (1, 6, 1, 1.5),
    "pickup": (1, 1, 0, 1.5), "drop": (.5, 0, 0, None), "transfer": (1, 1, 0, 1.5),
    "eat": (2, 0, 0, None), "first_aid": (3, 4, 2, 1.5),
    "open_gate": (1, 1, 0, 2), "close_gate": (1, 1, 0, 2),
    "claw": (1, 6, 1, 1.5), "bite": (1.5, 10, 2, 1.5),
    "feed": (3, 0, 1, 1.5), "smash": (2, 10, 2, 2),
    "treat_infection": (4, 6, 2, 1.5), "prophylaxis": (4, 6, 2, 1.5),
    "power_strike": (1.5, 15, 6, 1.5), "guard": (1, 8, 8, None),
    "recon": (2, 6, 20, None), "mark_target": (.5, 1, 3, None),
    "build_barricade": (8, 12, 2, 2), "repair_barrier": (5, 8, 1, 2),
    "rally": (2, 15, 20, None), "demolish": (3, 18, 6, 2),
    "dash": (1, 12, 8, None), "spit": (1, 8, 8, 12), "scream": (2, 15, 30, None),
}

