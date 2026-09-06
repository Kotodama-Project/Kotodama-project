"""Guard public projection contracts; regex checks supplement semantic privacy review."""
from pathlib import Path
import json
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    "docs/CONTEXT-AND-AGENT-RESPONSIBILITY.md",
    "docs/CONTEXT-ARCHITECTURE-REVIEW-2026-09-06.md",
    "docs/OPERATING-POLICY-2026-09-06.md",
]


class ContextPolicyProjectionTests(unittest.TestCase):
    def setUp(self):
        self.policy = json.loads((ROOT / "docs/operating-policy.json").read_text(encoding="utf-8"))

    def test_owners_and_initiatives_resolve_without_claiming_activation(self):
        self.assertEqual("1.6.0", self.policy["policy_version"])
        roles = {role["id"] for role in self.policy["agent_roles"]}
        responsibility = self.policy["agent_responsibility_policy"]
        domain_owners = {owner["role_ref"] for owner in responsibility["owners"]}
        self.assertLessEqual(domain_owners, roles)
        goals = self.policy["goal_reference_definitions"]
        outcomes = {item["id"] for item in goals["outcomes"]}
        kpis = {item["id"] for item in goals["kpis"]}
        kgis = {item["id"] for item in goals["kgis"]}
        for metric in goals["kpis"]:
            self.assertLessEqual(set(metric["outcome_refs"]), outcomes)
            self.assertLessEqual(set(metric["kgi_refs"]), kgis)
        rows = self.policy["initiatives"]
        self.assertEqual(len(rows), len({row["id"] for row in rows}))
        self.assertEqual(9, len(rows))
        page = (ROOT / DOCS[0]).read_text(encoding="utf-8")
        for row in rows:
            self.assertEqual("pending", row["status"])
            self.assertTrue(row["acceptance"])
            self.assertIn(row["id"], page)
            self.assertIn(row["accountable_role_ref"], domain_owners)
            self.assertLessEqual(set(row["collaborator_role_refs"]), roles)
            self.assertNotIn(row["accountable_role_ref"], row["collaborator_role_refs"])
            self.assertIn(row["independent_review_role_ref"], roles)
            self.assertTrue(row["independent_runtime_identity_required"])
            self.assertEqual("pending", row["runtime_owner_binding_status"])
            self.assertLessEqual(set(row["outcome_refs"]), outcomes)
            self.assertLessEqual(set(row["kpi_refs"]), kpis)
        self.assertFalse(responsibility["runtime_agents_started_by_this_policy"])
        self.assertEqual("policy_and_required_contract_only_not_deployed",
                         self.policy["dynamic_agent_context_policy"]["runtime_status"])

    def test_intent_authority_and_review_boundaries_remain_explicit(self):
        context = self.policy["intent_context_policy"]
        self.assertFalse(context["metric_guard"]["kpi_improvement_alone_proves_success"])
        self.assertIn("original_intent_and_correction_chain", context["retained_context"])
        self.assertTrue(context["independent_audit"]["required_every_session_and_logical_work_cycle"])
        self.assertTrue(context["independent_audit"]["reviewer_distinct_from_executor"])
        dynamic = self.policy["dynamic_agent_context_policy"]
        self.assertTrue(dynamic["trust_boundary"]["fixed_authority_rules_not_overwritten_by_generated_context"])
        self.assertTrue(dynamic["refresh_policy"]["no_rebuild_when_inputs_and_evidence_unchanged"])
        self.assertFalse(self.policy["usage_approval_policy"]["subsequent_human_reapproval_required"])
        review = (ROOT / DOCS[1]).read_text(encoding="utf-8")
        self.assertIn("review proposals", review)
        self.assertIn("三実験は未実施", review)

    def test_public_projection_has_no_private_locators_or_session_identity(self):
        paths = DOCS + ["AGENTS.md", "README.md", "STATUS.md", "ROADMAP.md",
                        "docs/PROJECT-MAP.md", "docs/acceptance/requirements.json",
                        "docs/operating-policy.json"]
        denied = r"(?i)(?:[a-z]:[\\/](?:users|codexwork)|/home/|\.codex[\\/]|chatgpt\.com/(?:c|share)/|rollout-[^\s\"<>]+\.jsonl|KTP-TASK-\d+|source_evidence_ref.*(?:\.jsonl|[\\/]work[\\/]))"
        for path in paths:
            with self.subTest(path=path):
                text = (ROOT / path).read_text(encoding="utf-8")
                self.assertNotRegex(text, denied)
        self.assertNotIn("historical_reconciliation_ref", json.dumps(self.policy))

    def test_new_document_links_stay_in_repository_or_public_https(self):
        for path in DOCS:
            file = ROOT / path
            for target in re.findall(r"\]\(([^)]+)\)", file.read_text(encoding="utf-8")):
                if target.startswith("https://"):
                    continue
                resolved = (file.parent / target.partition("#")[0]).resolve()
                self.assertTrue(resolved.is_relative_to(ROOT))
                self.assertTrue(resolved.is_file(), f"{path}: {target}")


if __name__ == "__main__":
    unittest.main()
