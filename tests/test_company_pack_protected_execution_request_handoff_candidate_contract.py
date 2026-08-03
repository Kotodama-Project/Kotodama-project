import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "company-pack-protected-execution-request-handoff-candidate.schema.json"
RUNBOOK = ROOT / "docs" / "PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md"

EXPECTED_PRIVATE_ROLES = [
    "source_record",
    "source_content",
    "access_consent_evidence",
    "retention_policy",
]

EXPECTED_STOP_CONDITIONS = [
    "locator_unresolved",
    "consent_or_retention_missing",
    "runner_binding_drift",
    "clock_untrusted_or_window_expired",
    "input_or_output_binding_drift",
    "external_effect_detected",
]

EXPECTED_REVIEW_TRIGGERS = [
    "source_contract_or_receipt_schema_change",
    "runner_policy_executable_configuration_or_environment_change",
    "private_locator_or_immutable_version_change",
    "clock_policy_window_or_skew_change",
    "stop_condition_or_rollback_policy_change",
    "expected_output_or_handoff_policy_change",
    "authority_consent_or_retention_change",
    "request_expiry",
]

EXPECTED_CLAIMS = {
    "execution_requested",
    "execution_accepted",
    "executed",
    "runner_verified",
    "private_snapshot_verified",
    "source_record_resolved",
    "source_content_resolved",
    "access_consent_resolved",
    "retention_policy_resolved",
    "trusted_clock_verified",
    "rollback_verified",
    "output_emitted",
    "receipt_verified",
    "source_authenticity_verified",
    "consent_verified",
    "retention_enforced",
    "deletion_enforced",
    "replay_prevented",
    "independent_verification_verified",
    "human_decision_verified",
    "work_order_authority_granted",
    "promotion_verified",
    "current_truth_changed",
    "voice_runtime_verified",
    "discord_runtime_verified",
    "provider_transfer_authorized",
    "external_transfer_authorized",
    "deploy_verified",
    "final_human_go",
    "public_beta_go",
}


def binding(seed: str, byte_count: int = 64) -> dict:
    return {"sha256": seed[0] * 64, "bytes": byte_count}


def opaque_ref(name: str) -> str:
    return f"ref/{name}"


def private_input(role: str, seed: str) -> dict:
    return {
        "role": role,
        "locator_ref": opaque_ref(f"private-locator/{role}"),
        "immutable_version_ref": opaque_ref(f"immutable-version/{role}"),
        "binding": binding(seed, 512),
        "purpose_ref": opaque_ref(f"purpose/{role}"),
        "retention_ref": opaque_ref("retention/private-source"),
        "resolution_status": "NOT_RESOLVED",
        "verification_status": "NOT_VERIFIED",
    }


def request_candidate(*, refused: bool = False) -> dict:
    return {
        "kind": "company_pack_protected_execution_request_handoff_candidate",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "request_state": "REFUSED_UNVERIFIED" if refused else "REQUEST_DEFINED_UNVERIFIED",
        "request_id_ref": opaque_ref("execution-request/r35-01"),
        "work_order": {
            "work_order_ref": opaque_ref("work-order/r35-protected-handoff"),
            "work_order_binding": binding("7"),
            "work_order_status": "NOT_VERIFIED",
            "authority_granted": False,
            "verification_status": "NOT_VERIFIED",
        },
        "source_contract": {
            "receipt_schema_ref": opaque_ref("schema/protected-source-binding-receipt-candidate"),
            "receipt_schema_binding": binding("a"),
            "public_revision": "2" * 40,
            "expected_receipt_kind": "company_pack_protected_source_binding_receipt_candidate",
            "expected_receipt_status": "CANDIDATE_ONLY",
            "expected_receipt_state": "PROTECTED_RECEIPT_RECORDED_UNVERIFIED",
            "verification_status": "NOT_VERIFIED",
        },
        "runner_request": {
            "runner_policy_ref": opaque_ref("runner/policy"),
            "runner_policy_binding": binding("b"),
            "executable_ref": opaque_ref("runner/executable"),
            "executable_binding": binding("c", 8192),
            "configuration_ref": opaque_ref("runner/configuration"),
            "configuration_binding": binding("d"),
            "execution_environment_ref": opaque_ref("runner/environment"),
            "execution_environment_binding": binding("8"),
            "operation_kind": "PRIVATE_SOURCE_BINDING_RECEIPT_CANDIDATE",
            "credentials_embedded": False,
            "physical_locator_embedded": False,
            "verification_status": "NOT_VERIFIED",
        },
        "private_inputs": [
            private_input("source_record", "e"),
            private_input("source_content", "f"),
            private_input("access_consent_evidence", "1"),
            private_input("retention_policy", "2"),
        ],
        "evaluation_window": {
            "clock_policy_ref": opaque_ref("clock/policy"),
            "clock_policy_binding": binding("3"),
            "not_before": "2026-08-03T20:30:00+09:00",
            "expires_at": "2026-08-03T21:30:00+09:00",
            "max_skew_seconds": 30,
            "requested_duration_seconds": 3600,
            "verification_status": "NOT_VERIFIED",
        },
        "failure_and_rollback": {
            "stop_conditions": EXPECTED_STOP_CONDITIONS,
            "rollback_policy_ref": opaque_ref("rollback/policy"),
            "rollback_policy_binding": binding("4"),
            "rollback_receipt_ref": None,
            "rollback_receipt_binding": None,
            "failure_state": "REFUSED_UNVERIFIED" if refused else "NOT_EXECUTED",
            "no_external_effects_expected": True,
            "execution_receipt_ref": None,
            "verification_status": "NOT_VERIFIED",
        },
        "expected_output": {
            "receipt_contract_ref": opaque_ref("contract/protected-source-binding-receipt-candidate"),
            "receipt_contract_binding": binding("5"),
            "expected_status": "CANDIDATE_ONLY",
            "expected_receipt_state": "PROTECTED_RECEIPT_RECORDED_UNVERIFIED",
            "expected_claims_false": True,
            "output_state": "NOT_EMITTED_UNVERIFIED",
            "serialized_receipt_locator": None,
            "serialized_receipt_binding": None,
            "private_content_embedded": False,
            "verification_status": "NOT_VERIFIED",
        },
        "handoff": {
            "recipient_role": "independent_verifier",
            "recipient_policy_ref": opaque_ref("independent-verifier/policy"),
            "recipient_policy_binding": binding("6"),
            "handoff_status": "INDEPENDENT_VERIFICATION_REQUIRED",
            "independent_result_ref": None,
            "independent_result_binding": None,
            "human_decision_ref": None,
            "authority_granted": False,
            "verification_status": "NOT_VERIFIED",
        },
        "content_handling": {
            "source_content_embedded": False,
            "audio_embedded": False,
            "transcript_embedded": False,
            "model_output_embedded": False,
            "private_projection_embedded": False,
            "credentials_embedded": False,
            "physical_locator_embedded": False,
            "candidate_visibility": "PUBLIC_CONTRACT_OPAQUE_REFS",
        },
        "recorded_at": "2026-08-03T20:30:01+09:00",
        "expires_at": "2026-08-03T21:30:01+09:00",
        "review_trigger": EXPECTED_REVIEW_TRIGGERS,
        "claims": {name: False for name in EXPECTED_CLAIMS},
        "public_beta": "NO_GO_UNPUBLISHED",
    }


class ProtectedExecutionRequestHandoffCandidateContractTests(unittest.TestCase):
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

    def test_real_draft_2020_12_accepts_defined_and_refused_candidates(self) -> None:
        self.assert_valid(request_candidate())
        self.assert_valid(request_candidate(refused=True))

    def test_hostile_overclaims_private_values_and_aliases_are_rejected(self) -> None:
        base = request_candidate()
        cases = {}

        mutated = copy.deepcopy(base)
        mutated["status"] = "VERIFIED"
        cases["verified status alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["approved"] = True
        cases["unknown approval field"] = mutated
        mutated = copy.deepcopy(base)
        mutated["claims"]["executed"] = True
        cases["execution overclaim"] = mutated
        mutated = copy.deepcopy(base)
        mutated["runner_request"]["executable_ref"] = r"C:\private\runner.exe"
        cases["physical executable path"] = mutated
        mutated = copy.deepcopy(base)
        mutated["private_inputs"][0]["locator_ref"] = "file:///private/source.json"
        cases["file locator"] = mutated
        mutated = copy.deepcopy(base)
        mutated["private_inputs"].append(private_input("audio", "7"))
        cases["raw audio role"] = mutated
        mutated = copy.deepcopy(base)
        mutated["private_inputs"].reverse()
        cases["private role reorder"] = mutated
        mutated = copy.deepcopy(base)
        del mutated["private_inputs"][2]
        cases["missing consent input"] = mutated
        mutated = copy.deepcopy(base)
        mutated["evaluation_window"]["max_skew_seconds"] = True
        cases["boolean skew"] = mutated
        mutated = copy.deepcopy(base)
        mutated["evaluation_window"]["max_skew_seconds"] = 86401
        cases["unbounded skew"] = mutated
        mutated = copy.deepcopy(base)
        mutated["evaluation_window"]["requested_duration_seconds"] = 86401
        cases["unbounded duration"] = mutated
        mutated = copy.deepcopy(base)
        mutated["evaluation_window"]["expires_at"] = "2026-02-30T25:61:61+09:00"
        cases["invalid evaluation time"] = mutated
        mutated = copy.deepcopy(base)
        mutated["failure_and_rollback"]["rollback_receipt_ref"] = opaque_ref("rollback/receipt")
        cases["rollback receipt overclaim"] = mutated
        mutated = copy.deepcopy(base)
        mutated["expected_output"]["serialized_receipt_locator"] = opaque_ref("receipt/private")
        cases["serialized receipt locator"] = mutated
        mutated = copy.deepcopy(base)
        mutated["handoff"]["human_decision_ref"] = opaque_ref("human-decision/1")
        cases["human decision overclaim"] = mutated
        mutated = copy.deepcopy(base)
        mutated["content_handling"]["transcript_embedded"] = True
        cases["transcript embedded"] = mutated
        mutated = copy.deepcopy(base)
        mutated["content_handling"]["model_output_embedded"] = True
        cases["model output embedded"] = mutated
        mutated = copy.deepcopy(base)
        mutated["source_contract"]["expected_receipt_status"] = "PUBLIC"
        cases["public output alias"] = mutated
        mutated = copy.deepcopy(base)
        mutated["failure_and_rollback"]["stop_conditions"][0], mutated["failure_and_rollback"]["stop_conditions"][1] = (
            mutated["failure_and_rollback"]["stop_conditions"][1],
            mutated["failure_and_rollback"]["stop_conditions"][0],
        )
        cases["stop condition reorder"] = mutated
        mutated = copy.deepcopy(base)
        mutated["review_trigger"].append("extra_trigger")
        cases["review trigger extra"] = mutated
        mutated = copy.deepcopy(base)
        mutated["handoff"]["independent_result_binding"] = binding("8")
        cases["independent result binding"] = mutated

        for name, instance in cases.items():
            with self.subTest(name=name):
                self.assert_invalid(instance, name)

    def test_schema_is_closed_and_every_runtime_or_authority_claim_is_false(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertEqual(self.schema["properties"]["status"]["const"], "CANDIDATE_ONLY")
        self.assertEqual(self.schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        claims = self.schema["$defs"]["claims"]
        self.assertFalse(claims["additionalProperties"])
        self.assertEqual(set(claims["required"]), EXPECTED_CLAIMS)
        self.assertEqual(set(claims["properties"]), EXPECTED_CLAIMS)
        self.assertTrue(all(spec["const"] is False for spec in claims["properties"].values()))

    def test_work_order_and_execution_environment_are_explicitly_bound(self) -> None:
        work_order = self.schema["$defs"]["work_order"]
        self.assertEqual(
            set(work_order["required"]),
            {
                "work_order_ref",
                "work_order_binding",
                "work_order_status",
                "authority_granted",
                "verification_status",
            },
        )
        runner = self.schema["$defs"]["runner_request"]
        self.assertIn("execution_environment_binding", runner["required"])
        self.assertEqual(
            runner["properties"]["execution_environment_binding"],
            {"$ref": "#/$defs/binding"},
        )

    def test_private_input_and_stop_condition_orders_are_exact(self) -> None:
        private = self.schema["$defs"]["private_inputs"]
        self.assertEqual(private["minItems"], 4)
        self.assertEqual(private["maxItems"], 4)
        self.assertEqual(
            [item["allOf"][1]["properties"]["role"]["const"] for item in private["prefixItems"]],
            EXPECTED_PRIVATE_ROLES,
        )
        self.assertFalse(private["items"])
        rollback = self.schema["$defs"]["failure_and_rollback"]
        self.assertEqual(rollback["properties"]["stop_conditions"]["const"], EXPECTED_STOP_CONDITIONS)
        review_trigger = self.schema["properties"]["review_trigger"]
        self.assertEqual(review_trigger["prefixItems"], [{"const": item} for item in EXPECTED_REVIEW_TRIGGERS])
        self.assertFalse(review_trigger["items"])

    def test_evaluation_window_shape_is_bounded_and_runbook_explains_time_order(self) -> None:
        window = self.schema["$defs"]["evaluation_window"]
        self.assertEqual(window["properties"]["max_skew_seconds"]["maximum"], 86400)
        self.assertEqual(window["properties"]["requested_duration_seconds"]["maximum"], 86400)
        self.assertEqual(window["properties"]["requested_duration_seconds"]["minimum"], 1)
        self.assertEqual(window["properties"]["verification_status"]["const"], "NOT_VERIFIED")
        runbook = RUNBOOK.read_text(encoding="utf-8")
        self.assertIn("not_before", runbook)
        self.assertIn("expires_at", runbook)
        self.assertIn("schema alone does not prove", runbook)

    def test_runbook_and_public_navigation_links_are_discoverable(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
        receipt_runbook = (ROOT / "docs" / "PROTECTED-SOURCE-BINDING-RECEIPT-CANDIDATE.md").read_text(
            encoding="utf-8"
        )
        template_guide = (ROOT / "docs" / "TEMPLATE-GUIDE.md").read_text(encoding="utf-8")
        starter_readme = (ROOT / "examples" / "company-starter" / "README.md").read_text(encoding="utf-8")
        for markdown in (readme, status, roadmap, receipt_runbook, template_guide, starter_readme):
            self.assertIn("PROTECTED-EXECUTION-REQUEST-HANDOFF-CANDIDATE.md", markdown)
        self.assertIn("company-pack-protected-execution-request-handoff-candidate.schema.json", readme)
        self.assertIn("NO_GO_UNPUBLISHED", RUNBOOK.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
