import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas" / "public-migration-ledger.schema.json"
VALIDATOR = ROOT / "tools" / "validate_public_migration_ledger.py"
FIXTURE = ROOT / "tests" / "fixtures" / "public-migration-ledger" / "valid.jsonl"
DOC = ROOT / "docs" / "PUBLIC-MIGRATION-LEDGER.md"
MATRIX = ROOT / "docs" / "SCHEMA-VALIDATOR-MATRIX.md"
MIGRATION_README = ROOT / "migration" / "README.md"

TERMINAL_CLASSIFICATIONS = [
    "PUBLIC_EXTRACT",
    "PRIVATE_RETAIN",
    "REGENERATE",
    "DROP",
]
TRANSFER_MODES = ["REAUTHOR", "GENERATE", "NO_COPY"]
GATE_NAMES = [
    "license_provenance",
    "secret_scan",
    "history_scan",
    "dependency_baseline",
    "independent_review",
]
CLAIM_FIELDS = [
    "migration_executed",
    "private_continuity_verified",
    "public_extract_published",
    "dependency_cutover_verified",
    "rollback_rehearsed",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
]


def _load_validator_module():
    spec = importlib.util.spec_from_file_location(
        "validate_public_migration_ledger", VALIDATOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("validator import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator_module = _load_validator_module()


class PublicMigrationLedgerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            json.loads(line)
            for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        ]
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    # --- helpers ---------------------------------------------------------

    def rechain(self, records: list[dict]) -> list[dict]:
        """Recompute prev_hash/content_hash so a mutation is not masked by a
        stale chain. Tests that target the chain itself skip this."""
        previous = validator_module.GENESIS_HASH
        for record in records:
            record["prev_hash"] = previous
            record.pop("content_hash", None)
            previous = validator_module.canonical_content_hash(record)
            record["content_hash"] = previous
        return records

    def run_validator(
        self, records: list[dict], anchor: str | None = None
    ) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    for r in records
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            command = [sys.executable, "-B", str(VALIDATOR), str(path)]
            if anchor is not None:
                command.extend(["--anchor", anchor])
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        return completed.returncode, json.loads(completed.stdout)

    def assert_refused(self, records: list[dict], reason: str) -> None:
        code, payload = self.run_validator(records)
        self.assertEqual(2, code, payload)
        self.assertEqual("REFUSED", payload["result"])
        self.assertIn(reason, payload["reason_codes"])

    def run_validator_with_anchor(
        self, records: list[dict], anchor: str
    ) -> tuple[int, dict]:
        return self.run_validator(records, anchor)

    def run_validator_path(self, path: Path) -> tuple[int, dict]:
        completed = subprocess.run(
            [sys.executable, "-B", str(VALIDATOR), str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return completed.returncode, json.loads(completed.stdout)

    # --- committed fixture ----------------------------------------------

    def test_committed_fixture_is_schema_valid_and_consistent(self) -> None:
        checker = Draft202012Validator(self.schema, format_checker=FormatChecker())
        for record in self.records:
            with self.subTest(sequence=record["sequence"]):
                self.assertEqual([], list(checker.iter_errors(record)))
        code, payload = self.run_validator(self.records)
        self.assertEqual(0, code, payload)
        self.assertEqual("LEDGER_CONSISTENT_UNVERIFIED", payload["result"])
        self.assertEqual(len(self.records), payload["record_count"])

    def test_result_never_asserts_a_claim_or_moves_the_public_gate(self) -> None:
        _, payload = self.run_validator(self.records)
        self.assertEqual("NO_GO_UNPUBLISHED", payload["public_beta"])
        for field in CLAIM_FIELDS:
            with self.subTest(field=field):
                self.assertIs(False, payload["claims"][field])

    def test_unanchored_result_is_explicitly_not_append_only_evidence(self) -> None:
        code, payload = self.run_validator(self.records)
        self.assertEqual(0, code, payload)
        self.assertEqual(
            {"provided": False, "matched": None}, payload["chain_anchor"]
        )

    def test_refusal_does_not_report_zero_unclassified(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["claims"]["migration_executed"] = True
        code, payload = self.run_validator(self.rechain(records))
        self.assertEqual(2, code, payload)
        self.assertIsNone(payload["zero_unclassified"])

    def test_unclassified_remainder_is_reported_not_hidden(self) -> None:
        _, payload = self.run_validator(self.records)
        counts = payload["terminal_classification_counts"]
        self.assertEqual(1, counts["UNCLASSIFIED_BLOCKED"])
        self.assertFalse(payload["zero_unclassified"])

        classified = copy.deepcopy(
            [r for r in self.records if r["terminal_classification"] is not None]
        )
        for index, record in enumerate(classified, start=1):
            record["sequence"] = index
        _, payload = self.run_validator(self.rechain(classified))
        self.assertEqual(0, payload["terminal_classification_counts"]["UNCLASSIFIED_BLOCKED"])
        self.assertTrue(payload["zero_unclassified"])

    # --- schema closure --------------------------------------------------

    def test_schema_is_closed_and_forces_every_claim_false(self) -> None:
        self.assertFalse(self.schema["additionalProperties"])
        self.assertFalse(self.schema["properties"]["gates"]["additionalProperties"])
        claims = self.schema["properties"]["claims"]
        self.assertFalse(claims["additionalProperties"])
        self.assertEqual(sorted(CLAIM_FIELDS), sorted(claims["required"]))
        for field in CLAIM_FIELDS:
            with self.subTest(field=field):
                self.assertIs(False, claims["properties"][field]["const"])
        self.assertEqual(
            "NO_GO_UNPUBLISHED", self.schema["properties"]["public_beta"]["const"]
        )

    def test_schema_separates_classification_from_transfer_mechanism(self) -> None:
        terminal = self.schema["properties"]["terminal_classification"]["oneOf"][0]["enum"]
        transfer = self.schema["properties"]["transfer_mode"]["oneOf"][0]["enum"]
        self.assertEqual(TERMINAL_CLASSIFICATIONS, terminal)
        self.assertEqual(TRANSFER_MODES, transfer)
        self.assertEqual(set(), set(terminal) & set(transfer))

    def test_schema_requires_digest_shaped_opaque_references(self) -> None:
        self.assertEqual(
            r"^ref/[0-9a-f]{64}$", self.schema["$defs"]["opaque_ref"]["pattern"]
        )
        self.assertEqual(
            "date-time", self.schema["$defs"]["timestamp"]["format"]
        )

    def test_unknown_property_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["private_path"] = "C:/private/thing"
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_non_opaque_subject_reference_is_rejected(self) -> None:
        for value in (
            "/etc/passwd",
            "C:/private/thing",
            "https://example.invalid/x",
            "ref/",
            "ref/participant/alice-smith",
            "ref/host/prod-01",
            "ref/provider/github/alice",
        ):
            with self.subTest(value=value):
                records = copy.deepcopy(self.records)
                records[0]["subject_ref"] = value
                self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_asserted_claim_is_rejected_by_the_schema(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["claims"]["migration_executed"] = True
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_transfer_mode_in_the_classification_field_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[1]["terminal_classification"] = "REAUTHOR"
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    # --- append-only ordering -------------------------------------------

    def test_sequence_gap_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[2]["sequence"] = 9
        records[3]["sequence"] = 10
        records[4]["sequence"] = 11
        self.assert_refused(self.rechain(records), "SEQUENCE_NOT_CONTIGUOUS")

    def test_duplicate_record_id_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[2]["record_id"] = records[1]["record_id"]
        self.assert_refused(self.rechain(records), "DUPLICATE_RECORD_ID")

    def test_out_of_order_timestamp_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[3]["recorded_at"] = "2026-08-23T00:00:00Z"
        self.assert_refused(self.rechain(records), "RECORDED_AT_NOT_MONOTONIC")

    def test_timestamp_must_be_a_real_date(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["recorded_at"] = "2026-02-30T25:61:61Z"
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_duplicate_json_key_in_a_line_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            line = json.dumps(self.records[0], sort_keys=True, separators=(",", ":"))
            tampered = line.replace('"version":"v1"', '"version":"v1","version":"v2"', 1)
            path.write_text(tampered + "\n", encoding="utf-8", newline="\n")
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
        self.assertEqual(2, completed.returncode)
        self.assertIn("INPUT_INVALID", json.loads(completed.stdout)["reason_codes"])

    def test_empty_ledger_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.jsonl"
            path.write_text("", encoding="utf-8", newline="\n")
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), str(path)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
        self.assertEqual(2, completed.returncode)
        self.assertIn("INPUT_INVALID", json.loads(completed.stdout)["reason_codes"])

    # --- tamper evidence -------------------------------------------------

    def test_content_digest_drift_is_detected(self) -> None:
        records = copy.deepcopy(self.records)
        records[2]["owner_ref"] = "ref/" + "a" * 64
        self.assert_refused(records, "CONTENT_DIGEST_DRIFT")

    def test_broken_hash_chain_is_detected(self) -> None:
        records = copy.deepcopy(self.records)
        records[3]["prev_hash"] = validator_module.GENESIS_HASH
        self.assert_refused(records, "HASH_CHAIN_BROKEN")

    def test_removing_a_record_breaks_the_chain(self) -> None:
        records = copy.deepcopy(self.records)
        del records[2]
        for index, record in enumerate(records, start=1):
            record["sequence"] = index
        self.assert_refused(records, "HASH_CHAIN_BROKEN")

    def test_genesis_record_must_use_the_zero_predecessor(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["prev_hash"] = "a" * 64
        self.assert_refused(records, "HASH_CHAIN_BROKEN")

    def test_trusted_head_anchor_accepts_exact_prefix_and_append(self) -> None:
        anchor = self.records[-1]["content_hash"]
        code, payload = self.run_validator_with_anchor(self.records, anchor)
        self.assertEqual(0, code, payload)
        self.assertEqual({"provided": True, "matched": True}, payload["chain_anchor"])

        appended = copy.deepcopy(self.records)
        appended_record = copy.deepcopy(appended[-1])
        appended_record["record_id"] = "ref/" + "a" * 64
        appended_record["sequence"] = len(appended) + 1
        appended_record["subject_ref"] = "ref/" + "b" * 64
        appended_record["subject_digest"] = "c" * 64
        appended_record["private_receipt_ref"] = "ref/" + "d" * 64
        appended_record["private_receipt_digest"] = "e" * 64
        appended_record["recorded_at"] = "2026-08-24T00:25:00Z"
        appended.append(appended_record)
        code, payload = self.run_validator_with_anchor(self.rechain(appended), anchor)
        self.assertEqual(0, code, payload)
        self.assertEqual({"provided": True, "matched": True}, payload["chain_anchor"])

    def test_rewritten_prefix_is_rejected_by_trusted_head_anchor(self) -> None:
        anchor = self.records[-1]["content_hash"]
        records = copy.deepcopy(self.records)
        del records[0]
        for sequence, record in enumerate(records, start=1):
            record["sequence"] = sequence
        code, payload = self.run_validator_with_anchor(self.rechain(records), anchor)
        self.assertEqual(2, code, payload)
        self.assertIn("CHAIN_ANCHOR_MISSING", payload["reason_codes"])
        self.assertEqual({"provided": True, "matched": False}, payload["chain_anchor"])

    def test_invalid_anchor_is_rejected(self) -> None:
        code, payload = self.run_validator_with_anchor(self.records, "not-a-sha256")
        self.assertEqual(2, code, payload)
        self.assertIn("ANCHOR_INVALID", payload["reason_codes"])

    # --- gate and vocabulary consistency ---------------------------------

    def test_accepted_record_cannot_bypass_a_gate(self) -> None:
        records = copy.deepcopy(self.records)
        records[2]["gates"]["secret_scan"] = "BLOCKED"
        self.assert_refused(self.rechain(records), "GATE_BYPASS")

    def test_failed_gate_cannot_stay_proposed(self) -> None:
        records = copy.deepcopy(self.records)
        records[1]["gates"]["history_scan"] = "FAIL"
        self.assert_refused(self.rechain(records), "FAILED_GATE_NOT_REJECTED_OR_BLOCKED")

    def test_blocked_record_cannot_carry_a_terminal_classification(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["terminal_classification"] = "PUBLIC_EXTRACT"
        records[0]["transfer_mode"] = "REAUTHOR"
        self.assert_refused(self.rechain(records), "BLOCKED_RECORD_CARRIES_CLASSIFICATION")

    def test_blocked_record_requires_a_blocking_gate(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["gates"] = {name: "PASS" for name in GATE_NAMES}
        self.assert_refused(self.rechain(records), "BLOCKED_WITHOUT_BLOCKING_GATE")

    def test_unblocked_record_requires_a_terminal_classification(self) -> None:
        records = copy.deepcopy(self.records)
        records[1]["terminal_classification"] = None
        records[1]["transfer_mode"] = None
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_rejected_record_requires_a_terminal_classification(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["status"] = "REJECTED"
        records[0]["terminal_classification"] = None
        records[0]["transfer_mode"] = None
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_counts_use_the_latest_disposition_per_subject(self) -> None:
        records = copy.deepcopy(self.records)
        latest = copy.deepcopy(records[0])
        latest["record_id"] = "ref/" + "a" * 64
        latest["sequence"] = len(records) + 1
        latest["subject_digest"] = "b" * 64
        latest["private_receipt_ref"] = "ref/" + "c" * 64
        latest["private_receipt_digest"] = "d" * 64
        latest["recorded_at"] = "2026-08-24T00:25:00Z"
        latest["status"] = "ACCEPTED"
        latest["terminal_classification"] = "PUBLIC_EXTRACT"
        latest["transfer_mode"] = "REAUTHOR"
        latest["gates"] = {name: "PASS" for name in GATE_NAMES}
        latest["proposed_action"] = "ref/" + "e" * 64
        records.append(latest)
        code, payload = self.run_validator(self.rechain(records))
        self.assertEqual(0, code, payload)
        counts = payload["terminal_classification_counts"]
        self.assertEqual(0, counts["UNCLASSIFIED_BLOCKED"])
        self.assertEqual(2, counts["PUBLIC_EXTRACT"])

    def test_drop_and_regenerate_bind_their_transfer_mechanism(self) -> None:
        records = copy.deepcopy(self.records)
        records[3]["transfer_mode"] = "REAUTHOR"
        self.assert_refused(self.rechain(records), "DROP_REQUIRES_NO_COPY")

        records = copy.deepcopy(self.records)
        records[4]["transfer_mode"] = "REAUTHOR"
        self.assert_refused(self.rechain(records), "REGENERATE_REQUIRES_GENERATE")

    def test_supersession_requires_rejection(self) -> None:
        records = copy.deepcopy(self.records)
        records[2]["supersession_reason"] = "WITHDRAWN"
        self.assert_refused(self.rechain(records), "SUPERSESSION_WITHOUT_REJECTION")

    def test_oversized_input_is_rejected_before_full_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized-ledger.jsonl"
            path.write_bytes(b"x" * (validator_module.MAX_INPUT_BYTES + 1))
            code, payload = self.run_validator_path(path)
        self.assertEqual(2, code, payload)
        self.assertIn("INPUT_TOO_LARGE", payload["reason_codes"])
        self.assertIsNone(payload["zero_unclassified"])

    def test_non_regular_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger-directory"
            path.mkdir()
            code, payload = self.run_validator_path(path)
        self.assertEqual(2, code, payload)
        self.assertIn("INPUT_INVALID", payload["reason_codes"])

    # --- documentation ---------------------------------------------------

    def test_documentation_states_the_boundary_and_is_linked(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        for token in (
            "NO_GO_UNPUBLISHED",
            "LEDGER_CONSISTENT_UNVERIFIED",
            "terminal_classification",
            "transfer_mode",
        ):
            with self.subTest(token=token):
                self.assertIn(token, doc)
        self.assertIn("public-migration-ledger.schema.json", MATRIX.read_text(encoding="utf-8"))
        self.assertIn("not yet populated", MIGRATION_README.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
