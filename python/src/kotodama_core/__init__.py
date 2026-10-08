"""Public candidate API; Task ownership remains with the calling application."""
import math

from .task_swarm.protocol import SwarmError, canonical as _canonical, digest as _digest

__version__ = "0.2.0.dev0"
__all__ = ["__version__", "SwarmError", "canonical", "digest"]


def _json_value(value, active=None, depth=0):
    if active is None:
        active = set()
    if depth > 64:
        raise SwarmError("INVALID_DOCUMENT", "JSON nesting limit exceeded")
    kind = type(value)
    if kind is str:
        try:
            value.encode("utf-8")
        except UnicodeError:
            raise SwarmError("INVALID_DOCUMENT", "JSON text must be valid Unicode") from None
    elif value is None or kind in (bool, int):
        pass
    elif kind is float:
        if not math.isfinite(value):
            raise SwarmError("INVALID_DOCUMENT", "JSON numbers must be finite")
    elif kind in (dict, list):
        if id(value) in active:
            raise SwarmError("INVALID_DOCUMENT", "JSON cannot contain cycles")
        active.add(id(value))
        try:
            if kind is dict:
                for key, item in value.items():
                    if type(key) is not str:
                        raise SwarmError("INVALID_DOCUMENT", "JSON object keys must be strings")
                    _json_value(key, active, depth + 1)
                    _json_value(item, active, depth + 1)
            else:
                for item in value:
                    _json_value(item, active, depth + 1)
        finally:
            active.remove(id(value))
    else:
        raise SwarmError("INVALID_DOCUMENT", "only JSON values are accepted")


def canonical(value):
    """Serialize finite JSON values with string-only object keys, without coercion."""
    _json_value(value)
    return _canonical(value)


def digest(value):
    """Hash the existing canonical JSON implementation after strict admission."""
    _json_value(value)
    return _digest(value)
