from __future__ import annotations

import copy
import importlib.util
import pathlib
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "validate_cloudflare_os_local_runtime_evaluation.py"
SPEC = importlib.util.spec_from_file_location("cloudflare_os_runtime_validator", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class CloudflareOsLocalRuntimeEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.receipt = MODULE.load_json(MODULE.RECEIPT)
        cls.schema = MODULE.load_json(MODULE.SCHEMA)
        cls.upstream = MODULE.load_json(MODULE.UPSTREAM_PIN)

    def mutate(self) -> dict:
        return copy.deepcopy(self.receipt)

    def test_current_receipt_passes(self) -> None:
        result = MODULE.validate()
        self.assertEqual("PASS_LOCAL_RUNTIME_WITH_GAPS", result["status"])
        self.assertEqual(1060, result["tests_passed"])
        self.assertEqual(0, result["external_effects"])

    def test_unknown_field_is_rejected_by_schema(self) -> None:
        candidate = self.mutate()
        candidate["unexpected"] = True
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "schema validation failed"):
            MODULE.validate_schema(candidate, self.schema)

    def test_public_beta_cannot_be_promoted(self) -> None:
        candidate = self.mutate()
        candidate["public_beta"] = "GO"
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "Public Beta"):
            MODULE.validate_semantics(candidate)

    def test_status_cannot_be_widened(self) -> None:
        candidate = self.mutate()
        candidate["status"] = "PASS_PRODUCTION"
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "status widened"):
            MODULE.validate_semantics(candidate)

    def test_external_effect_must_remain_zero(self) -> None:
        candidate = self.mutate()
        candidate["effects"]["deployments"] = 1
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "nonzero external effect"):
            MODULE.validate_semantics(candidate)

    def test_provider_preview_cannot_be_ready(self) -> None:
        candidate = self.mutate()
        candidate["decision"]["provider_preview_ready"] = True
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "provider preview"):
            MODULE.validate_semantics(candidate)

    def test_source_pin_mismatch_is_rejected(self) -> None:
        candidate = self.mutate()
        candidate["source"]["starter"]["commit"] = "0" * 40
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "starter commit drifted"):
            MODULE.validate_source_binding(candidate, self.upstream)

    def test_upstream_drift_cannot_be_self_approved(self) -> None:
        candidate = self.mutate()
        candidate["source"]["drift"]["independent_review"] = "PASS"
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "independent review"):
            MODULE.validate_semantics(candidate)

    def test_test_totals_are_bound(self) -> None:
        candidate = self.mutate()
        candidate["verification"]["tests"]["passed"] += 1
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "test totals"):
            MODULE.validate_semantics(candidate)

    def test_installation_safety_cannot_be_widened(self) -> None:
        candidate = self.mutate()
        candidate["verification"]["installation"]["ignore_scripts"] = False
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "installation safety"):
            MODULE.validate_semantics(candidate)

    def test_toolchain_is_exactly_bound(self) -> None:
        candidate = self.mutate()
        candidate["toolchain"]["wrangler"] = "latest"
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "toolchain binding"):
            MODULE.validate_semantics(candidate)

    def test_response_body_read_is_rejected(self) -> None:
        candidate = self.mutate()
        candidate["verification"]["runtime"]["response_body_read"] = True
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "response body"):
            MODULE.validate_semantics(candidate)

    def test_cleanup_must_have_zero_residue(self) -> None:
        candidate = self.mutate()
        candidate["verification"]["runtime"]["cleanup"]["remaining_listeners"] = 1
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "cleanup"):
            MODULE.validate_semantics(candidate)

    def test_high_advisory_cannot_be_hidden(self) -> None:
        candidate = self.mutate()
        candidate["verification"]["production_audit"]["core_high"] = 0
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "advisory"):
            MODULE.validate_semantics(candidate)

    def test_finding_inventory_cannot_drift(self) -> None:
        candidate = self.mutate()
        candidate["findings"]["items"].pop()
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "finding inventory"):
            MODULE.validate_semantics(candidate)

    def test_duplicate_finding_is_rejected(self) -> None:
        candidate = self.mutate()
        candidate["findings"]["items"].append(copy.deepcopy(candidate["findings"]["items"][0]))
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "duplicate finding"):
            MODULE.validate_semantics(candidate)

    def test_windows_adapter_source_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            changed = pathlib.Path(directory) / "shim.cs"
            changed.write_bytes(MODULE.SHIM.read_bytes() + b"\n// drift\n")
            with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "source hash drifted"):
                MODULE.validate_semantics(self.mutate(), changed)

    def test_secret_shaped_value_is_rejected(self) -> None:
        candidate = self.mutate()
        candidate["non_claims"].append("api_" + "token=" + "abcdefgh" + "ijklmnop")
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "secret-shaped"):
            MODULE.validate_public_safety(candidate, ())

    def test_local_absolute_path_is_rejected(self) -> None:
        candidate = self.mutate()
        candidate["non_claims"].append("C:" + "\\Users\\" + "example\\private")
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "local absolute path"):
            MODULE.validate_public_safety(candidate, ())

    def test_raw_discord_identifier_is_rejected(self) -> None:
        candidate = self.mutate()
        candidate["non_claims"].append("discord channel " + "123456789" + "012345678")
        with self.assertRaisesRegex(MODULE.RuntimeEvaluationViolation, "raw Discord identifier"):
            MODULE.validate_public_safety(candidate, ())


if __name__ == "__main__":
    unittest.main()
