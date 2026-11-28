"""Portable JSON/TOML scenario exchange shared by CLI and the workspace."""
import json
from copy import deepcopy
import tomllib
from .config import ConfigError
from .role_allocation import validate_role_allocation


class ConfigurationCodec:
    """Portable scenario encoding with shared role-allocation validation."""
    def dumps(self, config, format="json"):
        config = deepcopy(config)
        validate_role_allocation(config, ConfigError)
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


    def loads(self, text,format="json"):
        if format == "json": config = json.loads(text)
        elif format == "toml": config = tomllib.loads(text)
        else: raise ValueError("Configuration format must be JSON or TOML")
        validate_role_allocation(config, ConfigError)
        return config


_default_service = ConfigurationCodec()


def dumps(config, format='json'):
    """Compatibility entry point; see :class:`ConfigurationCodec`."""
    return _default_service.dumps(config, format)


def loads(text, format='json'):
    """Compatibility entry point; see :class:`ConfigurationCodec`."""
    return _default_service.loads(text, format)
