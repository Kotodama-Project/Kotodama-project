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
SCHEMA = ROOT / "schemas" / "public-agent-lifecycle-registry.schema.json"
VALIDATOR = ROOT / "tools" / "validate_public_agent_lifecycle_registry.py"
FIXTURE = ROOT / "tests" / "fixtures" / "public-agent-lifecycle" / "valid.jsonl"
DOC = ROOT / "docs" / "PUBLIC-AGENT-LIFECYCLE-REGISTRY.md"
MATRIX = ROOT / "docs" / "SCHEMA-VALIDATOR-MATRIX.md"

LIFECYCLE_STATES = [
    "prepared",
    "dispatched",
    "running",
    "completed",
    "failed",
    "cancelled",
    "expired",
]
CLAIM_FIELDS = [
    "agent_runtime_verified",
    "dispatch_executed",
    "provider_instance_reused",
    "continuity_verified",
    "evidence_independently_verified",
    "promotion_verified",
    "current_truth_changed",
    "final_human_go",
    "public_beta_go",
]


def _load_validator_module():
    spec = importlib.util.spec_from_file_location(
        "validate_public_agent_lifecycle_registry", VALIDATOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("validator import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validator_module = _load_validator_module()


class PublicAgentLifecycleRegistryContractTests(unittest.TestCase):
    def test_deep_json_cli_returns_structured_refusal(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deep.jsonl"
            path.write_text('{"nested":' * 5000 + "0" + "}" * 5000 + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, str(VALIDATOR), str(path)],
                                    capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"], "REFUSED")
        self.assertEqual(payload["reason_codes"], ["INPUT_INVALID"])
        self.assertTrue(all(value is False for value in payload["claims"].values()))
        self.assertNotIn("Traceback", result.stderr)

    def test_retry_cannot_begin_before_predecessor_terminal_event(self):
        for early_count in (1, 2, 3):
            with self.subTest(early_states=early_count):
                records = copy.deepcopy(self.records)
                early = [r for r in records if r["kind"] == "run_event"
                         and r["run_ref"] == "ref/run/worker-b-2"][:early_count]
                records = [r for r in records if r not in early]
                terminal = next(i for i, r in enumerate(records)
                                if r["kind"] == "run_event" and r["run_ref"] == "ref/run/worker-b-1"
                                and r["to_state"] == "failed")
                records[terminal:terminal] = early
                for index, record in enumerate(records):
                    record["recorded_at"] = f"2026-08-24T00:00:{index:02d}Z"
                self.assert_refused(self.rechain(records), "RETRY_BEFORE_PREDECESSOR_TERMINAL")

    def test_unknown_evidence_refusal_has_no_derived_success(self):
        records = copy.deepcopy(self.records)
        run = next(r for r in records if r["kind"] == "agent_run" and r["state"] == "completed")
        run["evidence_receipt_refs"] = ["ref/receipt/missing"]
        code, payload = self.run_validator(self.rechain(records))
        self.assertEqual(code, 2)
        self.assertIn("RUN_EVIDENCE_UNKNOWN", payload["reason_codes"])
        self.assertEqual(payload["derived_success_count"], 0)

    def test_json_depth_cap_is_checked_before_decoder(self):
        depth = validator_module.MAX_JSON_DEPTH
        at_limit = '{"nested":' * depth + '0' + '}' * depth
        records = validator_module._parse_lines((at_limit + "\n").encode("utf-8"))
        self.assertEqual(len(records), 1)
        over_limit = '{"nested":' * (depth + 1) + '0' + '}' * (depth + 1)
        with self.assertRaisesRegex(ValueError, "nesting exceeds limit"):
            validator_module._parse_lines((over_limit + "\n").encode("utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "depth.jsonl"
            path.write_text(over_limit + "\n", encoding="utf-8")
            code, payload = self.run_validator_path(path)
        self.assertEqual(code, 2)
        self.assertEqual(payload["reason_codes"], ["INPUT_INVALID"])

    def test_json_depth_guard_ignores_quoted_brackets_and_escapes(self):
        value = '[{' * 200 + '\\' + '"' + ']}' * 200
        line = json.dumps({"text": value, "nested": ["\\", '"', "[{}]"]})
        records = validator_module._parse_lines((line + "\n").encode("utf-8"))
        self.assertEqual(records, [{"text": value, "nested": ["\\", '"', "[{}]"]}])

    def test_later_instance_observation_cannot_expand_prior_run_budget(self):
        records = copy.deepcopy(self.records)
        original = next(r for r in records if r["kind"] == "agent_spec" and r["spec_ref"] == "ref/spec/orchestrator")
        original["max_fan_out"] = 2
        expanded = copy.deepcopy(original)
        expanded.update(record_id="ref/record/expanded-spec", spec_ref="ref/spec/expanded", max_fan_out=4)
        later = next(r for r in reversed(records) if r["kind"] == "agent_instance" and r["instance_ref"] == "ref/instance/root")
        later["spec_ref"] = expanded["spec_ref"]
        records.insert(records.index(later), expanded)
        for record in records:
            record["recorded_at"] = "2026-08-24T00:00:00Z"
        self.assert_refused(self.rechain(records), "FAN_OUT_BUDGET_EXCEEDED")

    def test_terminal_event_cannot_precede_its_earlier_subject_events(self):
        for run_ref in ("ref/run/root-1", "ref/run/worker-b-1"):
            with self.subTest(run_ref=run_ref):
                records = copy.deepcopy(self.records)
                terminal = next(r for r in records if r["kind"] == "run_event" and r["run_ref"] == run_ref
                                and r["to_state"] in {"completed", "failed"})
                records.remove(terminal)
                first = next(i for i, r in enumerate(records) if r["kind"] == "run_event" and r["run_ref"] == run_ref)
                records.insert(first, terminal)
                for record in records:
                    record["recorded_at"] = "2026-08-24T00:00:00Z"
                self.assert_refused(self.rechain(records), "EVENT_APPEND_ORDER_MISMATCH")

    def test_owned_regular_file_swap_during_open_is_refused(self) -> None:
        import os
        from unittest import mock
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.jsonl"
            path.write_bytes(b"original")
            saved = path.with_suffix(".saved")
            original_open, original_path_open = os.open, Path.open
            swapped = False
            def swap(target):
                nonlocal swapped
                if Path(target) == path and not swapped:
                    swapped = True
                    path.rename(saved)
                    path.write_bytes(b"replacement")
            def fd_open(target, *args, **kwargs):
                swap(target)
                return original_open(target, *args, **kwargs)
            def stream_open(target, *args, **kwargs):
                swap(target)
                return original_path_open(target, *args, **kwargs)
            with mock.patch("os.open", fd_open), mock.patch.object(Path, "open", stream_open):
                with self.assertRaises(validator_module.InputNotRegularFileError):
                    validator_module.read_bounded(path)
            self.assertTrue(swapped)

    def test_existing_hardlink_is_refused(self) -> None:
        import os
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.jsonl"
            path.write_bytes(b"original")
            linked = Path(temporary) / "hardlink.jsonl"
            try: os.link(path, linked)
            except OSError as error: self.skipTest(str(error))
            with self.assertRaises(validator_module.InputNotRegularFileError):
                validator_module.read_bounded(path)

    def test_small_record_limit_rejects_before_next_materialization(self) -> None:
        from unittest import mock
        raw = b"{}\n" * 4
        with mock.patch.object(validator_module, "MAX_RECORDS", 3):
            with self.assertRaises(validator_module.InputTooManyRecordsError):
                validator_module._parse_lines(raw)
        with mock.patch.object(validator_module, "MAX_RECORDS", 3):
            self.assertEqual(3, len(validator_module._parse_lines(b"{}\n" * 3)))

    def test_schema_validation_stops_on_first_error_before_next_record(self) -> None:
        calls = []
        class FirstErrorValidator:
            def iter_errors(self, record):
                calls.append(record)
                yield object()
                raise AssertionError("must not collect further schema errors")
        with self.assertRaises(validator_module.SchemaInvalidError):
            validator_module._parse_lines(b"{}\n{}\n", validator=FirstErrorValidator())
        self.assertEqual([{}], calls)

    def test_regular_read_allows_cross_api_ctime_representation_difference(self) -> None:
        import os
        from types import SimpleNamespace
        from unittest import mock
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "ledger.jsonl"
            path.write_bytes(b"original")
            actual_fstat = os.fstat
            def alternate_ctime(fd):
                info = actual_fstat(fd)
                values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
                values["st_ctime_ns"] += 100
                return SimpleNamespace(**values)
            with mock.patch("os.fstat", alternate_ctime):
                self.assertEqual(b"original", validator_module.read_bounded(path))

    def test_final_pathname_identity_change_is_refused(self) -> None:
        from unittest import mock
        with tempfile.TemporaryDirectory() as temporary:
            path, other = Path(temporary) / "ledger.jsonl", Path(temporary) / "other.jsonl"
            path.write_bytes(b"original")
            other.write_bytes(b"original")
            before, replacement = validator_module._plain_metadata(path), validator_module._plain_metadata(other)
            with mock.patch.object(validator_module, "_plain_metadata", side_effect=[before, replacement]):
                with self.assertRaises(validator_module.InputNotRegularFileError):
                    validator_module.read_bounded(path)

    def test_record_limit_refusal_payload_is_bounded(self):
        import contextlib
        import io
        from unittest import mock
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "records.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in self.records[:4]) + "\n", encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(validator_module, "MAX_RECORDS", 3), contextlib.redirect_stdout(output):
                code = validator_module.main(["validator", str(path)])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(payload["reason_codes"], ["RECORD_LIMIT_EXCEEDED"])
        self.assertEqual(payload["record_count"], 0)
        self.assertEqual(payload["derived_success_count"], 0)
        self.assertTrue(all(value is False for value in payload["claims"].values()))

    def test_reference_and_digest_fields_reject_terminal_newline(self):
        validator = Draft202012Validator(self.schema, format_checker=FormatChecker())
        for record in self.records:
            for field, value in record.items():
                if field == "record_id" or field.endswith("_ref") or field.endswith("_digest") or field in {"prev_hash", "content_hash", "revision", "policy_version", "recorded_at", "heartbeat_at", "expires_at", "capability_refs", "evidence_receipt_refs"}:
                    with self.subTest(kind=record["kind"], field=field):
                        changed = copy.deepcopy(record)
                        if isinstance(value, list):
                            if not value: continue
                            changed[field][0] += "\n"
                        else:
                            changed[field] += "\n"
                        self.assertFalse(validator_module._strict_reference_fields(changed))
                        self.assertIsNotNone(next(validator.iter_errors(changed), None))
                        raw = (json.dumps(changed) + "\n").encode("utf-8")
                        with self.assertRaises(validator_module.SchemaInvalidError):
                            validator_module._parse_lines(raw, validator=validator)

    def setUp(self) -> None:
        self.records = [
            json.loads(line)
            for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        ]
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    # --- helpers ---------------------------------------------------------

    def rechain(self, records: list[dict]) -> list[dict]:
        previous = validator_module.GENESIS_HASH
        for index, record in enumerate(records, start=1):
            record["sequence"] = index
            record["prev_hash"] = previous
            record.pop("content_hash", None)
            previous = validator_module.canonical_content_hash(record)
            record["content_hash"] = previous
        return records

    def run_validator(self, records: list[dict]) -> tuple[int, dict]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "registry.jsonl"
            path.write_text(
                "\n".join(
                    json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    for r in records
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            completed = subprocess.run(
                [sys.executable, "-B", str(VALIDATOR), str(path)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        return completed.returncode, json.loads(completed.stdout)

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

    def assert_refused(self, records: list[dict], reason: str) -> None:
        code, payload = self.run_validator(records)
        self.assertEqual(2, code, payload)
        self.assertEqual("REFUSED", payload["result"])
        self.assertIn(reason, payload["reason_codes"])

    def find(self, kind: str, key: str, value: str) -> dict:
        for record in self.records:
            if record["kind"] == kind and record.get(key) == value:
                return record
        raise AssertionError(f"{kind} with {key}={value} not in fixture")

    def index_of(self, record: dict) -> int:
        return self.records.index(record)

    # --- committed fixture ----------------------------------------------

    def test_committed_fixture_is_schema_valid_and_consistent(self) -> None:
        checker = Draft202012Validator(self.schema, format_checker=FormatChecker())
        for record in self.records:
            with self.subTest(sequence=record["sequence"], kind=record["kind"]):
                self.assertEqual([], list(checker.iter_errors(record)))
        code, payload = self.run_validator(self.records)
        self.assertEqual(0, code, payload)
        self.assertEqual("REGISTRY_CONSISTENT_UNVERIFIED", payload["result"])
        self.assertEqual(len(self.records), payload["record_count"])

    def test_result_never_asserts_a_claim_or_moves_the_public_gate(self) -> None:
        _, payload = self.run_validator(self.records)
        self.assertEqual("NO_GO_UNPUBLISHED", payload["public_beta"])
        for field in CLAIM_FIELDS:
            with self.subTest(field=field):
                self.assertIs(False, payload["claims"][field])

    # --- fail-closed outcome contract ------------------------------------

    def test_success_is_derived_from_state_reason_and_evidence(self) -> None:
        run = copy.deepcopy(self.find("agent_run", "run_ref", "ref/run/root-1"))
        self.assertTrue(validator_module.derived_success(run))
        for mutation in (
            {"state": "running"},
            {"termination_reason": "MISSING_EVIDENCE"},
            {"evidence_receipt_refs": []},
        ):
            with self.subTest(mutation=mutation):
                candidate = copy.deepcopy(run)
                candidate.update(mutation)
                self.assertFalse(validator_module.derived_success(candidate))

    def test_degraded_is_an_attribute_not_a_successful_state(self) -> None:
        self.assertNotIn("degraded", LIFECYCLE_STATES)
        run_property = self.schema["$defs"]["agent_run"]["properties"]
        self.assertEqual(LIFECYCLE_STATES, run_property["state"]["enum"])
        self.assertEqual("boolean", run_property["degraded"]["type"])

        degraded_completed = self.find("agent_run", "run_ref", "ref/run/worker-a-1")
        self.assertTrue(degraded_completed["degraded"])
        _, payload = self.run_validator(self.records)
        self.assertEqual(1, payload["degraded_run_count"])
        self.assertEqual(3, payload["derived_success_count"])

        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-b-1"))][
            "degraded"
        ] = True
        code, payload = self.run_validator(self.rechain(records))
        self.assertEqual(0, code, payload)
        self.assertEqual(3, payload["derived_success_count"])

    def test_completed_run_without_evidence_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/root-1"))][
            "evidence_receipt_refs"
        ] = []
        self.assert_refused(self.rechain(records), "COMPLETED_RUN_WITHOUT_EVIDENCE")

    def test_failed_run_cannot_claim_the_completion_reason(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-b-1"))][
            "termination_reason"
        ] = "EVIDENCE_COMPLETE"
        self.assert_refused(self.rechain(records), "FAILED_RUN_CLAIMS_COMPLETION_REASON")

    def test_prepared_payload_alone_cannot_carry_evidence_or_a_reason(self) -> None:
        records = copy.deepcopy(self.records)
        index = self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-b-1"))
        records[index].update(state="prepared", termination_reason="EVIDENCE_COMPLETE")
        self.assert_refused(
            self.rechain(records), "NON_TERMINAL_RUN_CARRIES_TERMINATION_REASON"
        )

        records = copy.deepcopy(self.records)
        records[index].update(
            state="prepared",
            termination_reason=None,
            evidence_receipt_refs=["ref/receipt/root-1"],
        )
        self.assert_refused(self.rechain(records), "NON_TERMINAL_RUN_CARRIES_EVIDENCE")

    def test_terminal_run_needs_a_termination_reason(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-b-1"))][
            "termination_reason"
        ] = None
        self.assert_refused(self.rechain(records), "TERMINAL_RUN_WITHOUT_TERMINATION_REASON")

    def test_terminal_reason_matches_the_terminal_state(self) -> None:
        cases = (
            ("cancelled", "LEASE_EXPIRED"),
            ("expired", "CANCELLED_BY_PARENT"),
            ("failed", "CANCELLED_BY_PARENT"),
        )
        for state, reason in cases:
            with self.subTest(state=state, reason=reason):
                records = copy.deepcopy(self.records)
                run = records[
                    self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-b-1"))
                ]
                run.update(state=state, termination_reason=reason)
                self.assert_refused(
                    self.rechain(records), "TERMINATION_REASON_STATE_MISMATCH"
                )

    # --- state machine ---------------------------------------------------

    def test_illegal_transition_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        events = [
            r
            for r in records
            if r["kind"] == "run_event" and r["run_ref"] == "ref/run/root-1"
        ]
        events[1].update(from_state="prepared", to_state="completed")
        for event in events[2:]:
            records.remove(event)
        run = records[self.index_of(self.find("agent_run", "run_ref", "ref/run/root-1"))]
        run["state"] = "completed"
        self.assert_refused(self.rechain(records), "ILLEGAL_STATE_TRANSITION")

    def test_run_state_must_match_its_event_history(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-b-1"))].update(
            state="cancelled", termination_reason="CANCELLED_BY_PARENT"
        )
        self.assert_refused(
            self.rechain(records), "RUN_STATE_DOES_NOT_MATCH_EVENT_HISTORY"
        )

    def test_run_without_event_history_is_rejected(self) -> None:
        records = [
            r
            for r in copy.deepcopy(self.records)
            if not (r["kind"] == "run_event" and r["run_ref"] == "ref/run/worker-b-2")
        ]
        self.assert_refused(self.rechain(records), "RUN_WITHOUT_EVENT_HISTORY")

    def test_event_sequence_gap_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        for record in records:
            if record["kind"] == "run_event" and record["run_ref"] == "ref/run/root-1":
                if record["subject_sequence"] == 4:
                    record["subject_sequence"] = 9
        self.assert_refused(self.rechain(records), "SUBJECT_SEQUENCE_NOT_CONTIGUOUS")

    # --- budgets, edges, idempotency -------------------------------------

    def test_child_depth_must_be_parent_depth_plus_one(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-a-1"))][
            "depth"
        ] = 2
        self.assert_refused(self.rechain(records), "DEPTH_NOT_PARENT_PLUS_ONE")

    def test_depth_budget_is_enforced(self) -> None:
        records = copy.deepcopy(self.records)
        spec_index = self.index_of(self.find("agent_spec", "spec_ref", "ref/spec/worker"))
        records[spec_index]["max_depth"] = 1
        run_index = self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-a-1"))
        records[run_index]["depth"] = 2
        parent_index = self.index_of(self.find("agent_run", "run_ref", "ref/run/root-1"))
        records[parent_index]["depth"] = 1
        self.assert_refused(self.rechain(records), "DEPTH_BUDGET_EXCEEDED")

    def test_fan_out_budget_is_enforced(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_spec", "spec_ref", "ref/spec/orchestrator"))][
            "max_fan_out"
        ] = 2
        self.assert_refused(self.rechain(records), "FAN_OUT_BUDGET_EXCEEDED")

    def test_leaf_spec_can_prohibit_all_child_delegation(self) -> None:
        records = copy.deepcopy(self.records)
        spec = records[
            self.index_of(self.find("agent_spec", "spec_ref", "ref/spec/worker"))
        ]
        spec["max_fan_out"] = 0

        code, payload = self.run_validator(self.rechain(records))

        self.assertEqual(0, code, payload)

    def test_parent_edge_must_accompany_a_parent(self) -> None:
        records = copy.deepcopy(self.records)
        del records[self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-a-1"))][
            "parent_edge_ref"
        ]
        self.assert_refused(self.rechain(records), "PARENT_EDGE_INCONSISTENT")

    def test_root_run_must_have_depth_zero(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/root-1"))]["depth"] = 1
        self.assert_refused(self.rechain(records), "ROOT_RUN_DEPTH_NOT_ZERO")

    def test_repeated_attempt_for_one_idempotency_key_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-b-2"))][
            "attempt"
        ] = 1
        self.assert_refused(
            self.rechain(records), "DUPLICATE_ATTEMPT_FOR_IDEMPOTENCY_KEY"
        )

    def test_retry_requires_a_terminal_unsuccessful_predecessor(self) -> None:
        for predecessor_state in ("completed", "running"):
            with self.subTest(predecessor_state=predecessor_state):
                records = copy.deepcopy(self.records)
                predecessor = records[
                    self.index_of(self.find("agent_run", "run_ref", "ref/run/worker-b-1"))
                ]
                predecessor["state"] = predecessor_state
                predecessor["termination_reason"] = (
                    "EVIDENCE_COMPLETE" if predecessor_state == "completed" else None
                )
                self.assert_refused(
                    self.rechain(records), "RETRY_PREDECESSOR_NOT_UNSUCCESSFUL"
                )

    def test_lease_epoch_must_strictly_increase_and_outlive_its_heartbeat(self) -> None:
        records = copy.deepcopy(self.records)
        lease = self.find("worker_lease", "run_ref", "ref/run/root-1")
        duplicate = copy.deepcopy(lease)
        duplicate["record_id"] = "ref/record/b0001"
        duplicate["lease_ref"] = "ref/lease/root-1-again"
        records.insert(self.index_of(lease) + 1, duplicate)
        self.assert_refused(self.rechain(records), "LEASE_EPOCH_NOT_STRICTLY_INCREASING")

        records = copy.deepcopy(self.records)
        records[self.index_of(lease)]["heartbeat_at"] = "2026-08-24T23:00:00Z"
        self.assert_refused(self.rechain(records), "LEASE_HEARTBEAT_AFTER_EXPIRY")

    def test_lease_and_event_references_are_unique(self) -> None:
        cases = (
            ("worker_lease", "run_ref", "ref/run/root-1", "DUPLICATE_LEASE_REF"),
            ("run_event", "event_ref", "ref/event/root-1/1", "DUPLICATE_EVENT_REF"),
        )
        for kind, key, value, reason in cases:
            with self.subTest(reason=reason):
                records = copy.deepcopy(self.records)
                original = records[self.index_of(self.find(kind, key, value))]
                duplicate = copy.deepcopy(original)
                duplicate["record_id"] = "ref/record/duplicate-" + kind
                if kind == "worker_lease":
                    duplicate["epoch"] += 1
                else:
                    duplicate["subject_sequence"] += 100
                records.append(duplicate)
                self.assert_refused(self.rechain(records), reason)

    # --- referential integrity -------------------------------------------

    def test_unknown_references_are_rejected(self) -> None:
        cases = [
            ("agent_run", "run_ref", "ref/run/root-1", "instance_ref", "ref/instance/ghost", "RUN_INSTANCE_UNKNOWN"),
            ("worker_lease", "run_ref", "ref/run/root-1", "run_ref", "ref/run/ghost", "LEASE_RUN_UNKNOWN"),
            ("evidence_receipt", "receipt_ref", "ref/receipt/root-1", "run_ref", "ref/run/ghost", "RECEIPT_RUN_UNKNOWN"),
        ]
        for kind, key, value, field, replacement, reason in cases:
            with self.subTest(reason=reason):
                records = copy.deepcopy(self.records)
                records[self.index_of(self.find(kind, key, value))][field] = replacement
                self.assert_refused(self.rechain(records), reason)

    def test_evidence_bound_to_another_run_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_run", "run_ref", "ref/run/root-1"))][
            "evidence_receipt_refs"
        ] = ["ref/receipt/worker-a-1"]
        self.assert_refused(
            self.rechain(records), "RUN_EVIDENCE_BOUND_TO_ANOTHER_RUN"
        )

    def test_instance_spec_binding_drift_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_instance", "instance_ref", "ref/instance/worker-a"))][
            "spec_digest"
        ] = "b" * 64
        self.assert_refused(self.rechain(records), "INSTANCE_SPEC_BINDING_DRIFT")

    # --- continuity ------------------------------------------------------

    def test_continuity_is_never_reported_as_verified(self) -> None:
        _, payload = self.run_validator(self.records)
        assessments = {a["instance_ref"]: a for a in payload["continuity_assessments"]}
        self.assertEqual(
            "PRECONDITIONS_MATCH_UNVERIFIED",
            assessments["ref/instance/root"]["assessment"],
        )
        self.assertNotIn(
            "CONTINUITY_VERIFIED",
            json.dumps(payload),
        )
        self.assertIs(False, payload["claims"]["continuity_verified"])
        self.assertIs(False, payload["claims"]["provider_instance_reused"])

    def test_any_precondition_drift_downgrades_to_work_resume_only(self) -> None:
        _, payload = self.run_validator(self.records)
        assessments = {a["instance_ref"]: a for a in payload["continuity_assessments"]}
        worker = assessments["ref/instance/worker-a"]
        self.assertEqual("WORK_RESUME_ONLY", worker["assessment"])
        self.assertEqual(["context_capsule_digest"], worker["mismatched_preconditions"])

        for field in ("provider_locator_ref", "revision", "repository_ref", "policy_version"):
            with self.subTest(field=field):
                records = copy.deepcopy(self.records)
                observations = [
                    index
                    for index, record in enumerate(records)
                    if record["kind"] == "agent_instance"
                    and record["instance_ref"] == "ref/instance/root"
                ]
                self.assertEqual(2, len(observations))
                record = records[observations[1]]
                record[field] = (
                    "v9" if field == "policy_version"
                    else ("f" * 40 if field == "revision" else record[field] + "-successor")
                )
                if field == "policy_version":
                    # A policy change also breaks the spec binding, which is a
                    # separate and stronger refusal; assert that instead.
                    self.assert_refused(
                        self.rechain(records), "INSTANCE_SPEC_BINDING_DRIFT"
                    )
                    continue
                code, payload = self.run_validator(self.rechain(records))
                self.assertEqual(0, code, payload)
                assessment = {
                    a["instance_ref"]: a for a in payload["continuity_assessments"]
                }["ref/instance/root"]
                self.assertEqual("WORK_RESUME_ONLY", assessment["assessment"])
                self.assertIn(field, assessment["mismatched_preconditions"])

    # --- envelope and tamper evidence ------------------------------------

    def test_schema_is_closed_and_forces_every_claim_false(self) -> None:
        self.assertFalse(self.schema["unevaluatedProperties"])
        claims = self.schema["properties"]["claims"]
        self.assertFalse(claims["additionalProperties"])
        self.assertEqual(sorted(CLAIM_FIELDS), sorted(claims["required"]))
        for field in CLAIM_FIELDS:
            with self.subTest(field=field):
                self.assertIs(False, claims["properties"][field]["const"])
        self.assertEqual(
            "NO_GO_UNPUBLISHED", self.schema["properties"]["public_beta"]["const"]
        )

    def test_unknown_property_and_non_opaque_reference_are_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["provider_thread_id"] = "thread_abc123"
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

        records = copy.deepcopy(self.records)
        records[self.index_of(self.find("agent_instance", "instance_ref", "ref/instance/root"))][
            "provider_locator_ref"
        ] = "https://provider.invalid/threads/abc"
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_asserted_claim_is_rejected(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["claims"]["continuity_verified"] = True
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_content_digest_drift_and_broken_chain_are_detected(self) -> None:
        records = copy.deepcopy(self.records)
        records[4]["session_ref"] = "ref/session/other"
        self.assert_refused(records, "CONTENT_DIGEST_DRIFT")

        records = copy.deepcopy(self.records)
        records[6]["prev_hash"] = validator_module.GENESIS_HASH
        self.assert_refused(records, "HASH_CHAIN_BROKEN")

    def test_empty_registry_and_duplicate_json_key_fail_closed(self) -> None:
        for content in ("", None):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "registry.jsonl"
                if content is None:
                    line = json.dumps(self.records[0], sort_keys=True, separators=(",", ":"))
                    text = line.replace('"version":"v1"', '"version":"v1","version":"v2"', 1) + "\n"
                else:
                    text = content
                path.write_text(text, encoding="utf-8", newline="\n")
                completed = subprocess.run(
                    [sys.executable, "-B", str(VALIDATOR), str(path)],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", check=False,
                )
            self.assertEqual(2, completed.returncode)
            self.assertIn("INPUT_INVALID", json.loads(completed.stdout)["reason_codes"])

    def test_timestamp_must_be_a_real_date(self) -> None:
        records = copy.deepcopy(self.records)
        records[0]["recorded_at"] = "2026-99-99T99:99:99Z"
        self.assert_refused(self.rechain(records), "SCHEMA_INVALID")

    def test_oversized_and_non_regular_inputs_fail_before_unbounded_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            oversized = Path(directory) / "oversized.jsonl"
            oversized.write_bytes(b"x" * (validator_module.MAX_INPUT_BYTES + 1))
            code, payload = self.run_validator_path(oversized)
            self.assertEqual(2, code, payload)
            self.assertIn("INPUT_TOO_LARGE", payload["reason_codes"])

            non_regular = Path(directory) / "registry-directory"
            non_regular.mkdir()
            code, payload = self.run_validator_path(non_regular)
            self.assertEqual(2, code, payload)
            self.assertIn("INPUT_INVALID", payload["reason_codes"])

    # --- documentation ---------------------------------------------------

    def test_documentation_states_the_boundary_and_is_linked(self) -> None:
        doc = DOC.read_text(encoding="utf-8")
        for token in (
            "NO_GO_UNPUBLISHED",
            "REGISTRY_CONSISTENT_UNVERIFIED",
            "PRECONDITIONS_MATCH_UNVERIFIED",
            "WORK_RESUME_ONLY",
            "prepared",
            "dispatched",
        ):
            with self.subTest(token=token):
                self.assertIn(token, doc)
        self.assertIn(
            "public-agent-lifecycle-registry.schema.json",
            MATRIX.read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
