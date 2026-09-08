import json
import re
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


if __name__ == "__main__":
    unittest.main()
