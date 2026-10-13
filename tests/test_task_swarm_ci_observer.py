"""Compare real pytest subprocesses, including successful subtests and hard stops."""
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/pytest_ci_observer.py"
PREFIX = "KOTODAMA_PYTEST_EVENT "

# An independent, finite fixture-side inventory; loaded for both subprocesses.
REFERENCE = '''
import json, os
from pathlib import Path
rows = []
def pytest_collection_finish(session):
    rows.append(["collection", [item.nodeid for item in session.items]])
def pytest_runtest_logreport(report):
    context = getattr(report, "context", None)
    rows.append([report.nodeid, report.when, report.outcome,
        report.longrepr[2] if report.skipped and isinstance(report.longrepr, tuple) else None,
        getattr(report, "wasxfail", None),
        [context.msg, dict(context.kwargs)] if context else None])
def pytest_sessionfinish(session, exitstatus):
    Path(os.environ["REFERENCE_PATH"]).write_text(json.dumps(rows), encoding="utf-8")
'''
SUCCESS = '''
import subprocess, sys, unittest
import pytest

def test_subtests(subtests):
    for number in [1, 1, 2]:
        with subtests.test("repeated values", number=number):
            assert number > 0

class TestUnit(unittest.TestCase):
    def test_subtests(self):
        with self.subTest(label="unit"):
            self.assertEqual(1, 1)

@pytest.mark.skip(reason="explicit fixture skip")
def test_skip():
    raise AssertionError("must remain skipped")

@pytest.mark.skipif(sys.platform == "win32", reason="Windows fixture reason")
def test_os_specific():
    assert True

@pytest.mark.xfail(reason="known fixture expectation")
def test_xfail():
    assert False

def test_capture(capsys):
    print("CAPTURED_STDOUT_SENTINEL")
    print("CAPTURED_STDERR_SENTINEL", file=sys.stderr)
    out, err = capsys.readouterr()
    assert out == "CAPTURED_STDOUT_SENTINEL\\n"
    assert err == "CAPTURED_STDERR_SENTINEL\\n"

def test_fd_capture(capfd):
    subprocess.run([sys.executable, "-c", "print('CAPTURED_CHILD_SENTINEL')"], check=True)
    assert capfd.readouterr().out == "CAPTURED_CHILD_SENTINEL\\n"

@pytest.fixture
def staged_subtests(subtests):
    with subtests.test("fixture setup", value="ready"):
        assert True
    yield
    with subtests.test("fixture teardown", value="settled"):
        assert True

def test_fixture_subtests(staged_subtests):
    pass
'''
FAILURES = '''
import subprocess, sys
import pytest

@pytest.fixture
def setup_error():
    raise RuntimeError("fixture setup error")
@pytest.fixture
def teardown_error():
    yield
    raise RuntimeError("fixture teardown error")
def test_setup(setup_error):
    pass
def test_teardown(teardown_error):
    pass
def test_failure():
    assert False, "ordinary failure"
def test_child_failure():
    subprocess.run([sys.executable, "-c", "raise SystemExit(7)"], check=True)
def test_failed_subtest(subtests):
    with subtests.test("failure", value=9):
        assert False
'''


def project(tmp_path, content=SUCCESS):
    root = tmp_path / "fixture"
    root.mkdir()
    (root / "conftest.py").write_text(REFERENCE, encoding="utf-8")
    (root / "test_fixture.py").write_text(content, encoding="utf-8")
    return root


def invocation(root, name, *, observed, limit=None, extra=()):
    env = dict(os.environ)
    for key in ("PYTEST_PLUGINS", "PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "KOTODAMA_CI_OBSERVATION_DIR",
                "KOTODAMA_CI_OBSERVATION_MAX_BYTES"):
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", PYTHONPATH=str(ROOT),
               REFERENCE_PATH=str(root / (name + "-reference.json")))
    output = root / (name + "-observation")
    if observed:
        env.update(PYTEST_PLUGINS="tools.pytest_ci_observer", KOTODAMA_CI_OBSERVATION_DIR=str(output))
    if limit is not None:
        env["KOTODAMA_CI_OBSERVATION_MAX_BYTES"] = str(limit)
    command = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
               "--rootdir", str(root), *extra, "test_fixture.py"]
    return command, env, output


def run(root, name, *, observed, limit=None, extra=()):
    command, env, output = invocation(root, name, observed=observed, limit=limit, extra=extra)
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    return result, output


def events(directory):
    return [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def verify(directory):
    return subprocess.run([sys.executable, "-B", str(TOOL), str(directory)], capture_output=True,
                          text=True, timeout=10)


@pytest.mark.parametrize("content,expected", [(SUCCESS, 0), (SUCCESS + FAILURES, 1)], ids=["success", "failures"])
def test_same_collection_phase_outcomes_and_successful_subtests(tmp_path, content, expected):
    root = project(tmp_path, content)
    baseline, _ = run(root, "baseline", observed=False)
    observed, output = run(root, "observed", observed=True)
    assert baseline.returncode == observed.returncode == expected
    original = json.loads((root / "baseline-reference.json").read_text(encoding="utf-8"))
    actual = json.loads((root / "observed-reference.json").read_text(encoding="utf-8"))
    assert original == actual
    raw = events(output)
    assert [item["nodeid"] for item in raw if item["kind"] == "collected"] == original[0][1]
    outcomes = [[item["nodeid"], item["when"], item["outcome"], item["skip_reason"], item["wasxfail"],
                 [item["subtest"]["message"], item["subtest"]["parameters"]] if item["kind"] == "subtest" else None]
                for item in raw if item["kind"] in ("phase", "subtest")]
    assert outcomes == original[1:]
    assert sum(item["kind"] == "subtest" and item["outcome"] == "passed" for item in raw) == 6
    assert all(item["duration_seconds"] >= 0 for item in raw if item["kind"] in ("phase", "subtest"))
    assert {item["when"] for item in raw if item["kind"] == "phase_start"} == {"setup", "call", "teardown"}
    assert any(item.get("skip_reason") == "Skipped: explicit fixture skip" for item in raw)
    # Every event is mirrored before termination; no final-only JUnit dependency.
    mirrored = [json.loads(line.split(PREFIX, 1)[1]) for line in observed.stdout.splitlines() if PREFIX in line]
    assert mirrored == raw
    for sentinel in ("CAPTURED_STDOUT_SENTINEL", "CAPTURED_STDERR_SENTINEL", "CAPTURED_CHILD_SENTINEL"):
        assert sentinel not in baseline.stdout and sentinel not in observed.stdout
    assert verify(output).returncode == expected
    final = json.loads((output / "final.json").read_text(encoding="utf-8"))
    assert final["complete"] is True
    assert final["observer_hook_seconds_before_final_write"] >= 0
    assert raw[0]["source"]["observer_sha256"] == hashlib.sha256(TOOL.read_bytes()).hexdigest()
    assert raw[0]["environment"]["python"] == platform.python_version()
    assert all(value is None for value in raw[0]["unknown"].values())


@pytest.mark.parametrize("body,expected", [("os._exit(23)", 23), ("raise KeyboardInterrupt", 2)])
def test_crash_and_interrupt_preserve_exit_and_partial_events(tmp_path, body, expected):
    root = project(tmp_path, "import os\ndef test_stop():\n    " + body + "\n")
    baseline, _ = run(root, "baseline", observed=False)
    observed, output = run(root, "observed", observed=True)
    assert baseline.returncode == observed.returncode == expected
    raw = events(output)
    assert any(item["kind"] == "phase_start" and item["when"] == "call" for item in raw)
    assert PREFIX in observed.stdout
    assert verify(output).returncode == 3
    if (output / "final.json").exists():
        assert json.loads((output / "final.json").read_text())["complete"] is False


def test_external_termination_retains_partial_before_process_exit(tmp_path):
    root = project(tmp_path, '''
import os, time
from pathlib import Path
def test_wait():
    Path(os.environ["REFERENCE_PATH"] + ".ready").write_text("ready")
    time.sleep(60)
''')
    returns = []
    for name, observed in (("baseline", False), ("observed", True)):
        command, env, output = invocation(root, name, observed=observed)
        ready = Path(env["REFERENCE_PATH"] + ".ready")
        with (root / (name + ".log")).open("wb") as log:
            child = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 15
                while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                assert ready.exists(), "fixture must enter the blocked call before cancellation"
                if observed:
                    assert events(output)[-1]["kind"] == "phase_start"
                    assert PREFIX.encode() in (root / (name + ".log")).read_bytes()
                child.terminate()
                returns.append(child.wait(timeout=10))
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=10)
        if observed:
            assert not (output / "final.json").exists()
            assert verify(output).returncode == 3
    assert returns[0] == returns[1] != 0


@pytest.mark.parametrize("case", ["stream", "record"])
def test_capacity_is_bounded_without_skipping_remaining_tests(tmp_path, case):
    content = ("import pytest\n@pytest.mark.parametrize('number', range(20))\ndef test_many(number):\n    assert number >= 0\n"
               if case == "stream" else "import pytest\ndef test_long_reason():\n    pytest.skip('x' * 70000)\n")
    root = project(tmp_path, content)
    baseline, _ = run(root, "baseline", observed=False)
    observed, output = run(root, "observed", observed=True, limit=4096 if case == "stream" else None)
    assert baseline.returncode == observed.returncode == 0
    assert json.loads((root / "baseline-reference.json").read_text()) == json.loads((root / "observed-reference.json").read_text())
    final = json.loads((output / "final.json").read_text())
    assert final["complete"] is False and final["incomplete_reason"] == "capacity_exceeded"
    assert (output / "events.jsonl").stat().st_size <= (4096 if case == "stream" else 16 * 1024 * 1024)
    assert (output / "final.json").stat().st_size <= 8192
    assert final["console_bytes"] <= (4096 if case == "stream" else 16 * 1024 * 1024)
    assert verify(output).returncode == 3


@pytest.mark.parametrize("case", ["final_missing", "truncated", "phase_missing", "early_stop", "collection_error", "final_write_error"])
def test_missing_or_incomplete_inventory_cannot_pass(tmp_path, case):
    root = project(tmp_path, "def test_ok():\n    assert True\n" if case != "early_stop" else FAILURES)
    if case == "collection_error":
        (root / "test_fixture.py").write_text("raise RuntimeError('collection failed')\n")
    if case == "final_write_error":
        (root / "test_fixture.py").write_text("import os\nfrom pathlib import Path\ndef test_ok():\n"
            "    if 'KOTODAMA_CI_OBSERVATION_DIR' in os.environ:\n"
            "        (Path(os.environ['KOTODAMA_CI_OBSERVATION_DIR']) / 'final.json').mkdir()\n")
    observed, output = run(root, "observed", observed=True, extra=("-x",) if case == "early_stop" else ())
    if case == "final_missing":
        (output / "final.json").unlink()
    elif case == "truncated":
        file = output / "events.jsonl"
        file.write_bytes(file.read_bytes()[:-1])
    elif case == "phase_missing":
        # Repair the cheap digest too: the inventory verifier must notice the
        # missing call outcome, rather than relying only on hash mismatch.
        raw = [item for item in events(output) if not (item["kind"] == "phase" and item["when"] == "call")]
        for sequence, item in enumerate(raw):
            item["sequence"] = sequence
        data = b"".join((json.dumps(item) + "\n").encode() for item in raw)
        (output / "events.jsonl").write_bytes(data)
        final = json.loads((output / "final.json").read_text())
        final.update(events_sha256=hashlib.sha256(data).hexdigest(), events=len(raw), stream_bytes=len(data))
        (output / "final.json").write_text(json.dumps(final))
    elif case in ("early_stop", "collection_error"):
        baseline, _ = run(root, "baseline", observed=False, extra=("-x",) if case == "early_stop" else ())
        assert baseline.returncode == observed.returncode != 0
    else:
        baseline, _ = run(root, "baseline", observed=False)
        assert baseline.returncode == observed.returncode == 0
    assert verify(output).returncode == 3


@pytest.mark.parametrize("case", ["orphan_subtest", "foreign_parent", "subtest_phase", "missing_context",
                                  "outcome_enum", "failed_footer", "phase_start_missing", "phase_order"])
def test_semantic_inventory_corruption_refuses_even_with_recomputed_digest(tmp_path, case):
    root = project(tmp_path)
    result, output = run(root, "observed", observed=True)
    assert result.returncode == verify(output).returncode == 0
    raw = events(output)
    subtest = next(item for item in raw if item["kind"] == "subtest")
    if case == "orphan_subtest":
        subtest.update(occurrence=99999, nodeid="not_collected")
    elif case == "foreign_parent":
        foreign = next(item for item in raw if item["kind"] == "collected" and item["occurrence"] != subtest["occurrence"])
        subtest.update(occurrence=foreign["occurrence"], nodeid=foreign["nodeid"])
    elif case == "subtest_phase":
        subtest["when"] = "unknown-phase"
    elif case == "missing_context":
        del subtest["subtest"]["parameters"]
    elif case == "outcome_enum":
        next(item for item in raw if item["kind"] == "phase")["outcome"] = "unknown-outcome"
    elif case == "failed_footer":
        next(item for item in raw if item["kind"] == "phase" and item["when"] == "call")["outcome"] = "failed"
    elif case == "phase_start_missing":
        raw = [item for item in raw if item["kind"] != "phase_start"]
    else:
        next(item for item in raw if item["kind"] == "phase_start")["when"] = "teardown"
    for sequence, item in enumerate(raw):
        item["sequence"] = sequence
    data = b"".join((json.dumps(item) + "\n").encode() for item in raw)
    (output / "events.jsonl").write_bytes(data)
    final = json.loads((output / "final.json").read_text())
    final.update(events_sha256=hashlib.sha256(data).hexdigest(), events=len(raw), stream_bytes=len(data),
                 console_bytes=len(data) + len(raw) * (len(PREFIX) + 1))
    (output / "final.json").write_text(json.dumps(final))
    assert verify(output).returncode == 3
