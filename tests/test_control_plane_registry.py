"""The checked-in responsibility indexes resolve to the canonical public bundle."""
from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_control_plane import build_report


class ControlPlaneRegistryTest(unittest.TestCase):
    def test_repository_indexes_pass_the_unchanged_coverage_gate(self):
        report = build_report(ROOT, date(2026, 10, 6))
        self.assertEqual("PASS", report["status"], report["findings"])
        self.assertGreaterEqual(report["summary"]["classification_coverage"], .98)
        self.assertEqual(7, report["summary"]["registered_agent_count"])
        self.assertEqual(0, report["summary"]["active_agent_count"])
        self.assertFalse(any(report["claims"].values()))

    def test_responsibility_mapping_keeps_execution_and_knowledge_owners(self):
        agents = json.loads((ROOT/"governance/agent-registry.json").read_text(encoding="utf-8"))
        ids = {a["id"] for a in agents["agents"]}
        self.assertIn("git-steward", ids)
        self.assertNotIn("okf-steward", ids)
        self.assertTrue(all(a["runtime_evidence"] is None for a in agents["agents"]))
        self.assertTrue(all(a["authority"] in {"read_only","proposal_only"} for a in agents["agents"]))
        self.assertTrue(all(a["eval_gate"]["required_before_activation"] and a["eval_gate"]["critical_failures_allowed"]==0 for a in agents["agents"]))
        families = json.loads((ROOT/"governance/knowledge-registry.json").read_text(encoding="utf-8"))["fact_families"]
        paths = {f["id"]:f["canonical_path"] for f in families}
        self.assertEqual("knowledge/project/success-model.md", paths["project_goal_and_kgi"])
        self.assertEqual("knowledge/profile.yaml", paths["knowledge_operations"])

    def test_old_review_date_stays_visible_and_warning_exit_is_explicit(self):
        result = subprocess.run([sys.executable,str(ROOT/"tools/audit_control_plane.py"),"--root",str(ROOT),"--as-of","2026-10-06","--fail-on","warning"],capture_output=True,timeout=30)
        self.assertEqual(1,result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("PASS",report["status"])
        stale = [f for f in report["findings"] if f["code"]=="stale-canonical-source"]
        self.assertTrue(stale)
        self.assertTrue(all(f["evidence"]["observed_date"]=="2026-09-07" for f in stale))


if __name__ == "__main__":
    unittest.main()
