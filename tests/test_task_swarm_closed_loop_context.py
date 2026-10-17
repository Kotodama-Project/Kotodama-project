"""Synthetic child projections; no provider, filesystem source or Task grant."""
import copy
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from task_swarm.closed_loop_context import (
    MAX_SELECTED_SPANS, derive_child_view, validate_report_in_view,
)
from task_swarm.protocol import SwarmError, canonical, digest
from task_swarm.task_contract import validate_input, validate_report


PLAN = "d" * 64


def source(key, revision, text):
    return {"key": key * 64, "revision": revision, "text": text,
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}


def span(record, text):
    start = record["text"].index(text)
    return {"source_key": record["key"], "source_revision": record["revision"],
            "start": start, "end": start + len(text)}


def fixture():
    original = source("a", 1, "結果を整理する\nUNSELECTED-HISTORY")
    current = source("a", 2, "速度とメモリを同じ条件で比較する\n設定は提案だけに留める\n"
                     "本番の同時利用数は不明\n条件と未解決点を示す\nUNSELECTED-CURRENT")
    definitions = source("b", 4, "OUT-INTENT\nKGI-INTENT\nINIT-CONTEXT\nUNSELECTED-DEFINITION")
    detail = source("c", 1, "前置き🍀必要な追加根拠です。隣接の根拠です。\nUNSELECTED-DETAIL")
    request, constraint, unknown, acceptance = current["text"].splitlines()[:4]
    payload = {"version": 2, "task_id": "task-00000000-0000-4000-8000-000000000001", "revision": 5,
               "request": request, "acceptance": [acceptance],
               "sources": [original, current, definitions, detail],
               "objective": {"owner_ref": "ref/owner/fixture",
                    "intent": {"original": span(original, "結果を整理する"),
                               "replacements": [span(current, request)]},
                    "references": [{"kind": kind, "id": name, "source": span(definitions, name)}
                                   for kind, name in (("goal", "OUT-INTENT"), ("kgi", "KGI-INTENT"),
                                                      ("initiative", "INIT-CONTEXT"))],
                    "constraints": [span(current, constraint)], "unknowns": [span(current, unknown)],
                    "acceptance": [span(current, acceptance)],
                    "budget": {"attempt_budget": 4, "deadline": 1100},
                    "stop_conditions": ["cancelled", "binding_changed", "deadline_exceeded"],
                    "rollback": "not_applicable_read_only"}}
    binding = {"task_id": payload["task_id"], "revision": 5, "context_digest": digest(payload),
               "owner_ref": "ref/owner/fixture", "active_home": "fixture",
               "authority_ref": "ref/authority/fixture", "capability_ref": "ref/capability/swarm_research",
               "expires_at": 1200, "status": "active"}
    return validate_input(payload, binding, now=1000)


def report(payload, quote, *, job="facts", source_index=3, status="supported"):
    record = payload["sources"][source_index]
    return {"job_id": job, "summary": "合成報告", "conflicts": [],
            "claims": [{"text": "根拠のある合成主張", "status": status,
                        "evidence": [{**span(record, quote), "quote": quote}]}]}


class ClosedLoopContextTests(unittest.TestCase):
    def setUp(self):
        self.payload = fixture()
        self.selected = span(self.payload["sources"][3], "必要な追加根拠です。")

    def view(self, *, selected=None, job="facts", **options):
        return derive_child_view(self.payload, job, [self.selected] if selected is None else selected,
                                 plan_digest=PLAN, **options)

    def refusal(self, code, function):
        with self.assertRaises(SwarmError) as raised:
            function()
        self.assertEqual(raised.exception.code, code)

    def test_all_objective_texts_remain_and_unselected_source_bodies_are_absent(self):
        value = self.view()
        texts = {item["text"] for item in value["spans"]}
        self.assertEqual(texts, {"結果を整理する", self.payload["request"], "OUT-INTENT", "KGI-INTENT",
                                 "INIT-CONTEXT", "設定は提案だけに留める", "本番の同時利用数は不明",
                                 "条件と未解決点を示す", "必要な追加根拠です。"})
        self.assertNotIn("UNSELECTED", canonical(value))
        self.assertNotIn("sources", value)
        self.assertEqual(value["objective"], self.payload["objective"])
        self.assertEqual(value["acceptance"], self.payload["acceptance"])

    def test_selection_uses_original_unicode_codepoint_offsets_and_text_sha(self):
        item = self.view()["spans"][-1]
        self.assertEqual(item["start"], 4)
        self.assertGreater(len("前置き🍀".encode()), item["start"])
        self.assertEqual({key: item[key] for key in self.selected}, self.selected)
        self.assertEqual(item["sha256"], hashlib.sha256(item["text"].encode()).hexdigest())

    def test_view_is_deterministic_and_changes_no_parent_data(self):
        before = copy.deepcopy(self.payload)
        value = self.view()
        self.assertEqual(value, self.view())
        self.assertEqual(value["parent_input_digest"], digest(before))
        self.assertEqual(value["view_digest"], digest({k: v for k, v in value.items() if k != "view_digest"}))
        value["objective"]["unknowns"].clear()
        self.assertEqual(self.payload, before)

    def test_all_children_preserve_objective_and_distinct_bindings(self):
        first = self.view()
        other = derive_child_view(self.payload, "memory-analysis", [], plan_digest="e" * 64,
                                  previous_critic_digest="f" * 64)
        self.assertEqual(first["objective"], other["objective"])
        self.assertEqual(first["request"], other["request"])
        self.assertNotEqual(first["view_digest"], other["view_digest"])
        self.assertEqual(other["previous_critic_digest"], "f" * 64)

    def test_duplicate_selections_and_current_mandatory_refs_are_deduplicated(self):
        request = self.payload["objective"]["intent"]["replacements"][0]
        self.assertEqual(self.view(), self.view(selected=[request, self.selected, self.selected]))

    def test_original_history_is_delivered_but_cannot_be_selected_as_current(self):
        old = self.payload["objective"]["intent"]["original"]
        self.assertIn({**old, "text": "結果を整理する",
                       "sha256": hashlib.sha256("結果を整理する".encode()).hexdigest()}, self.view()["spans"])
        self.refusal("OBJECTIVE_SOURCE_STALE", lambda: self.view(selected=[old]))

    def test_version_one_is_not_silently_given_an_invented_objective(self):
        self.payload.pop("objective")
        self.payload["version"] = 1
        self.refusal("CLOSED_LOOP_OBJECTIVE_REQUIRED", self.view)

    def test_selection_count_and_type_are_bounded(self):
        for selection in (None, (), "text", [self.selected] * (MAX_SELECTED_SPANS + 1)):
            with self.subTest(selection_type=type(selection).__name__):
                self.refusal("CLOSED_LOOP_SELECTION_LIMIT",
                             lambda: derive_child_view(self.payload, "facts", selection, plan_digest=PLAN))

    def test_invalid_source_revisions_and_offsets_are_refused(self):
        for changes, code in (({"source_key": "f" * 64}, "OBJECTIVE_SOURCE_UNKNOWN"),
                              ({"source_revision": 9}, "OBJECTIVE_SOURCE_UNKNOWN"),
                              ({"source_key": []}, "OBJECTIVE_SOURCE_UNKNOWN"),
                              ({"start": -1}, "INVALID_LIMIT"), ({"start": True}, "INVALID_LIMIT"),
                              ({"end": 99999}, "INVALID_LIMIT"), ({"end": 4}, "OBJECTIVE_SPAN_INVALID"),
                              ({"quote": "extra"}, "OBJECTIVE_SPAN_INVALID")):
            with self.subTest(changes=changes):
                self.refusal(code, lambda: self.view(selected=[{**self.selected, **changes}]))

    def test_job_and_digest_metadata_are_validated(self):
        for job in ("", "../facts", "a" * 65, "Facts", "事実", 3):
            with self.subTest(job=job):
                self.refusal("CLOSED_LOOP_JOB_INVALID", lambda: self.view(job=job))
        for field in ("plan_digest", "previous_critic_digest"):
            for value in ("x" * 64, 1, "a" * 63):
                with self.subTest(field=field, value=value):
                    options = {"plan_digest": PLAN, field: value}
                    self.refusal("INVALID_DIGEST", lambda: derive_child_view(
                        self.payload, "facts", [], **options))

    def test_overlapping_selections_cannot_exceed_context_byte_limit(self):
        record = source("e", 1, "x" * 12000)
        self.payload["sources"].append(record)
        selections = [{"source_key": record["key"], "source_revision": 1, "start": index,
                       "end": 12000 - index} for index in range(MAX_SELECTED_SPANS)]
        self.refusal("CLOSED_LOOP_CONTEXT_LIMIT", lambda: self.view(selected=selections))

    def test_delivered_evidence_returns_the_original_report(self):
        value = report(self.payload, "必要な追加根拠です。")
        self.assertEqual(validate_report_in_view(value, self.view(), self.payload), value)

    def test_report_of_original_intent_uses_its_historical_revision(self):
        value = report(self.payload, "結果を整理する", source_index=0)
        self.assertEqual(validate_report_in_view(value, self.view(), self.payload), value)

    def test_dynamic_jobs_use_the_existing_explicit_allowlist(self):
        value = report(self.payload, "必要な追加根拠です。", job="memory-analysis")
        view = self.view(job="memory-analysis")
        self.refusal("REPORT_JOB_INVALID", lambda: validate_report_in_view(value, view, self.payload))
        self.assertEqual(validate_report_in_view(value, view, self.payload,
                                                allowed_jobs=("memory-analysis",)), value)

    def test_parent_valid_evidence_outside_the_delivered_view_is_refused(self):
        value = report(self.payload, "UNSELECTED-DETAIL")
        self.assertEqual(validate_report(value, "facts", self.payload), value)
        self.refusal("REPORT_EVIDENCE_NOT_DELIVERED",
                     lambda: validate_report_in_view(value, self.view(), self.payload))

    def test_evidence_cannot_bridge_adjacent_delivered_spans(self):
        detail = self.payload["sources"][3]
        view = self.view(selected=[self.selected, span(detail, "隣接の根拠です。")])
        value = report(self.payload, "必要な追加根拠です。隣接の根拠です。")
        self.refusal("REPORT_EVIDENCE_NOT_DELIVERED", lambda: validate_report_in_view(value, view, self.payload))

    def test_inference_evidence_has_the_same_delivered_scope(self):
        value = report(self.payload, "UNSELECTED-DETAIL", status="inference")
        self.refusal("REPORT_EVIDENCE_NOT_DELIVERED",
                     lambda: validate_report_in_view(value, self.view(), self.payload))

    def test_existing_parent_quote_validation_is_still_enforced(self):
        value = report(self.payload, "必要な追加根拠です。")
        value["claims"][0]["evidence"][0]["quote"] = "changed"
        self.refusal("REPORT_SPAN_MISMATCH", lambda: validate_report_in_view(value, self.view(), self.payload))

    def test_modified_view_fields_are_refused(self):
        for mutate in (lambda v: v.update(parent_input_digest="e" * 64),
                       lambda v: v.update(view_digest="e" * 64),
                       lambda v: v.update(request="changed"),
                       lambda v: v["spans"][-1].update(text="changed"),
                       lambda v: v["spans"][-1].update(sha256="e" * 64),
                       lambda v: v["spans"].reverse()):
            view = self.view()
            mutate(view)
            self.refusal("CLOSED_LOOP_VIEW_MISMATCH", lambda: validate_report_in_view(
                report(self.payload, "必要な追加根拠です。"), view, self.payload))

    def test_missing_mandatory_span_is_refused_even_with_recomputed_view_digest(self):
        view = self.view()
        view["spans"].pop(0)
        view["view_digest"] = digest({k: v for k, v in view.items() if k != "view_digest"})
        self.refusal("CLOSED_LOOP_VIEW_MISMATCH", lambda: validate_report_in_view(
            report(self.payload, "必要な追加根拠です。"), view, self.payload))

    def test_python_numeric_equality_cannot_hide_changed_view_types(self):
        for field, replacement in (("version", True), ("revision", 5.0)):
            view = self.view()
            view[field] = replacement
            self.refusal("CLOSED_LOOP_VIEW_MISMATCH", lambda: validate_report_in_view(
                report(self.payload, "必要な追加根拠です。"), view, self.payload))

    def test_changed_parent_cannot_reuse_an_older_view(self):
        view = self.view()
        self.payload["sources"][3]["text"] += " source changed"
        self.payload["sources"][3]["sha256"] = hashlib.sha256(self.payload["sources"][3]["text"].encode()).hexdigest()
        self.refusal("CLOSED_LOOP_VIEW_MISMATCH", lambda: validate_report_in_view(
            report(self.payload, "必要な追加根拠です。"), view, self.payload))

    def test_malformed_view_and_span_shapes_are_typed_refusals(self):
        for change in (lambda v: v.update(extra=True), lambda v: v.update(spans="text"),
                       lambda v: v["spans"][0].update(extra=True)):
            view = self.view()
            change(view)
            self.refusal("CLOSED_LOOP_VIEW_INVALID", lambda: validate_report_in_view(
                report(self.payload, "必要な追加根拠です。"), view, self.payload))


if __name__ == "__main__":
    unittest.main()
