#!/usr/bin/env python3
"""CLI and compatibility facade for the Kotodama OKF knowledge base."""
from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from kotodama_kb.foundation import *  # noqa: F401,F403,E402
from kotodama_kb.reserved import *  # noqa: F401,F403,E402
from kotodama_kb.load import *  # noqa: F401,F403,E402
from kotodama_kb.project import *  # noqa: F401,F403,E402
from kotodama_kb.retrieve import *  # noqa: F401,F403,E402
from kotodama_kb.audit import *  # noqa: F401,F403,E402
from kotodama_kb.verdicts import *  # noqa: F401,F403,E402
from kotodama_kb.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
