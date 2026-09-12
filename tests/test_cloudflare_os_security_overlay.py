from __future__ import annotations

import copy
import hashlib
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
TOOLS_PATH = ROOT / "tools"
VALIDATOR_PATH = TOOLS_PATH / "validate_cloudflare_os_security_candidate.py"
if str(TOOLS_PATH) not in sys.path:
    sys.path.insert(0, str(TOOLS_PATH))
import validate_cloudflare_os_security_candidate as candidate_validator

from tools.cloudflare_os_security_overlay import (
    SPEC_PATH,
    SecurityOverlayViolation,
    apply_workspace_overlay,
    evaluate_source_bytes,
    load_spec,
    validate_spec,
    verify_observed_generated_lock,
)


OLD_INTEGRITY = (
    "sha512-bzlKTyNJ7+LdGIIwy8ijFpIqEQIvafahV7eYykJ8Cvh42EdJeODoJ6gUJXpQJvej1BddH8OqTXZNE/"
    "KfbWAu8Q=="
)
NEW_INTEGRITY = (
    "sha512-DTg4MJbGMWkfi6VZFdNt2/caMbQy4Ou+Op/hJQvGEWcnVfoA1QA+xzRKAzw9jD6+GVOOeYr/mIcuDSdug6F6+w=="
)
BROWSER_INTEGRITY = (
    "sha512-HGM8iAmGTf+Y7t0373szVbTmt3d7vPkYL/1bpOkOFO0YUYLgSeuYBCzESklogNPvOBnZ/MRD5f07OkpqH1trtA=="
)
ARCHIVE_INTEGRITY = (
    "sha512-t9VmxaqrmANnEOBhpSDI6HD192Ge48k8vmWqQQL7hSFEqHEYwZbbsu49+aKLWZeRvFs3j1pMhXOqqF4kPlvjkQ=="
)
WORKSPACE_FIXTURE = b"""packages:
  - packages/*

overrides:
  workerd: ">=1.20260623.1"

minimumReleaseAge: 1440
"""
LOCK_FIXTURE = f"""lockfileVersion: '9.0'

settings:
  autoInstallPeers: true
  excludeLinksFromLockfile: false

overrides:
  workerd: '>=1.20260623.1'

packages:

  '@puppeteer/browsers@2.2.4':
    resolution: {{integrity: sha512-source-browser}}

  extract-zip@2.0.1:
    resolution: {{integrity: sha512-source-archive}}

  nanoid@3.3.16:
    resolution: {{integrity: {OLD_INTEGRITY}}}

snapshots:

  '@cloudflare/puppeteer@1.2.0':
    dependencies:
      '@puppeteer/browsers': 2.2.4

  '@puppeteer/browsers@2.2.4':
    dependencies:
      extract-zip: 2.0.1

  extract-zip@2.0.1: {{}}

  nanoid@3.3.16: {{}}

  postcss@8.5.25:
    dependencies:
      nanoid: 3.3.16
""".encode("utf-8")

GENERATED_LOCK_FIXTURE = f"""lockfileVersion: '9.0'

settings:
  autoInstallPeers: true
  excludeLinksFromLockfile: false

overrides:
  'postcss@8.5.25>nanoid': 3.3.18
  '@cloudflare/puppeteer@1.2.0>@puppeteer/browsers': 3.0.4
  workerd: '>=1.20260623.1'

packages:

  '@puppeteer/browsers@3.0.4':
    resolution: {{integrity: {BROWSER_INTEGRITY}}}

  modern-tar@0.7.7:
    resolution: {{integrity: {ARCHIVE_INTEGRITY}}}

  nanoid@3.3.18:
    resolution: {{integrity: {NEW_INTEGRITY}}}

snapshots:

  '@cloudflare/puppeteer@1.2.0':
    dependencies:
      '@puppeteer/browsers': 3.0.4

  '@puppeteer/browsers@3.0.4':
    dependencies:
      modern-tar: 0.7.7

  modern-tar@0.7.7: {{}}

  nanoid@3.3.18: {{}}

  postcss@8.5.25:
    dependencies:
      nanoid: 3.3.18

  postcss@8.5.25(peer):
    dependencies:
      nanoid: 3.3.18
""".encode("utf-8")


def fixture_spec() -> dict:
    spec = copy.deepcopy(load_spec())
    workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
    spec["source"]["workspace"]["canonical_sha256"] = hashlib.sha256(WORKSPACE_FIXTURE).hexdigest()
    spec["source"]["workspace"]["canonical_bytes"] = len(WORKSPACE_FIXTURE)
    spec["source"]["lock"]["canonical_sha256"] = hashlib.sha256(LOCK_FIXTURE).hexdigest()
    spec["source"]["lock"]["canonical_bytes"] = len(LOCK_FIXTURE)
    spec["remediation"]["expected_workspace_output"]["canonical_sha256"] = hashlib.sha256(
        workspace_out
    ).hexdigest()
    spec["remediation"]["expected_workspace_output"]["canonical_bytes"] = len(workspace_out)
    generated = spec["remediation"]["observed_generated_lock"]
    generated["canonical_sha256"] = hashlib.sha256(GENERATED_LOCK_FIXTURE).hexdigest()
    generated["canonical_bytes"] = len(GENERATED_LOCK_FIXTURE)
    generated["canonical_lines"] = GENERATED_LOCK_FIXTURE.count(b"\n")
    return spec


class CloudflareOsSecurityOverlayTests(unittest.TestCase):
    def test_validator_accepts_exact_limit_materialization_bytes_without_read_bytes(self) -> None:
        spec = fixture_spec()
        workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        with tempfile.TemporaryDirectory() as directory:
            workspace_path = pathlib.Path(directory) / "workspace.yaml"
            lock_path = pathlib.Path(directory) / "lock.yaml"
            workspace_path.write_bytes(workspace_out)
            lock_path.write_bytes(GENERATED_LOCK_FIXTURE)
            output = io.StringIO()
            with mock.patch.object(candidate_validator, "load_spec", return_value=spec):
                with mock.patch.object(candidate_validator, "validate_spec"):
                    with mock.patch.object(pathlib.Path, "read_bytes", side_effect=AssertionError("read_bytes is forbidden")):
                        with redirect_stdout(output):
                            status = candidate_validator.main(
                                [
                                    "--generated-workspace",
                                    str(workspace_path),
                                    "--generated-lock",
                                    str(lock_path),
                                ]
                            )
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "PASS")

    def test_validator_rejects_short_and_oversize_materialization_without_private_echo(self) -> None:
        spec = fixture_spec()
        workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        private_marker = "PRIVATE_MATERIALIZATION_SENTINEL"
        cases = (
            ("short-workspace", workspace_out[:-1], GENERATED_LOCK_FIXTURE),
            ("oversize-workspace", workspace_out + b"x", GENERATED_LOCK_FIXTURE),
            ("short-lock", workspace_out, GENERATED_LOCK_FIXTURE[:-1]),
            ("oversize-lock", workspace_out, GENERATED_LOCK_FIXTURE + b"x"),
        )
        with tempfile.TemporaryDirectory(prefix=private_marker) as directory:
            for label, workspace_bytes, lock_bytes in cases:
                with self.subTest(label=label):
                    workspace_path = pathlib.Path(directory) / f"{private_marker}-{label}-workspace"
                    lock_path = pathlib.Path(directory) / f"{private_marker}-{label}-lock"
                    workspace_path.write_bytes(workspace_bytes)
                    lock_path.write_bytes(lock_bytes)
                    output = io.StringIO()
                    with mock.patch.object(candidate_validator, "load_spec", return_value=spec):
                        with mock.patch.object(candidate_validator, "validate_spec"):
                            with redirect_stdout(output):
                                status = candidate_validator.main(
                                    [
                                        "--generated-workspace",
                                        str(workspace_path),
                                        "--generated-lock",
                                        str(lock_path),
                                    ]
                                )
                    rendered = output.getvalue()
                    self.assertEqual(status, 1)
                    self.assertEqual(json.loads(rendered)["status"], "FAIL")
                    self.assertNotIn(private_marker, rendered)
                    self.assertNotIn(str(workspace_path), rendered)
                    self.assertNotIn(str(lock_path), rendered)
                    self.assertNotIn("Traceback", rendered)

            sparse_workspace = pathlib.Path(directory) / f"{private_marker}-sparse-workspace"
            sparse_lock = pathlib.Path(directory) / f"{private_marker}-sparse-lock"
            with sparse_workspace.open("wb") as stream:
                stream.truncate(len(workspace_out) + 1)
            sparse_lock.write_bytes(GENERATED_LOCK_FIXTURE)
            output = io.StringIO()
            with mock.patch.object(candidate_validator, "load_spec", return_value=spec):
                with mock.patch.object(candidate_validator, "validate_spec"):
                    with redirect_stdout(output):
                        status = candidate_validator.main(
                            [
                                "--generated-workspace",
                                str(sparse_workspace),
                                "--generated-lock",
                                str(sparse_lock),
                            ]
                        )
            rendered = output.getvalue()
            self.assertEqual(status, 1)
            self.assertEqual(json.loads(rendered)["status"], "FAIL")
            self.assertNotIn(private_marker, rendered)
            self.assertNotIn("Traceback", rendered)

    def test_validator_reads_materialization_in_bounded_chunks(self) -> None:
        spec = fixture_spec()
        workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        read_sizes: list[int] = []
        real_open = pathlib.Path.open

        class TrackingStream:
            def __init__(self, stream) -> None:
                self._stream = stream

            def __enter__(self):
                self._stream.__enter__()
                return self

            def __exit__(self, *args):
                return self._stream.__exit__(*args)

            def read(self, size: int = -1):
                read_sizes.append(size)
                return self._stream.read(size)

        def open_tracking(path, mode="r", buffering=-1, encoding=None, errors=None, newline=None):
            return TrackingStream(real_open(path, mode, buffering, encoding, errors, newline))

        with tempfile.TemporaryDirectory() as directory:
            workspace_path = pathlib.Path(directory) / "workspace.yaml"
            lock_path = pathlib.Path(directory) / "lock.yaml"
            workspace_path.write_bytes(workspace_out)
            lock_path.write_bytes(GENERATED_LOCK_FIXTURE)
            output = io.StringIO()
            with mock.patch.object(candidate_validator, "load_spec", return_value=spec):
                with mock.patch.object(candidate_validator, "validate_spec"):
                    with mock.patch.object(pathlib.Path, "open", autospec=True, side_effect=open_tracking):
                        with redirect_stdout(output):
                            status = candidate_validator.main(
                                [
                                    "--generated-workspace",
                                    str(workspace_path),
                                    "--generated-lock",
                                    str(lock_path),
                                ]
                            )
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "PASS")
        self.assertTrue(read_sizes)
        self.assertNotIn(-1, read_sizes)
        self.assertTrue(all(size > 0 for size in read_sizes))

    def test_cli_rejects_sparse_input_without_private_echo_or_traceback(self) -> None:
        spec = load_spec()
        workspace_size = spec["remediation"]["expected_workspace_output"]["canonical_bytes"]
        lock_size = spec["remediation"]["observed_generated_lock"]["canonical_bytes"]
        private_marker = "PRIVATE_SPARSE_INPUT_SENTINEL"
        with tempfile.TemporaryDirectory(prefix=private_marker) as directory:
            workspace_path = pathlib.Path(directory) / f"{private_marker}-workspace"
            lock_path = pathlib.Path(directory) / f"{private_marker}-lock"
            with workspace_path.open("wb") as stream:
                stream.truncate(workspace_size + 1)
            with lock_path.open("wb") as stream:
                stream.truncate(lock_size)
            result = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(VALIDATOR_PATH),
                    "--generated-workspace",
                    str(workspace_path),
                    "--generated-lock",
                    str(lock_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["status"], "FAIL")
        self.assertEqual(result.stderr, "")
        self.assertNotIn(private_marker, result.stdout + result.stderr)
        self.assertNotIn(str(workspace_path), result.stdout + result.stderr)
        self.assertNotIn(str(lock_path), result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_current_spec_is_fail_closed_and_not_remediation_proof(self) -> None:
        spec = load_spec()
        validate_spec(spec)
        self.assertEqual(spec["kind"], "kotodama/cloudflare-os-security-overlay/v1")
        self.assertEqual(spec["status"], "LOCAL_MATERIALIZATION_VERIFIED_NOT_DEPLOYED")
        self.assertTrue(spec["gates"]["materialized"])
        self.assertTrue(spec["gates"]["production_audit_zero_high"])
        self.assertFalse(spec["gates"]["independent_review"])
        self.assertEqual(spec["graph"]["advisory"]["vulnerable_range"], "<3.3.18")
        self.assertEqual(spec["remediation"]["target_version"], "3.3.18")
        companion = spec["remediation"]["companion"]
        self.assertEqual(companion["advisory"]["patched_direct_versions"], [])
        self.assertEqual(companion["target_version"], "3.0.4")
        self.assertEqual(spec["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertTrue(SPEC_PATH.is_file())

    def test_exact_parent_scoped_overlay_writes_workspace_only(self) -> None:
        spec = fixture_spec()
        workspace_out, report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        self.assertEqual(report["before"]["vulnerable_lock_markers"], 4)
        self.assertEqual(report["after"]["workspace_override"], 1)
        self.assertEqual(report["after"]["companion_workspace_override"], 1)
        self.assertEqual(report["after"]["lock_writes"], 0)
        self.assertEqual(report["after"]["source_lock_sha256"], hashlib.sha256(LOCK_FIXTURE).hexdigest())
        self.assertIn(b"postcss@8.5.25>nanoid", workspace_out)

    def test_workspace_overlay_preserves_all_unrelated_workspace_bytes(self) -> None:
        spec = fixture_spec()
        workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        self.assertIn(b"minimumReleaseAge: 1440", workspace_out)
        self.assertEqual(workspace_out.count(b"postcss@8.5.25>nanoid"), 1)

    def test_observed_pnpm_lock_binding_has_five_target_markers(self) -> None:
        spec = fixture_spec()
        workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        report = verify_observed_generated_lock(workspace_out, GENERATED_LOCK_FIXTURE, spec)
        self.assertEqual(report["status"], "PASS_BOUND_GENERATED_LOCK_BYTES_NO_PROVENANCE")
        self.assertEqual(report["vulnerable_lock_markers"], 0)
        self.assertEqual(report["target_lock_markers"], 5)
        self.assertTrue(report["package_manager_provenance_recorded"])
        self.assertFalse(report["package_manager_provenance_verified_by_bytes"])

    def test_companion_remediation_removes_extract_zip_without_inventing_2_0_2(self) -> None:
        spec = fixture_spec()
        workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        report = verify_observed_generated_lock(workspace_out, GENERATED_LOCK_FIXTURE, spec)
        self.assertNotIn(b"extract-zip@2.0.1", GENERATED_LOCK_FIXTURE)
        self.assertNotIn(b"extract-zip@2.0.2", GENERATED_LOCK_FIXTURE)
        self.assertIn(b"@puppeteer/browsers@3.0.4", GENERATED_LOCK_FIXTURE)
        self.assertEqual(report["status"], "PASS_BOUND_GENERATED_LOCK_BYTES_NO_PROVENANCE")

    def test_rejects_companion_selector_drift(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["remediation"]["companion"]["selector"] = "@puppeteer/browsers"
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_manual_four_marker_lock_prediction(self) -> None:
        spec = fixture_spec()
        workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        manual = LOCK_FIXTURE.replace(b"overrides:\n", b"overrides:\n  'postcss@8.5.25>nanoid': 3.3.18\n", 1)
        manual = manual.replace(b"nanoid@3.3.16", b"nanoid@3.3.18")
        manual = manual.replace(b"nanoid: 3.3.16", b"nanoid: 3.3.18")
        manual = manual.replace(OLD_INTEGRITY.encode("ascii"), NEW_INTEGRITY.encode("ascii"))
        with self.assertRaises(SecurityOverlayViolation):
            verify_observed_generated_lock(workspace_out, manual, spec)

    def test_rejects_crlf_input_instead_of_normalizing_ambient_bytes(self) -> None:
        spec = fixture_spec()
        with self.assertRaises(SecurityOverlayViolation):
            apply_workspace_overlay(WORKSPACE_FIXTURE.replace(b"\n", b"\r\n"), LOCK_FIXTURE, spec)

    def test_rejects_double_application(self) -> None:
        spec = fixture_spec()
        workspace_out, _report = apply_workspace_overlay(WORKSPACE_FIXTURE, LOCK_FIXTURE, spec)
        with self.assertRaises(SecurityOverlayViolation):
            apply_workspace_overlay(workspace_out, LOCK_FIXTURE, spec)

    def test_rejects_vulnerable_marker_count_drift(self) -> None:
        spec = fixture_spec()
        drifted = LOCK_FIXTURE.replace(b"nanoid@3.3.16: {}", b"nanoid@3.3.15: {}")
        with self.assertRaises(SecurityOverlayViolation):
            apply_workspace_overlay(WORKSPACE_FIXTURE, drifted, spec)

    def test_rejects_old_integrity_drift(self) -> None:
        spec = fixture_spec()
        drifted = LOCK_FIXTURE.replace(OLD_INTEGRITY.encode("ascii"), b"sha512-drift")
        with self.assertRaises(SecurityOverlayViolation):
            apply_workspace_overlay(WORKSPACE_FIXTURE, drifted, spec)

    def test_rejects_global_override_selector(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["remediation"]["selector"] = "nanoid"
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_unpatched_target(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["remediation"]["target_version"] = "3.3.16"
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_ambient_latest(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["remediation"]["ambient_latest_allowed"] = True
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_manual_lock_as_accepted_production_control(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["remediation"]["manual_lock_edit_accepted"] = True
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_input_hash_drift(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["source"]["lock"]["canonical_sha256"] = "0" * 64
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_valid_looking_source_hash_rebinding(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["source"]["workspace"]["canonical_sha256"] = "1" * 64
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_bound_blob_oid_drift(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["source"]["workspace"]["blob_oid"] = "0" * 40
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_integrity_reference_revision_drift(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["source"]["target_integrity_reference"]["commit"] = "0" * 40
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_dependency_graph_digest_rebinding(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["graph"]["package_path_multiset_sha256"] = "0" * 64
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_integrity_value_rebinding(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["remediation"]["new_integrity"] = "sha512-" + ("A" * 100)
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_unknown_nested_field(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["source"]["workspace"]["future_binding"] = "unreviewed"
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_unproven_boundary_rebinding(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["unproven"][0] = "everything is proven"
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_output_hash_drift(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["remediation"]["observed_generated_lock"]["canonical_sha256"] = "0" * 64
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_rejects_valid_looking_output_hash_rebinding(self) -> None:
        spec = copy.deepcopy(load_spec())
        spec["remediation"]["expected_workspace_output"]["canonical_sha256"] = "1" * 64
        with self.assertRaises(SecurityOverlayViolation):
            validate_spec(spec)

    def test_evaluator_rejects_unbound_synthetic_fixture(self) -> None:
        with self.assertRaises(SecurityOverlayViolation):
            evaluate_source_bytes(WORKSPACE_FIXTURE, LOCK_FIXTURE, fixture_spec())

    def test_rejects_effect_or_public_go_overclaim(self) -> None:
        for mutate in (
            lambda value: value["effects"].__setitem__("dependency_update", 1),
            lambda value: value["effects"].__setitem__("install", 0),
            lambda value: value.__setitem__("public_beta", "GO"),
        ):
            spec = copy.deepcopy(load_spec())
            mutate(spec)
            with self.assertRaises(SecurityOverlayViolation):
                validate_spec(spec)


if __name__ == "__main__":
    unittest.main()
