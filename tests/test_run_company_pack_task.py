import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import create_company_pack as creator
import run_company_pack_task as executor


class CompanyPackTaskTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.request = {
            "kind": "company_pack_task_request", "operation": "CREATE_COMPANY_PACK",
            "operation_key": "create-demo-v1", "task_ref": "task:KTP-TASK-9001",
            "work_order_ref": "work-order:local-demo-v1", "capability_ref": "capability:local-pack-v1",
            "authorized_output_root": str(self.root), "source": executor.source_binding(),
            "pack_id": "demo-company", "human_intent_ref": "human-intent:local-demo-v1",
            "authority_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "retention_policy_ref": "retention-policy:local-demo-v1",
        }
        self.operation = self.root / self.request["operation_key"]
        self.pack = self.operation / "pack"
        self.binding_path = self.root / "binding.json"
        self.records_root = self.root / "records"
        self.records_root.mkdir()
        self.owner = "ref/role/local-pack-owner"
        self.task = {
            "$schema": "../../../schemas/task-record.schema.json", "kind": "kotodama.task-record",
            "version": "1.0", "record_status": "CANDIDATE_ONLY", "task_id": "KTP-TASK-9001",
            "project_ref": "../project.json", "phase_ref": None, "requirement_ref": None,
            "plan_ref": None, "lifecycle_ref": "../lifecycle.json", "title": "Create a local draft pack",
            "status": "active", "owner_ref": self.owner, "collaborator_refs": [],
            "outcome": "Create and verify one local draft Company Pack",
            "scope": {"in_scope": ["CREATE_COMPANY_PACK", "output-root:" + str(self.root)], "out_of_scope": ["external_write", "task_state_change", "promotion"]},
            "acceptance_criteria": [{"criterion_id": "AC-01", "text": "The bound local pack validates", "state": "pending", "evidence_refs": []}],
            "next_action": "Create and validate the local draft", "blocker": {"kind": "none", "summary": "No local blocker", "boundary_ref": None},
            "evidence_refs": [], "execution_surfaces": [], "stop_conditions": ["record drift or expiry"],
            "rollback_ref": "ref/local/retain-incomplete", "updated_at": datetime.now(timezone.utc).isoformat(),
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        task_entry = self.save_record("task", self.task)
        target = {
            "task_ref": self.request["task_ref"], "task_revision": task_entry["sha256"], "owner_ref": self.owner,
            "operation_key": self.request["operation_key"], "output_root": str(self.root), "pack_id": self.request["pack_id"],
            "human_intent_ref": self.request["human_intent_ref"], "retention_policy_ref": self.request["retention_policy_ref"],
        }
        self.work_order = {
            "kind": "work_order_candidate", "record_status": "CANDIDATE_ONLY", "status": "active",
            "work_order_id": "local-demo-v1", "decision_ref": "ref/local-caller/unverified-decision",
            "target": target, "action": "CREATE_COMPANY_PACK", "candidate_revision": self.request["source"],
            "effects": ["create_local_draft_pack_and_operation_receipt"], "rollback": "Retain output for owner inspection",
            "expires_at": self.request["authority_expires_at"], "stop_conditions": ["record drift or expiry"],
        }
        self.capability = {
            "kind": "capability_grant_candidate", "record_status": "CANDIDATE_ONLY", "status": "active",
            "grant_id": "local-pack-v1", "work_order_ref": self.request["work_order_ref"], "subject_ref": self.owner,
            "target": target, "allowed_actions": ["CREATE_COMPANY_PACK"],
            "denied_actions": ["external_write", "task_state_change", "promotion"], "issued_by_role": "local-operator",
            "authority_evidence_ref": self.work_order["decision_ref"], "issued_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": self.request["authority_expires_at"], "rollback": "Retain output for owner inspection",
            "stop_conditions": ["record drift or expiry"],
        }
        self.binding = {
            "kind": "company_pack_existing_record_binding", "version": "1.0", "owner_ref": self.owner,
            "task_updated_at": self.task["updated_at"], "records": {
                "task": task_entry, "work_order": self.save_record("work_order", self.work_order),
                "capability": self.save_record("capability", self.capability),
            },
        }
        self.save_binding()

    def save_record(self, name, value):
        path = self.records_root / (name + ".json")
        path.write_bytes(executor.canonical(value))
        return {"path": str(path), "sha256": executor.hashlib.sha256(path.read_bytes()).hexdigest()}

    def save_binding(self):
        self.binding_path.write_bytes(executor.canonical(self.binding))

    def execute(self, request=None, root=None):
        return executor.execute(request or self.request, root or self.root, self.binding_path)

    def run_cli(self, request=None, *, authorize=True):
        request_path = self.root / "request.json"
        request_path.write_text(json.dumps(request or self.request), encoding="utf-8")
        command = [sys.executable, "-B", str(ROOT / "tools/run_company_pack_task.py"), str(request_path)]
        if authorize:
            command.extend(["--authorize-local-output-root", str(self.root)])
        command.extend(["--record-binding", str(self.binding_path)])
        return subprocess.run(command, capture_output=True, cwd=ROOT, check=False)

    def assert_refused(self, request=None, code=None, root=None):
        with self.assertRaises(executor.Refused) as caught:
            self.execute(request, root)
        if code:
            self.assertEqual(str(caught.exception), code)

    def test_real_cli_creates_valid_pack_and_bound_receipt_without_task_ledger(self):
        task = self.root / "completed-task.json"
        task.write_bytes(b'{"status":"completed","counter":7}\n')
        records_before = executor.tree_bytes(self.records_root)
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertEqual(receipt["status"], "LOCAL_PASS")
        self.assertEqual(receipt["output"]["validated_files"], 22)
        self.assertFalse(receipt["task_state_changed"])
        self.assertTrue(all(value is False for value in receipt["claims"].values()))
        self.assertEqual(receipt["request_sha256"], executor.digest(self.request))
        self.assertEqual(executor.read_json(self.operation / "receipt.json"), receipt)
        self.assertEqual(receipt["output"]["files"], executor.byte_manifest(executor.tree_bytes(self.pack)))
        self.assertEqual(task.read_bytes(), b'{"status":"completed","counter":7}\n')
        self.assertEqual(executor.tree_bytes(self.records_root), records_before)
        self.assertEqual(receipt["record_binding"]["task_revision"], self.binding["records"]["task"]["sha256"])
        manifest = executor.read_json(self.pack / "manifest.json")
        self.assertEqual(manifest["id"], "demo-company")
        self.assertEqual(manifest["human_intent_ref"], self.request["human_intent_ref"])

    def test_repeat_reads_same_bytes_and_receipt_without_generating_again(self):
        original = self.execute()
        before = executor.tree_bytes(self.operation)
        with patch.object(executor, "create_company_pack", side_effect=AssertionError("must not repeat")):
            repeated = self.execute()
        self.assertEqual(repeated, original)
        self.assertEqual(executor.tree_bytes(self.operation), before)

    def test_record_ids_are_strings_before_reference_matching(self):
        for record_kind, field, prefix in (
            ("work_order", "work_order_id", "work-order"),
            ("capability", "grant_id", "capability"),
        ):
            for invalid in (True, 42, 1.0, None):
                with self.subTest(record=record_kind, value=invalid):
                    request = dict(self.request)
                    work_order, capability = dict(self.work_order), dict(self.capability)
                    if record_kind == "work_order":
                        work_order[field] = invalid
                        request["work_order_ref"] = prefix + ":" + str(invalid)
                        capability["work_order_ref"] = request["work_order_ref"]
                    else:
                        capability[field] = invalid
                        request["capability_ref"] = prefix + ":" + str(invalid)
                    self.binding["records"]["work_order"] = self.save_record("work_order", work_order)
                    self.binding["records"]["capability"] = self.save_record("capability", capability)
                    self.save_binding()
                    self.assert_refused(request, code="RECORD_IDENTIFIER_INVALID")
                    self.assertFalse(self.operation.exists())

    def test_real_process_crash_after_generation_recovers_by_observation(self):
        request_path = self.root / "request.json"
        request_path.write_text(json.dumps(self.request), encoding="utf-8")
        script = """import os, pathlib, sys
sys.path.insert(0, sys.argv[1])
import run_company_pack_task as operation
create = operation.create_company_pack
def crash_after_output(*args, **kwargs):
    result = create(*args, **kwargs)
    assert result['status'] == 'PASS'
    os._exit(93)
operation.create_company_pack = crash_after_output
operation.execute(operation.read_json(pathlib.Path(sys.argv[2])), pathlib.Path(sys.argv[3]), pathlib.Path(sys.argv[4]))
"""
        child = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "tools"), str(request_path), str(self.root), str(self.binding_path)], capture_output=True)
        self.assertEqual(child.returncode, 93, child.stderr)
        self.assertTrue(self.pack.is_dir())
        self.assertFalse((self.operation / "receipt.json").exists())
        before = executor.tree_bytes(self.pack)
        with patch.object(executor, "create_company_pack", side_effect=AssertionError("must observe")):
            receipt = self.execute()
        self.assertEqual(receipt["status"], "LOCAL_PASS")
        self.assertEqual(executor.tree_bytes(self.pack), before)

    def test_partial_generation_is_preserved_and_never_retried(self):
        def fail_generation(_id, target, _customization, **kwargs):
            self.assertTrue(kwargs["preserve_incomplete"])
            target.mkdir()
            (target / "keep.txt").write_text("partial work", encoding="utf-8")
            return {"status": "FAIL"}
        with patch.object(executor, "create_company_pack", side_effect=fail_generation):
            self.assert_refused(code="GENERATION_INCOMPLETE")
        with patch.object(executor, "create_company_pack", side_effect=AssertionError("must not repeat")):
            self.assert_refused(code="OUTPUT_VALIDATION_FAILED")
        self.assertEqual((self.pack / "keep.txt").read_text(encoding="utf-8"), "partial work")
        self.assertFalse((self.operation / "receipt.json").exists())

    def test_creator_retains_partial_only_when_explicitly_requested(self):
        for preserve in (False, True):
            target = self.root / ("preserved" if preserve else "legacy")
            with patch.object(creator, "check_customization", return_value={"status": "INVALID_PACK"}):
                result = creator.create_company_pack("demo-company", target, preserve_incomplete=preserve)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(target.exists(), preserve)
            if preserve:
                self.assertTrue((target / "manifest.json").is_file())

    def test_local_authorization_cannot_be_replaced_by_reference_strings(self):
        result = self.run_cli(authorize=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], "EXPLICIT_LOCAL_AUTHORIZATION_REQUIRED")
        self.assertFalse(self.operation.exists())
        other = self.root / "other"
        other.mkdir()
        self.assert_refused(root=other, code="LOCAL_AUTHORIZATION_ROOT_MISMATCH")

    def test_fake_references_without_actual_record_binding_are_refused(self):
        changed = copy.deepcopy(self.request)
        changed.update(task_ref="task:does-not-exist", work_order_ref="work-order:does-not-exist", capability_ref="capability:does-not-exist")
        with self.assertRaises(executor.Refused):
            executor.execute(changed, self.root)
        self.assertFalse(self.operation.exists())

    def test_fake_references_cannot_substitute_for_actual_record_ids(self):
        for name in ("task_ref", "work_order_ref", "capability_ref"):
            changed = copy.deepcopy(self.request)
            changed[name] = changed[name].split(":")[0] + ":does-not-exist"
            with self.subTest(name=name):
                self.assert_refused(changed)
                self.assertFalse(self.operation.exists())

    def test_absent_record_and_changed_record_digest_prevent_any_effect(self):
        path = Path(self.binding["records"]["task"]["path"])
        path.write_bytes(path.read_bytes() + b"\n")
        self.assert_refused(code="RECORD_DIGEST_DRIFT")
        self.assertFalse(self.operation.exists())
        self.binding["records"]["task"]["path"] = str(self.records_root / "absent.json")
        self.save_binding()
        with self.assertRaises(OSError):
            self.execute()
        self.assertFalse(self.operation.exists())

    def test_inactive_wrong_owner_action_root_and_expired_records_are_refused(self):
        cases = [
            ("task", "status", "waiting_human", "TASK_NOT_EXECUTABLE"),
            ("task", "status", "completed", "TASK_NOT_EXECUTABLE"),
            ("task", "status", "closed", "TASK_NOT_EXECUTABLE"),
            ("task", "owner_ref", "ref/role/someone-else", "TASK_OWNER_MISMATCH"),
            ("task", "scope", {"in_scope": ["public adoption"], "out_of_scope": []}, "TASK_SCOPE_MISMATCH"),
            ("task", "scope", {"in_scope": self.task["scope"]["in_scope"], "out_of_scope": ["No local writes"]}, "TASK_SCOPE_MISMATCH"),
            ("work_order", "status", "inactive", "BOUND_RECORD_INACTIVE"),
            ("work_order", "action", "PUBLISH_COMPANY_PACK", "WORK_ORDER_ACTION_OR_REVISION_MISMATCH"),
            ("work_order", "candidate_revision", {"revision": "0" * 40, "sha256": "0" * 64}, "WORK_ORDER_ACTION_OR_REVISION_MISMATCH"),
            ("work_order", "target", {**self.work_order["target"], "output_root": str(self.root / "other")}, "BOUND_RECORD_TARGET_MISMATCH"),
            ("work_order", "target", {**self.work_order["target"], "task_revision": "0" * 64}, "BOUND_RECORD_TARGET_MISMATCH"),
            ("work_order", "expires_at", "2000-01-01T00:00:00Z", "BOUND_RECORD_EXPIRY_MISMATCH"),
            ("capability", "subject_ref", "ref/role/someone-else", "CAPABILITY_OWNER_MISMATCH"),
            ("capability", "allowed_actions", ["CREATE_COMPANY_PACK", "external_write"], "CAPABILITY_ACTIONS_MISMATCH"),
            ("capability", "expires_at", "2000-01-01T00:00:00Z", "BOUND_RECORD_EXPIRY_MISMATCH"),
            ("capability", "work_order_ref", "work-order:unrelated", "CAPABILITY_REFERENCE_MISMATCH"),
        ]
        originals = {"task": self.task, "work_order": self.work_order, "capability": self.capability}
        for name, field, value, code in cases:
            modified = copy.deepcopy(originals[name])
            modified[field] = value
            self.binding["records"][name] = self.save_record(name, modified)
            self.save_binding()
            with self.subTest(name=name, field=field, value=value):
                self.assert_refused(code=code)
                self.assertFalse(self.operation.exists())
            self.binding["records"][name] = self.save_record(name, originals[name])
            self.save_binding()

    def test_expected_task_update_revision_and_binding_owner_are_checked(self):
        for field, value, code in (("task_updated_at", "2000-01-01T00:00:00Z", "TASK_REVISION_MISMATCH"), ("owner_ref", "ref/role/other-owner", "TASK_OWNER_MISMATCH")):
            previous = self.binding[field]
            self.binding[field] = value
            self.save_binding()
            self.assert_refused(code=code)
            self.assertFalse(self.operation.exists())
            self.binding[field] = previous
            self.save_binding()

    def test_record_change_during_generation_preserves_pack_without_receipt(self):
        create = executor.create_company_pack
        def change_record(*args, **kwargs):
            result = create(*args, **kwargs)
            path = Path(self.binding["records"]["task"]["path"])
            path.write_bytes(path.read_bytes() + b"\n")
            return result
        with patch.object(executor, "create_company_pack", side_effect=change_record):
            self.assert_refused(code="RECORD_DIGEST_DRIFT")
        self.assertTrue(self.pack.is_dir())
        self.assertFalse((self.operation / "receipt.json").exists())

    def test_malformed_record_types_fail_without_cli_traceback_or_effect(self):
        cases = [("task", "status", []), ("task", "updated_at", 7), ("capability", "issued_at", 7)]
        originals = {"task": self.task, "capability": self.capability}
        for name, field, value in cases:
            modified = copy.deepcopy(originals[name])
            modified[field] = value
            self.binding["records"][name] = self.save_record(name, modified)
            self.save_binding()
            result = self.run_cli()
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, b"")
            self.assertEqual(json.loads(result.stdout)["status"], "INCOMPLETE_OR_REFUSED")
            self.assertFalse(self.operation.exists())
            self.binding["records"][name] = self.save_record(name, originals[name])
            self.save_binding()

    def test_changed_input_cannot_reuse_operation_key(self):
        self.execute()
        before = executor.tree_bytes(self.operation)
        for field, value in (("task_ref", "task:OTHER-TASK"), ("pack_id", "different-company"), ("work_order_ref", "work-order:other-v1"), ("retention_policy_ref", "retention-policy:other-v1")):
            changed = copy.deepcopy(self.request)
            changed[field] = value
            with self.subTest(field=field):
                self.assert_refused(changed)
        self.assertEqual(executor.tree_bytes(self.operation), before)

    def test_unrelated_existing_operation_is_never_modified(self):
        self.operation.mkdir()
        (self.operation / "keep.txt").write_bytes(b"user work")
        with self.assertRaises(OSError):
            self.execute()
        self.assertEqual(list(self.operation.iterdir()), [self.operation / "keep.txt"])

    def test_wrong_owner_marker_refused_without_modification(self):
        self.operation.mkdir()
        executor.write_new_json(self.operation / "owner.json", {"kind": "different_owner"})
        before = executor.tree_bytes(self.operation)
        self.assert_refused(code="OPERATION_KEY_OR_OWNERSHIP_MISMATCH")
        self.assertEqual(executor.tree_bytes(self.operation), before)

    def test_path_escape_expired_window_unknown_operation_and_source_drift(self):
        cases = [
            ("operation_key", "../escape", "IDENTIFIER_INVALID"),
            ("authorized_output_root", str(self.root / ".."), "ABSOLUTE_LOCAL_PATH_REQUIRED"),
            ("authority_expires_at", "2000-01-01T00:00:00Z", "CUSTOMIZATION_OR_EXPIRY_INVALID"),
            ("authority_expires_at", "2099-01-01T00:00:00Z", "CUSTOMIZATION_OR_EXPIRY_INVALID"),
            ("operation", "RUN_SHELL", "OPERATION_REFUSED"),
            ("source", {"revision": "0" * 40, "sha256": "0" * 64}, "SOURCE_DRIFT"),
        ]
        for field, value, code in cases:
            changed = copy.deepcopy(self.request)
            changed[field] = value
            with self.subTest(field=field, code=code):
                self.assert_refused(changed, code)
                self.assertFalse(self.operation.exists())

    def test_symlink_output_root_refused(self):
        link = self.root / "linked"
        try:
            link.symlink_to(self.root, target_is_directory=True)
        except OSError:
            self.skipTest("symlink creation unavailable")
        changed = copy.deepcopy(self.request)
        changed["authorized_output_root"] = str(link)
        self.assert_refused(changed, "LINK_REFUSED", root=link)

    def test_hardlink_output_refused_and_external_bytes_unchanged(self):
        self.execute()
        external = self.root / "external.txt"
        external.write_bytes(b"keep external")
        os.link(external, self.pack / "unowned.txt")
        self.assert_refused(code="HARDLINK_REFUSED")
        self.assertEqual(external.read_bytes(), b"keep external")

    def test_receipt_detects_structurally_valid_output_byte_drift(self):
        self.execute()
        file = self.pack / "manifest.json"
        file.write_bytes(file.read_bytes() + b"\n")
        self.assert_refused(code="RECEIPT_OR_OUTPUT_DRIFT")

    def test_recovery_rejects_an_extra_output_file(self):
        self.execute()
        (self.pack / "unowned.txt").write_bytes(b"unrelated output")
        self.assert_refused(code="UNOWNED_OUTPUT_CONTENT")
        self.assertEqual((self.pack / "unowned.txt").read_bytes(), b"unrelated output")

    def test_recovery_rejects_changed_starter_copy_even_if_validator_accepts_it(self):
        self.execute()
        path = self.pack / "README.md"
        path.write_bytes(b"unrelated source content")
        self.assert_refused(code="OUTPUT_SOURCE_MISMATCH")

    def test_source_change_during_generation_preserves_output_without_receipt(self):
        bindings = [self.request["source"], {"revision": "0" * 40, "sha256": "0" * 64}]
        with patch.object(executor, "source_binding", side_effect=bindings):
            self.assert_refused(code="SOURCE_DRIFT")
        self.assertTrue(self.pack.is_dir())
        self.assertFalse((self.operation / "receipt.json").exists())

    def test_expiry_during_generation_preserves_output_without_receipt(self):
        with patch.object(executor, "validate_static_customization", side_effect=[None, "AUTHORITY_EXPIRY_NOT_FUTURE"]):
            self.assert_refused(code="EXPIRED_DURING_EXECUTION")
        self.assertTrue(self.pack.is_dir())
        self.assertFalse((self.operation / "receipt.json").exists())

    def test_existing_owned_operation_without_output_is_not_reexecuted(self):
        self.operation.mkdir()
        executor.write_new_json(self.operation / "owner.json", {
            "kind": "company_pack_operation_owner", "request_sha256": executor.digest(self.request), "request": self.request,
            "record_binding": executor.resolve_records(self.request, self.root, self.binding_path),
        })
        with patch.object(executor, "create_company_pack", side_effect=AssertionError("must not repeat")):
            self.assert_refused(code="OUTPUT_INCOMPLETE")
        self.assertFalse(self.pack.exists())

    def test_invalid_partial_receipt_is_not_overwritten(self):
        self.execute()
        file = self.operation / "receipt.json"
        file.write_bytes(b'{"partial":')
        self.assert_refused(code="INVALID_JSON")
        self.assertEqual(file.read_bytes(), b'{"partial":')

    def test_validator_failure_never_emits_receipt(self):
        real_run = subprocess.run
        def failing_validator(args, **kwargs):
            if "-I" in args:
                return subprocess.CompletedProcess(args, 1, b'{"status":"FAIL"}', b"")
            return real_run(args, **kwargs)
        with patch.object(executor.subprocess, "run", side_effect=failing_validator):
            self.assert_refused(code="OUTPUT_VALIDATION_FAILED")
        self.assertTrue((self.pack / "manifest.json").exists())
        self.assertFalse((self.operation / "receipt.json").exists())

    def test_os_lock_excludes_second_process(self):
        self.execute()
        with executor.operation_lock(self.operation / ".lock"):
            result = self.run_cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], "OPERATION_BUSY")

    def test_closed_json_and_non_reflective_errors(self):
        changed = copy.deepcopy(self.request)
        private_value = "private input must not be reflected"
        changed["command"] = private_value
        result = self.run_cli(changed)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(private_value.encode(), result.stdout + result.stderr)
        self.assertNotIn(str(self.root).encode(), result.stdout + result.stderr)
        path = self.root / "duplicate.json"
        path.write_text('{"kind":"one","kind":"two"}', encoding="utf-8")
        with self.assertRaisesRegex(executor.Refused, "DUPLICATE_JSON_KEY"):
            executor.read_json(path)


if __name__ == "__main__":
    unittest.main()
