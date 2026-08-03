import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "tools" / "validate_installation_lifecycle.py"
EXAMPLES = ROOT / "examples" / "installation-lifecycle"
SCHEMA = ROOT / "schemas" / "installation-lifecycle-profile.schema.json"


class InstallationLifecycleValidatorCliTests(unittest.TestCase):
    def run_path(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(path)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_document(self, document: object) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "profile.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return self.run_path(path)

    def load_example(self, name: str) -> dict[str, object]:
        return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))

    def test_shipped_profiles_pass_without_claiming_live_state(self) -> None:
        for filename, expected_profile in (
            ("compose-minimum.json", "compose_minimum"),
            ("proxmox-segmented.json", "proxmox_segmented"),
        ):
            with self.subTest(filename=filename):
                result = self.run_path(EXAMPLES / filename)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stderr, "")
            report = json.loads(result.stdout)
            self.assertEqual(report["kind"], "installation_lifecycle_validation")
            self.assertEqual(report["version"], "1.0")
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(report["profile"], expected_profile)
            self.assertEqual(report["phase_count"], 6)
            self.assertEqual(report["errors"], [])
            self.assertTrue(all(not value for value in report["claims"].values()))
            self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_lifecycle_phase_order_is_exact(self) -> None:
        document = self.load_example("compose-minimum.json")
        document["phases"][0], document["phases"][1] = (
            document["phases"][1],
            document["phases"][0],
        )

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        self.assertIn("phases must use the required lifecycle order", json.loads(result.stdout)["errors"])

    def test_whitespace_only_purpose_is_rejected_by_schema_and_validator(self) -> None:
        document = self.load_example("compose-minimum.json")
        document["purpose"] = "   "

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        self.assertIn("purpose must be a non-empty string", json.loads(result.stdout)["errors"])

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertTrue(list(Draft202012Validator(schema).iter_errors(document)))

    def test_material_phases_require_work_orders_and_rollback_binding(self) -> None:
        document = self.load_example("compose-minimum.json")
        apply_phase = document["phases"][2]
        apply_phase["requires_work_order"] = False
        apply_phase["rollback_ref"] = None

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("phase apply requires_work_order must be true", errors)
        self.assertIn("phase apply rollback_ref must be phase:rollback", errors)

    def test_verify_requires_digest_health_negative_and_boundary_evidence(self) -> None:
        document = self.load_example("compose-minimum.json")
        document["phases"][3]["required_evidence"] = ["candidate_digest"]

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        for evidence in (
            "service_health",
            "negative_test_results",
            "network_boundary_checks",
        ):
            self.assertIn(f"phase verify missing required evidence: {evidence}", errors)

    def test_compose_profile_requires_namespace_volume_and_restore_evidence(self) -> None:
        document = self.load_example("compose-minimum.json")
        document["profile_evidence"] = ["compose_runtime_version"]

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        for evidence in (
            "project_namespace",
            "volume_inventory",
            "backup_digest",
            "isolated_restore_result",
        ):
            self.assertIn(f"compose_minimum missing profile evidence: {evidence}", errors)

    def test_proxmox_profile_requires_segmentation_identity_and_restore_evidence(self) -> None:
        document = self.load_example("proxmox-segmented.json")
        document["profile_evidence"] = ["role_map_locator"]

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        for evidence in (
            "segmentation_matrix",
            "service_identity_matrix",
            "backup_digest",
            "isolated_restore_result",
        ):
            self.assertIn(f"proxmox_segmented missing profile evidence: {evidence}", errors)

    def test_claims_and_public_beta_fail_closed(self) -> None:
        document = self.load_example("compose-minimum.json")
        document["claims"]["live_installation_verified"] = True
        document["public_beta"] = "GO"

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("claim live_installation_verified must remain false", errors)
        self.assertIn("public_beta must remain NO_GO_UNPUBLISHED", errors)

    def test_secret_keys_and_private_infrastructure_literals_are_refused_without_echo(self) -> None:
        document = self.load_example("proxmox-segmented.json")
        document["runtime_bindings"] = {
            "api_token": "not-a-real-token",
            "host_ip": "192.168.50.20",
        }

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("not-a-real-token", result.stdout)
        self.assertNotIn("192.168.50.20", result.stdout)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("profile contains unknown field: runtime_bindings", errors)
        self.assertIn("secret-bearing key is forbidden: $.runtime_bindings.api_token", errors)
        self.assertIn("private infrastructure key is forbidden: $.runtime_bindings.host_ip", errors)

    def test_unknown_nested_fields_fail_closed(self) -> None:
        document = self.load_example("compose-minimum.json")
        document["phases"][0]["surprise"] = True

        result = self.run_document(document)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "phase preflight contains unknown field: surprise",
            json.loads(result.stdout)["errors"],
        )

    def test_duplicate_keys_and_non_finite_numbers_are_invalid_json(self) -> None:
        cases = (
            '{"kind":"installation_lifecycle_profile","kind":"shadow"}',
            '{"kind":"installation_lifecycle_profile","value":NaN}',
        )
        for content in cases:
            with self.subTest(content=content):
                with tempfile.TemporaryDirectory() as temporary:
                    path = Path(temporary) / "profile.json"
                    path.write_text(content, encoding="utf-8")
                    result = self.run_path(path)

            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["errors"], ["profile JSON is invalid"])

    def test_validation_is_deterministic(self) -> None:
        path = EXAMPLES / "compose-minimum.json"
        first = self.run_path(path)
        second = self.run_path(path)

        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual(first.stdout, second.stdout)

    def test_schema_is_closed_and_denies_all_live_claims(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "installation-lifecycle-profile.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertFalse(schema["properties"]["claims"]["additionalProperties"])
        for definition in schema["properties"]["claims"]["properties"].values():
            self.assertIs(definition["const"], False)

    def test_usage_error_returns_two_without_json_report(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)


if __name__ == "__main__":
    unittest.main()
