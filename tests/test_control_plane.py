from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]

PAIRS = (
    ("governance/okf.json", "schemas/okf.schema.json"),
    ("governance/knowledge-registry.json", "schemas/knowledge-registry.schema.json"),
    ("governance/agent-registry.json", "schemas/agent-registry.schema.json"),
    ("governance/audit-policy.json", "schemas/audit-policy.schema.json"),
)


class ControlPlaneTest(unittest.TestCase):
    def load(self, relative: str):
        return json.loads((ROOT / relative).read_text(encoding="utf-8"))

    def test_control_plane_instances_validate_against_schemas(self) -> None:
        for instance_path, schema_path in PAIRS:
            with self.subTest(instance=instance_path):
                schema = self.load(schema_path)
                Draft202012Validator.check_schema(schema)
                validator = Draft202012Validator(schema, format_checker=FormatChecker())
                errors = sorted(validator.iter_errors(self.load(instance_path)), key=lambda e: list(e.path))
                self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def test_read_only_audit_passes_structural_gates(self) -> None:
        process = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools" / "audit_control_plane.py"),
                "--root",
                str(ROOT),
                "--as-of",
                "2026-09-07",
                "--format",
                "json",
                "--fail-on",
                "error",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual("PASS", report["status"])
        self.assertEqual(0, report["summary"]["critical"])
        self.assertEqual(0, report["summary"]["error"])
        self.assertGreaterEqual(report["summary"]["classification_coverage"], 0.98)
        self.assertGreaterEqual(report["summary"]["registered_agent_count"], 1)
        self.assertEqual(0, report["summary"]["active_agent_count"])
        self.assertTrue(all(value is False for value in report["claims"].values()))

    def test_agents_are_pre_activation_candidates(self) -> None:
        registry = self.load("governance/agent-registry.json")
        for agent in registry["agents"]:
            with self.subTest(agent=agent["id"]):
                self.assertIn(agent["activation_state"], {"planned", "candidate", "disabled", "retired"})
                self.assertIn(agent["authority"], {"read_only", "proposal_only"})
                self.assertIsNone(agent["runtime_evidence"])
                self.assertTrue(agent["eval_gate"]["required_before_activation"])
                self.assertEqual(0, agent["eval_gate"]["critical_failures_allowed"])

    def test_missing_kgi_baselines_are_explicit(self) -> None:
        okf = self.load("governance/okf.json")
        for kgi in okf["kgis"]:
            with self.subTest(kgi=kgi["id"]):
                if kgi["baseline_status"] == "not_measured":
                    self.assertIsNone(kgi["baseline"])

    def test_autonomy_boundary_stays_closed(self) -> None:
        policy = self.load("governance/audit-policy.json")
        boundaries = policy["autonomy_boundaries"]
        self.assertEqual("proposal_only", boundaries["agentic_maintenance_default"])
        forbidden = set(boundaries["automatic_outputs_forbidden"])
        self.assertTrue(
            {
                "human_approval",
                "capability_grant",
                "promotion",
                "current_truth_change",
                "runtime_deployment",
                "final_human_go",
                "public_beta_go",
            }.issubset(forbidden)
        )


if __name__ == "__main__":
    unittest.main()
