"""Read-only reference navigation over an actual owner-admitted Task candidate."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from tests.test_knowledge_task_input_cli import prepare
from tests.test_knowledge_task_input import admit, reseal_seed, source
from kotodama_kb.load import load_bundle
from kotodama_kb.task_input import compile_task_input
from kotodama_kb import task_input_cli as adapter
from runtime.task_swarm.protocol import canonical, digest

ENTRY = ROOT / "tools/knowledge_base.py"


def inventory(root):
    return {path.relative_to(root).as_posix(): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


class TaskInputInspectTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        seed, self.owner, self.input = prepare(self.root, corrected=True)
        self.seed = seed
        self.candidate = compile_task_input(load_bundle(self.root), seed, self.owner)
        admit(self.candidate, self.owner, self.input)
        self.path = self.root / "candidate.json"
        self.save(self.candidate)

    def save(self, value):
        self.path.write_bytes((canonical(value) + "\n").encode("utf-8"))

    def args(self, **changes):
        values = dict(operation="inspect", as_of=None, root=self.root, owner=self.owner,
                      candidate=self.path, format="json", input=None,
                      learning_origin=None, learning_decision_digest=None)
        return SimpleNamespace(**{**values, **changes})

    def local(self, args=None):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = adapter.run(args or self.args())
        return code, output.getvalue(), error.getvalue()

    def command(self, *extra):
        return subprocess.run([sys.executable, "-I", "-B", str(ENTRY), "task-input",
            "inspect", "--root", str(self.root), "--owner", str(self.owner),
            "--candidate", str(self.path), *map(str, extra)],
            cwd=self.root, capture_output=True, timeout=30)

    def test_actual_cli_traces_correction_without_changing_any_file(self):
        before = inventory(self.root)
        result = self.command()
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
        report = json.loads(result.stdout)
        self.assertEqual(digest(self.candidate["payload"]), report["task"]["payload_digest"])
        self.assertEqual(self.candidate["payload"]["objective"]["intent"]["original"],
                         {key: report["objective"]["intent"]["original"][key]
                          for key in ("source_key", "source_revision", "start", "end")})
        self.assertEqual(1, len(report["objective"]["intent"]["replacements"]))
        self.assertEqual(["OUT-INTENT", "KGI-INTENT", "INIT-AGENT-OWNERSHIP"],
                         [row["id"] for row in report["references"]])
        self.assertEqual("NEEDS_RESOLUTION", report["decision_readiness"])
        self.assertEqual("NOT_EVALUATED", report["authority"]["actor_execution_authorization"])
        self.assertEqual("UNRESOLVED", report["authority"]["external_goal_adoption"])
        self.assertEqual(b"", result.stderr)
        self.assertEqual(before, inventory(self.root))
        evidence = os.environ.get("KOTODAMA_INSPECT_TEST_EVIDENCE")
        if evidence:
            Path(evidence).mkdir(parents=True, exist_ok=True)
            (Path(evidence) / "normal-json.frame").write_bytes(result.stdout)

    def test_normal_mode_cannot_fall_through_to_simulation_or_database(self):
        with mock.patch("sqlite3.connect", side_effect=AssertionError("DB called")), \
             mock.patch("runtime.task_swarm.state.SwarmState.__init__", side_effect=AssertionError("state initialized")), \
             mock.patch.object(adapter, "ScriptedSimulation", side_effect=AssertionError("simulation called")), \
             mock.patch.object(adapter, "execute_task_input", side_effect=AssertionError("execute called")):
            code, output, error = self.local()
        self.assertEqual(0, code, error)
        self.assertEqual("binding_verified", json.loads(output)["status"])

    def test_learning_candidate_is_refused_before_owner_or_learning_verifier(self):
        self.save({**self.candidate, "learning": None})
        with mock.patch.object(adapter, "verify_task_input", side_effect=AssertionError("normal verifier called")), \
             mock.patch.object(adapter, "load_bundle", side_effect=AssertionError("bundle read")), \
             mock.patch("sqlite3.connect", side_effect=AssertionError("DB called")):
            code, output, error = self.local(self.args(owner=self.root / "missing-owner.json"))
        self.assertEqual(2, code)
        self.assertEqual("", output)
        self.assertEqual("TASK_INPUT_INSPECT_LEARNING_UNSUPPORTED", json.loads(error)["error"])
        self.assertEqual("NOT_EVALUATED", json.loads(error)["current_learning_decision"])

    def test_actual_markdown_has_reference_paths_and_remains_read_only(self):
        before = inventory(self.root)
        result = self.command("--format", "markdown")
        self.assertEqual(0, result.returncode, result.stderr.decode("utf-8"))
        text = result.stdout.decode("utf-8")
        for expected in ("NEEDS_RESOLUTION", "UNRESOLVED", "NOT_EVALUATED", "knowledge/synthetic/0.md",
                         "KGI-INTENT", "input_only_unverified", "show CONCEPT_ID"):
            self.assertIn(expected, text)
        self.assertNotIn(self.candidate["payload"]["request"], text)
        self.assertTrue(result.stdout.endswith(b"\n"))
        self.assertFalse(result.stdout.endswith(b"\n\n"))
        self.assertEqual(b"", result.stderr)
        self.assertEqual(before, inventory(self.root))
        evidence = os.environ.get("KOTODAMA_INSPECT_TEST_EVIDENCE")
        if evidence:
            Path(evidence).mkdir(parents=True, exist_ok=True)
            (Path(evidence) / "normal-markdown.frame").write_bytes(result.stdout)

    def test_real_cli_learning_flags_are_typed_unsupported(self):
        for flag in ("--learning-origin", "--learning-decision-digest", "--input"):
            with self.subTest(flag=flag):
                result = self.command(flag, "unused-do-not-read")
                self.assertEqual(2, result.returncode)
                self.assertEqual(b"", result.stdout)
                self.assertEqual("NOT_EVALUATED", json.loads(result.stderr)["current_learning_decision"])
                self.assertEqual("NEEDS_RESOLUTION", json.loads(result.stderr)["decision_readiness"])

    def test_ten_sources_and_12000_character_boundary_are_supported(self):
        self.seed["sources"].append(source("unused-bounded-input", 1, "x" * 12000))
        self.assertEqual(10, len(self.seed["sources"]))
        reseal_seed(self.seed, self.owner, self.input)
        candidate = compile_task_input(load_bundle(self.root), self.seed, self.owner)
        admit(candidate, self.owner, self.input)
        self.save(candidate)
        before = inventory(self.root)
        result = self.command()
        self.assertEqual(0, result.returncode, result.stderr.decode())
        self.assertEqual(digest(candidate["payload"]), json.loads(result.stdout)["task"]["payload_digest"])
        self.assertEqual(before, inventory(self.root))

    def test_real_unicode_source_span_and_terminal_encoding(self):
        old = self.root / "knowledge/synthetic/0.md"
        raw = old.read_bytes().decode("utf-8")
        text = raw.replace("title: Synthetic 0", "title: 原意🧭")
        old.write_bytes(text.encode("utf-8"))
        for row in self.seed["sources"]:
            if row["text"] == raw: row["text"] = text
        reseal_seed(self.seed, self.owner, self.input)
        candidate = compile_task_input(load_bundle(self.root), self.seed, self.owner)
        admit(candidate, self.owner, self.input)
        self.save(candidate)
        for format in ("json", "markdown"):
            with self.subTest(format=format):
                raw_out, raw_err = io.BytesIO(), io.BytesIO()
                stdout = io.TextIOWrapper(raw_out, encoding="cp1252", newline="\r\n")
                stderr = io.TextIOWrapper(raw_err, encoding="cp1252", newline="\r\n")
                try:
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = adapter.run(self.args(format=format))
                    frame = raw_out.getvalue()
                    self.assertEqual(0, code, raw_err.getvalue())
                    self.assertIn("原意🧭".encode("utf-8"), frame)
                    self.assertTrue(frame.endswith(b"\n"))
                    self.assertNotIn(b"\r\n", frame)
                    if format == "json":
                        row = json.loads(frame)["references"][0]
                        location = row["source"]
                        self.assertEqual("OUT-INTENT", text[location["start"]:location["end"]])
                        self.assertNotEqual(location["start"], len(text[:location["start"]].encode("utf-8")))
                finally:
                    stdout.detach()
                    stderr.detach()

    def test_learning_flags_and_keys_are_rejected_without_import_or_reads(self):
        for flag in ("learning_origin", "learning_decision_digest", "input"):
            with self.subTest(flag=flag), \
                 mock.patch.object(adapter, "read_json", side_effect=AssertionError("input read")), \
                 mock.patch("sqlite3.connect", side_effect=AssertionError("DB called")):
                code, output, error = self.local(self.args(**{flag: "unused"}))
            self.assertEqual(2, code)
            self.assertEqual("", output)
            self.assertEqual("NOT_EVALUATED", json.loads(error)["current_learning_decision"])
        original_import = __import__
        def importing(name, *args, **kwargs):
            if "task_input_learning" in name or "learning_reuse" in name:
                raise AssertionError("learning imported")
            return original_import(name, *args, **kwargs)
        for value in (None, False, {}, "origin"):
            with self.subTest(value=value):
                self.save({**self.candidate, "learning": value})
                before = inventory(self.root)
                with mock.patch("builtins.__import__", side_effect=importing), \
                     mock.patch.object(adapter, "verify_task_input", side_effect=AssertionError("verifier called")):
                    code, output, error = self.local()
                self.assertEqual(2, code)
                self.assertEqual("", output)
                self.assertEqual("TASK_INPUT_INSPECT_LEARNING_UNSUPPORTED", json.loads(error)["error"])
                self.assertEqual(before, inventory(self.root))

    def test_malformed_bounded_candidate_inputs_have_typed_refusals(self):
        values = [None, False, [], 1, "candidate", {},
                  {**self.candidate, "unexpected": True},
                  {**self.candidate, "payload": []},
                  {**self.candidate, "context_projection": False}]
        for index, value in enumerate(values):
            with self.subTest(index=index):
                self.save(value)
                before = inventory(self.root)
                code, output, error = self.local()
                self.assertEqual(2, code)
                self.assertEqual("", output)
                self.assertIsInstance(json.loads(error)["error"], str)
                self.assertEqual(before, inventory(self.root))
        for raw in (b"{", b'{"payload":0,"payload":1}', b"\xff", b" " * (256 * 1024 + 2)):
            with self.subTest(raw_length=len(raw)):
                self.path.write_bytes(raw)
                code, output, error = self.local()
                self.assertEqual(2, code)
                self.assertEqual("", output)
                self.assertIsInstance(json.loads(error)["error"], str)

    def test_task_owner_binding_cannot_authorize_wrong_references_or_caps(self):
        original = copy.deepcopy(self.candidate)
        def edit(kind):
            candidate = copy.deepcopy(original)
            payload = candidate["payload"]
            if kind == "unknown": payload["objective"]["references"][1]["id"] = "KGI-UNKNOWN"
            if kind == "wrong_kind": payload["objective"]["references"][1]["kind"] = "initiative"
            if kind == "refs21": payload["objective"]["references"] *= 7
            if kind == "sources11":
                for index in range(11 - len(payload["sources"])):
                    text = "unused source " + str(index)
                    payload["sources"].append({"key": hashlib.sha256(text.encode()).hexdigest(),
                        "revision": 1, "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest()})
            if kind == "source12001":
                row = payload["sources"][0]
                row["text"] = "x" * 12001
                row["sha256"] = hashlib.sha256(row["text"].encode()).hexdigest()
            return candidate
        for kind in ("unknown", "wrong_kind", "refs21", "sources11", "source12001"):
            with self.subTest(kind=kind):
                changed = edit(kind)
                self.save(changed)
                admit(changed, self.owner, self.input)
                before = inventory(self.root)
                code, output, error = self.local()
                self.assertEqual(2, code)
                self.assertEqual("", output)
                self.assertIsInstance(json.loads(error)["error"], str)
                self.assertEqual(before, inventory(self.root))

    def test_projection_numeric_aliases_are_not_used_as_display_facts(self):
        changed = copy.deepcopy(self.candidate)
        changed["diagnostics"]["provider_delivery_verified"] = 0
        for row in changed["context_projection"]["concepts"]:
            row["is_stale"] = 0  # Existing equality allows False==0; display must not copy it.
        self.save(changed)
        code, output, error = self.local()
        self.assertEqual(0, code, error)
        report = json.loads(output)
        self.assertEqual("UNRESOLVED", report["authority"]["external_goal_adoption"])
        self.assertNotIn("provider_delivery_verified", report)
        for row in report["references"]:
            concept = load_bundle(self.root).by_id[row["concept"]["id"]]
            self.assertEqual(concept.content_sha256, row["concept"]["content_sha256"])
            self.assertEqual("candidate", row["concept"]["adoption_status"])

    def test_control_metric_cannot_replace_kgi_even_after_owner_admission(self):
        path = self.root / "knowledge/synthetic/1.md"
        original = path.read_bytes().decode("utf-8")
        changed = original.replace("measurement_role: product_outcome", "measurement_role: control_slo")
        self.assertNotEqual(original, changed)
        path.write_bytes(changed.encode("utf-8"))
        candidate = copy.deepcopy(self.candidate)
        for row in candidate["payload"]["sources"]:
            if row["text"] == original:
                row.update(text=changed, sha256=hashlib.sha256(changed.encode("utf-8")).hexdigest())
        for check in candidate["source_checks"]:
            if Path(check["path"]) == path:
                check["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.save(candidate)
        admit(candidate, self.owner, self.input)
        before = inventory(self.root)
        result = self.command()
        self.assertEqual(2, result.returncode)
        self.assertEqual(b"", result.stdout)
        self.assertEqual("KNOWLEDGE_INPUT_REFUSED", json.loads(result.stderr)["error"])
        self.assertEqual(before, inventory(self.root))

    def test_formatter_mutations_refuse_before_any_stdout(self):
        formatter = adapter._inspection_output
        paths = {self.path, self.owner, self.root / "work/REQ-0.md"}
        saved = {path: path.read_bytes() for path in paths}
        def mutate(kind):
            if kind == "candidate":
                info = self.path.stat()
                self.path.write_bytes(self.path.read_bytes()[:-1] + b" ")
                os.utime(self.path, ns=(info.st_atime_ns, info.st_mtime_ns))
            elif kind == "source":
                path = self.root / "work/REQ-0.md"
                info = path.stat()
                path.write_bytes(path.read_bytes().replace(b"latency", b"slowerx"))
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
            elif kind == "owner_actor":
                document = json.loads(self.owner.read_bytes())
                document["actors"]["worker-a"]["invocation_ref"] = "changed-actor-invocation"
                self.owner.write_bytes(canonical(document).encode())
            elif kind == "owner_task":
                document = json.loads(self.owner.read_bytes())
                document["binding"]["revision"] += 1
                self.owner.write_bytes(canonical(document).encode())
            elif kind == "source_delete":
                (self.root / "work/REQ-0.md").unlink()
            elif kind == "source_rename":
                (self.root / "work/REQ-0.md").rename(self.root / "work/renamed.md")
            else:
                (self.root / "knowledge/new.md").write_bytes(b"# Concurrent new source\n")
        for kind in ("candidate", "source", "owner_actor", "owner_task", "knowledge_add", "source_delete", "source_rename"):
            with self.subTest(kind=kind):
                for path, content in saved.items(): path.write_bytes(content)
                (self.root / "knowledge/new.md").unlink(missing_ok=True)
                (self.root / "work/renamed.md").unlink(missing_ok=True)
                def render(report, format):
                    value = formatter(report, format)
                    mutate(kind)
                    return value
                with mock.patch.object(adapter, "_inspection_output", side_effect=render):
                    code, output, error = self.local()
                self.assertEqual(2, code)
                self.assertEqual("", output)
                refusal = json.loads(error)["error"]
                if kind == "candidate": self.assertEqual("TASK_INPUT_INSPECT_CANDIDATE_CHANGED", refusal)
                if kind == "owner_actor": self.assertEqual("TASK_INPUT_INSPECT_OWNER_CHANGED", refusal)

    def test_real_verifier_checks_deadline_again_after_serialization(self):
        verifier = adapter.verify_task_input
        initial = __import__("time").time()
        deadline = self.candidate["payload"]["objective"]["budget"]["deadline"]
        times = iter((initial, deadline + 0.001))
        def verify(*args, **kwargs):
            instant = next(times)
            return verifier(*args, **kwargs, clock=lambda: instant)
        with mock.patch.object(adapter, "verify_task_input", side_effect=verify):
            code, output, error = self.local()
        self.assertEqual(2, code)
        self.assertEqual("", output)
        self.assertEqual("OBJECTIVE_DEADLINE_INVALID", json.loads(error)["error"])

    def test_framed_output_cap_counts_utf8_and_one_lf_without_truncation(self):
        for format in ("json", "markdown"):
            for extra in (0, 1):
                with self.subTest(format=format, extra=extra):
                    # Unicode plus padding models a formatter exceeding its finite transport budget.
                    text = "🧭" * (256 * 1024 // 4 - 1) + "x" * (3 + extra)
                    self.assertEqual(256 * 1024 + extra, len((text + "\n").encode("utf-8")))
                    with mock.patch.object(adapter, "_inspection_output", return_value=text):
                        code, output, error = self.local(self.args(format=format))
                    self.assertEqual(2 if extra else 0, code)
                    if extra:
                        self.assertEqual("", output)
                        self.assertEqual("TASK_INPUT_INSPECT_OUTPUT_LIMIT", json.loads(error)["error"])
                    else:
                        self.assertEqual(text + "\n", output)
                        self.assertEqual("", error)


if __name__ == "__main__":
    unittest.main()
