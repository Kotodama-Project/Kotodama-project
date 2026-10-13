"""Opt-in, source-bound Task v2 candidates; never writes an owner or creates a Task.

The selection declaration is an ordinary Source in an already owner-bound v1
input. Candidate hierarchy metadata is not a registry or adopted project state.
Only the existing owner can accept the resulting, different input digest.
"""
from __future__ import annotations

import hashlib
import datetime as dt
import json
from pathlib import Path
import re
import time

import yaml

from runtime.task_swarm.closed_loop import execute_closed_loop
from runtime.task_swarm.closed_loop_contract import loop_criteria, validate_plan
from runtime.task_swarm.closed_loop_context import derive_child_view
from runtime.task_swarm.owner_file import OwnerFile
from runtime.task_swarm.protocol import canonical, digest
from runtime.task_swarm.task_contract import MAX_INPUT_BYTES, require, shape, validate_input
from runtime.task_swarm.task_planning import _Sources, validate_objective
from runtime.task_swarm.task_runner import read_json

from .audit import context_as_dict
from .foundation import (_assert_current, _bounded_tree, _parse_frontmatter,
                         _parse_datetime, _read_bytes, _require_valid_bundle)
from .retrieve import select_context
from .strategy import strategy_model, strategy_reference_issues


MARKER = "<!-- kotodama-task-context-request -->"
_DECLARATION = re.compile(re.escape(MARKER) + r"\n```json\n(.*?)\n```", re.S)
_ID = re.compile(r"[A-Za-z][A-Za-z0-9._:/-]{0,159}\Z")
_SEED_KEYS = {"version", "task_id", "revision", "request", "acceptance", "sources"}


def _copy(value):
    _bounded_tree(value)
    encoded = canonical(value)
    require(len(encoded.encode("utf-8")) <= MAX_INPUT_BYTES, "TASK_CONTEXT_LIMIT")
    return json.loads(encoded)


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "TASK_CONTEXT_DECLARATION_INVALID")
        result[key] = value
    return result


def _declaration(seed):
    found = []
    latest = _Sources(seed).latest
    for source in seed["sources"]:
        matches = list(_DECLARATION.finditer(source["text"]))
        require(source["text"].count(MARKER) == len(matches), "TASK_CONTEXT_DECLARATION_INVALID")
        for match in matches:
            require(source["revision"] == latest[source["key"]], "TASK_CONTEXT_DECLARATION_STALE")
            try:
                value = json.loads(match[1], object_pairs_hook=_pairs,
                                   parse_constant=lambda _: None)
            except (ValueError, RecursionError) as exc:
                raise ValueError("TASK_CONTEXT_DECLARATION_INVALID") from exc
            found.append(value)
    require(len(found) == 1, "TASK_CONTEXT_DECLARATION_REQUIRED")
    value = found[0]
    _bounded_tree(value)
    require(isinstance(value, dict) and type(value.get("version")) is int
            and value["version"] in (1, 2), "TASK_CONTEXT_DECLARATION_INVALID")
    shape(value, {"kind", "version", "owner_ref", "intent", "references", "max_concepts",
                  "catalog_bindings", "hierarchy", "constraints", "unknowns", "budget"}
                 | ({"jobs"} if value["version"] == 1 else {"root_requirement_id"}),
          "TASK_CONTEXT_DECLARATION_INVALID")
    require(value["kind"] == "kotodama.task-context-request", "TASK_CONTEXT_DECLARATION_INVALID")
    return value


def catalog_context(bundle, references, *, max_concepts):
    """Resolve the unchanged KB selector; return a projection and full selection.

    An explicit narrower context budget may omit optional Concepts. Unresolved
    mandatory context and an omitted requested definition are always failures.
    """
    _require_valid_bundle(bundle)
    require(type(max_concepts) is int, "TASK_CONTEXT_LIMIT")
    shape(references, {"goals", "kgis", "initiatives"}, "TASK_CONTEXT_REFERENCES_INVALID")
    record = {key: references[field] for key, field in
              (("goal_refs", "goals"), ("kgi_refs", "kgis"), ("initiative_refs", "initiatives"))}
    graph, issues = strategy_model(bundle.concepts)
    require(not issues and not strategy_reference_issues(record, graph["definitions"], path="task-input"),
            "TASK_CONTEXT_REFERENCE_UNRESOLVED")
    require(bool(references["goals"]), "TASK_CONTEXT_GOAL_REQUIRED")
    # The narrowest explicit dimension avoids implicitly broadening an INIT
    # selection to every sibling with the same Goal. This is still the canonical
    # selector, including all mandatory governance/linked critical checks.
    field = next(key for key in ("initiatives", "kgis", "goals") if references[key])
    filters = {key: references[key] if key == field else [] for key in references}
    selected = select_context(bundle, **filters, tags=[], max_concepts=max_concepts)
    require(not selected.unresolved_ids, "TASK_CONTEXT_REQUIRED_UNRESOLVED")
    by_id = {concept.concept_id: concept for concept in selected.selected}
    require(all(graph["definitions"][identifier]["concept_id"] in by_id
                for values in references.values() for identifier in values),
            "TASK_CONTEXT_DEFINITION_OMITTED")
    return selected, context_as_dict(selected, bundle=bundle), graph


def _record(seed, reference):
    shape(reference, {"source_key", "source_revision"}, "TASK_CONTEXT_SOURCE_INVALID")
    _Sources(seed).span({**reference, "start": 0, "end": 1})
    return next(source for source in seed["sources"]
                if (source["key"], source["revision"]) ==
                (reference["source_key"], reference["source_revision"]))


def _span(source, text, *, start=0):
    require(isinstance(text, str) and text.strip() and 0 < len(text) <= 1000,
            "TASK_CONTEXT_STATEMENT_INVALID")
    offset = source["text"].find(text, start)
    require(offset >= start and source["text"].find(text, offset + 1) == -1,
            "TASK_CONTEXT_STATEMENT_AMBIGUOUS")
    return {"source_key": source["key"], "source_revision": source["revision"],
            "start": offset, "end": offset + len(text)}


def _definition_span(source, identifier):
    """Locate the parsed strategy.id scalar, including quoted YAML spellings."""
    lines = source["text"].splitlines(keepends=True)
    closing = next(i for i, line in enumerate(lines[1:], 1) if line.strip() == "---")
    node = yaml.compose("".join(lines[1:closing]), Loader=yaml.SafeLoader)
    for key in ("kotodama", "strategy", "id"):
        node = next(value for name, value in node.value if name.value == key)
    start = len(lines[0]) + node.start_mark.index
    end = len(lines[0]) + node.end_mark.index
    require(node.value == identifier, "TASK_CONTEXT_DEFINITION_MISMATCH")
    offset = source["text"].find(identifier, start, end)
    require(offset >= 0, "TASK_CONTEXT_DEFINITION_MISMATCH")
    return {"source_key": source["key"], "source_revision": source["revision"],
            "start": offset, "end": offset + len(identifier)}


def _live_context(projection, now):
    actual = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    require(all(item["stale_after"] is None or actual < _parse_datetime(
        item["stale_after"], field="stale_after", path=item["id"])
        for item in projection["concepts"]), "TASK_CONTEXT_EXPIRED")


def _hierarchy(bundle, seed, entries, *, planning=False):
    require(isinstance(entries, list) and 1 <= len(entries) <= 8, "TASK_CONTEXT_HIERARCHY_LIMIT")
    nodes, checks, paths = {}, {}, set()
    for entry in entries:
        shape(entry, {"path", "source_key", "source_revision"}, "TASK_CONTEXT_HIERARCHY_INVALID")
        relative = entry["path"]
        require(isinstance(relative, str) and not Path(relative).is_absolute()
                and ".." not in Path(relative).parts, "TASK_CONTEXT_PATH_INVALID")
        path = bundle.root / relative
        require(path.resolve().is_relative_to(bundle.root) and path not in paths,
                "TASK_CONTEXT_PATH_INVALID")
        paths.add(path)
        source = _record(seed, {key: entry[key] for key in ("source_key", "source_revision")})
        expected_bytes = source["text"].encode("utf-8")
        require(path.stat().st_size == len(expected_bytes), "TASK_CONTEXT_SOURCE_CHANGED")
        document = _parse_frontmatter(path, bundle.root)
        require(document.raw == source["text"], "TASK_CONTEXT_SOURCE_CHANGED")
        meta = document.frontmatter
        identifier, kind = meta.get("id"), meta.get("template_kind")
        require(isinstance(identifier, str) and _ID.fullmatch(identifier)
                and identifier not in nodes and kind in {"project", "phase", "requirement"}
                and meta.get("status") == "draft" and "{{" not in document.raw,
                "TASK_CONTEXT_HIERARCHY_INVALID")
        fields = meta.get("task_context")
        expected = {"constraints", "need", "acceptance"} if kind == "requirement" else {"constraints"}
        if planning and kind == "requirement":
            expected = expected | {"frontier"}
        shape(fields, expected, "TASK_CONTEXT_FIELDS_REQUIRED")
        require(isinstance(fields["constraints"], list) and len(fields["constraints"]) <= 20,
                "TASK_CONTEXT_STATEMENT_INVALID")
        body_start = len(document.raw) - len(document.body)
        constraints = [_span(source, text, start=body_start) for text in fields["constraints"]]
        acceptance, need = [], None
        if kind == "requirement":
            require(isinstance(fields["acceptance"], list) and 1 <= len(fields["acceptance"]) <= 20,
                    "TASK_CONTEXT_STATEMENT_INVALID")
            acceptance = [_span(source, text, start=body_start) for text in fields["acceptance"]]
            need = _span(source, fields["need"], start=body_start)
        nodes[identifier] = {"kind": kind, "parent": meta.get("parent_ref"),
                             "constraints": constraints, "acceptance": acceptance, "need": need}
        if planning and kind == "requirement":
            nodes[identifier].update(frontier=fields["frontier"], source=source)
        require(_read_bytes(path) == expected_bytes, "TASK_CONTEXT_SOURCE_CHANGED")
        checks[str(path)] = hashlib.sha256(expected_bytes).hexdigest()
    for node in nodes.values():
        parent = node["parent"]
        if node["kind"] == "project":
            require(parent is None, "TASK_CONTEXT_PARENT_INVALID")
        else:
            allowed = {"project"} if node["kind"] == "phase" else {"phase", "project"}
            require(isinstance(parent, str) and parent in nodes and nodes[parent]["kind"] in allowed,
                    "TASK_CONTEXT_PARENT_INVALID")
    return nodes, checks


def _build(bundle, seed, binding, *, now, allow_expired=False):
    declaration = _declaration(seed)
    require(declaration["owner_ref"] == binding["owner_ref"], "OBJECTIVE_OWNER_MISMATCH")
    selection, projection, graph = catalog_context(bundle, declaration["references"],
                                                  max_concepts=declaration["max_concepts"])
    _live_context(projection, now)
    bindings = declaration["catalog_bindings"]
    selected = {concept.concept_id: concept for concept in selection.selected}
    require(isinstance(bindings, dict) and set(bindings) == set(selected),
            "TASK_CONTEXT_CATALOG_COVERAGE")
    require(len(selected) <= 10, "TASK_CONTEXT_SOURCE_LIMIT")
    catalog_sources, identities = {}, set()
    for concept_id, concept in selected.items():
        source = _record(seed, bindings[concept_id])
        identity = (source["key"], source["revision"])
        require(identity not in identities, "TASK_CONTEXT_DISTINCT_SOURCE_REQUIRED")
        identities.add(identity)
        require(source["text"] == concept.document.raw, "TASK_CONTEXT_SOURCE_CHANGED")
        catalog_sources[concept_id] = source
    planning = declaration["version"] == 2
    nodes, checks = _hierarchy(bundle, seed, declaration["hierarchy"], planning=planning)
    catalog_spans = [{"source_key": source["key"], "source_revision": source["revision"],
                      "start": 0, "end": len(source["text"])} for source in catalog_sources.values()]
    work = None
    if planning:
        from .task_frontier import frontier_work
        work = frontier_work(seed, nodes, declaration["root_requirement_id"],
                             declaration["constraints"], catalog_spans)
        constraints, acceptance, jobs = work["constraints"], work["acceptance"], work["jobs"]
    else:
        require(isinstance(declaration["jobs"], list) and 1 <= len(declaration["jobs"]) <= 3,
                "TASK_CONTEXT_JOB_LIMIT")
        covered, constraints, acceptance, jobs = set(), list(declaration["constraints"]), [], []
        for job in declaration["jobs"]:
            shape(job, {"requirement_id", "job_id"}, "TASK_CONTEXT_JOB_INVALID")
            identifier = job["requirement_id"]
            require(isinstance(identifier, str) and identifier in nodes
                    and nodes[identifier]["kind"] == "requirement" and identifier not in covered,
                    "TASK_CONTEXT_REQUIREMENT_INVALID")
            node, ancestors = nodes[identifier], []
            while identifier is not None:
                require(identifier not in ancestors, "TASK_CONTEXT_PARENT_CYCLE")
                ancestors.append(identifier)
                if identifier not in covered:
                    constraints.extend(nodes[identifier]["constraints"])
                    covered.add(identifier)
                identifier = nodes[identifier]["parent"]
            acceptance.extend(node["acceptance"])
            jobs.append({"job_id": job["job_id"], "purpose": _Sources(seed).span(node["need"]),
                         "selected_spans": [*catalog_spans, node["need"], *node["acceptance"], *node["constraints"]]})
        require(covered == set(nodes), "TASK_CONTEXT_UNUSED_HIERARCHY")
    require(_Sources(seed).spans(acceptance) == seed["acceptance"], "TASK_CONTEXT_ACCEPTANCE_MISMATCH")
    references = []
    for field, kind in (("goals", "goal"), ("kgis", "kgi"), ("initiatives", "initiative")):
        for identifier in declaration["references"][field]:
            concept_id = graph["definitions"][identifier]["concept_id"]
            references.append({"kind": kind, "id": identifier,
                               "source": _definition_span(catalog_sources[concept_id], identifier)})
    payload = {**seed, "version": 2, "objective": {
        "owner_ref": declaration["owner_ref"], "intent": declaration["intent"],
        "references": references, "constraints": constraints,
        "unknowns": declaration["unknowns"], "acceptance": acceptance,
        "budget": declaration["budget"],
        "stop_conditions": ["cancelled", "binding_changed", "deadline_exceeded"],
        "rollback": "not_applicable_read_only"}}
    payload = _copy(payload)
    # This only validates the objective. The real owner's context_digest still
    # binds the v1 seed and MUST NOT be replaced to pretend candidate admission.
    validate_objective(payload, binding, now=now, allow_expired=allow_expired)
    # The coordinator already checks this declared deadline at every accept and
    # receipt boundary. Require the owner to cover the earliest selected expiry;
    # silently shortening its budget would create a different, unbound input.
    expiries = [_parse_datetime(item["stale_after"], field="stale_after", path=item["id"]).timestamp()
                for item in projection["concepts"] if item["stale_after"] is not None]
    require(not expiries or payload["objective"]["budget"]["deadline"] <= min(expiries),
            "TASK_CONTEXT_DEADLINE_EXCEEDS_CONTEXT")
    for index, job in enumerate(jobs):
        job["criterion_ids"] = [key for key in loop_criteria(payload)
                                if work is None or key not in work["assignments"]
                                or work["leaves"][index] in work["assignments"][key]]
    dependency = any("requires" in job for job in jobs)
    plan = validate_plan({"version": 2 if dependency else 1, "parent_input_digest": digest(payload), "jobs": jobs}, payload)
    if dependency:
        from runtime.task_swarm.dependency_contract import descriptor
        descriptor(payload, plan)
    all_spans = {tuple(span[key] for key in ("source_key", "source_revision", "start", "end")): span
                 for job in jobs for span in job["selected_spans"]}
    require(len(all_spans) <= 32, "TASK_CONTEXT_LIMIT")
    derive_child_view(payload, "r0-critic", list(all_spans.values()), plan_digest=digest(plan))
    checks.update({str(bundle.root / relative): sha for relative, sha in bundle.input_bindings})
    _assert_current(bundle)
    require(all(hashlib.sha256(_read_bytes(Path(path))).hexdigest() == sha for path, sha in checks.items()),
            "TASK_CONTEXT_SOURCE_CHANGED")
    diagnostics = {"status": "candidate_requires_owner_binding", "hierarchy": "owner_declared_candidate",
                   "history": "input_only_unverified", "catalog_adoption": "candidate",
                   "omitted_optional_concepts": list(selection.omitted_ids),
                   "provider_delivery_verified": False}
    if work is not None:
        diagnostics["frontier"] = work["diagnostic"]
        diagnostics["frontier"]["budget"] = {
            "work_cap": 3, "initial_work_count": len(jobs),
            "initial_attempts_required": len(jobs) + (2 if dependency else 1),
            "original_attempt_budget": payload["objective"]["budget"]["attempt_budget"],
            "attempts_after_initial_if_no_retry": (
                payload["objective"]["budget"]["attempt_budget"] - len(jobs) - (2 if dependency else 1)),
            "runtime_remaining_attempts": None,
        }
    return _copy({"payload": payload, "supplied_plan": plan, "seed_digest": digest(seed),
        "source_checks": [{"path": path, "sha256": sha} for path, sha in sorted(checks.items())],
        "context_projection": projection, "diagnostics": diagnostics})


def compile_task_input(bundle, seed_payload, owner_path, *, clock=time.time):
    """Compile an owner-bound v1 seed without modifying its binding or files."""
    seed = _copy(seed_payload)
    require(isinstance(seed, dict), "TASK_CONTEXT_V1_SEED_REQUIRED")
    require(seed.get("version") == 1, "TASK_CONTEXT_V1_SEED_REQUIRED")
    owner = OwnerFile(owner_path, clock=clock)
    binding = owner.read_task()
    seed = validate_input(seed, binding, now=clock())
    candidate = _build(bundle, seed, binding, now=clock())
    require(owner.read_task() == binding, "STALE_BINDING")
    _live_context(candidate["context_projection"], clock())
    return candidate


def verify_task_input(bundle, candidate, owner_path, *, clock=time.time, allow_expired=False):
    """Rebuild the projection and require the real owner to bind its v2 bytes."""
    candidate = _copy(candidate)
    owner = OwnerFile(owner_path, clock=clock)
    binding = owner.read_task()
    payload = validate_input(candidate["payload"], binding, now=clock(),
                             allow_expired_objective=allow_expired)
    seed = {key: payload[key] for key in _SEED_KEYS}
    seed["version"] = 1
    rebuilt = _build(bundle, seed, binding, now=clock(), allow_expired=allow_expired)
    require(rebuilt == candidate, "TASK_CONTEXT_CANDIDATE_CHANGED")
    document = read_json(owner.path)
    declared = {str((owner.path.parent / item["path"]).resolve()): item["sha256"]
                for item in document["source_checks"]}
    require(all(declared.get(str(Path(item["path"]).resolve())) == item["sha256"]
                for item in candidate["source_checks"]), "TASK_CONTEXT_OWNER_CHECKS_REQUIRED")
    require(owner.read_task() == binding, "STALE_BINDING")
    _live_context(rebuilt["context_projection"], clock())
    return payload


def execute_task_input(bundle, candidate, owner_path, payload_path, backend, *,
                       worker_actors, clock=time.time, **options):
    """Use the existing finite coordinator after actual owner admission.

    The wrapper checks before every backend call; the coordinator's existing
    owner/source checks also cover the intervals and receipt publication.
    """
    candidate = _copy(candidate)
    allow_expired = options.get("expected_receipt_sha256") is not None

    def guard():
        payload = verify_task_input(bundle, candidate, owner_path, clock=clock,
                                    allow_expired=allow_expired)
        require(read_json(Path(payload_path)) == payload, "TASK_CONTEXT_INPUT_CHANGED")
        _live_context(candidate["context_projection"], clock())

    guard()

    from runtime.task_swarm.task_backend import checked_backend
    return execute_closed_loop(owner_path, payload_path, candidate["supplied_plan"], checked_backend(backend, guard),
                               worker_actors=worker_actors, clock=clock, **options)
