import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools import validate_cloudflare_provider_inventory as checker

ROOT = Path(__file__).resolve().parents[1]


class ProviderInventoryTests(unittest.TestCase):
    def setUp(self):
        self.receipt = json.loads((ROOT / "examples/cloudflare-provider-inventory/synthetic.json").read_text(encoding="utf-8"))

    def test_partial_record_keeps_denied_billing_and_authority_unverified(self):
        report = checker.validate(self.receipt)
        self.assertEqual(report["reported_completeness"], "PARTIAL")
        self.assertIn("billing", report["unresolved"])
        self.assertIn("plan", report["unresolved"])
        self.assertIn("budget", report["unresolved"])
        for name in ("authenticity_verified", "identity_verified", "observations_reverified", "budget_approved", "deployment_authorized"):
            self.assertIs(report[name], False)

    def test_raw_identifiers_payloads_unknown_fields_and_write_methods_are_refused(self):
        changes = [
            lambda row: row.update(account_id="private-account-marker"),
            lambda row: row.update(account_locator="0123456789abcdef"*2),
            lambda row: row.update(zone_locator="private-host.example"),
            lambda row: row.update(token="private-token-marker"),
            lambda row: row["services"]["workers"].update(payload="private-body-marker"),
            lambda row: row.update(method="POST"),
        ]
        for change in changes:
            value = copy.deepcopy(self.receipt)
            change(value)
            with self.assertRaises(ValueError) as error:
                checker.validate(value)
            self.assertNotIn("private-", str(error.exception))

    def test_unknown_is_not_zero_and_paid_plan_requires_billing_evidence(self):
        for mutate in (
            lambda row: row["services"]["billing"].update(resource_count=0),
            lambda row: row["services"]["workers"].update(http_status=403),
            lambda row: row["plan"].update(name="PAID", entitlement_sha256="sha256:"+"a"*64),
            lambda row: row["budget"].update(monthly_ceiling=0),
            lambda row: row.update(zone_locator=None, services={**row["services"], "dns":dict(row["services"]["workers"])}),
        ):
            value=copy.deepcopy(self.receipt)
            mutate(value)
            with self.assertRaises(ValueError):
                checker.validate(value)

    def test_complete_report_still_does_not_verify_identity_or_approve_spend(self):
        for name in self.receipt["services"]:
            self.receipt["services"][name] = dict(status="OBSERVED", http_status=200, resource_count=0, response_sha256="sha256:"+"a"*64)
        self.receipt["plan"] = dict(name="FREE", entitlement_sha256="sha256:"+"b"*64)
        self.receipt["budget"] = dict(state="REPORTED_DECISION", currency="USD", monthly_ceiling=0, decision_sha256="sha256:"+"c"*64)
        self.receipt["unknown_bindings"] = []
        result = checker.validate(self.receipt)
        self.assertEqual(result["reported_completeness"], "COMPLETE_REPORTED")
        self.assertFalse(result["deployment_authorized"])
        self.assertFalse(result["budget_approved"])
        self.receipt["budget"]["monthly_ceiling"] = float("nan")
        with self.assertRaises(ValueError):
            checker.validate(self.receipt)

    def test_cli_refuses_duplicate_fields_without_echoing_input_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"input.json"
            raw=b'{"private-field":"private-body-marker","private-field":1}'
            path.write_bytes(raw)
            result=subprocess.run([sys.executable, "-B", str(ROOT/"tools/validate_cloudflare_provider_inventory.py"), str(path)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertNotIn("private-", result.stdout + result.stderr)
            self.assertEqual(path.read_bytes(), raw)
            self.assertEqual([item.name for item in Path(temporary).iterdir()], ["input.json"])


if __name__ == "__main__":
    unittest.main()
