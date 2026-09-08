"""Offline design-policy tests, not native OS, Cloudflare or Proxmox runtime tests."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "cloudflare_contract", ROOT / "tools/validate_cloudflare_os_integration.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def synthetic_base() -> dict:
    # Only the consumed OpenMaus design fields; this is not a live agent inventory.
    return {
        "management_model": {
            "primary_human_surface": "openmausbot_kotodama_control_surface",
            "principle": "one_management_plane_multiple_execution_boundaries",
            "no_parallel_authority": True},
        "work_contract": {
            "shared_work_identity_required": True,
            "idempotency_required_for_dispatch": True,
            "stop_request_requires_stop_observation": True},
        "adapters": {"proxmox": {"direct_agent_access_to_proxmox_management": False}},
    }


class CloudflareOSIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = json.loads((ROOT / module.CONFIG).read_text())
        self.schema = json.loads((ROOT / module.SCHEMA).read_text())
        self.base = synthetic_base()
        self.flush()

    def write(self, relative, value):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def flush(self):
        self.write(module.CONFIG, self.config)
        self.write(module.SCHEMA, self.schema)
        self.write(module.OPENMAUS, self.base)

    def refused(self, code):
        report = module.validate(self.root)
        self.assertEqual("FAIL", report["status"])
        self.assertIn({"code": code}, report["findings"])
        self.assertTrue(all(value is False for value in report["claims"].values()))

    def test_candidate_design_passes(self):
        report = module.validate(self.root)
        self.assertEqual("PASS", report["status"])
        self.assertEqual("design_contract_only", report["scope"])
        self.assertTrue(all(value is False for value in report["claims"].values()))

    def test_each_authority_guard_is_enforced(self):
        original = copy.deepcopy(self.config)
        for key, value in original["guards"].items():
            with self.subTest(guard=key):
                self.config = copy.deepcopy(original)
                self.config["guards"][key] = not value
                self.flush()
                self.refused("SCHEMA_INVALID")

    def test_external_portal_is_not_native_composition(self):
        self.config["composition"]["transport"] = "direct_iframe_http"
        self.flush()
        self.refused("SCHEMA_INVALID")

    def test_duplicate_service_hides_missing_service(self):
        self.config["cloudflare_services"][-1] = copy.deepcopy(self.config["cloudflare_services"][0])
        self.flush()
        self.refused("SERVICE_STAGE_DRIFT")

    def test_deferred_services_cannot_become_core_silently(self):
        self.config["cloudflare_services"][-1]["stage"] = "core"
        self.flush()
        self.refused("SERVICE_STAGE_DRIFT")

    def test_resources_cannot_be_declared_enabled(self):
        self.config["cloudflare_services"][0]["enabled"] = True
        self.flush()
        self.refused("SCHEMA_INVALID")

    def test_runtime_claims_are_not_accepted_or_echoed(self):
        self.config["claims"]["all_agents_integrated"] = True
        self.flush()
        self.refused("SCHEMA_INVALID")

    def test_one_shared_surface_binding(self):
        self.base["management_model"]["primary_human_surface"] = "second_portal"
        self.flush()
        self.refused("PARALLEL_MANAGEMENT_PLANE")

    def test_no_parallel_authority(self):
        self.base["management_model"]["no_parallel_authority"] = False
        self.flush()
        self.refused("PARALLEL_MANAGEMENT_PLANE")

    def test_shared_work_and_retry_and_stop_guards(self):
        original = copy.deepcopy(self.base)
        for key in original["work_contract"]:
            with self.subTest(key=key):
                self.base = copy.deepcopy(original)
                self.base["work_contract"][key] = False
                self.flush()
                self.refused("SHARED_WORK_CONTRACT_DRIFT")

    def test_no_direct_proxmox_authority(self):
        self.base["adapters"]["proxmox"]["direct_agent_access_to_proxmox_management"] = True
        self.flush()
        self.refused("PROXMOX_BOUNDARY_DRIFT")

    def test_unknown_config_fields_refused(self):
        self.config["backend_secret"] = "synthetic-withheld-value"
        self.flush()
        self.refused("SCHEMA_INVALID")
        self.assertNotIn("synthetic-withheld-value", json.dumps(module.validate(self.root)))

    def test_duplicate_json_keys_refused(self):
        (self.root / module.CONFIG).write_text('{"version":1,"version":1}')
        self.refused("INPUT_INVALID")

    def test_missing_file_refused(self):
        (self.root / module.CONFIG).unlink()
        self.refused("INPUT_INVALID")

    def test_wrong_shapes_refused_without_traceback(self):
        for value in ([], None, 7, "text"):
            with self.subTest(value=value):
                self.write(module.CONFIG, value)
                self.refused("INPUT_INVALID")
        self.config["guards"] = None
        self.flush()
        self.refused("SCHEMA_INVALID")

    def test_non_finite_numbers_refused(self):
        for number in ("NaN", "Infinity", "-Infinity", "1e999"):
            with self.subTest(number=number):
                (self.root / module.CONFIG).write_text('{"version":' + number + '}')
                self.refused("INPUT_INVALID")

    def test_oversized_input_refused(self):
        (self.root / module.CONFIG).write_bytes(b" " * (module.MAX_BYTES + 1))
        self.refused("INPUT_INVALID")

    def test_deep_input_refused(self):
        (self.root / module.CONFIG).write_text('{"x":' + '[' * 64 + '0' + ']' * 64 + '}')
        self.refused("INPUT_INVALID")

    def test_external_schema_refs_do_not_use_network(self):
        self.schema["$ref"] = "https://schema.invalid/never-fetch"
        self.flush()
        self.refused("EXTERNAL_SCHEMA_REF_FORBIDDEN")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_input_refused(self):
        path = self.root / module.CONFIG
        path.unlink()
        path.symlink_to(self.root / module.SCHEMA)
        self.refused("INPUT_INVALID")

    @unittest.skipUnless(hasattr(os, "mkfifo"), "POSIX FIFO unavailable")
    def test_fifo_input_refused_without_waiting(self):
        path = self.root / module.CONFIG
        path.unlink()
        os.mkfifo(path)
        self.refused("INPUT_INVALID")

    def test_cli_reports_pass_and_failure(self):
        args = [sys.executable, str(ROOT / "tools/validate_cloudflare_os_integration.py"),
                "--root", str(self.root)]
        passed = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(0, passed.returncode, passed.stderr)
        self.assertEqual("PASS", json.loads(passed.stdout)["status"])
        (self.root / module.CONFIG).unlink()
        failed = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(1, failed.returncode, failed.stderr)
        self.assertEqual("FAIL", json.loads(failed.stdout)["status"])


if __name__ == "__main__":
    unittest.main()
