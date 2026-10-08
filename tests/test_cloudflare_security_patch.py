"""The candidate verifier never promotes recorded component checks into adoption."""
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from tools import validate_cloudflare_security_patch as check


class CloudflareSecurityPatchTests(unittest.TestCase):
    def setUp(self):
        self.candidate = check.load_candidate()
        self.patch = (check.ARTIFACT / "candidate.patch").read_bytes()
        self.license = (check.ARTIFACT / "LICENSE").read_bytes()

    def test_actual_artifact_is_consistent_without_fresh_verification_or_approval(self):
        check.validate_candidate(self.candidate, self.patch, self.license)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(check.main([]), 0)
        result = json.loads(output.getvalue())
        for key in ("source_verified", "materialized_bytes_verified", "audit_rerun", "tests_rerun", "full_remediation_verified", "owner_approval_verified", "provider_verified"):
            self.assertIs(result[key], False)
        self.assertEqual(result["status"], "CANDIDATE_BYTES_VALID_FULL_SUITE_BLOCKED")

    def test_bytes_license_and_materialized_lf_drift_are_refused(self):
        for patch, license_bytes in ((self.patch+b"changed", self.license), (self.patch, self.license+b"changed")):
            with self.assertRaises(check.CandidateViolation):
                check.validate_candidate(self.candidate, patch, license_bytes)
        with self.assertRaises(check.CandidateViolation):
            check.verify_bytes(b"line\r\n", {"bytes":6, "sha256":hashlib.sha256(b"line\r\n").hexdigest()})

    def test_scope_mutation_cannot_hide_behind_a_new_patch_digest(self):
        for old, new in ((b"+++ b/pnpm-workspace.yaml", b"+++ b/unlisted.yaml"), (b"--- a/pnpm-workspace.yaml", b"rename to unlisted.yaml\n--- a/pnpm-workspace.yaml")):
            with self.subTest(new=new):
                patch = self.patch.replace(old, new, 1)
                candidate = copy.deepcopy(self.candidate)
                candidate["patch"].update(sha256=hashlib.sha256(patch).hexdigest(), bytes=len(patch))
                with self.assertRaises(check.CandidateViolation):
                    check.validate_candidate(candidate, patch, self.license)

    def test_forged_acceptance_or_parent_policy_is_refused(self):
        mutations = [
            lambda c: c["adoption"].update(full_remediation_claimed=True),
            lambda c: c["observed_verification"].update(full_upstream_suite_passed=True),
            lambda c: c["observed_verification"].update(production_audit_high=False),
            lambda c: c["review"].update(owner_independence_accepted=True),
            lambda c: c["source"].update(commit="1"*40),
            lambda c: c["overrides"].update({"seroval":"1.6.3"}),
        ]
        for mutate in mutations:
            candidate = copy.deepcopy(self.candidate)
            mutate(candidate)
            with self.assertRaises(check.CandidateViolation):
                check.validate_candidate(candidate, self.patch, self.license)

    def test_bounded_input_and_duplicate_fields_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input"
            path.write_bytes(b"12345")
            self.assertEqual(check.regular_bytes(path, 5), b"12345")
            with self.assertRaises(check.CandidateViolation):
                check.regular_bytes(path, 4)
        with self.assertRaises(check.CandidateViolation):
            json.loads('{"a":1,"a":2}', object_pairs_hook=check.unique_object)


if __name__ == "__main__":
    unittest.main()
