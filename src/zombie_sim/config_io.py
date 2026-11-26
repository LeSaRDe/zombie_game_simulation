"""Portable JSON/TOML scenario exchange shared by CLI and the workspace."""
import json
import tomllib


def dumps(config, format="json"):
    if format == "json": return json.dumps(config, indent=2, allow_nan=False)
    if format != "toml": raise ValueError("Configuration format must be JSON or TOML")
    def value(item):
        if item is None: raise ValueError("TOML has no null array element")
        if isinstance(item,bool): return "true" if item else "false"
        if isinstance(item,(int,float,str)): return json.dumps(item,ensure_ascii=False,allow_nan=False)
        if isinstance(item,list): return "["+", ".join(value(child) for child in item)+"]"
        if isinstance(item,dict): return "{ "+", ".join(json.dumps(str(key))+" = "+value(child) for key,child in item.items() if child is not None)+" }"
        raise TypeError(type(item).__name__)
    return "\n".join(json.dumps(str(key))+" = "+value(item) for key,item in config.items() if item is not None)+"\n"


def loads(text,format="json"):
    if format == "json": return json.loads(text)
    if format == "toml": return tomllib.loads(text)
    raise ValueError("Configuration format must be JSON or TOML")
