import copy
import json
import unittest
from tools.record_python_candidate_execution import bind, REPOSITORY, WORKFLOW


class PythonExecutionTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.dumps({"kind": "kotodama/python-candidate-build/v1", "status": "BUILT_NOT_RELEASED",
            "source_commit": "a" * 40, "source_tree": "b" * 40, "builder_inputs": {"builder.py": "c" * 64}}).encode()
        self.context = {"repository": REPOSITORY, "sha": "a" * 40, "ref": "refs/pull/1/merge",
            "workflow_ref": f"{REPOSITORY}/{WORKFLOW}@refs/pull/1/merge", "workflow_sha": "d" * 40,
            "run_id": 1, "run_attempt": 2, "job_name": "Build Python candidate (ubuntu-24.04)",
            "artifact_id": 3, "artifact_name": "python-candidate-ubuntu-24.04", "artifact_digest": "e" * 64}
        self.run = {"id": 1, "run_attempt": 2, "path": WORKFLOW, "repository": {"full_name": REPOSITORY}, "head_sha": "f" * 40}
        self.jobs = {"total_count": 1, "jobs": [{"id": 4, "run_id": 1, "run_attempt": 2, "name": self.context["job_name"]}]}
        self.artifact = {"id": 3, "name": self.context["artifact_name"], "workflow_run": {"id": 1, "head_sha": "f" * 40},
                         "expired": False, "digest": "sha256:" + "e" * 64}

    def test_merge_source_and_event_head_are_distinct_without_claiming_signature(self):
        result = bind(self.raw, self.context, self.run, self.jobs, self.artifact)
        self.assertEqual(result["source_commit"], "a" * 40)
        self.assertEqual(result["event_head_sha"], "f" * 40)
        self.assertEqual(result["job_id"], 4)
        self.assertFalse(result["signature_verified"])
        self.assertFalse(result["release_authorized"])

    def test_wrong_source_repository_workflow_attempt_and_artifact_are_refused(self):
        mutations = [
            lambda c,r,j,a: c.update(sha="b" * 40),
            lambda c,r,j,a: r["repository"].update(full_name="other/repository"),
            lambda c,r,j,a: r.update(path="other.yml"),
            lambda c,r,j,a: r.update(run_attempt=1),
            lambda c,r,j,a: j["jobs"].append(dict(j["jobs"][0])),
            lambda c,r,j,a: j["jobs"][0].update(run_attempt=1),
            lambda c,r,j,a: a.update(id=2),
            lambda c,r,j,a: a.update(expired=True),
            lambda c,r,j,a: a.update(digest="sha256:" + "0" * 64),
            lambda c,r,j,a: a["workflow_run"].update(id=2),
        ]
        for mutate in mutations:
            args = copy.deepcopy([self.context, self.run, self.jobs, self.artifact]); mutate(*args)
            with self.assertRaises(ValueError):
                bind(self.raw, *args)


if __name__ == "__main__":
    unittest.main()
