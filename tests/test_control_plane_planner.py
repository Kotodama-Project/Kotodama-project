from datetime import date
import json
import shlex
from pathlib import Path
import subprocess
import sys
import tempfile
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

    def test_cli_rejects_symlink_selected_root_without_following_it(self):
        with tempfile.TemporaryDirectory() as directory:
            link=Path(directory).resolve()/"repo-link"
            try:
                link.symlink_to(ROOT,target_is_directory=True)
            except OSError:
                self.skipTest("directory symlink unavailable")
            for tool in ("plan_control_plane_maintenance.py","audit_control_plane.py"):
                with self.subTest(tool=tool):
                    result=subprocess.run([sys.executable,str(ROOT/"tools"/tool),"--root",str(link),"--as-of","2026-10-06"],capture_output=True,timeout=20)
                    self.assertEqual(2,result.returncode,result.stdout)
                    self.assertEqual("REFUSED",json.loads(result.stdout)["status"])
                    self.assertNotIn(str(link).encode(),result.stdout+result.stderr)

    def test_unc_root_is_refused_before_any_filesystem_probe(self):
        with patch.object(Path,"exists",side_effect=AssertionError("network probe")), patch.object(Path,"lstat",side_effect=AssertionError("network probe")):
            with self.assertRaisesRegex(ValueError,"ROOT_REFUSED"):
                planner.plan(Path("//invalid.example/share"),date(2026,10,6))

    def test_markdown_preserves_origin_and_actionable_evidence_as_inert_text(self):
        finding={"code":"inventory-coverage","severity":"error","message":"unclassified files",
                 "source":"PUBLICREGISTRY","evidence":{"uncovered":["AFFECTEDFILE", "![fetch](https://example.invalid/pixel)<script>\n# heading"]}}
        with patch.object(planner,"build_report",return_value={"status":"REFUSED","summary":{"error":1},"findings":[finding]}):
            value=planner.plan(ROOT,date(2026,10,6))
        text=planner.markdown(value)
        self.assertIn("PUBLICREGISTRY",text);self.assertIn("AFFECTEDFILE",text)
        self.assertNotIn("![fetch](",text);self.assertNotIn("<script>",text);self.assertNotIn("\n# heading",text)

    def test_plan_explicitly_disclaims_every_human_and_promotion_outcome(self):
        with patch.object(planner,"build_report",return_value={"status":"PASS","summary":{},"findings":[]}):
            claims=planner.plan(ROOT,date(2026,10,6))["claims"]
        for name in ("human_approval_created","promotion_created","final_human_go_created"):
            with self.subTest(claim=name):
                self.assertIs(claims.get(name),False)

    def test_invalid_clock_cli_refuses_without_reflecting_input(self):
        result = subprocess.run([sys.executable,str(ROOT/"tools/plan_control_plane_maintenance.py"),"--as-of","private-marker"],capture_output=True,timeout=20)
        self.assertEqual(2,result.returncode)
        self.assertEqual("REFUSED",json.loads(result.stdout)["status"])
        self.assertNotIn(b"private-marker",result.stdout+result.stderr)

    def test_real_cli_preserves_missing_registry_findings_as_proposals(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable,str(ROOT/"tools/plan_control_plane_maintenance.py"),"--root",directory,"--as-of","2026-10-06"],capture_output=True,timeout=20)
            self.assertEqual(0,result.returncode)
            value = json.loads(result.stdout)
            self.assertEqual("REFUSED",value["source_audit_status"])
            self.assertTrue(any(item["source_finding"]["code"]=="missing-registry" for item in value["candidate_work"]))
            self.assertTrue(all(item["authority"]=="proposal_only" for item in value["candidate_work"]))
            self.assertFalse(any(value["claims"].values()))

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
        for line in text.splitlines():
            if "unittest discover" in line:
                command = shlex.split(line.split("run:", 1)[-1])
                self.assertIn("-p",command)
                self.assertEqual(command[command.index("-p")+1],"test_agent_status*.py")
        self.assertNotIn("pull_request_target",text)
        self.assertNotIn("schedule:",text)


if __name__ == "__main__":
    unittest.main()
