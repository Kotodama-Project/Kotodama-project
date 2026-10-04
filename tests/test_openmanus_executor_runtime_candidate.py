import copy
import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "executor-runtime-candidate.schema.json"
CANDIDATE_PATH = ROOT / "examples" / "executor-runtime" / "openmanus-proxmox.json"


class OpenManusExecutorRuntimeCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        cls.candidate = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))

    def test_schema_is_valid_draft_2020_12(self) -> None:
        Draft202012Validator.check_schema(self.schema)

    def test_candidate_matches_schema(self) -> None:
        validator = Draft202012Validator(self.schema)
        errors = sorted(validator.iter_errors(self.candidate), key=lambda error: list(error.path))
        self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def test_upstream_revision_is_commit_pinned(self) -> None:
        revision = self.candidate["upstream"]["revision"]
        self.assertRegex(revision, re.compile(r"^[0-9a-f]{40}$"))

    def test_worker_has_no_canonical_or_management_plane_authority(self) -> None:
        role = self.candidate["kotodama_role"]
        runtime = self.candidate["runtime"]
        result = self.candidate["result_contract"]

        self.assertEqual("kotodama", role["canonical_authority"])
        self.assertFalse(role["may_promote_current_truth"])
        self.assertFalse(role["may_modify_capability_grants"])
        self.assertEqual("deny", runtime["management_plane_access"])
        self.assertEqual("task_scoped_only", runtime["shared_filesystem"])
        self.assertFalse(result["completion_is_promotion"])

    def test_initial_candidate_is_single_concurrency_and_zero_breach(self) -> None:
        self.assertEqual(1, self.candidate["runtime"]["max_concurrency"])
        self.assertEqual(0, self.candidate["evaluation"]["authority_breaches_allowed"])

    def test_example_contains_no_embedded_secret_fields(self) -> None:
        serialized = json.dumps(self.candidate, ensure_ascii=False).lower()
        for forbidden in ('"api_key"', '"password"', '"token"', '"secret"'):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)


def load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_executor_runtime_candidate",
        ROOT / "tools" / "validate_executor_runtime_candidate.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ExecutorRuntimeValidatorTest(unittest.TestCase):
    """The CLI refuses candidates that the schema alone used to accept."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = load_validator()
        cls.candidate = json.loads(CANDIDATE_PATH.read_text(encoding="utf-8"))

    def errors_for(self, candidate: object | None = None, raw: bytes | None = None) -> list[str]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            path.write_bytes(raw if raw is not None else json.dumps(candidate).encode("utf-8"))
            return self.validator.validate(path)

    def test_checked_in_example_passes(self) -> None:
        self.assertEqual([], self.validator.validate(CANDIDATE_PATH))

    def test_every_authority_binding_and_output_is_required(self) -> None:
        for field, key in (
            ("request_contract", "required_bindings"),
            ("result_contract", "required_outputs"),
        ):
            for replacement in (self.candidate[field][key][1:], ["a", "b", "c", "d", "e", "f"]):
                with self.subTest(field=field, replacement=replacement[:2]):
                    candidate = copy.deepcopy(self.candidate)
                    candidate[field][key] = replacement
                    self.assertTrue(self.errors_for(candidate))

    def test_whitespace_only_metadata_is_refused(self) -> None:
        for key in ("entrypoint", "license", "browser_runtime"):
            with self.subTest(key=key):
                candidate = copy.deepcopy(self.candidate)
                candidate["upstream"][key] = " \t"
                self.assertTrue(self.errors_for(candidate))

    def test_secret_in_an_allowed_string_field_is_refused_without_echo(self) -> None:
        # Built at runtime so the tracked-secret scan of this file stays clean.
        token = "gh" + "p_" + "A" * 36
        candidate = copy.deepcopy(self.candidate)
        candidate["upstream"]["entrypoint"] = f"run --token {token}"
        errors = self.errors_for(candidate)
        self.assertTrue(any("secret-like value" in error for error in errors), errors)
        self.assertFalse(any(token in error for error in errors))

    def test_invalid_utf8_is_a_validation_failure(self) -> None:
        errors = self.errors_for(raw=b'{"kind": "\xff"}')
        self.assertEqual(1, len(errors))
        self.assertIn("not valid UTF-8", errors[0])

    def test_rejected_schema_values_and_keys_are_not_reflected_by_cli(self) -> None:
        marker = "private-synthetic-input-marker"
        candidates = []
        for field, key in (("upstream", "revision"), ("runtime", "management_plane_access")):
            candidate = copy.deepcopy(self.candidate)
            candidate[field][key] = marker
            candidates.append(candidate)
        candidate = copy.deepcopy(self.candidate)
        candidate[marker] = marker
        candidates.append(candidate)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"{marker}.json"
            for candidate in candidates:
                with self.subTest(candidate=list(candidate)):
                    path.write_text(json.dumps(candidate), encoding="utf-8")
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "tools/validate_executor_runtime_candidate.py"), str(path)],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertIn("schema validation failed", result.stdout)
                    self.assertEqual(result.stderr, "")
                    self.assertNotIn(marker, result.stdout + result.stderr)
                    self.assertNotIn(str(path), result.stdout + result.stderr)

    def test_read_parse_and_usage_failures_do_not_reflect_input(self) -> None:
        marker = "private-synthetic-input-marker"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / f"{marker}.json"
            for raw in (
                b'"\xff"', f'{{"{marker}": 1, "{marker}": 2}}'.encode(),
                b'{"incomplete":', b'[' * 50_000,
                b'{"owned-number":' + b'1' * 5_000 + b'}',
            ):
                with self.subTest(raw_kind=raw[:10]):
                    path.write_bytes(raw)
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "tools/validate_executor_runtime_candidate.py"), str(path)],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(result.returncode, 1)
                    self.assertEqual(result.stderr, "")
                    self.assertNotIn(marker, result.stdout)
                    self.assertNotIn(str(path), result.stdout)
            path.unlink()
            for arguments, expected_status in (([str(path)], 1), (["--unknown", marker], 2)):
                with self.subTest(status=expected_status):
                    result = subprocess.run(
                        [sys.executable, str(ROOT / "tools/validate_executor_runtime_candidate.py"), *arguments],
                        capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(result.returncode, expected_status)
                    self.assertNotIn(marker, result.stdout + result.stderr)
                    self.assertNotIn(str(path), result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
