"""Offline contract controls; these checks do not prove agent deployment."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
CONFIG_PATH = ROOT / "governance/openmaus-integration.json"
SCHEMA_PATH = ROOT / "schemas/openmaus-integration.schema.json"
VALIDATOR_PATH = ROOT / "tools/validate_openmaus_integration.py"
spec = importlib.util.spec_from_file_location("validate_openmaus_integration", VALIDATOR_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class OpenMausIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        self.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        for relative in module.OWNER_DOCUMENTS.values():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("Synthetic governing-contract reference.\n", encoding="utf-8")
        self.flush()

    def write(self, relative: Path, value) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def flush(self) -> None:
        self.write(module.CONFIG_PATH, self.config)
        self.write(module.SCHEMA_PATH, self.schema)

    def refused(self, code: str) -> dict:
        result = module.validate(self.root)
        self.assertEqual("FAIL", result["status"])
        self.assertIn(code, {item["code"] for item in result["findings"]})
        self.assertTrue(all(value is False for value in result["claims"].values()))
        self.assertEqual("NO_GO_UNPUBLISHED", result["public_beta"])
        return result

    def cli(self, format: str = "json") -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(VALIDATOR_PATH), "--root", str(self.root),
                               "--format", format], text=True, capture_output=True, timeout=10)

    def test_contract_validates_against_schema(self) -> None:
        Draft202012Validator.check_schema(self.schema)
        self.assertTrue(Draft202012Validator(self.schema, format_checker=FormatChecker()).is_valid(self.config))

    def test_validator_passes_current_repository_contract(self) -> None:
        result = module.validate(ROOT)
        self.assertEqual("PASS", result["status"])
        self.assertEqual("design_contract_only", result["scope"])
        self.assertEqual(5, result["summary"]["agent_group_count"])
        self.assertEqual(3, result["summary"]["execution_zone_count"])
        self.assertEqual(4, result["summary"]["rollout_phase_count"])
        self.assertTrue(all(value is False for value in result["claims"].values()))

    def test_cli_passes_design_only_candidate(self) -> None:
        process = self.cli()
        self.assertEqual(0, process.returncode, process.stderr)
        result = json.loads(process.stdout)
        self.assertEqual("PASS", result["status"])
        self.assertEqual("design_contract_only", result["scope"])
        self.assertTrue(all(value is False for value in result["claims"].values()))

    def test_cross_functional_groups_keep_one_authority(self) -> None:
        self.assertTrue(all(group["may_share_work_across_groups"] for group in self.config["agent_groups"]))
        self.assertTrue(self.config["work_contract"]["shared_work_identity_required"])
        self.assertTrue(self.config["work_contract"]["copy_paste_handoff_is_not_canonical"])
        self.config["management_model"]["no_parallel_authority"] = False
        self.flush()
        self.refused("schema-invalid")

    def test_execution_settlement_is_not_verification(self) -> None:
        self.assertTrue(self.config["common_agent_view"]["execution_completion_is_not_verification"])
        self.assertTrue({"execution_settled", "verification_pending", "verified_candidate"}
                        <= set(self.config["work_contract"]["result_states"]))
        self.config["common_agent_view"]["execution_completion_is_not_verification"] = False
        self.flush()
        self.refused("schema-invalid")

    def test_owned_execution_verification_boundary_survives_a_relaxed_schema(self) -> None:
        original = copy.deepcopy(self.config)
        key = "execution_completion_is_not_verification"
        view_schema = self.schema["properties"]["common_agent_view"]
        view_schema["properties"][key] = {}
        view_schema["required"].remove(key)
        self.flush()
        self.assertEqual("PASS", module.validate(self.root)["status"])
        self.assertEqual(0, self.cli().returncode)
        for label, value in (("false", False), ("zero", 0), ("one", 1), ("null", None),
                             ("string", "synthetic-withheld-value"), ("array", []), ("object", {}),
                             ("missing", None)):
            with self.subTest(value=label):
                self.config = copy.deepcopy(original)
                if label == "missing":
                    del self.config["common_agent_view"][key]
                else:
                    self.config["common_agent_view"][key] = value
                self.assertTrue(Draft202012Validator(self.schema).is_valid(self.config))
                self.assertTrue({"execution_settled", "verification_pending"} <= set(self.config["work_contract"]["result_states"]))
                self.flush()
                self.refused("execution-verification-collapse")
                process = self.cli()
                self.assertEqual(1, process.returncode, process.stderr)
                self.assertEqual("", process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual("FAIL", result["status"])
                self.assertEqual([{"code": "execution-verification-collapse", "message": "execution-verification-collapse"}], result["findings"])
                self.assertEqual("design_contract_only", result["scope"])
                self.assertEqual("NO_GO_UNPUBLISHED", result["public_beta"])
                self.assertTrue(all(value is False for value in result["claims"].values()))
                self.assertNotIn("synthetic-withheld", process.stdout)

    def test_upstream_mcp_capabilities_do_not_overlap_gaps(self) -> None:
        original = copy.deepcopy(self.config)
        for capability in original["adapters"]["openmaus_mcp"]["not_exposed_by_upstream_v1_mcp"]:
            with self.subTest(capability=capability):
                self.config = copy.deepcopy(original)
                self.config["adapters"]["openmaus_mcp"]["supported_for_integration"].append(capability)
                self.flush()
                self.refused("mcp-boundary-drift")
        self.config = copy.deepcopy(original)
        self.config["adapters"]["openmaus_mcp"]["supported_for_integration"].append("unverified_operation")
        self.flush()
        self.refused("mcp-boundary-drift")

    def test_proxmox_remains_management_adapter_only(self) -> None:
        self.assertTrue(self.config["adapters"]["proxmox"]["management_adapter_required"])
        self.assertTrue(self.config["adapters"]["proxmox"]["openmaus_byo_vps_pattern"]["docker_group_is_root_equivalent"])
        self.assertTrue(self.config["adapters"]["proxmox"]["openmaus_byo_vps_pattern"]["dedicated_worker_required"])
        self.config["adapters"]["proxmox"]["direct_agent_access_to_proxmox_management"] = True
        self.flush()
        self.refused("schema-invalid")

    def test_each_view_field_and_connection_state_is_mandatory(self) -> None:
        original = copy.deepcopy(self.config)
        schema_validator = Draft202012Validator(self.schema)
        for key in ("required_fields", "connection_states"):
            for member in original["common_agent_view"][key]:
                with self.subTest(key=key, member=member):
                    self.config = copy.deepcopy(original)
                    self.config["common_agent_view"][key].remove(member)
                    self.assertFalse(schema_validator.is_valid(self.config))
                    self.flush()
                    self.refused("schema-invalid")

    def test_view_order_is_not_semantic(self) -> None:
        for key in ("required_fields", "connection_states"):
            self.config["common_agent_view"][key].reverse()
        self.flush()
        self.assertEqual("PASS", module.validate(self.root)["status"])

    def test_view_unknown_or_duplicate_members_are_refused(self) -> None:
        original = copy.deepcopy(self.config)
        for key in ("required_fields", "connection_states"):
            for replacement in ("unrecognized", original["common_agent_view"][key][0]):
                with self.subTest(key=key, replacement=replacement):
                    self.config = copy.deepcopy(original)
                    self.config["common_agent_view"][key][-1] = replacement
                    self.flush()
                    self.refused("schema-invalid")

    def test_weakened_view_schema_does_not_weaken_owned_members(self) -> None:
        self.schema["properties"]["common_agent_view"] = {}
        self.config["common_agent_view"]["required_fields"] = ["display_name"]
        self.config["common_agent_view"]["connection_states"] = ["running"]
        self.flush()
        self.refused("agent-view-drift")

    def test_invalid_shapes_return_before_semantic_checks(self) -> None:
        original = copy.deepcopy(self.config)
        for key in ("agent_groups", "management_model", "adapters", "execution_zones", "rollout"):
            with self.subTest(key=key):
                self.config = copy.deepcopy(original)
                self.config[key] = None
                self.flush()
                self.refused("schema-invalid")
        for value in ([], None, 7, "synthetic"):
            with self.subTest(root_type=type(value).__name__):
                self.write(module.CONFIG_PATH, value)
                self.refused("input-invalid")

    def test_shape_failures_remain_structured_at_cli(self) -> None:
        for value in ([], {**self.config, "agent_groups": None}):
            self.write(module.CONFIG_PATH, value)
            process = self.cli()
            self.assertEqual(1, process.returncode, process.stderr)
            self.assertEqual("", process.stderr)
            self.assertEqual("FAIL", json.loads(process.stdout)["status"])

    def test_nonlocal_refs_are_refused_before_validator_construction(self) -> None:
        original = copy.deepcopy(self.schema)
        for keyword in ("$ref", "$dynamicRef", "$recursiveRef"):
            for value in ("https://schema.invalid/not-used", "other.json", "file:///not-used", 3):
                with self.subTest(keyword=keyword, value_type=type(value).__name__):
                    self.schema = copy.deepcopy(original)
                    self.schema["$defs"] = {"unused": {keyword: value}}
                    self.flush()
                    with patch.object(module.Draft202012Validator, "check_schema",
                                      side_effect=AssertionError("validator must not be constructed")):
                        self.refused("external-schema-ref-forbidden")

    def test_local_fragment_refs_remain_usable(self) -> None:
        self.schema["$defs"] = {"contract": {"type": "object"}}
        self.schema["$ref"] = "#/$defs/contract"
        self.flush()
        self.assertEqual("PASS", module.validate(self.root)["status"])

    def test_schema_diagnostics_do_not_reflect_instance_keys_or_values(self) -> None:
        original = copy.deepcopy(self.config)
        marker = "synthetic-withheld-marker"
        for mutate in (lambda c: c["upstream"].update(pinned_commit=marker),
                       lambda c: c.update({marker: marker})):
            self.config = copy.deepcopy(original)
            mutate(self.config)
            self.flush()
            self.refused("schema-invalid")
            for format in ("json", "markdown"):
                with self.subTest(format=format):
                    process = self.cli(format)
                    self.assertEqual(1, process.returncode)
                    self.assertNotIn(marker, process.stdout + process.stderr)
                    self.assertNotIn(str(self.root), process.stdout + process.stderr)
                    self.assertIn("schema-invalid", process.stdout)
                    self.assertEqual("", process.stderr)

    def test_bound_strict_json_inputs_are_refused(self) -> None:
        samples = (b'{"version":1,"version":1}', b'\xff', b'{"x":NaN}', b'{"x":1e999}',
                   b'{"x":' + b'[' * 40 + b'0' + b']' * 40 + b'}', b' ' * (256 * 1024 + 1))
        for raw in samples:
            with self.subTest(sample_bytes=len(raw)):
                (self.root / module.CONFIG_PATH).write_bytes(raw)
                self.refused("input-invalid")

    def test_missing_owner_contract_is_refused(self) -> None:
        (self.root / module.OWNER_DOCUMENTS["knowledge"]).unlink()
        self.refused("canonical-owner-missing")

    def test_argument_errors_do_not_reflect_input(self) -> None:
        marker = "synthetic-withheld-argument"
        process = subprocess.run([sys.executable, str(VALIDATOR_PATH), "--unknown", marker],
                                 text=True, capture_output=True, timeout=10)
        self.assertEqual(2, process.returncode)
        self.assertNotIn(marker, process.stdout + process.stderr)
        self.assertEqual("invalid arguments\n", process.stderr)


if __name__ == "__main__":
    unittest.main()
