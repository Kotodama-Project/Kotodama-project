"""Owner-bound local material acquisition, independently computed by real children.

This is an API fixture, not a product CLI acquisition backend or a model eval.
Owner freshness reads, worker acquisitions and critic oracle reads are separate.
"""
from __future__ import annotations

import copy
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from runtime.task_swarm.protocol import SwarmError, canonical, digest

MAX_BODY = 1024
MAX_FRAME = 256 * 1024
MAX_OUTPUT = 64 * 1024
PARTIAL_REQUEST = ("Report grounded current states for DocA and DocB. An initial partial report is allowed "
                   "when unacquired material stays explicitly unknown. Each numerical leaf has its "
                   "separate completion criterion.")
ROOT_ACCEPTANCE = "Every current state is grounded and unacquired material is explicitly unknown."
UNKNOWN = "An unacquired material has no measured value; absence is never zero."
REGISTRY = "READ_ONLY_MATERIALS="


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def leaf(identifier):
    return "r0-leaf-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:32]


def origin(job):
    return "r0-" + job[len("r1-repair-"):] if job.startswith("r1-repair-") else job


def registry(delivered):
    matches = [row["text"] for row in delivered["view"]["spans"] if row["text"].startswith(REGISTRY)]
    if len(matches) != 1:
        raise SwarmError("MATERIAL_DECLARATION_REQUIRED", "exact owner-bound material scope required")
    return json.loads(matches[0][len(REGISTRY):])


def needs(delivered):
    result = {}
    for row in delivered["view"]["spans"]:
        value = row["text"]
        if value.startswith("[REQ-") and " DATA=" in value:
            identifier, encoded = value[1:].split("] DATA=", 1)
            result[leaf(identifier)] = (row, json.loads(encoded))
    return result


def read_material(material, declared, records, *, kind):
    # This fixture's authority is the explicit Task declaration, not source_checks alone.
    if material not in declared["materials"]:
        raise SwarmError("MATERIAL_OUT_OF_SCOPE", "material was not prebound by this owner")
    cap = declared["max_body_bytes"]
    if type(cap) is not int or not 1 <= cap <= MAX_BODY:
        raise SwarmError("MATERIAL_BYTES_LIMIT", "invalid owner-declared material cap")
    with Path(material["path"]).open("rb") as handle:
        raw = handle.read(cap + 1)
    record = {"doc_id": material["doc_id"], "sha256": sha(raw), "bytes": len(raw), "kind": kind}
    records.append(record)
    if len(raw) > cap or sum(record["bytes"] for record in records) > declared["max_total_bytes"]:
        raise SwarmError("MATERIAL_BYTES_LIMIT", "bounded material read exceeded its cap")
    if len(raw) != material["bytes"] or sha(raw) != material["sha256"]:
        raise SwarmError("MATERIAL_SOURCE_CHANGED", "material bytes no longer match the declaration")
    return raw


def worker_value(raw, operation):
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    if operation == "sum":
        return sum(int(row["qty"]) for row in rows)
    if operation == "net" and len(rows) == 1:
        return int(rows[0]["gross"]) - int(rows[0]["discount"])
    raise SwarmError("MATERIAL_OPERATION_INVALID", "unknown finite fixture operation")


def oracle_value(raw, operation):
    # Separate parser and calculation from worker_value; answers are not supplied in stdin.
    lines = raw.decode("ascii").splitlines()
    if operation == "sum" and lines[0] == "qty":
        total = 0
        for value in lines[1:]:
            total += int(value)
        return total
    if operation == "net" and len(lines) == 2 and lines[0] == "gross,discount":
        gross, discount = [int(value) for value in lines[1].split(",")]
        return sum((gross, -discount))
    raise SwarmError("MATERIAL_ORACLE_INVALID", "oracle cannot interpret this declared material")


def worker(delivered, mode, records):
    declared = registry(delivered)
    # purpose remains the original Source-bound need before the verified gap suffix.
    need = delivered["purpose"].split("\nRepair verified gaps:", 1)[0]
    record = next(row for row in delivered["view"]["spans"] if row["text"] == need)
    data = json.loads(need.split(" DATA=", 1)[1])
    material = next(item for item in declared["materials"] if item["doc_id"] == data["doc_id"])
    value, acquired = None, []
    if data["doc_id"] != "DocB" or delivered["round"] != 0:
        selected = material
        if mode == "wrong_doc" and data["doc_id"] == "DocB":
            selected = next(item for item in declared["materials"] if item["doc_id"] == "DocA")
        if mode == "out_of_scope" and data["doc_id"] == "DocB":
            selected = {**material, "doc_id": "DocC", "path": str(Path(material["path"]).with_name("c.csv"))}
        raw = read_material(selected, declared, records, kind="worker_acquisition")
        value = worker_value(raw, "sum" if selected["doc_id"] == "DocA" else data["operation"])
        acquired = [{key: item[key] for key in ("doc_id", "sha256", "bytes")} for item in records]
        if mode == "fixed" and data["doc_id"] == "DocB":
            value = 13  # Adversarial control; this must fail the independently calculated second dataset.
    claim = canonical({"doc_id": data["doc_id"], "value": value, "acquisitions": acquired})
    if mode == "echo" and data["doc_id"] == "DocB" and delivered["round"] == 1:
        claim = need
    evidence = {key: record[key] for key in ("source_key", "source_revision", "start", "end")}
    return {"job_id": delivered["job_id"], "summary": "Grounded current acquisition state.", "conflicts": [],
            "claims": [{"text": claim, "status": "unknown" if value is None else "inference",
                        "evidence": [{**evidence, "quote": need}]}]}


def critic(delivered, mode, records):
    declared, supplied = registry(delivered), needs(delivered)
    expected, observations, valid = {}, {}, {}
    for job, (_, data) in supplied.items():
        material = next(item for item in declared["materials"] if item["doc_id"] == data["doc_id"])
        raw = read_material(material, declared, records, kind="critic_oracle")
        expected[job] = (data["doc_id"], oracle_value(raw, data["operation"]), material)
    for job, report in delivered["reports"].items():
        doc_id, value, material = expected[origin(job)]
        try:
            item = json.loads(report["claims"][0]["text"])
            claimed = item["acquisitions"]
            measured = [{"doc_id": doc_id, "sha256": material["sha256"], "bytes": material["bytes"]}]
            truthful = item["doc_id"] == doc_id and (
                (item["value"] is None and claimed == [] and report["claims"][0]["status"] == "unknown") or
                (item["value"] == value and type(item["value"]) is int and claimed == measured
                 and report["claims"][0]["status"] == "inference"))
        except (ValueError, KeyError, TypeError):
            item, truthful = {}, False
        observations[job], valid[job] = item, truthful
    latest = {first: ("r1-repair-" + first[3:] if "r1-repair-" + first[3:] in observations else first)
              for first in expected}
    complete = {first: valid[latest[first]] and observations[latest[first]].get("value") is not None
                for first in expected}
    truthful = all(valid.values()) and set(map(origin, observations)) == set(expected)
    answered = truthful and (declared["allow_partial"] or all(complete.values()))
    validations = []
    for key, criterion in delivered["criteria"].items():
        target = next((job for job, (_, data) in supplied.items() if criterion == "Complete " + data["doc_id"] + " numerical metric."), None)
        passed = complete[target] if target else (
            answered if key == "R" or criterion == "Complete both numerical metrics." else truthful)
        refs = [{"job_id": job, "claim_index": 0} for job in delivered["required_evidence_jobs"][key]]
        if mode == "wrong_refs" and key == "A3" and delivered["round"] == 1:
            refs = [{"job_id": leaf("REQ-A"), "claim_index": 0}]
        gap_record = supplied[target or leaf("REQ-B")][0]
        validations.append({"criterion_id": key, "status": "passed" if passed else "failed", "evidence": refs,
            "gap_reason": None if passed else "DocB acquisition or its independently checked metric is missing or invalid.",
            "source_spans": [] if passed else [{k: gap_record[k] for k in ("source_key", "source_revision", "start", "end")}]})
    return {"parent_input_digest": delivered["view"]["parent_input_digest"], "plan_digest": delivered["view"]["plan_digest"],
            "round": delivered["round"], "report_digests": delivered["report_digests"], "validations": validations}


def child(role, actor, mode):
    raw = sys.stdin.buffer.read(MAX_FRAME + 1)
    records = []
    if len(raw) > MAX_FRAME:
        raise SwarmError("MATERIAL_INPUT_LIMIT", "child input exceeded its bound")
    delivered = json.loads(raw)
    value = {"stdin_sha256": sha(raw), "pid": os.getpid(), "io": records}
    try:
        result = worker(delivered, mode, records) if role == "work" else critic(delivered, mode, records)
        value["response"] = {"result": result, "receipt": {"actor_ref": actor, "synthetic": True,
            "invocation_ref": "synthetic-" + delivered["job_id"], "input_digest": digest(delivered)}}
        code = 0
    except SwarmError as exc:
        value["error"] = exc.code
        code = 2
    encoded = (canonical(value) + "\n").encode("utf-8")
    if len(encoded) > MAX_OUTPUT:
        raise SwarmError("MATERIAL_OUTPUT_LIMIT", "child output exceeded its bound")
    sys.stdout.buffer.write(encoded)
    return code


def make_case(root, *, gross=17, discount=4, budget=6, corrected=False, allow_partial=True,
              ttl_seconds=None):
    from tests.test_knowledge_task_frontier import fixture
    from tests.test_knowledge_task_input import (STAMP, admit, change_declaration, reseal_seed,
                                                small_catalog, source, span)
    from kotodama_kb.task_input import compile_task_input
    if ttl_seconds is not None:
        small_catalog(root)
        expiry = dt.datetime.fromtimestamp(STAMP + ttl_seconds, dt.timezone.utc).isoformat().replace("+00:00", "Z")
        for path in (root / "knowledge/synthetic").glob("*.md"):
            path.write_bytes(path.read_bytes().replace(b"2026-12-07T00:00:00Z", expiry.encode("ascii")))
    materials = root / "materials"
    materials.mkdir(exist_ok=True)
    bodies = {"DocA": b"qty\n2\n3\n", "DocB": f"gross,discount\n{gross},{discount}\n".encode("ascii")}
    descriptors = []
    for name, raw in bodies.items():
        path = materials / (name + ".csv")
        path.write_bytes(raw)
        descriptors.append({"doc_id": name, "path": str(path), "sha256": sha(raw), "bytes": len(raw)})
    declared = {"allow_partial": allow_partial, "materials": descriptors,
                "max_body_bytes": MAX_BODY, "max_total_bytes": 2 * MAX_BODY}
    spec = {"REQ-ROOT": {"children": ["REQ-A", "REQ-B"], "acceptance": [ROOT_ACCEPTANCE if allow_partial else "Complete both numerical metrics."],
                         "constraints": [REGISTRY + canonical(declared), UNKNOWN]},
            "REQ-A": {"data": {"doc_id": "DocA", "operation": "sum"}, "acceptance": ["Complete DocA numerical metric."]},
            "REQ-B": {"data": {"doc_id": "DocB", "operation": "net"}, "acceptance": ["Complete DocB numerical metric."]}}
    bundle, seed, owner, file, rows = fixture(root, spec, corrected=corrected)
    requests = [row for row in seed["sources"] if row["key"] == source("request", 1, "")["key"]]
    for row in requests:
        row["text"] = PARTIAL_REQUEST if allow_partial else "Complete both numerical metrics before accepting an answer."
        if row["revision"] > 1:
            row["text"] += " Use the corrected current DocB material."
    seed["request"] = requests[-1]["text"]
    if corrected:
        rows["REQ-ROOT"]["revision"] = 2  # Its current manifest changed; no revision-1 body is relabelled current.
    def declaration(value):
        value["budget"]["attempt_budget"] = budget
        if ttl_seconds is not None:
            value["budget"]["deadline"] = STAMP + ttl_seconds  # Explicit fixture owner budget, no runtime shortening.
        value["intent"] = {"original": span(requests[0], requests[0]["text"]),
                           "replacements": [span(row, row["text"]) for row in requests[1:]]}
        start = rows["REQ-ROOT"]["text"].rindex(UNKNOWN)
        value["unknowns"] = [{"source_key": rows["REQ-ROOT"]["key"], "source_revision": rows["REQ-ROOT"]["revision"],
                              "start": start, "end": start + len(UNKNOWN)}]
        for entry in value["hierarchy"]:
            if entry["path"] == "work/REQ-ROOT.md":
                entry["source_revision"] = rows["REQ-ROOT"]["revision"]
    change_declaration(seed, root, declaration)
    reseal_seed(seed, owner, file)
    material_checks = [{"path": item["path"], "sha256": item["sha256"]} for item in descriptors]
    def bind_materials():
        document = json.loads(owner.read_bytes())
        document["source_checks"].extend(copy.deepcopy(material_checks))
        owner.write_bytes((canonical(document) + "\n").encode("utf-8"))
    bind_materials()  # Explicit synthetic owner binding before compile, not runtime self-approval.
    candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
    admit(candidate, owner, file)  # Existing owner's explicit candidate adoption in the fixture.
    bind_materials()  # Retain the preapproved material checks alongside the producer's required checks.
    return MaterialCase(bundle, candidate, owner, file, descriptors, STAMP)


class MaterialCase:
    def __init__(self, bundle, candidate, owner, file, materials, stamp):
        self.bundle, self.candidate, self.owner, self.file, self.materials = bundle, candidate, owner, file, materials
        self.stamp, self.now = stamp, stamp

    @property
    def directory(self):
        payload = self.candidate["payload"]
        return self.owner.parent / ("task-run-" + digest([payload["task_id"], payload["revision"]])[:32])

    def execute(self, backend, **options):
        from kotodama_kb.task_input import execute_task_input
        return execute_task_input(self.bundle, self.candidate, self.owner, self.file, backend,
            worker_actors=["worker-a", "worker-b"], clock=lambda: self.now, **options)


def retained(directory):
    name = leaf("REQ-A")
    with sqlite3.connect(directory / "execution.sqlite") as conn:
        attempt = conn.execute("SELECT * FROM attempts WHERE job_id=? ORDER BY attempt", (name,)).fetchall()
    return {"input": (directory / (name + "-input.json")).read_bytes(),
            "result": (directory / (name + "-result.json")).read_bytes(), "attempts": attempt}


class MaterialBackend:
    synthetic = True

    def __init__(self, *, mode="computed", after=None):
        self.mode, self.after = mode, after
        self.calls, self.source_reads, self.retained = [], [], []
        self.lock = threading.Lock()
        self.barrier = threading.Barrier(2)

    def _call(self, role, delivered, directory, actor):
        directory = directory.parent  # The backend receives its attempt directory.
        if role == "work" and delivered["round"] == 0:
            self.barrier.wait(timeout=10)  # Both original claims exist before either worker returns.
        if role == "critic":
            self.retained.append(retained(directory))
        raw = (canonical(delivered) + "\n").encode("utf-8")
        saved = (directory / (delivered["job_id"] + "-input.json")).read_bytes()
        assert raw == saved, "child must consume the exact coordinator-saved input"
        command = [sys.executable, "-B", str(Path(__file__).resolve()), "--material-child", role, actor, self.mode]
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            try:
                output, error = process.communicate(raw, timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
        assert len(output) <= MAX_OUTPUT and error == b"", "child emitted an invalid frame"
        value = json.loads(output)
        assert value["pid"] == process.pid and process.pid != os.getpid()
        assert value["stdin_sha256"] == sha(saved)
        with self.lock:
            self.calls.append({"job_id": delivered["job_id"], "role": role, "round": delivered["round"],
                "stdin_sha256": value["stdin_sha256"], "pid": value["pid"], "io": value["io"]})
        if process.returncode != 0:
            raise SwarmError(value["error"], "material fixture child refused")
        if self.after is not None:
            self.after(delivered, directory)
        return value["response"]

    def produce(self, delivered, directory, *, actor_ref, **kwargs):
        return self._call("work", delivered, directory, actor_ref)

    def review(self, delivered, directory, *, actor_ref, **kwargs):
        return self._call("critic", delivered, directory, actor_ref)

    def execute(self, case, **options):
        native = Path.read_bytes
        paths = {str(Path(item["path"])) for item in case.materials}
        def observed(path):
            raw = native(path)  # One original read; no cached source or substituted return value.
            if str(path) in paths:
                caller = sys._getframe(1).f_code.co_name
                assert caller == "_source_checks", "unexpected parent material read must be separately scoped"
                with self.lock:
                    self.source_reads.append({"path": str(path), "bytes": len(raw), "kind": "owner_freshness"})
            return raw
        with mock.patch.object(Path, "read_bytes", observed):
            return case.execute(self, **options)


class MaterialAcquisitionTests(unittest.TestCase):
    def case(self, **options):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return make_case(Path(temporary.name), **options)

    def test_two_real_material_inputs_change_the_independent_outcome_and_retain_a(self):
        for gross, discount, value in ((17, 4, 13), (31, 8, 23)):
            with self.subTest(expected=value):
                case = self.case(gross=gross, discount=discount)
                before = case.owner.read_bytes(), case.file.read_bytes()
                backend = MaterialBackend()
                result = backend.execute(case)
                self.assertTrue(result["receipt"]["review_passed"])
                self.assertEqual(5, result["receipt"]["budget"]["attempts_used"])
                self.assertEqual(1, result["receipt"]["budget"]["remaining_attempts"])
                self.assertEqual(before, (case.owner.read_bytes(), case.file.read_bytes()))
                self.assertEqual(backend.retained[0], backend.retained[1])
                self.assertEqual(5, len(backend.calls))
                payload = case.candidate["payload"]
                for call in backend.calls:
                    delivered = json.loads((case.directory / (call["job_id"] + "-input.json")).read_bytes())
                    self.assertEqual(payload["objective"], delivered["view"]["objective"])
                    self.assertEqual(digest(payload), delivered["view"]["parent_input_digest"])
                    self.assertEqual(payload["request"], delivered["view"]["request"])
                    if call["role"] == "work":
                        texts = [record["text"] for record in delivered["view"]["spans"]]
                        self.assertFalse(any("qty\n2\n3\n" in text or "gross,discount\n" in text for text in texts))
                self.assertNotIn(os.getpid(), {item["pid"] for item in backend.calls})
                workers = [item for item in backend.calls if item["role"] == "work"]
                acquired = {item["job_id"]: [record["doc_id"] for record in item["io"]] for item in workers}
                self.assertEqual({leaf("REQ-A"): ["DocA"], leaf("REQ-B"): [],
                                  "r1-repair-" + leaf("REQ-B")[3:]: ["DocB"]}, acquired)
                self.assertEqual({item["path"] for item in case.materials}, {item["path"] for item in backend.source_reads})
                for oracle in [call for call in backend.calls if call["role"] == "critic"]:
                    self.assertEqual(["DocA", "DocB"], sorted(item["doc_id"] for item in oracle["io"]))
                first = json.loads((case.directory / "r0-critic-result.json").read_bytes())["result"]
                self.assertEqual(["A3"], [item["criterion_id"] for item in first["validations"] if item["status"] == "failed"])
                final = json.loads((case.directory / "r1-critic-input.json").read_bytes())
                current = {item["job_id"]: json.loads(item["claim"]["text"]) for item in result["candidate"]["claims"]}
                self.assertEqual(5, current[leaf("REQ-A")]["value"])
                self.assertIsNone(current[leaf("REQ-B")]["value"])
                self.assertEqual(value, current["r1-repair-" + leaf("REQ-B")[3:]]["value"])
                impact = json.loads((case.directory / "repair-impact.json").read_bytes())
                self.assertEqual([leaf("REQ-A")], [item["job_id"] for item in impact["retained"]])
                self.assertEqual(digest(json.loads(backend.retained[0]["input"])), impact["retained"][0]["input_digest"])
                self.assertEqual(sha(backend.retained[0]["result"]), impact["retained"][0]["result_sha256"])
                for name, check in result["receipt"]["artifact_sha256"].items():
                    self.assertEqual(check, sha((case.directory / name).read_bytes()))
                for item in result["candidate"]["validations"]:
                    self.assertEqual(set(final["required_evidence_jobs"][item["criterion_id"]]),
                                     {ref["job_id"] for ref in item["evidence"]})
                calls = len(backend.calls)
                files = {p.name: p.read_bytes() for p in case.directory.glob("*.json")}
                replay = backend.execute(case, expected_receipt_sha256=result["receipt_sha256"])
                self.assertTrue(replay["duplicate"])
                self.assertEqual(calls, len(backend.calls))
                self.assertEqual(files, {p.name: p.read_bytes() for p in case.directory.glob("*.json")})

    def test_echo_fixed_answer_and_other_document_are_not_accepted(self):
        for mode in ("echo", "fixed", "wrong_doc"):
            with self.subTest(mode=mode):
                case = self.case(gross=31, discount=8)
                result = MaterialBackend(mode=mode).execute(case)
                self.assertFalse(result["receipt"]["review_passed"])
                self.assertEqual("unresolved", result["candidate"]["status"])
                self.assertIsNone(result["learning_candidate"])
                self.assertTrue(any(item["criterion_id"] == "A3" and item["status"] == "failed"
                                    for item in result["candidate"]["validations"]))

    def test_current_source_cancel_actor_and_deadline_refuse_after_real_repair_read(self):
        from runtime.task_swarm.closed_loop_cancellation import cancel_closed_loop
        from runtime.task_swarm.owner_file import OwnerFileError
        for change in ("source", "cancel", "actor", "deadline", "concept_ttl"):
            with self.subTest(change=change):
                case = self.case(ttl_seconds=80 if change == "concept_ttl" else None)
                def mutate(delivered, directory):
                    if delivered["role"] != "work" or delivered["round"] != 1:
                        return
                    if change == "source":
                        Path(case.materials[1]["path"]).write_bytes(b"gross,discount\n19,4\n")
                    elif change == "cancel":
                        cancel_closed_loop(case.owner, case.file, clock=lambda: case.now)
                    elif change == "actor":
                        document = json.loads(case.owner.read_bytes())
                        document["actors"]["worker-a"]["actor_status"] = "closed"
                        case.owner.write_bytes((canonical(document) + "\n").encode())
                    else:
                        case.now = case.candidate["payload"]["objective"]["budget"]["deadline"] + 1
                backend = MaterialBackend(after=mutate)
                with self.assertRaises((SwarmError, OwnerFileError)):
                    backend.execute(case)
                self.assertEqual(["DocA", "DocB"], [record["doc_id"] for call in backend.calls if call["role"] == "work" for record in call["io"]])
                self.assertEqual([0], [call["round"] for call in backend.calls if call["role"] == "critic"])
                self.assertFalse((case.directory / "receipt.json").exists())
                self.assertEqual(backend.retained[0], retained(case.directory))
                if change == "cancel":
                    for resume in (False, True):
                        fresh = MaterialBackend()
                        with self.assertRaisesRegex(SwarmError, "RUN_CANCELLED"):
                            fresh.execute(case, resume_finalization=resume)
                        self.assertEqual([], fresh.calls)
                if change == "concept_ttl":
                    from kotodama_kb.task_input import verify_task_input
                    with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_EXPIRED"):
                        verify_task_input(case.bundle, case.candidate, case.owner,
                                          clock=lambda: case.now, allow_expired=True)

    def test_source_change_before_execution_and_unbound_material_addition_refuse(self):
        from runtime.task_swarm.owner_file import OwnerFileError
        case = self.case()
        Path(case.materials[0]["path"]).write_bytes(b"qty\n7\n3\n")
        backend = MaterialBackend()
        with self.assertRaises((SwarmError, OwnerFileError)):
            backend.execute(case)
        self.assertEqual([], backend.calls)
        case = self.case()
        before = case.owner.read_bytes(), copy.deepcopy(case.candidate["payload"]["sources"])
        backend = MaterialBackend(mode="out_of_scope")
        with self.assertRaisesRegex(SwarmError, "MATERIAL_OUT_OF_SCOPE"):
            backend.execute(case)
        self.assertEqual(before, (case.owner.read_bytes(), case.candidate["payload"]["sources"]))
        self.assertFalse((case.directory / "receipt.json").exists())
        self.assertEqual([], next(call["io"] for call in backend.calls if call["round"] == 1))

    def test_full_completion_and_insufficient_budget_are_honest_unresolved_receipts(self):
        for partial in (True, False):
            with self.subTest(allow_partial=partial):
                case = self.case(budget=4, allow_partial=partial)
                backend = MaterialBackend()
                result = backend.execute(case)
                self.assertFalse(result["receipt"]["review_passed"])
                self.assertEqual("attempt_budget_exhausted", result["candidate"]["stop_reason"])
                self.assertEqual(3, result["receipt"]["budget"]["attempts_used"])
                self.assertEqual(1, result["receipt"]["budget"]["remaining_attempts"])
                self.assertEqual(3, len(backend.calls))
                self.assertIsNone(result["learning_candidate"])
                if not partial:
                    failed = {item["criterion_id"] for item in result["candidate"]["validations"] if item["status"] == "failed"}
                    self.assertEqual({"R", "A1", "A3"}, failed)
                    from runtime.task_swarm.closed_loop_contract import verified_gap
                    from runtime.task_swarm.repair_planning import derive_repair
                    review = json.loads((case.directory / "r0-critic-result.json").read_bytes())
                    gap = verified_gap(review["result"], critic_job_id="r0-critic", critic_result_digest=sha((case.directory / "r0-critic-result.json").read_bytes()))
                    plan, _ = derive_repair(case.candidate["payload"], case.candidate["supplied_plan"], gap)
                    self.assertEqual(2, len(plan["jobs"]))  # Cannot narrow a failed common condition to DocB.

    def test_wrong_assigned_evidence_and_bounded_material_reader_refuse(self):
        case = self.case()
        with self.assertRaisesRegex(SwarmError, "LOOP_CRITIC_ASSIGNMENT"):
            MaterialBackend(mode="wrong_refs").execute(case)
        self.assertFalse((case.directory / "receipt.json").exists())
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "oversized.csv"
            path.write_bytes(b"x" * (MAX_BODY + 1))
            material = {"doc_id": "DocA", "path": str(path), "bytes": MAX_BODY, "sha256": sha(path.read_bytes())}
            records = []
            with self.assertRaisesRegex(SwarmError, "MATERIAL_BYTES_LIMIT"):
                read_material(material, {"materials": [material], "max_body_bytes": MAX_BODY,
                                        "max_total_bytes": 2 * MAX_BODY}, records, kind="worker_acquisition")
            self.assertEqual(MAX_BODY + 1, records[0]["bytes"])

    def test_same_owner_correction_rejects_old_context_and_changes_child_inputs(self):
        from runtime.task_swarm.owner_file import OwnerFileError
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = make_case(root)
            original = MaterialBackend().execute(old)
            old_files = {p.name: p.read_bytes() for p in old.directory.glob("*.json")}
            new = make_case(root, gross=31, discount=8, corrected=True)
            self.assertEqual(old.owner, new.owner)
            self.assertEqual(old.candidate["payload"]["task_id"], new.candidate["payload"]["task_id"])
            stale = MaterialBackend()
            with self.assertRaises((SwarmError, OwnerFileError)):
                stale.execute(old, expected_receipt_sha256=original["receipt_sha256"])
            self.assertEqual([], stale.calls)
            self.assertEqual(old_files, {p.name: p.read_bytes() for p in old.directory.glob("*.json")})
            result = MaterialBackend().execute(new)
            self.assertTrue(result["receipt"]["review_passed"])
            self.assertEqual(10, len(new.candidate["payload"]["sources"]))
            for binding in result["receipt"]["dispatches"]:
                delivered = json.loads((new.directory / (binding + "-input.json")).read_bytes())
                self.assertEqual(2, delivered["view"]["revision"])
                self.assertEqual(1, len(delivered["view"]["objective"]["intent"]["replacements"]))
                self.assertIn("Use the corrected current DocB material.", delivered["view"]["request"])
            final = next(item["claim"] for item in result["candidate"]["claims"] if item["job_id"] == "r1-repair-" + leaf("REQ-B")[3:])
            self.assertEqual(23, json.loads(final["text"])["value"])


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--material-child":
        raise SystemExit(child(*sys.argv[2:]))
    unittest.main()
