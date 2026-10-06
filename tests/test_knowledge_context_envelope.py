"""One context format, distinct from authority and semantic acceptance."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import knowledge_base as kb
from knowledge_context import context_digest, context_json, make_context


class KnowledgeContextEnvelopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = kb.load_bundle(ROOT,as_of=datetime(2026,10,4,14,tzinfo=timezone.utc))
        cls.schema = json.loads((ROOT/"schemas/knowledge-context-bundle.schema.json").read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema,format_checker=FormatChecker())

    def context(self):
        selection=kb.select_context(self.bundle,goals=["OUT-INTENT"],kgis=[],initiatives=[],tags=[],max_concepts=8)
        return kb.context_as_dict(selection,bundle=self.bundle)

    def test_actual_knowledge_producer_emits_the_closed_v2_envelope(self):
        context=self.context()
        self.validator.validate(context)
        self.assertEqual(context["schema_revision"],"v2")
        self.assertEqual(context["kind"],"kotodama.generated-knowledge-context")
        self.assertIsNone(context["work"])
        self.assertEqual(context["errors"],[])
        self.assertFalse(any(context["claims"].values()))
        self.assertEqual(context["context_sha256"],context_digest(context))

    def test_changes_to_content_and_acceptance_surface_change_the_digest(self):
        before=self.context()
        changed=json.loads(context_json(before))
        changed["concepts"][0]["description"]+=" synthetic correction"
        self.assertNotEqual(before["context_sha256"],context_digest(changed))
        self.assertEqual(before["context_sha256"],context_digest(dict(reversed(list(before.items())))))

    def test_wrong_version_second_family_extra_fields_and_authority_are_refused(self):
        for update in ({"schema_revision":"v1"},{"kind":"knowledge_context_bundle"},{"extra":True},{"authority":"approved"},{"claims":{}}):
            with self.subTest(update=update):
                self.assertFalse(self.validator.is_valid({**self.context(),**update}))

    def test_refusal_has_the_same_fields_without_work_or_source_identity(self):
        refused=make_context(bundle_id="kotodama-knowledge-work",source_digest=None,
            as_of="2026-10-04T14:00:00Z",errors=["SENSITIVITY_CEILING"])
        self.validator.validate(refused)
        self.assertEqual(set(refused),set(self.context()))
        self.assertIsNone(refused["context_sha256"])
        self.assertIsNone(refused["work"])
        self.assertEqual(refused["concepts"],[])
        self.assertEqual(refused["state"],"needs_resolution")

    def test_work_payload_and_related_identifiers_are_cleared_on_refusal(self):
        secret="SYNTHETIC_SENSITIVE_WORK"
        for reason in ({"errors":["SENSITIVITY_CEILING"]},{"unresolved_ids":[secret]}):
            with self.subTest(reason=reason):
                value=make_context(bundle_id="kotodama-knowledge-work",source_digest="a"*64,
                    as_of="2026-10-04T14:00:00Z",work={"objective":secret,"acceptance_criteria":[secret],"deliverable_bindings":[secret]},
                    omitted_ids=[secret],filters={"goals":[secret],"kgis":[],"initiatives":[],"tags":[]},**reason)
                self.assertIsNone(value["work"])
                self.assertIsNone(value["source_digest"])
                self.assertIsNone(value["context_sha256"])
                self.assertNotIn(secret,context_json(value))
                self.validator.validate(value)


if __name__ == "__main__":
    unittest.main()
