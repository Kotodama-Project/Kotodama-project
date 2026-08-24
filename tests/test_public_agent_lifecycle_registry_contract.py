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
