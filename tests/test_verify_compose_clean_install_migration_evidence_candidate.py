import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "tools" / "resolve_compose_candidate.py"
PREFLIGHT = ROOT / "tools" / "preflight_compose_image_availability.py"
VERIFY = ROOT / "tools" / "verify_compose_clean_install_migration_evidence_candidate.py"
FIXTURE = ROOT / "tests" / "fixtures" / "fake_docker_cli.py"
SCHEMA = ROOT / "schemas" / "compose-clean-install-migration-evidence-candidate.schema.json"
MANIFEST_DIGEST = "sha256:" + "0" * 64


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


if __name__ == "__main__":
    unittest.main()
