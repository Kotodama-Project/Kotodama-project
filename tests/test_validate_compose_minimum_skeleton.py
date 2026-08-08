import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SKELETON = ROOT / "runtime" / "compose-minimum"
VALIDATOR = ROOT / "tools" / "validate_compose_minimum_skeleton.py"
GIT_ATTRIBUTES = ROOT / ".gitattributes"
SCHEMA = ROOT / "schemas" / "compose-minimum-skeleton.schema.json"


class ComposeMinimumSkeletonValidatorCliTests(unittest.TestCase):
    def test_exact_byte_bound_runtime_files_are_forced_to_lf_on_checkout(self) -> None:
        rules = {
            line.strip()
            for line in GIT_ATTRIBUTES.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertEqual(
            rules,
            {
                "runtime/compose-minimum/README.md text eol=lf",
                "runtime/compose-minimum/compose.yaml text eol=lf",
                "runtime/compose-minimum/company-db/001-company-core.sql text eol=lf",
                "runtime/compose-minimum/evidence-store/001-evidence-core.sql text eol=lf",
                "tools/cfos_pnpm_runtime_windows_shim.cs text eol=lf",
            },
        )

    def run_validator(self, directory: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(directory)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def copy_skeleton(self, parent: Path) -> Path:
        target = parent / "compose-minimum"
        shutil.copytree(SKELETON, target)
        return target

    def rebind(self, directory: Path, relative: str) -> None:
        manifest_path = directory / "skeleton.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        path = directory / relative
        for binding in manifest["bindings"]:
            if binding["path"] == relative:
                content = path.read_bytes()
                binding["sha256"] = hashlib.sha256(content).hexdigest()
                binding["bytes"] = len(content)
                break
        else:
            self.fail(f"binding not found: {relative}")
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_shipped_skeleton_passes_without_live_claims(self) -> None:
        result = self.run_validator(SKELETON)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        report = json.loads(result.stdout)
        self.assertEqual(report["kind"], "compose_minimum_skeleton_validation")
        self.assertEqual(report["version"], "1.0")
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["skeleton_id"], "kotodama-compose-data-plane")
        self.assertEqual(report["validated_files"], 4)
        self.assertEqual(report["errors"], [])
        self.assertTrue(all(not value for value in report["claims"].values()))
        self.assertEqual(report["public_beta"], "NO_GO_UNPUBLISHED")

    def test_integer_valued_json_number_for_binding_bytes_matches_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            manifest_path = skeleton / "skeleton.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["bindings"][0]["bytes"] = float(manifest["bindings"][0]["bytes"])
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
            Draft202012Validator(schema).validate(manifest)
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "PASS")

    def test_security_boolean_fixed_fields_reject_integer_aliases_in_schema_and_validator(self) -> None:
        for field in (
            "host_ports_forbidden",
            "networks_internal_and_separate",
            "volumes_separate",
        ):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temporary:
                skeleton = self.copy_skeleton(Path(temporary))
                manifest_path = skeleton / "skeleton.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["security"][field] = 1
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
                self.assertTrue(list(Draft202012Validator(schema).iter_errors(manifest)))
                result = self.run_validator(skeleton)

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                f"security.{field} does not match the safe skeleton contract",
                json.loads(result.stdout)["errors"],
            )

    def test_binding_bytes_still_rejects_boolean_fraction_and_negative_number(self) -> None:
        for invalid in (True, 1.5, -1.0):
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as temporary:
                skeleton = self.copy_skeleton(Path(temporary))
                manifest_path = skeleton / "skeleton.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["bindings"][0]["bytes"] = invalid
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                result = self.run_validator(skeleton)

            self.assertEqual(result.returncode, 1)
            self.assertIn(
                "binding[0].bytes must be a non-negative integer",
                json.loads(result.stdout)["errors"],
            )

    def test_one_byte_drift_fails_the_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            changed = skeleton / "company-db" / "001-company-core.sql"
            changed.write_bytes(changed.read_bytes() + b"\n")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "binding mismatch: company-db/001-company-core.sql",
            json.loads(result.stdout)["errors"],
        )

    def test_unbound_extra_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            (skeleton / "unreviewed.txt").write_text("extra", encoding="utf-8")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        self.assertIn("unbound file: unreviewed.txt", json.loads(result.stdout)["errors"])

    def test_hardcoded_password_is_rejected_even_after_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            compose = skeleton / "compose.yaml"
            content = compose.read_text(encoding="utf-8").replace(
                "${KOTODAMA_COMPANY_DB_PASSWORD:?set in private environment}",
                "hardcoded-example-password",
            )
            compose.write_text(content, encoding="utf-8")
            self.rebind(skeleton, "compose.yaml")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("hardcoded-example-password", result.stdout)
        self.assertIn(
            "compose company-db POSTGRES_PASSWORD must use its required private environment reference",
            json.loads(result.stdout)["errors"],
        )

    def test_expected_password_in_comment_cannot_mask_hardcoded_value(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            compose = skeleton / "compose.yaml"
            required = 'POSTGRES_PASSWORD: "${KOTODAMA_COMPANY_DB_PASSWORD:?set in private environment}"'
            content = compose.read_text(encoding="utf-8").replace(
                required,
                "POSTGRES_PASSWORD: hardcoded-comment-bypass\n      # " + required,
                1,
            )
            compose.write_text(content, encoding="utf-8")
            self.rebind(skeleton, "compose.yaml")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        self.assertNotIn("hardcoded-comment-bypass", result.stdout)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("compose comments are forbidden in the canonical skeleton", errors)
        self.assertIn(
            "compose company-db POSTGRES_PASSWORD must use its required private environment reference",
            errors,
        )
        self.assertIn("binding is not the shipped skeleton revision: compose.yaml", errors)

    def test_host_port_and_mutable_image_are_rejected_after_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            compose = skeleton / "compose.yaml"
            content = compose.read_text(encoding="utf-8")
            content = content.replace(
                "services:\n",
                "services:\n  unsafe:\n    image: postgres:latest\n    ports:\n      - '5432:5432'\n",
            )
            compose.write_text(content, encoding="utf-8")
            self.rebind(skeleton, "compose.yaml")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("compose host port publication is forbidden", errors)
        self.assertIn("compose images must use the required digest-pinned environment reference", errors)

    def test_service_networks_and_storage_must_remain_separate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            manifest_path = skeleton / "skeleton.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["services"][1]["network"] = manifest["services"][0]["network"]
            manifest["services"][1]["volume"] = manifest["services"][0]["volume"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("service networks must be distinct", errors)
        self.assertIn("service volumes must be distinct", errors)

    def test_compose_body_cannot_merge_service_networks_or_volumes_after_rebinding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            compose = skeleton / "compose.yaml"
            content = compose.read_text(encoding="utf-8")
            evidence_start = content.index("  evidence-store:")
            networks_start = content.index("\nnetworks:")
            before = content[:evidence_start]
            evidence = content[evidence_start:networks_start]
            after = content[networks_start:]
            evidence = evidence.replace(
                "- evidence-store-data:/var/lib/postgresql/data",
                "- company-db-data:/var/lib/postgresql/data",
            ).replace("- evidence-data", "- company-data")
            compose.write_text(before + evidence + after, encoding="utf-8")
            self.rebind(skeleton, "compose.yaml")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("compose service networks must be distinct and role bound", errors)
        self.assertIn("compose service volumes must be distinct and role bound", errors)

    def test_compose_credentials_migrations_and_healthchecks_are_role_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            compose = skeleton / "compose.yaml"
            content = compose.read_text(encoding="utf-8")
            company_password = "${KOTODAMA_COMPANY_DB_PASSWORD:?set in private environment}"
            evidence_password = "${KOTODAMA_EVIDENCE_DB_PASSWORD:?set in private environment}"
            content = content.replace(company_password, "${SWAP_PLACEHOLDER}", 1)
            content = content.replace(evidence_password, company_password, 1)
            content = content.replace("${SWAP_PLACEHOLDER}", evidence_password, 1)
            content = content.replace(
                "./evidence-store/001-evidence-core.sql:/docker-entrypoint-initdb.d/001-evidence-core.sql:ro",
                "./evidence-store/001-evidence-core.sql:/docker-entrypoint-initdb.d/001-evidence-core.sql:rw",
            )
            content = content.replace(
                "pg_isready -U kotodama_evidence_owner -d kotodama_evidence",
                "pg_isready -U kotodama_company_owner -d kotodama_company",
            )
            compose.write_text(content, encoding="utf-8")
            self.rebind(skeleton, "compose.yaml")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("compose database password references must be role bound", errors)
        self.assertIn("compose migrations must be role bound and read-only", errors)
        self.assertIn("compose healthchecks must be role bound", errors)

    def test_sql_contract_requires_non_login_roles_and_core_tables(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            sql = skeleton / "evidence-store" / "001-evidence-core.sql"
            content = sql.read_text(encoding="utf-8")
            content = content.replace("NOLOGIN", "LOGIN", 1)
            content = content.replace("CREATE TABLE evidence.receipt", "CREATE TABLE evidence.missing_receipt")
            sql.write_text(content, encoding="utf-8")
            self.rebind(skeleton, "evidence-store/001-evidence-core.sql")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("evidence-store SQL must define NOLOGIN roles", errors)
        self.assertIn("evidence-store SQL missing core table: evidence.receipt", errors)

    def test_sql_comment_cannot_mask_a_missing_core_table(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            sql = skeleton / "evidence-store" / "001-evidence-core.sql"
            content = sql.read_text(encoding="utf-8").replace(
                "CREATE TABLE evidence.receipt (",
                "CREATE TABLE evidence.shadow_receipt (\n-- CREATE TABLE evidence.receipt (",
                1,
            )
            sql.write_text(content, encoding="utf-8")
            self.rebind(skeleton, "evidence-store/001-evidence-core.sql")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("evidence-store SQL comments are forbidden", errors)
        self.assertIn("evidence-store SQL missing core table: evidence.receipt", errors)
        self.assertIn(
            "binding is not the shipped skeleton revision: evidence-store/001-evidence-core.sql",
            errors,
        )

    def test_shipped_company_schema_cannot_self_mark_promotion(self) -> None:
        sql = (SKELETON / "company-db" / "001-company-core.sql").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("'promoted'", sql)
        self.assertNotIn("current_truth", sql.lower())

    def test_rebound_company_schema_cannot_add_promotion_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            sql = skeleton / "company-db" / "001-company-core.sql"
            content = sql.read_text(encoding="utf-8").replace(
                "'verified_candidate'", "'verified_candidate', 'promoted'"
            )
            sql.write_text(content, encoding="utf-8")
            self.rebind(skeleton, "company-db/001-company-core.sql")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "company-db SQL cannot define Promotion or Current Truth state",
            json.loads(result.stdout)["errors"],
        )

    def test_claims_and_public_beta_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            manifest_path = skeleton / "skeleton.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["claims"]["clean_install_verified"] = True
            manifest["public_beta"] = "GO"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            result = self.run_validator(skeleton)

        self.assertEqual(result.returncode, 1)
        errors = json.loads(result.stdout)["errors"]
        self.assertIn("claim clean_install_verified must remain false", errors)
        self.assertIn("public_beta must remain NO_GO_UNPUBLISHED", errors)

    def test_duplicate_keys_non_finite_and_unknown_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            manifest_path = skeleton / "skeleton.json"
            original = manifest_path.read_text(encoding="utf-8")
            manifest_path.write_text('{"kind":"shadow",' + original[1:], encoding="utf-8")
            duplicate = self.run_validator(skeleton)

        self.assertEqual(duplicate.returncode, 1)
        self.assertEqual(json.loads(duplicate.stdout)["errors"], ["skeleton JSON is invalid"])

        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            manifest_path = skeleton / "skeleton.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["unknown"] = float("nan")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            non_finite = self.run_validator(skeleton)

        self.assertEqual(non_finite.returncode, 1)
        self.assertEqual(json.loads(non_finite.stdout)["errors"], ["skeleton JSON is invalid"])

        with tempfile.TemporaryDirectory() as temporary:
            skeleton = self.copy_skeleton(Path(temporary))
            manifest_path = skeleton / "skeleton.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["unknown"] = True
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            unknown = self.run_validator(skeleton)

        self.assertEqual(unknown.returncode, 1)
        self.assertIn("skeleton contains unknown field: unknown", json.loads(unknown.stdout)["errors"])

    def test_compose_config_resolves_to_the_role_bound_structure(self) -> None:
        docker = shutil.which("docker")
        if docker is None:
            self.skipTest("Docker Compose is unavailable")
        environment = os.environ.copy()
        environment.update(
            {
                "KOTODAMA_POSTGRES_IMAGE": "postgres@sha256:" + "0" * 64,
                "KOTODAMA_COMPANY_DB_PASSWORD": "synthetic-company-only",
                "KOTODAMA_EVIDENCE_DB_PASSWORD": "synthetic-evidence-only",
            }
        )
        result = subprocess.run(
            [
                docker,
                "compose",
                "--file",
                str(SKELETON / "compose.yaml"),
                "config",
                "--format",
                "json",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        if "compose is not a docker command" in result.stderr.lower():
            self.skipTest("Docker Compose plugin is unavailable")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        resolved = json.loads(result.stdout)
        self.assertEqual(set(resolved["services"]), {"company-db", "evidence-store"})
        expected = {
            "company-db": {
                "network": "company-data",
                "volume": "company-db-data",
                "password": "synthetic-company-only",
                "health": "pg_isready -U kotodama_company_owner -d kotodama_company",
                "migration": "001-company-core.sql",
            },
            "evidence-store": {
                "network": "evidence-data",
                "volume": "evidence-store-data",
                "password": "synthetic-evidence-only",
                "health": "pg_isready -U kotodama_evidence_owner -d kotodama_evidence",
                "migration": "001-evidence-core.sql",
            },
        }
        for service_id, contract in expected.items():
            service = resolved["services"][service_id]
            self.assertNotIn("ports", service)
            self.assertEqual(set(service["networks"]), {contract["network"]})
            self.assertEqual(service["pull_policy"], "never")
            self.assertEqual(
                service["image"], "postgres@sha256:" + "0" * 64
            )
            self.assertEqual(
                service["environment"]["POSTGRES_PASSWORD"], contract["password"]
            )
            self.assertEqual(service["healthcheck"]["test"][1], contract["health"])
            data_volumes = [
                item
                for item in service["volumes"]
                if item["target"] == "/var/lib/postgresql/data"
            ]
            self.assertEqual(len(data_volumes), 1)
            self.assertEqual(data_volumes[0]["source"], contract["volume"])
            migrations = [
                item
                for item in service["volumes"]
                if item["target"].startswith("/docker-entrypoint-initdb.d/")
            ]
            self.assertEqual(len(migrations), 1)
            self.assertTrue(migrations[0]["read_only"])
            self.assertTrue(migrations[0]["target"].endswith(contract["migration"]))
        self.assertTrue(resolved["networks"]["company-data"]["internal"])
        self.assertTrue(resolved["networks"]["evidence-data"]["internal"])

    def test_validation_is_deterministic(self) -> None:
        first = self.run_validator(SKELETON)
        second = self.run_validator(SKELETON)

        self.assertEqual(first.returncode, 0, first.stdout)
        self.assertEqual(first.stdout, second.stdout)

    def test_schema_closes_the_manifest_and_denies_live_claims(self) -> None:
        schema = json.loads(
            (ROOT / "schemas" / "compose-minimum-skeleton.schema.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["public_beta"]["const"], "NO_GO_UNPUBLISHED")
        self.assertFalse(schema["properties"]["claims"]["additionalProperties"])
        for definition in schema["properties"]["claims"]["properties"].values():
            self.assertIs(definition["const"], False)

    def test_usage_error_returns_two_without_json(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR)],
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
