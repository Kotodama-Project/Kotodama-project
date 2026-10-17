"""Source-declared initial work, real owner admission and computed fixture reports.

This fixture checks #361 distribution, plans and computed reports. The runtime
enforces every criterion's assigned-leaf evidence under contract 2.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tests.test_knowledge_task_input import (CONSTRAINT, MARKER, STAMP, admit,
    change_declaration, markdown, reseal_seed, setup, source, span)
from kotodama_kb.task_frontier import frontier_work, resolve_frontier
from kotodama_kb.task_input import compile_task_input, execute_task_input, verify_task_input
from runtime.task_swarm.protocol import SwarmError, canonical, digest


def graph(*, two=False, shared=False, corrected=False):
    latency = {"operation": "latency", "values": list(range(1, 21))}
    rss = {"operation": "rss", "values": [None, 96, 128] if corrected else [None, 64, 96]}
    if shared:
        return {"REQ-ROOT": {"children": ["REQ-G1", "REQ-G2"]},
                "REQ-G1": {"children": ["REQ-C"], "constraints": ["G1 measurements stay separate."]},
                "REQ-G2": {"children": ["REQ-C"], "constraints": ["G2 missing data stays unknown."]},
                "REQ-C": {"data": latency}}
    if two:
        return {"REQ-ROOT": {"children": ["REQ-LATENCY", "REQ-RSS"]},
                "REQ-LATENCY": {"data": latency}, "REQ-RSS": {"data": rss}}
    return {"REQ-ROOT": {"data": latency}}


def fixture(root, spec, *, corrected=False, public=False):
    bundle, seed, owner, file = setup(root, jobs=1, corrected=corrected, public=public)
    project = next(row for row in seed["sources"] if MARKER in row["text"])
    request_key = source("request", 1, "")["key"]
    requests = [row for row in seed["sources"] if row["key"] == request_key]
    for row in requests:
        row["text"] = ("Report source-bound benchmark observations." if row["revision"] == 1 else
                       "Report source-bound observations with the corrected RSS workload.")
    seed["request"] = requests[-1]["text"]
    old = source("REQ-0", 1, "")["key"]
    seed["sources"] = [row for row in seed["sources"] if row["key"] != old]
    rows, hierarchy, conditions = {}, [], {}
    for identifier, value in spec.items():
        need = (f"[{identifier}] DATA=" + canonical(value["data"]) if "data" in value else
                identifier + " combines every required child.")
        accepted = value.get("acceptance", [identifier + " results match the current measurements."])
        constraints = value.get("constraints", [])
        fields = {"need": need, "acceptance": accepted, "constraints": constraints,
                  "frontier": {"kind": "all_of" if "children" in value else "atomic",
                               "children": value.get("children", []), "requires": value.get("requires", [])}}
        text = markdown({"template_kind": "requirement", "id": identifier,
                         "parent_ref": "PROJECT-SYNTHETIC", "status": "draft", "task_context": fields},
                        "\n\n".join([need, *accepted, *constraints]))
        row = source(identifier, 2 if corrected and identifier == "REQ-RSS" else 1, text)
        path = root / "work" / (identifier + ".md")
        path.write_bytes(text.encode("utf-8"))
        rows[identifier] = row
        seed["sources"].append(row)
        hierarchy.append({"path": path.relative_to(root).as_posix(),
                          "source_key": row["key"], "source_revision": row["revision"]})
        conditions[identifier] = accepted
    seed["acceptance"] = [value for key in ["REQ-ROOT", *sorted(set(spec) - {"REQ-ROOT"})]
                          for value in conditions[key]]
    hierarchy.append({"path": "work/project.md", "source_key": project["key"],
                      "source_revision": project["revision"]})
    def declaration(value):
        value["version"] = 2
        value.pop("jobs")
        value["root_requirement_id"] = "REQ-ROOT"
        value["hierarchy"] = hierarchy
        value["intent"] = {"original": span(requests[0], requests[0]["text"]),
                           "replacements": [span(row, row["text"]) for row in requests[1:]]}
    change_declaration(seed, root, declaration)
    reseal_seed(seed, owner, file)
    return bundle, seed, owner, file, rows


class ComputingBackend:
    synthetic = True

    def __init__(self, *, mode="computed"):
        self.inputs, self.mode = [], mode

    @staticmethod
    def decode(need):
        return json.loads(need.split(" DATA=", 1)[1])

    def produce(self, delivered, directory, *, actor_ref, **kwargs):
        self.inputs.append(copy.deepcopy(delivered))
        need = delivered["purpose"]
        data = self.decode(need)
        values = data["values"]
        if data["operation"] == "latency":
            result = {"p95_ms": sorted(values)[math.ceil(.95 * len(values)) - 1]}
        else:
            result = {"peak_mib": max(v for v in values if v is not None),
                      "missing": sum(v is None for v in values)}
        if self.mode == "wrong_leaf":
            result = {"peak_mib": 19, "missing": 0} if data["operation"] == "latency" else {"p95_ms": 96}
        record = next(row for row in delivered["view"]["spans"] if row["text"] == need)
        evidence = {key: record[key] for key in ("source_key", "source_revision", "start", "end")}
        claim = need if self.mode == "echo" else canonical(result)
        return {"result": {"job_id": delivered["job_id"], "summary": "Computed current observations.",
                "conflicts": [], "claims": [{"text": claim, "status": "inference",
                                              "evidence": [{**evidence, "quote": need}]}]},
                "receipt": {"actor_ref": actor_ref, "invocation_ref": "synthetic-" + delivered["job_id"],
                            "input_digest": digest(delivered), "synthetic": True}}

    def review(self, delivered, directory, *, actor_ref, **kwargs):
        self.inputs.append(copy.deepcopy(delivered))
        expected = {}
        for row in delivered["view"]["spans"]:
            text = row["text"]
            if not text.startswith("[REQ-") or " DATA=" not in text:
                continue
            identifier = text.split("]", 1)[0][1:]
            data = self.decode(text)
            values = data["values"]
            if data["operation"] == "latency":
                value = next(v for n, v in enumerate(sorted(values), 1) if n / len(values) >= .95)
                result = {"p95_ms": value}
            else:
                measured = sorted(v for v in values if v is not None)
                result = {"peak_mib": measured[-1], "missing": len(values) - len(measured)}
            key = "r0-leaf-" + hashlib.sha256(identifier.encode()).hexdigest()[:32]
            expected[key] = canonical(result)
        reports = delivered["reports"]
        passed = set(expected) == set(reports) and all(
            report["claims"][0]["text"] == expected[key] for key, report in reports.items())
        record = next(row for row in delivered["view"]["spans"] if row["text"].startswith("[REQ-"))
        gap = {key: record[key] for key in ("source_key", "source_revision", "start", "end")}
        return {"result": {"parent_input_digest": delivered["view"]["parent_input_digest"],
                "plan_digest": delivered["view"]["plan_digest"], "round": delivered["round"],
                "report_digests": delivered["report_digests"], "validations": [
                    {"criterion_id": key, "status": "passed" if passed else "failed",
                     "evidence": [{"job_id": job, "claim_index": 0}
                         for job in delivered["required_evidence_jobs"][key]] if passed else [],
                     "gap_reason": None if passed else "Current source calculations do not match these reports.",
                     "source_spans": [] if passed else [gap]} for key in delivered["criteria"]]},
                "receipt": {"actor_ref": actor_ref, "invocation_ref": "synthetic-" + delivered["job_id"],
                            "input_digest": digest(delivered), "synthetic": True}}


class TaskFrontierTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def compile(self, spec, **options):
        bundle, seed, owner, file, rows = fixture(self.root, spec, **options)
        before = owner.read_bytes(), file.read_bytes(), copy.deepcopy(seed)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(before, (owner.read_bytes(), file.read_bytes(), seed))
        return bundle, candidate, owner, file, rows

    def execute(self, bundle, candidate, owner, file, *, mode="computed", actors=2, **options):
        admit(candidate, owner, file)
        backend = ComputingBackend(mode=mode)
        result = execute_task_input(bundle, candidate, owner, file, backend,
            worker_actors=["worker-a", "worker-b", "worker-c"][:actors], clock=lambda: STAMP, **options)
        return backend, result

    def test_one_two_and_shared_leaf_change_real_inputs_and_dispatch_counts(self):
        for name, spec, count in (("one", graph(), 1), ("two", graph(two=True), 2),
                                  ("shared", graph(shared=True), 1)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, seed, owner, file, _ = fixture(root, spec)
                candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                self.assertEqual(count, len(candidate["supplied_plan"]["jobs"]))
                backend, result = self.execute(bundle, candidate, owner, file)
                self.assertEqual(count + 1, len(backend.inputs))
                self.assertTrue(result["receipt"]["review_passed"])
                directory = owner.parent / result["receipt"]["run_id"]
                for key, binding in result["receipt"]["dispatches"].items():
                    saved = json.loads((directory / (key + "-input.json")).read_text())
                    self.assertEqual(digest(saved), binding["delivered_input_digest"])
                    self.assertEqual(digest(candidate["payload"]), saved["view"]["parent_input_digest"])
                    texts = [row["text"] for row in saved["view"]["spans"]]
                    self.assertIn(CONSTRAINT, texts)
                    if name == "shared":
                        self.assertIn("G1 measurements stay separate.", texts)
                        self.assertIn("G2 missing data stays unknown.", texts)
                reports = backend.inputs[-1]["reports"]
                for work in backend.inputs[:-1]:
                    claim = reports[work["job_id"]]["claims"][0]["text"]
                    self.assertNotEqual(work["purpose"], claim)
                    measurement = json.loads(claim)
                    expected = ({"p95_ms": 19} if "latency" in work["purpose"] else
                                {"peak_mib": 96, "missing": 1})
                    self.assertEqual(expected, measurement)

    def test_leaf_criterion_assignment_and_correction_preserve_current_intent(self):
        bundle, first, owner, file, first_rows = self.compile(graph(two=True))
        jobs = {row["requirement_id"]: row["job_id"] for row in first["diagnostics"]["frontier"]["leaf_jobs"]}
        criteria = {row["job_id"]: row["criterion_ids"] for row in first["supplied_plan"]["jobs"]}
        self.assertEqual(["REQ-LATENCY"], first["diagnostics"]["frontier"]["criteria"][1]["leaf_requirement_ids"])
        self.assertIn("A2", criteria[jobs["REQ-LATENCY"]])
        self.assertNotIn("A2", criteria[jobs["REQ-RSS"]])
        old_backend, _ = self.execute(bundle, first, owner, file)
        bundle, second, same_owner, same_file, _ = self.compile(graph(two=True, corrected=True), corrected=True)
        self.assertEqual((owner, file), (same_owner, same_file))
        admit(second, owner, file)
        stopped = ComputingBackend()
        with self.assertRaisesRegex(SwarmError, "STALE_BINDING"):
            execute_task_input(bundle, first, owner, file, stopped,
                               worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        self.assertEqual([], stopped.inputs)
        old_job = next(row for row in first["supplied_plan"]["jobs"]
                       if row["job_id"] == jobs["REQ-RSS"])
        old_span = span(first_rows["REQ-RSS"], old_job["purpose"])
        stale = copy.deepcopy(second)
        next(row for row in stale["supplied_plan"]["jobs"]
             if row["job_id"] == jobs["REQ-RSS"])["selected_spans"].append(old_span)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_CANDIDATE_CHANGED"):
            verify_task_input(bundle, stale, owner, clock=lambda: STAMP)
        backend, result = self.execute(bundle, second, owner, file)
        old = {row["job_id"]: row for row in old_backend.inputs[:-1]}
        new = {row["job_id"]: row for row in backend.inputs[:-1]}
        self.assertEqual(old["r0-" + jobs["REQ-LATENCY"]]["purpose"], new["r0-" + jobs["REQ-LATENCY"]]["purpose"])
        self.assertNotEqual(old["r0-" + jobs["REQ-RSS"]]["purpose"], new["r0-" + jobs["REQ-RSS"]]["purpose"])
        for value in backend.inputs:
            self.assertEqual(1, len(value["view"]["objective"]["intent"]["replacements"]))
            self.assertIn(first["payload"]["request"], [row["text"] for row in value["view"]["spans"]])
        self.assertTrue(result["receipt"]["review_passed"])

    def test_three_leaves_respect_explicit_actor_count_and_original_budget(self):
        spec = graph(two=True)
        spec["REQ-ROOT"]["children"].append("REQ-THIRD")
        spec["REQ-THIRD"] = {"data": {"operation": "latency", "values": list(range(1, 21))}}
        bundle, candidate, owner, file, _ = self.compile(spec)
        self.assertEqual(3, len(candidate["supplied_plan"]["jobs"]))
        self.assertEqual(0, candidate["diagnostics"]["frontier"]["budget"]["attempts_after_initial_if_no_retry"])
        self.assertIsNone(candidate["diagnostics"]["frontier"]["budget"]["runtime_remaining_attempts"])
        admit(candidate, owner, file)
        stopped = ComputingBackend()
        before = owner.read_bytes()
        with self.assertRaisesRegex(SwarmError, "LOOP_ACTORS_INVALID"):
            execute_task_input(bundle, candidate, owner, file, stopped,
                worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        self.assertEqual([], stopped.inputs)
        self.assertEqual(before, owner.read_bytes())
        document = json.loads(before)
        document["actors"]["worker-c"] = {**document["actors"]["worker-b"],
                                             "invocation_ref": "invocation-worker-c"}
        owner.write_text(json.dumps(document), encoding="utf-8")
        backend, result = self.execute(bundle, candidate, owner, file, actors=3)
        self.assertEqual(4, len(backend.inputs))
        self.assertTrue(result["receipt"]["review_passed"])
        with sqlite3.connect(owner.parent / result["receipt"]["run_id"] / "execution.sqlite") as db:
            self.assertEqual(4, db.execute("SELECT count(*) FROM attempts").fetchone()[0])

    def test_echo_and_wrong_leaf_fail_the_independently_computed_fixture(self):
        for mode in ("echo", "wrong_leaf"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                bundle, seed, owner, file, _ = fixture(Path(temporary), graph(two=True))
                candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                _, result = self.execute(bundle, candidate, owner, file, mode=mode)
                self.assertFalse(result["receipt"]["review_passed"])
                self.assertEqual("unresolved", result["candidate"]["status"])
                with sqlite3.connect(owner.parent / result["receipt"]["run_id"] / "execution.sqlite") as db:
                    self.assertEqual(0, db.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0])

    def test_correct_computations_cannot_bypass_assigned_leaf_evidence(self):
        bundle, candidate, owner, file, _ = self.compile(graph(two=True))
        admit(candidate, owner, file)

        class WrongAssignment(ComputingBackend):
            def review(self, delivered, *args, **kwargs):
                value = super().review(delivered, *args, **kwargs)
                assigned = set(delivered["required_evidence_jobs"]["A2"])
                unrelated = next(job for job in delivered["reports"] if job not in assigned)
                criterion = next(row for row in value["result"]["validations"] if row["criterion_id"] == "A2")
                assert criterion["status"] == "passed"  # independent computations were correct
                criterion["evidence"] = [{"job_id": unrelated, "claim_index": 0}]
                return value

        backend = WrongAssignment()
        with self.assertRaisesRegex(SwarmError, "LOOP_CRITIC_ASSIGNMENT"):
            execute_task_input(bundle, candidate, owner, file, backend,
                worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        self.assertEqual(3, len(backend.inputs))
        self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))

    def test_real_owner_source_expiry_actor_and_tampering_refuse(self):
        bundle, candidate, owner, file, _ = self.compile(graph(two=True))
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_MISMATCH"):
            verify_task_input(bundle, candidate, owner, clock=lambda: STAMP)
        admit(candidate, owner, file)
        changed = copy.deepcopy(candidate)
        changed["supplied_plan"]["jobs"][0]["criterion_ids"] = ["R"]
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_CANDIDATE_CHANGED"):
            verify_task_input(bundle, changed, owner, clock=lambda: STAMP)
        with self.assertRaisesRegex(SwarmError, "OBJECTIVE_DEADLINE_INVALID"):
            verify_task_input(bundle, candidate, owner, clock=lambda: STAMP + 101)
        backend = ComputingBackend()
        with self.assertRaisesRegex(SwarmError, "LOOP_ACTORS_INVALID"):
            execute_task_input(bundle, candidate, owner, file, backend,
                               worker_actors=["worker-a"], clock=lambda: STAMP)
        self.assertEqual([], backend.inputs)
        (self.root / "work/REQ-LATENCY.md").write_bytes(b"Changed current source")
        with self.assertRaises(SwarmError):
            execute_task_input(bundle, candidate, owner, file, backend,
                               worker_actors=["worker-a", "worker-b"], clock=lambda: STAMP)
        self.assertEqual([], backend.inputs)
        self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))

    def test_public_catalog_and_existing_source_and_field_caps(self):
        bundle, candidate, owner, file, _ = self.compile(graph(), public=True, corrected=True)
        self.assertEqual(10, len(candidate["payload"]["sources"]))
        self.assertTrue(self.execute(bundle, candidate, owner, file)[1]["receipt"]["review_passed"])
        with tempfile.TemporaryDirectory() as temporary:
            bundle, seed, owner, _, _ = fixture(Path(temporary), graph(shared=True), corrected=True)
            self.assertEqual(11, len(seed["sources"]))
            with self.assertRaisesRegex(SwarmError, "TASK_SOURCES_INVALID"):
                compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        with tempfile.TemporaryDirectory() as temporary:
            spec = graph()
            spec["REQ-ROOT"]["acceptance"] = [f"Check {i:02d} has measured evidence." for i in range(20)]
            bundle, seed, owner, _, _ = fixture(Path(temporary), spec)
            compiled = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
            self.assertGreater(len(compiled["supplied_plan"]["jobs"][0]["criterion_ids"]), 20)

    def test_legacy_declaration_remains_opt_in(self):
        bundle, seed, owner, _ = setup(self.root, jobs=1)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertNotIn("frontier", candidate["diagnostics"])
        self.assertEqual("requirement-0", candidate["supplied_plan"]["jobs"][0]["job_id"])

    def test_source_span_origins_are_unioned_without_merging_equal_text(self):
        root = source("root", 1, "Root need.\nRoot condition.\nGlobal condition.")
        left = source("left", 1, "Left need.\nShared condition.\nLeft condition.")
        right = source("right", 1, "Right need.\nShared condition.\nRight condition.")
        shared = span(left, "Shared condition.")
        nodes = {
            "R": {"source": root, "need": span(root, "Root need."),
                  "acceptance": [span(root, "Root condition.")], "constraints": [],
                  "kind": "requirement", "parent": "P",
                  "frontier": {"kind": "all_of", "children": ["B", "A"], "requires": []}},
            "A": {"source": left, "need": span(left, "Left need."),
                  "acceptance": [shared], "constraints": [span(left, "Left condition.")],
                  "kind": "requirement", "parent": "P",
                  "frontier": {"kind": "atomic", "children": [], "requires": []}},
            "B": {"source": right, "need": span(right, "Right need."),
                  "acceptance": [shared, span(right, "Shared condition.")],
                  "constraints": [span(right, "Right condition.")],
                  "kind": "requirement", "parent": "P",
                  "frontier": {"kind": "atomic", "children": [], "requires": []}},
            "P": {"kind": "project", "parent": None,
                  "constraints": [span(root, "Global condition.")]},
        }
        seed = {"sources": [root, left, right]}
        work = frontier_work(seed, nodes, "R", [span(root, "Global condition.")], [])
        self.assertEqual(["A", "B"], work["leaves"])
        self.assertEqual({"A1": ["A", "B"], "A2": ["A", "B"], "A3": ["B"]}, work["assignments"])
        self.assertEqual(["A", "B"], work["diagnostic"]["criteria"][1]["origin_requirement_ids"])
        self.assertEqual(3, len(work["acceptance"]))
        self.assertEqual(3, len(work["constraints"]))
        reordered = copy.deepcopy(nodes)
        reordered["R"]["frontier"]["children"].reverse()
        self.assertEqual(work, frontier_work(seed, reordered, "R", [span(root, "Global condition.")], []))

    def test_current_declaration_and_acceptance_cannot_be_silently_repaired(self):
        cases = [("jobs", "TASK_CONTEXT_DECLARATION_INVALID"),
                 ("missing_root", "TASK_FRONTIER_ROOT_INVALID"),
                 ("acceptance_order", "TASK_CONTEXT_ACCEPTANCE_MISMATCH"),
                 ("missing_frontier", "TASK_CONTEXT_FIELDS_REQUIRED"),
                 ("unused", "TASK_CONTEXT_UNUSED_HIERARCHY")]
        for action, code in cases:
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                spec = graph(two=True)
                if action == "unused":
                    spec["REQ-UNUSED"] = {"data": {"operation": "rss", "values": [1]}}
                bundle, seed, owner, file, rows = fixture(root, spec)
                if action == "jobs":
                    change_declaration(seed, root, lambda value: value.update(jobs=[]))
                elif action == "missing_root":
                    change_declaration(seed, root, lambda value: value.update(root_requirement_id="MISSING"))
                elif action == "acceptance_order":
                    seed["acceptance"].reverse()
                elif action == "missing_frontier":
                    row = rows["REQ-RSS"]
                    text = row["text"]
                    start, end = text.index("  frontier:\n"), text.index("---\n\n")
                    row["text"] = text[:start] + text[end:]
                    (root / "work/REQ-RSS.md").write_bytes(row["text"].encode("utf-8"))
                reseal_seed(seed, owner, file)
                before = owner.read_bytes(), file.read_bytes()
                with self.assertRaisesRegex(SwarmError, code):
                    compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                self.assertEqual(before, (owner.read_bytes(), file.read_bytes()))

    def test_selected_span_and_attempt_caps_still_refuse_instead_of_truncating(self):
        for action, code in (("spans", "LOOP_CONTEXT_REQUIRED"),
                             ("budget", "INVALID_LIMIT")):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as temporary:
                root, spec = Path(temporary), graph()
                if action == "spans":
                    spec["REQ-ROOT"].update(
                        acceptance=[f"Check {i:02d} is measured." for i in range(20)],
                        constraints=[f"Constraint {i:02d} remains in scope." for i in range(8)])
                bundle, seed, owner, file, _ = fixture(root, spec)
                if action == "budget":
                    change_declaration(seed, root, lambda value: value["budget"].update(attempt_budget=3))
                    reseal_seed(seed, owner, file)
                before = owner.read_bytes()
                with self.assertRaisesRegex(SwarmError, code):
                    compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                self.assertEqual(before, owner.read_bytes())

    def test_graph_rejects_long_shared_paths_cycles_and_undeclared_dependencies(self):
        def nodes(edges):
            return {key: {"kind": "requirement", "parent": None,
                          "frontier": {"kind": "all_of" if children else "atomic",
                                       "children": children, "requires": []}} for key, children in edges.items()}
        cases = [(nodes({"R": ["C", "G1"], "G1": ["G2"], "G2": ["C"], "C": []}), "DEPTH_LIMIT"),
                 (nodes({"R": ["G"], "G": ["R"]}), "CYCLE"),
                 (nodes({"R": ["MISSING"]}), "CHILD_INVALID"),
                 (nodes({"R": ["A", "A"], "A": []}), "CHILD_DUPLICATE"),
                 (nodes({"R": ["A", "B", "C", "D"], "A": [], "B": [], "C": [], "D": []}), "WORK_LIMIT")]
        dependency = nodes({"R": []})
        dependency["R"]["frontier"]["requires"] = ["UPSTREAM"]
        cases.append((dependency, "DEPENDENCY_UNSUPPORTED"))
        for identifier in ("R", "G", "C"):
            value = nodes({"R": ["G"], "G": ["C"], "C": []})
            value[identifier]["frontier"]["requires"] = ["UPSTREAM"]
            cases.append((value, "DEPENDENCY_UNSUPPORTED"))
        for frontier in ({"children": [], "requires": []},
                         {"kind": "all_of", "children": [], "requires": []},
                         {"kind": "atomic", "children": ["C"], "requires": []}):
            value = nodes({"R": ["C"], "C": []})
            value["R"]["frontier"] = frontier
            cases.append((value, "INVALID"))
        for value, code in cases:
            with self.subTest(code=code), self.assertRaisesRegex(SwarmError, "TASK_FRONTIER_" + code):
                resolve_frontier(value, "R")


if __name__ == "__main__":
    unittest.main()
