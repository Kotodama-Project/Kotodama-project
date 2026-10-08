import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import unittest

from tools import relationship_catalog as catalog

ROOT = Path(__file__).resolve().parents[1]


class RelationshipCatalogTests(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((ROOT / "examples/relationship-catalog/synthetic.json").read_text(encoding="utf-8"))
        self.args = dict(tenant="example", actor="example-reader", purpose="planning", now=datetime(2026, 10, 8, tzinfo=timezone.utc))

    def view(self):
        return catalog.project(self.document, **self.args)

    def test_same_name_different_provider_stays_separate_and_context_matches_ui(self):
        view = self.view()
        self.assertEqual(len(view["records"]), 5)
        people = [row for row in view["records"] if row["entity_type"] == "person"]
        self.assertEqual(people[0]["label"], people[1]["label"])
        self.assertNotEqual(people[0]["id"], people[1]["id"])
        page = catalog.render(view)
        for row in view["records"]:
            self.assertIn(row["label"], page)
        self.assertFalse(view["provider_verified"])

    def test_deleted_and_revoked_latest_hide_old_rows_and_dependent_relationships(self):
        for state in ("deleted", "revoked"):
            with self.subTest(state=state):
                updated = {**self.document["records"][0], "revision": 2, "state": state}
                self.document["records"].append(updated)
                view = self.view()
                self.assertEqual({row["record_id"] for row in view["records"]}, {"o1", "p1"})
                self.assertEqual([row["provider"] for row in view["records"] if row["record_id"] == "p1"], ["salesforce"])
                self.document["records"].pop()

    def test_retry_dedup_conflict_and_explicit_new_revision_resolution(self):
        original = self.document["records"][0]
        before = self.view()["context_digest"]
        self.document["records"].append(copy.deepcopy(original))
        self.assertEqual(self.view()["context_digest"], before)
        self.document["records"].append({**original, "label": "競合した説明"})
        self.assertEqual(len(self.view()["records"]), 2)
        self.document["records"].append({**original, "revision": 2, "source_revision": "resolved-2", "label": "確認した説明"})
        self.assertEqual(len(self.view()["records"]), 5)
        self.assertIn("確認した説明", catalog.render(self.view()))

    def test_acl_purpose_tenant_and_expiry_do_not_fall_back(self):
        original = self.document["records"][0]
        self.document["records"].append({**original, "revision": 2, "readers": []})
        self.assertEqual(len(self.view()["records"]), 2)
        for field, value in (("tenant", "another"), ("actor", "another"), ("purpose", "another")):
            with self.subTest(field=field):
                self.assertEqual(catalog.project(self.document, **{**self.args, field:value})["records"], [])
        self.assertEqual(catalog.project(self.document, **{**self.args, "now":datetime(2030,1,1,tzinfo=timezone.utc)})["records"], [])

    def test_selected_synthetic_mapping_rejects_unknown_object_or_field(self):
        profile = dict(synthetic=True, tenant="example", connection="sandbox-fixture", owner="owner", readers=["example-reader"], purposes=["planning"], objects={"Contact":["Id","Name"]})
        rows = [dict(fields={"Id":"p9", "Name":"架空人物"}, revision=1, source_revision="fixture-1", expires_at="2030-01-01T00:00:00Z", state="active")]
        kwargs = dict(profile=profile, object_name="Contact", entity_type="person", field_map={"Name":"label"})
        result = catalog.map_salesforce_fixture(rows, **kwargs)
        self.assertEqual(result["records"][0]["connection"], "sandbox-fixture")
        for changed in (dict(object_name="Account"), dict(field_map={"Email":"label"}), dict(profile={**profile,"synthetic":False})):
            with self.assertRaises(ValueError):
                catalog.map_salesforce_fixture(rows, **{**kwargs, **changed})
        rows[0]["fields"]["Secret"] = "unselected fixture"
        with self.assertRaises(ValueError):
            catalog.map_salesforce_fixture(rows, **kwargs)

    def test_html_escapes_source_text_and_real_data_flag_is_rejected(self):
        self.document["records"][0]["label"] = '<script>fixture</script>'
        page = catalog.render(self.view())
        self.assertNotIn('<script>fixture</script>', page)
        self.assertIn('&lt;script&gt;fixture&lt;/script&gt;', page)
        self.document["synthetic"] = False
        with self.assertRaises(ValueError):
            self.view()
        with self.assertRaises(ValueError):
            json.loads('{"revision":1,"revision":2}', object_pairs_hook=catalog.unique_object)


if __name__ == "__main__":
    unittest.main()
