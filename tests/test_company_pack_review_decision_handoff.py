import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))
import build_company_pack_review_decision_handoff as handoff_builder
import verify_company_pack_review_decision_handoff as handoff_verifier


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

    def run_handoff_verifier(self, chain: dict, handoff_path: Path, *, env=None):
        paths = chain["paths"]
        return self.run_cli(
            HANDOFF_VERIFIER,
            paths["bundle"],
            chain["pack"],
            paths["bundle_verification"],
            paths["request"],
            paths["response"],
            paths["response_verification"],
            handoff_path,
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
                "decision": None,
                "selected_outcome": None,
            },
        )
        self.assertTrue(all(value is False for value in handoff["claims"].values()))
        self.assertEqual(handoff["public_beta"], "NO_GO_UNPUBLISHED")

    def test_report_substitution_and_current_pack_drift_fail_closed(self) -> None:
        mutations = {
            "bundle bytes": lambda chain: chain["paths"]["bundle"].write_bytes(
                chain["paths"]["bundle"].read_bytes() + b" "
            ),
            "bundle verification": lambda chain: self._mutate_json(
                chain["paths"]["bundle_verification"],
                lambda value: value.__setitem__("matched_bindings", 21),
            ),
            "request candidate binding": lambda chain: self._mutate_json(
                chain["paths"]["request"],
                lambda value: value["candidate_binding"]["saved_bundle"].__setitem__(
                    "sha256", "0" * 64
                ),
            ),
            "response item": lambda chain: self._mutate_json(
                chain["paths"]["response"],
                lambda value: value["review_response"]["items"][0].__setitem__(
                    "reason", "tampered-private-reason"
                ),
            ),
            "response verification": lambda chain: self._mutate_json(
                chain["paths"]["response_verification"],
                lambda value: value["review_summary"]["outcome_counts"].__setitem__(
                    "accept", 17
                ),
            ),
            "current Pack": lambda chain: (
                chain["pack"] / "records" / "source-record.json"
            ).write_bytes(
                (chain["pack"] / "records" / "source-record.json").read_bytes()
                + b"\n"
            ),
        }

        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                chain = self.create_complete_chain(Path(temporary))
                mutate(chain)
                result = self.run_builder(chain)

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, b"")
            self.assertNotIn(b"private-decision-handoff", result.stdout)
            self.assertNotIn(b"tampered-private-reason", result.stdout)
            refusal = json.loads(result.stdout)
            self.assertEqual(refusal["status"], "HANDOFF_BUILD_REFUSED")
            self.assertIn(
                refusal["reason"],
                {"SOURCE_INVALID", "CHAIN_MISMATCH", "SOURCE_DRIFT_DETECTED"},
            )
            self.assertIsNone(refusal["pack_id"])
            self.assertIsNone(refusal["artifact_bindings"])
            self.assertIsNone(refusal["candidate_binding"])
            self.assertEqual(refusal["review_summary"]["completed_items"], 0)
            self.assertEqual(refusal["decision_requirements"]["required_fields"], [])
            self.assertTrue(all(value is False for value in refusal["claims"].values()))
            self.assertEqual(refusal["public_beta"], "NO_GO_UNPUBLISHED")

    def test_saved_handoff_matches_current_chain_without_becoming_a_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chain = self.create_complete_chain(root)
            built = self.run_builder(chain)
            self.assertEqual(built.returncode, 0, built.stdout.decode("utf-8"))
            handoff_path = root / "saved-decision-handoff.json"
            handoff_path.write_bytes(built.stdout)
            result = self.run_handoff_verifier(chain, handoff_path)
            handoff = json.loads(built.stdout)

        self.assertEqual(result.returncode, 0, result.stdout.decode("utf-8"))
        self.assertEqual(result.stderr, b"")
        self.assertNotIn(b"private-decision-handoff", result.stdout)
        self.assertNotIn(b"private-review-note", result.stdout)
        report = json.loads(result.stdout)
        self.assertEqual(
            report["kind"], "company_pack_review_decision_handoff_verification"
        )
        self.assertEqual(report["version"], "1.0")
        self.assertEqual(report["status"], "DECISION_HANDOFF_MATCH")
        self.assertIsNone(report["reason"])
        self.assertEqual(report["pack_id"], "decision-handoff-pack")
        self.assertEqual(report["artifact_bindings"], handoff["artifact_bindings"])
        self.assertEqual(
            report["handoff_binding"],
            {
                "sha256": hashlib.sha256(built.stdout).hexdigest(),
                "bytes": len(built.stdout),
            },
        )
        self.assertEqual(report["candidate_binding"], handoff["candidate_binding"])
        self.assertEqual(report["source_checks"], handoff["source_checks"])
        self.assertEqual(report["review_summary"], handoff["review_summary"])
        self.assertEqual(
            report["unresolved_evidence"],
            {"state": "EVIDENCE_REQUIRED", "item_count": 5},
        )
        self.assertEqual(
            report["decision_requirements"],
            {
                "state": "HUMAN_DECISION_REQUIRED",
                "decision": None,
                "selected_outcome": None,
            },
        )
        self.assertTrue(all(value is False for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_handoff_schemas_close_the_decision_and_authority_boundaries(self) -> None:
        handoff_schema = json.loads(
            (
                ROOT
                / "schemas"
                / "company-pack-review-decision-handoff.schema.json"
            ).read_text(encoding="utf-8")
        )
        verification_schema = json.loads(
            (
                ROOT
                / "schemas"
                / "company-pack-review-decision-handoff-verification.schema.json"
            ).read_text(encoding="utf-8")
        )

        for schema in (handoff_schema, verification_schema):
            self.assertEqual(schema["additionalProperties"], False)
            self.assertEqual(
                schema["properties"]["public_beta"]["const"],
                "NO_GO_UNPUBLISHED",
            )
            claims = schema["$defs"]["claims"]
            self.assertEqual(claims["additionalProperties"], False)
            self.assertEqual(
                set(claims["properties"]),
                {
                    "reviewer_identity_verified",
                    "reviewer_authority_verified",
                    "reviewer_independence_verified",
                    "decision_maker_identity_verified",
                    "decision_maker_authority_verified",
                    "governed_review_completed",
                    "human_approval_verified",
                    "candidate_bound_human_decision_verified",
                    "external_evidence_verified",
                    "promotion_verified",
                    "current_truth_changed",
                    "runtime_ready",
                    "final_human_go",
                    "public_beta_go",
                },
            )
            self.assertTrue(
                all(
                    definition["const"] is False
                    for definition in claims["properties"].values()
                )
            )

        artifact_bindings = handoff_schema["$defs"]["artifact_bindings"]
        self.assertEqual(artifact_bindings["additionalProperties"], False)
        self.assertEqual(
            artifact_bindings["required"],
            [
                "bundle",
                "bundle_verification",
                "request",
                "response",
                "response_verification",
            ],
        )
        handoff_requirements = handoff_schema["properties"][
            "decision_requirements"
        ]
        self.assertEqual(handoff_requirements["additionalProperties"], False)
        self.assertEqual(
            handoff_requirements["properties"]["decision"]["type"], "null"
        )
        self.assertEqual(
            handoff_requirements["properties"]["selected_outcome"]["type"],
            "null",
        )
        self.assertEqual(
            handoff_schema["$defs"]["required_decision_fields"]["prefixItems"],
            [{"const": field} for field in EXPECTED_DECISION_FIELDS],
        )
        verification_requirements = verification_schema["properties"][
            "decision_requirements"
        ]
        self.assertEqual(verification_requirements["additionalProperties"], False)
        self.assertEqual(
            verification_requirements["properties"]["decision"]["type"], "null"
        )
        self.assertEqual(
            verification_requirements["properties"]["selected_outcome"]["type"],
            "null",
        )

    def test_handoff_runbook_is_discoverable_and_preserves_the_human_gate(self) -> None:
        runbook = (ROOT / "docs" / "REVIEW-DECISION-HANDOFF.md").read_text(
            encoding="utf-8"
        )
        for required in (
            "build_company_pack_review_decision_handoff.py",
            "verify_company_pack_review_decision_handoff.py",
            "[IO.FileMode]::CreateNew",
            "noclobber",
            "evidence_ref",
            "decision: null",
            "selected_outcome: null",
            "HUMAN_DECISION_REQUIRED",
            "NO_GO_UNPUBLISHED",
            "intent_candidate_ref",
            "reviewer_identity_ref",
            "decision_maker_authority_ref",
        ):
            self.assertIn(required, runbook)

        discoverability_files = (
            ROOT / "README.md",
            ROOT / "docs" / "REVIEW-WORKFLOW.md",
            ROOT / "docs" / "REVIEW-RESPONSE.md",
            ROOT / "docs" / "STARTER-WALKTHROUGH.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md",
            ROOT / "docs" / "VALIDATION.md",
            ROOT / "docs" / "CUSTOMIZATION-CHECKLIST.md",
            ROOT / "examples" / "company-starter" / "README.md",
        )
        for path in discoverability_files:
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIn(
                    "REVIEW-DECISION-HANDOFF.md", path.read_text(encoding="utf-8")
                )

    def test_saved_handoff_tamper_and_type_aliases_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chain = self.create_complete_chain(root)
            built = self.run_builder(chain)
            self.assertEqual(built.returncode, 0, built.stdout.decode("utf-8"))
            original = json.loads(built.stdout)
            handoff_path = root / "saved-decision-handoff.json"
            mutations = {
                "unknown field": lambda value: value.__setitem__(
                    "private_sentinel", "PRIVATE_SENTINEL_DO_NOT_ECHO"
                ),
                "overall decision": lambda value: value[
                    "decision_requirements"
                ].__setitem__("decision", "accept"),
                "selected outcome": lambda value: value[
                    "decision_requirements"
                ].__setitem__("selected_outcome", "accept"),
                "authority claim": lambda value: value["claims"].__setitem__(
                    "decision_maker_authority_verified", True
                ),
                "boolean byte alias": lambda value: value["artifact_bindings"][
                    "response"
                ].__setitem__("bytes", True),
                "float count alias": lambda value: value[
                    "candidate_binding"
                ].__setitem__("binding_count", 22.0),
            }
            for label, mutate in mutations.items():
                with self.subTest(label=label):
                    value = json.loads(json.dumps(original))
                    mutate(value)
                    self.save_json(handoff_path, value)
                    result = self.run_handoff_verifier(chain, handoff_path)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, b"")
                    self.assertNotIn(b"PRIVATE_SENTINEL_DO_NOT_ECHO", result.stdout)
                    report = json.loads(result.stdout)
                    self.assertEqual(report["status"], "DECISION_HANDOFF_MISMATCH")
                    self.assertEqual(report["reason"], "HANDOFF_MISMATCH")
                    self.assertIsNone(report["pack_id"])
                    self.assertIsNone(report["artifact_bindings"])
                    self.assertIsNone(report["handoff_binding"])
                    self.assertIsNone(report["decision_requirements"]["decision"])
                    self.assertTrue(
                        all(value is False for value in report["claims"].values())
                    )

    def test_saved_handoff_strict_json_boundary_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chain = self.create_complete_chain(root)
            handoff_path = root / "saved-decision-handoff.json"
            deep: object = None
            for _ in range(70):
                deep = [deep]
            cases = {
                "missing": None,
                "empty": b"",
                "invalid utf8": b"\xff",
                "duplicate key": b'{"kind":"a","kind":"b"}',
                "nonfinite": b'{"value":NaN}',
                "too deep": json.dumps({"value": deep}).encode("utf-8"),
                "oversized": b'{"value":"' + b"x" * (1024 * 1024) + b'"}',
            }
            for label, data in cases.items():
                with self.subTest(label=label):
                    if data is None:
                        handoff_path.unlink(missing_ok=True)
                    else:
                        handoff_path.write_bytes(data)
                    result = self.run_handoff_verifier(chain, handoff_path)
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, b"")
                    report = json.loads(result.stdout)
                    self.assertEqual(report["status"], "DECISION_HANDOFF_MISMATCH")
                    self.assertEqual(report["reason"], "HANDOFF_INVALID")
                    self.assertIsNone(report["handoff_binding"])
                    self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_output_is_deterministic_utf8_and_usage_does_not_reflect_arguments(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chain = self.create_complete_chain(root)
            legacy_env = dict(os.environ)
            legacy_env["PYTHONIOENCODING"] = "cp1252"
            first = self.run_builder(chain, env=legacy_env)
            second = self.run_builder(chain, env=legacy_env)
            self.assertEqual(first.returncode, 0)
            self.assertEqual(first.stdout, second.stdout)
            self.assertEqual(
                json.loads(first.stdout.decode("utf-8"))["status"],
                "CANDIDATE_DECISION_HANDOFF",
            )
            handoff_path = root / "saved-decision-handoff.json"
            handoff_path.write_bytes(first.stdout)
            first_verification = self.run_handoff_verifier(
                chain, handoff_path, env=legacy_env
            )
            second_verification = self.run_handoff_verifier(
                chain, handoff_path, env=legacy_env
            )
            self.assertEqual(first_verification.returncode, 0)
            self.assertEqual(first_verification.stdout, second_verification.stdout)

            sentinel = Path("PRIVATE_SENTINEL_DO_NOT_ECHO")
            paths = chain["paths"]
            builder_usage = self.run_cli(
                HANDOFF_BUILDER,
                paths["bundle"],
                chain["pack"],
                paths["bundle_verification"],
                paths["request"],
                paths["response"],
                paths["response_verification"],
                sentinel,
            )
            verifier_usage = self.run_cli(
                HANDOFF_VERIFIER,
                paths["bundle"],
                chain["pack"],
                paths["bundle_verification"],
                paths["request"],
                paths["response"],
                paths["response_verification"],
                handoff_path,
                sentinel,
            )

        for result in (builder_usage, verifier_usage):
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"usage:", result.stderr)
            self.assertNotIn(bytes(sentinel), result.stderr)

    def test_final_rereads_refuse_source_or_handoff_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chain = self.create_complete_chain(root)
            paths = chain["paths"]
            initial_reads = [
                paths[name].read_bytes() for name in handoff_builder.ARTIFACT_NAMES
            ]
            with mock.patch.object(
                handoff_builder,
                "read_limited_bytes",
                side_effect=[*initial_reads, initial_reads[0] + b" "],
            ):
                report = handoff_builder.build_decision_handoff(
                    paths["bundle"],
                    chain["pack"],
                    paths["bundle_verification"],
                    paths["request"],
                    paths["response"],
                    paths["response_verification"],
                )
            self.assertEqual(report["status"], "HANDOFF_BUILD_REFUSED")
            self.assertEqual(report["reason"], "SOURCE_DRIFT_DETECTED")
            self.assertIsNone(report["artifact_bindings"])

            built = self.run_builder(chain)
            self.assertEqual(built.returncode, 0, built.stdout.decode("utf-8"))
            handoff_path = root / "saved-decision-handoff.json"
            handoff_path.write_bytes(built.stdout)
            with mock.patch.object(
                handoff_verifier,
                "read_limited_bytes",
                return_value=built.stdout + b" ",
            ):
                verification = handoff_verifier.verify_decision_handoff(
                    paths["bundle"],
                    chain["pack"],
                    paths["bundle_verification"],
                    paths["request"],
                    paths["response"],
                    paths["response_verification"],
                    handoff_path,
                )
            self.assertEqual(
                verification["status"], "DECISION_HANDOFF_MISMATCH"
            )
            self.assertEqual(verification["reason"], "SOURCE_DRIFT_DETECTED")
            self.assertIsNone(verification["handoff_binding"])

    def test_pack_change_after_final_request_rebuild_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chain = self.create_complete_chain(root)
            paths = chain["paths"]
            pack_file = chain["pack"] / "records" / "source-record.json"
            original_build_request = handoff_builder.build_review_request
            call_count = 0

            def rebuild_then_change_pack(bundle_path: Path, pack_dir: Path):
                nonlocal call_count
                result = original_build_request(bundle_path, pack_dir)
                call_count += 1
                if call_count == 2:
                    pack_file.write_bytes(pack_file.read_bytes() + b"\n")
                return result

            with mock.patch.object(
                handoff_builder,
                "build_review_request",
                side_effect=rebuild_then_change_pack,
            ):
                report = handoff_builder.build_decision_handoff(
                    paths["bundle"],
                    chain["pack"],
                    paths["bundle_verification"],
                    paths["request"],
                    paths["response"],
                    paths["response_verification"],
                )

        self.assertEqual(call_count, 2)
        self.assertEqual(report["status"], "HANDOFF_BUILD_REFUSED")
        self.assertEqual(report["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertIsNone(report["artifact_bindings"])

    def test_verifier_pack_change_after_second_handoff_rebuild_is_refused(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            chain = self.create_complete_chain(root)
            paths = chain["paths"]
            built = self.run_builder(chain)
            self.assertEqual(built.returncode, 0, built.stdout.decode("utf-8"))
            handoff_path = root / "saved-decision-handoff.json"
            handoff_path.write_bytes(built.stdout)
            pack_file = chain["pack"] / "records" / "source-record.json"
            original_build_handoff = handoff_verifier.build_decision_handoff
            call_count = 0

            def rebuild_then_change_pack(*arguments):
                nonlocal call_count
                result = original_build_handoff(*arguments)
                call_count += 1
                if call_count == 2:
                    pack_file.write_bytes(pack_file.read_bytes() + b"\n")
                return result

            with mock.patch.object(
                handoff_verifier,
                "build_decision_handoff",
                side_effect=rebuild_then_change_pack,
            ):
                report = handoff_verifier.verify_decision_handoff(
                    paths["bundle"],
                    chain["pack"],
                    paths["bundle_verification"],
                    paths["request"],
                    paths["response"],
                    paths["response_verification"],
                    handoff_path,
                )

        self.assertEqual(call_count, 3)
        self.assertEqual(report["status"], "DECISION_HANDOFF_MISMATCH")
        self.assertEqual(report["reason"], "SOURCE_DRIFT_DETECTED")
        self.assertIsNone(report["handoff_binding"])

    def _mutate_json(self, path: Path, mutation) -> None:
        value = json.loads(path.read_bytes())
        mutation(value)
        self.save_json(path, value)


if __name__ == "__main__":
    unittest.main()
