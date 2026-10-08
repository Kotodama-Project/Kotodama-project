"""Public candidate API; Task ownership remains with the calling application."""
from .task_swarm.protocol import SwarmError, canonical, digest

__version__ = "0.2.0.dev0"
__all__ = ["__version__", "SwarmError", "canonical", "digest"]
