import importlib.util
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "tools" / "resolve_compose_candidate.py"
PREFLIGHT = ROOT / "tools" / "preflight_compose_image_availability.py"
VERIFY = ROOT / "tools" / "verify_compose_clean_install_migration_evidence_candidate.py"
FIXTURE = ROOT / "tests" / "fixtures" / "fake_docker_cli.py"
SCHEMA = ROOT / "schemas" / "compose-clean-install-migration-evidence-candidate.schema.json"
MANIFEST_DIGEST = "sha256:" + "0" * 64


def load_verifier():
    spec = importlib.util.spec_from_file_location("compose_evidence_verifier_tests", VERIFY)
    module = importlib.util.module_from_spec(spec)
    original_path = sys.path[:]
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
    return module


VERIFIER = load_verifier()


def canonical_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class ComposeCleanInstallMigrationEvidenceCandidateVerifierCliTests(unittest.TestCase):
    def run_main(self, paths: tuple[Path, Path, Path]) -> subprocess.CompletedProcess:
        arguments = [str(VERIFY), *(str(path) for path in paths)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            returncode = VERIFIER.main(arguments)
        return subprocess.CompletedProcess(arguments, returncode, stdout.getvalue(), stderr.getvalue())

    def assert_input_refusal(self, result: subprocess.CompletedProcess) -> None:
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INVALID")
        self.assertEqual(report["errors"], ["input JSON is invalid"])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")
        self.assertTrue(all(value is False for value in report["claims"].values()))
        self.assertNotIn("private-input-marker", result.stdout)

    def write_sized_inputs(
        self, temporary: Path, candidate: dict, preflight: dict,
        sizes: tuple[int | None, int | None, int | None],
    ) -> tuple[Path, Path, Path]:
        def write(path: Path, value: dict, size: int | None) -> None:
            raw = json.dumps(value).encode("utf-8")
            if size is not None:
                self.assertLessEqual(len(raw), size)
                raw += b" " * (size - len(raw))
            path.write_bytes(raw)

        evidence_path = temporary / "private-input-marker-evidence.json"
        candidate_path = temporary / "private-input-marker-candidate.json"
        preflight_path = temporary / "private-input-marker-preflight.json"
        write(candidate_path, candidate, sizes[1])
        preflight = json.loads(json.dumps(preflight))
        preflight["candidate_binding"]["candidate_file_sha256"] = hashlib.sha256(
            candidate_path.read_bytes()
        ).hexdigest()
        preflight["preflight_sha256"] = canonical_sha256(
            {key: value for key, value in preflight.items() if key != "preflight_sha256"}
        )
        write(preflight_path, preflight, sizes[2])
        evidence = self.make_evidence(candidate_path, preflight_path, candidate, preflight)
        write(evidence_path, evidence, sizes[0])
        return evidence_path, candidate_path, preflight_path

    def fake_environment(self, temporary: Path) -> dict[str, str]:
        environment = os.environ.copy()
        if os.name == "nt":
            wrapper = temporary / "docker.cmd"
            wrapper.write_text(
                f'@echo off\r\n"{sys.executable}" "{FIXTURE}" %*\r\n',
                encoding="utf-8",
            )
        else:
            wrapper = temporary / "docker"
            wrapper.write_text(
                f'#!/bin/sh\nexec "{sys.executable}" "{FIXTURE}" "$@"\n',
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
        environment["PATH"] = str(temporary) + os.pathsep + environment.get("PATH", "")
        environment["KOTODAMA_POSTGRES_IMAGE"] = "postgres@" + MANIFEST_DIGEST
        environment["KOTODAMA_COMPANY_DB_PASSWORD"] = "synthetic-r16-company"
        environment["KOTODAMA_EVIDENCE_DB_PASSWORD"] = "synthetic-r16-evidence"
        environment["KOTODAMA_FAKE_DOCKER_MODE"] = "success"
        environment["KOTODAMA_FAKE_DOCKER_LOG"] = str(temporary / "docker-commands.jsonl")
        return environment

    def make_inputs(self, temporary: Path) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
        environment = self.fake_environment(temporary)
        candidate_path = temporary / "resolved-candidate.json"
        resolved = subprocess.run(
            [sys.executable, str(RESOLVER), "kotodama-r16", "--output", str(candidate_path)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
        preflight_path = temporary / "image-preflight.json"
        preflight = subprocess.run(
            [sys.executable, str(PREFLIGHT), str(candidate_path), "--output", str(preflight_path)],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
        return (
            candidate_path,
            preflight_path,
            json.loads(candidate_path.read_text(encoding="utf-8")),
            json.loads(preflight_path.read_text(encoding="utf-8")),
        )

    def make_evidence(
        self,
        candidate_path: Path,
        preflight_path: Path,
        candidate: dict[str, object],
        preflight: dict[str, object],
    ) -> dict[str, object]:
        services = candidate["resolved"]["services"]
        service_reports = []
        for index, service in enumerate(services):
            service_reports.append(
                {
                    "service_id": service["id"],
                    "migration_path": service["migration"],
                    "migration_sha256": service["migration_sha256"],
                    "evidence_sha256": format(index + 10, "064x"),
                    "positive_checks": {
                        "migration_digest_match_reported": True,
                        "required_tables_present_reported": True,
                        "expected_roles_present_reported": True,
                        "health_query_passed_reported": True,
                        "transaction_write_read_rollback_reported": True,
                    },
                    "negative_checks": {
                        "wrong_role_ddl_denied_reported": True,
                        "wrong_role_write_denied_reported": True,
                        "cross_store_access_denied_reported": True,
                        "public_network_access_denied_reported": True,
                        "dirty_schema_rejected_reported": True,
                    },
                }
            )
        evidence = {
            "kind": "compose_clean_install_migration_evidence_candidate",
            "version": "1.0",
            "status": "UNATTESTED_EVIDENCE_CANDIDATE",
            "reported_at": "2026-08-03T05:00:00+09:00",
            "candidate_binding": {
                "candidate_file_sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
                "project_name": candidate["project_name"],
                "resolved_contract_sha256": candidate["resolved"]["resolved_contract_sha256"],
                "image_manifest_digest": candidate["resolved"]["services"][0]["image_digest"],
            },
            "preflight_binding": {
                "preflight_file_sha256": hashlib.sha256(preflight_path.read_bytes()).hexdigest(),
                "preflight_sha256": preflight["preflight_sha256"],
                "daemon_id_sha256": preflight["host_binding"]["daemon_id_sha256"],
                "local_image_id_digest": preflight["image_observation"]["local_image_id_digest"],
                "status": "LOCAL_IMAGE_AVAILABLE",
            },
            "authorization_binding": {
                "work_order_sha256": "a" * 64,
                "target_locator_sha256": "b" * 64,
                "before_state_receipt_sha256": "c" * 64,
                "executor_identity_sha256": "d" * 64,
                "reviewer_identity_sha256": "e" * 64,
                "identities_distinct": True,
                "protected_attestation_verified": False,
            },
            "reported_effects": {
                "container_create_reported": True,
                "container_start_reported": True,
                "migration_execution_reported": True,
                "database_smoke_write_reported": True,
                "image_pull_reported": False,
                "image_mutation_reported": False,
                "daemon_configuration_change_reported": False,
                "credential_values_emitted": False,
                "raw_command_output_emitted": False,
                "raw_host_identity_emitted": False,
                "irreversible_delete_reported": False,
                "provider_transfer_reported": False,
            },
            "service_reports": service_reports,
            "claims": {
                claim: False
                for claim in (
                    "execution_authenticity_verified",
                    "observation_freshness_verified",
                    "observation_atomicity_verified",
                    "current_daemon_reachable_verified",
                    "current_local_image_available_verified",
                    "clean_install_verified",
                    "services_started_verified",
                    "migrations_verified",
                    "database_positive_checks_verified",
                    "database_negative_checks_verified",
                    "application_least_privilege_verified",
                    "restart_verified",
                    "rollback_verified",
                    "backup_verified",
                    "restore_verified",
                    "promotion_verified",
                    "current_truth_changed",
                    "final_human_go",
                    "public_beta_go",
                )
            },
            "evidence_candidate_sha256": "",
            "public_beta": "NO_GO_UNPUBLISHED",
        }
        evidence["evidence_candidate_sha256"] = canonical_sha256(
            {key: value for key, value in evidence.items() if key != "evidence_candidate_sha256"}
        )
        return evidence

    def test_valid_saved_candidate_reports_only_unattested_historical_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            candidate_path, preflight_path, candidate, preflight = self.make_inputs(temporary)
            evidence = self.make_evidence(candidate_path, preflight_path, candidate, preflight)
            evidence_path = temporary / "evidence-candidate.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(VERIFY),
                    str(evidence_path),
                    str(candidate_path),
                    str(preflight_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "compose_clean_install_migration_evidence_validation")
        self.assertEqual(report["version"], "1.0")
        self.assertEqual(report["status"], "UNATTESTED_EVIDENCE_BINDING_ONLY")
        self.assertEqual(report["errors"], [])
        for claim in (
            "evidence_candidate_self_digest_verified",
            "candidate_binding_verified",
            "preflight_binding_verified",
            "reported_check_completeness_verified",
            "role_separation_structure_verified",
        ):
            self.assertTrue(report["claims"][claim])
        for claim in (
            "execution_authenticity_verified",
            "observation_freshness_verified",
            "observation_atomicity_verified",
            "current_daemon_reachable_verified",
            "current_local_image_available_verified",
            "clean_install_verified",
            "migrations_verified",
            "public_beta_go",
        ):
            self.assertFalse(report["claims"][claim])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_two_services_cannot_reuse_one_reported_evidence_digest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            candidate_path, preflight_path, candidate, preflight = self.make_inputs(temporary)
            evidence = self.make_evidence(candidate_path, preflight_path, candidate, preflight)
            evidence["service_reports"][1]["evidence_sha256"] = evidence["service_reports"][0][
                "evidence_sha256"
            ]
            evidence["evidence_candidate_sha256"] = canonical_sha256(
                {key: value for key, value in evidence.items() if key != "evidence_candidate_sha256"}
            )
            evidence_path = temporary / "reused-evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFY), str(evidence_path), str(candidate_path), str(preflight_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertIn("service evidence digests must be distinct", report["errors"])
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_schema_is_closed_and_denies_attestation_live_state_and_go(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["status"]["const"], "UNATTESTED_EVIDENCE_CANDIDATE")
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertFalse(schema["properties"]["authorization_binding"]["additionalProperties"])
        self.assertFalse(
            schema["properties"]["authorization_binding"]["properties"]
            ["protected_attestation_verified"]["const"]
        )
        self.assertEqual(schema["properties"]["service_reports"]["minItems"], 2)
        self.assertEqual(schema["properties"]["service_reports"]["maxItems"], 2)
        self.assertFalse(schema["properties"]["claims"]["additionalProperties"])
        for definition in schema["properties"]["claims"]["properties"].values():
            self.assertIs(definition["const"], False)

    def test_executor_and_reviewer_must_be_distinct_hash_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            candidate_path, preflight_path, candidate, preflight = self.make_inputs(temporary)
            evidence = self.make_evidence(candidate_path, preflight_path, candidate, preflight)
            evidence["authorization_binding"]["reviewer_identity_sha256"] = evidence[
                "authorization_binding"
            ]["executor_identity_sha256"]
            evidence["evidence_candidate_sha256"] = canonical_sha256(
                {key: value for key, value in evidence.items() if key != "evidence_candidate_sha256"}
            )
            evidence_path = temporary / "same-role.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFY), str(evidence_path), str(candidate_path), str(preflight_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "executor and reviewer identity bindings must be distinct",
            json.loads(result.stdout)["errors"],
        )

    def test_candidate_preflight_and_migration_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            candidate_path, preflight_path, candidate, preflight = self.make_inputs(temporary)
            base = self.make_evidence(candidate_path, preflight_path, candidate, preflight)
            cases = []
            candidate_drift = json.loads(json.dumps(base))
            candidate_drift["candidate_binding"]["project_name"] = "kotodama-other"
            cases.append((candidate_drift, "candidate binding mismatch"))
            preflight_drift = json.loads(json.dumps(base))
            preflight_drift["preflight_binding"]["daemon_id_sha256"] = "9" * 64
            cases.append((preflight_drift, "preflight binding mismatch"))
            migration_drift = json.loads(json.dumps(base))
            migration_drift["service_reports"][0]["migration_sha256"] = "8" * 64
            cases.append(
                (
                    migration_drift,
                    "service_reports[0].migration_sha256 is not candidate bound",
                )
            )
            results = []
            for index, (evidence, expected_error) in enumerate(cases):
                evidence["evidence_candidate_sha256"] = canonical_sha256(
                    {
                        key: value
                        for key, value in evidence.items()
                        if key != "evidence_candidate_sha256"
                    }
                )
                evidence_path = temporary / f"drift-{index}.json"
                evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(VERIFY),
                        str(evidence_path),
                        str(candidate_path),
                        str(preflight_path),
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                results.append((result, expected_error))

        for result, expected_error in results:
            self.assertEqual(result.returncode, 1)
            report = json.loads(result.stdout)
            self.assertIn(expected_error, report["errors"])
            self.assertTrue(all(not value for value in report["claims"].values()))

    def test_reported_checks_effects_and_live_claims_are_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            candidate_path, preflight_path, candidate, preflight = self.make_inputs(temporary)
            evidence = self.make_evidence(candidate_path, preflight_path, candidate, preflight)
            evidence["service_reports"][0]["negative_checks"][
                "cross_store_access_denied_reported"
            ] = False
            evidence["reported_effects"]["image_pull_reported"] = True
            evidence["claims"]["clean_install_verified"] = True
            evidence["evidence_candidate_sha256"] = canonical_sha256(
                {key: value for key, value in evidence.items() if key != "evidence_candidate_sha256"}
            )
            evidence_path = temporary / "overclaim.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFY), str(evidence_path), str(candidate_path), str(preflight_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("service_reports[0] negative checks must all be reported true", errors)
        self.assertIn("reported effects do not match the bounded evidence-candidate contract", errors)
        self.assertIn("claim clean_install_verified must remain false", errors)

    def test_duplicate_unknown_and_self_digest_tamper_are_safe_refusals(self) -> None:
        private_marker = "private-secret-value-must-not-leak"
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            candidate_path, preflight_path, candidate, preflight = self.make_inputs(temporary)
            base = self.make_evidence(candidate_path, preflight_path, candidate, preflight)
            unknown = json.loads(json.dumps(base))
            unknown[private_marker] = private_marker
            unknown["evidence_candidate_sha256"] = canonical_sha256(
                {key: value for key, value in unknown.items() if key != "evidence_candidate_sha256"}
            )
            unknown_path = temporary / "unknown.json"
            unknown_path.write_text(json.dumps(unknown), encoding="utf-8")
            duplicate_path = temporary / "duplicate.json"
            duplicate_path.write_text(
                '{"kind":"shadow",' + json.dumps(base).lstrip()[1:], encoding="utf-8"
            )
            tamper = json.loads(json.dumps(base))
            tamper["reported_at"] = "2001-01-01T00:00:00Z"
            tamper_path = temporary / "tamper.json"
            tamper_path.write_text(json.dumps(tamper), encoding="utf-8")
            results = [
                subprocess.run(
                    [sys.executable, str(VERIFY), str(path), str(candidate_path), str(preflight_path)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                for path in (unknown_path, duplicate_path, tamper_path)
            ]

        for result in results:
            self.assertEqual(result.returncode, 1)
            self.assertNotIn(private_marker, result.stdout)
            self.assertTrue(all(not value for value in json.loads(result.stdout)["claims"].values()))

    def test_ancient_self_consistent_candidate_is_historical_not_fresh(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            candidate_path, preflight_path, candidate, preflight = self.make_inputs(temporary)
            evidence = self.make_evidence(candidate_path, preflight_path, candidate, preflight)
            evidence["reported_at"] = "2001-01-01T00:00:00Z"
            evidence["evidence_candidate_sha256"] = canonical_sha256(
                {key: value for key, value in evidence.items() if key != "evidence_candidate_sha256"}
            )
            evidence_path = temporary / "ancient.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFY), str(evidence_path), str(candidate_path), str(preflight_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "UNATTESTED_EVIDENCE_BINDING_ONLY")
        self.assertFalse(report["claims"]["observation_freshness_verified"])

    def test_usage_error_returns_two_without_json(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VERIFY)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)

    def test_each_input_accepts_exact_byte_limit_and_refuses_limit_plus_one(self) -> None:
        self.assertEqual(VERIFIER.MAX_INPUT_BYTES, 1_048_576)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            _, _, candidate, preflight = self.make_inputs(temporary)
            for index in range(3):
                with self.subTest(input_index=index):
                    sizes = [None, None, None]
                    sizes[index] = 1_048_576
                    paths = self.write_sized_inputs(temporary, candidate, preflight, tuple(sizes))
                    positive = self.run_main(paths)
                    self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
                    self.assertEqual(positive.stderr, "")
                    report = json.loads(positive.stdout)
                    self.assertEqual(report["status"], "UNATTESTED_EVIDENCE_BINDING_ONLY")
                    self.assertFalse(report["claims"]["execution_authenticity_verified"])
                    self.assertFalse(report["claims"]["observation_freshness_verified"])
                    sizes[index] += 1
                    paths = self.write_sized_inputs(temporary, candidate, preflight, tuple(sizes))
                    self.assert_input_refusal(self.run_main(paths))
            result = subprocess.run(
                [sys.executable, str(VERIFY), *(str(path) for path in paths)],
                cwd=ROOT, text=True, capture_output=True, check=False, timeout=10,
            )
            self.assert_input_refusal(result)

    def test_aggregate_limit_is_independent_of_per_file_limit(self) -> None:
        self.assertEqual(VERIFIER.MAX_TOTAL_INPUT_BYTES, 2_097_152)
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            _, _, candidate, preflight = self.make_inputs(temporary)
            # All three files remain below 1 MiB. Every binding is recomputed so
            # the total-byte guard is the only reason the second case refuses.
            paths = self.write_sized_inputs(
                temporary, candidate, preflight, (700_000, 700_000, 697_152)
            )
            positive = self.run_main(paths)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            self.assertEqual(positive.stderr, "")
            paths = self.write_sized_inputs(
                temporary, candidate, preflight, (700_000, 700_000, 697_153)
            )
            self.assert_input_refusal(self.run_main(paths))

    def test_nonregular_link_and_reparse_inputs_are_refused_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            regular = temporary / "private-input-marker.json"
            regular.write_bytes(b"{}")
            targets = [temporary]
            if hasattr(os, "mkfifo"):
                fifo = temporary / "private-input-marker.fifo"
                os.mkfifo(fifo)
                targets.append(fifo)
            for target in targets:
                with self.subTest(target_type="directory" if target == temporary else "fifo"):
                    with mock.patch.object(VERIFIER.os, "open") as opened:
                        self.assert_input_refusal(self.run_main((target, regular, regular)))
                        opened.assert_not_called()
            original_lstat = Path.lstat
            metadata = regular.lstat()
            for changes in (
                {"st_mode": stat.S_IFLNK | 0o777},
                {"st_file_attributes": 0x400},
                {"st_reparse_tag": 1},
                {"st_nlink": 2},
            ):
                with self.subTest(metadata=tuple(changes)):
                    replacement = SimpleNamespace(
                        st_mode=metadata.st_mode, st_nlink=metadata.st_nlink,
                        st_file_attributes=0, st_reparse_tag=0,
                    )
                    replacement.__dict__.update(changes)
                    def lstat(path, **kwargs):
                        return replacement if path == regular else original_lstat(path, **kwargs)
                    with mock.patch.object(Path, "lstat", lstat):
                        with mock.patch.object(VERIFIER.os, "open") as opened:
                            self.assert_input_refusal(self.run_main((regular, regular, regular)))
                            opened.assert_not_called()

    def test_opened_identity_drift_is_refused_and_descriptor_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            path, other = temporary / "input.json", temporary / "other.json"
            path.write_bytes(b"small")
            other.write_bytes(b"small")
            original_open, original_read = os.open, os.read
            for substitution in (True, False):
                with self.subTest(substituted_object=substitution):
                    path.write_bytes(b"small")
                    descriptors = []
                    def substituted_open(_path, flags):
                        if not substitution:
                            path.write_bytes(b"small!")
                        descriptor = original_open(other if substitution else path, flags)
                        descriptors.append(descriptor)
                        return descriptor
                    with mock.patch.object(VERIFIER.os, "open", substituted_open):
                        with mock.patch.object(VERIFIER.os, "read", wraps=original_read) as read:
                            with self.assertRaises(ValueError):
                                VERIFIER.read_bounded(path, 32)
                            read.assert_not_called()
                    self.assertEqual(len(descriptors), 1)
                    with self.assertRaises(OSError):
                        os.fstat(descriptors[0])

    def test_ctime_is_compared_only_between_same_descriptor_observations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            path.write_bytes(b"small")
            original_fstat = os.fstat
            for late_change in (False, True):
                with self.subTest(descriptor_ctime_changes=late_change):
                    calls = 0
                    def descriptor_metadata(descriptor):
                        nonlocal calls
                        details = original_fstat(descriptor)
                        calls += 1
                        replacement = SimpleNamespace(**{
                            field: getattr(details, field) for field in (
                                "st_dev", "st_ino", "st_mode", "st_nlink",
                                "st_size", "st_mtime_ns", "st_ctime_ns",
                            )
                        })
                        replacement.st_file_attributes = getattr(details, "st_file_attributes", 0)
                        replacement.st_reparse_tag = getattr(details, "st_reparse_tag", 0)
                        replacement.st_ctime_ns += 1_000 + int(late_change and calls == 2)
                        return replacement
                    with mock.patch.object(VERIFIER.os, "fstat", descriptor_metadata):
                        if late_change:
                            with self.assertRaises(ValueError):
                                VERIFIER.read_bounded(path, 32)
                        else:
                            self.assertEqual(VERIFIER.read_bounded(path, 32), b"small")
                    self.assertEqual(calls, 2)

    def test_growth_and_same_size_drift_during_read_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.json"
            original_read = os.read
            for replacement in (b"small!", b"other"):
                with self.subTest(replacement_size=len(replacement)):
                    path.write_bytes(b"small")
                    before = path.stat()
                    changed = False
                    def changing_read(descriptor, count):
                        nonlocal changed
                        chunk = original_read(descriptor, count)
                        if not changed:
                            changed = True
                            path.write_bytes(replacement)
                            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000))
                        return chunk
                    with mock.patch.object(VERIFIER.os, "read", changing_read):
                        with self.assertRaises(ValueError):
                            VERIFIER.read_bounded(path, 32)
                    self.assertTrue(changed)

    def test_terminal_path_replacement_is_refused_after_descriptor_close(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            path, other = temporary / "input.json", temporary / "other.json"
            path.write_bytes(b"small")
            other.write_bytes(b"small")
            original_close = os.close
            def replace_after_close(descriptor):
                original_close(descriptor)
                path.unlink()
                other.replace(path)
            with mock.patch.object(VERIFIER.os, "close", replace_after_close):
                with self.assertRaises(ValueError):
                    VERIFIER.read_bounded(path, 32)
            self.assertEqual(path.read_bytes(), b"small")

    def test_descriptor_closes_on_read_failure_and_short_reads_are_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-input-marker.json"
            path.write_bytes(b"small")
            original_open, original_read = os.open, os.read
            descriptors = []
            def observed_open(selected_path, flags):
                descriptor = original_open(selected_path, flags)
                descriptors.append(descriptor)
                return descriptor
            with mock.patch.object(VERIFIER.os, "open", observed_open):
                with mock.patch.object(VERIFIER.os, "read", side_effect=OSError("private-input-marker")):
                    self.assert_input_refusal(self.run_main((path, path, path)))
            self.assertEqual(len(descriptors), 1)
            with self.assertRaises(OSError):
                os.fstat(descriptors[0])
            with mock.patch.object(VERIFIER.os, "read", lambda fd, count: original_read(fd, min(count, 1))):
                self.assertEqual(VERIFIER.read_bounded(path, 32), b"small")


if __name__ == "__main__":
    unittest.main()
