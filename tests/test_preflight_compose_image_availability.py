import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "tools" / "resolve_compose_candidate.py"
PREFLIGHT = ROOT / "tools" / "preflight_compose_image_availability.py"
VERIFY = ROOT / "tools" / "verify_compose_image_availability_preflight.py"
FIXTURE = ROOT / "tests" / "fixtures" / "fake_docker_cli.py"
SCHEMA = ROOT / "schemas" / "compose-image-availability-preflight.schema.json"
MANIFEST_DIGEST = "sha256:" + "0" * 64


class ComposeImageAvailabilityPreflightCliTests(unittest.TestCase):
    def fake_environment(self, temporary: Path, mode: str = "success") -> dict[str, str]:
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
        environment["KOTODAMA_COMPANY_DB_PASSWORD"] = "synthetic-r14-company"
        environment["KOTODAMA_EVIDENCE_DB_PASSWORD"] = "synthetic-r14-evidence"
        environment["KOTODAMA_FAKE_DOCKER_MODE"] = mode
        environment["KOTODAMA_FAKE_DOCKER_LOG"] = str(temporary / "docker-commands.jsonl")
        return environment

    def make_candidate(self, temporary: Path, environment: dict[str, str]) -> Path:
        result = subprocess.run(
            [sys.executable, str(RESOLVER), "kotodama-r14"],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        path = temporary / "resolved-candidate.json"
        path.write_text(result.stdout, encoding="utf-8")
        return path

    def test_matching_local_image_emits_a_private_identity_safe_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = self.fake_environment(temporary)
            candidate = self.make_candidate(temporary, environment)
            result = subprocess.run(
                [sys.executable, str(PREFLIGHT), str(candidate)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            commands = [
                json.loads(line)
                for line in (temporary / "docker-commands.jsonl").read_text(
                    encoding="utf-8"
                ).splitlines()
            ]

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        snapshot = json.loads(result.stdout)
        self.assertEqual(snapshot["kind"], "compose_image_availability_preflight")
        self.assertEqual(snapshot["version"], "1.0")
        self.assertEqual(snapshot["status"], "LOCAL_IMAGE_AVAILABLE")
        self.assertEqual(snapshot["candidate_binding"]["project_name"], "kotodama-r14")
        self.assertEqual(snapshot["candidate_binding"]["image_manifest_digest"], MANIFEST_DIGEST)
        self.assertEqual(snapshot["image_observation"]["image_manifest_digest"], MANIFEST_DIGEST)
        self.assertTrue(snapshot["image_observation"]["available_locally"])
        self.assertTrue(snapshot["image_observation"]["repo_digest_match_observed"])
        self.assertRegex(snapshot["host_binding"]["daemon_id_sha256"], r"^[0-9a-f]{64}$")
        self.assertFalse(snapshot["host_binding"]["raw_identity_emitted"])
        self.assertTrue(snapshot["claims"]["daemon_reachable_verified"])
        self.assertTrue(snapshot["claims"]["local_image_available_verified"])
        self.assertTrue(snapshot["claims"]["manifest_digest_match_verified"])
        for claim in (
            "image_pulled",
            "services_started",
            "migrations_applied",
            "health_verified",
            "restart_verified",
            "backup_verified",
            "restore_verified",
            "promotion_verified",
            "current_truth_changed",
            "final_human_go",
            "public_beta_go",
        ):
            self.assertFalse(snapshot["claims"][claim])
        self.assertEqual(snapshot["public_beta"], "NO_GO_UNPUBLISHED")
        serialized = json.dumps(snapshot, sort_keys=True)
        for private_value in (
            "FAKE-PRIVATE-DAEMON-ID-R14",
            "private-hostname-must-not-leak",
            "private.invalid",
            "private-tag-must-not-leak",
            str(candidate),
        ):
            self.assertNotIn(private_value, serialized)
        preflight_commands = commands[1:]
        self.assertEqual([item[:2] for item in preflight_commands], [["info", "--format"], ["image", "ls"], ["image", "inspect"]])
        flattened = " ".join(" ".join(item) for item in preflight_commands)
        for forbidden in (" pull ", " run ", " create ", " start ", " tag ", " rmi "):
            self.assertNotIn(forbidden, " " + flattened + " ")

    def test_saved_snapshot_verifier_binds_candidate_without_claiming_fresh_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = self.fake_environment(temporary)
            candidate = self.make_candidate(temporary, environment)
            preflight = subprocess.run(
                [sys.executable, str(PREFLIGHT), str(candidate)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
            snapshot = temporary / "image-preflight.json"
            snapshot.write_text(preflight.stdout, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFY), str(snapshot), str(candidate)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "compose_image_availability_preflight_validation")
        self.assertEqual(report["version"], "1.1")
        self.assertEqual(report["status"], "HISTORICAL_BINDING_ONLY")
        self.assertEqual(report["errors"], [])
        self.assertTrue(report["claims"]["snapshot_self_digest_verified"])
        self.assertTrue(report["claims"]["candidate_binding_verified"])
        self.assertFalse(report["claims"]["snapshot_authenticity_verified"])
        self.assertFalse(report["claims"]["observation_freshness_verified"])
        self.assertFalse(report["claims"]["observation_atomicity_verified"])
        self.assertFalse(report["claims"]["current_daemon_reachable_verified"])
        self.assertFalse(report["claims"]["current_local_image_available_verified"])
        self.assertFalse(report["claims"]["public_beta_go"])
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_rehashed_observation_values_never_gain_authenticity_freshness_or_atomicity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = self.fake_environment(temporary)
            candidate = self.make_candidate(temporary, environment)
            preflight = subprocess.run(
                [sys.executable, str(PREFLIGHT), str(candidate)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            snapshot_value = json.loads(preflight.stdout)
            snapshot_value["host_binding"]["daemon_id_sha256"] = "f" * 64
            snapshot_value["image_observation"]["size_bytes"] += 1
            digest_input = dict(snapshot_value)
            digest_input.pop("preflight_sha256")
            snapshot_value["preflight_sha256"] = hashlib.sha256(
                json.dumps(
                    digest_input,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            snapshot = temporary / "self-rehashed-preflight.json"
            snapshot.write_text(json.dumps(snapshot_value), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFY), str(snapshot), str(candidate)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "HISTORICAL_BINDING_ONLY")
        self.assertTrue(report["claims"]["snapshot_self_digest_verified"])
        self.assertTrue(report["claims"]["candidate_binding_verified"])
        for claim in (
            "snapshot_authenticity_verified",
            "observation_freshness_verified",
            "observation_atomicity_verified",
            "current_daemon_reachable_verified",
            "current_local_image_available_verified",
        ):
            self.assertFalse(report["claims"][claim])

    def test_snapshot_schema_closes_identity_effect_and_go_boundaries(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertFalse(schema["properties"]["host_binding"]["additionalProperties"])
        self.assertFalse(
            schema["properties"]["host_binding"]["properties"]["raw_identity_emitted"]["const"]
        )
        self.assertFalse(schema["properties"]["effects"]["additionalProperties"])
        for field in (
            "image_pull",
            "image_tag",
            "image_remove",
            "container_create",
            "container_start",
            "daemon_configuration_change",
        ):
            self.assertFalse(schema["properties"]["effects"]["properties"][field]["const"])
        self.assertTrue(
            schema["properties"]["claims"]["properties"]["local_image_available_verified"]["const"]
        )
        self.assertFalse(schema["properties"]["claims"]["properties"]["public_beta_go"]["const"])

    def test_unreachable_daemon_refuses_without_forwarding_private_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = self.fake_environment(temporary)
            candidate = self.make_candidate(temporary, environment)
            environment["KOTODAMA_FAKE_DOCKER_MODE"] = "daemon-unavailable"
            result = subprocess.run(
                [sys.executable, str(PREFLIGHT), str(candidate)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "REFUSED")
        self.assertEqual(report["reason"], "DAEMON_UNAVAILABLE")
        self.assertNotIn("private-daemon-error-must-not-leak", result.stdout)
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_missing_ambiguous_or_uninspectable_image_fails_closed(self) -> None:
        cases = {
            "image-absent": "IMAGE_NOT_AVAILABLE",
            "digest-mismatch": "IMAGE_NOT_AVAILABLE",
            "ambiguous-image": "IMAGE_DIGEST_AMBIGUOUS",
            "inspect-failure": "IMAGE_INSPECT_REFUSED",
            "inspect-digest-mismatch": "IMAGE_DIGEST_MISMATCH",
        }
        for mode, reason in cases.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                temporary = Path(directory)
                environment = self.fake_environment(temporary)
                candidate = self.make_candidate(temporary, environment)
                environment["KOTODAMA_FAKE_DOCKER_MODE"] = mode
                result = subprocess.run(
                    [sys.executable, str(PREFLIGHT), str(candidate)],
                    cwd=ROOT,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )

            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stderr, "")
            report = json.loads(result.stdout)
            self.assertEqual(report["reason"], reason)
            self.assertNotIn("private.invalid", result.stdout)
            self.assertNotIn("private-inspect-error-must-not-leak", result.stdout)
            self.assertTrue(all(not value for value in report["claims"].values()))

    def test_saved_verifier_rejects_rehashed_mutating_effect_claim(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = self.fake_environment(temporary)
            candidate = self.make_candidate(temporary, environment)
            preflight = subprocess.run(
                [sys.executable, str(PREFLIGHT), str(candidate)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            snapshot_value = json.loads(preflight.stdout)
            snapshot_value["effects"]["image_pull"] = True
            digest_input = dict(snapshot_value)
            digest_input.pop("preflight_sha256")
            snapshot_value["preflight_sha256"] = hashlib.sha256(
                json.dumps(
                    digest_input,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            snapshot = temporary / "tampered-preflight.json"
            snapshot.write_text(json.dumps(snapshot_value), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(VERIFY), str(snapshot), str(candidate)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "INVALID")
        self.assertIn(
            "effects must remain the exact read-only observation contract",
            report["errors"],
        )
        self.assertTrue(all(not value for value in report["claims"].values()))

    def test_cli_usage_errors_return_two_without_json(self) -> None:
        for tool in (PREFLIGHT, VERIFY):
            with self.subTest(tool=tool.name):
                result = subprocess.run(
                    [sys.executable, str(tool)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("usage:", result.stderr)

    def test_output_option_writes_utf8_without_overwriting_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = self.fake_environment(temporary)
            candidate = temporary / "candidate.json"
            resolved = subprocess.run(
                [
                    sys.executable,
                    str(RESOLVER),
                    "kotodama-r14",
                    "--output",
                    str(candidate),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(resolved.returncode, 0, resolved.stdout + resolved.stderr)
            self.assertEqual(candidate.read_bytes(), resolved.stdout)
            snapshot = temporary / "preflight.json"
            preflight = subprocess.run(
                [
                    sys.executable,
                    str(PREFLIGHT),
                    str(candidate),
                    "--output",
                    str(snapshot),
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                check=False,
            )
            self.assertEqual(preflight.returncode, 0, preflight.stdout + preflight.stderr)
            self.assertEqual(snapshot.read_bytes(), preflight.stdout)
            command_count = len(
                (temporary / "docker-commands.jsonl").read_text(encoding="utf-8").splitlines()
            )
            repeated = subprocess.run(
                [
                    sys.executable,
                    str(PREFLIGHT),
                    str(candidate),
                    "--output",
                    str(snapshot),
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            final_command_count = len(
                (temporary / "docker-commands.jsonl").read_text(encoding="utf-8").splitlines()
            )

        self.assertEqual(repeated.returncode, 1)
        self.assertEqual(json.loads(repeated.stdout)["reason"], "OUTPUT_REFUSED")
        self.assertEqual(final_command_count, command_count)

    def test_saved_verifier_rejects_unknown_duplicate_and_candidate_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            environment = self.fake_environment(temporary)
            candidate = self.make_candidate(temporary, environment)
            preflight = subprocess.run(
                [sys.executable, str(PREFLIGHT), str(candidate)],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
            original = json.loads(preflight.stdout)

            unknown_value = dict(original)
            unknown_value["private_locator"] = "must-not-be-accepted"
            unknown = temporary / "unknown.json"
            unknown.write_text(json.dumps(unknown_value), encoding="utf-8")

            duplicate = temporary / "duplicate.json"
            duplicate.write_text(
                '{"kind":"shadow",' + preflight.stdout.lstrip()[1:],
                encoding="utf-8",
            )

            changed_candidate = json.loads(candidate.read_text(encoding="utf-8"))
            changed_candidate["project_name"] = "kotodama-r14-other"
            changed_candidate_path = temporary / "changed-candidate.json"
            changed_candidate_path.write_text(json.dumps(changed_candidate), encoding="utf-8")

            unknown_result = subprocess.run(
                [sys.executable, str(VERIFY), str(unknown), str(candidate)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            duplicate_result = subprocess.run(
                [sys.executable, str(VERIFY), str(duplicate), str(candidate)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            candidate_result = subprocess.run(
                [sys.executable, str(VERIFY), str(unknown), str(changed_candidate_path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

        self.assertEqual(unknown_result.returncode, 1)
        self.assertIn(
            "snapshot contains unknown field: private_locator",
            json.loads(unknown_result.stdout)["errors"],
        )
        self.assertEqual(duplicate_result.returncode, 1)
        self.assertEqual(json.loads(duplicate_result.stdout)["errors"], ["input JSON is invalid"])
        self.assertEqual(candidate_result.returncode, 1)
        self.assertEqual(
            json.loads(candidate_result.stdout)["errors"],
            ["resolved candidate is invalid"],
        )
        self.assertNotIn("must-not-be-accepted", unknown_result.stdout)


if __name__ == "__main__":
    unittest.main()
