import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import validate_resolved_compose_candidate as candidate_validator


ROOT = Path(__file__).resolve().parents[1]
RESOLVER = ROOT / "tools" / "resolve_compose_candidate.py"
VALIDATOR = ROOT / "tools" / "validate_resolved_compose_candidate.py"
SCHEMA = ROOT / "schemas" / "resolved-compose-candidate.schema.json"
IMAGE = "postgres@sha256:" + "0" * 64
COMPANY_SECRET = "synthetic-company-r13-secret"
EVIDENCE_SECRET = "synthetic-evidence-r13-secret"


def synthetic_candidate() -> dict:
    source = candidate_validator.shipped_source()
    bindings = source["bindings"]
    binding_hashes = {item["path"]: item["sha256"] for item in bindings}
    services = []
    for service_id in ("company-db", "evidence-store"):
        expected = candidate_validator.EXPECTED_SERVICE_BASE[service_id]
        services.append(
            {
                "id": service_id,
                "role": expected["role"],
                "image_digest": IMAGE.replace("postgres@", ""),
                "network": expected["network"],
                "volume": expected["volume"],
                "migration": expected["migration"],
                "migration_sha256": binding_hashes[expected["migration"]],
                "healthcheck_sha256": hashlib.sha256(
                    expected["healthcheck"].encode("utf-8")
                ).hexdigest(),
            }
        )
    candidate = {
        "kind": "resolved_compose_candidate",
        "version": "1.0",
        "status": "CANDIDATE_READY_FOR_RUNTIME_PREFLIGHT",
        "project_name": "synthetic-resolved-candidate",
        "source": copy.deepcopy(source),
        "resolved": {
            "credential_contract": {
                "source": "process_environment",
                "both_present_observed": True,
                "distinct_values_observed": True,
                "values_emitted": False,
                "password_derived_digest": False,
            },
            "networks": copy.deepcopy(candidate_validator.EXPECTED_NETWORKS),
            "services": services,
            "resolved_contract_sha256": "0" * 64,
        },
        "claims": candidate_validator.false_claims(),
        "public_beta": "NO_GO_UNPUBLISHED",
    }
    candidate["resolved"]["resolved_contract_sha256"] = (
        candidate_validator.canonical_sha256(
            candidate_validator.safe_contract_projection(candidate)
        )
    )
    return candidate


class ResolvedComposeCandidateCliTests(unittest.TestCase):
    def compose_available(self) -> bool:
        docker = shutil.which("docker")
        if docker is None:
            return False
        result = subprocess.run(
            [docker, "compose", "version"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode == 0

    def run_resolver(
        self,
        project_name: str = "kotodama-r13",
        *,
        image: str = IMAGE,
        company_secret: str | None = COMPANY_SECRET,
        evidence_secret: str | None = EVIDENCE_SECRET,
    ) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["KOTODAMA_POSTGRES_IMAGE"] = image
        if company_secret is None:
            environment.pop("KOTODAMA_COMPANY_DB_PASSWORD", None)
        else:
            environment["KOTODAMA_COMPANY_DB_PASSWORD"] = company_secret
        if evidence_secret is None:
            environment.pop("KOTODAMA_EVIDENCE_DB_PASSWORD", None)
        else:
            environment["KOTODAMA_EVIDENCE_DB_PASSWORD"] = evidence_secret
        return subprocess.run(
            [sys.executable, str(RESOLVER), project_name],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )

    def run_validator(self, bundle: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )

    def require_compose(self) -> None:
        if not self.compose_available():
            self.skipTest("Docker Compose is unavailable")

    def test_valid_resolution_emits_only_a_safe_bound_candidate(self) -> None:
        self.require_compose()
        result = self.run_resolver()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        bundle = json.loads(result.stdout)
        self.assertEqual(
            set(bundle),
            {
                "kind",
                "version",
                "status",
                "project_name",
                "source",
                "resolved",
                "claims",
                "public_beta",
            },
        )
        self.assertEqual(bundle["kind"], "resolved_compose_candidate")
        self.assertEqual(bundle["version"], "1.0")
        self.assertEqual(bundle["status"], "CANDIDATE_READY_FOR_RUNTIME_PREFLIGHT")
        self.assertEqual(bundle["project_name"], "kotodama-r13")
        self.assertEqual(bundle["source"]["skeleton_id"], "kotodama-compose-data-plane")
        self.assertRegex(bundle["source"]["skeleton_manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(len(bundle["source"]["bindings"]), 4)
        self.assertEqual(
            [item["id"] for item in bundle["resolved"]["services"]],
            ["company-db", "evidence-store"],
        )
        self.assertEqual(
            [item["id"] for item in bundle["resolved"]["networks"]],
            ["company-data", "evidence-data"],
        )
        credential_contract = bundle["resolved"]["credential_contract"]
        self.assertEqual(
            credential_contract,
            {
                "source": "process_environment",
                "both_present_observed": True,
                "distinct_values_observed": True,
                "values_emitted": False,
                "password_derived_digest": False,
            },
        )
        self.assertTrue(all(not value for value in bundle["claims"].values()))
        self.assertEqual(bundle["public_beta"], "NO_GO_UNPUBLISHED")
        serialized = json.dumps(bundle, sort_keys=True)
        self.assertNotIn(COMPANY_SECRET, serialized)
        self.assertNotIn(EVIDENCE_SECRET, serialized)
        self.assertNotIn(str(ROOT), serialized)
        self.assertNotIn("postgres@", serialized)

    def test_password_changes_do_not_change_output_or_any_digest(self) -> None:
        self.require_compose()
        first = self.run_resolver(
            company_secret="synthetic-company-first",
            evidence_secret="synthetic-evidence-first",
        )
        second = self.run_resolver(
            company_secret="synthetic-company-second",
            evidence_secret="synthetic-evidence-second",
        )

        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertEqual(first.stdout, second.stdout)

    def test_equal_passwords_fail_closed_without_echoing_the_value(self) -> None:
        self.require_compose()
        secret = "synthetic-shared-secret-that-must-not-leak"
        result = self.run_resolver(company_secret=secret, evidence_secret=secret)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["status"], "REFUSED")
        self.assertEqual(report["reason"], "CREDENTIAL_CONTRACT_REFUSED")
        self.assertNotIn(secret, result.stdout)
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_missing_password_and_mutable_image_fail_without_compose_stderr(self) -> None:
        self.require_compose()
        missing = self.run_resolver(company_secret=None)
        mutable = self.run_resolver(image="postgres:latest")

        self.assertEqual(missing.returncode, 1)
        self.assertEqual(missing.stderr, "")
        self.assertEqual(json.loads(missing.stdout)["reason"], "RESOLUTION_REFUSED")
        self.assertNotIn("KOTODAMA_COMPANY_DB_PASSWORD", missing.stdout)
        self.assertEqual(mutable.returncode, 1)
        self.assertEqual(mutable.stderr, "")
        self.assertEqual(json.loads(mutable.stdout)["reason"], "IMAGE_NOT_DIGEST_PINNED")
        self.assertNotIn("postgres:latest", mutable.stdout)

    def test_unsafe_project_name_is_a_usage_error_before_resolution(self) -> None:
        result = self.run_resolver("../private path")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("usage:", result.stderr)
        self.assertNotIn("../private path", result.stderr)

    def test_saved_candidate_validator_passes_and_recomputes_digest(self) -> None:
        self.require_compose()
        resolved = self.run_resolver()
        bundle = json.loads(resolved.stdout)
        result = self.run_validator(bundle)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "resolved_compose_candidate_validation")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["errors"], [])
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_saved_candidate_validator_rejects_tamper_unknown_and_live_claims(self) -> None:
        self.require_compose()
        bundle = json.loads(self.run_resolver().stdout)
        tampered = copy.deepcopy(bundle)
        tampered["resolved"]["services"][0]["network"] = "evidence-data"
        unknown = copy.deepcopy(bundle)
        unknown["unexpected"] = True
        live_claim = copy.deepcopy(bundle)
        live_claim["claims"]["services_started"] = True

        tampered_result = self.run_validator(tampered)
        unknown_result = self.run_validator(unknown)
        live_result = self.run_validator(live_claim)

        self.assertEqual(tampered_result.returncode, 1)
        self.assertIn("resolved contract digest mismatch", json.loads(tampered_result.stdout)["errors"])
        self.assertEqual(unknown_result.returncode, 1)
        self.assertIn("candidate contains unknown field: unexpected", json.loads(unknown_result.stdout)["errors"])
        self.assertEqual(live_result.returncode, 1)
        self.assertIn("claim services_started must remain false", json.loads(live_result.stdout)["errors"])

    def test_saved_candidate_requires_one_shared_resolved_image_digest(self) -> None:
        self.require_compose()
        bundle = json.loads(self.run_resolver().stdout)
        bundle["resolved"]["services"][1]["image_digest"] = "sha256:" + "2" * 64
        projection = {
            "project_name": bundle["project_name"],
            "networks": bundle["resolved"]["networks"],
            "services": bundle["resolved"]["services"],
        }
        bundle["resolved"]["resolved_contract_sha256"] = hashlib.sha256(
            json.dumps(
                projection,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        result = self.run_validator(bundle)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "resolved service image digests must match",
            json.loads(result.stdout)["errors"],
        )

    def test_shipped_source_rejects_manifest_to_file_byte_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = Path(temporary) / "compose-minimum"
            shutil.copytree(ROOT / "runtime" / "compose-minimum", skeleton)
            readme = skeleton / "README.md"
            readme.write_bytes(readme.read_bytes() + b"\n")

            with self.assertRaises(ValueError):
                candidate_validator.shipped_source(skeleton)

    def test_schema_is_closed_and_denies_runtime_and_go_claims(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertFalse(schema["properties"]["claims"]["additionalProperties"])
        for definition in schema["properties"]["claims"]["properties"].values():
            self.assertIs(definition["const"], False)
        credential = schema["$defs"]["credentialContract"]
        self.assertFalse(credential["additionalProperties"])
        self.assertFalse(credential["properties"]["values_emitted"]["const"])
        self.assertFalse(credential["properties"]["password_derived_digest"]["const"])

    def test_integer_valued_json_number_for_binding_bytes_matches_schema_and_validator(self) -> None:
        candidate = synthetic_candidate()
        candidate["source"]["bindings"][0]["bytes"] = float(
            candidate["source"]["bindings"][0]["bytes"]
        )
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

        Draft202012Validator(schema).validate(candidate)
        self.assertEqual(candidate_validator.validate_candidate(candidate), [])

    def test_resolved_binding_bytes_rejects_boolean_fraction_negative_and_non_finite(self) -> None:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        for invalid in (True, 1.5, -1, float("nan")):
            with self.subTest(invalid=invalid):
                candidate = synthetic_candidate()
                candidate["source"]["bindings"][0]["bytes"] = invalid
                with self.assertRaises(ValidationError):
                    Draft202012Validator(schema).validate(candidate)
                self.assertTrue(candidate_validator.validate_candidate(candidate))

    def test_usage_errors_return_two_without_json(self) -> None:
        resolver = subprocess.run(
            [sys.executable, str(RESOLVER)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        validator = subprocess.run(
            [sys.executable, str(VALIDATOR)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(resolver.returncode, 2)
        self.assertEqual(resolver.stdout, "")
        self.assertIn("usage:", resolver.stderr)
        self.assertEqual(validator.returncode, 2)
        self.assertEqual(validator.stdout, "")
        self.assertIn("usage:", validator.stderr)


if __name__ == "__main__":
    unittest.main()
