"""Reuse bounded local reads for candidate integration contracts."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from knowledge_work_validator import QuietParser, read_bound
from validate_resolved_compose_candidate import load_strict_json_bytes

MAX_BYTES = 256 * 1024
MAX_DEPTH = 32


def load_contract(root: Path, relative: str | Path) -> dict[str, Any]:
    value = load_strict_json_bytes(read_bound(root, str(relative), MAX_BYTES))
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH or isinstance(node, float) and not math.isfinite(node):
            raise ValueError("invalid contract JSON")
        children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
        stack.extend((child, depth + 1) for child in children)
    return value


def local_schema_references_only(schema: Any) -> bool:
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in ("$ref", "$dynamicRef", "$recursiveRef"):
                if key in node and (not isinstance(node[key], str) or not node[key].startswith("#")):
                    return False
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return True
