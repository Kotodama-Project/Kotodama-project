"""Adversarial offline snapshots: no live agent, identity service or deployment."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("status_hardening", ROOT / "tools/project_agent_status.py")
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def inputs():
    registry = {"version": 1, "status": "promoted", "agents": [{
        "id": "sample", "name": "Sample", "purpose": "Synthetic input only",
        "activation_state": "active", "authority": "read_only",
        "implementation": {"kind": "script", "path": "fixture://sample"},
    }]}
    contract = {"version": 1, "status": "candidate_only", "common_agent_view": {
        "required_fields": ["kotodama_agent_id", "connection_state", "verification_state"],
        "connection_states": ["unknown", "offline", "idle", "running", "interrupted"],
        "execution_completion_is_not_verification": True,
    }, "work_contract": {
        "result_states": ["running", "failed", "execution_settled", "verification_pending", "verified_candidate", "cancelled"],
        "stop_request_requires_stop_observation": True,
    }, "adapters": {"external": {"state": "planned"}}}
    observations = {"version": 1, "observations": [{
        "kotodama_agent_id": "sample", "observation_ref": "fixture:observation",
        "adapter_id": "external", "observed_at": "2026-09-11T00:00:00Z",
        "connection_state": "running", "current_work_ref": "fixture:work", "run_ref": "fixture:run",
        "work_state": "running", "stop_requested_at": None, "stop_observed_at": None,
    }]}
    return registry, contract, observations


def project(registry=None, contract=None, observations=None):
    r, c, o = inputs()
    return M.project(registry if registry is not None else r,
                     contract if contract is not None else c,
                     observations if observations is not None else o,
                     as_of="2026-09-11T00:00:30Z")


class JsonBoundaryTests(unittest.TestCase):
    def test_integer_digit_limit_is_a_normalized_input_error(self):
        with self.assertRaises(M.InputError):
            M.parse_json(b'{"value":' + b'9' * 5000 + b'}')

    def test_unpaired_unicode_surrogates_are_refused_at_parse_boundary(self):
        for text in (r'{"value":"\ud800"}', r'{"\udfff":0}', r'{"value":"\udc00"}'):
            with self.subTest(text=text), self.assertRaises(M.InputError):
                M.parse_json(text.encode())

    def test_valid_surrogate_pair_and_multilingual_text_survive(self):
        self.assertEqual(M.parse_json(br'{"value":"\ud83d\ude80"}')["value"], "🚀")
        self.assertEqual(M.parse_json('{"value":"日本語é"}'.encode())["value"], "日本語é")

    def test_total_node_budget_blocks_wide_small_collections(self):
        # Each individual collection is within MAX_ITEMS; the aggregate is not.
        value = {"branches": [[0] * 300 for _ in range(300)]}
        with self.assertRaises(M.InputError):
            M.bounded(value)

    def test_direct_api_rejects_non_json_values_and_non_string_keys(self):
        for value in ({"value": object()}, {1: "value"}, {"value": (1, 2)}, {"value": b"x"}):
            with self.subTest(kind=type(value)), self.assertRaises(M.InputError):
                M.bounded(value)

    def test_direct_api_rejects_oversized_display_text(self):
        r, _, _ = inputs()
        r["agents"][0]["purpose"] = "x" * (M.MAX_BYTES + 1)
        with self.assertRaises(M.InputError):
            project(registry=r)

    def test_duplicate_required_view_fields_are_not_silently_deduplicated(self):
        _, c, _ = inputs()
        c["common_agent_view"]["required_fields"].append("kotodama_agent_id")
        with self.assertRaises(M.InputError):
            project(contract=c)

    def test_extreme_utc_conversion_is_a_normalized_refusal(self):
        for instant in ("0001-01-01T00:00:00+23:59", "9999-12-31T23:59:59-23:59"):
            with self.subTest(instant=instant), self.assertRaises(M.InputError):
                M.timestamp(instant)

    def test_cyclic_direct_input_does_not_raise_recursion_error(self):
        value = {}
        value["self"] = value
        with self.assertRaises(M.InputError):
            M.bounded(value)


class StableReadTests(unittest.TestCase):
    def test_empty_and_normal_files_preserve_exact_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input"
            for data in (b"", b"{}\n", "日本語".encode()):
                path.write_bytes(data)
                self.assertEqual(M.regular_bytes(path), data)

    def test_file_changed_after_open_before_read_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input"
            path.write_bytes(b"original")
            real_fdopen = os.fdopen

            def changed(fd, *args, **kwargs):
                path.write_bytes(b"changed-to-different-length")
                return real_fdopen(fd, *args, **kwargs)

            with patch.object(M.os, "fdopen", side_effect=changed):
                with self.assertRaises(M.InputError):
                    M.regular_bytes(path)

    def test_replacement_between_precheck_and_open_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input"
            path.write_bytes(b"original")
            replacement = Path(tmp) / "replacement"
            replacement.write_bytes(b"replacement")
            real_open = os.open

            def swapped(*args, **kwargs):
                os.replace(replacement, path)
                return real_open(*args, **kwargs)

            with patch.object(M.os, "open", side_effect=swapped):
                with self.assertRaises(M.InputError):
                    M.regular_bytes(path)

    def test_file_removed_during_read_is_refused(self):
        # Removing open files is supported on POSIX; Windows denies it itself.
        if os.name == "nt":
            self.skipTest("Windows prohibits unlink of an open input")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input"
            path.write_bytes(b"original")
            real_fdopen = os.fdopen

            def removed(fd, *args, **kwargs):
                path.unlink()
                return real_fdopen(fd, *args, **kwargs)

            with patch.object(M.os, "fdopen", side_effect=removed):
                with self.assertRaises((M.InputError, OSError)):
                    M.regular_bytes(path)

    def test_stability_failure_closes_the_descriptor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input"
            path.write_bytes(b"data")
            original_open, original_fdopen = os.open, os.fdopen
            descriptors = []

            def tracked(*args, **kwargs):
                fd = original_open(*args, **kwargs)
                descriptors.append(fd)
                return fd

            def changed(fd, *args, **kwargs):
                path.write_bytes(b"a much longer payload")
                return original_fdopen(fd, *args, **kwargs)

            with patch.object(M.os, "open", side_effect=tracked), patch.object(M.os, "fdopen", side_effect=changed):
                with self.assertRaises(M.InputError):
                    M.regular_bytes(path)
            self.assertEqual(len(descriptors), 1)
            with self.assertRaises(OSError):
                os.fstat(descriptors[0])


class ActionableDiagnosticsTests(unittest.TestCase):
    def test_each_finding_has_only_a_fixed_read_only_next_step(self):
        report = project()
        row = report["agents"][0]
        self.assertEqual(report["schema_revision"], "agent-status-v2")
        self.assertEqual(len(row["next_steps"]), len(row["diagnostics"]))
        for item in row["next_steps"]:
            self.assertEqual(set(item), {"code", "action"})
            self.assertIn(item["code"], row["diagnostics"])
            self.assertIsInstance(item["action"], str)
        self.assertEqual(row["controls"], [])
        self.assertFalse(report["mutations_enabled"])
        self.assertFalse(report["runtime_evidence_verified"])

    def test_summary_counts_missing_stale_future_and_fresh_separately(self):
        r, c, o = inputs()
        for index, instant in enumerate((None, "2026-09-10T00:00:00Z", "2026-09-12T00:00:00Z")):
            agent = copy.deepcopy(r["agents"][0])
            agent["id"] = f"sample-{index}"
            r["agents"].append(agent)
            if instant is not None:
                obs = dict(o["observations"][0], kotodama_agent_id=agent["id"],
                           observation_ref=f"fixture:observation-{index}", run_ref=f"fixture:run-{index}",
                           observed_at=instant)
                o["observations"].append(obs)
        report = project(r, c, o)
        self.assertEqual(report["summary"]["observation_freshness"], {
            "missing": 1, "stale": 1, "future": 1, "fresh": 1})
        self.assertNotIn("healthy_agents", report["summary"])

    def test_stop_advice_does_not_authorize_retry_or_restart(self):
        _, _, o = inputs()
        o["observations"][0]["stop_requested_at"] = "2026-09-10T23:59:59Z"
        row = project(observations=o)["agents"][0]
        advice = {entry["code"]: entry["action"] for entry in row["next_steps"]}
        self.assertIn("stop_confirmation_missing", advice)
        self.assertIn("reconcile", advice["stop_confirmation_missing"].lower())
        self.assertEqual(row["stop_state"], "requested")
        self.assertEqual(row["controls"], [])

    def test_markdown_exposes_next_steps_without_private_display_text(self):
        r, c, o = inputs()
        r["agents"][0]["purpose"] = "PRIVATE-PURPOSE"
        report = project(r, c, o)
        output = M.markdown(report)
        self.assertIn("Next step", output)
        self.assertNotIn("PRIVATE-PURPOSE", output)

    def test_cancellation_stays_unverified_in_actionable_output(self):
        _, _, o = inputs()
        o["observations"][0].update(work_state="cancelled", connection_state="interrupted",
            stop_requested_at="2026-09-10T23:59:58Z", stop_observed_at="2026-09-10T23:59:59Z")
        report = project(observations=o)
        self.assertEqual(report["agents"][0]["stop_state"], "observed")
        self.assertEqual(report["agents"][0]["verification_state"], "not_evaluated")
        self.assertFalse(report["runtime_evidence_verified"])

    def test_v2_projection_is_deterministic_and_preserves_input(self):
        values = inputs()
        before = copy.deepcopy(values)
        self.assertEqual(project(*values), project(*values))
        self.assertEqual(values, before)


if __name__ == "__main__":
    unittest.main()
