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
            "operation_key": "create-demo-v1", "task_ref": "task:KTP-EXAMPLE-01",
            "work_order_ref": "work-order:local-demo-v1", "capability_ref": "capability:local-pack-v1",
            "authorized_output_root": str(self.root), "source": executor.source_binding(),
            "pack_id": "demo-company", "human_intent_ref": "human-intent:local-demo-v1",
            "authority_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "retention_policy_ref": "retention-policy:local-demo-v1",
        }
        self.operation = self.root / self.request["operation_key"]
        self.pack = self.operation / "pack"

    def run_cli(self, request=None, *, authorize=True):
        request_path = self.root / "request.json"
        request_path.write_text(json.dumps(request or self.request), encoding="utf-8")
        command = [sys.executable, "-B", str(ROOT / "tools/run_company_pack_task.py"), str(request_path)]
        if authorize:
            command.extend(["--authorize-local-output-root", str(self.root)])
        return subprocess.run(command, capture_output=True, cwd=ROOT, check=False)

    def assert_refused(self, request=None, code=None, root=None):
        with self.assertRaises(executor.Refused) as caught:
            executor.execute(request or self.request, root or self.root)
        if code:
            self.assertEqual(str(caught.exception), code)

    def test_real_cli_creates_valid_pack_and_bound_receipt_without_task_ledger(self):
        task = self.root / "completed-task.json"
        task.write_bytes(b'{"status":"completed","counter":7}\n')
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
        manifest = executor.read_json(self.pack / "manifest.json")
        self.assertEqual(manifest["id"], "demo-company")
        self.assertEqual(manifest["human_intent_ref"], self.request["human_intent_ref"])

    def test_repeat_reads_same_bytes_and_receipt_without_generating_again(self):
        original = executor.execute(self.request, self.root)
        before = executor.tree_bytes(self.operation)
        with patch.object(executor, "create_company_pack", side_effect=AssertionError("must not repeat")):
            repeated = executor.execute(self.request, self.root)
        self.assertEqual(repeated, original)
        self.assertEqual(executor.tree_bytes(self.operation), before)

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
operation.execute(operation.read_json(pathlib.Path(sys.argv[2])), pathlib.Path(sys.argv[3]))
"""
        child = subprocess.run([sys.executable, "-B", "-c", script, str(ROOT / "tools"), str(request_path), str(self.root)], capture_output=True)
        self.assertEqual(child.returncode, 93, child.stderr)
        self.assertTrue(self.pack.is_dir())
        self.assertFalse((self.operation / "receipt.json").exists())
        before = executor.tree_bytes(self.pack)
        with patch.object(executor, "create_company_pack", side_effect=AssertionError("must observe")):
            receipt = executor.execute(self.request, self.root)
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

    def test_changed_input_cannot_reuse_operation_key(self):
        executor.execute(self.request, self.root)
        before = executor.tree_bytes(self.operation)
        for field, value in (("task_ref", "task:OTHER-TASK"), ("pack_id", "different-company"), ("work_order_ref", "work-order:other-v1"), ("retention_policy_ref", "retention-policy:other-v1")):
            changed = copy.deepcopy(self.request)
            changed[field] = value
            with self.subTest(field=field):
                self.assert_refused(changed, "OPERATION_KEY_OR_OWNERSHIP_MISMATCH")
        self.assertEqual(executor.tree_bytes(self.operation), before)

    def test_unrelated_existing_operation_is_never_modified(self):
        self.operation.mkdir()
        (self.operation / "keep.txt").write_bytes(b"user work")
        with self.assertRaises(OSError):
            executor.execute(self.request, self.root)
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
        executor.execute(self.request, self.root)
        external = self.root / "external.txt"
        external.write_bytes(b"keep external")
        os.link(external, self.pack / "unowned.txt")
        self.assert_refused(code="HARDLINK_REFUSED")
        self.assertEqual(external.read_bytes(), b"keep external")

    def test_receipt_detects_structurally_valid_output_byte_drift(self):
        executor.execute(self.request, self.root)
        file = self.pack / "manifest.json"
        file.write_bytes(file.read_bytes() + b"\n")
        self.assert_refused(code="RECEIPT_OR_OUTPUT_DRIFT")

    def test_recovery_rejects_an_extra_output_file(self):
        executor.execute(self.request, self.root)
        (self.pack / "unowned.txt").write_bytes(b"unrelated output")
        self.assert_refused(code="UNOWNED_OUTPUT_CONTENT")
        self.assertEqual((self.pack / "unowned.txt").read_bytes(), b"unrelated output")

    def test_recovery_rejects_changed_starter_copy_even_if_validator_accepts_it(self):
        executor.execute(self.request, self.root)
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
        })
        with patch.object(executor, "create_company_pack", side_effect=AssertionError("must not repeat")):
            self.assert_refused(code="OUTPUT_INCOMPLETE")
        self.assertFalse(self.pack.exists())

    def test_invalid_partial_receipt_is_not_overwritten(self):
        executor.execute(self.request, self.root)
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
        executor.execute(self.request, self.root)
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
