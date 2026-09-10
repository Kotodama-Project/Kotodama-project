"""Synthetic reports exercise projection rules, NOT a deployed runtime."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("agent_status_projection_under_test", ROOT / "tools/project_agent_status.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def inputs():
    # Reduced synthetic consumed-field fixtures; not full registry-schema fixtures.
    registry = {"version": 1, "status": "promoted", "agents": [{
        "id": "synthetic-agent", "name": "Synthetic Agent", "purpose": "Test only",
        "activation_state": "active", "authority": "read_only",
        "implementation": {"kind": "external_adapter", "path": "fixture://adapter"},
    }]}
    contract = {"version": 1, "status": "candidate_only", "common_agent_view": {
        "required_fields": ["kotodama_agent_id", "connection_state", "verification_state"],
        "connection_states": ["unknown", "offline", "idle", "running", "needs_user", "failed", "stalled", "interrupted"],
        "execution_completion_is_not_verification": True,
    }, "work_contract": {"stop_request_requires_stop_observation": True,
        "result_states": ["queued", "running", "needs_user", "execution_settled", "verification_pending", "verified_candidate", "failed", "cancelled", "stalled"]},
        "adapters": {"external_agents": {"state": "planned"}}}
    observations = {"version": 1, "observations": [{
        "kotodama_agent_id": "synthetic-agent", "observation_ref": "fixture:observation-1",
        "adapter_id": "external_agents", "observed_at": "2026-09-10T09:00:00Z",
        "connection_state": "running", "current_work_ref": "fixture:work-1", "run_ref": "fixture:run-1",
        "work_state": "running", "stop_requested_at": None, "stop_observed_at": None,
    }]}
    return registry, contract, observations


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self.registry, self.contract, self.observations = inputs()
        self.obs = self.observations["observations"][0]

    def project(self, as_of="2026-09-10T09:00:30Z", **kwargs):
        return MODULE.project(self.registry, self.contract, self.observations, as_of=as_of, **kwargs)

    def row(self, **kwargs):
        return self.project(**kwargs)["agents"][0]

    def test_fresh_report_is_not_authority(self):
        result = self.project()
        self.assertEqual(result["agents"][0]["connection_state"], "running")
        self.assertEqual(result["agents"][0]["controls"], [])
        self.assertEqual(result["access_evaluation"], "not_evaluated_do_not_serve")
        self.assertFalse(result["runtime_evidence_verified"])
        self.assertFalse(result["mutations_enabled"])
        self.assertIn("adapter_report_not_authenticated", result["agents"][0]["diagnostics"])

    def test_unbound_candidate_cannot_look_running(self):
        self.registry["status"] = "candidate_only"
        self.registry["agents"][0]["activation_state"] = "planned"
        self.registry["agents"][0]["implementation"] = {"kind": "unbound", "path": None}
        row = self.row()
        self.assertEqual(row["connection_state"], "unknown")
        self.assertEqual(row["reported_connection_state"], "running")
        self.assertIn("runtime_unbound", row["diagnostics"])
        self.assertIsNone(row["current_work_ref"])

    def test_disabled_and_retired_cannot_look_running(self):
        for state in ("disabled", "retired", "candidate", "planned"):
            with self.subTest(state=state):
                self.registry["agents"][0]["activation_state"] = state
                self.assertEqual(self.row()["connection_state"], "unknown")

    def test_missing_observation_is_unknown_not_offline(self):
        self.observations["observations"] = []
        row = self.row()
        self.assertEqual(row["connection_state"], "unknown")
        self.assertEqual(row["observation_freshness"], "missing")
        self.assertEqual(row["stop_state"], "unknown")

    def test_exact_expiry_and_old_report_cannot_look_running(self):
        for instant in ("2026-09-10T09:02:00Z", "2026-09-11T09:00:00Z"):
            with self.subTest(instant=instant):
                row = self.row(as_of=instant)
                self.assertEqual(row["connection_state"], "unknown")
                self.assertEqual(row["execution_state"], "unknown")
                self.assertEqual(row["observation_freshness"], "stale")

    def test_future_report_is_not_current(self):
        row = self.row(as_of="2026-09-10T08:59:59Z")
        self.assertEqual(row["connection_state"], "unknown")
        self.assertEqual(row["observation_freshness"], "future")

    def test_timezone_normalization(self):
        self.obs["observed_at"] = "2026-09-10T18:00:00+09:00"
        self.assertEqual(self.row()["observation_freshness"], "fresh")

    def test_execution_is_never_independent_verification(self):
        for state in ("execution_settled", "verification_pending", "verified_candidate"):
            with self.subTest(state=state):
                self.obs["work_state"] = state
                row = self.row()
                self.assertEqual(row["execution_state"], "execution_settled")
                self.assertEqual(row["verification_state"], "not_evaluated")

    def test_stop_request_is_not_stop_confirmation(self):
        self.obs["stop_requested_at"] = "2026-09-10T08:59:50Z"
        self.assertEqual(self.row()["stop_state"], "requested")
        self.assertEqual(self.row()["execution_state"], "running")

    def test_cancelled_claim_requires_stop_observation(self):
        self.obs["work_state"] = "cancelled"
        self.obs["stop_requested_at"] = "2026-09-10T08:59:50Z"
        row = self.row()
        self.assertEqual(row["execution_state"], "unknown")
        self.assertIn("cancellation_not_observed", row["diagnostics"])

    def test_observed_stop_is_bound_and_expires(self):
        self.obs.update(work_state="cancelled", connection_state="interrupted",
                        stop_requested_at="2026-09-10T08:59:50Z", stop_observed_at="2026-09-10T08:59:55Z")
        self.assertEqual(self.row()["stop_state"], "observed")
        self.assertEqual(self.row()["execution_state"], "cancelled")
        self.assertEqual(self.row(as_of="2026-09-10T09:02:00Z")["stop_state"], "unknown")

    def test_conflicting_stop_or_stop_without_request_rejected(self):
        self.obs["stop_observed_at"] = "2026-09-10T08:59:55Z"
        with self.assertRaises(MODULE.InputError):
            self.project()
        self.obs["stop_requested_at"] = "2026-09-10T08:59:50Z"
        with self.assertRaises(MODULE.InputError):
            self.project()

    def test_invalid_stop_time_order_rejected(self):
        self.obs.update(work_state="cancelled", connection_state="interrupted",
                        stop_requested_at="2026-09-10T08:59:50Z", stop_observed_at="2026-09-10T08:59:40Z")
        with self.assertRaises(MODULE.InputError):
            self.project()

    def test_duplicate_agent_observations_rejected_not_last_write_wins(self):
        self.observations["observations"].append(copy.deepcopy(self.obs))
        with self.assertRaises(MODULE.InputError):
            self.project()

    def test_unknown_agents_adapters_states_and_extra_fields_rejected(self):
        for key, value in (("kotodama_agent_id", "unknown"), ("adapter_id", "unknown"),
                           ("connection_state", "healthy"), ("work_state", "success"), ("token", "secret")):
            with self.subTest(key=key):
                old = copy.deepcopy(self.obs)
                self.obs[key] = value
                with self.assertRaises(MODULE.InputError):
                    self.project()
                self.obs.clear()
                self.obs.update(old)

    def test_partial_work_run_binding_rejected(self):
        self.obs["run_ref"] = None
        with self.assertRaises(MODULE.InputError):
            self.project()

    def test_same_run_cannot_be_attributed_to_two_agents(self):
        other = copy.deepcopy(self.registry["agents"][0])
        other["id"] = "second-agent"
        self.registry["agents"].append(other)
        obs = dict(self.obs, kotodama_agent_id="second-agent", observation_ref="fixture:second")
        self.observations["observations"].append(obs)
        with self.assertRaises(MODULE.InputError):
            self.project()

    def test_new_common_view_field_requires_upgrade(self):
        self.contract["common_agent_view"]["required_fields"].append("future_required_field")
        with self.assertRaises(MODULE.InputError):
            self.project()

    def test_changed_safety_contract_rejected(self):
        self.contract["work_contract"]["stop_request_requires_stop_observation"] = False
        with self.assertRaises(MODULE.InputError):
            self.project()

    def test_bad_timestamps_rejected(self):
        for value in (None, "2026-09-10", "2026-09-10T09:00:00", "2026-99-10T09:00:00Z",
                      "2026-09-10T09:00:00-00:00", "2026-09-10T09:00:00+09:60"):
            with self.subTest(value=value), self.assertRaises(MODULE.InputError):
                self.project(as_of=value)

    def test_bad_age_limits_rejected(self):
        for age in (True, 0, -1, 86401, 1.5):
            with self.subTest(age=age), self.assertRaises(MODULE.InputError):
                self.project(max_age_seconds=age)

    def test_boolean_versions_rejected(self):
        self.observations["version"] = True
        with self.assertRaises(MODULE.InputError):
            self.project()

    def test_projection_is_deterministic_and_does_not_mutate(self):
        before = copy.deepcopy((self.registry, self.contract, self.observations))
        first = self.project()
        self.assertEqual(first, self.project())
        self.assertEqual(before, (self.registry, self.contract, self.observations))

    def test_untrusted_extra_registry_text_not_echoed(self):
        self.registry["agents"][0]["runtime_evidence"] = {"token": "DO-NOT-ECHO"}
        self.assertNotIn("DO-NOT-ECHO", json.dumps(self.project()))

    def test_markdown_cannot_inject_html_or_table_rows(self):
        report = self.project()
        report["agents"][0]["kotodama_agent_id"] = "<script>|\nBAD"
        rendered = MODULE.markdown(report)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("\nBAD", rendered)
        self.assertIn("&#124;", rendered)


class InputAndCliTests(unittest.TestCase):
    def test_malformed_duplicate_nonfinite_and_nonobject_json_rejected(self):
        cases = (b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'{"a":1e999}', b'[]', b'\xff', b'{')
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(MODULE.InputError):
                MODULE.parse_json(raw)

    def test_deep_large_and_oversized_collection_rejected(self):
        cases = (b'{"a":' * 30 + b'0' + b'}' * 30,
                 b' ' * (MODULE.MAX_BYTES + 1),
                 json.dumps({"a": list(range(MODULE.MAX_ITEMS + 1))}).encode())
        for raw in cases:
            with self.subTest(size=len(raw)), self.assertRaises(MODULE.InputError):
                MODULE.parse_json(raw)

    def test_regular_file_symlink_directory_and_fifo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normal = root / "normal"
            normal.write_bytes(b'{}')
            self.assertEqual(MODULE.load_json(normal), {})
            with self.assertRaises((MODULE.InputError, OSError)):
                MODULE.load_json(root)
            if hasattr(os, "mkfifo"):
                fifo = root / "fifo"
                os.mkfifo(fifo)
                with self.assertRaises((MODULE.InputError, OSError)):
                    MODULE.load_json(fifo)

    def test_symlink_input_is_refused_when_supported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            normal = root / "normal"
            normal.write_bytes(b'{}')
            link = root / "link"
            try:
                link.symlink_to(normal)
            except (NotImplementedError, OSError) as exc:
                if isinstance(exc, NotImplementedError) or getattr(exc, "winerror", None) == 1314:
                    self.skipTest("symlink creation is unavailable for this test principal")
                raise
            with self.assertRaises((MODULE.InputError, OSError)):
                MODULE.load_json(link)

    def test_bundle_changes_for_code_skill_or_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in MODULE.BUNDLE:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'original')
            initial = MODULE.bundle_sha256(root)
            for name in MODULE.BUNDLE:
                path = root / name
                path.write_bytes(b'changed')
                self.assertNotEqual(initial, MODULE.bundle_sha256(root))
                path.write_bytes(b'original')
            self.assertNotEqual(initial, MODULE.bundle_sha256(root, b'override-contract'))

    def test_cli_on_repository_registry_without_live_observations(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/project_agent_status.py"),
                                 "--as-of", "2026-09-10T09:00:30Z"], capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["summary"]["supplied_observations"], 0)
        self.assertTrue(all(row["connection_state"] == "unknown" for row in report["agents"]))
        self.assertFalse(report["mutations_enabled"])

    def test_cli_reports_hashes_of_the_parsed_bytes(self):
        registry, contract, observations = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "governance").mkdir()
            for path, data in ((MODULE.REGISTRY, registry), (MODULE.CONTRACT, contract), ("obs.json", observations)):
                (root / path).write_text(json.dumps(data), encoding="utf-8")
            result = subprocess.run([sys.executable, str(ROOT / "tools/project_agent_status.py"),
                                     "--root", str(root), "--observations", str(root / "obs.json"),
                                     "--as-of", "2026-09-10T09:00:30Z"], capture_output=True, text=True, encoding="utf-8", timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["input_sha256"]["registry"], hashlib.sha256((root / MODULE.REGISTRY).read_bytes()).hexdigest())
            self.assertEqual(report["bundle_sha256"], MODULE.bundle_sha256(ROOT, (root / MODULE.CONTRACT).read_bytes()))

    def test_cli_mismatched_skill_bundle_fails_before_projection(self):
        result = subprocess.run([sys.executable, str(ROOT / "tools/project_agent_status.py"),
                                 "--expected-bundle-sha256", "0" * 64], capture_output=True, text=True, encoding="utf-8", timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("bundle mismatch", result.stderr)

    def test_cli_usage_errors_do_not_echo_input(self):
        for arguments in (("--format", "PRIVATE-MARKER"), ("--PRIVATE-MARKER",),
                          ("--max-age-seconds", "PRIVATE-MARKER")):
            with self.subTest(arguments=arguments):
                result = subprocess.run([sys.executable, str(ROOT / "tools/project_agent_status.py"),
                                         *arguments], capture_output=True, text=True, encoding="utf-8", timeout=10)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("PRIVATE-MARKER", result.stderr)

    def test_cli_utf8_output_under_legacy_console_encoding(self):
        env = dict(os.environ, PYTHONIOENCODING="ascii")
        result = subprocess.run([sys.executable, str(ROOT / "tools/project_agent_status.py"),
                                 "--as-of", "2026-09-10T09:00:30Z", "--format", "markdown"],
                                env=env, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("offline diagnostic projection", result.stdout.decode("utf-8"))

    def test_pure_projector_cannot_access_files_or_network(self):
        registry, contract, observations = inputs()
        with patch("builtins.open", side_effect=AssertionError("file I/O")), \
             patch("socket.socket", side_effect=AssertionError("network")), \
             patch("subprocess.run", side_effect=AssertionError("process")):
            report = MODULE.project(registry, contract, observations, as_of="2026-09-10T09:00:30Z")
        self.assertFalse(report["mutations_enabled"])


if __name__ == "__main__":
    unittest.main()
