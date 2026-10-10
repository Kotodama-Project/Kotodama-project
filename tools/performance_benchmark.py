#!/usr/bin/env python3
"""Measure a fixed offline Kotodama fixture; no arbitrary commands or providers."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
from performance_benchmark.runner import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
