"""Project observations preserve existing owner bindings and never apply edits."""
import copy
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import project_hub as hub


def fixture(now=1000):
    payload = {"version": 1, "task_id": "task-00000000-0000-4000-8000-000000000001",
               "revision": 2, "request": "イベントを企画する", "acceptance": ["会場候補を比較する"],
               "sources": [{"key": "a" * 64, "revision": 1, "text": "元の依頼",
                            "sha256": hashlib.sha256("元の依頼".encode()).hexdigest()}]}
    binding = {"task_id": payload["task_id"], "revision": 2, "context_digest": hub.digest(payload),
               "owner_ref": "ref/owner/task", "active_home": "fixture",
               "authority_ref": "ref/authority/fixture", "capability_ref": "ref/capability/swarm_research",
               "expires_at": now + 600, "status": "active"}
    project = {"version": 1, "project_id": "project-event", "revision": 1,
               "owner_ref": "ref/owner/project", "original_ref": "ref/source/original/1", "name": "企画",
               "brief": {"outcome": "小さなイベントを実現する", "in_scope": ["調査"],
                         "out_of_scope": ["予約"], "constraints": ["費用上限を守る"],
                         "acceptance": ["候補を比較する"], "unknowns": ["参加人数"]},
               "task_refs": [{k: binding[k] for k in ("task_id", "owner_ref", "revision", "context_digest")}]}
    return project, binding, payload


class ProjectHubTests(unittest.TestCase):
    def test_final_reread_distinguishes_boolean_from_integer_revision(self):
        project, _, _ = fixture()
        project["task_refs"] = []
        changed = {**project, "revision": True}
        output = io.StringIO()
        with patch.object(hub, "load_json", side_effect=[project, changed]), contextlib.redirect_stdout(output):
            status = hub.main(["view", "--project", "fixture.json"])
        self.assertEqual(1, status)
        self.assertEqual("PROJECT_CHANGED_DURING_READ", json.loads(output.getvalue())["reason_code"])

    def test_view_retains_intent_and_references_without_creating_completion(self):
        project, binding, payload = fixture()
        before = copy.deepcopy((project, binding, payload))
        result = hub.project_view(project, lambda _: (binding, payload), now=1000)
        self.assertEqual(0, result["unresolved_count"])
        self.assertEqual("元の依頼", payload["sources"][0]["text"])
        self.assertNotIn("text", result["tasks"][0]["source_refs"][0])
        self.assertEqual("not_observed", result["completion"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(before, (project, binding, payload))

    def test_stale_cancelled_expired_and_wrong_owner_do_not_expose_task_content(self):
        for field, value, code in (("status", "cancelled", "INACTIVE_TASK"),
                                   ("expires_at", 999, "EXPIRED_BINDING"),
                                   ("owner_ref", "ref/owner/other", "PROJECT_OWNER_MISMATCH"),
                                   ("context_digest", "b" * 64, "TASK_CONTEXT_MISMATCH"),
                                   ("revision", 3, "STALE_BINDING")):
            with self.subTest(field=field):
                project, binding, payload = fixture()
                binding[field] = value
                row = hub.project_view(project, lambda _: (binding, payload), now=1000)["tasks"][0]
                self.assertEqual(code, row["reason_code"])
                self.assertNotIn("request", row)

    def test_updated_owner_requires_project_reference_refresh(self):
        project, binding, payload = fixture()
        payload["revision"] = binding["revision"] = 3
        binding["context_digest"] = hub.digest(payload)
        row = hub.project_view(project, lambda _: (binding, payload), now=1000)["tasks"][0]
        self.assertEqual("PROJECT_TASK_STALE", row["reason_code"])

    def test_owner_change_between_reads_invalidates_observation(self):
        project, binding, payload = fixture()
        calls = []

        def resolve(_):
            calls.append(1)
            return ({**binding, "authority_ref": "ref/authority/new"} if len(calls) == 2 else binding), payload

        row = hub.project_view(project, resolve, now=1000)["tasks"][0]
        self.assertEqual("PROJECT_TASK_CHANGED", row["reason_code"])
        self.assertNotIn("request", row)

    def test_v2_original_correction_constraints_and_unknowns_survive_projection(self):
        project, binding, payload = fixture()
        original = payload["sources"][0]
        current_text = "イベントを企画する\n予約しない\n人数不明\n会場候補を比較する\nOUT-EVENT"
        current = {"key": "a" * 64, "revision": 2, "text": current_text,
                   "sha256": hashlib.sha256(current_text.encode()).hexdigest()}

        def span(source, text):
            start = source["text"].index(text)
            return {"source_key": source["key"], "source_revision": source["revision"],
                    "start": start, "end": start + len(text)}

        payload.update(version=2, sources=[original, current], objective={
            "owner_ref": binding["owner_ref"],
            "intent": {"original": span(original, original["text"]),
                       "replacements": [span(current, payload["request"])]},
            "references": [{"kind": "goal", "id": "OUT-EVENT", "source": span(current, "OUT-EVENT")}],
            "constraints": [span(current, "予約しない")], "unknowns": [span(current, "人数不明")],
            "acceptance": [span(current, payload["acceptance"][0])],
            "budget": {"attempt_budget": 4, "deadline": 1100},
            "stop_conditions": ["cancelled", "binding_changed", "deadline_exceeded"],
            "rollback": "not_applicable_read_only"})
        binding["context_digest"] = hub.digest(payload)
        project["task_refs"][0]["context_digest"] = hub.digest(payload)
        row = hub.project_view(project, lambda _: (binding, payload), now=1000)["tasks"][0]
        self.assertEqual("resolved", row["resolution"])
        self.assertEqual(payload["objective"], row["objective"])

    def proposal(self, project):
        brief = copy.deepcopy(project["brief"])
        brief["acceptance"] = ["新しい条件"]
        return {"version": 1, "project_id": project["project_id"], "expected_revision": project["revision"],
                "base_digest": hub.digest(project), "reason": "追加情報による訂正案",
                "source_ref": "ref/source/correction/2", "brief": brief}

    def test_change_reports_removed_conditions_and_all_impacted_tasks_without_applying(self):
        project, _, _ = fixture()
        before = copy.deepcopy(project)
        result = hub.inspect_change(project, self.proposal(project))
        self.assertFalse(result["applied"])
        self.assertEqual(["候補を比較する"], result["removed_requirements"]["acceptance"])
        self.assertEqual(project["task_refs"], result["impact_task_refs"])
        self.assertEqual(before, project)

    def test_stale_change_and_same_revision_different_base_refused(self):
        project, _, _ = fixture()
        for field, value, code in (("expected_revision", 2, "PROJECT_REVISION_STALE"),
                                   ("expected_revision", True, "INVALID_LIMIT"),
                                   ("base_digest", "a" * 64, "PROJECT_BASE_MISMATCH"),
                                   ("project_id", "other", "PROJECT_ID_MISMATCH")):
            proposal = self.proposal(project)
            proposal[field] = value
            with self.subTest(field=field), self.assertRaises(hub.SwarmError) as caught:
                hub.inspect_change(project, proposal)
            self.assertEqual(code, caught.exception.code)

    def test_invalid_brief_and_duplicate_task_refs_refused(self):
        project, _, _ = fixture()
        for change in ({"revision": True}, {"task_refs": project["task_refs"] * 2},
                       {"grant": "new"}, {"brief": {**project["brief"], "acceptance": "unknown"}}):
            with self.subTest(change=change), self.assertRaises(hub.SwarmError):
                hub.validate_project({**project, **change})

    def test_cli_reads_real_owner_and_detects_cancellation_without_writes(self):
        project, binding, payload = fixture(time.time())
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            owner = {"binding": binding, "actors": {"reader": {"epoch": 1,
                     "invocation_ref": "ref/invocation/reader", "actor_status": "active",
                     "capability_ref": "ref/capability/read", "peers": []}},
                     "storage": {"root": str(root / "storage"), "mailbox": "mailbox.sqlite", "payloads": "payloads"},
                     "source_checks": [], "allowed_actions": []}
            for name, value in (("project", project), ("input", payload), ("owner", owner)):
                (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            command = [sys.executable, "-B", str(ROOT / "tools/project_hub.py"), "view",
                       "--project", str(root / "project.json"), "--task", payload["task_id"],
                       str(root / "owner.json"), str(root / "input.json")]
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            run = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual("resolved", json.loads(run.stdout)["tasks"][0]["resolution"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            owner["binding"]["status"] = "cancelled"
            (root / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
            run = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertEqual("INACTIVE_TASK", json.loads(run.stdout)["tasks"][0]["reason_code"])
            missing = subprocess.run(command[:-4], capture_output=True, text=True, check=True)
            self.assertEqual("PROJECT_OWNER_UNSELECTED", json.loads(missing.stdout)["tasks"][0]["reason_code"])
            owner["binding"]["status"] = "active"
            other_owner = copy.deepcopy(owner)
            other_input = copy.deepcopy(payload)
            other_id = "task-00000000-0000-4000-8000-000000000002"
            other_input["task_id"] = other_owner["binding"]["task_id"] = other_id
            other_owner["binding"]["context_digest"] = hub.digest(other_input)
            project["task_refs"].append({k: other_owner["binding"][k] for k in
                                        ("task_id", "revision", "owner_ref", "context_digest")})
            (root / "project.json").write_text(json.dumps(project), encoding="utf-8")
            (root / "other-owner.json").write_text(json.dumps(other_owner), encoding="utf-8")
            (root / "other-input.json").write_text(json.dumps(other_input), encoding="utf-8")
            owner["actors"]["reader"]["actor_status"] = []
            (root / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
            run = subprocess.run(command + ["--task", other_id, str(root / "other-owner.json"),
                                            str(root / "other-input.json")],
                                 capture_output=True, text=True, check=True)
            result = json.loads(run.stdout)
            self.assertEqual("PROJECT_OWNER_INVALID", result["tasks"][0]["reason_code"])
            self.assertEqual("resolved", result["tasks"][1]["resolution"])
            self.assertEqual("", run.stderr)

    def test_cli_change_candidate_and_duplicate_json_key(self):
        project, _, _ = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "project.json"
            proposal = root / "change.json"
            base.write_text(json.dumps(project), encoding="utf-8")
            proposal.write_text(json.dumps(self.proposal(project)), encoding="utf-8")
            before = {p.name: p.read_bytes() for p in root.iterdir()}
            command = [sys.executable, "-B", str(ROOT / "tools/project_hub.py"), "inspect-change",
                       "--project", str(base), "--proposal", str(proposal)]
            run = subprocess.run(command, capture_output=True, text=True, check=True)
            self.assertFalse(json.loads(run.stdout)["applied"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})
            proposal.write_text('{"version": 1, "version": 2}', encoding="utf-8")
            run = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(1, run.returncode)
            self.assertEqual("REFUSED", json.loads(run.stdout)["status"])
            self.assertEqual("", run.stderr)


if __name__ == "__main__":
    unittest.main()
