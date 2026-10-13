"""Finite current-source hierarchy and saved execution proof, without dispatch.

Document references are candidates. A saved runtime Plan is historical artifact
consistency, never an organization Plan or a current execution authorization.
"""
from __future__ import annotations

import datetime as dt
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import time

import yaml

from runtime.task_swarm.closed_loop_context import derive_child_view, validate_report_in_view
from runtime.task_swarm.closed_loop_contract import (
    evidence_version, integration_candidate, learning_candidate, loop_criteria, required_evidence_jobs, validate_critic,
    validate_plan, work_input,
)
from runtime.task_swarm.owner_file import OwnerFile
from runtime.task_swarm.protocol import canonical, digest, digest_ref, integer, validate_binding
from runtime.task_swarm.task_contract import MAX_INPUT_BYTES, require, shape, validate_input
from runtime.task_swarm.task_planning import _Sources
from runtime.task_swarm.task_runner import read_bytes, read_json, safe_directory

from .foundation import (
    _assert_current, _bounded_tree, _parse_datetime, _parse_frontmatter,
    _read_bytes, _require_valid_bundle,
)
from .strategy import strategy_model


MAX_NODES, MAX_DEPTH, MAX_EDGES, MAX_PARENTS = 8, 2, 16, 2
MAX_ARTIFACT_FILES, MAX_ARTIFACT_BYTES = 32, 2 * 1024 * 1024
QUERY_SECONDS = 10
_ID = re.compile(r"[A-Za-z][A-Za-z0-9._:/-]{0,159}\Z")
_SPAN_KEYS = ("source_key", "source_revision", "start", "end")


def _copy(value):
    _bounded_tree(value)
    raw = canonical(value).encode("utf-8")
    require(len(raw) <= MAX_INPUT_BYTES, "HIERARCHY_INPUT_LIMIT")
    return json.loads(raw)


def _exact(left, right):
    # Python equality aliases bool/int/float. Saved JSON must retain the exact
    # current types and nested values even when the caller re-anchors a file.
    return canonical(left) == canonical(right)


def _identifier(value):
    require(isinstance(value, str) and _ID.fullmatch(value), "HIERARCHY_ID_INVALID")
    return value


def _record(payload, entry):
    span = {key: entry[key] for key in ("source_key", "source_revision")}
    _Sources(payload).span({**span, "start": 0, "end": 1})
    return next(row for row in payload["sources"]
                if (row["key"], row["revision"]) == (span["source_key"], span["source_revision"]))


def _span(source, start, end):
    raw = source["text"]
    require(0 <= start < end <= len(raw), "HIERARCHY_SPAN_INVALID")
    return {"source_key": source["key"], "source_revision": source["revision"],
            "start": start, "end": end, "line": raw.count("\n", 0, start) + 1,
            "end_line": raw.count("\n", 0, end - 1) + 1, "text": raw[start:end],
            "sha256": hashlib.sha256(raw[start:end].encode("utf-8")).hexdigest()}


def _yaml_spans(source, document):
    lines = document.raw.splitlines(keepends=True)
    closing = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    offset = len(lines[0])
    frontmatter = "".join(lines[1:closing])
    require(not any(isinstance(token, yaml.AliasToken) for token in yaml.scan(frontmatter)),
            "HIERARCHY_DECLARATION_ALIAS")
    root = yaml.compose(frontmatter, Loader=yaml.SafeLoader)
    require(isinstance(root, yaml.MappingNode), "HIERARCHY_FIELDS_REQUIRED")
    fields = {key.value: value for key, value in root.value}
    def record(node):
        return _span(source, offset + node.start_mark.index, offset + node.end_mark.index)
    result = {key: record(fields[key]) for key in ("id", "template_kind", "status")}
    parents = []
    if "parent_refs" in fields:
        require(isinstance(fields["parent_refs"], yaml.SequenceNode), "HIERARCHY_PARENT_INVALID")
        parents = [record(node) for node in fields["parent_refs"].value]
    elif "parent_ref" in fields:
        parents = [record(fields["parent_ref"])]
    return result, parents


def _statement(source, statement, body_start):
    require(isinstance(statement, str) and bool(statement.strip()) and len(statement) <= 1000,
            "HIERARCHY_STATEMENT_INVALID")
    start = source["text"].find(statement, body_start)
    require(start >= body_start and source["text"].find(statement, start + 1) == -1,
            "HIERARCHY_STATEMENT_AMBIGUOUS")
    return _span(source, start, start + len(statement))


def _nodes(bundle, payload, entries):
    require(isinstance(entries, list) and 1 <= len(entries) <= MAX_NODES, "HIERARCHY_NODE_LIMIT")
    nodes, checks, paths = {}, {}, set()
    for entry in entries:
        shape(entry, {"path", "source_key", "source_revision"}, "HIERARCHY_NODE_INVALID")
        name = entry["path"]
        require(isinstance(name, str) and 0 < len(name) <= 4096 and "\\" not in name
                and not Path(name).is_absolute() and not PureWindowsPath(name).drive
                and ".." not in Path(name).parts, "HIERARCHY_PATH_INVALID")
        path = bundle.root / name
        safe_directory(path.parent)
        require(path.resolve().is_relative_to(bundle.root) and path.resolve() not in paths,
                "HIERARCHY_PATH_INVALID")
        paths.add(path.resolve())
        source = _record(payload, entry)
        document = _parse_frontmatter(path, bundle.root)
        require(document.raw == source["text"], "HIERARCHY_SOURCE_CHANGED")
        meta = document.frontmatter
        identifier, kind = _identifier(meta.get("id")), meta.get("template_kind")
        require(identifier not in nodes, "HIERARCHY_ID_AMBIGUOUS")
        require(isinstance(kind, str) and kind in {"project", "phase", "requirement"} and meta.get("status") == "draft"
                and "{{" not in document.raw, "HIERARCHY_KIND_UNRESOLVED")
        require(not ("parent_ref" in meta and "parent_refs" in meta), "HIERARCHY_PARENT_CONFLICT")
        parents = meta.get("parent_refs", [meta["parent_ref"]] if "parent_ref" in meta else [])
        require(isinstance(parents, list) and len(parents) <= MAX_PARENTS, "HIERARCHY_PARENT_LIMIT")
        require(all(isinstance(parent, str) and _ID.fullmatch(parent) for parent in parents)
                and len(set(parents)) == len(parents), "HIERARCHY_PARENT_INVALID")
        require(not parents if kind == "project" else bool(parents), "HIERARCHY_PARENT_REQUIRED")
        fields = meta.get("task_context")
        expected = {"constraints", "need", "acceptance"} if kind == "requirement" else {"constraints"}
        require(isinstance(fields, dict) and expected <= fields.keys()
                and fields.keys() <= expected | {"frontier"}, "HIERARCHY_FIELDS_REQUIRED")
        require(isinstance(fields["constraints"], list) and len(fields["constraints"]) <= 20,
                "HIERARCHY_STATEMENT_LIMIT")
        start = len(document.raw) - len(document.body)
        statements = {"constraints": [_statement(source, value, start) for value in fields["constraints"]]}
        if kind == "requirement":
            require(isinstance(fields["acceptance"], list) and 1 <= len(fields["acceptance"]) <= 20,
                    "HIERARCHY_STATEMENT_LIMIT")
            statements.update(need=_statement(source, fields["need"], start),
                acceptance=[_statement(source, value, start) for value in fields["acceptance"]])
        metadata, parent_spans = _yaml_spans(source, document)
        checks[path] = hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
        require(hashlib.sha256(_read_bytes(path)).hexdigest() == checks[path], "HIERARCHY_SOURCE_CHANGED")
        nodes[identifier] = {"id": identifier, "kind": kind, "path": path.relative_to(bundle.root).as_posix(),
            "source_key": source["key"], "source_revision": source["revision"], "source_sha256": source["sha256"],
            "parents": parents, "parent_spans": parent_spans, "metadata_spans": metadata,
            "statements": statements, "document_state": "candidate", "authority": "projection_only",
            "selection_reason": "explicit_root_and_source_declared_ancestor",
            "opaque_frontier": fields.get("frontier")}
    return nodes, checks


def _closure(nodes, root_id):
    require(root_id in nodes and nodes[root_id]["kind"] == "requirement", "HIERARCHY_ROOT_UNRESOLVED")
    visited, edges = set(), []
    def visit(identifier, stack):
        require(identifier not in stack, "HIERARCHY_PARENT_CYCLE")
        require(len(stack) <= MAX_DEPTH, "HIERARCHY_DEPTH_LIMIT")
        node = nodes[identifier]
        for parent in node["parents"]:
            require(parent in nodes, "HIERARCHY_PARENT_UNRESOLVED")
            require(nodes[parent]["kind"] in ({"project"} if node["kind"] == "phase"
                                             else {"phase", "project"}), "HIERARCHY_PARENT_KIND")
            visit(parent, [*stack, identifier])
        visited.add(identifier)
    visit(root_id, [])
    require(visited == set(nodes), "HIERARCHY_UNUSED_NODE")
    reverse = {identifier: [] for identifier in nodes}
    for identifier in sorted(nodes):
        node = nodes[identifier]
        for parent, source in zip(node["parents"], node["parent_spans"]):
            reverse[parent].append(identifier)
            edges.append({"from": identifier, "to": parent, "relation": "structural_parent_candidate",
                          "source": source})
    require(len(edges) <= MAX_EDGES, "HIERARCHY_EDGE_LIMIT")
    # IDs and sources are deliberately retained even when constraint text is identical.
    constraints = [span for identifier in sorted(nodes) for span in nodes[identifier]["statements"]["constraints"]]
    unique = {tuple(span[key] for key in _SPAN_KEYS) for span in constraints}
    require(len(unique) <= 32, "HIERARCHY_CONTEXT_LIMIT")
    return sorted(visited), reverse, edges, constraints


def _concepts(bundle, payload, now):
    """Only Concepts already supplied verbatim by this owner; no retrieval/import."""
    matched, sources = {}, _Sources(payload)
    for concept in bundle.concepts:
        rows = [row for row in payload["sources"] if row["text"] == concept.document.raw
                and row["revision"] == sources.latest[row["key"]]]
        require(len(rows) <= 1, "HIERARCHY_CATALOG_AMBIGUOUS")
        if not rows:
            continue
        require(concept.metadata.get("status") != "deprecated" and concept.extension.get("knowledge_state")
                not in {"unknown", "conflicted", "deprecated", "revoked"}, "HIERARCHY_CATALOG_UNRESOLVED")
        require(concept.stale_after is None or dt.datetime.fromtimestamp(now, dt.timezone.utc) <
                _parse_datetime(concept.stale_after, field="stale_after", path=concept.concept_id),
                "HIERARCHY_CONTEXT_EXPIRED")
        matched[concept.concept_id] = rows[0]
    graph, issues = strategy_model(bundle.concepts)
    require(not issues, "HIERARCHY_STRATEGY_UNRESOLVED")
    for reference in payload.get("objective", {}).get("references", []):
        definition = graph["definitions"].get(reference["id"])
        expected_kind = "metric" if reference["kind"] == "kgi" else reference["kind"]
        require(definition is not None and definition["kind"] == expected_kind
                and (reference["kind"] != "kgi" or definition.get("measurement_role") == "product_outcome"),
                "HIERARCHY_STRATEGY_UNRESOLVED")
        row = matched.get(definition["concept_id"])
        require(row is not None and (reference["source"]["source_key"], reference["source"]["source_revision"])
                == (row["key"], row["revision"]), "HIERARCHY_STRATEGY_UNRESOLVED")
    return [{"concept_id": identifier, "source_key": row["key"], "source_revision": row["revision"],
             "source_sha256": row["sha256"], "adoption": "candidate",
             "declared_status": bundle.by_id[identifier].metadata.get("status"),
             "declared_knowledge_state": bundle.by_id[identifier].extension.get("knowledge_state"),
             "stale_after": bundle.by_id[identifier].stale_after}
            for identifier, row in sorted(matched.items())]


def _objective_records(payload):
    """Render already validated intent history and unknowns, never a new interpretation."""
    rows = {(row["key"], row["revision"]): row for row in payload["sources"]}
    def record(span):
        return _span(rows[(span["source_key"], span["source_revision"])], span["start"], span["end"])
    objective = payload.get("objective")
    if objective is None:
        return {"intent_history": [], "unknowns": [], "purpose_references": []}
    return {"intent_history": [{"role": "original", **record(objective["intent"]["original"])},
            *[{"role": "replacement", **record(span)} for span in objective["intent"]["replacements"]]],
            "unknowns": [record(span) for span in objective["unknowns"]],
            "purpose_references": [{"kind": ref["kind"], "id": ref["id"], "source": record(ref["source"])}
                                   for ref in objective["references"]]}


def _contains(view, span):
    return any(record["source_key"] == span["source_key"] and record["source_revision"] == span["source_revision"]
               and record["start"] <= span["start"] < span["end"] <= record["end"] for record in view["spans"])


def _saved_plan(owner, payload, binding, owner_sha, reference, required_spans, check_deadline,
                resources, current_sources):
    """Inspect one completed run; legacy synthetic proof stays file-only."""
    shape(reference, {"kind", "id", "revision", "mandatory", "receipt_sha256"}, "HIERARCHY_REFERENCE_INVALID")
    expected_id = "task-run-" + digest([payload["task_id"], payload["revision"]])[:32]
    require(reference["id"] == expected_id and type(reference["revision"]) is int
            and reference["revision"] == payload["revision"], "HIERARCHY_PLAN_STALE")
    digest_ref(reference["receipt_sha256"])
    root = safe_directory(owner.storage()["root"])
    require(Path(binding["active_home"]).is_absolute() and Path(binding["active_home"]).resolve() == root,
            "RUN_HOME_MISMATCH")
    directory = safe_directory(root / expected_id)
    receipt, sha = read_json(directory / "receipt.json", MAX_INPUT_BYTES, with_digest=True)
    require(sha == reference["receipt_sha256"], "RUN_REPLAY_ANCHOR_CHANGED")
    require(isinstance(receipt, dict) and receipt.get("run_id") == expected_id
            and receipt.get("binding_digest") == digest(binding) and receipt.get("owner_input_sha256") == owner_sha
            and receipt.get("parent_input_digest") == digest(payload), "RUN_REPLAY_CONFLICT")
    require(receipt.get("synthetic") is True and receipt.get("model_runtime_verified") is False
            and receipt.get("task_state_changed") is False, "HIERARCHY_PROOF_SCOPE")
    manifest = receipt.get("artifact_sha256")
    require(isinstance(manifest, dict) and 3 <= len(manifest) <= MAX_ARTIFACT_FILES,
            "RUN_RECEIPT_INVALID")
    values, checks, total = {}, {directory / "receipt.json": sha}, 0
    for name, expected in manifest.items():
        require(isinstance(name, str) and re.fullmatch(r"[a-zA-Z0-9_-]+\.json", name), "RUN_RECEIPT_INVALID")
        digest_ref(expected)
        raw = read_bytes(directory / name, MAX_ARTIFACT_BYTES - total)
        total += len(raw)
        require(hashlib.sha256(raw).hexdigest() == expected, "RUN_ARTIFACT_CHANGED")
        value, actual = read_json(directory / name, with_digest=True)
        require(actual == expected, "RUN_ARTIFACT_CHANGED")
        _bounded_tree(value)
        values[name], checks[directory / name] = value, expected
        check_deadline()
    require(type(receipt.get("artifact_bytes")) is int and total == receipt["artifact_bytes"],
            "LOOP_ARTIFACT_BUDGET")
    require({"input.json", "specification.json", "plan.json", "execution.json", "candidate.json",
             "r0-critic-template.json"} <= values.keys(), "RUN_RECEIPT_INVALID")
    template = values["r0-critic-template.json"]
    if isinstance(template, dict) and any(key.startswith("executor_") for key in template):
        from .hierarchy_execution import saved_executor_plan
        proof, actors, final_guard = saved_executor_plan(owner, payload, binding, owner_sha,
            directory, receipt, sha, values, required_spans, check_deadline, resources, current_sources)
        return proof, checks, actors, final_guard
    require(type(receipt.get("rounds")) is int and receipt["rounds"] == 1,
            "HIERARCHY_REPAIR_UNRESOLVED")
    require("context-binding.json" not in values and "extension.json" not in values,
            "HIERARCHY_CURRENT_DECISION_UNRESOLVED")
    require(_exact(values["input.json"], payload), "RUN_REPLAY_CONFLICT")
    specification = validate_plan(values["specification.json"], payload)
    require(digest(specification) == receipt.get("initial_plan_digest"), "RUN_REPLAY_CONFLICT")
    initial_digest, runtime = digest(specification), values["plan.json"]
    shape(runtime, {"run_id", "task_id", "binding_digest", "budget", "jobs"}, "HIERARCHY_PLAN_INVALID")
    require(runtime["run_id"] == expected_id and runtime["task_id"] == payload["task_id"]
            and runtime["binding_digest"] == digest(binding), "HIERARCHY_PLAN_INVALID")
    actors, critic_actor = receipt.get("worker_actors"), receipt.get("critic_actor")
    require(isinstance(actors, list) and len(specification["jobs"]) <= len(actors) <= 3
            and all(isinstance(actor, str) for actor in actors) and isinstance(critic_actor, str)
            and len(set([*actors, critic_actor, binding["owner_ref"]])) == len(actors) + 2,
            "RUN_OWNER_INDEPENDENCE")
    actor_bindings = {actor: owner.read_binding(payload["task_id"], actor) for actor in [*actors, critic_actor]}
    for actor, current in actor_bindings.items():
        validate_binding(current, now=owner.clock(), actor=actor)
        require(current["capability_ref"] == binding["capability_ref"], "RUN_ACTOR_SCOPE_INVALID")
    template, selected, expected_jobs, inputs, reports = values["r0-critic-template.json"], {}, [], {}, {}
    for job in sorted(specification["jobs"], key=lambda item: item["job_id"]):
        delivered = work_input(payload, job, 0, initial_digest, round_plan_digest=initial_digest)
        name = delivered["job_id"]
        inputs[name] = delivered
        expected_jobs.append({"job_id": name, "kind": "work", "dependencies": [], "exclusive_keys": [],
            "payload_ref": "ref/loop/input/" + name, "payload_digest": digest(delivered)})
        for span in job["selected_spans"]:
            selected[tuple(span[key] for key in _SPAN_KEYS)] = span
    require(len(selected) <= 32, "LOOP_CONTEXT_LIMIT")
    expected_template = {"role": "critic", "job_id": "r0-critic", "round": 0,
        "round_plan_digest": initial_digest, "criteria": loop_criteria(payload),
        "view": derive_child_view(payload, "r0-critic", list(selected.values()), plan_digest=initial_digest),
        "repair_planning_contract": 1, "repair_impact_sha256": None,
        "evidence_contract_version": 2, "required_evidence_jobs": required_evidence_jobs(payload, specification)}
    require(_exact(template, expected_template), "LOOP_DISPATCH_TEMPLATE_MISMATCH")
    expected_jobs.append({"job_id": "r0-critic", "kind": "review", "dependencies": sorted(inputs),
        "exclusive_keys": [], "payload_ref": "ref/loop/template/r0-critic", "payload_digest": digest(template)})
    require(_exact(runtime["jobs"], expected_jobs) and _exact(runtime["budget"], {
        **payload["objective"]["budget"], "concurrency": len(actors), "verifier_reserve": 1}), "HIERARCHY_PLAN_INVALID")
    require(type(receipt.get("version")) is int and evidence_version(runtime, template) == receipt["version"] == 2
            and receipt.get("coordinator") == "closed_loop_v2", "LOOP_EVIDENCE_POLICY")
    execution = values["execution.json"]
    require(isinstance(execution, dict) and execution.get("run_id") == expected_id
            and execution.get("task_id") == payload["task_id"] and execution.get("binding_digest") == digest(binding)
            and _exact(execution.get("plan"), runtime)
            and execution.get("extension") is None and set(execution.get("jobs", {})) == {j["job_id"] for j in expected_jobs},
            "HIERARCHY_EXECUTION_INVALID")
    dispatches = receipt.get("dispatches")
    require(isinstance(dispatches, dict) and set(dispatches) == {j["job_id"] for j in expected_jobs},
            "LOOP_DISPATCH_COVERAGE")
    invocations, context_bytes, delivered_proofs = set(), 0, []
    for number, job in enumerate(expected_jobs):
        name = job["job_id"]
        require({name + "-input.json", name + "-result.json"} <= values.keys(), "RUN_RECEIPT_INVALID")
        delivered, response = values[name + "-input.json"], values[name + "-result.json"]
        shape(response, {"result", "receipt"}, "LOOP_BACKEND_INVALID")
        shape(response["receipt"], {"actor_ref", "invocation_ref", "input_digest", "synthetic"}, "LOOP_RECEIPT_INVALID")
        proof = response["receipt"]
        actor = critic_actor if job["kind"] == "review" else actors[number]
        require(proof["actor_ref"] == actor and proof["input_digest"] == digest(delivered)
                and proof["synthetic"] is True and isinstance(proof["invocation_ref"], str)
                and proof["invocation_ref"] not in invocations, "LOOP_INPUT_RECEIPT_MISMATCH")
        invocations.add(proof["invocation_ref"])
        require(_exact(dispatches[name], {"declared_input_ref": job["payload_ref"],
            "declared_input_digest": job["payload_digest"], "delivered_input_digest": digest(delivered)}),
            "LOOP_DISPATCH_INPUT_MISMATCH")
        current = execution["jobs"][name]
        require(isinstance(current, dict) and all(_exact(current.get(key), value) for key, value in job.items())
                and current.get("state") in {"reported", "accepted"} and type(current.get("attempt_count")) is int
                and current["attempt_count"] == 1,
                "HIERARCHY_EXECUTION_INVALID")
        attempt = current.get("current_attempt")
        require(isinstance(attempt, dict) and attempt.get("state") == current["state"]
                and attempt.get("outcome") == "candidate" and attempt.get("result_digest") == manifest[name + "-result.json"]
                and attempt.get("result_ref") == "ref/loop/result/" + name
                and attempt.get("runtime_receipt_ref") == "ref/loop/receipt/" + name
                and attempt.get("worker_ref") == actor
                and _exact(attempt.get("identity"), {"kind": "native", "thread_id": proof["invocation_ref"]}),
                "HIERARCHY_EXECUTION_INVALID")
        context_bytes += len(canonical(delivered).encode("utf-8"))
        if job["kind"] == "work":
            require(_exact(delivered, inputs[name]), "LOOP_WORK_BINDING")
            reports[name] = validate_report_in_view(response["result"], delivered["view"], payload, allowed_jobs=inputs)
        else:
            require(_exact(delivered, {**template, "template_digest": digest(template), "reports": reports,
                "report_digests": {key: digest(report) for key, report in reports.items()}}), "LOOP_CRITIC_DISPATCH_MISMATCH")
            critic = validate_critic(response["result"], payload, reports, view=delivered["view"], plan_digest=initial_digest,
                round_index=0, initial_execution_plan_digest=digest(runtime), expected_jobs=tuple(inputs),
                dispatched_input=delivered, dispatched_input_digest=digest(delivered),
                initial_specification=specification, initial_runtime_plan=runtime, initial_template=template,
                work_inputs=inputs, execution_snapshot=execution)
            require(all(_contains(delivered["view"], span) and any(_contains(value["view"], span)
                        for value in inputs.values()) for span in required_spans), "HIERARCHY_PROOF_CONTEXT_MISSING")
        delivered_proofs.append({"job_id": name, "role": delivered["role"],
            "input_file_sha256": manifest[name + "-input.json"], "input_digest": digest(delivered),
            "result_file_sha256": manifest[name + "-result.json"], "view_digest": delivered["view"]["view_digest"]})
    require(type(receipt.get("context_bytes")) is int and context_bytes == receipt["context_bytes"]
            and context_bytes <= 512 * 1024, "LOOP_CONTEXT_BUDGET")
    complete = all(item["status"] == "passed" for item in critic["validations"])
    candidate = integration_candidate(payload, reports, critic, manifest["r0-critic-result.json"],
                                      stop_reason="review_complete" if complete else "unresolved_review")
    learning = learning_candidate(candidate) if candidate["status"] == "needs_owner_review" else None
    require(_exact(values["candidate.json"], candidate) and _exact(values.get("learning.json"), learning)
            and type(receipt.get("review_passed")) is bool and receipt["review_passed"] == (learning is not None),
            "HIERARCHY_CANDIDATE_CONFLICT")
    return {"kind": "runtime_plan", "id": expected_id, "entity_revision": payload["revision"],
        "revision_scope": "task_run", "status": "saved_artifact_consistency",
        "receipt_sha256": sha, "specification_digest": initial_digest, "execution_plan_digest": digest(runtime),
        "dispatches": delivered_proofs, "live_execution_state": "not_observed",
        "current_cancellation": "not_observed", "current_decision": "not_observed",
        "learning_artifact": "candidate_only" if "learning.json" in values else "absent"}, checks, actor_bindings, None


def trace_current_refs(bundle, input_payload, owner_path, request, *, clock=time.time, with_bytes=False):
    """Read an explicit current Source closure. All failures return no context.

    The bundle and input are supplied snapshots; bytes, current owner and real
    clock are checked again before returning. This API makes no writes.
    """
    with ExitStack() as resources:
        return _trace_current_refs(bundle, input_payload, owner_path, request,
                                   clock=clock, with_bytes=with_bytes, resources=resources)


def _trace_current_refs(bundle, input_payload, owner_path, request, *, clock, with_bytes, resources):
    started = time.monotonic()
    require(type(with_bytes) is bool, "HIERARCHY_REQUEST_INVALID")
    def deadline():
        require(time.monotonic() - started < QUERY_SECONDS, "HIERARCHY_QUERY_TIMEOUT")
    request, payload = _copy(request), _copy(input_payload)
    shape(request, {"version", "root_id", "nodes", "references"}, "HIERARCHY_REQUEST_INVALID")
    require(type(request["version"]) is int and request["version"] == 1, "HIERARCHY_REQUEST_INVALID")
    root_id = _identifier(request["root_id"])
    references = request["references"]
    require(isinstance(references, list) and len(references) <= 8, "HIERARCHY_REFERENCE_LIMIT")
    owner = OwnerFile(owner_path, clock=clock)
    owner_path = owner.path
    owner_document, owner_sha = read_json(owner_path, 1024 * 1024, with_digest=True)
    binding = owner.read_task(payload.get("task_id"))
    # Defer only the execution-budget expiry while an explicit receipt is being
    # authenticated. The completed executor branch must verify it before the
    # final check may use historical-read semantics; other paths keep the old
    # current-input deadline requirement.
    history_reference = any(isinstance(ref, dict) and ref.get("kind") == "runtime_plan"
                            and isinstance(ref.get("receipt_sha256"), str) for ref in references)
    payload = validate_input(payload, binding, now=clock(), allow_expired_objective=history_reference)
    _require_valid_bundle(bundle)
    _assert_current(bundle)
    declared = {str((owner_path.parent / item["path"]).resolve()): item["sha256"]
                for item in owner_document["source_checks"]}
    nodes, checks = _nodes(bundle, payload, request["nodes"])
    closure, reverse, edges, constraints = _closure(nodes, root_id)
    required_spans = [*constraints, nodes[root_id]["statements"]["need"],
                      *nodes[root_id]["statements"]["acceptance"]]
    require(len({tuple(span[key] for key in _SPAN_KEYS) for span in required_spans}) <= 32,
            "HIERARCHY_CONTEXT_LIMIT")
    checks.update({bundle.root / name: sha for name, sha in bundle.input_bindings})
    require(all(declared.get(str(path.resolve())) == sha for path, sha in checks.items()),
            "HIERARCHY_OWNER_CHECKS_REQUIRED")
    catalogs = _concepts(bundle, payload, clock())
    resolved, unresolved, actor_bindings, seen, final_guards = [], [], {}, set(), []
    def current_sources(*, allow_expired_objective=False):
        _assert_current(bundle)
        require(all(hashlib.sha256(read_bytes(path)).hexdigest() == sha for path, sha in checks.items()),
                "HIERARCHY_SOURCE_CHANGED")
        _concepts(bundle, payload, clock())
        validate_input(payload, owner.read_task(payload["task_id"]), now=clock(),
                       allow_expired_objective=allow_expired_objective)
        _assert_current(bundle)
        deadline()
    if "learning_reuse" in owner_document:
        unresolved.append({"kind": "learning_reuse", "reason": "CURRENT_DECISION_NOT_OBSERVED",
            "next_action": "use_current_learning_verifier", "mandatory": True})
    else:
        for row in payload["sources"]:
            try:
                proposal = json.loads(row["text"])
            except ValueError:
                continue
            if isinstance(proposal, dict) and proposal.get("kind") == "task_learning_reuse_proposal":
                unresolved.append({"kind": "learning_reuse", "source_key": row["key"],
                    "source_revision": row["revision"], "reason": "CURRENT_DECISION_NOT_OBSERVED",
                    "next_action": "use_current_learning_verifier", "mandatory": True})
    for node in nodes.values():
        if node["opaque_frontier"] is not None:
            unresolved.append({"kind": "frontier", "id": node["id"],
                "reason": "WORK_DECOMPOSITION_NOT_RESOLVED_BY_STRUCTURAL_READER",
                "next_action": "use_task_input_producer", "mandatory": True})
    for reference in references:
        require(isinstance(reference, dict) and type(reference.get("mandatory")) is bool,
                "HIERARCHY_REFERENCE_INVALID")
        shape(reference, {"kind", "id", "revision", "mandatory"}
              | ({"receipt_sha256"} if reference.get("kind") == "runtime_plan" else set()), "HIERARCHY_REFERENCE_INVALID")
        kind, identifier = reference["kind"], reference["id"]
        require(isinstance(kind, str) and 0 < len(kind) <= 64, "HIERARCHY_REFERENCE_INVALID")
        _identifier(identifier)
        integer(reference["revision"], "reference revision", minimum=0, maximum=2**53-1)
        require((kind, identifier) not in seen, "HIERARCHY_REFERENCE_DUPLICATE")
        seen.add((kind, identifier))
        if kind == "owner_task":
            require(identifier == binding["task_id"] and reference["revision"] == binding["revision"], "HIERARCHY_TASK_STALE")
            resolved.append({"kind": kind, "id": identifier, "entity_revision": binding["revision"],
                "revision_scope": "task_owner", "status": "current_owner_input_bound"})
        elif kind == "runtime_plan" and "learning_reuse" not in owner_document:
            proof, artifact_checks, actors, final_guard = _saved_plan(owner, payload, binding, owner_sha, reference,
                required_spans, deadline, resources, current_sources)
            checks.update(artifact_checks)
            actor_bindings.update(actors)
            resolved.append(proof)
            if final_guard is not None:
                final_guards.append(final_guard)
        else:
            unresolved.append({"kind": kind, "id": identifier, "revision": reference["revision"],
                "reason": "CURRENT_DECISION_NOT_OBSERVED" if kind == "runtime_plan" else "OWNER_OR_KIND_UNRESOLVED",
                "next_action": "use_current_learning_verifier" if kind == "runtime_plan"
                               else "resolve_kind_and_current_owner_binding",
                "mandatory": reference["mandatory"]})
        deadline()
    blocked = any(item["mandatory"] for item in unresolved)
    context = None if blocked else {"kind": "hierarchy_context_candidate", "root_id": root_id,
        "closure": closure, "constraints": constraints, "need": nodes[root_id]["statements"]["need"],
        "acceptance": nodes[root_id]["statements"]["acceptance"],
        "objective": payload.get("objective"), "request": payload["request"],
        **_objective_records(payload),
        "dispatch_ready": False, "producer_bridge": "requires_source_rederivation"}
    result = {"version": 1, "kind": "kotodama.hierarchy-trace", "status": "BLOCKED" if blocked else "TRACED_CANDIDATE",
        "task_id": payload["task_id"], "task_revision": payload["revision"], "binding_digest": digest(binding),
        "parent_input_digest": digest(payload), "owner_input_sha256": owner_sha, "source_digest": bundle.source_digest,
        "request_digest": digest(request), "nodes": [nodes[key] for key in sorted(nodes)],
        "edges": edges, "closure": closure, "reverse_refs": reverse, "catalog_bindings": catalogs,
        "resolved_references": resolved, "unresolved": unresolved, "context_candidate": context,
        "authority": "projection_only", "live_execution_state": "completed_cut_checked" if final_guards else "not_observed",
        "dispatch_performed": False,
        "organization_plan_resolved": False, "current_learning_decision": "not_observed"}
    result["trace_digest"] = digest(result)
    require(len(canonical(result).encode("utf-8")) <= MAX_INPUT_BYTES, "HIERARCHY_OUTPUT_LIMIT")
    result = _copy(result)  # Bounds the complete output, including diagnostics; no truncation.
    frame = (canonical(result) + "\n").encode("utf-8")
    deadline()
    require(owner.read_task(payload["task_id"]) == binding, "STALE_BINDING")
    require(read_json(owner_path, 1024 * 1024, with_digest=True)[1] == owner_sha, "OWNER_INPUT_CHANGED")
    require(all(owner.read_binding(payload["task_id"], actor) == original for actor, original in actor_bindings.items()),
            "STALE_ACTOR")
    current_sources(allow_expired_objective=bool(final_guards))
    # The frame is already complete. The shared executor fence performs current
    # policy/Source and live-cut callbacks before its last proof/actor/owner
    # comparison; no further Source read or serialization follows that fence.
    for guard in final_guards:
        guard()
    require(time.monotonic() - started < QUERY_SECONDS, "HIERARCHY_QUERY_TIMEOUT")
    return (result, frame) if with_bytes else result
