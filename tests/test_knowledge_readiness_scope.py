"""Observed scope and unresolved dependencies stay distinct from conformance."""
import contextlib
import datetime as dt
import io
import json
import tempfile
import unittest
from pathlib import Path

from tests import test_knowledge_base as fixture

KB, AS_OF = fixture.KB, fixture.AS_OF


class KnowledgeReadinessScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = KB.load_bundle(fixture.ROOT, as_of=AS_OF)

    def copy(self):
        temp = tempfile.TemporaryDirectory(prefix="okf-scope-")
        self.addCleanup(temp.cleanup)
        return fixture.KnowledgeBaseTests._minimal_copy(Path(temp.name))

    def scoped(self, bundle=None, **kwargs):
        return KB.decision_readiness_report(
            bundle or self.bundle, actor="human:reviewer", purpose="review project direction",
            task="task:owned-fixture", evaluated_at=AS_OF, **kwargs)

    def test_time_and_task_are_both_required_without_creating_authority(self):
        for args in ({}, {"task": "task:owned-fixture"}, {"evaluated_at": AS_OF}):
            with self.subTest(args=args):
                report = KB.decision_readiness_report(self.bundle, actor="human:reviewer", purpose="review", **args)
                self.assertEqual(report["DECISION_READY"], "NOT_EVALUATED")
                self.assertIn("EXPLICIT_TIME_AND_TASK_REQUIRED", report["global_blockers"])
        report = self.scoped()
        self.assertEqual(report["schema_revision"], "v2")
        self.assertEqual(report["DECISION_READY"], "NEEDS_RESOLUTION")
        self.assertEqual(report["task_ref"], "task:owned-fixture")
        self.assertIn("ACTOR_PURPOSE_ACCESS_NOT_RESOLVED", report["global_blockers"])

    def test_different_or_naive_readiness_instant_requires_reload(self):
        for instant in (AS_OF + dt.timedelta(seconds=1), AS_OF.replace(tzinfo=None)):
            with self.subTest(instant=instant), self.assertRaisesRegex(KB.KnowledgeBaseError, "READINESS_INSTANT_MISMATCH"):
                KB.decision_readiness_report(self.bundle, actor="human:reviewer", purpose="review", evaluated_at=instant)

    def test_invalid_scope_types_cannot_mean_no_requirements(self):
        base = {"actor": "human:reviewer", "purpose": "review", "task": "task:fixture", "evaluated_at": AS_OF}
        cases = []
        for field in ("concept_ids", "mandatory_concept_ids"):
            cases += [(field, value, "READINESS_CONCEPT_IDS_INVALID") for value in
                      (False, "project/goal", {}, [False], [None], [""], [" project/goal"], ["project/goal"] * 257)]
        for field in ("actor", "purpose", "task"):
            cases += [(field, value, "READINESS_SCOPE_INVALID") for value in (False, {}, "", " ", "x" * 4097)]
        cases += [("evaluated_at", value, "READINESS_INSTANT_INVALID") for value in ("2026-10-04T14:00:00Z", AS_OF.date(), False)]
        for field, value, code in cases:
            with self.subTest(field=field, value_type=type(value).__name__), self.assertRaisesRegex(KB.KnowledgeBaseError, "^" + code + "$"):
                KB.decision_readiness_report(self.bundle, **(base | {field: value}))
        explicit_empty = self.scoped(mandatory_concept_ids=[])
        self.assertEqual(explicit_empty["mandatory_context"], "INCLUDED")
        self.assertEqual(explicit_empty["DECISION_READY"], "NEEDS_RESOLUTION")

    def test_missing_required_context_and_unknown_requirements_do_not_pass(self):
        unknown = self.scoped(concept_ids=["project/goal"])
        self.assertEqual(unknown["mandatory_context"], "NOT_EVALUATED")
        missing = self.scoped(concept_ids=["project/goal"], mandatory_concept_ids=["governance/authority-boundaries"])
        self.assertEqual(missing["mandatory_context"], "MISSING")
        self.assertEqual(missing["missing_mandatory_concept_ids"], ["governance/authority-boundaries"])
        self.assertIn("MANDATORY_CONTEXT_MISSING", missing["global_blockers"])
        rendered = KB.readiness_markdown(missing)
        self.assertIn("## Missing required concepts", rendered)
        self.assertIn("governance/authority-boundaries", rendered)
        self.assertIn("attestation=NOT_EVALUATED", rendered)
        included = self.scoped(concept_ids=["project/goal"], mandatory_concept_ids=["project/goal"])
        self.assertEqual(included["mandatory_context"], "INCLUDED")
        self.assertEqual(included["DECISION_READY"], "NEEDS_RESOLUTION")

    def test_readiness_has_independent_dimensions_and_no_unearned_verification(self):
        row = self.scoped(concept_ids=["project/goal"])["concepts"][0]
        self.assertEqual(row["checks"], {
            "source_resolution": "RESOLVED_LOCAL", "source_revision_integrity": "MATCHED_LOCAL_SNAPSHOT",
            "verification": "NOT_RECORDED", "freshness": "CURRENT", "conflict": "NO_CONFLICT_DECLARED",
            "access": "UNRESOLVED", "attestation": "NOT_EVALUATED", "mandatory_context": "NOT_EVALUATED",
            "final_readiness": "NEEDS_RESOLUTION"})
        self.assertIn("NO_INDEPENDENT_VERIFICATION", row["blockers"])

    def test_external_source_is_not_a_verified_local_revision(self):
        root = self.copy()
        path = root / "knowledge/project/goal.md"
        path.write_text(path.read_text(encoding="utf-8").replace("../../README.md", "https://example.invalid/source"), encoding="utf-8")
        row = self.scoped(KB.load_bundle(root, as_of=AS_OF), concept_ids=["project/goal"])["concepts"][0]
        self.assertEqual(row["checks"]["source_resolution"], "UNRESOLVED")
        self.assertEqual(row["checks"]["source_revision_integrity"], "UNRESOLVED")
        self.assertIn("SOURCE_NOT_RESOLVED_LOCALLY", row["blockers"])

    def test_optional_dates_follow_guidance_without_becoming_standard_errors(self):
        root = self.copy()
        path = root / "knowledge/project/goal.md"
        cases = ("stale_after: 2026-12-07", "sources: [{resource: sample, last_modified: 2026-12-07}]",
                 "usage_window: {from: 2026-12-07, to: 2026-12-08}",
                 "sources: [{resource: sample, usage_window: {from: 2026-12-07, to: 2026-12-08}}]",
                 "verified: {by: 'human:reviewer', at: 2026-12-07}", "generated: {at: 2026-12-07}")
        for fields in cases:
            with self.subTest(fields=fields):
                path.write_text("---\ntype: Extension Type\n" + fields + "\n---\n", encoding="utf-8")
                result = KB.validation_verdicts(KB.load_bundle(root, as_of=AS_OF))
                self.assertEqual(result["OKF_CONFORMANT"]["verdict"], "PASS")
                self.assertEqual(result["KOTODAMA_PROFILE_PASS"]["verdict"], "FAIL")
                self.assertTrue(result["OKF_CONFORMANT"]["guidance"])
                self.assertTrue(all(i["code"] == "OKF_TIMESTAMP_GUIDANCE" for i in result["OKF_CONFORMANT"]["guidance"]))
                path.write_text(path.read_text(encoding="utf-8").replace("2026-12-07", "2026-12-07T00:00:00Z").replace("2026-12-08", "2026-12-08T00:00:00+09:00"), encoding="utf-8")
                good = KB.validation_verdicts(KB.load_bundle(root, as_of=AS_OF))
                self.assertEqual(good["OKF_CONFORMANT"]["guidance"], [])

    def test_extensions_and_concept_history_survive_projection_round_trip(self):
        root = self.copy()
        path = root / "knowledge/project/goal.md"
        marker = "future_extension: {mode: preserved, nested: [one, two]}\n"
        path.write_text(path.read_text(encoding="utf-8").replace("sources:\n", marker + "sources:\n", 1), encoding="utf-8")
        before = path.read_bytes()
        bundle = KB.load_bundle(root, as_of=AS_OF)
        self.assertEqual(KB.validation_verdicts(bundle)["KOTODAMA_PROFILE_PASS"]["verdict"], "PASS")
        KB.build(bundle, check=False)
        after = KB.load_bundle(root, as_of=AS_OF)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(after.by_id["project/goal"].metadata["future_extension"], {"mode": "preserved", "nested": ["one", "two"]})

    def test_date_only_is_a_profile_error_on_otherwise_valid_concepts(self):
        root = self.copy()
        path = root / "knowledge/project/goal.md"
        raw = path.read_text(encoding="utf-8")
        _, head, body = raw.split("---", 2)
        metadata = KB._load_yaml(head, path=path)
        for target in ("stale", "source", "shared_window", "source_window"):
            with self.subTest(target=target):
                value = json.loads(json.dumps(metadata))
                if target == "stale":
                    value["stale_after"] = "2026-12-07"
                elif target == "source":
                    value["sources"][0]["last_modified"] = "2026-12-07"
                else:
                    owner = value if target == "shared_window" else value["sources"][0]
                    owner["usage_window"] = {"from": "2026-12-07", "to": "2026-12-08"}
                draft = "---\n" + KB.yaml.safe_dump(value) + "---" + body
                path.write_text(draft, encoding="utf-8")
                verdict = KB.validation_verdicts(KB.load_bundle(root, as_of=AS_OF))
                self.assertEqual(verdict["OKF_CONFORMANT"]["verdict"], "PASS")
                self.assertEqual(verdict["KOTODAMA_PROFILE_PASS"]["verdict"], "FAIL")
                self.assertTrue(verdict["OKF_CONFORMANT"]["guidance"])
                def timestamp_values(node):
                    if isinstance(node, dict):
                        return {key: timestamp_values(child) for key, child in node.items()}
                    if isinstance(node, list):
                        return [timestamp_values(child) for child in node]
                    if isinstance(node, str) and node in {"2026-12-07", "2026-12-08"}:
                        return node + "T00:00:00Z"
                    return node
                path.write_text("---\n" + KB.yaml.safe_dump(timestamp_values(value)) + "---" + body, encoding="utf-8")
                good = KB.validation_verdicts(KB.load_bundle(root, as_of=AS_OF))
                self.assertEqual(good["KOTODAMA_PROFILE_PASS"]["verdict"], "PASS")
                self.assertEqual(good["OKF_CONFORMANT"]["guidance"], [])

    def test_cli_requires_explicit_time_and_reports_every_requested_requirement(self):
        args = ["readiness", "--root", str(fixture.ROOT), "--actor", "human:reviewer", "--purpose", "review", "--task", "task:fixture"]
        for extra, verdict in (([], "NOT_EVALUATED"), (["--as-of", AS_OF.isoformat(), "--concept", "project/goal", "--required-concept", "governance/authority-boundaries"], "NEEDS_RESOLUTION")):
            with self.subTest(extra=extra):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = KB.main(args + extra)
                report = json.loads(output.getvalue())
                self.assertEqual(code, 3)
                self.assertEqual(report["DECISION_READY"], verdict)
                if extra:
                    self.assertEqual(report["mandatory_context"], "MISSING")


if __name__ == "__main__":
    unittest.main()
