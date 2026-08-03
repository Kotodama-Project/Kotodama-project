import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CREATOR = ROOT / "tools" / "create_company_pack.py"
BUNDLE_BUILDER = ROOT / "tools" / "build_company_pack_review_bundle.py"
BUNDLE_VERIFIER = ROOT / "tools" / "verify_company_pack_review_bundle.py"
REQUEST_BUILDER = ROOT / "tools" / "build_company_pack_review_request.py"
RESPONSE_BUILDER = ROOT / "tools" / "build_company_pack_review_response.py"
RESPONSE_VERIFIER = ROOT / "tools" / "verify_company_pack_review_response.py"
HANDOFF_BUILDER = ROOT / "tools" / "build_company_pack_review_decision_handoff.py"
HANDOFF_VERIFIER = ROOT / "tools" / "verify_company_pack_review_decision_handoff.py"


EXPECTED_DECISION_FIELDS = [
    "decision_id",
    "intent_candidate_ref",
    "reviewer_identity_ref",
    "reviewer_role",
    "reviewer_authority_ref",
    "reviewer_independence_ref",
    "reviewed_at",
    "decision_maker_identity_ref",
    "decision_maker_role",
    "decision_maker_authority_ref",
    "decided_at",
    "selected_outcome",
    "scope",
    "reason",
    "expires_at",
    "review_trigger",
    "unresolved_evidence_refs",
    "artifact_bindings",
    "candidate_binding",
    "retention_policy_ref",
]


class CompanyPackReviewDecisionHandoffCliTests(unittest.TestCase):
    def run_cli(self, tool: Path, *arguments: Path, env=None):
        return subprocess.run(
            [sys.executable, str(tool), *(str(value) for value in arguments)],
            cwd=ROOT,
            capture_output=True,
            check=False,
            env=env,
        )

    def save_json(self, path: Path, value: dict) -> bytes:
        data = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        path.write_bytes(data)
        return data

    def create_complete_chain(self, root: Path) -> dict:
        pack = root / "decision-handoff-pack"
        creation = subprocess.run(
            [
                sys.executable,
                str(CREATOR),
                "decision-handoff-pack",
                str(pack),
                "--human-intent-ref",
                "human-intent:private-decision-handoff-source",
                "--authority-expires-at",
                "2026-08-20T00:00:00Z",
                "--retention-policy-ref",
                "retention-policy:private-decision-handoff-policy",
            ],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(creation.returncode, 0, creation.stdout.decode("utf-8"))

        paths = {
            "bundle": root / "saved-review-bundle.json",
            "bundle_verification": root / "saved-bundle-verification.json",
            "request": root / "saved-review-request.json",
            "response": root / "saved-review-response.json",
            "response_verification": root / "saved-response-verification.json",
        }

        bundle = self.run_cli(BUNDLE_BUILDER, pack)
        self.assertEqual(bundle.returncode, 0, bundle.stdout.decode("utf-8"))
        paths["bundle"].write_bytes(bundle.stdout)

        bundle_verification = self.run_cli(
            BUNDLE_VERIFIER, paths["bundle"], pack
        )
        self.assertEqual(
            bundle_verification.returncode,
            0,
            bundle_verification.stdout.decode("utf-8"),
        )
        paths["bundle_verification"].write_bytes(bundle_verification.stdout)

        request = self.run_cli(REQUEST_BUILDER, paths["bundle"], pack)
        self.assertEqual(request.returncode, 0, request.stdout.decode("utf-8"))
        paths["request"].write_bytes(request.stdout)

        response = self.run_cli(RESPONSE_BUILDER, paths["request"])
        self.assertEqual(response.returncode, 0, response.stdout.decode("utf-8"))
        response_value = json.loads(response.stdout)
        outcomes = ["accept", "request_changes", "reject"]
        for index, item in enumerate(response_value["review_response"]["items"]):
            item["outcome"] = outcomes[index % len(outcomes)]
            if item["outcome"] != "accept":
                item["reviewer_note"] = f"private-review-note-ref:{index:02d}"
        self.save_json(paths["response"], response_value)

        response_verification = self.run_cli(
            RESPONSE_VERIFIER, paths["request"], paths["response"]
        )
        self.assertEqual(
            response_verification.returncode,
            0,
            response_verification.stdout.decode("utf-8"),
        )
        paths["response_verification"].write_bytes(response_verification.stdout)

        return {
            "pack": pack,
            "paths": paths,
            "request": json.loads(request.stdout),
            "response_verification": json.loads(response_verification.stdout),
        }

    def run_builder(self, chain: dict, *, env=None):
        paths = chain["paths"]
        return self.run_cli(
            HANDOFF_BUILDER,
            paths["bundle"],
            chain["pack"],
            paths["bundle_verification"],
            paths["request"],
            paths["response"],
            paths["response_verification"],
            env=env,
        )

    def test_complete_chain_builds_non_authorizing_decision_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            chain = self.create_complete_chain(Path(temporary))
            result = self.run_builder(chain)
            artifact_bytes = {
                name: path.read_bytes() for name, path in chain["paths"].items()
            }

        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(b"private-decision-handoff", result.stdout)
        self.assertNotIn(b"private-review-note", result.stdout)
        handoff = json.loads(result.stdout)
        self.assertEqual(handoff["kind"], "company_pack_review_decision_handoff")
        self.assertEqual(handoff["version"], "1.0")
        self.assertEqual(handoff["status"], "CANDIDATE_DECISION_HANDOFF")
        self.assertIsNone(handoff["reason"])
        self.assertEqual(handoff["pack_id"], "decision-handoff-pack")
        self.assertEqual(
            handoff["artifact_bindings"],
            {
                name: {
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
                for name, data in artifact_bytes.items()
            },
        )
        self.assertEqual(
            handoff["candidate_binding"], chain["request"]["candidate_binding"]
        )
        self.assertEqual(
            handoff["source_checks"],
            {
                "current_bundle": {"status": "MATCH", "matched_bindings": 22},
                "response": {"status": "ITEM_RESPONSES_MATCH_REQUEST"},
            },
        )
        self.assertEqual(
            handoff["review_summary"],
            {
                "state": "ALL_ITEM_RESPONSES_PRESENT",
                "expected_items": 46,
                "completed_items": 46,
                "outcome_counts": {
                    "accept": 16,
                    "request_changes": 15,
                    "reject": 15,
                },
                "selected_outcome": None,
            },
        )
        self.assertEqual(
            handoff["unresolved_evidence"],
            {"state": "EVIDENCE_REQUIRED", "item_count": 5},
        )
        self.assertEqual(
            handoff["decision_requirements"],
            {
                "state": "HUMAN_DECISION_REQUIRED",
                "required_fields": EXPECTED_DECISION_FIELDS,
                "permitted_outcomes": ["accept", "request_changes", "reject"],
                "selected_outcome": None,
            },
        )
        self.assertTrue(all(value is False for value in handoff["claims"].values()))
        self.assertEqual(handoff["public_beta"], "NO_GO_UNPUBLISHED")


if __name__ == "__main__":
    unittest.main()
