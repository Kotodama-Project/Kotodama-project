from __future__ import annotations

import copy
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
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

    def test_fixed_metadata_rejects_unknown_fields_at_every_object(self) -> None:
        def object_paths(value, path=()):
            if isinstance(value, dict):
                yield path
                for key, child in value.items():
                    yield from object_paths(child, (*path, key))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from object_paths(child, (*path, index))

        for relative in (VALIDATOR.MANIFEST_PATH, VALIDATOR.PROVENANCE_PATH):
            original = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            for pointer in object_paths(original):
                with self.subTest(file=relative.name, object=pointer):
                    temporary, root = self._fixture()
                    with temporary:
                        document = copy.deepcopy(original)
                        target = document
                        for part in pointer:
                            target = target[part]
                        target["source_body"] = "ordinary fixture prose"
                        (root / relative).write_text(json.dumps(document), encoding="utf-8")
                        result = VALIDATOR.validate(root)
                        self.assertEqual(result["status"], "FAIL")
                        self.assertEqual(result["admission_status"], "BLOCKED")
                        self.assertTrue(any("metadata differs" in error for error in result["errors"]))

        for key in VALIDATOR.MANIFEST_KEYS:
            with self.subTest(missing_manifest_key=key):
                temporary, root = self._fixture()
                with temporary:
                    manifest = self._manifest(root)
                    manifest.pop(key)
                    self._write_manifest(root, manifest)
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertIn("manifest fields must match the public record exactly", result["errors"])

    def test_fixed_provenance_history_values_and_types_reject_drift(self) -> None:
        mutations = {
            "commits_touching_source": (1, True, 3.0),
            "withheld_author_identities": (2, True, 1.0),
            "author_github_handles": (["fixture-reviewer"],),
        }
        for index in range(4):
            for field, values in mutations.items():
                for value in values:
                    with self.subTest(row=index, field=field, value_type=type(value).__name__):
                        temporary, root = self._fixture()
                        with temporary:
                            path = root / VALIDATOR.PROVENANCE_PATH
                            provenance = json.loads(path.read_text(encoding="utf-8"))
                            provenance["entries"][index][field] = value
                            path.write_text(json.dumps(provenance), encoding="utf-8")
                            result = VALIDATOR.validate(root)
                            self.assertEqual(result["status"], "FAIL")
                            self.assertEqual(result["admission_status"], "BLOCKED")
                            self.assertIn("provenance metadata differs from the fixed public record", result["errors"])
        temporary, root = self._fixture()
        with temporary:
            path = root / VALIDATOR.PROVENANCE_PATH
            provenance = json.loads(path.read_text(encoding="utf-8"))
            provenance["private_source_history_result"] = "PASS"
            path.write_text(json.dumps(provenance), encoding="utf-8")
            self.assertIn(
                "provenance metadata differs from the fixed public record",
                VALIDATOR.validate(root)["errors"],
            )

    def test_fixed_metadata_allows_formatting_and_only_known_review_states(self) -> None:
        for state in ("PENDING", "PASSED_INDEPENDENT_REVIEW"):
            with self.subTest(state=state):
                temporary, root = self._fixture()
                with temporary:
                    for relative in (VALIDATOR.MANIFEST_PATH, VALIDATOR.PROVENANCE_PATH):
                        path = root / relative
                        document = json.loads(path.read_text(encoding="utf-8"))
                        if relative == VALIDATOR.MANIFEST_PATH:
                            document["admission_gates"]["independent_review"] = state
                        path.write_text(json.dumps(dict(reversed(list(document.items()))), indent=4), encoding="utf-8")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "PASS", result["errors"])
                    self.assertEqual(result["admission_status"], "ADMITTED" if state == "PASSED_INDEPENDENT_REVIEW" else "BLOCKED")

    def test_metadata_duplicate_root_and_nested_keys_are_rejected(self) -> None:
        for relative in (VALIDATOR.MANIFEST_PATH, VALIDATOR.PROVENANCE_PATH):
            original = json.loads((ROOT / relative).read_text(encoding="utf-8"))
            encoded = json.dumps(original)
            root_duplicate = '{"schema_version":"ordinary fixture prose",' + encoded[1:]
            if relative == VALIDATOR.MANIFEST_PATH:
                nested_duplicate = encoded.replace('"source": {', '"source": {"fixed_commit":"ordinary fixture prose",', 1)
            else:
                nested_duplicate = encoded.replace('"entries": [{', '"entries": [{"decision":"ordinary fixture prose",', 1)
            for label, mutated in (("root", root_duplicate), ("nested", nested_duplicate)):
                with self.subTest(file=relative.name, position=label):
                    # A permissive last-wins decoder would hide this added text.
                    self.assertEqual(json.loads(mutated), original)
                    temporary, root = self._fixture()
                    with temporary:
                        (root / relative).write_text(mutated, encoding="utf-8")
                        result = VALIDATOR.validate(root)
                        self.assertEqual(result["status"], "FAIL")
                        self.assertEqual(result["admission_status"], "BLOCKED")
                        self.assertTrue(any("JSON" in error for error in result["errors"]))

    def test_metadata_nonfinite_values_are_rejected(self) -> None:
        for relative in (VALIDATOR.MANIFEST_PATH, VALIDATOR.PROVENANCE_PATH):
            encoded = (ROOT / relative).read_text(encoding="utf-8")
            for token in ("NaN", "Infinity", "-Infinity", "1e999"):
                with self.subTest(file=relative.name, token=token):
                    temporary, root = self._fixture()
                    with temporary:
                        changed = '{"fixture_number":' + token + ',' + encoded.lstrip()[1:]
                        (root / relative).write_text(changed, encoding="utf-8")
                        result = VALIDATOR.validate(root)
                        self.assertEqual(result["status"], "FAIL")
                        self.assertTrue(any("JSON" in error for error in result["errors"]))

    def test_malformed_review_states_return_structured_failure(self) -> None:
        for state in ("APPROVED", [], {}, None, True):
            with self.subTest(state_type=type(state).__name__):
                temporary, root = self._fixture()
                with temporary:
                    manifest = self._manifest(root)
                    manifest["admission_gates"]["independent_review"] = state
                    self._write_manifest(root, manifest)
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertEqual(result["admission_status"], "BLOCKED")
                    self.assertIn("independent review gate must be PENDING or PASSED_INDEPENDENT_REVIEW", result["errors"])

    def test_candidate_scan_rejects_normal_and_escaped_windows_user_paths(self) -> None:
        synthetic = "C:" + chr(92) + "Users" + chr(92) + "fixture-user" + chr(92) + "record.txt"
        representations = (synthetic, json.dumps(synthetic), repr(synthetic), json.dumps(json.dumps(synthetic)))
        for relative in (Path("tests/test_migration_batch_a019.py"), Path("tools/validate_migration_batch_a019.py")):
            for index, text in enumerate(representations):
                with self.subTest(file=relative.name, representation=index):
                    temporary, root = self._fixture()
                    with temporary:
                        path = root / relative
                        path.write_text(path.read_text(encoding="utf-8") + "\n# " + text + "\n", encoding="utf-8")
                        result = VALIDATOR.validate(root)
                        self.assertEqual(result["status"], "FAIL")
                        self.assertEqual(result["admission_status"], "BLOCKED")
                        self.assertTrue(any(
                            error.startswith("candidate scan finding absolute_user_path: ")
                            and relative.as_posix() in error for error in result["errors"]
                        ))

    def test_exact_candidate_passes_and_reports_the_recorded_admission(self) -> None:
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
        self.assertEqual(
            manifest["component_license"]["source_derived_scope"],
            sorted(VALIDATOR.DESTINATIONS),
        )
        if manifest["admission_gates"]["independent_review"] == "PASSED_INDEPENDENT_REVIEW":
            self.assertEqual(result["admission_status"], "ADMITTED")
            self.assertEqual(result["no_go_reasons"], [])
        else:
            self.assertEqual(result["admission_status"], "BLOCKED")
            self.assertEqual(result["no_go_reasons"], ["INDEPENDENT_REVIEW_PENDING"])

    def test_admission_gates_and_provenance_fail_closed(self) -> None:
        def gate(value):
            return lambda manifest, provenance: manifest["admission_gates"].update(value)

        def prov(update):
            return lambda manifest, provenance: update(provenance)

        mutations = {
            "issue 25 gate reopened": gate({"license_and_provenance": "BLOCKED_ISSUE_25"}),
            "sibling integration reopened": gate({"sibling_integration": "BLOCKED_ISSUE_30"}),
            "unknown review state": gate({"independent_review": "APPROVED"}),
            "receipt digest removed": prov(lambda p: p.pop("private_source_history_receipt_sha256")),
            "receipt did not pass": prov(lambda p: p.update(private_source_history_result="FINDINGS")),
            "author is not a handle": prov(lambda p: p["entries"][0].update(author_github_handles=["Some Person"])),
            "row names no author": prov(
                lambda p: p["entries"][0].update(author_github_handles=[], withheld_author_identities=0)
            ),
            "re-authored source missing": prov(lambda p: p["entries"].pop()),
            "source blob drift": prov(lambda p: p["entries"][0].update(source_blob_sha="0" * 40)),
            # The path is read from the manifest so this file never names it.
            "source path repeated": lambda manifest, provenance: provenance["entries"][0].update(
                source_path=manifest["entries"][0]["source_path"]
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture()
                with temporary:
                    manifest = self._manifest(root)
                    provenance_path = root / VALIDATOR.PROVENANCE_PATH
                    provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
                    mutate(manifest, provenance)
                    self._write_manifest(root, manifest)
                    provenance_path.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL", label)
                    self.assertEqual(result["admission_status"], "BLOCKED", label)
                    self.assertIn("VALIDATION_FAILED", result["no_go_reasons"], label)

    def test_provenance_shape_and_fixed_metadata_fail_closed(self) -> None:
        mutations = {
            "extra root field": lambda p: p.update(source_body="ordinary fixture prose"),
            "extra row field": lambda p: p["entries"][0].update(source_body="ordinary fixture prose"),
            "missing root field": lambda p: p.pop("entry_scope"),
            "missing row field": lambda p: p["entries"][0].pop("decision"),
            "changed identity policy": lambda p: p.update(author_identity_policy="ordinary fixture prose"),
            "changed entry scope": lambda p: p.update(entry_scope="ordinary fixture prose"),
            "changed decision": lambda p: p["entries"][0].update(decision="PRIVATE_RETAIN"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                temporary, root = self._fixture()
                with temporary:
                    path = root / VALIDATOR.PROVENANCE_PATH
                    provenance = json.loads(path.read_text(encoding="utf-8"))
                    mutate(provenance)
                    path.write_text(json.dumps(provenance), encoding="utf-8")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL", result["errors"])
                    self.assertEqual(result["admission_status"], "BLOCKED")
                    self.assertTrue(any("provenance" in error for error in result["errors"]))

    def test_private_receipt_digest_is_bound_to_the_public_record(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            path = root / VALIDATOR.PROVENANCE_PATH
            provenance = json.loads(path.read_text(encoding="utf-8"))
            provenance["private_source_history_receipt_sha256"] = "0" * 64
            path.write_text(json.dumps(provenance), encoding="utf-8")
            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["admission_status"], "BLOCKED")
            self.assertIn(
                "provenance must bind the private source-history receipt digest",
                result["errors"],
            )

    def test_oversized_file_is_refused_before_open(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("fixture.json")
            (root / relative).write_bytes(b"x" * 9)
            errors: list[str] = []
            with mock.patch.object(VALIDATOR, "MAX_FILE_BYTES", 8), mock.patch.object(
                VALIDATOR.os, "open", side_effect=AssertionError("oversized file opened")
            ):
                self.assertIsNone(VALIDATOR._read_bounded(root, relative, errors))
            self.assertEqual(errors, ["file exceeds 8 bytes: fixture.json"])

    def test_read_limit_accepts_boundary_and_refuses_growth(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("fixture.json")
            (root / relative).write_bytes(b"x" * 8)
            original_fdopen = VALIDATOR.os.fdopen
            for grew in (False, True):
                with self.subTest(grew=grew):
                    reads = []

                    @contextmanager
                    def observed_open(fd, mode):
                        with original_fdopen(fd, mode) as stream:
                            proxy = mock.Mock(wraps=stream)

                            def bounded_read(size):
                                reads.append(size)
                                self.assertEqual(size, 9)
                                return b"x" * 9 if grew else stream.read(size)

                            proxy.read.side_effect = bounded_read
                            yield proxy

                    errors: list[str] = []
                    with mock.patch.object(VALIDATOR, "MAX_FILE_BYTES", 8), mock.patch.object(
                        VALIDATOR.os, "fdopen", side_effect=observed_open
                    ):
                        data = VALIDATOR._read_bounded(root, relative, errors)
                    self.assertEqual(reads, [9])
                    self.assertEqual(data, None if grew else b"x" * 8)
                    self.assertEqual(errors, ["file exceeds 8 bytes: fixture.json"] if grew else [])

    def test_reparse_parent_and_leaf_are_refused_before_open(self) -> None:
        # Portable metadata fixture; real Windows junction behavior belongs to CI.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            relative = Path("nested/fixture.json")
            (root / relative).parent.mkdir()
            (root / relative).write_bytes(b"{}")
            original_lstat = Path.lstat
            for target in ((root / relative).parent, root / relative):
                for attributes, tag in ((0x400, 0), (0, 0xA0000003)):
                    with self.subTest(target=target.name, attributes=attributes, tag=tag):
                        def reparse_lstat(path, *args, **kwargs):
                            info = original_lstat(path, *args, **kwargs)
                            if path == target:
                                return SimpleNamespace(
                                    st_mode=info.st_mode, st_dev=info.st_dev,
                                    st_ino=info.st_ino, st_size=info.st_size,
                                    st_file_attributes=attributes, st_reparse_tag=tag,
                                )
                            return info

                        errors: list[str] = []
                        with mock.patch.object(Path, "lstat", reparse_lstat), mock.patch.object(
                            VALIDATOR.os, "open", side_effect=AssertionError("reparse path opened")
                        ):
                            self.assertIsNone(VALIDATOR._read_bounded(root, relative, errors))
                        self.assertEqual(errors, ["reparse point is not allowed: nested/fixture.json"])

    def test_resolved_candidate_must_stay_inside_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            relative = Path("fixture.json")
            candidate = root / relative
            candidate.write_bytes(b"{}")
            original_resolve = Path.resolve

            def escaped_resolution(path, *args, **kwargs):
                if path == candidate:
                    return root.parent / "outside-fixture.json"
                return original_resolve(path, *args, **kwargs)

            errors: list[str] = []
            with mock.patch.object(Path, "resolve", escaped_resolution), mock.patch.object(
                VALIDATOR.os, "open", side_effect=AssertionError("escaping path opened")
            ):
                self.assertIsNone(VALIDATOR._read_bounded(root, relative, errors))
            self.assertEqual(errors, ["missing, escaping, or unreadable path: fixture.json"])

    def test_required_file_symlink_is_refused(self) -> None:
        for relative in (VALIDATOR.MANIFEST_PATH, Path(next(iter(VALIDATOR.DESTINATIONS)))):
            with self.subTest(path=relative):
                temporary, root = self._fixture()
                with temporary:
                    candidate = root / relative
                    target = root / "unlisted-fixture.json"
                    shutil.copy2(candidate, target)
                    candidate.unlink()
                    try:
                        candidate.symlink_to(target)
                    except OSError as error:
                        self.skipTest(f"symlink creation unavailable: {error}")
                    result = VALIDATOR.validate(root)
                    self.assertEqual(result["status"], "FAIL")
                    self.assertEqual(result["admission_status"], "BLOCKED")
                    self.assertIn(f"symlink is not allowed: {relative.as_posix()}", result["errors"])

    def test_required_parent_symlink_is_refused(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            directory = root / "schemas"
            target = root / "unlisted-fixture-directory"
            directory.rename(target)
            try:
                directory.symlink_to(target, target_is_directory=True)
            except OSError as error:
                self.skipTest(f"symlink creation unavailable: {error}")
            result = VALIDATOR.validate(root)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["admission_status"], "BLOCKED")
            for relative in VALIDATOR.DESTINATIONS:
                self.assertIn(f"symlink is not allowed: {relative}", result["errors"])

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

    def test_candidate_scan_scope_is_the_fixed_batch_file_set(self) -> None:
        # No Git history and no full-tree walk: the scope cannot grow with later changes.
        self.assertEqual(VALIDATOR._candidate_scan_paths(), set(VALIDATOR.REQUIRED_PATHS))

    def test_candidate_scan_covers_every_batch_file(self) -> None:
        temporary, root = self._fixture()
        with temporary:
            provenance_path = root / VALIDATOR.PROVENANCE_PATH
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            provenance["author_identity_policy"] += (
                " C:" + chr(47) + "Users/someone/private.txt"
            )
            provenance_path.write_text(
                json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "FAIL")
            self.assertTrue(
                any(
                    error.startswith("candidate scan finding absolute_user_path: ")
                    and VALIDATOR.PROVENANCE_PATH.as_posix() in error
                    for error in result["errors"]
                ),
                result["errors"],
            )

    def test_candidate_scan_ignores_files_outside_the_batch(self) -> None:
        # A dated CHANGELOG entry or unrelated documentation added after this
        # batch must not change its result.
        temporary, root = self._fixture()
        with temporary:
            (root / "CHANGELOG.md").write_text(
                "## [0.2.0-preview] - " + "2026" + "-09-" + "25\n", encoding="utf-8"
            )
            extra = root / "docs" / "unrelated.md"
            extra.parent.mkdir(parents=True)
            extra.write_text(
                "Contact " + "person" + "@" + "example.invalid\n", encoding="utf-8"
            )

            result = VALIDATOR.validate(root)

            self.assertEqual(result["status"], "PASS", result["errors"])
            self.assertEqual(result["candidate_scan_findings"], 0)
            self.assertEqual(
                result["admission_status"], VALIDATOR.validate(ROOT)["admission_status"]
            )

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
