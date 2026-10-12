"""Current multi-parent Source reaches real child stdin through the existing owner.

Four synthetic children compute Source data, not echo purpose. Historical input
rows are exact owner-pinned copies, never independently verified external history.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
from tests.test_knowledge_task_input import (MARKER, REFS, STAMP, admit,
    markdown, reseal_seed, setup, source, span)
from kotodama_kb.task_input import catalog_context, compile_task_input, execute_task_input, verify_task_input
from kotodama_kb.foundation import KnowledgeBaseError
from runtime.task_swarm.protocol import SwarmError, canonical, digest

ORIGINAL = "Compute source measurements while retaining both parent constraints."
CORRECTED = "Compute corrected source measurements; missing values remain unknown and both parents apply."
COMMON = "Missing measurements remain unknown."
SPAN_KEYS = {"source_key", "source_revision", "start", "end"}


def inventory(root):
    return sorted((path.relative_to(root).as_posix(),
        hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None)
        for path in root.rglob("*"))


def fixture(root, *, public=False, previous=None, planning=0, work_count=3):
    bundle, base, owner, file = setup(root, jobs=1, public=public)
    selected = [row for row in base["sources"] if row["key"] not in {
        source("request", 1, "")["key"], source("REQ-0", 1, "")["key"],
        source("project", 1, "")["key"]}]
    selection, _, _ = catalog_context(bundle, REFS, max_concepts=6 if public else 4)
    corrected = previous is not None
    revision = 2 if corrected else 1
    count = planning or work_count
    names = ["REQ-A", "REQ-B", "REQ-C"][:count]
    ordered = (["REQ-ROOT"] if planning else []) + names
    declaration = {"kind": "kotodama.task-context-request", "version": 2 if planning else 1,
        "owner_ref": "ref/owner/synthetic", "intent": {}, "references": copy.deepcopy(REFS),
        "max_concepts": 6 if public else 4,
        "catalog_bindings": {concept.concept_id: {"source_key": row["key"], "source_revision": row["revision"]}
            for concept, row in zip(selection.selected, selected)},
        "hierarchy": [], "constraints": [], "unknowns": [],
        "budget": {"attempt_budget": 6 if planning else 4, "deadline": STAMP + 100}}
    if planning:
        declaration["root_requirement_id"] = "REQ-ROOT"
    else:
        declaration["jobs"] = [{"requirement_id": name, "job_id": "work-" + name[-1].lower()}
                               for name in names]
    rows, accepted = {}, []
    for name in ordered:
        data = ({"operation": "latency", "values": [2, 4, 6, 8, 12 if corrected else 10]}
                if name == "REQ-A" else {"operation": "rss", "values": [None, 32, 48]}
                if name == "REQ-B" else {"operation": "count", "values": [None, 0, 3]})
        need = (name + " combines every declared child." if name == "REQ-ROOT" else
                "[" + name + "] DATA=" + canonical(data))
        acceptance = name + " matches its current source measurements."
        fields = {"need": need, "constraints": [], "acceptance": [acceptance]}
        if planning:
            fields["frontier"] = {"kind": "all_of" if name == "REQ-ROOT" else "atomic",
                                  "children": names if name == "REQ-ROOT" else [], "requires": []}
        body = "\n\n".join([need, acceptance, CORRECTED if corrected else ORIGINAL] if name == "REQ-A"
                            else [need, acceptance])
        text = markdown({"template_kind": "requirement", "id": name,
            "parent_refs": ["PROJECT-A", "PROJECT-B"], "status": "draft", "task_context": fields}, body)
        row = source(name, revision if name == "REQ-A" else 1, text)
        rows[name] = row
        path = root / "work" / (name + ".md")
        path.write_bytes(text.encode("utf-8"))
        declaration["hierarchy"].append({"path": path.relative_to(root).as_posix(),
            "source_key": row["key"], "source_revision": row["revision"]})
        accepted.append(acceptance)
    original = previous or rows["REQ-A"]
    declaration["intent"] = {"original": span(original, ORIGINAL),
        "replacements": [span(rows["REQ-A"], CORRECTED)] if corrected else []}
    for name in ("PROJECT-A", "PROJECT-B"):
        row_key = source(name, 1, "")["key"]
        declaration["hierarchy"].append({"path": "work/" + name + ".md",
                                       "source_key": row_key, "source_revision": revision})
    for name in ("PROJECT-A", "PROJECT-B"):
        extra = ("Every result names its workload." if name == "PROJECT-A" else
                 "Keep corrected workload boundaries explicit." if corrected else "Retain source boundaries.")
        body = COMMON + "\n\n" + extra
        if name == "PROJECT-A":
            body += "\n\n" + MARKER + "\n```json\n" + canonical(declaration) + "\n```"
        text = markdown({"template_kind": "project", "id": name, "status": "draft",
                         "task_context": {"constraints": [COMMON, extra]}}, body)
        rows[name] = source(name, revision, text)
        (root / "work" / (name + ".md")).write_bytes(text.encode("utf-8"))
    sources = [*selected, *rows.values(), *([copy.deepcopy(previous)] if corrected else [])]
    seed = {**base, "revision": revision, "request": CORRECTED if corrected else ORIGINAL,
            "sources": sources, "acceptance": accepted}
    document = json.loads(owner.read_bytes())
    document["binding"]["revision"] = revision
    document["actors"]["worker-c"] = {**document["actors"]["worker-b"],
                                         "invocation_ref": "invocation-worker-c"}
    owner.write_bytes(canonical(document).encode("utf-8"))
    reseal_seed(seed, owner, file)
    return bundle, seed, owner, file, rows


def edit_node(root, seed, name, edit, *, statements=()):
    row = next(row for row in seed["sources"] if row["key"] == source(name, 1, "")["key"]
               and row["revision"] == max(r["revision"] for r in seed["sources"]
                   if r["key"] == source(name, 1, "")["key"]))
    _, meta, body = row["text"].split("---", 2)
    value = yaml.safe_load(meta)
    edit(value)
    row["text"] = markdown(value, "\n\n".join([body.strip(), *statements]))
    row["sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
    (root / "work" / (name + ".md")).write_bytes(row["text"].encode("utf-8"))


def edit_declaration(root, seed, edit):
    row = next(r for r in seed["sources"] if MARKER in r["text"])
    start = row["text"].index("```json\n") + len("```json\n")
    end = row["text"].index("\n```", start)
    value = json.loads(row["text"][start:end])
    edit(value)
    row["text"] = row["text"][:start] + canonical(value) + row["text"][end:]
    row["sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
    (root / "work/PROJECT-A.md").write_bytes(row["text"].encode("utf-8"))


CHILD = r'''
import hashlib,json,math,sys
raw=sys.stdin.buffer.read(); d=json.loads(raw); actor,mode=sys.argv[1:]
canon=lambda v: json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
sha=lambda v: hashlib.sha256(canon(v).encode()).hexdigest()
if d['role']=='work':
    data=json.loads(d['purpose'].split(' DATA=',1)[1]); values=data['values']
    if data['operation']=='latency': result={'p95_ms':sorted(values)[math.ceil(.95*len(values))-1]}
    elif data['operation']=='rss': result={'peak_mib':max(v for v in values if v is not None),'missing':sum(v is None for v in values)}
    else: result={'present':sum(v is not None for v in values),'missing':sum(v is None for v in values)}
    quote=d['purpose']; record=next(r for r in d['view']['spans'] if r['text']==quote)
    claim=quote if mode=='echo' else canon({'wrong':0}) if mode=='wrong' else canon(result)
    ev={k:record[k] for k in ('source_key','source_revision','start','end')}
    result={'job_id':d['job_id'],'summary':'Computed Source measurements.','conflicts':[],
            'claims':[{'text':claim,'status':'inference','evidence':[{**ev,'quote':quote}]}]}
else:
    passed=True
    for job,report in d['reports'].items():
        evidence=report['claims'][0]['evidence'][0]; quote=evidence['quote']
        matching=[r for r in d['view']['spans'] if all(r[k]==evidence[k] for k in ('source_key','source_revision','start','end')) and r['text']==quote]
        passed=passed and len(matching)==1
        data=json.loads(quote.split(' DATA=',1)[1]); values=data['values']
        if data['operation']=='latency':
            ordered=sorted(values); value=next(v for i,v in enumerate(ordered,1) if i/len(ordered)>=.95); expected={'p95_ms':value}
        else:
            missing=len([v for v in values if v is None]); measured=sorted(v for v in values if v is not None)
            expected={'peak_mib':measured[-1],'missing':missing} if data['operation']=='rss' else {'present':len(values)-missing,'missing':missing}
        passed=passed and report['claims'][0]['text']==canon(expected)
    gap=next(r for r in d['view']['spans'] if r['text'].startswith('[REQ-') and ' DATA=' in r['text'])
    gap={k:gap[k] for k in ('source_key','source_revision','start','end')}
    result={'parent_input_digest':d['view']['parent_input_digest'],'plan_digest':d['view']['plan_digest'],
        'round':d['round'],'report_digests':d['report_digests'],'validations':[]}
    for key in d['criteria']:
        jobs=d['required_evidence_jobs'][key]
        evidence=[{'job_id':j,'claim_index':0} for j in jobs] if passed else []
        if mode=='omit_evidence' and len(evidence)>1: evidence=evidence[:-1]
        result['validations'].append({'criterion_id':key,'status':'passed' if passed else 'failed',
            'evidence':evidence,'gap_reason':None if passed else 'Independent Source arithmetic mismatch.',
            'source_spans':[] if passed else [gap]})
response={'result':result,'receipt':{'actor_ref':actor,'invocation_ref':'local-'+d['job_id'],
    'input_digest':sha(d),'synthetic':True}}
print(canon({'response':response,'raw_input_sha256':hashlib.sha256(raw).hexdigest()}))
'''


class ChildBackend:
    synthetic = True

    def __init__(self, *, mode="computed", after=None):
        self.inputs, self.observed, self.returncodes = [], [], []
        self.mode, self.after = mode, after

    def call(self, delivered, directory, *, actor_ref, **options):
        raw = (canonical(delivered) + "\n").encode("utf-8")
        child = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD, actor_ref, self.mode],
                               input=raw, capture_output=True, timeout=10, check=True)
        record = json.loads(child.stdout)
        self.inputs.append(copy.deepcopy(delivered))
        self.observed.append(record["raw_input_sha256"])
        self.returncodes.append(child.returncode)
        if self.after:
            self.after(delivered)
        return record["response"]

    produce = call
    review = call


class HierarchyBridgeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def compile(self, **options):
        bundle, seed, owner, file, rows = fixture(self.root, **options)
        before, supplied = inventory(self.root), copy.deepcopy(seed)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(before, inventory(self.root))
        self.assertEqual(supplied, seed)
        with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_MISMATCH"):
            verify_task_input(bundle, candidate, owner, clock=lambda: STAMP)
        self.assertEqual(before, inventory(self.root))
        return bundle, candidate, owner, file, rows

    def execute(self, bundle, candidate, owner, file, *, mode="computed", after=None):
        admit(candidate, owner, file)
        backend = ChildBackend(mode=mode, after=after)
        result = execute_task_input(bundle, candidate, owner, file, backend,
            worker_actors=["worker-a", "worker-b", "worker-c"], clock=lambda: STAMP)
        self.assertEqual([0] * len(backend.inputs), backend.returncodes)
        return backend, result

    def assert_delivery(self, candidate, backend, result, owner):
        directory = owner.parent / result["receipt"]["run_id"]
        for delivered, observed in zip(backend.inputs, backend.observed):
            raw = (directory / (delivered["job_id"] + "-input.json")).read_bytes()
            self.assertEqual(observed, hashlib.sha256(raw).hexdigest())
            self.assertEqual(canonical(delivered).encode() + b"\n", raw)
            self.assertEqual(digest(delivered), result["receipt"]["dispatches"][delivered["job_id"]]["delivered_input_digest"])
            self.assertEqual(candidate["payload"]["objective"], delivered["view"]["objective"])
            constraints = delivered["view"]["objective"]["constraints"]
            texts = {(r["source_key"], r["source_revision"], r["start"], r["end"]):r["text"] for r in delivered["view"]["spans"]}
            both = [r for r in constraints if texts[tuple(r[k] for k in ("source_key","source_revision","start","end"))] == COMMON]
            self.assertEqual(2, len(both))
            self.assertEqual(2, len({r["source_key"] for r in both}))
            self.assertEqual({"goal", "kgi", "initiative"}, {r["kind"] for r in delivered["view"]["objective"]["references"]})
        for row in candidate["payload"]["objective"]["constraints"]:
            self.assertEqual(SPAN_KEYS, set(row))

    def test_four_lanes_same_owner_correction_keeps_exact_historical_row_and_stdin(self):
        bundle, first, owner, file, rows = self.compile()
        self.assertEqual(9, len(first["payload"]["sources"]))
        old_row = copy.deepcopy(rows["REQ-A"])
        old_row_bytes = canonical(old_row).encode()
        old_backend, old_result = self.execute(bundle, first, owner, file)
        self.assertEqual(4, len(old_backend.inputs))
        self.assertTrue(old_result["receipt"]["review_passed"])
        self.assert_delivery(first, old_backend, old_result, owner)
        saved_directory = owner.parent / old_result["receipt"]["run_id"]
        saved_input_bytes = (saved_directory / "input.json").read_bytes()
        saved_row = next(r for r in json.loads(saved_input_bytes)["sources"] if r["key"] == old_row["key"])
        self.assertEqual(old_row_bytes, canonical(saved_row).encode())
        bundle, second, same_owner, same_file, _ = self.compile(previous=old_row)
        self.assertEqual((owner, file), (same_owner, same_file))
        self.assertEqual(10, len(second["payload"]["sources"]))
        saved = next(r for r in second["payload"]["sources"] if (r["key"],r["revision"]) == (old_row["key"],1))
        self.assertEqual(old_row_bytes, canonical(saved).encode())
        self.assertNotIn(MARKER, saved["text"])
        self.assertEqual(1, sum(r["text"].count(MARKER) for r in second["payload"]["sources"]))
        intent = second["payload"]["objective"]["intent"]
        self.assertEqual(intent["original"]["source_key"], intent["replacements"][0]["source_key"])
        self.assertEqual((1,2), (intent["original"]["source_revision"],intent["replacements"][0]["source_revision"]))
        self.assertEqual("input_only_unverified", second["diagnostics"]["history"])
        self.assertEqual(saved_input_bytes, (saved_directory / "input.json").read_bytes())
        admit(second, owner, file)
        stopped = ChildBackend()
        with self.assertRaisesRegex(SwarmError, "STALE_BINDING"):
            execute_task_input(bundle, first, owner, file, stopped,
                worker_actors=["worker-a", "worker-b", "worker-c"], clock=lambda: STAMP)
        self.assertEqual([], stopped.inputs)
        new_backend, result = self.execute(bundle, second, owner, file)
        self.assert_delivery(second, new_backend, result, owner)
        self.assertTrue(result["receipt"]["review_passed"])
        for old, new in zip(old_backend.inputs, new_backend.inputs):
            self.assertNotEqual(digest(old), digest(new))
            self.assertEqual(ORIGINAL, next(r["text"] for r in new["view"]["spans"] if r["source_key"] == old_row["key"] and r["source_revision"]==1 and r["start"]==intent["original"]["start"]))
        self.assertEqual(saved_input_bytes, (saved_directory / "input.json").read_bytes())
        reports = new_backend.inputs[-1]["reports"]
        self.assertEqual({"p95_ms":12}, json.loads(reports["r0-work-a"]["claims"][0]["text"]))
        self.assertEqual({"peak_mib":48,"missing":1}, json.loads(reports["r0-work-b"]["claims"][0]["text"]))
        self.assertEqual({"present":2,"missing":1}, json.loads(reports["r0-work-c"]["claims"][0]["text"]))

    def test_two_leaf_frontier_keeps_responsible_union_and_parents_separate(self):
        bundle, candidate, owner, file, rows = self.compile(planning=2)
        self.assertEqual(9, len(candidate["payload"]["sources"]))
        self.assertEqual(2, len(candidate["supplied_plan"]["jobs"]))
        self.assertEqual(["REQ-A","REQ-B"], candidate["diagnostics"]["frontier"]["criteria"][0]["leaf_requirement_ids"])
        backend, result = self.execute(bundle, candidate, owner, file)
        self.assertEqual(3, len(backend.inputs))
        self.assertTrue(result["receipt"]["review_passed"])
        self.assert_delivery(candidate, backend, result, owner)
        bundle, newer, owner, file, _ = self.compile(planning=2, previous=rows["REQ-A"])
        self.assertEqual(10, len(newer["payload"]["sources"]))
        backend, result = self.execute(bundle, newer, owner, file)
        self.assertTrue(result["receipt"]["review_passed"])
        self.assert_delivery(newer, backend, result, owner)

    def test_public_one_requirement_two_parents_and_full_four_lane_source_cap(self):
        bundle, candidate, owner, file, _ = self.compile(public=True, work_count=1)
        self.assertEqual(9, len(candidate["payload"]["sources"]))
        backend, result = self.execute(bundle, candidate, owner, file)
        self.assert_delivery(candidate, backend, result, owner)
        self.assertTrue(result["receipt"]["review_passed"])
        bundle, seed, owner, _, _ = fixture(self.root, public=True)
        self.assertEqual(11, len(seed["sources"]))
        before = inventory(self.root)
        with self.assertRaisesRegex(SwarmError, "TASK_SOURCES_INVALID"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(before, inventory(self.root))

    def test_three_leaf_frontier_correction_refuses_eleven_source_records(self):
        bundle, first, owner, file, rows = self.compile(planning=3)
        self.assertEqual(10, len(first["payload"]["sources"]))
        self.assertEqual(3, len(first["supplied_plan"]["jobs"]))
        bundle, seed, owner, _, _ = fixture(self.root, planning=3, previous=rows["REQ-A"])
        self.assertEqual(11, len(seed["sources"]))
        before = inventory(self.root)
        with self.assertRaisesRegex(SwarmError, "TASK_SOURCES_INVALID"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(before, inventory(self.root))

    def test_optional_phase_and_shared_parent_keep_each_source_identity_once(self):
        bundle, seed, owner, file, rows = fixture(self.root, work_count=1)
        text = "Phase constraints remain explicit."
        row = source("PHASE-A", 1, markdown({"template_kind":"phase", "id":"PHASE-A",
            "parent_refs":["PROJECT-A","PROJECT-B"], "status":"draft",
            "task_context":{"constraints":[text]}}, text))
        seed["sources"].append(row)
        (self.root / "work/PHASE-A.md").write_bytes(row["text"].encode())
        edit_node(self.root, seed, "REQ-A", lambda m: m.update(parent_refs=["PHASE-A","PROJECT-B"]))
        def declare(value):
            value["hierarchy"].append({"path":"work/PHASE-A.md", "source_key":row["key"], "source_revision":1})
            value["intent"]["original"] = span(rows["REQ-A"], ORIGINAL)
        edit_declaration(self.root, seed, declare)
        reseal_seed(seed, owner, file)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        reverse = candidate["diagnostics"]["structural_parents"]["reverse_refs"]
        self.assertEqual(["PHASE-A","REQ-A"], reverse["PROJECT-B"])
        backend, result = self.execute(bundle, candidate, owner, file)
        self.assert_delivery(candidate, backend, result, owner)
        for delivered in backend.inputs:
            self.assertEqual(1, sum(r["text"]==text for r in delivered["view"]["spans"]))

    def test_shared_atomic_leaf_is_one_job_and_all_of_cycle_still_refuses(self):
        bundle, seed, owner, file, rows = fixture(self.root, planning=2)
        need = "REQ-A requires its declared child measurement."
        edit_node(self.root, seed, "REQ-A", lambda m: m["task_context"].update(
            need=need, frontier={"kind":"all_of","children":["REQ-B"],"requires":[]}), statements=[need])
        edit_declaration(self.root, seed, lambda d: d["intent"].update(original=span(rows["REQ-A"], ORIGINAL)))
        reseal_seed(seed, owner, file)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(1, len(candidate["supplied_plan"]["jobs"]))
        self.assertTrue(all(r["leaf_requirement_ids"]==["REQ-B"] for r in candidate["diagnostics"]["frontier"]["criteria"]))
        backend, result = self.execute(bundle, candidate, owner, file)
        self.assertEqual(2, len(backend.inputs))
        self.assert_delivery(candidate, backend, result, owner)
        edit_node(self.root, seed, "REQ-B", lambda m: m["task_context"].update(
            frontier={"kind":"all_of","children":["REQ-ROOT"],"requires":[]}))
        reseal_seed(seed, owner, file)
        before = inventory(self.root)
        with self.assertRaisesRegex(SwarmError, "TASK_FRONTIER_CYCLE"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(before, inventory(self.root))

    def test_existing_prerequisite_lane_stays_separate_from_structural_parents(self):
        from runtime.task_swarm.dependency_contract import descriptor
        # This pre-existing pytest helper uses direct test-module imports.
        # Keep that lookup local rather than change production/package paths.
        with mock.patch.object(sys, "path", [str(ROOT / "tests"), *sys.path]):
            from tests.test_task_swarm_dependency_source import SourceCalculation
        bundle, seed, owner, file, _ = fixture(self.root, planning=2)
        # The existing fixture backend expects its discrete 20-value percentile.
        edit_node(self.root, seed, "REQ-B", lambda m: m["task_context"]["frontier"].update(requires=["REQ-A"]))
        reseal_seed(seed, owner, file)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        plan = candidate["supplied_plan"]
        self.assertEqual(2, plan["version"])
        desc, _ = descriptor(candidate["payload"], plan)
        self.assertEqual(1, len(desc["gate"]))
        for node in candidate["diagnostics"]["structural_parents"]["edges"]:
            self.assertIn(node["parent"], {"PROJECT-A","PROJECT-B"})
        # SourceCalculation uses a fixed 20-value data fixture; use the real
        # baseline source fixture below rather than silently change that work.
        from tests.test_knowledge_task_frontier import fixture as existing_fixture, graph
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec = graph(two=True)
            spec["REQ-RSS"]["requires"] = ["REQ-LATENCY"]
            current_bundle, current_seed, current_owner, current_file, _ = existing_fixture(root, spec)
            from tests.test_knowledge_task_input import change_declaration
            def pair(value):
                value["hierarchy"].append({"path":"work/PROJECT-B.md",
                    "source_key":source("PROJECT-B",1,"")["key"],"source_revision":1})
            change_declaration(current_seed, root, pair)
            text = markdown({"template_kind":"project","id":"PROJECT-B","status":"draft",
                "task_context":{"constraints":[COMMON]}}, COMMON)
            current_seed["sources"].append(source("PROJECT-B",1,text))
            (root / "work/PROJECT-B.md").write_bytes(text.encode())
            for name in ("REQ-ROOT","REQ-LATENCY","REQ-RSS"):
                edit_node(root, current_seed, name, lambda m: (m.pop("parent_ref"),
                    m.update(parent_refs=["PROJECT-SYNTHETIC","PROJECT-B"])))
            reseal_seed(current_seed, current_owner, current_file)
            current = compile_task_input(current_bundle, current_seed, current_owner, clock=lambda: STAMP)
            admit(current, current_owner, current_file)
            backend = SourceCalculation()
            result = execute_task_input(current_bundle, current, current_owner, current_file, backend,
                worker_actors=["worker-a","worker-b"], clock=lambda: STAMP)
            self.assertEqual(4, len(backend.inputs))
            self.assertEqual(3, result["receipt"]["version"])
            self.assertTrue(result["receipt"]["review_passed"])
            self.assertEqual(1, sum("core" in d for d in backend.inputs))
            self.assertEqual(1, sum("prerequisite" in d for d in backend.inputs))
        # Three dependent leaves remain outside the accepted one-edge slice.
        bundle, seed, owner, file, _ = fixture(self.root, planning=3)
        edit_node(self.root, seed, "REQ-B", lambda m: m["task_context"]["frontier"].update(requires=["REQ-A"]))
        reseal_seed(seed, owner, file)
        with self.assertRaisesRegex(SwarmError, "TASK_FRONTIER_DEPENDENCY_UNSUPPORTED"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)

    def test_old_audit_time_does_not_waive_inflight_or_completed_concept_expiry(self):
        for phase in ("inflight", "replay"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                setup(root, jobs=1)
                for path in (root / "knowledge/synthetic").glob("*.md"):
                    path.write_bytes(path.read_bytes().replace(b"2026-12-07T00:00:00Z", b"2026-10-10T00:00:02Z"))
                bundle, seed, owner, file, _ = fixture(root, work_count=1)
                edit_declaration(root, seed, lambda d: d["budget"].update(deadline=STAMP+2))
                reseal_seed(seed, owner, file)
                before = inventory(root)
                with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_EXPIRED"):
                    compile_task_input(bundle, seed, owner, clock=lambda: STAMP+2)
                self.assertEqual(before, inventory(root))
                candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                admit(candidate, owner, file)
                now = [STAMP]
                def advance(delivered):
                    if delivered["role"] == "critic": now[0] = STAMP+2
                backend = ChildBackend(after=advance if phase == "inflight" else None)
                if phase == "inflight":
                    with self.assertRaisesRegex(SwarmError, "DEADLINE|EXPIRED"):
                        execute_task_input(bundle, candidate, owner, file, backend,
                            worker_actors=["worker-a"], clock=lambda: now[0])
                    self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))
                else:
                    result = execute_task_input(bundle, candidate, owner, file, backend,
                        worker_actors=["worker-a"], clock=lambda: now[0])
                    stopped = ChildBackend()
                    with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_EXPIRED"):
                        execute_task_input(bundle, candidate, owner, file, stopped, worker_actors=["worker-a"],
                            clock=lambda: STAMP+2, expected_receipt_sha256=result["receipt_sha256"])
                    self.assertEqual([], stopped.inputs)
                self.assertEqual([0,0], backend.returncodes)

    def test_lazy_helper_absence_is_typed_and_unrelated_import_error_is_retained(self):
        module = "kotodama_kb.hierarchy_reader"
        bundle, seed, owner, file = setup(self.root, jobs=1)
        with mock.patch.dict(sys.modules, {module: None}):
            default = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertNotIn("structural_parents", default["diagnostics"])
        bundle, candidate, owner, file, _ = self.compile(work_count=1)
        admit(candidate, owner, file)
        before = inventory(self.root)
        backend = ChildBackend()
        with mock.patch.dict(sys.modules, {module: None}):
            with self.assertRaisesRegex(SwarmError, "TASK_CONTEXT_HIERARCHY_UNSUPPORTED"):
                execute_task_input(bundle, candidate, owner, file, backend,
                    worker_actors=["worker-a"], clock=lambda: STAMP)
        self.assertEqual([], backend.inputs)
        self.assertEqual(before, inventory(self.root))
        unrelated = ModuleNotFoundError("missing unrelated dependency", name="unrelated_dependency")
        with mock.patch("importlib.import_module", side_effect=unrelated):
            with self.assertRaises(ModuleNotFoundError) as caught:
                verify_task_input(bundle, candidate, owner, clock=lambda: STAMP)
        self.assertIs(unrelated, caught.exception)
        self.assertEqual(before, inventory(self.root))

    def test_source_cli_compiles_the_opt_in_and_missing_helper_refuses_without_writes(self):
        _bundle, seed, owner, file, _rows = fixture(self.root, work_count=1)
        edit_declaration(self.root, seed, lambda d: d["budget"].update(deadline=time.time()+600))
        reseal_seed(seed, owner, file)
        document = json.loads(owner.read_bytes())
        document["binding"]["expires_at"] = time.time()+900
        owner.write_bytes(canonical(document).encode()+b"\n")
        args = ["task-input", "compile", "--root", str(self.root), "--owner", str(owner),
                "--input", str(file), "--as-of", "2026-10-10T00:00:00Z"]
        before = inventory(self.root)
        native = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "tools/knowledge_base.py"), *args],
                                cwd=self.root.parent, capture_output=True, timeout=30)
        self.assertEqual(0, native.returncode, native.stderr)
        self.assertEqual(b"", native.stderr)
        self.assertEqual(2, len(json.loads(native.stdout)["diagnostics"]["structural_parents"]["edges"]))
        self.assertEqual(before, inventory(self.root))
        code = ("import sys; sys.path.insert(0, sys.argv[1]); "
                "sys.modules['kotodama_kb.hierarchy_reader']=None; "
                "from kotodama_kb.cli import main; raise SystemExit(main(sys.argv[2:]))")
        missing = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT / "tools"), *args],
                                 cwd=self.root.parent, capture_output=True, timeout=30)
        self.assertEqual(2, missing.returncode, missing.stderr)
        self.assertEqual(b"", missing.stdout)
        self.assertEqual("TASK_CONTEXT_HIERARCHY_UNSUPPORTED", json.loads(missing.stderr)["error"])
        self.assertEqual(before, inventory(self.root))

    def test_current_strict_fields_and_structural_limits_refuse_not_partial_context(self):
        cases = {
            "mixed_parent": ("REQ-A", lambda m: m.update(parent_ref="PROJECT-A")),
            "unknown_parent": ("REQ-A", lambda m: m.update(parent_refs=["PROJECT-A","MISSING"])),
            "duplicate_parent": ("REQ-A", lambda m: m.update(parent_refs=["PROJECT-A","PROJECT-A"])),
            "third_parent": ("REQ-A", lambda m: m.update(parent_refs=["PROJECT-A","PROJECT-B","PROJECT-C"])),
            "project_frontier": ("PROJECT-B", lambda m: m["task_context"].update(frontier={"kind":"atomic","children":[],"requires":[]})),
            "requirement_frontier_v1": ("REQ-A", lambda m: m["task_context"].update(frontier={"kind":"atomic","children":[],"requires":[]})),
            "unknown_field": ("REQ-A", lambda m: m["task_context"].update(unrecognized=True)),
            "unresolved_kind": ("PROJECT-B", lambda m: m.update(template_kind="organization_plan")),
        }
        for name, (node, change) in cases.items():
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, seed, owner, file, _ = fixture(root, work_count=1)
                edit_node(root, seed, node, change)
                reseal_seed(seed, owner, file)
                before = inventory(root)
                with self.assertRaises(SwarmError):
                    compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                self.assertEqual(before, inventory(root))

    def test_constraint_twenty_is_separate_from_reader_thirty_two_selection_cap(self):
        bundle, seed, owner, file, _ = fixture(self.root, work_count=1)
        for name in ("PROJECT-A", "PROJECT-B"):
            added = [name + " explicit constraint " + str(i) for i in range(8)]
            edit_node(self.root, seed, name,
                      lambda m, added=added: m["task_context"]["constraints"].extend(added), statements=added)
        reseal_seed(seed, owner, file)
        candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(20, len(candidate["payload"]["objective"]["constraints"]))
        added = "PROJECT-B twenty-first aggregate constraint."
        edit_node(self.root, seed, "PROJECT-B",
                  lambda m: m["task_context"]["constraints"].append(added), statements=[added])
        reseal_seed(seed, owner, file)
        before = inventory(self.root)
        with self.assertRaisesRegex(SwarmError, "OBJECTIVE_SPANS_INVALID"):
            compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
        self.assertEqual(before, inventory(self.root))

    def test_cross_key_correction_and_missing_history_or_old_declaration_are_rejected(self):
        for case in ("cross_key", "same_revision", "missing_history", "stale_marker", "duplicate_source"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, _, _, _, rows = fixture(root, work_count=1)
                bundle, seed, owner, file, current = fixture(root, work_count=1, previous=rows["REQ-A"])
                if case == "cross_key":
                    edit_declaration(root, seed, lambda d: d["intent"].update(original=span(current["PROJECT-B"], COMMON)))
                elif case == "same_revision":
                    edit_declaration(root, seed, lambda d: d["intent"].update(replacements=[span(rows["REQ-A"], ORIGINAL)]))
                elif case == "missing_history":
                    seed["sources"] = [r for r in seed["sources"] if (r["key"],r["revision"]) != (rows["REQ-A"]["key"],1)]
                elif case == "stale_marker":
                    historical = next(r for r in seed["sources"] if (r["key"],r["revision"]) == (rows["REQ-A"]["key"],1))
                    historical["text"] += "\n" + MARKER + '\n```json\n{"kind":"old"}\n```\n'
                else:
                    seed["sources"].append(copy.deepcopy(current["REQ-A"]))
                reseal_seed(seed, owner, file)
                before = inventory(root)
                expected = ("OBJECTIVE_CORRECTION_ORDER" if case in ("cross_key","same_revision") else
                            "OBJECTIVE_SOURCE_UNKNOWN" if case == "missing_history" else
                            "TASK_CONTEXT_DECLARATION_STALE" if case == "stale_marker" else "TASK_SOURCE_DUPLICATE")
                with self.assertRaisesRegex(SwarmError, expected):
                    compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                self.assertEqual(before, inventory(root))

    def test_echo_wrong_arithmetic_and_missing_assigned_evidence_do_not_pass(self):
        for mode in ("echo", "wrong", "omit_evidence"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, seed, owner, file, _ = fixture(root)
                candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                admit(candidate, owner, file)
                backend = ChildBackend(mode=mode)
                if mode == "omit_evidence":
                    with self.assertRaisesRegex(SwarmError, "LOOP_CRITIC"):
                        execute_task_input(bundle, candidate, owner, file, backend,
                            worker_actors=["worker-a","worker-b","worker-c"], clock=lambda: STAMP)
                    self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))
                else:
                    result = execute_task_input(bundle, candidate, owner, file, backend,
                        worker_actors=["worker-a","worker-b","worker-c"], clock=lambda: STAMP)
                    self.assertFalse(result["receipt"]["review_passed"])
                self.assertEqual(4, len(backend.inputs))
                self.assertEqual([0]*4, backend.returncodes)

    def test_source_bytes_structure_and_current_actor_or_revision_cannot_be_cached(self):
        for case in ("same_size_mtime", "add", "delete", "rename", "actor", "revision"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, seed, owner, file, _ = fixture(root, work_count=1)
                candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                admit(candidate, owner, file)
                def change(_delivered):
                    target = root / "work/PROJECT-B.md"
                    if case == "same_size_mtime":
                        stat = target.stat()
                        target.write_bytes(target.read_bytes().replace(b"Retain source", b"retain source"))
                        os.utime(target, ns=(stat.st_atime_ns,stat.st_mtime_ns))
                        self.assertEqual(stat.st_size, target.stat().st_size)
                    elif case == "add":
                        (root / "knowledge/synthetic/extra.md").write_bytes((root / "knowledge/synthetic/0.md").read_bytes())
                    elif case == "delete":
                        target.unlink()
                    elif case == "rename":
                        target.rename(target.with_name("renamed.md"))
                    else:
                        document = json.loads(owner.read_bytes())
                        if case == "actor": document["actors"]["verifier"]["epoch"] += 1
                        else: document["binding"]["revision"] += 1
                        owner.write_bytes(canonical(document).encode())
                backend = ChildBackend(after=change)
                with self.assertRaises((SwarmError, KnowledgeBaseError)):
                    execute_task_input(bundle, candidate, owner, file, backend,
                        worker_actors=["worker-a"], clock=lambda: STAMP)
                self.assertEqual([0], backend.returncodes)
                self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))

    def test_final_eligibility_withdrawal_refuses_anchor_but_post_cutoff_returns_exact_anchor(self):
        from runtime.task_swarm import closed_loop_recovery as finalizer
        for phase in ("before_final_guard", "after_final_guard"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                bundle, seed, owner, file, _ = fixture(root, work_count=1)
                candidate = compile_task_input(bundle, seed, owner, clock=lambda: STAMP)
                admit(candidate, owner, file)
                backend = ChildBackend()
                def withdraw():
                    document = json.loads(owner.read_bytes())
                    document["binding"]["status"] = "cancelled"
                    owner.write_bytes(canonical(document).encode())
                write, replace = finalizer.write_json, finalizer.os.replace
                def staged(path, value):
                    result = write(path, value)
                    if path.name == ".receipt-pending.json": withdraw()
                    return result
                def publish(source_path, target):
                    if Path(target).name == "receipt.json": withdraw()
                    return replace(source_path, target)
                patch = mock.patch.object(finalizer, "write_json", side_effect=staged) if phase == "before_final_guard" else mock.patch.object(finalizer.os, "replace", side_effect=publish)
                with patch:
                    if phase == "before_final_guard":
                        with self.assertRaisesRegex(SwarmError, "INACTIVE_TASK|RUN_CANCELLED"):
                            execute_task_input(bundle, candidate, owner, file, backend,
                                worker_actors=["worker-a"], clock=lambda: STAMP)
                        self.assertEqual([], list(owner.parent.glob("task-run-*/receipt.json")))
                        execution = json.loads(next(owner.parent.glob("task-run-*/execution.json")).read_bytes())
                        self.assertTrue(all(j["state"]=="accepted" for j in execution["jobs"].values()))
                    else:
                        result = execute_task_input(bundle, candidate, owner, file, backend,
                            worker_actors=["worker-a"], clock=lambda: STAMP)
                        receipt = owner.parent / result["receipt"]["run_id"] / "receipt.json"
                        self.assertEqual(result["receipt_sha256"], hashlib.sha256(receipt.read_bytes()).hexdigest())
                        stopped = ChildBackend()
                        with self.assertRaisesRegex(SwarmError, "INACTIVE_TASK|RUN_CANCELLED"):
                            execute_task_input(bundle, candidate, owner, file, stopped, worker_actors=["worker-a"],
                                expected_receipt_sha256=result["receipt_sha256"], clock=lambda: STAMP)
                        self.assertEqual([], stopped.inputs)
                self.assertEqual(2, len(backend.inputs))


if __name__ == "__main__":
    unittest.main()
