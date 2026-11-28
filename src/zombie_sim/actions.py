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
    """Retired extension name; new actions use ActionHandler/ActionHandlerRegistry."""
    def __init_subclass__(cls, **kwargs):
        from .core.migration import unsupported_extension
        unsupported_extension('ActionSystemMixin')
