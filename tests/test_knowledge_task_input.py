"""Real owner/coordinator input binding; catalogs and requirements stay candidates."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from kotodama_kb.load import load_bundle
from kotodama_kb.strategy import strategy_template
from kotodama_kb.task_input import (MARKER, catalog_context, compile_task_input,
                                    execute_task_input, verify_task_input)
from runtime.task_swarm.protocol import SwarmError, digest

NOW = dt.datetime(2026, 10, 10, tzinfo=dt.timezone.utc)
STAMP = NOW.timestamp()
REFS = {"goals": ["OUT-INTENT"], "kgis": ["KGI-INTENT"], "initiatives": ["INIT-AGENT-OWNERSHIP"]}
CONSTRAINT = "Report measured values separately from unmeasured values."


def source(name, revision, text):
    return {"key": hashlib.sha256(name.encode()).hexdigest(), "revision": revision,
            "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}


def span(row, text):
    start = row["text"].index(text)
    return {"source_key": row["key"], "source_revision": row["revision"],
            "start": start, "end": start + len(text)}


def markdown(meta, body):
    return "---\n" + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True) + "---\n\n" + body + "\n"


def small_catalog(root):
    (root / "knowledge/synthetic").mkdir(parents=True)
    (root / "schemas").mkdir()
    (root / "docs").mkdir()
    for name in ("kotodama-okf-profile.schema.json", "kotodama-okf-concept.schema.json"):
        shutil.copyfile(ROOT / "schemas" / name, root / "schemas" / name)
    shutil.copyfile(ROOT / "knowledge/profile.yaml", root / "knowledge/profile.yaml")
    (root / "docs/source.md").write_text("Synthetic catalog source.\n", encoding="utf-8")
    names = []
    for index, (kind, identifier) in enumerate((("Goal", "OUT-INTENT"), ("Metric", "KGI-INTENT"),
            ("Initiative", "INIT-AGENT-OWNERSHIP"), ("Information", None))):
        logical = "synthetic/" + str(index)
        ext = {"profile": "0.1", "id": logical, "classification": "public_candidate",
               "authority": "projection_only", "knowledge_state": "candidate", "owner_role": "AI-BUILDER",
               "reviewer_role": "AI-AUDITOR", "context_priority": 5,
               "goal_refs": REFS["goals"], "kgi_refs": REFS["kgis"], "initiative_refs": REFS["initiatives"],
               "agent_use": {"discoverable": True, "answer_mode": "source_required",
                             "decision_authority": False, "runtime_authority": False}}
        if identifier:
            ext["strategy"] = strategy_template(kind, identifier)
            if kind == "Metric": ext["strategy"]["measurement_role"] = "product_outcome"
            if kind == "Initiative": ext["strategy"]["hypothesis"] = {
                "intervention": "Preserve explicit ancestor context.", "expected_effect": "Fewer missing constraints.",
                "falsifier": "A current ancestor constraint is absent from a delivered input."}
        metadata = {"type": kind, "title": "Synthetic " + str(index), "description": "Synthetic candidate definition.",
            "tags": ["governance"] if identifier is None else ["synthetic"], "status": "draft",
            "stale_after": "2026-12-07T00:00:00Z", "generated": {"by": "process:synthetic", "at": "2026-10-01T00:00:00Z"},
            "sources": [{"id": "manual", "resource": "../../docs/source.md", "title": "Synthetic source", "author": "team:synthetic"}],
            "kotodama": ext}
        (root / "knowledge" / (logical + ".md")).write_text(markdown(metadata, "Synthetic definition.[^manual]\n\n[^manual]: Synthetic source."), encoding="utf-8")
        names.append(f"* [Synthetic {index}]({logical}.md)")
    (root / "knowledge/index.md").write_text('---\nokf_version: "0.2"\n---\n\n' + "\n".join(names), encoding="utf-8")


def setup(root, *, public=False, corrected=False, jobs=2, max_concepts=None):
    if not (root / "knowledge").exists():
        if public:
            for relative, _ in load_bundle(ROOT, as_of=NOW).input_bindings:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
        else:
            small_catalog(root)
    bundle = load_bundle(root, as_of=NOW)
    selection, _, _ = catalog_context(bundle, REFS, max_concepts=max_concepts or (6 if public else 4))
    (root / "work").mkdir(exist_ok=True)
    area = root / "operations"
    area.mkdir(exist_ok=True)
    original = source("request", 1, "Compare knowledge-search latency and peak RSS.")
    current = source("request", 2, "Compare latency and peak RSS per workload; unavailable RSS stays unknown, never zero.") if corrected else original
    request_rows = [original, current] if corrected else [original]
    catalog_rows = [source(concept.concept_id, 1, concept.document.raw) for concept in selection.selected]
    declaration = {"kind": "kotodama.task-context-request", "version": 1, "owner_ref": "ref/owner/synthetic",
        "intent": {"original": span(original, original["text"]), "replacements": [span(current, current["text"])] if corrected else []},
        "references": copy.deepcopy(REFS), "max_concepts": max_concepts or (6 if public else 4),
        "catalog_bindings": {concept.concept_id: {"source_key": row["key"], "source_revision": row["revision"]}
                             for concept, row in zip(selection.selected, catalog_rows)},
        "hierarchy": [], "jobs": [], "constraints": [], "unknowns": [],
        "budget": {"attempt_budget": 4, "deadline": STAMP + 100}}
    rows, acceptance = [], []
    for index in range(jobs):
        identifier = "REQ-" + str(index)
        need = "Compare knowledge search latency." if index == 0 else (
            "Record peak RSS per workload; unavailable stays unknown, never zero." if corrected else "Record peak RSS and identify unavailable measurements.")
        accepted = "Show latency with its workload." if index == 0 else (
            "Show per-workload RSS or an explicit unknown." if corrected else "Show measured peak RSS or its missing reason.")
        text = markdown({"template_kind": "requirement", "id": identifier, "parent_ref": "PROJECT-SYNTHETIC",
                         "status": "draft", "task_context": {"need": need, "constraints": [], "acceptance": [accepted]}},
                        "# Need\n\n" + need + "\n\n# Acceptance\n\n" + accepted)
        path = root / "work" / (identifier + ".md")
        path.write_bytes(text.encode("utf-8"))
        row = source(identifier, 2 if corrected and index == 1 else 1, text)
        rows.append(row)
        declaration["hierarchy"].append({"path": path.relative_to(root).as_posix(), "source_key": row["key"], "source_revision": row["revision"]})
        declaration["jobs"].append({"requirement_id": identifier, "job_id": "requirement-" + str(index)})
        acceptance.append(accepted)
    project = root / "work/project.md"
    declaration["hierarchy"].append({"path": "work/project.md", "source_key": source("project", 1, "")["key"], "source_revision": 2 if corrected else 1})
    project_text = markdown({"template_kind": "project", "id": "PROJECT-SYNTHETIC", "status": "draft",
                            "task_context": {"constraints": [CONSTRAINT]}},
        "# Constraint\n\n" + CONSTRAINT + "\n\n" + MARKER + "\n```json\n" + json.dumps(declaration, ensure_ascii=False) + "\n```")
    project.write_bytes(project_text.encode("utf-8"))
    rows.append(source("project", 2 if corrected else 1, project_text))
    seed = {"version": 1, "task_id": "task-00000000-0000-4000-8000-000000000001", "revision": 2 if corrected else 1,
            "request": current["text"], "acceptance": acceptance, "sources": [*request_rows, *catalog_rows, *rows]}
    file, owner = area / "input.json", area / "owner.json"
    file.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    binding = {"task_id": seed["task_id"], "revision": seed["revision"], "context_digest": digest(seed),
               "owner_ref": "ref/owner/synthetic", "active_home": str(area), "authority_ref": "ref/authority/synthetic",
               "capability_ref": "ref/capability/swarm_research", "expires_at": STAMP + 200, "status": "active"}
    doc = {"binding": binding, "actors": {actor: {"epoch": 1, "invocation_ref": "invocation-" + actor,
                "actor_status": "active", "capability_ref": binding["capability_ref"], "peers": []}
            for actor in ("worker-a", "worker-b", "verifier")}, "allowed_actions": [],
           "source_checks": [{"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}],
           "storage": {"root": str(area), "mailbox": str(area / "mailbox.sqlite"), "payloads": str(area / "payloads")}}
    owner.write_text(json.dumps(doc), encoding="utf-8")
    return bundle, seed, owner, file


def admit(candidate, owner, file):
    """Explicit synthetic existing-owner action, deliberately outside producer."""
    file.write_text(json.dumps(candidate["payload"], ensure_ascii=False), encoding="utf-8")
    document = json.loads(owner.read_text(encoding="utf-8"))
    document["binding"]["context_digest"] = digest(candidate["payload"])
    document["source_checks"] = [*candidate["source_checks"],
        {"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}]
    owner.write_text(json.dumps(document), encoding="utf-8")


def reseal_seed(seed, owner, file):
    """Construct another explicitly owner-bound malformed fixture, not a runtime API."""
    for row in seed["sources"]:
        row["sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
    file.write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    document = json.loads(owner.read_text())
    document["binding"]["context_digest"] = digest(seed)
    document["source_checks"] = [{"path": str(file), "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}]
    owner.write_text(json.dumps(document))


def change_declaration(seed, root, change):
    row = next(row for row in seed["sources"] if MARKER in row["text"])
    begin = row["text"].index("```json\n") + len("```json\n")
    end = row["text"].index("\n```", begin)
    value = json.loads(row["text"][begin:end])
    change(value)
    row["text"] = row["text"][:begin] + json.dumps(value, ensure_ascii=False) + row["text"][end:]
    (root / "work/project.md").write_bytes(row["text"].encode("utf-8"))


class InspectingBackend:
    synthetic = True

    def __init__(self): self.inputs = []

    def produce(self, delivered, directory, *, actor_ref, **kwargs):
        self.inputs.append(copy.deepcopy(delivered))
        assert CONSTRAINT in [row["text"] for row in delivered["view"]["spans"]]
        row = next(row for row in delivered["view"]["spans"] if row["text"] == delivered["purpose"])
        evidence = {key: row[key] for key in ("source_key", "source_revision", "start", "end")}
        return {"result": {"job_id": delivered["job_id"], "summary": row["text"], "conflicts": [],
                    "claims": [{"text": row["text"], "status": "supported", "evidence": [{**evidence, "quote": row["text"]}]}]},
                "receipt": {"actor_ref": actor_ref, "invocation_ref": "synthetic-" + delivered["job_id"],
                            "input_digest": digest(delivered), "synthetic": True}}

    def review(self, delivered, directory, *, actor_ref, **kwargs):
        self.inputs.append(copy.deepcopy(delivered))
        assert CONSTRAINT in [row["text"] for row in delivered["view"]["spans"]]
        references = [{"job_id": job, "claim_index": 0} for job in delivered["reports"]]
        return {"result": {"parent_input_digest": delivered["view"]["parent_input_digest"],
            "plan_digest": delivered["view"]["plan_digest"], "round": delivered["round"],
            "report_digests": delivered["report_digests"], "validations": [
                {"criterion_id": key, "status": "passed", "evidence": references,
                 "gap_reason": None, "source_spans": []} for key in delivered["criteria"]]},
            "receipt": {"actor_ref": actor_ref, "invocation_ref": "synthetic-" + delivered["job_id"],
                        "input_digest": digest(delivered), "synthetic": True}}


class TaskContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_fixture_sources_survive_platform_newline_translation(self):
        original = Path.write_text
        def windows_write_text(path, data, encoding=None, errors=None, newline=None):
            if newline is None:
                data = data.replace("\n", "\r\n")
            return original(path, data, encoding=encoding, errors=errors, newline="")
        with mock.patch.object(Path, "write_text", windows_write_text):
            bundle, seed, owner, file = setup(self.root, jobs=1)
            change_declaration(seed, self.root, lambda value: value["budget"].update(deadline=STAMP + 90))
            reseal_seed(seed, owner, file)
            candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(STAMP + 90, candidate["payload"]["objective"]["budget"]["deadline"])

    def test_two_requirements_and_one_correction_change_actual_inputs_and_receipts(self):
        before = setup(self.root)
        bundle, seed, owner, file = before
        owner_bytes = owner.read_bytes()
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(owner_bytes, owner.read_bytes())
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_MISMATCH"):
            verify_task_input(bundle, candidate, owner, clock=lambda: STAMP)
        admit(candidate, owner, file)
        backend = InspectingBackend()
        result = execute_task_input(bundle, candidate, owner, file, backend, worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        work = {entry["job_id"]: entry for entry in backend.inputs if entry["role"] == "work"}
        self.assertNotEqual(work["r0-requirement-0"]["purpose"], work["r0-requirement-1"]["purpose"])
        self.assertEqual(result["receipt"]["parent_input_digest"], digest(candidate["payload"]))
        self.assertIn("O1", backend.inputs[-1]["criteria"])
        selected, _, _ = catalog_context(bundle, REFS, max_concepts=4)
        for delivered in backend.inputs:
            texts = [row["text"] for row in delivered["view"]["spans"]]
            self.assertTrue(all(concept.document.raw in texts for concept in selected.selected))
        corrected = setup(self.root, corrected=True)
        newer_bundle, newer_seed, newer_owner, newer_file = corrected
        self.assertEqual(owner, newer_owner)
        self.assertEqual(file, newer_file)
        newer = compile_task_input(newer_bundle, newer_seed, newer_owner, clock=lambda: STAMP)
        admit(newer, newer_owner, newer_file)
        with self.assertRaisesRegex(SwarmError, "STALE_BINDING"):
            verify_task_input(newer_bundle, candidate, newer_owner, clock=lambda: STAMP)
        obsolete_backend = InspectingBackend()
        with self.assertRaisesRegex(SwarmError, "STALE_BINDING"):
            execute_task_input(newer_bundle, candidate, newer_owner, newer_file, obsolete_backend,
                               worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        self.assertEqual([], obsolete_backend.inputs)
        second = InspectingBackend()
        new_result = execute_task_input(newer_bundle, newer, newer_owner, newer_file, second,
                                       worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        new_work = {entry["job_id"]: entry for entry in second.inputs if entry["role"] == "work"}
        for job in work:
            self.assertNotEqual(digest(work[job]), digest(new_work[job]))
            objective = new_work[job]["view"]["objective"]
            self.assertEqual(1, len(objective["intent"]["replacements"]))
            self.assertIn(seed["request"], [row["text"] for row in new_work[job]["view"]["spans"]])
        self.assertEqual(work["r0-requirement-0"]["purpose"], new_work["r0-requirement-0"]["purpose"])
        self.assertNotEqual(work["r0-requirement-1"]["purpose"], new_work["r0-requirement-1"]["purpose"])
        self.assertNotEqual(result["receipt_sha256"], new_result["receipt_sha256"])
        old_b = next(item for item in candidate["supplied_plan"]["jobs"] if item["job_id"] == "requirement-1")
        stale = copy.deepcopy(newer)
        stale["supplied_plan"]["jobs"][1]["selected_spans"] = old_b["selected_spans"]
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_CANDIDATE_CHANGED"):
            verify_task_input(newer_bundle, stale, newer_owner, clock=lambda: STAMP)
        replay = execute_task_input(newer_bundle, newer, newer_owner, newer_file, second, worker_actors=["worker-a", "worker-b"],
            clock=lambda: STAMP + 101, expected_receipt_sha256=new_result["receipt_sha256"])
        self.assertTrue(replay["duplicate"])
        self.assertEqual(3, len(second.inputs))

    def test_unknown_parent_missing_mandatory_fields_and_declared_scope_refuse(self):
        for mutation in ("parent", "fields", "closure"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, seed, owner, file = setup(root)
                if mutation == "closure":
                    change_declaration(seed, root, lambda value: value["hierarchy"].pop())
                else:
                    row = next(row for row in seed["sources"] if "id: REQ-0\n" in row["text"])
                    row["text"] = row["text"].replace("parent_ref: PROJECT-SYNTHETIC", "parent_ref: PROJECT-MISSING") if mutation == "parent" else row["text"].replace("  constraints: []\n", "")
                    (root / "work/REQ-0.md").write_bytes(row["text"].encode("utf-8"))
                reseal_seed(seed, owner, file)
                with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_(PARENT_INVALID|FIELDS_REQUIRED)"):
                    compile_task_input(bundle, seed, owner, clock=lambda: STAMP)

    def test_missing_original_and_aliased_catalog_records_refuse_even_after_owner_binding(self):
        bundle, seed, owner, file = setup(self.root, corrected=True)
        original = seed["sources"].pop(0)
        reseal_seed(seed, owner, file)
        with self.assertRaisesRegex(SwarmError, "OBJECTIVE_SOURCE_UNKNOWN"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        seed["sources"].insert(0, original)
        def alias(value):
            keys = list(value["catalog_bindings"])
            value["catalog_bindings"][keys[1]] = value["catalog_bindings"][keys[0]]
        change_declaration(seed, self.root, alias)
        reseal_seed(seed, owner, file)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_DISTINCT_SOURCE_REQUIRED"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)

    def test_source_change_during_work_cannot_publish_a_success_receipt(self):
        bundle, seed, owner, file = setup(self.root, jobs=1)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        admit(candidate, owner, file)
        class ChangingBackend(InspectingBackend):
            def produce(inner, *args, **kwargs):
                result = super().produce(*args, **kwargs)
                path = self.root / "knowledge/synthetic/0.md"
                path.write_bytes(path.read_bytes() + b"\n")
                return result
        with self.assertRaises(SwarmError):
            execute_task_input(bundle, candidate, owner, file, ChangingBackend(), worker_actors=["worker-a"], clock=lambda: STAMP)
        self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))

    def test_hierarchy_change_between_parse_and_hash_is_not_bound_to_new_bytes(self):
        bundle, seed, owner, _ = setup(self.root)
        import kotodama_kb.task_input as producer
        real_parse = producer._parse_frontmatter
        def change_after_parse(path, root):
            parsed = real_parse(path, root)
            path.write_bytes(path.read_bytes() + b"\n")
            return parsed
        with mock.patch.object(producer, "_parse_frontmatter", side_effect=change_after_parse):
            with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_SOURCE_CHANGED"):
                compile_task_input(bundle, seed, owner, clock=lambda: STAMP)

    def test_old_as_of_does_not_hide_compile_or_inflight_context_expiry(self):
        for phase in ("work", "critic"):
            with self.subTest(phase=phase):
                root = self.root / phase
                setup(root, jobs=1)
                for path in (root / "knowledge/synthetic").glob("*.md"):
                    path.write_text(path.read_text().replace("2026-12-07T00:00:00Z", "2026-10-10T00:00:01Z"))
                bundle, seed, owner, file = setup(root, jobs=1)
                with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_EXPIRED"):
                    compile_task_input(bundle, seed, owner, clock=lambda: STAMP + 2)
                change_declaration(seed, root, lambda value: value["budget"].update(deadline=STAMP + 1))
                reseal_seed(seed, owner, file)
                candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                admit(candidate, owner, file)
                clock = [STAMP]
                class ExpiringBackend(InspectingBackend):
                    def produce(inner, *args, **kwargs):
                        result = super().produce(*args, **kwargs)
                        if phase == "work": clock[0] = STAMP + 2
                        return result
                    def review(inner, *args, **kwargs):
                        result = super().review(*args, **kwargs)
                        clock[0] = STAMP + 2
                        return result
                with self.assertRaises(SwarmError):
                    execute_task_input(bundle, candidate, owner, file, ExpiringBackend(),
                                       worker_actors=["worker-a"], clock=lambda: clock[0])
                self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))

    def test_owner_must_bind_a_deadline_within_the_earliest_selected_context_expiry(self):
        setup(self.root, jobs=1)
        for index, path in enumerate(sorted((self.root / "knowledge/synthetic").glob("*.md"))):
            expiry = dt.datetime.fromtimestamp(STAMP + 1 + index, dt.timezone.utc).isoformat()
            path.write_text(path.read_text().replace("2026-12-07T00:00:00Z", expiry))
        bundle, seed, owner, file = setup(self.root, jobs=1)
        change_declaration(seed, self.root, lambda value: value["budget"].update(deadline=STAMP + 2))
        reseal_seed(seed, owner, file)
        before = (copy.deepcopy(seed), owner.read_bytes(), file.read_bytes())
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_DEADLINE_EXCEEDS_CONTEXT"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(before, (seed, owner.read_bytes(), file.read_bytes()))
        change_declaration(seed, self.root, lambda value: value["budget"].update(deadline=STAMP + 1))
        reseal_seed(seed, owner, file)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(STAMP + 1, candidate["payload"]["objective"]["budget"]["deadline"])

    def test_context_expiry_before_integration_cannot_accept_or_publish(self):
        import runtime.task_swarm.closed_loop as loop
        from runtime.task_swarm.state import SwarmState
        setup(self.root, jobs=1)
        for path in (self.root / "knowledge/synthetic").glob("*.md"):
            path.write_text(path.read_text().replace("2026-12-07T00:00:00Z", "2026-10-10T00:00:01Z"))
        bundle, seed, owner, file = setup(self.root, jobs=1)
        change_declaration(seed, self.root, lambda value: value["budget"].update(deadline=STAMP + 1))
        reseal_seed(seed, owner, file)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        admit(candidate, owner, file)
        clock, backend = [STAMP], InspectingBackend()
        original = loop.integration_candidate
        def expire_before_integration(*args, **kwargs):
            clock[0] = STAMP + 2
            return original(*args, **kwargs)
        with mock.patch.object(loop, "integration_candidate", side_effect=expire_before_integration):
            with mock.patch.object(SwarmState, "accept", autospec=True) as accept:
                with self.assertRaisesRegex(SwarmError, "DEADLINE_EXPIRED"):
                    execute_task_input(bundle, candidate, owner, file, backend,
                                       worker_actors=["worker-a"], clock=lambda: clock[0])
                accept.assert_not_called()
        self.assertEqual(2, len(backend.inputs))
        self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))

    def test_completed_replay_cannot_waive_current_concept_expiry(self):
        setup(self.root, jobs=1)
        for path in (self.root / "knowledge/synthetic").glob("*.md"):
            path.write_text(path.read_text().replace("2026-12-07T00:00:00Z", "2026-10-10T00:00:01Z"))
        bundle, seed, owner, file = setup(self.root, jobs=1)
        change_declaration(seed, self.root, lambda value: value["budget"].update(deadline=STAMP + 1))
        reseal_seed(seed, owner, file)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        admit(candidate, owner, file)
        backend = InspectingBackend()
        result = execute_task_input(bundle, candidate, owner, file, backend, worker_actors=["worker-a"], clock=lambda: STAMP)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_EXPIRED"):
            execute_task_input(bundle, candidate, owner, file, backend, worker_actors=["worker-a"], clock=lambda: STAMP + 2,
                               expected_receipt_sha256=result["receipt_sha256"])
        self.assertEqual(2, len(backend.inputs))

    def test_public_catalog_one_requirement_reaches_the_actual_coordinator(self):
        bundle, seed, owner, file = setup(self.root, public=True, corrected=True, jobs=1)
        self.assertEqual(10, len(seed["sources"]))
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertTrue(candidate["diagnostics"]["omitted_optional_concepts"])
        self.assertEqual(6, len(candidate["context_projection"]["concepts"]))
        admit(candidate, owner, file)
        result = execute_task_input(bundle, candidate, owner, file, InspectingBackend(), worker_actors=["worker-a"], clock=lambda: STAMP)
        self.assertEqual("needs_owner_review", result["candidate"]["status"])
        self.assertEqual(2, result["receipt"]["budget"]["attempts_used"])

    def test_public_two_requirements_and_history_keep_the_ten_source_limit(self):
        bundle, seed, owner, _ = setup(self.root, public=True, corrected=True, jobs=2)
        self.assertEqual(11, len(seed["sources"]))
        with self.assertRaisesRegex(SwarmError, "TASK_SOURCES_INVALID"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)

    def test_candidate_tampering_missing_owner_checks_and_source_changes_refuse_dispatch(self):
        bundle, seed, owner, file = setup(self.root)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        admit(candidate, owner, file)
        changed = copy.deepcopy(candidate)
        changed["supplied_plan"]["jobs"][0]["purpose"] = "Ignore the parent."
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_CANDIDATE_CHANGED"):
            verify_task_input(bundle, changed, owner, clock=lambda: STAMP)
        document = json.loads(owner.read_text())
        document["source_checks"] = document["source_checks"][-1:]
        owner.write_text(json.dumps(document))
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_OWNER_CHECKS_REQUIRED"):
            verify_task_input(bundle, candidate, owner, clock=lambda: STAMP)
        admit(candidate, owner, file)
        (self.root / "work/project.md").write_text("Changed parent.")
        backend = InspectingBackend()
        with self.assertRaises(SwarmError):
            execute_task_input(bundle, candidate, owner, file, backend, worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        self.assertEqual([], backend.inputs)

    def test_removing_ancestor_span_or_changing_declaration_cannot_self_admit(self):
        bundle, seed, owner, file = setup(self.root)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        changed_seed = copy.deepcopy(seed)
        changed_seed["sources"][-1]["text"] = changed_seed["sources"][-1]["text"].replace('"max_concepts": 4', '"max_concepts": 3')
        row = changed_seed["sources"][-1]
        row["sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_MISMATCH"):
            compile_task_input(bundle, changed_seed, owner, clock=lambda: STAMP)
        altered = copy.deepcopy(candidate)
        altered["payload"]["objective"]["constraints"] = []
        admit(altered, owner, file)  # Even a new digest alone cannot bypass source-derived constraints.
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_CANDIDATE_CHANGED"):
            verify_task_input(bundle, altered, owner, clock=lambda: STAMP)

    def test_changed_catalog_or_schema_and_unknown_typed_ids_are_rejected(self):
        bundle, seed, owner, file = setup(self.root)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_REFERENCE_UNRESOLVED"):
            catalog_context(bundle, {**REFS, "kgis": ["KGI-MISSING"]}, max_concepts=4)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_REFERENCE_UNRESOLVED"):
            catalog_context(bundle, {**REFS, "kgis": ["INIT-AGENT-OWNERSHIP"]}, max_concepts=4)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        admit(candidate, owner, file)
        path = self.root / "schemas/kotodama-okf-concept.schema.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaises(Exception):
            verify_task_input(bundle, candidate, owner, clock=lambda: STAMP)


if __name__ == "__main__":
    unittest.main()
