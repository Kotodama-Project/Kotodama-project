#!/usr/bin/env python3
"""Small shared helper for deterministic UTF-8 JSON output without overwrite."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def output_target_available(path: Path | None) -> bool:
    if path is None:
        return True
    try:
        return not path.exists() and path.parent.is_dir()
    except OSError:
        return False


def emit_json(value: dict[str, Any], output_path: Path | None) -> bool:
    line = json.dumps(value, sort_keys=True) + "\n"
    if output_path is not None:
        try:
            with output_path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
        except (OSError, UnicodeError):
            return False
    try:
        sys.stdout.buffer.write(line.encode("utf-8"))
    except (OSError, UnicodeError):
        return False
    return True
