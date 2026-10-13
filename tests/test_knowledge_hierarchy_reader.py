"""Current Source and real saved consumers; a trace must never mutate the run."""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import test_knowledge_task_input as fixture
from kotodama_kb.hierarchy_reader import trace_current_refs
from kotodama_kb.load import load_bundle
from runtime.task_swarm.protocol import SwarmError, canonical, digest
from runtime.task_swarm.task_contract import MAX_INPUT_BYTES
from runtime.task_swarm.closed_loop import execute_closed_loop
from runtime.task_swarm.closed_loop_contract import loop_criteria


def inventory(root):
    return {path.relative_to(root).as_posix(): ("directory" if path.is_dir() else
            hashlib.sha256(path.read_bytes()).hexdigest()) for path in root.rglob("*")}


class HierarchyReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.now = fixture.STAMP

    def graph(self, *, corrected=False):
        if not (self.root / "knowledge").exists():
            fixture.small_catalog(self.root)
        bundle = load_bundle(self.root)
        area, work = self.root / "operations", self.root / "work"
        area.mkdir(exist_ok=True)
        work.mkdir(exist_ok=True)
        description = [
            ("PROJECT-A", "project", [], fixture.CONSTRAINT),
            ("PHASE-A", "phase", ["PROJECT-A"], "Separate observed and unknown latency."),
            ("PHASE-B", "phase", ["PROJECT-A"], "Keep missing RSS explicit."),
            ("REQ-ROOT", "requirement", ["PHASE-A", "PHASE-B"], "Compare the declared workloads."),
        ]
        rows, entries = [], []
        for identifier, kind, parents, constraint in description:
            if corrected and identifier == "PHASE-B":
                constraint = "Keep missing RSS explicit for each workload."
            fields = {"constraints": [constraint]}
            if kind == "requirement":
                fields.update(need="Compare latency and RSS.", acceptance=["Show both workloads and missing measurements."])
            meta = {"id": identifier, "template_kind": kind, "title": "Same visible title",
                    "status": "draft", "task_context": fields}
            if parents:
                meta["parent_refs"] = parents
            raw = fixture.markdown(meta, "\n\n".join([constraint, *([fields["need"], *fields["acceptance"]] if kind == "requirement" else [])]))
            path = work / (identifier + ".md")
            path.write_bytes(raw.encode("utf-8"))
            row = fixture.source(identifier, 2 if corrected else 1, raw)
            rows.append(row)
            entries.append({"path": path.relative_to(self.root).as_posix(), "source_key": row["key"], "source_revision": row["revision"]})
        payload = {"version": 1, "task_id": "task-00000000-0000-4000-8000-000000000001", "revision": 2 if corrected else 1,
                   "request": "Compare the current workloads.", "acceptance": [], "sources": rows}
        file, owner = area / "input.json", area / "owner.json"
        file.write_bytes(canonical(payload).encode())
        binding = {"task_id": payload["task_id"], "revision": payload["revision"], "context_digest": digest(payload),
            "owner_ref": "ref/owner/synthetic", "active_home": str(area), "authority_ref": "ref/authority/synthetic",
            "capability_ref": "ref/capability/swarm_research", "expires_at": self.now + 200, "status": "active"}
        document = {"binding": binding, "actors": {"reader": {"epoch": 1, "invocation_ref": "invocation-reader",
            "actor_status": "active", "capability_ref": binding["capability_ref"], "peers": []}}, "allowed_actions": [],
            "source_checks": [{"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                              for path in [file, *(self.root / name for name, _ in bundle.input_bindings),
                                           *(self.root / entry["path"] for entry in entries)]],
            "storage": {"root": str(area), "mailbox": str(area / "mailbox.sqlite"), "payloads": str(area / "payloads")}}
        owner.write_bytes(canonical(document).encode())
        request = {"version": 1, "root_id": "REQ-ROOT", "nodes": entries,
            "references": [{"kind": "owner_task", "id": payload["task_id"], "revision": payload["revision"], "mandatory": True}]}
        return bundle, payload, owner, file, request

    def change_source(self, payload, owner, file, request, index, change):
        row, entry = payload["sources"][index], request["nodes"][index]
        row["text"] = change(row["text"])
        row["sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
        (self.root / entry["path"]).write_bytes(row["text"].encode())
        fixture.reseal_seed(payload, owner, file)
        document = json.loads(owner.read_bytes())
        bundle = load_bundle(self.root)
        document["source_checks"] += [{"path": str(self.root / relative), "sha256": sha}
                                      for relative, sha in bundle.input_bindings]
        document["source_checks"] += [{"path": str(self.root / node["path"]),
            "sha256": hashlib.sha256((self.root / node["path"]).read_bytes()).hexdigest()} for node in request["nodes"]]
        owner.write_bytes(canonical(document).encode())

    def run_reader(self, data, *, request=None, clock=None):
        bundle, payload, owner, _, original = data
        return trace_current_refs(bundle, payload, owner, request or original, clock=clock or (lambda: self.now))

    def completed(self, *, corrected=False):
        with mock.patch.object(fixture, "STAMP", self.now):
            bundle, seed, owner, file = fixture.setup(self.root, corrected=corrected)
            candidate = fixture.compile_task_input(bundle, seed, owner, clock=lambda: self.now)
            fixture.admit(candidate, owner, file)
            backend = fixture.InspectingBackend()
            result = fixture.execute_task_input(bundle, candidate, owner, file, backend,
                worker_actors=["worker-a", "worker-b"], clock=lambda: self.now)
        project = next(row for row in seed["sources"] if fixture.MARKER in row["text"])
        begin = project["text"].index("```json\n") + len("```json\n")
        end = project["text"].index("\n```", begin)
        entries = json.loads(project["text"][begin:end])["hierarchy"]
        request = {"version": 1, "root_id": "REQ-0", "nodes": entries[:1] + entries[-1:], "references": [
            {"kind": "owner_task", "id": seed["task_id"], "revision": seed["revision"], "mandatory": True},
            {"kind": "runtime_plan", "id": result["receipt"]["run_id"], "revision": seed["revision"],
             "receipt_sha256": result["receipt_sha256"], "mandatory": True}]}
        return (bundle, candidate["payload"], owner, file, request), backend, result

    def completed_diamond(self, *, corrected=False):
        data = self.graph(corrected=corrected)
        bundle, payload, owner, file, request = data
        if corrected:
            self.change_source(payload, owner, file, request, 3,
                lambda text: text.replace("parent_refs:\n- PHASE-A\n- PHASE-B", "parent_refs:\n- PROJECT-A\n- PHASE-B"))
            request["nodes"] = [request["nodes"][index] for index in (0, 2, 3)]
        original = fixture.source("original-request", 1, "Compare the declared latency and RSS workloads.")
        current = fixture.source("original-request", 2,
            "Compare the current workloads; preserve per-workload RSS unknowns.") if corrected else original
        goal = fixture.source("synthetic-goal", 1, bundle.concepts[0].document.raw)
        payload["sources"] = [*payload["sources"], original, *([current] if corrected else []), goal]
        payload["version"], payload["request"] = 2, current["text"]
        constraints, selected = [], []
        for entry in request["nodes"]:
            row = next(row for row in payload["sources"] if row["key"] == entry["source_key"])
            meta = yaml.safe_load(row["text"].split("---", 2)[1])
            for statement in meta["task_context"]["constraints"]:
                start = row["text"].rindex(statement)
                constraints.append({"source_key": row["key"], "source_revision": row["revision"],
                                    "start": start, "end": start + len(statement)})
            selected.append(fixture.span(row, row["text"]))
        requirement = next(row for row in payload["sources"] if "id: REQ-ROOT\n" in row["text"])
        need = "Compare latency and RSS."
        accepted = "Show both workloads and missing measurements."
        def body_span(row, statement):
            start = row["text"].rindex(statement)
            return {"source_key": row["key"], "source_revision": row["revision"], "start": start, "end": start + len(statement)}
        from kotodama_kb.task_input import _definition_span
        payload["acceptance"] = [accepted]
        payload["objective"] = {"owner_ref": "ref/owner/synthetic",
            "intent": {"original": fixture.span(original, original["text"]),
                       "replacements": [fixture.span(current, current["text"])] if corrected else []},
            "references": [{"kind": "goal", "id": "OUT-INTENT", "source": _definition_span(goal, "OUT-INTENT")}],
            "constraints": constraints, "unknowns": [], "acceptance": [body_span(requirement, accepted)],
            "budget": {"attempt_budget": 4, "deadline": self.now + 100},
            "stop_conditions": ["cancelled", "binding_changed", "deadline_exceeded"], "rollback": "not_applicable_read_only"}
        selected.append(body_span(requirement, need))
        selected.append(fixture.span(goal, goal["text"]))
        plan = {"version": 1, "parent_input_digest": digest(payload), "jobs": [
            {"job_id": name, "purpose": need, "criterion_ids": list(loop_criteria(payload)), "selected_spans": selected}
            for name in ("left", "right")]}
        file.write_bytes(canonical(payload).encode())
        document = json.loads(owner.read_bytes())
        document["binding"]["context_digest"] = digest(payload)
        document["actors"] = {actor: {"epoch": 1, "invocation_ref": "invocation-" + actor,
            "actor_status": "active", "capability_ref": document["binding"]["capability_ref"], "peers": []}
            for actor in ("worker-a", "worker-b", "verifier")}
        next(check for check in document["source_checks"] if check["path"] == str(file))["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
        owner.write_bytes(canonical(document).encode())
        backend = fixture.InspectingBackend()
        result = execute_closed_loop(owner, file, plan, backend, worker_actors=["worker-a", "worker-b"], clock=lambda: self.now)
        request["references"].append({"kind": "runtime_plan", "id": result["receipt"]["run_id"],
            "revision": payload["revision"], "receipt_sha256": result["receipt_sha256"], "mandatory": True})
        return data, backend, result

    def test_source_declared_diamond_preserves_offsets_reverse_refs_and_no_writes(self):
        data = self.graph()
        before = inventory(self.root)
        result = self.run_reader(data)
        self.assertEqual(before, inventory(self.root))
        self.assertEqual("TRACED_CANDIDATE", result["status"])
        self.assertEqual(["PHASE-A", "PHASE-B"], result["reverse_refs"]["PROJECT-A"])
        self.assertEqual(["REQ-ROOT"], result["reverse_refs"]["PHASE-B"])
        self.assertEqual(4, len(result["context_candidate"]["constraints"]))
        by_key = {row["key"]: row for row in data[1]["sources"]}
        for edge in result["edges"]:
            span = edge["source"]
            self.assertEqual(span["text"], by_key[span["source_key"]]["text"][span["start"]:span["end"]])
            self.assertEqual(hashlib.sha256(span["text"].encode()).hexdigest(), span["sha256"])
            self.assertGreater(span["line"], 1)
        self.assertFalse(result["context_candidate"]["dispatch_ready"])
        self.assertEqual("requires_source_rederivation", result["context_candidate"]["producer_bridge"])
        self.assertFalse(result["dispatch_performed"])

    def test_stable_id_rename_with_explicit_owner_update_and_old_locator_refusal(self):
        data = self.graph()
        original = self.run_reader(data)
        old = copy.deepcopy(data[4])
        path = self.root / data[4]["nodes"][1]["path"]
        renamed = path.with_name("renamed-phase.md")
        path.rename(renamed)
        doc = json.loads(data[2].read_bytes())
        next(check for check in doc["source_checks"] if check["path"] == str(path))["path"] = str(renamed)
        data[2].write_bytes(canonical(doc).encode())
        data[4]["nodes"][1]["path"] = renamed.relative_to(self.root).as_posix()
        current = self.run_reader(data)
        self.assertEqual(original["closure"], current["closure"])
        self.assertEqual(original["reverse_refs"], current["reverse_refs"])
        with self.assertRaises((SwarmError, OSError, RuntimeError)):
            self.run_reader(data, request=old)

    def test_single_parent_and_optional_phase_are_supported_without_kind_alias(self):
        data = self.graph()
        self.change_source(data[1], data[2], data[3], data[4], 3,
                           lambda raw: raw.replace("parent_refs:\n- PHASE-A\n- PHASE-B", "parent_ref: PROJECT-A"))
        data[4]["nodes"] = [data[4]["nodes"][0], data[4]["nodes"][3]]
        result = self.run_reader(data)
        self.assertEqual(["PROJECT-A", "REQ-ROOT"], result["closure"])

    def test_unknown_reference_blocks_whole_context_and_task_template_is_not_task(self):
        data = self.graph()
        for kind in ("organization_plan", "Plan", "Task", "session", "architecture", "atomic"):
            with self.subTest(kind=kind):
                request = copy.deepcopy(data[4])
                request["references"].append({"kind": kind, "id": "PLAN-X", "revision": 1, "mandatory": True})
                result = self.run_reader(data, request=request)
                self.assertEqual("BLOCKED", result["status"])
                self.assertIsNone(result["context_candidate"])
                self.assertFalse(result["organization_plan_resolved"])
                self.assertEqual("resolve_kind_and_current_owner_binding", result["unresolved"][0]["next_action"])
        request["references"][-1]["mandatory"] = False
        self.assertEqual("TRACED_CANDIDATE", self.run_reader(data, request=request)["status"])

    def test_declaration_conflict_unknown_parent_cycle_withdrawal_and_alias_refuse(self):
        mutations = {
            "parent_conflict": lambda text: text.replace("parent_refs:", "parent_ref: PHASE-A\nparent_refs:"),
            "unknown_parent": lambda text: text.replace("- PHASE-B", "- PHASE-MISSING"),
            "cycle": lambda text: text.replace("- PHASE-B", "- REQ-ROOT"),
            "withdrawn": lambda text: text.replace("status: draft", "status: revoked"),
            "alias": lambda text: text.replace("template_kind: requirement", "template_kind: Plan"),
            "parent_overflow": lambda text: text.replace("- PHASE-B", "- PHASE-B\n- PROJECT-A"),
            "yaml_alias": lambda text: text.replace("- PHASE-A", "- &parent PHASE-A").replace("- PHASE-B", "- *parent"),
        }
        for name, change in mutations.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                old_root, self.root = self.root, Path(tmp).resolve()
                try:
                    data = self.graph()
                    self.change_source(data[1], data[2], data[3], data[4], 3, change)
                    with self.assertRaises(SwarmError):
                        self.run_reader(data)
                finally:
                    self.root = old_root

    def test_mandatory_missing_node_duplicate_identity_and_unused_node_do_not_truncate(self):
        data = self.graph()
        for case in ("missing", "duplicate", "overflow"):
            request = copy.deepcopy(data[4])
            if case == "missing": request["nodes"].pop(1)
            elif case == "duplicate": request["nodes"].append(request["nodes"][1])
            else: request["nodes"] *= 3
            with self.subTest(case=case), self.assertRaises(SwarmError):
                self.run_reader(data, request=request)

    def test_distinct_files_cannot_alias_one_stable_id_and_foreign_paths_cannot_import(self):
        data = self.graph()
        row = copy.deepcopy(data[1]["sources"][1])
        row["key"] = hashlib.sha256(b"different-source-same-id").hexdigest()
        path = self.root / "work/copy.md"
        path.write_bytes(row["text"].encode())
        data[1]["sources"].append(row)
        data[4]["nodes"].append({"path": "work/copy.md", "source_key": row["key"], "source_revision": row["revision"]})
        self.change_source(data[1], data[2], data[3], data[4], 0, lambda raw: raw)
        with self.assertRaisesRegex(SwarmError, "HIERARCHY_ID_AMBIGUOUS"):
            self.run_reader(data)
        data[4]["nodes"].pop()
        for path in ("../outside.md", "/outside.md", "C:outside.md", "C:/outside.md", "\\\\server\\share\\outside.md"):
            request = copy.deepcopy(data[4])
            request["nodes"][0]["path"] = path
            with self.subTest(path=path), self.assertRaisesRegex(SwarmError, "HIERARCHY_PATH_INVALID"):
                self.run_reader(data, request=request)

    def test_source_tamper_same_size_mtime_and_add_delete_rename_refuse(self):
        for case in ("same_size", "add", "delete", "rename"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                old_root, self.root = self.root, Path(tmp).resolve()
                try:
                    data = self.graph()
                    path = self.root / data[4]["nodes"][1]["path"]
                    info = path.stat()
                    if case == "same_size":
                        path.write_bytes(path.read_bytes().replace(b"unknown", b"missing"))
                        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                    elif case == "add": (self.root / "knowledge/new.md").write_bytes(b"added")
                    elif case == "delete": path.unlink()
                    else: path.rename(path.with_suffix(".moved"))
                    with self.assertRaises((SwarmError, RuntimeError, OSError)):
                        self.run_reader(data)
                finally:
                    self.root = old_root

    def test_wrong_source_revision_and_wrong_task_refuse(self):
        data = self.graph()
        request = copy.deepcopy(data[4])
        request["nodes"][1]["source_revision"] = 0
        with self.assertRaisesRegex(SwarmError, "OBJECTIVE_SOURCE"):
            self.run_reader(data, request=request)
        request = copy.deepcopy(data[4])
        request["references"][0]["id"] = "task-00000000-0000-4000-8000-000000000002"
        with self.assertRaisesRegex(SwarmError, "HIERARCHY_TASK_STALE"):
            self.run_reader(data, request=request)

    def test_actual_saved_worker_critic_and_plan_are_read_without_sqlite_or_dispatch(self):
        data, backend, result = self.completed()
        before, inputs = inventory(self.root), copy.deepcopy(backend.inputs)
        with mock.patch.object(sqlite3, "connect", side_effect=AssertionError("query opened SQLite")), \
             mock.patch("runtime.task_swarm.state.SwarmState.__init__", side_effect=AssertionError("query constructed state")), \
             mock.patch("runtime.task_swarm.closed_loop.execute_closed_loop", side_effect=AssertionError("query dispatched")):
            trace = self.run_reader(data)
        self.assertEqual(before, inventory(self.root))
        self.assertEqual(inputs, backend.inputs)
        proof = trace["resolved_references"][1]
        self.assertNotEqual(proof["specification_digest"], proof["execution_plan_digest"])
        self.assertEqual("task_run", proof["revision_scope"])
        self.assertEqual(["work", "work", "critic"], [entry["role"] for entry in proof["dispatches"]])
        self.assertEqual("not_observed", proof["current_cancellation"])
        self.assertEqual("candidate_only", proof["learning_artifact"])
        self.assertEqual(result["receipt_sha256"], proof["receipt_sha256"])

    def test_same_owner_new_revision_changes_actual_worker_and_critic_bytes(self):
        first, backend, receipt = self.completed()
        trace = self.run_reader(first)
        old_dir = first[2].parent / receipt["receipt"]["run_id"]
        old_raw = {entry["job_id"]: (old_dir / (entry["job_id"] + "-input.json")).read_bytes()
                   for entry in backend.inputs}
        second, newer, new_receipt = self.completed(corrected=True)
        self.assertEqual(first[2], second[2])
        new_trace = self.run_reader(second)
        new_dir = second[2].parent / new_receipt["receipt"]["run_id"]
        for entry in newer.inputs:
            raw = (new_dir / (entry["job_id"] + "-input.json")).read_bytes()
            self.assertNotEqual(old_raw[entry["job_id"]], raw)
            self.assertEqual(json.loads(raw), entry)
        self.assertNotEqual(trace["parent_input_digest"], new_trace["parent_input_digest"])
        self.assertNotEqual(trace["trace_digest"], new_trace["trace_digest"])
        self.assertEqual(trace["closure"], new_trace["closure"])
        self.assertEqual(trace["reverse_refs"], new_trace["reverse_refs"])
        self.assertNotEqual(trace["nodes"], new_trace["nodes"])
        self.assertEqual(new_receipt["receipt_sha256"], new_trace["resolved_references"][1]["receipt_sha256"])
        count = len(newer.inputs)
        with self.assertRaisesRegex(SwarmError, "STALE_BINDING"):
            self.run_reader(first)
        with self.assertRaisesRegex(SwarmError, "HIERARCHY_PLAN_STALE"):
            self.run_reader(second, request={**second[4], "references": [first[4]["references"][1]]})
        self.assertEqual(count, len(newer.inputs))

    def test_diamond_current_revision_changes_closure_reverse_refs_and_real_consumer_bytes(self):
        first, backend, receipt = self.completed_diamond()
        old = self.run_reader(first)
        before = inventory(self.root)
        self.run_reader(first)
        self.assertEqual(before, inventory(self.root))
        old_dir = first[2].parent / receipt["receipt"]["run_id"]
        saved = {entry["job_id"]: (old_dir / (entry["job_id"] + "-input.json")).read_bytes() for entry in backend.inputs}
        second, new_backend, new_receipt = self.completed_diamond(corrected=True)
        current = self.run_reader(second)
        self.assertEqual(first[2], second[2])
        self.assertNotEqual(old["closure"], current["closure"])
        self.assertNotEqual(old["reverse_refs"], current["reverse_refs"])
        self.assertEqual(["original", "replacement"], [row["role"] for row in current["context_candidate"]["intent_history"]])
        self.assertEqual(first[1]["request"], current["context_candidate"]["intent_history"][0]["text"])
        self.assertEqual(second[1]["request"], current["context_candidate"]["intent_history"][1]["text"])
        self.assertEqual(["PROJECT-A", "PHASE-B"], next(node for node in current["nodes"] if node["id"] == "REQ-ROOT")["parents"])
        new_dir = second[2].parent / new_receipt["receipt"]["run_id"]
        for entry in new_backend.inputs:
            raw = (new_dir / (entry["job_id"] + "-input.json")).read_bytes()
            self.assertNotEqual(saved[entry["job_id"]], raw)
            self.assertEqual(json.loads(raw), entry)
            self.assertEqual(second[1]["objective"], entry["view"]["objective"])
        self.assertEqual("critic", new_backend.inputs[-1]["role"])
        with self.assertRaisesRegex(SwarmError, "STALE_BINDING"):
            self.run_reader(first)
        self.assertEqual(3, len(new_backend.inputs))

    def test_only_caller_plan_missing_anchor_or_staged_receipt_is_not_saved_proof(self):
        data, _, result = self.completed()
        request = copy.deepcopy(data[4])
        request["references"][1].pop("receipt_sha256")
        with self.assertRaisesRegex(SwarmError, "HIERARCHY_REFERENCE_INVALID"):
            self.run_reader(data, request=request)
        directory = data[2].parent / result["receipt"]["run_id"]
        (directory / "receipt.json").rename(directory / ".receipt-pending.json")
        with self.assertRaises(OSError):
            self.run_reader(data)

    def test_saved_inputs_critic_and_result_tamper_fail_even_if_manifest_is_reanchored(self):
        for artifact in ("r0-requirement-0-input.json", "r0-critic-input.json", "r0-requirement-0-result.json", "plan.json"):
            with self.subTest(artifact=artifact), tempfile.TemporaryDirectory() as tmp:
                old_root, self.root = self.root, Path(tmp).resolve()
                try:
                    data, _, result = self.completed()
                    directory = data[2].parent / result["receipt"]["run_id"]
                    path = directory / artifact
                    value = json.loads(path.read_bytes())
                    if artifact == "plan.json": value["task_id"] = "task-00000000-0000-4000-8000-000000000002"
                    elif artifact.endswith("result.json"): value["result"]["claims"][0]["evidence"][0]["quote"] = "tampered"
                    elif artifact.startswith("r0-critic"): value["reports"] = {}
                    else: value["purpose"] = "A reflected instruction, not the saved owner purpose."
                    path.write_bytes((canonical(value) + "\n").encode())
                    receipt_path = directory / "receipt.json"
                    receipt = json.loads(receipt_path.read_bytes())
                    receipt["artifact_sha256"][artifact] = hashlib.sha256(path.read_bytes()).hexdigest()
                    receipt["artifact_bytes"] = sum((directory / name).stat().st_size for name in receipt["artifact_sha256"])
                    receipt_path.write_bytes((canonical(receipt) + "\n").encode())
                    data[4]["references"][1]["receipt_sha256"] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
                    with self.assertRaises(SwarmError):
                        self.run_reader(data)
                finally:
                    self.root = old_root

    def test_reanchored_saved_json_numeric_aliases_cannot_replace_exact_inputs_or_plan(self):
        data, backend, result = self.completed_diamond()
        directory = data[2].parent / result["receipt"]["run_id"]
        original = {path.name: path.read_bytes() for path in directory.glob("*.json")}
        anchor = data[4]["references"][1]["receipt_sha256"]
        cases = [
            ("input.json", ("revision",), True, "RUN_REPLAY_CONFLICT"),
            ("input.json", ("revision",), 1.0, "RUN_REPLAY_CONFLICT"),
            ("input.json", ("sources", 0, "revision"), True, "RUN_REPLAY_CONFLICT"),
            ("input.json", ("sources", 0, "revision"), 1.0, "RUN_REPLAY_CONFLICT"),
            ("input.json", ("objective", "references", 0, "source", "source_revision"), True, "RUN_REPLAY_CONFLICT"),
            ("input.json", ("objective", "budget", "attempt_budget"), 4.0, "RUN_REPLAY_CONFLICT"),
            ("plan.json", ("budget", "concurrency"), 2.0, "HIERARCHY_PLAN_INVALID"),
            ("plan.json", ("budget", "attempt_budget"), 4.0, "HIERARCHY_PLAN_INVALID"),
            ("execution.json", ("plan", "budget", "concurrency"), 2.0, "HIERARCHY_EXECUTION_INVALID"),
            ("execution.json", ("jobs", "r0-left", "attempt_count"), True, "HIERARCHY_EXECUTION_INVALID"),
            ("execution.json", ("jobs", "r0-left", "attempt_count"), 1.0, "HIERARCHY_EXECUTION_INVALID"),
            ("candidate.json", ("revision",), True, "HIERARCHY_CANDIDATE_CONFLICT"),
            ("candidate.json", ("revision",), 1.0, "HIERARCHY_CANDIDATE_CONFLICT"),
            ("candidate.json", ("owner_accepted",), 0, "HIERARCHY_CANDIDATE_CONFLICT"),
            ("learning.json", ("revision",), True, "HIERARCHY_CANDIDATE_CONFLICT"),
            ("learning.json", ("revision",), 1.0, "HIERARCHY_CANDIDATE_CONFLICT"),
            ("learning.json", ("next_context_eligible",), 0, "HIERARCHY_CANDIDATE_CONFLICT"),
            ("receipt.json", ("version",), 2.0, "LOOP_EVIDENCE_POLICY"),
            ("receipt.json", ("artifact_bytes",), float(result["receipt"]["artifact_bytes"]), "LOOP_ARTIFACT_BUDGET"),
            ("receipt.json", ("context_bytes",), float(result["receipt"]["context_bytes"]), "LOOP_CONTEXT_BUDGET"),
        ]
        calls = len(backend.inputs)
        for artifact, path_keys, replacement, error in cases:
            with self.subTest(artifact=artifact, field=path_keys, value=replacement):
                for name, raw in original.items():
                    (directory / name).write_bytes(raw)
                data[4]["references"][1]["receipt_sha256"] = anchor
                value = json.loads(original[artifact])
                target = value
                for key in path_keys[:-1]:
                    target = target[key]
                target[path_keys[-1]] = replacement
                self.assertEqual(json.loads(original[artifact]), value)  # Demonstrate Python's numeric alias.
                self.assertNotEqual(canonical(json.loads(original[artifact])), canonical(value))
                (directory / artifact).write_bytes((canonical(value) + "\n").encode())
                receipt = value if artifact == "receipt.json" else json.loads(original["receipt.json"])
                if artifact != "receipt.json":
                    receipt["artifact_sha256"][artifact] = hashlib.sha256((directory / artifact).read_bytes()).hexdigest()
                    receipt["artifact_bytes"] = sum((directory / name).stat().st_size for name in receipt["artifact_sha256"])
                (directory / "receipt.json").write_bytes((canonical(receipt) + "\n").encode())
                data[4]["references"][1]["receipt_sha256"] = hashlib.sha256((directory / "receipt.json").read_bytes()).hexdigest()
                before = inventory(self.root)
                with self.assertRaisesRegex(SwarmError, error):
                    self.run_reader(data)
                self.assertEqual(before, inventory(self.root))
                self.assertEqual(calls, len(backend.inputs))
        for name, raw in original.items():
            (directory / name).write_bytes(raw)
        data[4]["references"][1]["receipt_sha256"] = anchor
        self.assertEqual("TRACED_CANDIDATE", self.run_reader(data)["status"])

    def test_reanchored_worker_round_alias_cannot_change_actual_delivered_bytes(self):
        data, backend, result = self.completed_diamond()
        directory = data[2].parent / result["receipt"]["run_id"]
        original = {path.name: path.read_bytes() for path in directory.glob("*.json")}
        anchor = data[4]["references"][1]["receipt_sha256"]
        for replacement in (False, 0.0):
            with self.subTest(value=replacement):
                for name, raw in original.items():
                    (directory / name).write_bytes(raw)
                delivered = json.loads(original["r0-left-input.json"])
                delivered["round"] = replacement
                self.assertEqual(delivered, json.loads(original["r0-left-input.json"]))
                self.assertNotEqual(canonical(delivered), canonical(json.loads(original["r0-left-input.json"])))
                response = json.loads(original["r0-left-result.json"])
                response["receipt"]["input_digest"] = digest(delivered)
                for name, value in (("r0-left-input.json", delivered), ("r0-left-result.json", response)):
                    (directory / name).write_bytes((canonical(value) + "\n").encode())
                execution = json.loads(original["execution.json"])
                execution["jobs"]["r0-left"]["current_attempt"]["result_digest"] = hashlib.sha256(
                    (directory / "r0-left-result.json").read_bytes()).hexdigest()
                (directory / "execution.json").write_bytes((canonical(execution) + "\n").encode())
                receipt = json.loads(original["receipt.json"])
                receipt["dispatches"]["r0-left"]["delivered_input_digest"] = digest(delivered)
                receipt["artifact_sha256"] = {name: hashlib.sha256((directory / name).read_bytes()).hexdigest()
                                               for name in receipt["artifact_sha256"]}
                receipt["artifact_bytes"] = sum((directory / name).stat().st_size for name in receipt["artifact_sha256"])
                receipt["context_bytes"] = sum(len(canonical(json.loads((directory / name).read_bytes())).encode())
                    for name in receipt["artifact_sha256"] if name.endswith("-input.json"))
                (directory / "receipt.json").write_bytes((canonical(receipt) + "\n").encode())
                data[4]["references"][1]["receipt_sha256"] = hashlib.sha256((directory / "receipt.json").read_bytes()).hexdigest()
                before = inventory(self.root)
                with self.assertRaisesRegex(SwarmError, "LOOP_WORK_BINDING"):
                    self.run_reader(data)
                self.assertEqual(before, inventory(self.root))
                self.assertEqual(3, len(backend.inputs))
        for name, raw in original.items():
            (directory / name).write_bytes(raw)
        data[4]["references"][1]["receipt_sha256"] = anchor
        self.assertEqual("TRACED_CANDIDATE", self.run_reader(data)["status"])

    def test_current_actor_withdrawal_and_expiry_fail_before_return(self):
        data, _, _ = self.completed()
        document = json.loads(data[2].read_bytes())
        document["actors"]["worker-a"]["actor_status"] = "revoked"
        data[2].write_bytes(canonical(document).encode())
        with self.assertRaises(SwarmError): self.run_reader(data)
        data = self.graph(corrected=True)
        with self.assertRaisesRegex(SwarmError, "EXPIRED_BINDING"):
            self.run_reader(data, clock=lambda: self.now + 200)

    def test_final_guard_observes_source_owner_and_artifact_mutations(self):
        import kotodama_kb.hierarchy_reader as reader
        for kind in ("source", "owner", "artifact"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                old_root, self.root = self.root, Path(tmp).resolve()
                try:
                    data, _, result = self.completed()
                    real_copy, calls = reader._copy, [0]
                    def mutate_after_output(value):
                        returned = real_copy(value)
                        if value.get("kind") == "kotodama.hierarchy-trace":
                            if kind == "source": path = self.root / data[4]["nodes"][0]["path"]
                            elif kind == "owner": path = data[2]
                            else: path = data[2].parent / result["receipt"]["run_id"] / "r0-critic-input.json"
                            path.write_bytes(path.read_bytes() + b" ")
                            calls[0] += 1
                        return returned
                    with mock.patch.object(reader, "_copy", side_effect=mutate_after_output):
                        with self.assertRaises((SwarmError, RuntimeError)):
                            self.run_reader(data)
                    self.assertEqual(1, calls[0])
                finally:
                    self.root = old_root

    def test_real_clock_freshness_not_bundle_old_boolean_and_midquery_expiry(self):
        fixture.small_catalog(self.root)
        path = self.root / "knowledge/synthetic/0.md"
        expiry = dt.datetime.fromtimestamp(self.now + 1, dt.timezone.utc).isoformat()
        path.write_bytes(path.read_bytes().replace(b"2026-12-07T00:00:00Z", expiry.encode()))
        # The real owner may admit this finite Task budget; the reader independently checks Concept TTL.
        prepared, _, _ = self.completed_diamond()
        data = (load_bundle(self.root, as_of=fixture.NOW), *prepared[1:])
        self.assertFalse(data[0].concepts[0].is_stale)
        self.assertEqual("TRACED_CANDIDATE", self.run_reader(data)["status"])
        import kotodama_kb.hierarchy_reader as reader
        with self.assertRaisesRegex(SwarmError, "HIERARCHY_CONTEXT_EXPIRED"):
            self.run_reader(data, clock=lambda: self.now + 1)
        real_copy = reader._copy
        clock = [self.now]
        def expire_after_output(value):
            result = real_copy(value)
            if value.get("kind") == "kotodama.hierarchy-trace": clock[0] = self.now + 1
            return result
        with mock.patch.object(reader, "_copy", side_effect=expire_after_output):
            with self.assertRaisesRegex(SwarmError, "HIERARCHY_CONTEXT_EXPIRED"):
                self.run_reader(data, clock=lambda: clock[0])

    def test_real_thread_add_delete_rename_after_frame_preparation_refuse(self):
        import kotodama_kb.hierarchy_reader as reader
        for kind in ("add", "delete", "rename"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                old_root, self.root = self.root, Path(tmp).resolve()
                try:
                    data = self.graph()
                    ready, finished = threading.Event(), threading.Event()
                    failures = []
                    def change_source():
                        try:
                            if not ready.wait(5): raise AssertionError("trace did not reach its render boundary")
                            path = self.root / "knowledge/synthetic/0.md"
                            if kind == "add": path.with_name("added.md").write_bytes(b"new source")
                            elif kind == "delete": path.unlink()
                            else: path.rename(path.with_name("renamed.md"))
                        except BaseException as exc:
                            failures.append(exc)
                        finally:
                            finished.set()
                    thread = threading.Thread(target=change_source)
                    thread.start()
                    real_canonical = reader.canonical
                    def interleave(value):
                        raw = real_canonical(value)
                        if isinstance(value, dict) and value.get("kind") == "kotodama.hierarchy-trace" and "trace_digest" in value:
                            ready.set()
                            self.assertTrue(finished.wait(5))
                        return raw
                    try:
                        with mock.patch.object(reader, "canonical", side_effect=interleave):
                            with self.assertRaises((SwarmError, RuntimeError, OSError)):
                                self.run_reader(data)
                    finally:
                        ready.set()
                        thread.join(5)
                    self.assertFalse(thread.is_alive())
                    self.assertEqual([], failures)
                finally:
                    self.root = old_root

    def test_learning_grant_is_unresolved_without_observing_current_decision(self):
        data = self.graph()
        document = json.loads(data[2].read_bytes())
        document["learning_reuse"] = {"opaque": "No automatic current-decision assertion."}
        data[2].write_bytes(canonical(document).encode())
        result = self.run_reader(data)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIsNone(result["context_candidate"])
        self.assertEqual("CURRENT_DECISION_NOT_OBSERVED", result["unresolved"][0]["reason"])

    def test_learning_source_without_grant_cannot_imply_current_decision(self):
        data = self.graph()
        data[1]["sources"].append(fixture.source("unadopted-learning", 1,
            canonical({"kind": "task_learning_reuse_proposal", "version": 1})))
        self.change_source(data[1], data[2], data[3], data[4], 0, lambda text: text)
        result = self.run_reader(data)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIsNone(result["context_candidate"])
        self.assertEqual("not_observed", result["current_learning_decision"])

    def test_superseded_learning_proposal_uses_latest_source_without_losing_history(self):
        data = self.graph()
        original_sources = copy.deepcopy(data[1]["sources"])
        proposal = canonical({"kind": "task_learning_reuse_proposal", "version": 1})
        for latest_text in ("The prior learning proposal is withdrawn.",
                            canonical({"kind": "corrected_source", "text": "No learning proposal remains."})):
            rows = [fixture.source("learning-history", 1, proposal),
                    fixture.source("learning-history", 3, proposal),
                    fixture.source("learning-history", 7, latest_text)]
            for order in ((0, 1, 2), (2, 0, 1), (1, 2, 0)):
                with self.subTest(latest=latest_text, order=order):
                    data[1]["sources"] = copy.deepcopy(original_sources + [rows[i] for i in order])
                    self.change_source(data[1], data[2], data[3], data[4], 0, lambda text: text)
                    before, expected = inventory(self.root), copy.deepcopy(data[1])
                    result = self.run_reader(data)
                    self.assertEqual("TRACED_CANDIDATE", result["status"])
                    self.assertIsNotNone(result["context_candidate"])
                    self.assertEqual([], result["unresolved"])
                    self.assertEqual(digest(expected), result["parent_input_digest"])
                    self.assertEqual(expected, data[1])
                    self.assertEqual(expected, json.loads(data[3].read_bytes()))
                    self.assertEqual(before, inventory(self.root))

    def test_current_learning_sources_and_owner_grants_still_block_after_correction(self):
        data = self.graph()
        original_sources = copy.deepcopy(data[1]["sources"])
        proposal = canonical({"kind": "task_learning_reuse_proposal", "version": 1})
        old = fixture.source("learning-history", 1, proposal)
        withdrawn = fixture.source("learning-history", 7, "The old proposal is withdrawn.")
        for kind in ("same_key", "other_key", "owner_grant"):
            with self.subTest(kind=kind):
                current = fixture.source("learning-history", 9, proposal) if kind == "same_key" else (
                    fixture.source("other-learning", 0, proposal) if kind == "other_key" else None)
                data[1]["sources"] = copy.deepcopy(original_sources + ([current] if current else []) + [withdrawn, old])
                self.change_source(data[1], data[2], data[3], data[4], 0, lambda text: text)
                if kind == "owner_grant":
                    document = json.loads(data[2].read_bytes())
                    document["learning_reuse"] = {"opaque": "A current decision is still required."}
                    data[2].write_bytes(canonical(document).encode())
                before = inventory(self.root)
                result = self.run_reader(data)
                self.assertEqual("BLOCKED", result["status"])
                self.assertIsNone(result["context_candidate"])
                self.assertEqual("not_observed", result["current_learning_decision"])
                expected = {"kind": "learning_reuse", "reason": "CURRENT_DECISION_NOT_OBSERVED",
                            "next_action": "use_current_learning_verifier", "mandatory": True}
                if current:
                    expected.update(source_key=current["key"], source_revision=current["revision"])
                self.assertEqual([expected], result["unresolved"])
                self.assertEqual(before, inventory(self.root))

    def test_artifact_count_budget_and_complete_statement_budget_do_not_truncate(self):
        data, _, result = self.completed()
        directory = data[2].parent / result["receipt"]["run_id"]
        path = directory / "receipt.json"
        receipt = json.loads(path.read_bytes())
        while len(receipt["artifact_sha256"]) <= 32:
            receipt["artifact_sha256"]["extra-" + str(len(receipt["artifact_sha256"])) + ".json"] = "a" * 64
        path.write_bytes((canonical(receipt) + "\n").encode())
        data[4]["references"][1]["receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaisesRegex(SwarmError, "RUN_RECEIPT_INVALID"):
            self.run_reader(data)
        # Mandatory statements can each be locally valid and still exceed the whole-context cap.
        data = self.graph(corrected=True)
        for index in (0, 1):
            statements = [f"Bounded constraint {index}-{number}." for number in range(20)]
            def expand(text, values=statements):
                meta = yaml.safe_load(text.split("---", 2)[1])
                meta["task_context"]["constraints"] = values
                return fixture.markdown(meta, "\n\n".join(values))
            self.change_source(data[1], data[2], data[3], data[4], index, expand)
        with self.assertRaisesRegex(SwarmError, "HIERARCHY_CONTEXT_LIMIT"):
            self.run_reader(data)

    def test_complete_output_byte_budget_refuses_without_partial_context(self):
        data = self.graph()
        for identifier in ("PROJECT-B", "PROJECT-C"):
            raw = fixture.markdown({"id": identifier, "template_kind": "project", "status": "draft",
                                  "task_context": {"constraints": []}}, "Concrete candidate.")
            row = fixture.source(identifier, 1, raw)
            path = self.root / "work" / (identifier + ".md")
            path.write_bytes(raw.encode())
            data[1]["sources"].append(row)
            data[4]["nodes"].append({"path": path.relative_to(self.root).as_posix(),
                                    "source_key": row["key"], "source_revision": 1})
        self.change_source(data[1], data[2], data[3], data[4], 1,
                           lambda raw: raw.replace("- PROJECT-A", "- PROJECT-A\n- PROJECT-B"))
        self.change_source(data[1], data[2], data[3], data[4], 2,
                           lambda raw: raw.replace("- PROJECT-A", "- PROJECT-C"))
        for index in range(6):
            def expand(raw, node_index=index):
                meta = yaml.safe_load(raw.split("---", 2)[1])
                values = [(f"{node_index}-{number} " + "😀" * 1000)[:1000] for number in range(5)]
                meta["task_context"]["constraints"] = values
                extra = [meta["task_context"]["need"], *meta["task_context"]["acceptance"]] if meta["template_kind"] == "requirement" else []
                return fixture.markdown(meta, "\n\n".join([*values, *extra]))
            self.change_source(data[1], data[2], data[3], data[4], index, expand)
        self.assertLessEqual(len(canonical(data[1]).encode()), MAX_INPUT_BYTES)
        self.assertTrue(all(len(row["text"]) <= 12000 for row in data[1]["sources"]))
        with self.assertRaisesRegex(SwarmError, "HIERARCHY_OUTPUT_LIMIT"):
            self.run_reader(data)

    def test_standalone_cli_uses_current_owner_and_emits_whole_utf8_result(self):
        self.now = time.time()  # Only the real CLI uses a real-clock owner; API fixtures stay deterministic.
        data = self.graph()
        request = self.root / "request.json"
        request.write_bytes(canonical(data[4]).encode())
        before = inventory(self.root)
        command = [sys.executable, "-I", "-B", str(ROOT / "tools/hierarchy_trace.py"), "--root", str(self.root),
                   "--owner", str(data[2]), "--input", str(data[3]), "--request", str(request)]
        child = subprocess.run(command, cwd=self.root.parent, capture_output=True, timeout=20)
        self.assertEqual(0, child.returncode, child.stderr.decode())
        value = json.loads(child.stdout)
        self.assertEqual("TRACED_CANDIDATE", value["status"])
        self.assertLessEqual(len(child.stdout), MAX_INPUT_BYTES + 1)
        self.assertEqual(before, inventory(self.root))
        malformed = copy.deepcopy(data[4])
        malformed["references"][0]["revision"] += 1
        request.write_bytes(canonical(malformed).encode())
        refused = subprocess.run(command, cwd=self.root.parent, capture_output=True, timeout=20)
        self.assertEqual(2, refused.returncode)
        self.assertEqual(b"", refused.stdout)
        self.assertIsNone(json.loads(refused.stderr)["context_candidate"])

    def test_owner_alias_uses_canonical_relative_source_checks_in_the_real_cli(self):
        self.now = time.time()
        data = self.graph()
        owner = data[2]
        document = json.loads(owner.read_bytes())
        for item in document["source_checks"]:
            item["path"] = os.path.relpath(item["path"], owner.parent)
        owner.write_bytes(canonical(document).encode())
        selected = self.root / "selected"
        selected.mkdir()
        alias = selected / "owner.json"
        try:
            alias.symlink_to(owner)
        except OSError:
            self.skipTest("owner symlink creation is not available")
        request = self.root / "request.json"
        request.write_bytes(canonical(data[4]).encode())
        before, outputs = inventory(self.root), []
        for path in (owner, alias):
            command = [sys.executable, "-I", "-B", str(ROOT / "tools/hierarchy_trace.py"),
                "--root", str(self.root), "--owner", str(path), "--input", str(data[3]),
                "--request", str(request)]
            child = subprocess.run(command, cwd=selected, capture_output=True, timeout=20)
            self.assertEqual(0, child.returncode, child.stderr.decode())
            self.assertEqual(b"", child.stderr)
            outputs.append(child.stdout)
            self.assertEqual(before, inventory(self.root))
        self.assertEqual(outputs[0], outputs[1])
        source = self.root / data[4]["nodes"][0]["path"]
        source.write_bytes(source.read_bytes() + b"\n")
        changed = inventory(self.root)
        refused = subprocess.run(command, cwd=selected, capture_output=True, timeout=20)
        self.assertEqual(2, refused.returncode)
        self.assertEqual(b"", refused.stdout)
        self.assertIsNone(json.loads(refused.stderr)["context_candidate"])
        self.assertEqual(changed, inventory(self.root))


if __name__ == "__main__":
    unittest.main()
