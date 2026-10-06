from datetime import date
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import plan_control_plane_maintenance as planner
from audit_control_plane import load_bundle


class ControlPlanePlannerTest(unittest.TestCase):
    def test_actual_warning_becomes_deterministic_proposal_without_mutation(self):
        paths = [ROOT/f"governance/{name}.json" for name in ("knowledge-registry","agent-registry","audit-policy")]
        before = [p.read_bytes() for p in paths]
        value = planner.plan(ROOT,date(2026,10,6))
        self.assertEqual(value,planner.plan(ROOT,date(2026,10,6)))
        self.assertEqual(before,[p.read_bytes() for p in paths])
        self.assertGreater(value["candidate_work_count"],0)
        self.assertFalse(any(value["claims"].values()))
        work = value["candidate_work"]
        self.assertTrue(all(item["authority"]=="proposal_only" for item in work))
        self.assertTrue(all(item["assigned_agent_role"]=="AI-LIBRARIAN" for item in work if item["source_finding"]["code"]=="stale-canonical-source"))

    def test_every_routing_reference_resolves_to_current_knowledge(self):
        ids = {c.concept_id for c in load_bundle(ROOT).concepts}
        self.assertTrue(all(ref in ids for refs in planner.ROLE_LINKS.values() for ref in refs))
        self.assertNotIn("okf-steward",planner.ROLE_LINKS)
        self.assertEqual("AI-AUDITOR",planner.assign_role("autonomy-boundary-gap"))
        self.assertEqual("AI-AUDITOR",planner.assign_role("forbidden-cadence-output"))
        self.assertIn("Promotion stop",planner.next_action({"code":"autonomy-boundary-gap"},"AI-AUDITOR"))

    def test_changed_evidence_cannot_reuse_proposal_identity(self):
        a = {"code":"stale-canonical-source","severity":"warning","message":"same","evidence":{"revision":1}}
        b = {**a,"evidence":{"revision":2}}
        self.assertNotEqual(planner.candidate_id(a),planner.candidate_id(b))
        self.assertEqual(planner.candidate_id(a),planner.candidate_id(dict(reversed(list(a.items())))))

    def test_invalid_clock_cli_refuses_without_reflecting_input(self):
        result = subprocess.run([sys.executable,str(ROOT/"tools/plan_control_plane_maintenance.py"),"--as-of","private-marker"],capture_output=True,timeout=20)
        self.assertEqual(2,result.returncode)
        self.assertEqual("REFUSED",json.loads(result.stdout)["status"])
        self.assertNotIn(b"private-marker",result.stdout+result.stderr)

    def test_refused_audit_keeps_critical_finding_and_escaped_output(self):
        report = {"status":"REFUSED","summary":{"critical":1},"findings":[{"code":"autonomy-boundary-gap","severity":"critical","message":"<script> [x](https://invalid.example)"}]}
        with patch.object(planner,"build_report",return_value=report):
            value = planner.plan(ROOT,date(2026,10,6))
        self.assertEqual("REFUSED",value["source_audit_status"])
        self.assertEqual("critical",value["candidate_work"][0]["priority"])
        self.assertFalse(any(value["claims"].values()))
        self.assertNotIn("<script>",planner.markdown(value))
        self.assertNotIn("[x](",planner.markdown(value))

    def test_optional_workflow_is_focused_read_only_and_hash_locked(self):
        text = (ROOT/".github/workflows/control-plane-audit.yml").read_text(encoding="utf-8")
        self.assertIn("paths:",text)
        self.assertIn("contents: read",text)
        self.assertIn("--require-hashes -r requirements-ci.txt",text)
        self.assertNotIn("unittest discover",text)
        self.assertNotIn("pull_request_target",text)
        self.assertNotIn("schedule:",text)


if __name__ == "__main__":
    unittest.main()
