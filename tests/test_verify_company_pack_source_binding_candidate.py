from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from jsonschema import Draft202012Validator, FormatChecker

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from test_company_pack_source_record_instance_contract import (
    USES,
    source_record_instance,
)
import verify_company_pack_source_binding_candidate as verifier


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "verify_company_pack_source_binding_candidate.py"
REPORT_SCHEMA = (
    ROOT / "schemas" / "company-pack-source-binding-verification-candidate.schema.json"
)
EVIDENCE_SCHEMA = (
    ROOT / "schemas" / "company-pack-source-access-projection-evidence.schema.json"
)
RUNBOOK = ROOT / "docs" / "SOURCE-BINDING-VERIFIER-CANDIDATE.md"
R31_SCHEMA = ROOT / "schemas" / "company-pack-source-record-instance.schema.json"
R30_SCHEMA = ROOT / "schemas" / "company-pack-intent-candidate-instance.schema.json"


def binding(content: bytes) -> dict[str, object]:
    return {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def matched_inputs(
    state: str = "CONTENT_BINDING_RECORDED_UNVERIFIED",
) -> tuple[dict, bytes, dict]:
    record = source_record_instance(state)
    content = b"synthetic source bytes for R32 only\n"
    record["content_observation"]["content_binding"] = binding(content)
    record["acquisition_provenance"]["output_binding"] = binding(content)
    permitted: list[str] = []
    for use in USES:
        declaration = record["access_or_consent"]["use_declarations"][use]
        if declaration["declaration_status"] == "DECLARED_PERMITTED_UNVERIFIED":
            permitted.append(use)
            declaration["purpose_scope_ref"] = "ref/use-purpose/common"
            declaration["subject_scope_ref"] = "ref/use-subject/common"
    record_bytes = canonical_bytes(record)
    evidence = {
        "kind": "company_pack_source_access_projection_evidence",
        "version": "1.0",
        "status": "CANDIDATE_ONLY",
        "source_record_id_sha256": hashlib.sha256(
            record["source_record_id"].encode("utf-8")
        ).hexdigest(),
        "source_record_binding": binding(record_bytes),
        "source_content_binding": binding(content),
        "common_purpose_scope_ref": "ref/use-purpose/common",
        "declared_permitted_uses": permitted,
        "subject_scope_ref": "ref/use-subject/common",
        "scope_expires_at": "2026-08-04T17:20:00+09:00",
        "revocation_evidence_ref": None,
        "basis_ref": record["access_or_consent"]["basis_ref"],
        "basis_binding": record["access_or_consent"]["basis_binding"],
        "use_evidence_bindings": {
            use: {
                "evidence_ref": record["access_or_consent"]["use_declarations"][use][
                    "evidence_ref"
                ],
                "evidence_binding": record["access_or_consent"]["use_declarations"][use][
                    "evidence_binding"
                ],
            }
            for use in permitted
        },
        "recorded_at": "2026-08-03T17:21:00+09:00",
        "expires_at": "2026-08-03T18:20:00+09:00",
        "claims": {
            "access_or_consent_verified": False,
            "evidence_authenticity_verified": False,
            "human_authority_verified": False,
            "retention_enforced": False,
            "source_authenticity_verified": False,
        },
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    return record, content, evidence


def expected_projection_bytes(
    record: dict,
    evidence_bytes: bytes,
    record_bytes: bytes,
    record_locator: str = "ref/source-record/serialized",
    evidence_locator: str = "ref/access-consent/aggregate",
) -> bytes:
    declarations = record["access_or_consent"]["use_declarations"]
    permitted = [
        use
        for use in USES
        if declarations[use]["declaration_status"] == "DECLARED_PERMITTED_UNVERIFIED"
    ]
    first = declarations[permitted[0]]
    content = record["content_observation"]
    retention = record["retention"]
    projection = {
        "source_record_locator": record_locator,
        "source_record_binding": binding(record_bytes),
        "source_content_locator": content["storage_locator_ref"],
        "source_content_binding": content["content_binding"],
        "declared_media_type": content["declared_media_type"],
        "source_revision": record["source_revision"],
        "observed_at": content["observed_at"],
        "source_record_schema_status": "NOT_VERIFIED",
        "derived_from_refs": (
            []
            if record["lineage"]["lineage_kind"] == "DECLARED_ORIGINAL"
            else record["lineage"]["parent_source_record_refs"]
        ),
        "lineage_status": "NOT_VERIFIED",
        "access_or_consent": {
            "evidence_ref": evidence_locator,
            "evidence_binding": binding(evidence_bytes),
            "declared_permitted_uses": permitted,
            "subject_scope_ref": first["subject_scope_ref"],
            "scope_expires_at": first["scope_expires_at"],
            "revocation_evidence_ref": first["revocation_evidence_ref"],
            "verification_status": "NOT_VERIFIED",
        },
        "retention": {
            key: retention[key]
            for key in (
                "policy_ref",
                "policy_binding",
                "retain_until",
                "deletion_trigger",
                "deletion_receipt_ref",
                "enforcement_status",
            )
        },
    }
    return json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


class SourceBindingVerificationCandidateTests(unittest.TestCase):
    def run_raw(
        self,
        record_bytes: bytes,
        content: bytes,
        evidence_bytes: bytes,
        record_locator: str = "ref/source-record/serialized",
        evidence_locator: str = "ref/access-consent/aggregate",
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_path = root / "private-record-PHYSICAL-MARKER.json"
            content_path = root / "private-content-PHYSICAL-MARKER.bin"
            evidence_path = root / "private-evidence-PHYSICAL-MARKER.json"
            record_path.write_bytes(record_bytes)
            content_path.write_bytes(content)
            evidence_path.write_bytes(evidence_bytes)
            return subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    str(record_path),
                    str(content_path),
                    str(evidence_path),
                    record_locator,
                    evidence_locator,
                ],
                text=True,
                capture_output=True,
                check=False,
            )

    def run_tool(
        self,
        record: dict,
        content: bytes,
        evidence: dict,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            record_path = root / "record.json"
            content_path = root / "content.bin"
            evidence_path = root / "access-evidence.json"
            record_path.write_bytes(canonical_bytes(record))
            content_path.write_bytes(content)
            evidence_path.write_bytes(canonical_bytes(evidence))
            return subprocess.run(
                [
                    sys.executable,
                    str(TOOL),
                    str(record_path),
                    str(content_path),
                    str(evidence_path),
                    "ref/source-record/serialized",
                    "ref/access-consent/aggregate",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

    def test_narrow_match_is_deterministic_non_reflective_and_no_go(self) -> None:
        for path in (TOOL, REPORT_SCHEMA, EVIDENCE_SCHEMA, RUNBOOK):
            self.assertTrue(path.is_file(), path)

        record, content, evidence = matched_inputs()
        first = self.run_tool(record, content, evidence)
        second = self.run_tool(record, content, evidence)

        self.assertEqual(first.returncode, 0, (first.stdout, first.stderr))
        self.assertEqual(second.returncode, 0, (second.stdout, second.stderr))
        self.assertEqual(first.stdout, second.stdout)
        self.assertEqual(first.stderr, "")
        report = json.loads(first.stdout)
        self.assertEqual(report["status"], "CANDIDATE_ONLY")
        self.assertEqual(report["result"], "SOURCE_BINDING_MATCH_POINT_IN_TIME")
        self.assertEqual(
            report["r31_input_status"],
            "PARSED_PROJECTION_CONTRACT_MATCHED_UNVERIFIED",
        )
        self.assertEqual(report["read_set_status"], "STABLE_POSTCHECK_UNVERIFIED")
        self.assertEqual(report["r30_projection_eligibility"], "ELIGIBLE_UNVERIFIED")
        self.assertEqual(report["reason_codes"], [])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertTrue(report["claims"]["strict_input_parsing_matched"])
        self.assertTrue(report["claims"]["stable_read_set_reread_matched"])
        self.assertTrue(report["claims"]["r30_projection_digest_computed"])
        self.assertFalse(report["claims"]["full_r31_schema_verified"])
        self.assertFalse(report["claims"]["atomic_multi_file_snapshot_verified"])
        self.assertFalse(report["claims"]["access_or_consent_verified"])
        self.assertFalse(report["claims"]["source_authenticity_verified"])
        self.assertFalse(report["claims"]["public_beta_go"])
        self.assertRegex(
            report["r30_projection_digest_candidate"]["sha256"],
            r"^[0-9a-f]{64}$",
        )
        self.assertGreater(report["r30_projection_digest_candidate"]["bytes"], 0)

        serialized = first.stdout + first.stderr
        for forbidden in (
            str(Path(tempfile.gettempdir())),
            "synthetic source bytes",
            record["source_record_id"],
            record["content_observation"]["storage_locator_ref"],
            "ref/source-record/serialized",
            "ref/access-consent/aggregate",
        ):
            self.assertNotIn(forbidden, serialized)

        report_schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(report_schema)
        Draft202012Validator(
            report_schema,
            format_checker=FormatChecker(),
        ).validate(report)
        report_validator = Draft202012Validator(
            report_schema,
            format_checker=FormatChecker(),
        )
        for name, mutation in (
            ("missing projection", json.loads(json.dumps(report))),
            ("false narrow claim", json.loads(json.dumps(report))),
            ("atomic overclaim", json.loads(json.dumps(report))),
            ("wrong read status", json.loads(json.dumps(report))),
            ("refusal preserving success states", json.loads(json.dumps(report))),
        ):
            if name == "missing projection":
                mutation["r30_projection_digest_candidate"] = None
            elif name == "false narrow claim":
                mutation["claims"]["strict_input_parsing_matched"] = False
            elif name == "atomic overclaim":
                mutation["claims"]["atomic_multi_file_snapshot_verified"] = True
            elif name == "wrong read status":
                mutation["read_set_status"] = "NOT_EVALUATED"
            else:
                mutation["result"] = "REFUSED"
                mutation["reason_codes"] = ["INPUT_INVALID"]
                mutation["r30_projection_digest_candidate"] = None
                for claim in verifier.NARROW_CLAIMS:
                    mutation["claims"][claim] = False
            with self.subTest(report_schema=name):
                self.assertTrue(list(report_validator.iter_errors(mutation)))
        evidence_schema = json.loads(EVIDENCE_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(evidence_schema)
        Draft202012Validator(
            evidence_schema,
            format_checker=FormatChecker(),
        ).validate(evidence)

    def test_strict_json_limits_types_and_refs_are_non_reflective_refusals(self) -> None:
        record, content, evidence = matched_inputs()
        record_bytes = canonical_bytes(record)
        evidence_bytes = canonical_bytes(evidence)
        private_marker = "PRIVATE-R32-MARKER-DO-NOT-REFLECT"
        deep: object = private_marker
        for _ in range(40):
            deep = {"nested": deep}
        many_nodes = {f"key-{index}": index for index in range(10_100)}
        recursive_json = b'{"nested":' * 1_100 + b"0" + b"}" * 1_100
        huge_integer_json = (
            b'{"value":'
            + b"9" * 5_000
            + b',"marker":"'
            + private_marker.encode()
            + b'"}'
        )

        bool_size = json.loads(json.dumps(evidence))
        bool_size["source_content_binding"]["bytes"] = True
        cases = [
            (
                b'{"kind":"' + private_marker.encode() + b'","kind":"duplicate"}',
                evidence_bytes,
                "STRICT_JSON_INVALID",
            ),
            (record_bytes, b'{"value":NaN,"marker":"' + private_marker.encode() + b'"}', "STRICT_JSON_INVALID"),
            (b"\xef\xbb\xbf" + record_bytes, evidence_bytes, "STRICT_JSON_INVALID"),
            (b"\xff" + private_marker.encode(), evidence_bytes, "STRICT_JSON_INVALID"),
            (b'{"value":"\\ud800","marker":"' + private_marker.encode() + b'"}', evidence_bytes, "STRICT_JSON_INVALID"),
            (b'["' + private_marker.encode() + b'"]', evidence_bytes, "STRICT_JSON_INVALID"),
            (canonical_bytes(deep), evidence_bytes, "STRICT_JSON_INVALID"),
            (record_bytes, canonical_bytes(many_nodes), "STRICT_JSON_INVALID"),
            (
                record_bytes,
                b'{"value":1e9999,"marker":"' + private_marker.encode() + b'"}',
                "STRICT_JSON_INVALID",
            ),
            (record_bytes, huge_integer_json, "STRICT_JSON_INVALID"),
            (recursive_json, evidence_bytes, "STRICT_JSON_INVALID"),
            (record_bytes, canonical_bytes(bool_size), "ACCESS_EVIDENCE_CONTRACT_MISMATCH"),
        ]
        for hostile_record, hostile_evidence, expected_reason in cases:
            with self.subTest(expected_reason=expected_reason, size=len(hostile_record)):
                result = self.run_raw(hostile_record, content, hostile_evidence)
                self.assertEqual(result.returncode, 1, (result.stdout, result.stderr))
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "CANDIDATE_ONLY")
                self.assertEqual(report["result"], "REFUSED")
                self.assertEqual(report["reason_codes"], [expected_reason])
                self.assertEqual(result.stderr, "")
                reflected = result.stdout + result.stderr
                for forbidden in (
                    private_marker,
                    "PHYSICAL-MARKER",
                    "private-record",
                    "surrogate",
                    "duplicate",
                    "non-finite",
                ):
                    self.assertNotIn(forbidden, reflected)

        for bad_ref in (
            private_marker,
            "C:/private/source.json",
            "../private/source.json",
            "https://private.invalid/source",
        ):
            with self.subTest(ref=bad_ref):
                result = self.run_raw(
                    record_bytes,
                    content,
                    evidence_bytes,
                    record_locator=bad_ref,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)["reason_codes"], ["INPUT_INVALID"])
                self.assertNotIn(bad_ref, result.stdout + result.stderr)

        malformed_evidence = self.run_raw(
            record_bytes,
            content,
            b'{"value":NaN}',
        )
        malformed_report = json.loads(malformed_evidence.stdout)
        self.assertEqual(
            malformed_report["r31_input_status"],
            "STRICTLY_PARSED_UNVERIFIED",
        )
        self.assertEqual(malformed_report["reason_codes"], ["STRICT_JSON_INVALID"])

    def test_projection_digest_matches_independent_r30_mapping_for_both_states(self) -> None:
        r30_schema = json.loads(R30_SCHEMA.read_text(encoding="utf-8"))
        source_binding_schema = {
            "$schema": r30_schema["$schema"],
            "$defs": r30_schema["$defs"],
            **r30_schema["$defs"]["source_binding"],
        }
        r30_validator = Draft202012Validator(
            source_binding_schema,
            format_checker=FormatChecker(),
        )
        for state in (
            "CONTENT_BINDING_RECORDED_UNVERIFIED",
            "DERIVED_CONTENT_BINDING_RECORDED_UNVERIFIED",
        ):
            with self.subTest(state=state):
                record, content, evidence = matched_inputs(state)
                result = self.run_tool(record, content, evidence)
                self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
                report = json.loads(result.stdout)
                expected = expected_projection_bytes(
                    record,
                    canonical_bytes(evidence),
                    canonical_bytes(record),
                )
                r30_validator.validate(json.loads(expected))
                self.assertEqual(
                    report["r30_projection_digest_candidate"],
                    binding(expected),
                )
                self.assertNotIn(expected.decode("utf-8"), result.stdout)

        record, content, evidence = matched_inputs()
        first = self.run_tool(record, content, evidence)
        changed_locator = self.run_raw(
            canonical_bytes(record),
            content,
            canonical_bytes(evidence),
            record_locator="ref/source-record/alternate",
        )
        self.assertEqual(first.returncode, 0)
        self.assertEqual(changed_locator.returncode, 0)
        self.assertNotEqual(
            json.loads(first.stdout)["r30_projection_digest_candidate"],
            json.loads(changed_locator.stdout)["r30_projection_digest_candidate"],
        )
        self.assertNotIn("alternate", changed_locator.stdout)

    def test_all_r31_eligible_acquisition_modes_match_and_media_contract_is_exact(self) -> None:
        r31_schema = json.loads(R31_SCHEMA.read_text(encoding="utf-8"))
        r31_validator = Draft202012Validator(
            r31_schema,
            format_checker=FormatChecker(),
        )
        for mode in ("capture", "import", "synthetic"):
            record, content, evidence = matched_inputs()
            record["acquisition_mode"] = mode
            evidence["source_record_binding"] = binding(canonical_bytes(record))
            with self.subTest(mode=mode):
                r31_validator.validate(record)
                result = self.run_tool(record, content, evidence)
                self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
                self.assertEqual(
                    json.loads(result.stdout)["result"],
                    "SOURCE_BINDING_MATCH_POINT_IN_TIME",
                )

        record, content, evidence = matched_inputs()
        record["content_observation"]["declared_media_type"] = (
            "application/json;charset=utf-8"
        )
        refused = self.run_tool(record, content, evidence)
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(
            json.loads(refused.stdout)["reason_codes"],
            ["RECORD_CONTRACT_MISMATCH"],
        )

    def test_projection_relevant_time_ordering_is_fail_closed(self) -> None:
        record, content, evidence = matched_inputs()
        cases: list[tuple[str, dict]] = []
        started_after_completed = json.loads(json.dumps(record))
        started_after_completed["acquisition_provenance"]["started_at"] = (
            "2026-08-03T17:21:00+09:00"
        )
        cases.append(("started after completed", started_after_completed))
        completed_after_observed = json.loads(json.dumps(record))
        completed_after_observed["acquisition_provenance"]["completed_at"] = (
            "2026-08-03T17:21:00+09:00"
        )
        cases.append(("completed after content observation", completed_after_observed))
        content_after_recorded = json.loads(json.dumps(record))
        content_after_recorded["content_observation"]["observed_at"] = (
            "2026-08-03T17:21:00+09:00"
        )
        cases.append(("content observed after record", content_after_recorded))
        source_after_recorded = json.loads(json.dumps(record))
        source_after_recorded["source_observed_at"] = "2026-08-03T17:21:00+09:00"
        cases.append(("source observed after record", source_after_recorded))

        for name, mutation in cases:
            with self.subTest(name=name):
                refused = self.run_tool(mutation, content, evidence)
                self.assertEqual(refused.returncode, 1)
                self.assertEqual(
                    json.loads(refused.stdout)["reason_codes"],
                    ["RECORD_CONTRACT_MISMATCH"],
                )

    def test_consumed_r31_subset_rejects_out_of_schema_projection_loss(self) -> None:
        cases: list[tuple[str, dict, bytes, dict]] = []

        record, content, evidence = matched_inputs()
        manual_trigger = json.loads(json.dumps(record))
        manual_trigger["retention"]["deletion_trigger"] = "manual_review"
        cases.append(("manual deletion trigger", manual_trigger, content, evidence))

        unknown_coverage = json.loads(json.dumps(record))
        unknown_coverage["retention"]["covered_artifacts"].append(
            "private_unknown_artifact"
        )
        cases.append(("unknown retention coverage", unknown_coverage, content, evidence))

        original_segmentation = json.loads(json.dumps(record))
        original_segmentation["lineage"]["segmentation_ref"] = (
            "ref/segmentation/unexpected"
        )
        cases.append(("original segmentation", original_segmentation, content, evidence))

        derived, derived_content, derived_evidence = matched_inputs(
            "DERIVED_CONTENT_BINDING_RECORDED_UNVERIFIED"
        )
        derived["lineage"]["parent_source_record_refs"] = [
            f"ref/source-record/parent-{index:02d}" for index in range(17)
        ]
        derived["lineage"]["transformation_refs"] = [
            f"ref/transformation/item-{index:02d}" for index in range(17)
        ]
        cases.append(("oversized lineage", derived, derived_content, derived_evidence))

        for name, mutation, case_content, case_evidence in cases:
            case_evidence = json.loads(json.dumps(case_evidence))
            case_evidence["source_record_binding"] = binding(canonical_bytes(mutation))
            with self.subTest(name=name):
                refused = self.run_tool(mutation, case_content, case_evidence)
                self.assertEqual(refused.returncode, 1, (refused.stdout, refused.stderr))
                self.assertEqual(
                    json.loads(refused.stdout)["reason_codes"],
                    ["RECORD_CONTRACT_MISMATCH"],
                )

    def test_r31_projection_loss_and_binding_drift_fail_closed(self) -> None:
        base_record, content, base_evidence = matched_inputs()
        cases: list[tuple[str, dict]] = []

        reference = source_record_instance("REFERENCE_DECLARED_UNVERIFIED")
        cases.append(("reference", reference))
        withdrawal = source_record_instance("WITHDRAWAL_RECORDED_UNVERIFIED")
        withdrawal["content_observation"]["content_binding"] = binding(content)
        withdrawal["acquisition_provenance"]["output_binding"] = binding(content)
        cases.append(("withdrawal", withdrawal))

        per_use_withdrawal = json.loads(json.dumps(base_record))
        per_use_withdrawal["access_or_consent"]["use_declarations"]["read"][
            "declaration_status"
        ] = "WITHDRAWAL_ENTERED_UNVERIFIED"
        per_use_withdrawal["access_or_consent"]["use_declarations"]["read"][
            "revocation_evidence_ref"
        ] = "ref/use-revocation/read"
        cases.append(("per-use withdrawal", per_use_withdrawal))

        no_permitted = json.loads(json.dumps(base_record))
        for declaration in no_permitted["access_or_consent"]["use_declarations"].values():
            declaration["declaration_status"] = "DECLARED_NOT_PERMITTED"
        cases.append(("no permitted use", no_permitted))

        for field, value in (
            ("purpose_scope_ref", "ref/use-purpose/other"),
            ("subject_scope_ref", "ref/use-subject/other"),
            ("scope_expires_at", "2026-08-04T17:21:00+09:00"),
            ("revocation_evidence_ref", "ref/use-revocation/other"),
        ):
            changed = json.loads(json.dumps(base_record))
            changed["access_or_consent"]["use_declarations"]["read"][field] = value
            cases.append((f"lossy {field}", changed))

        revision = json.loads(json.dumps(base_record))
        revision["content_observation"]["declared_source_revision"] = (
            "ref/source-revision/other"
        )
        cases.append(("revision", revision))
        retention = json.loads(json.dumps(base_record))
        retention["retention"]["covered_artifacts"] = [
            "source_record_serialized_bytes"
        ]
        cases.append(("retention", retention))
        lineage = json.loads(json.dumps(base_record))
        lineage["lineage"]["parent_source_record_refs"] = [
            "ref/source-record/unexpected"
        ]
        cases.append(("lineage", lineage))
        content_drift = json.loads(json.dumps(base_record))
        content_drift["content_observation"]["content_binding"]["sha256"] = "0" * 64
        cases.append(("content binding", content_drift))

        for name, record in cases:
            with self.subTest(name=name):
                result = self.run_tool(record, content, base_evidence)
                self.assertEqual(result.returncode, 1, (result.stdout, result.stderr))
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "CANDIDATE_ONLY")
                self.assertEqual(report["result"], "REFUSED")
                self.assertIn(
                    report["reason_codes"][0],
                    {"R30_PROJECTION_INELIGIBLE", "RECORD_CONTRACT_MISMATCH"},
                )
                self.assertIsNone(report["r30_projection_digest_candidate"])
                self.assertFalse(report["claims"]["r30_projection_digest_computed"])
                self.assertFalse(report["claims"]["access_or_consent_verified"])

        unknown_state = json.loads(json.dumps(base_record))
        unknown_state["source_state"] = "PRIVATE-UNKNOWN-STATE"
        unknown = self.run_tool(unknown_state, content, base_evidence)
        self.assertEqual(unknown.returncode, 1)
        self.assertEqual(
            json.loads(unknown.stdout)["reason_codes"],
            ["RECORD_CONTRACT_MISMATCH"],
        )

    def test_fixed_r31_denial_claims_and_review_triggers_fail_closed(self) -> None:
        base_record, content, _ = matched_inputs()
        cases: list[tuple[str, dict]] = []

        missing_claim = json.loads(json.dumps(base_record))
        del missing_claim["claims"]["public_beta_go"]
        cases.append(("missing denial claim", missing_claim))

        unknown_claim = json.loads(json.dumps(base_record))
        unknown_claim["claims"]["private_false_claim"] = False
        cases.append(("unknown denial claim", unknown_claim))

        overclaim = json.loads(json.dumps(base_record))
        overclaim["claims"]["source_authenticity_verified"] = True
        cases.append(("true denial claim", overclaim))

        missing_trigger = json.loads(json.dumps(base_record))
        missing_trigger["review_trigger"].pop()
        cases.append(("missing review trigger", missing_trigger))

        reordered_trigger = json.loads(json.dumps(base_record))
        reordered_trigger["review_trigger"][0:2] = reversed(
            reordered_trigger["review_trigger"][0:2]
        )
        cases.append(("reordered review trigger", reordered_trigger))

        unknown_trigger = json.loads(json.dumps(base_record))
        unknown_trigger["review_trigger"][-1] = "private-trigger-marker"
        cases.append(("unknown review trigger", unknown_trigger))

        for name, record in cases:
            with self.subTest(name=name):
                _, _, evidence = matched_inputs()
                evidence["source_record_binding"] = binding(canonical_bytes(record))
                result = self.run_tool(record, content, evidence)
                self.assertEqual(result.returncode, 1, (result.stdout, result.stderr))
                report = json.loads(result.stdout)
                self.assertEqual(report["reason_codes"], ["RECORD_CONTRACT_MISMATCH"])
                self.assertEqual(report["result"], "REFUSED")
                self.assertIsNone(report["r30_projection_digest_candidate"])
                self.assertTrue(all(value is False for value in report["claims"].values()))
                self.assertNotIn("private", result.stdout.lower() + result.stderr.lower())

    def test_access_projection_evidence_substitution_and_overclaim_fail_closed(self) -> None:
        record, content, evidence = matched_inputs()
        mutations: list[tuple[str, dict]] = []

        def changed(name: str) -> dict:
            value = json.loads(json.dumps(evidence))
            mutations.append((name, value))
            return value

        changed("record id")["source_record_id_sha256"] = "0" * 64
        changed("record bytes")["source_record_binding"]["sha256"] = "0" * 64
        changed("content bytes")["source_content_binding"]["bytes"] += 1
        changed("purpose")["common_purpose_scope_ref"] = "ref/use-purpose/other"
        changed("uses")["declared_permitted_uses"] = ["read", "store"]
        changed("subject")["subject_scope_ref"] = "ref/use-subject/other"
        changed("expiry")["scope_expires_at"] = "2026-08-04T17:21:00+09:00"
        changed("candidate expiry")["expires_at"] = "2026-08-03T18:21:00+09:00"
        changed("evidence predates record")["recorded_at"] = (
            "2026-08-03T17:19:00+09:00"
        )
        changed("revocation")["revocation_evidence_ref"] = (
            "ref/use-revocation/other"
        )
        changed("basis")["basis_binding"]["sha256"] = "0" * 64
        changed("use evidence")["use_evidence_bindings"]["read"][
            "evidence_binding"
        ]["sha256"] = "0" * 64
        changed("overclaim")["claims"]["access_or_consent_verified"] = True
        changed("unknown root")["private_payload"] = "PRIVATE-EVIDENCE-PAYLOAD"

        for name, mutation in mutations:
            with self.subTest(name=name):
                result = self.run_tool(record, content, mutation)
                self.assertEqual(result.returncode, 1, (result.stdout, result.stderr))
                report = json.loads(result.stdout)
                self.assertEqual(
                    report["reason_codes"],
                    ["ACCESS_EVIDENCE_CONTRACT_MISMATCH"],
                )
                self.assertFalse(report["claims"]["access_or_consent_verified"])
                self.assertIsNone(report["r30_projection_digest_candidate"])
                self.assertNotIn("PRIVATE-EVIDENCE-PAYLOAD", result.stdout + result.stderr)

    def test_expired_projection_scope_and_retention_refuse_at_evidence_time(self) -> None:
        record, content, evidence = matched_inputs()
        scope_expired = json.loads(json.dumps(record))
        for declaration in scope_expired["access_or_consent"]["use_declarations"].values():
            if declaration["declaration_status"] == "DECLARED_PERMITTED_UNVERIFIED":
                declaration["scope_expires_at"] = "2026-08-03T17:20:30+09:00"
        scope_evidence = json.loads(json.dumps(evidence))
        scope_evidence["scope_expires_at"] = "2026-08-03T17:20:30+09:00"
        scope_evidence["source_record_binding"] = binding(canonical_bytes(scope_expired))

        retention_expired = json.loads(json.dumps(record))
        retention_expired["retention"]["retain_until"] = (
            "2026-08-03T17:20:30+09:00"
        )
        retention_evidence = json.loads(json.dumps(evidence))
        retention_evidence["source_record_binding"] = binding(
            canonical_bytes(retention_expired)
        )

        for name, changed_record, changed_evidence in (
            ("access scope", scope_expired, scope_evidence),
            ("retention window", retention_expired, retention_evidence),
        ):
            with self.subTest(name=name):
                result = self.run_tool(changed_record, content, changed_evidence)
                self.assertEqual(result.returncode, 1, (result.stdout, result.stderr))
                report = json.loads(result.stdout)
                self.assertEqual(
                    report["reason_codes"],
                    ["ACCESS_EVIDENCE_CONTRACT_MISMATCH"],
                )
                self.assertEqual(report["result"], "REFUSED")
                self.assertIsNone(report["r30_projection_digest_candidate"])
                self.assertTrue(all(value is False for value in report["claims"].values()))

    def test_terminal_reread_refuses_byte_or_identity_drift_with_all_claims_false(self) -> None:
        record, content, evidence = matched_inputs()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            paths = (
                root / "record.json",
                root / "content.bin",
                root / "evidence.json",
            )
            paths[0].write_bytes(canonical_bytes(record))
            paths[1].write_bytes(content)
            paths[2].write_bytes(canonical_bytes(evidence))
            first = verifier.read_set(paths)
            byte_drift = (
                first[0],
                verifier.FileSnapshot(
                    content=first[1].content + b"x",
                    identity=(
                        first[1].identity[0],
                        first[1].identity[1],
                        first[1].identity[2] + 1,
                        first[1].identity[3] + 1,
                    ),
                ),
                first[2],
            )
            identity_drift = (
                verifier.FileSnapshot(
                    content=first[0].content,
                    identity=(
                        first[0].identity[0],
                        first[0].identity[1] + 1,
                        first[0].identity[2],
                        first[0].identity[3],
                    ),
                ),
                first[1],
                first[2],
            )
            for name, changed in (
                ("byte drift", byte_drift),
                ("same bytes identity substitution", identity_drift),
            ):
                with self.subTest(name=name), mock.patch.object(
                    verifier,
                    "read_set",
                    side_effect=[first, changed, changed],
                ):
                    report = verifier.evaluate(
                        paths[0],
                        paths[1],
                        paths[2],
                        "ref/source-record/serialized",
                        "ref/access-consent/aggregate",
                    )
                    self.assertEqual(report["status"], "CANDIDATE_ONLY")
                    self.assertEqual(report["result"], "REFUSED")
                    self.assertEqual(
                        report["reason_codes"],
                        ["SOURCE_DRIFT_DETECTED"],
                    )
                    self.assertEqual(report["read_set_status"], "LATE_DRIFT_DETECTED")
                    self.assertEqual(report["r30_projection_eligibility"], "INELIGIBLE")
                    self.assertEqual(report["checks"]["terminal_reread"], "MISMATCH")
                    self.assertIsNone(report["r30_projection_digest_candidate"])
                    self.assertTrue(all(value is False for value in report["claims"].values()))

    def test_stable_reader_rejects_empty_directory_over_limit_and_reparse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            empty = root / "empty.bin"
            empty.write_bytes(b"")
            oversized = root / "oversized.bin"
            oversized.write_bytes(b"12345")
            for path, maximum in ((empty, 4), (root, 4), (oversized, 4)):
                with self.subTest(path=path.name):
                    with self.assertRaises(verifier.StrictInputError):
                        verifier.stable_read(path, maximum)

            target = root / "target.bin"
            target.write_bytes(b"safe")
            link = root / "link.bin"
            try:
                link.symlink_to(target)
            except OSError:
                reparse_stat = SimpleNamespace(
                    st_file_attributes=getattr(
                        __import__("stat"),
                        "FILE_ATTRIBUTE_REPARSE_POINT",
                        0x400,
                    )
                )
                self.assertTrue(verifier.is_reparse(link, reparse_stat))
            else:
                with self.assertRaises(verifier.StrictInputError):
                    verifier.stable_read(link, 16)

    def test_cli_is_stdlib_only_single_line_canonical_and_has_fixed_usage(self) -> None:
        source = TOOL.read_text(encoding="utf-8")
        self.assertNotIn("import jsonschema", source)
        self.assertNotIn("from jsonschema", source)
        usage = subprocess.run(
            [sys.executable, str(TOOL)],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(usage.returncode, 2)
        self.assertEqual(usage.stdout, "")
        self.assertEqual(
            usage.stderr,
            "usage: verify_company_pack_source_binding_candidate.py "
            "SOURCE_RECORD_JSON SOURCE_CONTENT_FILE ACCESS_EVIDENCE_JSON "
            "SOURCE_RECORD_LOCATOR_REF ACCESS_EVIDENCE_LOCATOR_REF\n",
        )

        record, content, evidence = matched_inputs()
        result = self.run_tool(record, content, evidence)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.count("\n"), 1)
        self.assertTrue(result.stdout.endswith("\n"))
        self.assertEqual(
            result.stdout,
            json.dumps(json.loads(result.stdout), sort_keys=True) + "\n",
        )

    def test_locator_validation_precedes_file_reads_and_artifact_aliases_refuse(self) -> None:
        with mock.patch.object(verifier, "read_set") as read_set:
            report = verifier.evaluate(
                Path("PRIVATE-record"),
                Path("PRIVATE-content"),
                Path("PRIVATE-evidence"),
                "C:/PRIVATE/record.json",
                "ref/access-consent/aggregate",
            )
        read_set.assert_not_called()
        self.assertEqual(report["reason_codes"], ["INPUT_INVALID"])
        self.assertTrue(all(value is False for value in report["claims"].values()))

        with mock.patch.object(verifier, "read_set") as aliased_read_set:
            aliased_path_report = verifier.evaluate(
                Path("PRIVATE-same"),
                Path("PRIVATE-same"),
                Path("PRIVATE-evidence"),
                "ref/source-record/serialized",
                "ref/access-consent/aggregate",
            )
        aliased_read_set.assert_not_called()
        self.assertEqual(aliased_path_report["reason_codes"], ["INPUT_INVALID"])

        same_object = verifier.FileSnapshot(
            content=b"{}",
            identity=(1, 1, 2, 1),
        )
        with mock.patch.object(
            verifier,
            "read_set",
            return_value=(same_object, same_object, same_object),
        ):
            same_object_report = verifier.evaluate(
                Path("PRIVATE-record"),
                Path("PRIVATE-content"),
                Path("PRIVATE-evidence"),
                "ref/source-record/serialized",
                "ref/access-consent/aggregate",
            )
        self.assertEqual(same_object_report["reason_codes"], ["INPUT_INVALID"])

        record, content, evidence = matched_inputs()
        same_external = self.run_raw(
            canonical_bytes(record),
            content,
            canonical_bytes(evidence),
            record_locator="ref/source-record/same",
            evidence_locator="ref/source-record/same",
        )
        self.assertEqual(same_external.returncode, 1)
        self.assertEqual(
            json.loads(same_external.stdout)["reason_codes"],
            ["INPUT_INVALID"],
        )

        for name, record_locator, evidence_locator in (
            (
                "record aliases source item",
                record["source_locator_ref"],
                "ref/access-consent/aggregate",
            ),
            (
                "record aliases content",
                record["content_observation"]["storage_locator_ref"],
                "ref/access-consent/aggregate",
            ),
            (
                "evidence aliases content",
                "ref/source-record/serialized",
                record["content_observation"]["storage_locator_ref"],
            ),
        ):
            with self.subTest(name=name):
                result = self.run_raw(
                    canonical_bytes(record),
                    content,
                    canonical_bytes(evidence),
                    record_locator=record_locator,
                    evidence_locator=evidence_locator,
                )
                self.assertEqual(result.returncode, 1)
                self.assertEqual(
                    json.loads(result.stdout)["reason_codes"],
                    ["R30_PROJECTION_INELIGIBLE"],
                )

    def test_record_hash_binds_exact_raw_bytes_and_unknown_consumed_fields_refuse(self) -> None:
        record, content, evidence = matched_inputs()
        pretty_record = (
            json.dumps(record, ensure_ascii=False, sort_keys=False, indent=2).encode("utf-8")
            + b"\n"
        )
        evidence["source_record_binding"] = binding(pretty_record)
        result = self.run_raw(pretty_record, content, canonical_bytes(evidence))
        self.assertEqual(result.returncode, 0, (result.stdout, result.stderr))
        report = json.loads(result.stdout)
        self.assertEqual(report["evaluated_inputs"]["source_record"], binding(pretty_record))
        expected = expected_projection_bytes(
            record,
            canonical_bytes(evidence),
            pretty_record,
        )
        self.assertEqual(report["r30_projection_digest_candidate"], binding(expected))

        for name, mutation in (
            ("root", json.loads(json.dumps(record))),
            ("content", json.loads(json.dumps(record))),
            ("access", json.loads(json.dumps(record))),
            ("use declaration", json.loads(json.dumps(record))),
        ):
            if name == "root":
                mutation["private_payload"] = "PRIVATE-RECORD-MARKER"
            elif name == "content":
                mutation["content_observation"]["private_payload"] = (
                    "PRIVATE-RECORD-MARKER"
                )
            elif name == "access":
                mutation["access_or_consent"]["private_payload"] = (
                    "PRIVATE-RECORD-MARKER"
                )
            else:
                mutation["access_or_consent"]["use_declarations"]["read"][
                    "private_payload"
                ] = "PRIVATE-RECORD-MARKER"
            with self.subTest(name=name):
                refused = self.run_tool(mutation, content, evidence)
                self.assertEqual(refused.returncode, 1)
                self.assertEqual(
                    json.loads(refused.stdout)["reason_codes"],
                    ["RECORD_CONTRACT_MISMATCH"],
                )
                self.assertNotIn(
                    "PRIVATE-RECORD-MARKER",
                    refused.stdout + refused.stderr,
                )

    def test_runbook_is_discoverable_honest_and_no_populated_source_is_shipped(self) -> None:
        surfaces = [
            ROOT / "README.md",
            ROOT / "STATUS.md",
            ROOT / "ROADMAP.md",
            ROOT / "docs" / "VALIDATION.md",
            ROOT / "docs" / "SOURCE-RECORD-INSTANCE.md",
            ROOT / "docs" / "INTENT-CANDIDATE-INSTANCE.md",
            ROOT / "docs" / "STARTER-WALKTHROUGH.md",
            ROOT / "docs" / "TEMPLATE-GUIDE.md",
            ROOT / "docs" / "CUSTOMIZATION-CHECKLIST.md",
            ROOT / "examples" / "company-starter" / "README.md",
        ]
        for path in surfaces:
            self.assertIn(
                "SOURCE-BINDING-VERIFIER-CANDIDATE.md",
                path.read_text(encoding="utf-8"),
                path,
            )
        runbook = RUNBOOK.read_text(encoding="utf-8")
        for phrase in (
            "Ideal use",
            "Current implementation",
            "CANDIDATE_ONLY",
            "STABLE_POSTCHECK_UNVERIFIED",
            "ELIGIBLE_UNVERIFIED",
            "atomic snapshot",
            "Non-reflective refusal",
            "locatorのresolution",
            "Source authenticity",
            "consent/access authority",
            "retention enforcement",
            "Human Intent",
            "NO_GO_UNPUBLISHED",
        ):
            self.assertIn(phrase, runbook)
        self.assertFalse((ROOT / "examples" / "source-record-instance.json").exists())
        self.assertFalse((ROOT / "examples" / "source-content.bin").exists())
        self.assertFalse((ROOT / "examples" / "source-access-projection-evidence.json").exists())


if __name__ == "__main__":
    unittest.main()
