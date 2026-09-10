"""Intent preservation checks; not an assertion that live company tasks work."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("persona_audit", ROOT / "tools/run_persona_intent_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)

class PersonaIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = audit.run(ROOT)

    def test_every_executed_case_satisfies_independent_user_outcome(self):
        for case in self.report["cases"]:
            if case["status"] == "BLOCKED":
                continue
            with self.subTest(case=case["id"]):
                self.assertEqual(case["status"], "PASS", case["failures"])

    def test_blocked_journeys_are_not_counted_as_pass_or_hidden(self):
        self.assertEqual(self.report["counts"], {"PASS": 192, "FAIL": 0, "BLOCKED": 24})
        self.assertEqual(self.report["executed_behavior_families"], 16)
        self.assertEqual(self.report["personas"], 12)
        self.assertFalse(any(self.report["claims"].values()))
        self.assertEqual(len({c["id"] for c in self.report["cases"]}), 216)
        self.assertTrue(all(c["actual"] for c in self.report["cases"] if c["status"] == "BLOCKED"))

    def test_test_inventory_preserves_assertions_and_unreviewed_status(self):
        records = audit.inventory(ROOT)
        self.assertTrue(records)
        self.assertTrue(any(r["assertion_calls"] for r in records))
        self.assertTrue(all(r["review_status"].startswith("structurally_inventoried") for r in records))


class ContextEmissionTests(unittest.TestCase):
    def test_cli_emitted_utf8_obeys_requested_budget(self):
        import json
        import subprocess
        import sys
        from datetime import datetime, timezone
        sys.path.insert(0, str(ROOT / "tools"))
        from compile_knowledge_context import compile_context
        workspace = ROOT / "examples/knowledge-work/business-rehearsal"
        result = compile_context(workspace, now=datetime(2026, 9, 11, tzinfo=timezone.utc))
        required = len(json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")) + 3
        completed = subprocess.run([sys.executable, str(ROOT / "tools/compile_knowledge_context.py"),
            str(workspace), "--as-of", "2026-09-11T00:00:00Z", "--max-bytes", str(required)],
            capture_output=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertLessEqual(len(completed.stdout), required)
        self.assertEqual(json.loads(completed.stdout)["status"], "READY_CANDIDATE")

    def test_default_markdown_withholds_context_and_explicit_display_is_inert(self):
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        import project_agent_status as projector
        r, c, o = audit.diagnostic_inputs(audit.PERSONAS[0])
        r["agents"][0]["name"] = "![private](https://example.invalid/never-fetch)"
        r["agents"][0]["purpose"] = "SYNTHETIC-PRIVATE-PURPOSE"
        result = projector.project(r, c, o, as_of="2026-09-11T00:00:30Z")
        default = projector.markdown(result)
        for hidden in (r["agents"][0]["purpose"], "example.invalid", o["observations"][0]["current_work_ref"], o["observations"][0]["run_ref"]):
            self.assertNotIn(hidden, default)
        explicit = projector.markdown(result, include_context=True)
        self.assertIn("SYNTHETIC-PRIVATE-PURPOSE", explicit)
        self.assertNotIn("![private](", explicit)

if __name__ == "__main__":
    unittest.main()
