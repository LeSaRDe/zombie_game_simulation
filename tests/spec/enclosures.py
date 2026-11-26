"""Explicit gate enclosure fixtures, approved on 2026-11-25.

This is test arrangement only: no simulator calls or expected-outcome logic.
The gate spans the west side of a rectangular shelter. Three nonoverlapping
walls close the other sides. Existing gate coordinates and actor positions stay
unchanged, including corner-approach and doorway-occupancy examples.
"""
from copy import deepcopy
from decimal import Decimal


def with_gate_enclosures(setup, *, depth="8", thickness="0.1"):
    setup=deepcopy(setup)
    for gate in list(setup.get("barriers",[])):
        if gate.get("kind")!="Gate":continue
        x0,y0,x1,y1=map(Decimal,gate["rect"])
        # Deliberately malformed rectangles test their own domain validation.
        # Do not make a second malformed enclosure obscure that test input.
        if not (0<=x0<x1<Decimal(setup["length"]) and 0<y0<y1<Decimal(setup["width"])):continue
        d,t=Decimal(depth),Decimal(thickness)
        east=min(x1+d,Decimal(setup["length"])-t)
        sid="shelter-"+gate["id"]
        walls=[("south",[x1,y0-t,east+t,y0]),
               ("north",[x1,y1,east+t,y1+t]),
               ("east",[east,y0,east+t,y1])]
        gate["shelter_id"]=sid
        for name,rectangle in walls:
            setup["barriers"].append({"id":sid+"-"+name,"kind":"Obstacle","rect":[str(v) for v in rectangle]})
        setup.setdefault("shelters",[]).append({"id":sid,"interior":[str(v) for v in (x1,y0,east,y1)],
            "walls":[sid+"-"+name for name,_ in walls],"gates":[gate["id"]]})
    return setup
