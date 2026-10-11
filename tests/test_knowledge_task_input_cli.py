"""Real source-checkout CLI, owner admission, child inputs and anchored replay."""
from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import datetime as dt
import io
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from tests.test_knowledge_task_input import CONSTRAINT, admit, change_declaration, reseal_seed, setup
from runtime.task_swarm.closed_loop_contract import loop_criteria
from runtime.task_swarm.protocol import SwarmError, canonical, digest

ENTRY = ROOT / "tools/knowledge_base.py"


def prepare(root, *, corrected=False):
    """An explicit fixture-owner action, with real future deadlines for the CLI."""
    setup(root, corrected=corrected)
    expiry = dt.datetime.fromtimestamp(time.time() + 86400, dt.timezone.utc).isoformat()
    for path in (root / "knowledge/synthetic").glob("*.md"):
        path.write_bytes(path.read_bytes().decode("utf-8").replace("2026-12-07T00:00:00Z", expiry).encode("utf-8"))
    bundle, seed, owner, file = setup(root, corrected=corrected)
    change_declaration(seed, root, lambda value: value["budget"].update(deadline=time.time() + 600))
    reseal_seed(seed, owner, file)
    document = json.loads(owner.read_text())
    document["binding"]["expires_at"] = time.time() + 900
    owner.write_text(json.dumps(document), encoding="utf-8")
    return seed, owner, file


def scenario(candidate, *, negative=False):
    payload, plan = candidate["payload"], candidate["supplied_plan"]
    sources = {(row["key"], row["revision"]): row["text"] for row in payload["sources"]}
    reports = {}
    for job in plan["jobs"]:
        evidence = next(location for location in job["selected_spans"]
            if sources[(location["source_key"], location["source_revision"])][location["start"]:location["end"]] == job["purpose"])
        identifier = "r0-" + job["job_id"]
        reports[identifier] = {"job_id": identifier, "summary": job["purpose"], "conflicts": [],
            "claims": [{"text": job["purpose"], "status": "supported",
                        "evidence": [{**evidence, "quote": job["purpose"]}]}]}
    references = [{"job_id": key, "claim_index": 0} for key in reports]
    validations = [{"criterion_id": key, "status": "passed", "evidence": references,
                    "gap_reason": None, "source_spans": []} for key in loop_criteria(payload)]
    if negative:
        failed = next(row for row in validations if row["criterion_id"] == "O1")
        failed.update(status="failed", evidence=[], gap_reason="The ancestor constraint is not demonstrated.",
                      source_spans=[payload["objective"]["constraints"][0]])
    return {"work": reports, "critics": {"0": {
        "parent_input_digest": digest(payload), "plan_digest": digest(plan), "round": 0,
        "report_digests": {key: digest(value) for key, value in reports.items()}, "validations": validations}},
        "repair_plan": None}


class TaskInputCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.cwd = self.root / "unrelated-cwd"
        self.cwd.mkdir()

    def command(self, operation, owner, *args, code=0):
        result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), "task-input", operation,
            "--root", str(self.root), "--owner", str(owner), *map(str, args)],
            cwd=self.cwd, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(code, result.returncode, result.stderr)
        if code == 2:
            self.assertEqual("", result.stdout)
            return json.loads(result.stderr)
        self.assertEqual("", result.stderr)
        return json.loads(result.stdout)

    def compile(self, owner, file):
        before = owner.read_bytes(), file.read_bytes()
        candidate = self.command("compile", owner, "--input", file)
        self.assertEqual(before, (owner.read_bytes(), file.read_bytes()))
        path = self.root / "candidate.json"
        path.write_text(json.dumps(candidate, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
        return candidate, path

    def run_scenario(self, candidate, path, owner, file, *, negative=False, extra=()):
        target = self.root / "scenario.json"
        target.write_text(json.dumps(scenario(candidate, negative=negative)), encoding="utf-8")
        return self.command("simulate", owner, "--candidate", path, "--input", file,
            "--simulation", target, "--worker", "worker-a", "--worker", "worker-b", *extra,
            code=3 if negative else 0)

    def inspect_inputs(self, candidate, result, owner):
        directory = owner.parent / result["receipt"]["run_id"]
        inputs = {key: json.loads((directory / (key + "-input.json")).read_text())
                  for key in result["receipt"]["dispatches"]}
        for key, value in inputs.items():
            self.assertEqual(digest(value), result["receipt"]["dispatches"][key]["delivered_input_digest"])
            self.assertEqual(digest(candidate["payload"]), value["view"]["parent_input_digest"])
            texts = [row["text"] for row in value["view"]["spans"]]
            self.assertIn(CONSTRAINT, texts)
            self.assertIn(candidate["payload"]["request"], texts)
        self.assertEqual(scenario(candidate)["work"], inputs["r0-critic"]["reports"])
        self.assertIn("O1", inputs["r0-critic"]["criteria"])
        self.assertTrue(result["receipt"]["synthetic"])
        self.assertFalse(result["receipt"]["model_runtime_verified"])
        self.assertFalse(result["receipt"]["task_state_changed"])
        return directory, inputs

    def test_compile_verify_simulate_and_exact_replay_through_isolated_cli(self):
        _, owner, file = prepare(self.root)
        candidate, path = self.compile(owner, file)
        refused = self.command("verify", owner, "--candidate", path, code=2)
        self.assertEqual("TASK_CONTEXT_MISMATCH", refused["error"])
        admit(candidate, owner, file)
        before = owner.read_bytes()
        verified = self.command("verify", owner, "--candidate", path)
        self.assertEqual("binding_verified", verified["status"])
        self.assertEqual(digest(candidate["payload"]), verified["payload_digest"])
        refused = self.command("verify", owner, "--candidate", path,
            "--as-of", "2026-10-10T00:00:00Z", code=2)
        self.assertEqual("TASK_CONTEXT_AUDIT_INSTANT_CHANGED", refused["error"])
        result = self.run_scenario(candidate, path, owner, file)
        directory, inputs = self.inspect_inputs(candidate, result, owner)
        self.assertNotEqual(inputs["r0-requirement-0"]["purpose"], inputs["r0-requirement-1"]["purpose"])
        before_execution = (directory / "execution.json").read_bytes()
        replay = self.run_scenario(candidate, path, owner, file, extra=("--receipt-sha256", result["receipt_sha256"]))
        self.assertTrue(replay["duplicate"])
        self.assertEqual(3, replay["receipt"]["budget"]["attempts_used"])
        self.assertEqual(before_execution, (directory / "execution.json").read_bytes())
        self.assertEqual(before, owner.read_bytes())
        refused = self.command("simulate", owner, "--candidate", path, "--input", file,
            "--simulation", self.root / "scenario.json", "--worker", "worker-a", "--worker", "worker-b",
            "--receipt-sha256", "0" * 64, code=2)
        self.assertEqual("RUN_REPLAY_ANCHOR_MISMATCH", refused["error"])

    def test_same_owner_correction_changes_child_inputs_and_rejects_previous_candidate(self):
        _, owner, file = prepare(self.root)
        first, path = self.compile(owner, file)
        admit(first, owner, file)
        before, old_inputs = self.inspect_inputs(first, self.run_scenario(first, path, owner, file), owner)
        _, new_owner, new_file = prepare(self.root, corrected=True)
        self.assertEqual((owner, file), (new_owner, new_file))
        second, path = self.compile(owner, file)
        admit(second, owner, file)
        old = self.root / "previous-candidate.json"
        old.write_text(json.dumps(first), encoding="utf-8")
        refused = self.command("simulate", owner, "--candidate", old, "--input", file,
            "--simulation", self.root / "scenario.json", "--worker", "worker-a", "--worker", "worker-b", code=2)
        self.assertEqual("STALE_BINDING", refused["error"])
        self.assertEqual(1, len(list(owner.parent.glob("task-run-*"))))
        result = self.run_scenario(second, path, owner, file)
        after, new_inputs = self.inspect_inputs(second, result, owner)
        self.assertNotEqual(before, after)
        for key in old_inputs:
            self.assertIn(first["payload"]["request"], [row["text"] for row in new_inputs[key]["view"]["spans"]])
            self.assertEqual(1, len(new_inputs[key]["view"]["objective"]["intent"]["replacements"]))
        self.assertEqual(old_inputs["r0-requirement-0"]["purpose"], new_inputs["r0-requirement-0"]["purpose"])
        self.assertNotEqual(old_inputs["r0-requirement-1"]["purpose"], new_inputs["r0-requirement-1"]["purpose"])

    def test_negative_critic_returns_exit_three_without_accepting_jobs(self):
        _, owner, file = prepare(self.root)
        candidate, path = self.compile(owner, file)
        admit(candidate, owner, file)
        result = self.run_scenario(candidate, path, owner, file, negative=True)
        self.assertEqual("unresolved", result["candidate"]["status"])
        self.assertFalse(result["receipt"]["review_passed"])
        self.assertIsNone(result["learning_candidate"])
        with sqlite3.connect(owner.parent / result["receipt"]["run_id"] / "execution.sqlite") as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM jobs WHERE state='accepted'").fetchone()[0])

    def test_source_and_current_clock_refusals_do_not_rewrite_owner_or_dispatch(self):
        _, owner, file = prepare(self.root)
        candidate, path = self.compile(owner, file)
        admit(candidate, owner, file)
        before = owner.read_bytes()
        (self.root / "work/REQ-0.md").write_text("changed", encoding="utf-8")
        refused = self.command("verify", owner, "--candidate", path, code=2)
        self.assertEqual("SOURCE_BINDING_INVALID", refused["error"])
        self.assertEqual(before, owner.read_bytes())
        self.assertEqual([], list(owner.parent.glob("task-run-*")))
        seed, owner, file = prepare(self.root)
        change_declaration(seed, self.root, lambda value: value["budget"].update(deadline=time.time() - 10))
        reseal_seed(seed, owner, file)
        before = owner.read_bytes()
        refused = self.command("compile", owner, "--input", file, "--as-of", "2026-10-10T00:00:00Z", code=2)
        self.assertEqual("OBJECTIVE_DEADLINE_INVALID", refused["error"])
        self.assertEqual(before, owner.read_bytes())

    def test_malformed_or_oversized_inputs_and_missing_simulation_are_refused(self):
        _, owner, file = prepare(self.root)
        candidate, path = self.compile(owner, file)
        before = owner.read_bytes()
        for content, code in (("{", "RUN_JSON_INVALID"), ("[]", "TASK_CONTEXT_CANDIDATE_INVALID"),
                              (" " * (256 * 1024 + 2), "RUN_FILE_REFUSED")):
            with self.subTest(code=code):
                path.write_text(content, encoding="utf-8")
                self.assertEqual(code, self.command("verify", owner, "--candidate", path, code=2)["error"])
                self.assertEqual(before, owner.read_bytes())
        result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), "task-input", "simulate",
            "--root", str(self.root), "--owner", str(owner), "--candidate", str(path), "--input", str(file),
            "--worker", "worker-a"], cwd=self.cwd, capture_output=True, text=True, timeout=30)
        self.assertEqual(2, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("--simulation", result.stderr)

    def test_non_object_compile_inputs_return_typed_json_without_side_effects(self):
        _, owner, file = prepare(self.root)
        malformed = self.root / "non-object-input.json"
        for label, value in (("number", 42), ("list", []), ("null", None),
                             ("false", False), ("string", "request")):
            with self.subTest(kind=label):
                malformed.write_bytes((canonical(value) + "\n").encode("utf-8"))
                before = {path.relative_to(self.root): path.read_bytes()
                          for path in self.root.rglob("*") if path.is_file()}
                result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY),
                    "task-input", "compile", "--root", str(self.root), "--owner", str(owner),
                    "--input", str(malformed)], cwd=self.cwd, capture_output=True, timeout=30)
                self.assertEqual(2, result.returncode, result.stderr.decode("utf-8"))
                self.assertEqual(b"", result.stdout)
                expected = {"error": "TASK_CONTEXT_V1_SEED_REQUIRED",
                            "message": "Task run contract refused"}
                self.assertEqual((canonical(expected) + "\n").encode("utf-8"), result.stderr)
                self.assertEqual(before, {path.relative_to(self.root): path.read_bytes()
                                         for path in self.root.rglob("*") if path.is_file()})
                self.assertEqual([], list(owner.parent.glob("task-run-*")))

    def test_direct_producer_refuses_non_object_seeds_before_owner_access(self):
        from kotodama_kb.load import load_bundle
        from kotodama_kb.task_input import compile_task_input
        _, owner, file = prepare(self.root)
        bundle = load_bundle(self.root)
        before = owner.read_bytes(), file.read_bytes()
        for label, value in (("number", 42), ("list", []), ("null", None),
                             ("false", False), ("string", "request")):
            with self.subTest(kind=label), \
                 mock.patch("kotodama_kb.task_input.OwnerFile") as owner_reader:
                with self.assertRaises(SwarmError) as caught:
                    compile_task_input(bundle, value, owner)
                self.assertEqual("TASK_CONTEXT_V1_SEED_REQUIRED", caught.exception.code)
                owner_reader.assert_not_called()
                self.assertEqual(before, (owner.read_bytes(), file.read_bytes()))

    def test_historical_audit_cannot_waive_context_expiry_or_shorten_owner_budget(self):
        seed, owner, file = prepare(self.root)
        for seconds, expected in ((-10, "TASK_CONTEXT_EXPIRED"), (60, "TASK_CONTEXT_DEADLINE_EXCEEDS_CONTEXT")):
            with self.subTest(seconds=seconds):
                audit = dt.datetime.fromtimestamp(time.time() - 20, dt.timezone.utc).isoformat()
                expiry = dt.datetime.fromtimestamp(time.time() + seconds, dt.timezone.utc).isoformat()
                for path in (self.root / "knowledge/synthetic").glob("*.md"):
                    previous = path.read_bytes().decode("utf-8")
                    current = re.sub(r"(?m)^stale_after:.*$", "stale_after: '" + expiry + "'", previous)
                    path.write_bytes(current.encode("utf-8"))
                    for row in seed["sources"]:
                        if row["text"] == previous:
                            row["text"] = current
                reseal_seed(seed, owner, file)
                before = owner.read_bytes(), file.read_bytes()
                refused = self.command("compile", owner, "--input", file, "--as-of", audit, code=2)
                self.assertEqual(expected, refused["error"])
                self.assertEqual(before, (owner.read_bytes(), file.read_bytes()))
                self.assertEqual([], list(owner.parent.glob("task-run-*")))

    def test_admitting_a_candidate_cannot_erase_source_declared_ancestor_constraints(self):
        _, owner, file = prepare(self.root)
        candidate, path = self.compile(owner, file)
        changed = copy.deepcopy(candidate)
        changed["payload"]["objective"]["constraints"] = []
        path.write_text(json.dumps(changed), encoding="utf-8")
        admit(changed, owner, file)
        before = owner.read_bytes()
        refused = self.command("verify", owner, "--candidate", path, code=2)
        self.assertEqual("TASK_CONTEXT_CANDIDATE_CHANGED", refused["error"])
        self.assertEqual(before, owner.read_bytes())

    def test_query_keeps_task_modules_unloaded_in_a_fresh_process(self):
        code = """import sys
sys.path.insert(0, sys.argv[1])
from kotodama_kb.cli import main
assert main(['query', 'KGI', '--root', sys.argv[2], '--as-of', '2026-10-10T00:00:00Z', '--json']) == 0
assert 'kotodama_kb.task_input_cli' not in sys.modules
assert 'kotodama_kb.task_input' not in sys.modules
assert not any(k == 'runtime' or k.startswith('runtime.') for k in sys.modules)
"""
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(ROOT / "tools"), str(ROOT)],
            cwd=self.cwd, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["results"])

    def test_json_output_ignores_terminal_encoding_and_newline_translation(self):
        from kotodama_kb import task_input_cli as adapter
        args = SimpleNamespace(operation="compile", as_of=None, root=self.root)
        for encoding in ("cp1252", "utf-8"):
            for refused in (False, True):
                with self.subTest(encoding=encoding, refused=refused):
                    raw_out, raw_err = io.BytesIO(), io.BytesIO()
                    stdout = io.TextIOWrapper(raw_out, encoding=encoding, newline="\r\n")
                    stderr = io.TextIOWrapper(raw_err, encoding=encoding, newline="\r\n")
                    result = {"message": "原意と訂正"}
                    failure = adapter.SwarmError("FIXTURE_REFUSED", "原意と訂正")
                    expected = {"error": failure.code, "message": failure.detail} if refused else result
                    try:
                        with mock.patch.object(adapter, "load_bundle"), mock.patch.object(adapter, "_assert_current"), \
                             mock.patch.object(adapter, "_execute", side_effect=failure if refused else None,
                                               return_value=(result, 0)), \
                             redirect_stdout(stdout), redirect_stderr(stderr):
                            code = adapter.run(args)
                        self.assertEqual(2 if refused else 0, code)
                        self.assertEqual((adapter.canonical(expected) + "\n").encode("utf-8"),
                                         raw_err.getvalue() if refused else raw_out.getvalue())
                        self.assertEqual(b"", raw_out.getvalue() if refused else raw_err.getvalue())
                    finally:
                        stdout.detach()
                        stderr.detach()
        for refused in (False, True):
            with self.subTest(memory_stream=True, refused=refused):
                stdout, stderr = io.StringIO(), io.StringIO()
                with mock.patch.object(adapter, "load_bundle"), mock.patch.object(adapter, "_assert_current"), \
                     mock.patch.object(adapter, "_execute", side_effect=failure if refused else None,
                                       return_value=(result, 0)), \
                     redirect_stdout(stdout), redirect_stderr(stderr):
                    self.assertEqual(2 if refused else 0, adapter.run(args))
                expected = {"error": failure.code, "message": failure.detail} if refused else result
                self.assertEqual(adapter.canonical(expected) + "\n", stderr.getvalue() if refused else stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
