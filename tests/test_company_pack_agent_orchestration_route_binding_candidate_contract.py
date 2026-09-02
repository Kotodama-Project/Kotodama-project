import copy
import json
import runpy
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "company-pack-agent-orchestration-route-binding-candidate.schema.json"
DOC = ROOT / "docs" / "AGENT-ORCHESTRATION-ROUTE-BINDING-CANDIDATE.md"
VALIDATOR = ROOT / "tools" / "validate_company_pack_agent_orchestration_route_binding_candidate.py"
MATRIX = ROOT / "docs" / "SCHEMA-VALIDATOR-MATRIX.md"

STOP_CONDITIONS = [
    "source_target_mismatch",
    "workspace_or_revision_drift",
    "route_policy_drift",
    "preview_stale_or_expired",
    "confirmation_missing_or_mismatch",
    "external_effect_detected",
    "operation_replay_conflict",
]
REVIEW_TRIGGERS = [
    "source_or_target_identity_change",
    "workspace_or_revision_change",
    "route_policy_or_allowed_action_change",
    "candidate_manifest_or_preview_change",
    "clock_or_expiry_change",
    "rollback_or_stop_condition_change",
    "confirmation_or_authority_change",
    "schema_change",
    "request_expiry",
]
CLAIMS = {
    "route_verified",
    "source_target_correlated",
    "workspace_binding_verified",
    "revision_current_verified",
    "candidate_manifest_verified",
    "preview_verified",
    "confirmation_verified",
    "reobserve_verified",
    "replay_prevented",
    "dispatch_executed",
    "external_effect_authorized",
    "external_effect_executed",
    "human_decision_verified",
    "work_order_authority_granted",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}


def binding(seed: str, byte_count: int = 64) -> dict:
    return {"sha256": seed * 64, "bytes": byte_count}


def ref(name: str) -> str:
    return f"ref/{name}"


def task(prefix: str) -> dict:
    return {
        "task_ref": ref(f"task/{prefix}"),
        "thread_ref": ref(f"thread/{prefix}"),
        "host_ref": ref(f"host/{prefix}"),
        "title_ref": ref(f"title/{prefix}"),
        "workspace_ref": ref(f"workspace/{prefix}"),
        "workspace_binding": binding("1" if prefix == "source" else "2", 4096),
    }


def candidate(*, refused: bool = False) -> dict:
    return {
        "kind": "company_pack_agent_orchestration_route_binding_candidate",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "route_state": "REFUSED_UNVERIFIED" if refused else "ROUTE_DEFINED_UNVERIFIED",
        "route_id_ref": ref("route/internal-handoff/rb-01"),
        "operation_id_ref": ref("operation/rb-01"),
        "source_task": task("source"),
        "target_task": task("target"),
        "resource_binding": {
            "repository_ref": ref("repository/kotodama-project"),
            "public_revision": "a" * 40,
            "candidate_manifest_binding": binding("3", 1024),
            "resource_scope_ref": ref("scope/public-preview"),
            "verification_status": "NOT_VERIFIED",
        },
        "route_policy": {
            "allowed_action": "INTERNAL_AGENT_HANDOFF",
            "effect_class": "INTERNAL_CANDIDATE_ONLY",
            "expected_effects": ["INTERNAL_CANDIDATE_RECORD_ONLY"],
            "source_target_correlation_ref": ref("correlation/root-to-child/rb-01"),
            "route_policy_ref": ref("route-policy/internal-candidate-only"),
            "route_policy_binding": binding("4", 256),
            "external_effects_allowed": False,
            "provider_effects_allowed": False,
            "device_effects_allowed": False,
            "public_effects_allowed": False,
            "verification_status": "NOT_VERIFIED",
        },
        "preview": {
            "preview_binding": binding("5", 512),
            "observed_at": "2026-08-16T09:01:00+09:00",
            "expires_at": "2026-08-16T09:30:00+09:00",
            "preview_status": "PREVIEW_RECORDED_UNVERIFIED",
            "confirmation_required": True,
            "verification_status": "NOT_VERIFIED",
        },
        "confirmation": {
            "confirmation_ref": None,
            "confirmation_binding": None,
            "confirmation_status": "NOT_CONFIRMED",
            "human_gate": False,
            "verification_status": "NOT_VERIFIED",
        },
        "failure_and_rollback": {
            "stop_conditions": STOP_CONDITIONS,
            "rollback_policy_ref": ref("rollback/route-binding"),
            "rollback_policy_binding": binding("6", 256),
            "rollback_receipt_ref": None,
            "rollback_receipt_binding": None,
            "failure_state": "REFUSED_UNVERIFIED" if refused else "NOT_EXECUTED",
            "no_external_effects_expected": True,
            "execution_receipt_ref": None,
            "verification_status": "NOT_VERIFIED",
        },
        "recorded_at": "2026-08-16T09:00:00+09:00",
        "expires_at": "2026-08-16T09:31:00+09:00",
        "review_trigger": REVIEW_TRIGGERS,
        "claims": {name: False for name in CLAIMS},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


class AgentOrchestrationRouteBindingCandidateContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema, format_checker=FormatChecker())

    def assert_valid(self, instance: dict) -> None:
        errors = list(self.validator.iter_errors(instance))
        self.assertEqual(errors, [], [error.message for error in errors])

    def assert_invalid(self, instance: dict, name: str) -> None:
        self.assertTrue(list(self.validator.iter_errors(instance)), name)

    def run_cli(self, instance: dict) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_text(json.dumps(instance), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
        return result.returncode, json.loads(result.stdout)

    def test_draft_2020_schema_accepts_defined_and_refused_candidates(self) -> None:
        self.assert_valid(candidate())
        self.assert_valid(candidate(refused=True))

    def test_schema_is_closed_and_all_claims_are_false(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.schema["properties"]["status"]["const"], "CANDIDATE_ONLY")
        self.assertEqual(self.schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        claims = self.schema["$defs"]["claims"]
        self.assertFalse(claims["additionalProperties"])
        self.assertEqual(set(claims["required"]), CLAIMS)
        self.assertTrue(all(spec["const"] is False for spec in claims["properties"].values()))

    def test_hostile_authority_effect_and_private_ref_mutations_are_rejected(self) -> None:
        base = candidate()
        cases = {}

        mutated = copy.deepcopy(base)
        mutated["status"] = "VERIFIED"
        cases["verified status"] = mutated
        mutated = copy.deepcopy(base)
        mutated["route_policy"]["public_effects_allowed"] = True
        cases["public effect"] = mutated
        mutated = copy.deepcopy(base)
        mutated["confirmation"]["human_gate"] = True
        cases["human gate"] = mutated
        mutated = copy.deepcopy(base)
        mutated["claims"]["dispatch_executed"] = True
        cases["dispatch claim"] = mutated
        mutated = copy.deepcopy(base)
        mutated["source_task"]["workspace_ref"] = r"C:\private\workspace"
        cases["physical workspace"] = mutated
        mutated = copy.deepcopy(base)
        mutated["route_id_ref"] = "file:///private/route"
        cases["file route ref"] = mutated
        mutated = copy.deepcopy(base)
        mutated["route_policy"]["allowed_action"] = "LOCAL_CANDIDATE_DISPATCH"
        cases["public dispatch alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["failure_and_rollback"]["stop_conditions"].reverse()
        cases["stop condition reorder"] = mutated

        for name, instance in cases.items():
            with self.subTest(name=name):
                self.assert_invalid(instance, name)

    def test_schema_and_cli_reject_the_same_hostile_structural_mutations(self) -> None:
        cases = []
        mutated = candidate()
        mutated["route_policy"]["public_effects_allowed"] = True
        cases.append(mutated)
        mutated = candidate()
        mutated["confirmation"]["human_gate"] = True
        cases.append(mutated)
        mutated = candidate()
        mutated["claims"]["dispatch_executed"] = True
        cases.append(mutated)
        mutated = candidate()
        mutated["source_task"]["task_ref"] = "file:///private/task"
        cases.append(mutated)
        mutated = candidate()
        mutated["preview"]["observed_at"] = "not-a-timestamp"
        cases.append(mutated)

        for index, instance in enumerate(cases):
            with self.subTest(index=index):
                self.assertTrue(list(self.validator.iter_errors(instance)))
                code, report = self.run_cli(instance)
                self.assertEqual(code, 2)
                self.assertIn("SCHEMA_INVALID", report["reason_codes"])

    def test_cli_keeps_a_refused_candidate_refused(self) -> None:
        code, report = self.run_cli(candidate(refused=True))
        self.assertEqual(code, 2)
        self.assertEqual(report["result"], "REFUSED")
        self.assertIn("CANDIDATE_MARKED_REFUSED", report["reason_codes"])

    def test_cli_rejects_a_refused_failure_state_on_a_defined_route(self) -> None:
        mutated = candidate()
        mutated["failure_and_rollback"]["failure_state"] = "REFUSED_UNVERIFIED"
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("CANDIDATE_MARKED_REFUSED", report["reason_codes"])

    def test_cli_returns_unverified_candidate_only_result(self) -> None:
        code, report = self.run_cli(candidate())
        self.assertEqual(code, 0)
        self.assertEqual(report["result"], "PRECONDITIONS_MATCH_UNVERIFIED")
        self.assertEqual(report["status"], "CANDIDATE_ONLY")
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertTrue(all(value is False for value in report["claims"].values()))

    def test_cli_rejects_identity_collision_and_route_operation_alias(self) -> None:
        mutated = candidate()
        mutated["target_task"]["task_ref"] = mutated["source_task"]["task_ref"]
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("SOURCE_TARGET_IDENTITY_COLLISION", report["reason_codes"])

        mutated = candidate()
        mutated["operation_id_ref"] = mutated["route_id_ref"]
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("ROUTE_OPERATION_ID_COLLISION", report["reason_codes"])

    def test_cli_rejects_stale_or_unbounded_preview_window(self) -> None:
        mutated = candidate()
        mutated["preview"]["observed_at"] = "2026-08-16T09:31:00+09:00"
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("PREVIEW_WINDOW_ORDER_INVALID", report["reason_codes"])

        mutated = candidate()
        mutated["preview"]["expires_at"] = "2026-08-18T09:30:00+09:00"
        mutated["expires_at"] = "2026-08-19T09:31:00+09:00"
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("PREVIEW_WINDOW_UNBOUNDED", report["reason_codes"])

    def test_cli_rejects_duplicate_keys_and_oversized_input(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text('{"kind": "one", "kind": "two"}', encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("INPUT_INVALID", json.loads(result.stdout)["reason_codes"])

            path.write_bytes(b"{" + b"a" * (1_048_576 + 1) + b"}")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("INPUT_TOO_LARGE", json.loads(result.stdout)["reason_codes"])

    def test_cli_checks_input_size_before_unbounded_path_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b"{" + b"a" * (1_048_576 + 1) + b"}")
            module = runpy.run_path(str(VALIDATOR))
            output = StringIO()
            with patch.object(Path, "read_bytes", side_effect=AssertionError("full read forbidden")):
                with redirect_stdout(output):
                    code = module["main"]([str(VALIDATOR), str(path)])

        self.assertEqual(code, 2)
        self.assertIn("INPUT_TOO_LARGE", json.loads(output.getvalue())["reason_codes"])

    def test_cli_converts_excessive_json_nesting_to_structured_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deep.json"
            path.write_text('{"a":' * 20_000 + "0" + "}" * 20_000, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
            )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["result"], "REFUSED")
        self.assertIn("INPUT_INVALID", report["reason_codes"])

    def test_cli_reports_schema_match_for_semantic_refusal(self) -> None:
        mutated = candidate()
        mutated["preview"]["expires_at"] = "2026-08-18T09:30:00+09:00"
        mutated["expires_at"] = "2026-08-19T09:31:00+09:00"
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("PREVIEW_WINDOW_UNBOUNDED", report["reason_codes"])
        self.assertEqual(report["checks"]["schema"], "MATCH")

    def test_public_navigation_exposes_candidate_without_runtime_claim(self) -> None:
        self.assertTrue(DOC.is_file())
        doc = DOC.read_text(encoding="utf-8")
        for marker in (
            "source_task",
            "target_task",
            "workspace / revision",
            "PRECONDITIONS_MATCH_UNVERIFIED",
            "NO_GO_UNPUBLISHED",
            "Codex transport",
            "subagent",
            "Promotion",
            "Current Truth",
            "CANDIDATE_MARKED_REFUSED",
            "VALIDATOR_UNAVAILABLE",
            "requirements-test.txt",
        ):
            self.assertIn(marker, doc)

        matrix = MATRIX.read_text(encoding="utf-8")
        for marker in (
            "Agent orchestration route-binding candidate",
            "company-pack-agent-orchestration-route-binding-candidate.schema.json",
            "validate_company_pack_agent_orchestration_route_binding_candidate.py",
            "test_company_pack_agent_orchestration_route_binding_candidate_contract.py",
            "read-only",
            "candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            self.assertIn(marker, matrix)


if __name__ == "__main__":
    unittest.main()
