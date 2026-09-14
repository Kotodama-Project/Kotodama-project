from __future__ import annotations

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
CONFIG_PATH = ROOT / "governance" / "openmaus-integration.json"
SCHEMA_PATH = ROOT / "schemas" / "openmaus-integration.schema.json"
VALIDATOR_PATH = ROOT / "tools" / "validate_openmaus_integration.py"

spec = importlib.util.spec_from_file_location("validate_openmaus_integration", VALIDATOR_PATH)
assert spec and spec.loader
validator_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator_module)


class OpenMausIntegrationTest(unittest.TestCase):
    def load(self, path: Path):
        return json.loads(path.read_text(encoding="utf-8"))

    def test_contract_validates_against_schema(self) -> None:
        schema = self.load(SCHEMA_PATH)
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(validator.iter_errors(self.load(CONFIG_PATH)), key=lambda error: list(error.path))
        self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def test_validator_passes_candidate_contract(self) -> None:
        process = subprocess.run(
            [sys.executable, str(VALIDATOR_PATH), "--root", str(ROOT), "--format", "json"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(0, process.returncode, process.stdout + process.stderr)
        report = json.loads(process.stdout)
        self.assertEqual("PASS", report["status"])
        self.assertEqual(5, report["summary"]["agent_group_count"])
        self.assertEqual(3, report["summary"]["execution_zone_count"])
        self.assertEqual(4, report["summary"]["rollout_phase_count"])
        self.assertTrue(all(value is False for value in report["claims"].values()))

    def test_groups_are_cross_functional_views_not_silos(self) -> None:
        config = self.load(CONFIG_PATH)
        self.assertEqual("view_and_routing_only_not_authority_silos", config["management_model"]["grouping_semantics"])
        self.assertTrue(config["management_model"]["no_parallel_authority"])
        self.assertTrue(all(group["may_share_work_across_groups"] for group in config["agent_groups"]))
        self.assertTrue(config["work_contract"]["shared_work_identity_required"])
        self.assertTrue(config["work_contract"]["copy_paste_handoff_is_not_canonical"])

    def test_execution_settlement_is_not_verification(self) -> None:
        config = self.load(CONFIG_PATH)
        self.assertTrue(config["common_agent_view"]["execution_completion_is_not_verification"])
        states = set(config["work_contract"]["result_states"])
        self.assertIn("execution_settled", states)
        self.assertIn("verification_pending", states)
        self.assertIn("verified_candidate", states)

    def test_upstream_mcp_limitations_remain_explicit(self) -> None:
        config = self.load(CONFIG_PATH)
        omitted = set(config["adapters"]["openmaus_mcp"]["not_exposed_by_upstream_v1_mcp"])
        self.assertTrue(
            {
                "approve_requests",
                "remember_permission_grants",
                "delete_data",
                "import_teams",
                "change_credentials",
                "computer_or_vm_lifecycle",
            }.issubset(omitted)
        )
        self.assertEqual(
            "missing_mcp_capability_must_not_be_simulated_as_success",
            config["adapters"]["openmaus_mcp"]["kotodama_policy"],
        )

    def test_proxmox_boundary_is_not_agent_root(self) -> None:
        config = self.load(CONFIG_PATH)
        proxmox = config["adapters"]["proxmox"]
        self.assertFalse(proxmox["direct_agent_access_to_proxmox_management"])
        self.assertTrue(proxmox["management_adapter_required"])
        self.assertTrue(proxmox["openmaus_byo_vps_pattern"]["docker_group_is_root_equivalent"])
        self.assertTrue(proxmox["openmaus_byo_vps_pattern"]["dedicated_worker_required"])

    def test_mutation_catches_parallel_authority(self) -> None:
        config = self.load(CONFIG_PATH)
        mutated = copy.deepcopy(config)
        mutated["management_model"]["no_parallel_authority"] = False
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "governance").mkdir()
            (root / "schemas").mkdir()
            (root / "governance" / "openmaus-integration.json").write_text(
                json.dumps(mutated, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (root / "schemas" / "openmaus-integration.schema.json").write_text(
                SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
            report = validator_module.validate(root)
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(any(item["code"] in {"schema-invalid", "parallel-authority"} for item in report["findings"]))

    def test_mutation_catches_direct_proxmox_access(self) -> None:
        config = self.load(CONFIG_PATH)
        mutated = copy.deepcopy(config)
        mutated["adapters"]["proxmox"]["direct_agent_access_to_proxmox_management"] = True
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "governance").mkdir()
            (root / "schemas").mkdir()
            for relative in config["management_model"]["canonical_owners"].values():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n", encoding="utf-8")
            (root / "governance" / "openmaus-integration.json").write_text(
                json.dumps(mutated, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            (root / "schemas" / "openmaus-integration.schema.json").write_text(
                SCHEMA_PATH.read_text(encoding="utf-8"), encoding="utf-8"
            )
            report = validator_module.validate(root)
        self.assertEqual("FAIL", report["status"])
        self.assertTrue(any(item["code"] in {"schema-invalid", "proxmox-direct-agent-access"} for item in report["findings"]))


if __name__ == "__main__":
    unittest.main()
