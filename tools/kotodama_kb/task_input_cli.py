"""Lazy source-checkout CLI adapter for an explicitly selected existing Task."""
from __future__ import annotations

import copy
from pathlib import Path
import sys

# This is executable source, distinct from the user-selected knowledge root.
# Query/show never import this module or the Task runtime.
SOURCE_ROOT = Path(__file__).resolve().parents[2]
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from runtime.task_swarm.closed_loop import ScriptedSimulation
from runtime.task_swarm.protocol import SwarmError, canonical, digest
from runtime.task_swarm.task_contract import MAX_INPUT_BYTES, require, shape
from runtime.task_swarm.task_runner import read_json

from .foundation import KnowledgeBaseError, _assert_current, _parse_as_of
from .load import load_bundle
from .task_input import compile_task_input, execute_task_input, verify_task_input


def _candidate(args):
    # The producer bounds canonical JSON; allow the CLI's one-byte LF frame.
    value = read_json(args.candidate, MAX_INPUT_BYTES + 1)
    shape(value, {"payload", "supplied_plan", "seed_digest", "source_checks",
                  "context_projection", "diagnostics"}
          | ({"learning"} if isinstance(value, dict) and "learning" in value else set()),
          "TASK_CONTEXT_CANDIDATE_INVALID")
    projection = value["context_projection"]
    require(isinstance(projection, dict) and isinstance(projection.get("as_of"), str),
            "TASK_CONTEXT_CANDIDATE_INVALID")
    return value


def _execute(args, bundle, candidate):
    if args.operation == "compile":
        if getattr(args, "learning_origin", None) is not None:
            from .task_input_learning import compile_task_learning_input
            origin = read_json(args.learning_origin, 32768)
            shape(origin, {"origin_owner", "origin_input", "origin_anchor", "claim_index"},
                  "TASK_LEARNING_ORIGIN_INVALID")
            return compile_task_learning_input(bundle, read_json(args.input, MAX_INPUT_BYTES),
                                               args.owner, **origin), 0
        return compile_task_input(bundle, read_json(args.input, MAX_INPUT_BYTES), args.owner), 0
    learning = "learning" in candidate
    decision = getattr(args, "learning_decision_digest", None)
    require(learning == (decision is not None), "TASK_LEARNING_DECISION_REQUIRED")
    if args.operation == "verify":
        if learning:
            from .task_input_learning import verify_task_learning_input
            require(getattr(args, "input", None) is not None, "TASK_LEARNING_INPUT_REQUIRED")
            payload = verify_task_learning_input(bundle, candidate, args.owner, args.input,
                                                decision_digest=decision)
        else:
            require(getattr(args, "input", None) is None, "TASK_LEARNING_CANDIDATE_REQUIRED")
            payload = verify_task_input(bundle, candidate, args.owner)
        return {"status": "binding_and_learning_verified" if learning else "binding_verified", "task_id": payload["task_id"],
                "revision": payload["revision"], "payload_digest": digest(payload)}, 0
    scenario = read_json(args.simulation, 1024 * 1024)
    backend = ScriptedSimulation(scenario)
    repair = scenario["repair_plan"]
    execute = execute_task_input
    options = {}
    if learning:
        from .task_input_learning import execute_task_learning_input
        execute = execute_task_learning_input
        options["decision_digest"] = decision
    result = execute(bundle, candidate, args.owner, args.input, backend,
        worker_actors=args.worker, critic_actor=args.critic,
        repair_planner=(lambda _gap: copy.deepcopy(repair)) if repair is not None else None,
        expected_receipt_sha256=args.receipt_sha256, **options)
    return result, 0 if result["receipt"]["review_passed"] else 3


def _emit(value, stream):
    """Keep JSON UTF-8 and LF framing independent of terminal text settings."""
    data = (value + "\n").encode("utf-8")
    buffer = getattr(stream, "buffer", None)
    if buffer is None:
        # In-memory text streams have no encoding or newline translation.
        stream.write(data.decode("utf-8"))
        stream.flush()
    else:
        stream.flush()
        buffer.write(data)
        buffer.flush()


def run(args):
    """Emit one complete JSON result, or one typed refusal on stderr."""
    try:
        candidate = None if args.operation == "compile" else _candidate(args)
        as_of = _parse_as_of(args.as_of if candidate is None else candidate["context_projection"]["as_of"])
        if candidate is not None and args.as_of is not None:
            require(_parse_as_of(args.as_of) == as_of, "TASK_CONTEXT_AUDIT_INSTANT_CHANGED")
        # Preserve the projection's audit instant, but load current bytes and
        # leave every execution/owner/Concept expiry check on the real clock.
        bundle = load_bundle(args.root, as_of=as_of)
        result, code = _execute(args, bundle, candidate)
        output = canonical(result)
        _assert_current(bundle)
    except SwarmError as exc:
        refusal = {"error": exc.code, "message": exc.detail}
    except KnowledgeBaseError as exc:
        refusal = {"error": "KNOWLEDGE_INPUT_REFUSED", "message": str(exc)}
    except OSError:
        refusal = {"error": "TASK_CONTEXT_FILE_UNAVAILABLE", "message": "Local input could not be read"}
    except (ValueError, UnicodeError, RecursionError):
        refusal = {"error": "TASK_CONTEXT_INPUT_INVALID", "message": "Bounded UTF-8 JSON input required"}
    else:
        _emit(output, sys.stdout)
        return code
    _emit(canonical(refusal), sys.stderr)
    return 2
