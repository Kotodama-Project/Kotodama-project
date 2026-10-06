"""Bounded public responsibility-index checks; no live-agent assertion."""
from __future__ import annotations

import copy
from datetime import date
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import audit_control_plane as audit

AS_OF = date(2026, 10, 6)


class ControlPlaneTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = audit.load_bundle(ROOT).input_bindings

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        for relative, _ in self.inputs:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        for name in ("knowledge-registry", "agent-registry", "audit-policy"):
            shutil.copyfile(ROOT / f"schemas/{name}.schema.json", self.root / f"schemas/{name}.schema.json")
        self.knowledge = {
            "version": 1, "status": "candidate_only", "reviewed_at": "2026-09-07",
            "inventory_scope": {"include": ["*"], "exclude": [], "minimum_classification_coverage": 0.98},
            "fact_families": [{"id": "knowledge", "description": "Synthetic fixture",
                "canonical_path": "knowledge/project/goal.md", "human_projection_paths": [],
                "classification_patterns": ["*"], "freshness": {"mode":"manual", "max_age_days":None,"severity":"warning"},
                "owner_role":"AI-LIBRARIAN","required_provenance":["fixture"]}],
            "contradiction_policy": {"severity_1_examples":["unsupported truth"],"required_action":"review","agent_may_auto_resolve":False}}
        self.agents = {"version":2,"status":"candidate_only","reviewed_at":"2026-09-07",
            "activation_policy":{"default":"not_active","required_before_active":["external owner"],"unregistered_agent":"forbidden","candidate_only_note":"responsibility index"},
            "agents":[{"id":"fixture-auditor","name":"Fixture auditor","purpose":"Test only",
                "canonical_role":"AI-AUDITOR","knowledge_refs":["project/goal"],
                "activation_state":"planned","authority":"read_only","reads_fact_families":["knowledge"],
                "outputs":["finding"],"capabilities":[],"prohibited_actions":["activate"],
                "eval_gate":{"required_before_activation":True,"suite":"synthetic","minimum_pass_rate":1,"critical_failures_allowed":0},
                "rollback":{"method":"discard candidate","owner_role":"AI-AUDITOR"},
                "implementation":{"kind":"unbound","path":None},"runtime_evidence":None}]}
        self.policy = {"version":1,"status":"candidate_only","reviewed_at":"2026-09-07",
            "optimization_priority":["safety"],"cadence":[{"id":"audit","frequency":"on_pull_request","mode":"deterministic","authority":"read_only","outputs":["finding"]}],
            "gates":[{"id":"closed","severity":"critical","condition":"no authority"}],
            "finding_lifecycle":{"states":["candidate"],"critical_owner_sla_days":0,"high_resolution_target_days":1,"required_fields":["evidence"]},
            "autonomy_boundaries":{"deterministic_checks_may_run_automatically":True,"agentic_maintenance_default":"proposal_only",
                "automatic_outputs_allowed":["finding"],"automatic_outputs_forbidden":["human_approval","capability_grant","promotion","current_truth_change","runtime_deployment","final_human_go","public_beta_go"]}}
        self.flush()

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8", newline="\n")

    def flush(self):
        for name, value in (("knowledge-registry",self.knowledge),("agent-registry",self.agents),("audit-policy",self.policy)):
            self.write(f"governance/{name}.json", value)

    def report(self):
        self.flush()
        return audit.build_report(self.root, AS_OF)

    def test_real_bundle_and_synthetic_indexes_pass_without_authority(self):
        before = {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        report = self.report()
        self.assertEqual("PASS", report["status"], report["findings"])
        self.assertGreaterEqual(report["summary"]["classification_coverage"], .98)
        self.assertEqual(0, report["summary"]["active_agent_count"])
        self.assertFalse(any(report["claims"].values()))
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertEqual(before, {p.relative_to(self.root).as_posix():p.read_bytes() for p in self.root.rglob("*") if p.is_file()})

    def test_unknown_concept_and_fact_family_are_refused(self):
        self.agents["agents"][0]["knowledge_refs"] = ["project/absent"]
        self.agents["agents"][0]["reads_fact_families"] = ["absent"]
        report = self.report()
        self.assertEqual("REFUSED", report["status"])
        self.assertTrue({"unknown-concept-reference","unknown-fact-family"}.issubset({f["code"] for f in report["findings"]}))

    def test_unknown_schema_fields_and_active_claim_are_refused(self):
        for field, value in (("activation_state","active"),("authority","bounded_execute"),("runtime_evidence",{"PASS":True}),("kgi_links",["KGI-01"])):
            with self.subTest(field=field):
                original = copy.deepcopy(self.agents)
                self.agents["agents"][0][field] = value
                self.assertIn("invalid-registry-json", {f["code"] for f in self.report()["findings"]})
                self.agents = original

    def test_coverage_gate_cannot_be_lowered_and_unclassified_files_fail(self):
        self.knowledge["inventory_scope"]["minimum_classification_coverage"] = .5
        self.assertEqual("REFUSED", self.report()["status"])
        self.knowledge["inventory_scope"]["minimum_classification_coverage"] = .98
        self.knowledge["fact_families"][0]["classification_patterns"] = ["knowledge/*"]
        self.assertIn("inventory-coverage", {f["code"] for f in self.report()["findings"]})

    def test_canonical_path_escape_and_competing_owners_fail(self):
        self.knowledge["fact_families"][0]["canonical_path"] = "../outside.json"
        self.assertIn("missing-canonical-source", {f["code"] for f in self.report()["findings"]})
        self.knowledge["fact_families"].append(copy.deepcopy(self.knowledge["fact_families"][0]))
        self.assertIn("competing-canonical-owner", {f["code"] for f in self.report()["findings"]})

    def test_stale_source_date_is_preserved_as_warning(self):
        family = self.knowledge["fact_families"][0]
        family["canonical_path"] = "governance/agent-registry.json"
        family["freshness"] = {"mode":"json_field","field":"reviewed_at","max_age_days":14,"severity":"warning"}
        report = self.report()
        self.assertEqual("PASS", report["status"])
        self.assertIn("stale-canonical-source", {f["code"] for f in report["findings"]})
        self.assertEqual("2026-09-07", self.agents["reviewed_at"])

    def test_future_freshness_is_refused_in_both_supported_formats(self):
        family = self.knowledge["fact_families"][0]
        for mode in ("json_field", "date_line"):
            with self.subTest(mode=mode):
                family["canonical_path"] = "freshness.json" if mode=="json_field" else "freshness.md"
                family["freshness"] = {"mode":mode,"field":"reviewed_at","prefix":"Updated:","max_age_days":None,"severity":"warning"}
                if mode=="json_field": self.write("freshness.json",{"reviewed_at":"2026-10-07"})
                else: (self.root/"freshness.md").write_text("Updated: 2026-10-07\n",encoding="utf-8")
                self.assertEqual("REFUSED",self.report()["status"])

    def test_contradictory_allowed_and_forbidden_outputs_are_refused(self):
        self.policy["autonomy_boundaries"]["automatic_outputs_allowed"].append("runtime_deployment")
        self.assertEqual("REFUSED",self.report()["status"])

    def test_executable_cadence_is_refused_even_with_a_safe_default(self):
        self.policy["cadence"][0]["authority"] = "bounded_execute"
        self.assertEqual("REFUSED",self.report()["status"])

    def test_read_only_cadence_cannot_declare_forbidden_outputs(self):
        self.policy["cadence"][0]["outputs"] = ["runtime_deployment"]
        self.assertEqual("REFUSED",self.report()["status"])

    def test_knowledge_changed_after_reference_check_cannot_publish_pass(self):
        original = audit.check_agents
        def mutate(*args,**kwargs):
            result = original(*args,**kwargs)
            target = self.root/"knowledge/project/goal.md"
            target.write_bytes(target.read_bytes()+b"\nConcurrent revision.\n")
            return result
        with patch.object(audit,"check_agents",side_effect=mutate):
            self.assertEqual("REFUSED",self.report()["status"])

    def test_missing_boundary_and_invalid_registry_refuse(self):
        self.policy["autonomy_boundaries"]["automatic_outputs_forbidden"].remove("human_approval")
        self.assertEqual("REFUSED", self.report()["status"])
        self.write("governance/audit-policy.json", [])
        self.assertEqual("REFUSED", audit.build_report(self.root, AS_OF)["status"])

    def test_excluded_directories_are_pruned_and_links_not_followed(self):
        nested = self.root / "generated" / "nested"
        nested.mkdir(parents=True)
        (nested / "ignored.json").write_text("{}", encoding="utf-8")
        self.assertFalse(any(p.startswith("generated/") for p in audit.inventory(self.root,["*"],["generated/**"])))
        link = self.root / "directory-link"
        try:
            link.symlink_to(nested, target_is_directory=True)
        except OSError:
            self.skipTest("directory symlink unavailable")
        self.assertNotIn("directory-link/ignored.json", audit.inventory(self.root,["*"],[]))

    def test_cli_refuses_missing_inputs_and_does_not_reflect_path(self):
        result = subprocess.run([sys.executable,str(ROOT/"tools/audit_control_plane.py"),"--root",str(self.root),"--as-of","secret-marker"],capture_output=True,timeout=20)
        self.assertNotEqual(0,result.returncode)
        self.assertNotIn(b"secret-marker", result.stdout)
        self.assertEqual("REFUSED",json.loads(result.stdout)["status"])

    def test_schema_and_markdown_are_closed(self):
        for name in ("knowledge-registry","agent-registry","audit-policy"):
            Draft202012Validator.check_schema(json.loads((ROOT/f"schemas/{name}.schema.json").read_text(encoding="utf-8")))
        report = self.report()
        report["findings"] = [{"severity":"error","code":"untrusted","message":"<script> [click](https://invalid.example) `x`","source":"fixture"}]
        rendered = audit.to_markdown(report)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("[click](", rendered)


if __name__ == "__main__":
    unittest.main()
