"""The checked-in responsibility indexes resolve to the canonical public bundle."""
from datetime import date
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_control_plane import build_report, inventory, path_matches


class ControlPlaneRegistryTest(unittest.TestCase):
    def test_repository_indexes_pass_the_unchanged_coverage_gate(self):
        report = build_report(ROOT, date(2026, 10, 7))
        self.assertEqual("PASS", report["status"], report["findings"])
        self.assertGreaterEqual(report["summary"]["classification_coverage"], .98)
        self.assertEqual(7, report["summary"]["registered_agent_count"])
        self.assertEqual(0, report["summary"]["active_agent_count"])
        self.assertFalse(any(report["claims"].values()))

    def test_named_virtual_environments_are_pruned_but_unknown_sources_remain(self):
        registry = json.loads(
            (ROOT / "governance/knowledge-registry.json").read_text(encoding="utf-8")
        )
        scope = registry["inventory_scope"]
        classification_patterns = [
            pattern
            for family in registry["fact_families"]
            for pattern in family["classification_patterns"]
        ]
        original_scandir = os.scandir
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            excluded = [root / "venv-agent", root / "adapter/venv-worker"]
            for environment in excluded:
                package = environment / "lib/site-packages/generated_dependency.py"
                package.parent.mkdir(parents=True)
                package.write_text("# Installed dependency\n", encoding="utf-8")
            (root / "README.md").write_text("# Known source\n", encoding="utf-8")
            (root / "unclassified-source.txt").write_text(
                "Unclassified source must stay visible\n", encoding="utf-8"
            )
            scanned = []

            def scan(directory):
                directory = Path(directory)
                self.assertNotIn(directory, excluded, "excluded environment was scanned")
                scanned.append(directory)
                return original_scandir(directory)

            with patch("audit_control_plane.os.scandir", side_effect=scan):
                files = inventory(root, scope["include"], scope["exclude"])

            self.assertCountEqual([root, root / "adapter"], scanned)
            self.assertEqual(["README.md", "unclassified-source.txt"], files)
            uncovered = [p for p in files if not path_matches(p, classification_patterns)]
            self.assertEqual(["unclassified-source.txt"], uncovered)
            self.assertEqual(0.98, scope["minimum_classification_coverage"])

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
        result = subprocess.run([sys.executable,str(ROOT/"tools/audit_control_plane.py"),"--root",str(ROOT),"--as-of","2026-10-07","--fail-on","warning"],capture_output=True,timeout=30)
        self.assertEqual(1,result.returncode)
        report = json.loads(result.stdout)
        self.assertEqual("PASS",report["status"])
        stale = [f for f in report["findings"] if f["code"]=="stale-canonical-source"]
        self.assertTrue(stale)
        self.assertTrue(all(f["evidence"]["observed_date"]=="2026-09-07" for f in stale))


if __name__ == "__main__":
    unittest.main()
