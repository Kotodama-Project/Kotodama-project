"""Lazy source-checkout CLI adapter for an explicitly selected existing Task."""
from __future__ import annotations

import copy
import hashlib
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


def _inspection_supported(args, value=None):
    if any(getattr(args, key, None) is not None for key in
           ("learning_origin", "learning_decision_digest")):
        raise SwarmError("TASK_INPUT_INSPECT_LEARNING_UNSUPPORTED", "Read-only inspection does not evaluate learning decisions")
    require(getattr(args, "input", None) is None, "TASK_INPUT_INSPECT_EXTRA_INPUT_UNSUPPORTED")
    if isinstance(value, dict) and "learning" in value:
        raise SwarmError("TASK_INPUT_INSPECT_LEARNING_UNSUPPORTED", "Read-only inspection does not evaluate learning decisions")


def _inspection_candidate(args):
    _inspection_supported(args)
    value, sha = read_json(args.candidate, MAX_INPUT_BYTES + 1, with_digest=True)
    require(isinstance(value, dict), "TASK_CONTEXT_CANDIDATE_INVALID")
    _inspection_supported(args, value)
    shape(value, {"payload", "supplied_plan", "seed_digest", "source_checks",
                  "context_projection", "diagnostics"}, "TASK_CONTEXT_CANDIDATE_INVALID")
    projection = value["context_projection"]
    require(isinstance(projection, dict) and isinstance(projection.get("as_of"), str),
            "TASK_CONTEXT_CANDIDATE_INVALID")
    return value, sha


def _inspection_report(bundle, payload):
    """Derive reference facts from the verified payload and actual Concepts."""
    from runtime.task_swarm.task_planning import _Sources
    from .strategy import strategy_model, strategy_reference_issues
    from .task_input import _declaration, _definition_span, _record

    sources = _Sources(payload)
    declaration = _declaration(payload)
    graph, issues = strategy_model(bundle.concepts)
    require(not issues, "TASK_CONTEXT_REFERENCE_UNRESOLVED")
    references = payload["objective"]["references"]
    require(isinstance(references, list) and 1 <= len(references) <= 20,
            "OBJECTIVE_REFERENCES_INVALID")
    fields = {"goal": "goal_refs", "kgi": "kgi_refs", "initiative": "initiative_refs"}
    rows = []
    for reference in references:
        kind, identifier = reference["kind"], reference["id"]
        require(kind in fields and not strategy_reference_issues(
            {fields[kind]: [identifier]}, graph["definitions"], path="task-input inspect"),
            "TASK_CONTEXT_REFERENCE_UNRESOLVED")
        definition = graph["definitions"][identifier]
        concept = bundle.by_id[definition["concept_id"]]
        source = _record(payload, declaration["catalog_bindings"][concept.concept_id])
        require(source["text"] == concept.document.raw
                and canonical(reference["source"]) == canonical(_definition_span(source, identifier))
                and sources.span(reference["source"]) == identifier, "TASK_CONTEXT_SOURCE_CHANGED")
        rows.append({"kind": kind, "id": identifier, "definition_kind": definition["kind"],
            "concept": {"id": concept.concept_id,
                "title": concept.metadata["title"],
                "path": concept.document.path.relative_to(bundle.root).as_posix(),
                "content_sha256": concept.content_sha256, "knowledge_state": concept.extension["knowledge_state"],
                "adoption_status": concept.extension["strategy"]["adoption_status"],
                "stale_after": concept.stale_after},
            "source": {**reference["source"], "sha256": source["sha256"],
                       "offset_unit": "unicode_codepoints", "revision_scope": "task_input_source"}})

    def bound(span, *, current=True):
        text = sources.span(span, current=current)
        return {**span, "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "offset_unit": "unicode_codepoints", "revision_scope": "task_input_source"}

    objective = payload["objective"]
    return {"kind": "kotodama.task-input-inspection", "status": "binding_verified",
        "scope": "normal_task_candidate", "decision_readiness": "NEEDS_RESOLUTION",
        "task": {"id": payload["task_id"], "revision": payload["revision"],
                 "payload_digest": digest(payload), "owner_ref": objective["owner_ref"]},
        "source_digest": bundle.source_digest, "as_of": bundle.as_of.isoformat().replace("+00:00", "Z"),
        "authority": {"task_input_binding": "VERIFIED", "source_bytes": "VERIFIED",
            "actor_execution_authorization": "NOT_EVALUATED", "current_learning_decision": "NOT_EVALUATED",
            "external_goal_revision": "UNRESOLVED", "external_goal_adoption": "UNRESOLVED",
            "external_goal_access": "UNRESOLVED", "actual_outcome_acceptance": "NOT_EVALUATED"},
        "references": rows, "objective": {
            "intent": {"original": bound(objective["intent"]["original"], current=False),
                       "replacements": [bound(s, current=False) for s in objective["intent"]["replacements"]],
                       "history_authority": "input_only_unverified"},
            **{key: [bound(s) for s in objective[key]] for key in ("constraints", "unknowns", "acceptance")},
            **{key: copy.deepcopy(objective[key]) for key in ("budget", "stop_conditions", "rollback")}},
        "next_actions": {"concept_read": ["show", "CONCEPT_ID", "--root", "SAME_ROOT", "--json"],
            "external_adoption": "Resolve the existing Goal/KGI adoption-owner locator; this inspection cannot grant authority."}}


def _inspection_output(report, format):
    require(format in ("json", "markdown"), "TASK_INPUT_INSPECT_FORMAT_INVALID")
    if format == "json":
        return canonical(report)
    def cell(value):
        return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ").replace("`", "\\`")
    lines = ["# Task input inspection", "",
        f"Task: {report['task']['id']} / revision {report['task']['revision']}",
        f"Payload SHA-256: {report['task']['payload_digest']}",
        "Readiness: **NEEDS_RESOLUTION**. Actor execution and learning decision: **NOT_EVALUATED**.",
        "External Goal revision, adoption and access: **UNRESOLVED**.", "",
        "| Kind | ID | Concept title / path | Source revision / Unicode span |",
        "|---|---|---|---|"]
    for row in report["references"]:
        source = row["source"]
        values = (row["kind"], row["id"], row["concept"]["title"] + " (" + row["concept"]["path"] + ")",
                  f"{source['source_key']} @ {source['source_revision']} [{source['start']}:{source['end']}]")
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    lines.extend(["", "## Exact reference and objective metadata", "", "```json", canonical(report), "```", "",
        "Open the listed Concept with `show CONCEPT_ID --root SAME_ROOT --json`.",
        "This read-only view does not evaluate current execution permission or accept the requested outcome."])
    return "\n".join(lines)


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
    if args.operation == "inspect":
        _inspection_supported(args, candidate)
        return _inspection_report(bundle, verify_task_input(bundle, candidate, args.owner)), 0
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
    return result, 0 if result.get("receipt") and result["receipt"]["review_passed"] else 3


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
        inspecting = args.operation == "inspect"
        if inspecting:
            candidate, candidate_sha = _inspection_candidate(args)
            _, owner_sha = read_json(args.owner, 1024 * 1024, with_digest=True)
        else:
            candidate = None if args.operation == "compile" else _candidate(args)
        as_of = _parse_as_of(args.as_of if candidate is None else candidate["context_projection"]["as_of"])
        if candidate is not None and args.as_of is not None:
            require(_parse_as_of(args.as_of) == as_of, "TASK_CONTEXT_AUDIT_INSTANT_CHANGED")
        # Preserve the projection's audit instant, but load current bytes and
        # leave every execution/owner/Concept expiry check on the real clock.
        bundle = load_bundle(args.root, as_of=as_of)
        result, code = _execute(args, bundle, candidate)
        output = _inspection_output(result, args.format) if inspecting else canonical(result)
        if inspecting:
            require(len((output + "\n").encode("utf-8")) <= MAX_INPUT_BYTES, "TASK_INPUT_INSPECT_OUTPUT_LIMIT")
            final = verify_task_input(bundle, candidate, args.owner)
            require(digest(final) == result["task"]["payload_digest"], "TASK_CONTEXT_INPUT_CHANGED")
            require(read_json(args.candidate, MAX_INPUT_BYTES + 1, with_digest=True)[1] == candidate_sha,
                    "TASK_INPUT_INSPECT_CANDIDATE_CHANGED")
            require(read_json(args.owner, 1024 * 1024, with_digest=True)[1] == owner_sha,
                    "TASK_INPUT_INSPECT_OWNER_CHANGED")
        _assert_current(bundle)
    except SwarmError as exc:
        refusal = {"error": exc.code, "message": exc.detail}
        if exc.code in {"TASK_INPUT_INSPECT_LEARNING_UNSUPPORTED", "TASK_INPUT_INSPECT_EXTRA_INPUT_UNSUPPORTED"}:
            refusal.update(inspection_status="UNSUPPORTED", decision_readiness="NEEDS_RESOLUTION",
                           current_learning_decision="NOT_EVALUATED")
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
