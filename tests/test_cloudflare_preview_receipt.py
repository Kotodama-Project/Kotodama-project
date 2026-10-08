import copy
import json
from pathlib import Path
import unittest
import yaml

from tools import validate_cloudflare_preview_receipt as checker

ROOT = Path(__file__).resolve().parents[1]


class PreviewReceiptTests(unittest.TestCase):
    def setUp(self):
        self.receipt=json.loads((ROOT/"examples/cloudflare-preview/synthetic-receipt.json").read_text(encoding="utf-8"))

    def test_expected_statuses_do_not_imply_verified_provider_or_human_approval(self):
        result=checker.validate(self.receipt, "a"*40)
        self.assertTrue(result["reported_checks_match"])
        self.assertTrue(result["candidate_binding_checked"])
        self.assertFalse(result["provider_reverified"])
        self.assertFalse(result["human_approval_verified"])
        self.assertFalse(result["production_deployed"])

    def test_old_candidate_at_any_boundary_is_refused(self):
        for field in ("candidate_sha","dispatch_sha","approved_sha","readback_sha"):
            value=copy.deepcopy(self.receipt)
            value[field]="e"*40
            with self.subTest(field=field), self.assertRaises(ValueError):
                checker.validate(value, "a"*40)

    def test_raw_version_host_body_and_fake_header_evidence_are_refused(self):
        for mutate in (
            lambda value:value.update(version_locator="raw-provider-version"),
            lambda value:value.update(hostname="private-host.example"),
            lambda value:value["probes"]["health"].update(body_bytes_stored=1),
            lambda value:value["probes"]["health"].update(headers={"private":"marker"}),
            lambda value:value["probes"]["health"].update(headers_sha256=None),
        ):
            value=copy.deepcopy(self.receipt); mutate(value)
            with self.assertRaises(ValueError):
                checker.validate(value, "a"*40)

    def test_failure_and_not_run_remain_incomplete(self):
        self.receipt["probes"]["health"]["http_status"]=503
        self.assertFalse(checker.validate(self.receipt,"a"*40)["reported_checks_match"])
        self.receipt["upload_state"]="NOT_RUN"
        self.receipt["version_locator"]=None
        for probe in self.receipt["probes"].values():
            probe.update(http_status=None, headers_sha256=None)
        self.assertFalse(checker.validate(self.receipt,"a"*40)["reported_checks_match"])

    def test_both_preview_jobs_keep_a_fixed_runner_and_protected_upload(self):
        workflow=yaml.safe_load((ROOT/".github/workflows/cloudflare-edge-preview.yml").read_text(encoding="utf-8"))
        self.assertEqual({job["runs-on"] for job in workflow["jobs"].values()}, {"ubuntu-24.04"})
        self.assertEqual(workflow["jobs"]["upload-preview-version"]["environment"],"cloudflare-preview")


if __name__ == "__main__":
    unittest.main()
