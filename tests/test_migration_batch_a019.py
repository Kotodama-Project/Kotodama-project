from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR_PATH = ROOT / "tools" / "validate_migration_batch_a019.py"
SPEC = importlib.util.spec_from_file_location("validate_migration_batch_a019", VALIDATOR_PATH)
assert SPEC is not None and SPEC.loader is not None
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


class A019MigrationBatchTests(unittest.TestCase):
    def _fixture(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name) / "candidate"
        root.mkdir()
        for relative in VALIDATOR.REQUIRED_PATHS:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        return temporary, root

    @staticmethod
    def _manifest(root: Path) -> dict[str, object]:
        return json.loads(
            (root / VALIDATOR.MANIFEST_PATH).read_text(encoding="utf-8")
        )

    @staticmethod
    def _write_manifest(root: Path, manifest: dict[str, object]) -> None:
        (root / VALIDATOR.MANIFEST_PATH).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _schemas(root: Path) -> dict[str, dict[str, object]]:
        return {
            path: json.loads((root / path).read_text(encoding="utf-8"))
            for path in VALIDATOR.DESTINATIONS
        }

    def _instance_context(
        self,
    ) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
        schemas = self._schemas(ROOT)
        meta_errors: list[str] = []
        validators = VALIDATOR._schema_validators(schemas, meta_errors)
        self.assertEqual(meta_errors, [])
        return schemas, validators

    def test_exact_candidate_passes_but_admission_remains_blocked(self) -> None:
        result = VALIDATOR.validate(ROOT)
        manifest = self._manifest(ROOT)

        self.assertEqual(result["status"], "PASS", result["errors"])
        self.assertFalse(result["changed"])
        self.assertEqual(result["source_entries"], 6)
        self.assertEqual(
            result["decisions"], {"PRIVATE_RETAIN": 2, "PUBLIC_REAUTHOR": 4}
        )
        self.assertEqual(result["unique_reauthored_destinations"], 4)
        self.assertEqual(result["destination_blobs_verified"], 4)
        self.assertEqual(result["schemas_meta_validated"], 4)
        self.assertTrue(result["offline_refs_resolved"])
        self.assertEqual(result["source_registry_blob_reuse"], 0)
        self.assertEqual(result["source_path_leakage"], 0)
        self.assertEqual(result["candidate_scan_findings"], 0)
        self.assertEqual(result["admission_status"], "BLOCKED")
        self.assertEqual(
            manifest["component_license"]["source_derived_scope"],
            sorted(VALIDATOR.DESTINATIONS),
        )
        self.assertIn(
            "MISSING_APPLICABLE_A019_PRIVATE_SOURCE_HISTORY_RECEIPT",
            result["no_go_reasons"],
        )

    def test_exact_six_source_mapping_fails_closed_on_drift(self) -> None:
        mutations = (
            lambda manifest: manifest["entries"].append(
                copy.deepcopy(manifest["entries"][0])
            ),
            lambda manifest: manifest["entries"][0].__setitem__("source_mode", "100755"),
            lambda manifest: manifest["entries"][0].__setitem__(
                "source_blob_sha", "0" * 40
            ),
            lambda manifest: manifest["entries"][0].__setitem__(
                "source_path", "unlisted/source.json"
            ),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                temporary, root = self._fixture()
                with temporary:
                    manifest = self._manifest(root)
                    mutate(manifest)
                    self._write_manifest(root, manifest)
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertTrue(
                        any(
                            "mapping" in error
                            or "source-blob coverage" in error
                            or "exactly 6" in error
                            for error in result["errors"]
                        ),
                        result["errors"],
                    )

    def test_manifest_entries_reject_unknown_fields(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            manifest["entries"][0]["source_body"] = "unexported source prose"
            self._write_manifest(root, manifest)

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any("unknown manifest entry field" in error for error in result["errors"]),
                result["errors"],
            )

    def test_malformed_manifest_entry_values_fail_closed(self) -> None:
        mutations = (
            ("source_path", [], "every source path must be a string"),
            ("semantic_coverage", ["bounded", {}], "semantic coverage must be"),
            ("decision", {}, "every decision must be a string"),
            ("source_blob_sha", [], "source-blob coverage mismatch"),
            ("destination_path", [], "PUBLIC_REAUTHOR destination set"),
        )
        for field, value, expected in mutations:
            with self.subTest(field=field):
                temporary, root = self._fixture()
                with temporary:
                    manifest = self._manifest(root)
                    entry_index = 2 if field == "destination_path" else 0
                    manifest["entries"][entry_index][field] = value
                    self._write_manifest(root, manifest)

                    result = VALIDATOR.validate(root)

                    self.assertEqual(result["status"], "FAIL")
                    self.assertTrue(
                        any(expected in error for error in result["errors"]),
                        result["errors"],
                    )

    def test_schema_meta_validation_and_offline_refs_are_exact(self) -> None:
        schemas, validators = self._instance_context()
        self.assertEqual(set(schemas), set(VALIDATOR.DESTINATIONS))
        self.assertEqual(set(validators), set(VALIDATOR.DESTINATIONS))
        self.assertEqual(VALIDATOR._offline_ref_errors(schemas), [])
        for path, schema in schemas.items():
            self.assertEqual(schema["$id"], VALIDATOR.SCHEMA_IDS[path])
            self.assertEqual(
                schema["$schema"], "https://json-schema.org/draft/2020-12/schema"
            )
            self.assertEqual(
                schema["properties"]["candidate_status"]["const"], "candidate_only"
            )

        drifted = copy.deepcopy(schemas)
        drifted["schemas/task-decomposition.schema.json"]["properties"]["tasks"][
            "items"
        ]["$ref"] = "https://invalid.example/schema.json"
        self.assertTrue(
            any("non-offline" in error for error in VALIDATOR._offline_ref_errors(drifted))
        )

    def test_positive_contracts_resolve_and_validate(self) -> None:
        schemas, validators = self._instance_context()
        for path, instance in VALIDATOR.positive_instances().items():
            with self.subTest(path=path):
                self.assertEqual(
                    VALIDATOR.validate_instance(path, instance, schemas, validators), []
                )

    def test_task_and_decomposition_semantics_reject_invalid_graphs(self) -> None:
        schemas, validators = self._instance_context()
        positives = VALIDATOR.positive_instances()
        task = copy.deepcopy(positives["schemas/task-contract.schema.json"])
        task["dependency_task_ids"] = [task["task_id"]]
        task["authority"]["denied_actions"] = list(
            task["authority"]["allowed_actions"]
        )
        self.assertTrue(
            VALIDATOR.validate_instance(
                "schemas/task-contract.schema.json", task, schemas, validators
            )
        )

        task_mutations = []
        duplicate_check = copy.deepcopy(
            positives["schemas/task-contract.schema.json"]
        )
        duplicate_check["acceptance_checks"].append(
            copy.deepcopy(duplicate_check["acceptance_checks"][0])
        )
        task_mutations.append((duplicate_check, "duplicate acceptance check IDs"))

        invalid_irreversible = copy.deepcopy(
            positives["schemas/task-contract.schema.json"]
        )
        invalid_irreversible["rollback"] = {
            "reversible": False,
            "strategy": "restore_previous",
            "steps": ["Restore the candidate."],
        }
        task_mutations.append(
            (
                invalid_irreversible,
                "irreversible task must use not_applicable with no rollback steps",
            )
        )

        invalid_reversible = copy.deepcopy(
            positives["schemas/task-contract.schema.json"]
        )
        invalid_reversible["rollback"] = {
            "reversible": True,
            "strategy": "not_applicable",
            "steps": [],
        }
        task_mutations.append(
            (
                invalid_reversible,
                "reversible task must define a rollback strategy and steps",
            )
        )

        for instance, expected in task_mutations:
            with self.subTest(expected=expected):
                errors = VALIDATOR.validate_instance(
                    "schemas/task-contract.schema.json",
                    instance,
                    schemas,
                    validators,
                )
                self.assertIn(expected, errors, errors)

        base = positives["schemas/task-decomposition.schema.json"]
        mutations = []

        unknown = copy.deepcopy(base)
        unknown["tasks"][0]["dependency_task_ids"] = ["task.missing"]
        unknown["edges"][0]["to_task_id"] = "task.missing"
        mutations.append((unknown, "unknown dependency reference"))

        duplicate = copy.deepcopy(base)
        duplicate["tasks"].append(copy.deepcopy(duplicate["tasks"][0]))
        mutations.append((duplicate, "duplicate task IDs"))

        self_edge = copy.deepcopy(base)
        self_edge["tasks"][0]["dependency_task_ids"] = ["task.root"]
        self_edge["edges"][0]["to_task_id"] = "task.root"
        mutations.append((self_edge, "self dependency edge"))

        cycle = copy.deepcopy(base)
        cycle["tasks"][1]["dependency_task_ids"] = ["task.root"]
        cycle["edges"].append(
            {
                "from_task_id": "task.child",
                "to_task_id": "task.root",
                "relation": "requires",
            }
        )
        mutations.append((cycle, "cyclic dependency graph"))

        for instance, expected in mutations:
            with self.subTest(expected=expected):
                errors = VALIDATOR.validate_instance(
                    "schemas/task-decomposition.schema.json",
                    instance,
                    schemas,
                    validators,
                )
                self.assertIn(expected, errors, errors)

    def test_worker_contracts_reject_open_world_and_unsupported_claims(self) -> None:
        schemas, validators = self._instance_context()
        positives = VALIDATOR.positive_instances()

        catalog = copy.deepcopy(
            positives["schemas/worker-capability-catalog.schema.json"]
        )
        catalog["workers"][0]["provider_name"] = "unspecified"
        catalog["workers"][0]["capabilities"].append(
            copy.deepcopy(catalog["workers"][0]["capabilities"][0])
        )
        catalog_errors = VALIDATOR.validate_instance(
            "schemas/worker-capability-catalog.schema.json",
            catalog,
            schemas,
            validators,
        )
        self.assertTrue(
            any("schema validation failed" in error for error in catalog_errors),
            catalog_errors,
        )
        self.assertIn("duplicate capability IDs", catalog_errors)

        for risk_class in ("reversible_change", "privileged_change"):
            with self.subTest(risk_class=risk_class):
                mutation_catalog = copy.deepcopy(
                    positives["schemas/worker-capability-catalog.schema.json"]
                )
                mutation_capability = mutation_catalog["workers"][0][
                    "capabilities"
                ][0]
                mutation_capability["risk_class"] = risk_class
                mutation_capability["evidence_required"] = False
                mutation_errors = VALIDATOR.validate_instance(
                    "schemas/worker-capability-catalog.schema.json",
                    mutation_catalog,
                    schemas,
                    validators,
                )
                self.assertIn(
                    "mutation capability must require evidence", mutation_errors
                )

        result = positives["schemas/worker-result.schema.json"]
        mutations = []
        no_evidence = copy.deepcopy(result)
        no_evidence["evidence_refs"] = []
        no_evidence["checks"] = []
        mutations.append((no_evidence, "succeeded result must bind evidence"))
        failed_check = copy.deepcopy(result)
        failed_check["checks"][0]["status"] = "fail"
        mutations.append(
            (failed_check, "succeeded result requires every check to pass")
        )
        not_run_check = copy.deepcopy(result)
        not_run_check["checks"][0]["status"] = "not_run"
        not_run_check["checks"][0].pop("evidence_ref")
        mutations.append(
            (not_run_check, "succeeded result requires every check to pass")
        )
        omitted_success = copy.deepcopy(result)
        omitted_success["omitted_work"] = ["One bounded check was not performed."]
        mutations.append((omitted_success, "succeeded result cannot omit work"))
        error_success = copy.deepcopy(result)
        error_success["error_category"] = "unknown"
        mutations.append(
            (error_success, "succeeded result cannot include an error category")
        )
        duplicate_check = copy.deepcopy(result)
        duplicate_check["checks"].append(copy.deepcopy(duplicate_check["checks"][0]))
        mutations.append((duplicate_check, "duplicate result check IDs"))
        failed_without_detail = copy.deepcopy(result)
        failed_without_detail["status"] = "failed"
        failed_without_detail["error_category"] = "tool_failure"
        failed_without_detail["evidence_refs"] = []
        failed_without_detail["checks"] = []
        mutations.append(
            (
                failed_without_detail,
                "failed or blocked result requires omitted work or a failed check",
            )
        )
        blocked_without_error = copy.deepcopy(result)
        blocked_without_error["status"] = "blocked"
        blocked_without_error["evidence_refs"] = []
        blocked_without_error["checks"] = []
        blocked_without_error["omitted_work"] = ["Await bounded input."]
        mutations.append(
            (
                blocked_without_error,
                "failed or blocked result requires an error category",
            )
        )
        blocked_without_detail = copy.deepcopy(result)
        blocked_without_detail["status"] = "blocked"
        blocked_without_detail["error_category"] = "authority"
        blocked_without_detail["evidence_refs"] = []
        blocked_without_detail["checks"] = []
        blocked_without_detail["omitted_work"] = []
        mutations.append(
            (
                blocked_without_detail,
                "failed or blocked result requires omitted work or a failed check",
            )
        )
        for claim in ("promotion", "current_truth", "release"):
            authority_claim = copy.deepcopy(result)
            authority_claim["authority_claims"][claim] = True
            mutations.append(
                (authority_claim, "result authority claims must all remain false")
            )
        for rollback_status in ("available", "executed", "failed"):
            missing_rollback_receipt = copy.deepcopy(result)
            missing_rollback_receipt["rollback"]["status"] = rollback_status
            missing_rollback_receipt["rollback"]["receipt_refs"] = []
            mutations.append(
                (missing_rollback_receipt, "rollback status requires a receipt")
            )
        unexpected_rollback_receipt = copy.deepcopy(result)
        unexpected_rollback_receipt["rollback"]["status"] = "not_required"
        unexpected_rollback_receipt["rollback"]["receipt_refs"] = [
            "urn:evidence/rollback"
        ]
        mutations.append(
            (
                unexpected_rollback_receipt,
                "not_required rollback cannot bind receipts",
            )
        )

        for instance, expected in mutations:
            with self.subTest(expected=expected):
                errors = VALIDATOR.validate_instance(
                    "schemas/worker-result.schema.json",
                    instance,
                    schemas,
                    validators,
                )
                self.assertIn(expected, errors, errors)

    def test_blob_reuse_source_path_and_candidate_scan_fail_closed(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            target = root / "schemas" / "task-contract.schema.json"
            target_sha = VALIDATOR.git_blob_sha(target.read_bytes())
            with mock.patch.object(
                VALIDATOR, "SOURCE_BLOBS", set(VALIDATOR.SOURCE_BLOBS) | {target_sha}
            ):
                result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertGreater(result["source_registry_blob_reuse"], 0)

        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            source_path = next(
                entry["source_path"]
                for entry in manifest["entries"]
                if entry["decision"] == "PRIVATE_RETAIN"
            )
            license_path = root / VALIDATOR.LICENSE_PATH
            license_path.write_text(
                license_path.read_text(encoding="utf-8") + "\n" + source_path + "\n",
                encoding="utf-8",
            )
            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertGreater(result["source_path_leakage"], 0)

        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            manifest["entries"][2]["rationale"] += (
                " Contact " + "person" + "@" + "example.invalid"
            )
            self._write_manifest(root, manifest)
            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertGreater(result["candidate_scan_findings"], 0)

    def test_candidate_scan_covers_unlisted_candidate_paths(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            extra = root / "docs" / "added-candidate.txt"
            extra.parent.mkdir(parents=True)
            extra.write_text(
                "registry/" + "INDEX.md\n"
                + "C:" + chr(47) + "Users/rambo/private-source.txt\n",
                encoding="utf-8",
            )

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertGreater(result["source_path_leakage"], 0)
            self.assertGreater(result["candidate_scan_findings"], 0)
            self.assertTrue(
                any("docs/added-candidate.txt" in error for error in result["errors"]),
                result["errors"],
            )

    def test_candidate_scan_rejects_source_blob_reuse_in_unlisted_path(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            extra = root / "docs" / "copied-source.md"
            extra.parent.mkdir(parents=True)
            copied_source = b"private source bytes copied unchanged\n"
            extra.write_bytes(copied_source)
            copied_blob = VALIDATOR.git_blob_sha(copied_source)

            with mock.patch.object(
                VALIDATOR,
                "SOURCE_BLOBS",
                VALIDATOR.SOURCE_BLOBS | {copied_blob},
            ):
                result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn(
                "source registry blob copied unchanged: docs/copied-source.md",
                result["errors"],
            )
            self.assertEqual(result["source_registry_blob_reuse"], 1)

    def test_unavailable_git_scope_fails_closed_without_full_tree_fallback(self) -> None:
        errors: list[str] = []
        with mock.patch.object(
            VALIDATOR,
            "_git_candidate_paths",
            side_effect=VALIDATOR.CandidateScopeError("shallow repository"),
        ), mock.patch.object(
            VALIDATOR,
            "_filesystem_paths",
            side_effect=AssertionError("full-tree fallback forbidden"),
        ):
            paths = VALIDATOR._candidate_scan_paths(ROOT, errors)

        self.assertEqual(set(VALIDATOR.REQUIRED_PATHS), paths)
        self.assertEqual(["candidate Git scope unavailable or shallow"], errors)

    def test_repository_validation_fetches_history_for_candidate_scope(self) -> None:
        workflow = (
            ROOT / ".github" / "workflows" / "repository-validation.yml"
        ).read_text(encoding="utf-8")
        checkout = workflow.split("uses: actions/checkout@", 1)[1].split(
            "- name:", 1
        )[0]

        self.assertIn("persist-credentials: false", checkout)
        self.assertIn("fetch-depth: 0", checkout)

    def test_merge_ref_scopes_candidate_scan_to_second_parent(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        with temporary:
            repository = Path(temporary.name) / "merge-ref"
            repository.mkdir()

            def git(*arguments: str) -> str:
                completed = subprocess.run(
                    ["git", *arguments],
                    cwd=repository,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                return completed.stdout.strip()

            git("init", "--initial-branch=main")
            git("config", "core.autocrlf", "false")
            git("config", "user.name", "A019 test")
            git("config", "user.email", "a019-test@" + "example.invalid")
            git("commit", "--allow-empty", "-m", "common ancestor")
            common = git("rev-parse", "HEAD")

            base_only = repository / "base-only.txt"
            base_only.write_text(
                "C:" + chr(47) + "Users/base-only/private.txt\n",
                encoding="utf-8",
            )
            git("add", "base-only.txt")
            git("commit", "-m", "updated PR18 base")
            parent_one = git("rev-parse", "HEAD")

            git("switch", "-c", "candidate", common)
            for relative in VALIDATOR.REQUIRED_PATHS:
                destination = repository / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, destination)
            git("add", ".")
            git("commit", "-m", "A019 candidate")
            parent_two = git("rev-parse", "HEAD")

            git("switch", "main")
            git("merge", "--no-ff", "--no-edit", "candidate")
            parents = git("rev-list", "--parents", "-n", "1", "HEAD").split()

            self.assertEqual(parents[1:], [parent_one, parent_two])
            self.assertEqual(git("merge-base", parent_one, parent_two), common)
            candidate_paths = VALIDATOR._git_candidate_paths(repository)
            self.assertIsNotNone(candidate_paths)
            self.assertNotIn(Path("base-only.txt"), candidate_paths)

            result = VALIDATOR.validate(repository)

            self.assertEqual(result["status"], "PASS", result["errors"])
            self.assertEqual(result["candidate_scan_findings"], 0)

    def test_non_object_manifest_source_returns_structured_failure(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            manifest = self._manifest(root)
            manifest["source"] = []
            self._write_manifest(root, manifest)

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertIn("source fixed-point contract mismatch", result["errors"])

    def test_destination_blob_count_only_includes_verified_bytes(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            missing = root / "schemas" / "worker-result.schema.json"
            missing.unlink()

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["destination_blobs_verified"], 3)

    def test_worker_result_schema_rejects_mixed_succeeded_checks(self) -> None:
        schemas, validators = self._instance_context()
        result = copy.deepcopy(
            VALIDATOR.positive_instances()["schemas/worker-result.schema.json"]
        )
        result["checks"].append(
            {"check_id": "scope.bound", "status": "fail"}
        )

        direct_errors = list(
            validators["schemas/worker-result.schema.json"].iter_errors(result)
        )

        self.assertTrue(direct_errors)

    def test_malformed_schema_returns_structured_failure(self) -> None:
        mutations = (
            lambda schema: schema.__setitem__("$id", []),
            lambda schema: schema.__setitem__("$schema", []),
            lambda schema: schema.__setitem__("properties", []),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                temporary, root = self._fixture()
                with temporary:
                    schema_path = root / "schemas" / "task-contract.schema.json"
                    schema = json.loads(schema_path.read_text(encoding="utf-8"))
                    mutate(schema)
                    schema_path.write_text(
                        json.dumps(schema), encoding="utf-8"
                    )

                    result = VALIDATOR.validate(root)

                    self.assertEqual(result["status"], "FAIL")
                    self.assertTrue(result["errors"], result)

    def test_schema_invalid_types_are_structured_semantic_failures(self) -> None:
        schemas, validators = self._instance_context()
        cases = (
            ("schemas/task-contract.schema.json", "scope", []),
            ("schemas/worker-capability-catalog.schema.json", "workers", None),
        )
        for schema_path, field, value in cases:
            with self.subTest(schema_path=schema_path, field=field):
                instance = copy.deepcopy(VALIDATOR.positive_instances()[schema_path])
                instance[field] = value

                errors = VALIDATOR.validate_instance(
                    schema_path,
                    instance,
                    schemas,
                    validators,
                )

                self.assertTrue(errors)
                self.assertTrue(
                    any("semantic validation failed closed" in error for error in errors),
                    errors,
                )

    def test_license_scope_destination_binding_and_gates_fail_closed(self) -> None:
        mutations = (
            lambda manifest: manifest["component_license"].__setitem__(
                "source_derived_scope", ["schemas/**"]
            ),
            lambda manifest: manifest["destination_contract"][0].__setitem__(
                "blob_sha", "0" * 40
            ),
            lambda manifest: manifest["admission_gates"].__setitem__(
                "license_and_provenance", "PASS"
            ),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                temporary, root = self._fixture()
                with temporary:
                    manifest = self._manifest(root)
                    mutate(manifest)
                    self._write_manifest(root, manifest)
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertEqual(result["admission_status"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
