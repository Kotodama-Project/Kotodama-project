#!/usr/bin/env python3
"""Explicit read-only candidate hierarchy and saved normal-run trace."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

# Executable code and operator-selected Source root are separate inputs.
sys.dont_write_bytecode = True
TOOLS = Path(__file__).resolve().parent
sys.path[:0] = [str(TOOLS), str(TOOLS.parent)]

from kotodama_kb.foundation import KnowledgeBaseError
from kotodama_kb.hierarchy_reader import trace_current_refs
from kotodama_kb.load import load_bundle
from runtime.task_swarm.protocol import SwarmError, canonical
from runtime.task_swarm.task_contract import MAX_INPUT_BYTES
from runtime.task_swarm.task_runner import read_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Existing knowledge/Source checkout")
    parser.add_argument("--owner", type=Path, required=True, help="Existing operator-supplied Task owner")
    parser.add_argument("--input", type=Path, required=True, help="Current owner-bound Task input")
    parser.add_argument("--request", type=Path, required=True, help="Explicit bounded hierarchy trace request")
    args = parser.parse_args(argv)
    try:
        result, raw = trace_current_refs(load_bundle(args.root), read_json(args.input, MAX_INPUT_BYTES),
                                        args.owner, read_json(args.request, MAX_INPUT_BYTES), with_bytes=True)
    except SwarmError as exc:
        refusal = {"status": "REFUSED", "error": exc.code, "context_candidate": None}
    except KnowledgeBaseError:
        refusal = {"status": "REFUSED", "error": "KNOWLEDGE_INPUT_REFUSED", "context_candidate": None}
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        refusal = {"status": "REFUSED", "error": "HIERARCHY_INPUT_UNAVAILABLE_OR_INVALID", "context_candidate": None}
    else:
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()
        return 3 if result["status"] == "BLOCKED" else 0
    sys.stderr.buffer.write((canonical(refusal) + "\n").encode("utf-8"))
    sys.stderr.buffer.flush()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
