"""Explicit pure codecs for continuation value types, not arbitrary Python classes."""
from fractions import Fraction
from collections.abc import Mapping
from pathlib import Path
import json
import math

def canonical(value):
    def mapping_record(item):
        if isinstance(item, Mapping):
            return dict(item)
        raise TypeError(f'Cannot serialize {type(item).__name__}')
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False,default=mapping_record)

def _encode(value):
    from .domain_model import ScheduledTask
    if isinstance(value, ScheduledTask):
        return _encode(value.as_legacy_tuple())
    if isinstance(value,Fraction):
        return {"$runtime_type":"fraction","numerator":value.numerator,"denominator":value.denominator}
    if isinstance(value,Path):
        return {"$runtime_type":"path","value":str(value)}
    if isinstance(value,set):
        encoded=[_encode(v) for v in value]
        return {"$runtime_type":"set","items":sorted(encoded,key=canonical)}
    if isinstance(value,tuple):
        return {"$runtime_type":"tuple","items":[_encode(v) for v in value]}
    if isinstance(value,list):
        return [_encode(v) for v in value]
    if isinstance(value,Mapping):
        if not all(isinstance(k,str) for k in value):
            return {"$runtime_type":"mapping","items":[[_encode(k),_encode(v)] for k,v in value.items()]}
        if "$runtime_type" in value:
            return {"$runtime_type":"mapping","items":[[k,_encode(v)] for k,v in value.items()]}
        return {k:_encode(v) for k,v in value.items()}
    if value is None or isinstance(value,(str,bool,int)):
        return value
    if isinstance(value,float) and math.isfinite(value):
        return value
    raise TypeError(f"Runtime state must have an explicit JSON codec; unsupported {type(value).__name__}")


def _decode(value):
    if isinstance(value,list):
        return [_decode(v) for v in value]
    if not isinstance(value,dict):
        return value
    kind=value.get("$runtime_type")
    if kind=="fraction":
        return Fraction(int(value["numerator"]),int(value["denominator"]))
    if kind=="path":
        return Path(value["value"])
    if kind in ("set","tuple"):
        items=[_decode(v) for v in value["items"]]
        return set(items) if kind=="set" else tuple(items)
    if kind=="mapping":
        return {_decode(k):_decode(v) for k,v in value["items"]}
    if kind=="unavailable_model_memory":return value
    if kind is not None:
        raise ValueError(f"Unsupported runtime codec {kind!r}")
    return {k:_decode(v) for k,v in value.items()}


encode_value = _encode
decode_value = _decode
