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
SCHEMA = ROOT / "schemas" / "company-pack-agent-swarm-execution-candidate.schema.json"
DOC = ROOT / "docs" / "AGENT-SWARM-KOTODAMA-ADOPTION-CANDIDATE.md"
VALIDATOR = ROOT / "tools" / "validate_company_pack_agent_swarm_execution_candidate.py"
MATRIX = ROOT / "docs" / "SCHEMA-VALIDATOR-MATRIX.md"

STOP_CONDITIONS = [
    "parent_edge_mismatch",
    "assignment_identity_mismatch",
    "workspace_or_revision_drift",
    "handoff_binding_mismatch",
    "lease_expired_or_epoch_drift",
    "child_timeout_or_cancel",
    "output_binding_missing",
    "external_effect_detected",
]
REVIEW_TRIGGERS = [
    "root_orchestrator_identity_change",
    "budget_or_wave_change",
    "assignment_role_objective_or_ownership_change",
    "parent_edge_or_handoff_change",
    "workspace_or_revision_change",
    "lease_ttl_epoch_or_dedup_change",
    "stop_condition_or_expected_output_change",
    "verifier_reserve_or_acceptance_change",
    "schema_change",
    "request_expiry",
]
CLAIMS = {
    "plan_verified",
    "budget_verified",
    "orchestrator_identity_verified",
    "parent_edges_verified",
    "assignment_identity_verified",
    "workspace_binding_verified",
    "revision_current_verified",
    "handoff_verified",
    "lease_fencing_verified",
    "replay_prevented",
    "all_assignments_completed",
    "swarm_runtime_verified",
    "dispatch_executed",
    "external_effect_authorized",
    "external_effect_executed",
    "human_decision_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
}


def binding(seed: str, byte_count: int = 64) -> dict:
    return {"sha256": seed * 64, "bytes": byte_count}


def ref(name: str) -> str:
    return f"ref/{name}"


def handoff(source: str, target: str, seed: str) -> dict:
    return {
        "handoff_ref": ref(f"handoff/{seed}"),
        "source_attempt_ref": source,
        "target_attempt_ref": target,
        "input_binding": binding(seed, 128),
        "expected_output_binding": binding(seed, 256),
        "handoff_state": "HANDOFF_DEFINED_UNVERIFIED",
        "confirmation": False,
        "verification_status": "NOT_VERIFIED",
    }


def lease(seed: str) -> dict:
    return {
        "ttl_seconds": 1_800,
        "epoch": 1,
        "dedup_key_ref": ref(f"dedup/{seed}"),
        "retry_owner_ref": ref("agent/root-orchestrator"),
        "cancel_reason_ref": None,
        "verification_status": "NOT_VERIFIED",
    }


def expected_output(kind: str, name: str) -> dict:
    return {
        "output_kind": kind,
        "expected_output_ref": ref(f"output/{name}"),
        "result_ref": None,
        "receipt_binding": None,
        "acceptance_status": "PENDING_UNVERIFIED",
        "verification_status": "NOT_VERIFIED",
    }


def assignment(
    *,
    attempt: str,
    parent: str | None,
    edge: str,
    kind: str,
    source: str,
    target: str,
    depth: int,
    wave: int,
    planned_children: list[str],
    dependencies: list[str],
    handoff_target: str,
    lease_key: str,
    output_kind: str,
    output_name: str,
    seed: str,
) -> dict:
    return {
        "attempt_ref": ref(attempt),
        "parent_attempt_ref": None if parent is None else ref(parent),
        "parent_edge_ref": ref(edge),
        "role_ref": ref(f"role/{kind.lower()}"),
        "kind": kind,
        "objective_ref": ref(f"objective/{attempt}"),
        "ownership_ref": ref(f"ownership/{attempt}"),
        "source_task_ref": ref(f"task/{source}"),
        "target_task_ref": ref(f"task/{target}"),
        "workspace_ref": ref("workspace/public-kotodama-candidate"),
        "workspace_binding": binding("a", 4096),
        "public_revision": "b" * 40,
        "candidate_binding": binding(seed, 1024),
        "depth": depth,
        "wave": wave,
        "dependencies": [ref(item) for item in dependencies],
        "planned_child_attempt_refs": [ref(item) for item in planned_children],
        "may_spawn_descendants": False,
        "descendant_budget": 0,
        "handoff": handoff(ref(attempt), ref(handoff_target), seed),
        "lease": lease(lease_key),
        "stop_conditions": STOP_CONDITIONS,
        "expected_output": expected_output(output_kind, output_name),
        "assignment_state": "PLANNED_UNVERIFIED",
        "external_effects_allowed": False,
        "provider_effects_allowed": False,
        "device_effects_allowed": False,
        "public_effects_allowed": False,
        "verification_status": "NOT_VERIFIED",
    }


def candidate(*, refused: bool = False) -> dict:
    root_attempt = ref("attempt/root-builder")
    verifier_attempt = ref("attempt/verifier")
    return {
        "kind": "company_pack_agent_swarm_execution_candidate",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "swarm_state": "REFUSED_UNVERIFIED" if refused else "PLAN_DEFINED_UNVERIFIED",
        "swarm_id_ref": ref("swarm/public-candidate-01"),
        "root_task_ref": ref("task/root"),
        "root_operation_ref": ref("operation/root-01"),
        "orchestrator": {
            "agent_ref": ref("agent/root-orchestrator"),
            "role_ref": ref("role/orchestrator"),
            "task_ref": ref("task/root"),
            "thread_ref": ref("thread/root-01"),
            "workspace_ref": ref("workspace/public-kotodama-candidate"),
            "workspace_binding": binding("a", 4096),
            "model_ref": ref("model/unverified-luna"),
            "model_verification_status": "NOT_VERIFIED",
        },
        "budget": {
            "attempt_budget_N": 4,
            "concurrency_cap_C": 4,
            "wave_width_W": 2,
            "max_workflow_depth": 2,
            "verifier_reserve_V": 1,
            "external_effects_allowed": False,
            "provider_effects_allowed": False,
            "device_effects_allowed": False,
            "public_effects_allowed": False,
            "verification_status": "NOT_VERIFIED",
        },
        "root_policy": {
            "orchestration_pattern": "CODE_BOUNDED_PARALLEL",
            "final_integrator": "ROOT_ORCHESTRATOR_ONLY",
            "shared_writer": "ROOT_ONLY",
            "allowed_action": "INTERNAL_AGENT_HANDOFF",
            "expected_effects": ["INTERNAL_CANDIDATE_RECORD_ONLY"],
            "human_gate": False,
            "verification_status": "NOT_VERIFIED",
        },
        "assignments": [
            assignment(
                attempt="attempt/root-builder",
                parent=None,
                edge="edge/root",
                kind="BUILDER",
                source="root",
                target="builder",
                depth=1,
                wave=1,
                planned_children=["attempt/verifier"],
                dependencies=[],
                handoff_target="attempt/verifier",
                lease_key="root",
                output_kind="CHANGE_CANDIDATE",
                output_name="root-builder",
                seed="c",
            ),
            assignment(
                attempt="attempt/verifier",
                parent="attempt/root-builder",
                edge="edge/root-to-verifier",
                kind="VERIFIER",
                source="builder",
                target="verifier",
                depth=2,
                wave=2,
                planned_children=[],
                dependencies=["attempt/root-builder"],
                handoff_target="attempt/root-builder",
                lease_key="verifier",
                output_kind="REVIEW_REPORT",
                output_name="verifier",
                seed="d",
            ),
        ],
        "recorded_at": "2026-08-17T00:30:00+09:00",
        "expires_at": "2026-08-17T01:30:00+09:00",
        "review_trigger": REVIEW_TRIGGERS,
        "claims": {name: False for name in CLAIMS},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


class AgentSwarmExecutionCandidateContractTests(unittest.TestCase):
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

    def test_schema_is_closed_and_effects_claims_are_false(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertEqual(self.schema["$defs"]["stop_conditions"]["minItems"], 8)
        claims = self.schema["$defs"]["claims"]
        self.assertFalse(claims["additionalProperties"])
        self.assertEqual(set(claims["required"]), CLAIMS)
        self.assertTrue(all(spec["const"] is False for spec in claims["properties"].values()))

    def test_hostile_authority_and_identity_mutations_are_rejected(self) -> None:
        cases = {}
        mutated = copy.deepcopy(candidate())
        mutated["status"] = "VERIFIED"
        cases["verified status"] = mutated
        mutated = copy.deepcopy(candidate())
        mutated["budget"]["public_effects_allowed"] = True
        cases["public effect"] = mutated
        mutated = copy.deepcopy(candidate())
        mutated["root_policy"]["human_gate"] = True
        cases["human gate"] = mutated
        mutated = copy.deepcopy(candidate())
        mutated["claims"]["swarm_runtime_verified"] = True
        cases["runtime claim"] = mutated
        mutated = copy.deepcopy(candidate())
        mutated["orchestrator"]["workspace_ref"] = r"C:\private\workspace"
        cases["physical workspace"] = mutated
        mutated = copy.deepcopy(candidate())
        mutated["swarm_id_ref"] = "file:///private/swarm"
        cases["file swarm ref"] = mutated
        mutated = copy.deepcopy(candidate())
        mutated["assignments"][1]["may_spawn_descendants"] = True
        cases["descendant spawn"] = mutated
        for name, instance in cases.items():
            with self.subTest(name=name):
                self.assert_invalid(instance, name)

    def test_cli_returns_unverified_candidate_only_result(self) -> None:
        code, report = self.run_cli(candidate())
        self.assertEqual(code, 0)
        self.assertEqual(report["result"], "PRECONDITIONS_MATCH_UNVERIFIED")
        self.assertEqual(report["status"], "CANDIDATE_ONLY")
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertTrue(all(value is False for value in report["claims"].values()))

    def test_cli_refuses_semantic_budget_and_edge_drift(self) -> None:
        cases = [
            ("wave width", {"budget": {"wave_width_W": 5}, "reason": "WAVE_WIDTH_EXCEEDS_CONCURRENCY"}),
            ("no verifier", {"assignments": [0], "reason": "VERIFIER_RESERVE_NOT_PLANNED"}),
            ("parent self", {"assignments": [0], "reason": "PARENT_SELF_REFERENCE"}),
            ("source target", {"assignments": [0], "reason": "ASSIGNMENT_SOURCE_TARGET_COLLISION"}),
            ("lease window", {"assignments": [0], "reason": "LEASE_EXCEEDS_REQUEST_WINDOW"}),
        ]
        for name, mutation in cases:
            with self.subTest(name=name):
                instance = copy.deepcopy(candidate())
                if name == "wave width":
                    instance["budget"]["wave_width_W"] = mutation["budget"]["wave_width_W"]
                elif name == "no verifier":
                    instance["assignments"][1]["kind"] = "BUILDER"
                elif name == "parent self":
                    instance["assignments"][1]["parent_attempt_ref"] = instance["assignments"][1]["attempt_ref"]
                elif name == "source target":
                    instance["assignments"][0]["target_task_ref"] = instance["assignments"][0]["source_task_ref"]
                elif name == "lease window":
                    instance["assignments"][0]["lease"]["ttl_seconds"] = 86_400
                code, report = self.run_cli(instance)
                self.assertEqual(code, 2)
                self.assertIn(mutation["reason"], report["reason_codes"])

    def test_cli_rejects_self_referential_and_cyclic_dependencies(self) -> None:
        mutated = copy.deepcopy(candidate())
        mutated["assignments"][0]["dependencies"] = [ref("attempt/root-builder")]
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("DEPENDENCY_SELF_REFERENCE", report["reason_codes"])

        mutated = copy.deepcopy(candidate())
        mutated["assignments"][0]["dependencies"] = [ref("attempt/verifier")]
        mutated["assignments"][1]["dependencies"] = [ref("attempt/root-builder")]
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("DEPENDENCY_CYCLE", report["reason_codes"])

    def test_cli_rejects_child_declarations_that_point_back_to_the_wrong_parent(self) -> None:
        mutated = copy.deepcopy(candidate())
        mutated["assignments"][1]["planned_child_attempt_refs"] = [ref("attempt/root-builder")]
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("CHILD_PARENT_EDGE_MISMATCH", report["reason_codes"])

    def test_cli_refuses_state_and_structural_drift(self) -> None:
        code, report = self.run_cli(candidate(refused=True))
        self.assertEqual(code, 2)
        self.assertIn("CANDIDATE_MARKED_REFUSED", report["reason_codes"])

        mutated = copy.deepcopy(candidate())
        mutated["assignments"][1]["dependencies"] = [ref("attempt/unknown")]
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("DEPENDENCY_ATTEMPT_UNKNOWN", report["reason_codes"])

        mutated = copy.deepcopy(candidate())
        mutated["review_trigger"] = list(reversed(mutated["review_trigger"]))
        self.assert_invalid(mutated, "review trigger order")
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("SCHEMA_INVALID", report["reason_codes"])

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
        mutated = copy.deepcopy(candidate())
        mutated["budget"]["wave_width_W"] = 5
        code, report = self.run_cli(mutated)
        self.assertEqual(code, 2)
        self.assertIn("WAVE_WIDTH_EXCEEDS_CONCURRENCY", report["reason_codes"])
        self.assertEqual(report["checks"]["schema"], "MATCH")

    def test_public_navigation_exposes_candidate_without_runtime_claim(self) -> None:
        self.assertTrue(DOC.is_file())
        doc = DOC.read_text(encoding="utf-8")
        for marker in (
            "root orchestrator",
            "parent edge",
            "workspace / revision",
            "handoff",
            "lease",
            "PRECONDITIONS_MATCH_UNVERIFIED",
            "NO_GO_UNPUBLISHED",
            "Codex",
            "subagent",
            "Promotion",
            "Current Truth",
            "VALIDATOR_UNAVAILABLE",
            "requirements-test.txt",
        ):
            self.assertIn(marker, doc)

        matrix = MATRIX.read_text(encoding="utf-8")
        for marker in (
            "Agent swarm execution candidate",
            "company-pack-agent-swarm-execution-candidate.schema.json",
            "validate_company_pack_agent_swarm_execution_candidate.py",
            "test_company_pack_agent_swarm_execution_candidate_contract.py",
            "read-only",
            "candidate-only",
            "NO_GO_UNPUBLISHED",
        ):
            self.assertIn(marker, matrix)


if __name__ == "__main__":
    unittest.main()
