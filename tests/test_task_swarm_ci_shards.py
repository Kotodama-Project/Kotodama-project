"""Real small pytest runs, then independently corrupted matrix evidence."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

try:
    import pytest
except ModuleNotFoundError:
    import unittest
    raise unittest.SkipTest("runs in the required Task swarm pytest job")

ROOT = Path(__file__).resolve().parents[1]
COMMAND = [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider",
           "-o", "python_files=test_task_swarm_*.py", "tests"]
PROGRAM = '''
import os, pytest
@pytest.mark.parametrize("value", [1, 1, 2])
def test_parameter(value):
    assert value > 0
def test_subtests(subtests):
    for value in [1, 1, 2]:
        with subtests.test("same", value=value):
            assert os.environ.get("FIXTURE_FAIL") != "yes"
@pytest.mark.skip(reason="existing fixture skip")
def test_skip():
    assert False
@pytest.mark.xfail(reason="existing fixture expectation")
def test_xfail():
    assert False
def test_capture(capsys):
    print("captured fixture")
    assert capsys.readouterr().out == "captured fixture\\n"
'''
DUPLICATES = '''
import os, pytest
class Duplicate(pytest.Item):
    def runtest(self): pass
    def reportinfo(self): return self.path, 0, self.name
class Repeated(pytest.File):
    def collect(self):
        for name in (["single"] if os.environ.get("FIXTURE_SMALL") else ["same", "same", "last"]):
            yield Duplicate.from_parent(self, name=name)
def pytest_ignore_collect(collection_path, config):
    if os.environ.get("FIXTURE_SMALL") and collection_path.name == "test_task_swarm_fixture.py":
        return True
def pytest_collect_file(file_path, parent):
    if file_path.name == "repeated.data":
        return Repeated.from_parent(parent, path=file_path)
'''


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_bytes(encoded(value))


def run(root, command, env, expected=0):
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == expected, result.stdout + result.stderr
    return result


def clean_env(root):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_", "KOTODAMA_CI_"))}
    env.update(PYTHONPATH=str(root), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1", GITHUB_RUN_ID="123",
               GITHUB_RUN_ATTEMPT="1", RUNNER_OS="Linux", MATRIX_RESULT="success")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    env.update(GITHUB_SHA=head, KOTODAMA_CI_HEAD_SHA=head)
    return env


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    root = tmp_path_factory.mktemp("shards")
    (root / "tools").mkdir()
    (root / "tests").mkdir()
    for name in ("pytest_ci_shards.py", "pytest_ci_observer.py"):
        shutil.copyfile(ROOT / "tools" / name, root / "tools" / name)
    (root / "tools/__init__.py").write_text("")
    (root / "pytest.ini").write_text("[pytest]\n")
    (root / "requirements-task-swarm-ci.txt").write_text("# owned fixture lock\n")
    (root / "tests/test_task_swarm_fixture.py").write_text(PROGRAM)
    (root / "tests/conftest.py").write_text(DUPLICATES)
    (root / "tests/repeated.data").write_text("owned duplicate occurrence fixture\n")
    for command in (["git", "init", "-q"], ["git", "add", "."],
                    ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                     "commit", "-qm", "owned fixture"]):
        subprocess.run(command, cwd=root, check=True, capture_output=True)
    env = clean_env(root)
    outcomes, runs = {}, {}
    for width in (1, 2, 4):
        for index in range(width):
            directory = root / f"width-{width}-{index}"
            local = {**env, "KOTODAMA_CI_SHARD_OS": "ubuntu-22.04", "KOTODAMA_CI_SHARD_INDEX": str(index),
                     "KOTODAMA_CI_SHARD_COUNT": str(width), "KOTODAMA_CI_SHARD_DIR": str(directory / "partition")}
            if index == 0:
                run(root, [sys.executable, "-B", "tools/pytest_ci_shards.py", "reference", str(directory / "reference")], local)
            observed = {**local, "PYTEST_PLUGINS": "tools.pytest_ci_observer,tools.pytest_ci_shards",
                        "KOTODAMA_CI_OBSERVATION_DIR": str(directory / "observation")}
            run(root, COMMAND, observed)
            run(root, [sys.executable, "-B", "tools/pytest_ci_shards.py", "seal", str(directory),
                       "--demo", "success" if index == 0 else "skipped",
                       "--benchmark", "success" if index == 0 else "skipped"], local)
            selection = read(directory / "partition/selection.json")
            events = [json.loads(line) for line in (directory / "observation/events.jsonl").read_bytes().splitlines()]
            for event in events:
                if event["kind"] in ("phase", "subtest"):
                    global_index = selection["selected_occurrences"][event["occurrence"]]
                    outcomes.setdefault(width, []).append((global_index, event["kind"], event["when"], event["outcome"],
                        event["skip_reason"], event.get("wasxfail"), event.get("subtest", {}).get("message"),
                        event.get("subtest", {}).get("parameters")))
            runs[width, index] = directory
    return root, env, outcomes, runs


def test_real_one_two_four_shards_preserve_occurrences_outcomes_and_subtests(campaign):
    _, _, outcomes, runs = campaign
    expected = sorted(outcomes[1], key=lambda row: row[0])
    assert sorted(outcomes[2], key=lambda row: row[0]) == expected
    assert sorted(outcomes[4], key=lambda row: row[0]) == expected
    full = read(runs[1, 0] / "reference/reference.json")["full_inventory"]
    assert len(full) == 10 and len(set(full)) == 9
    for width in (1, 2, 4):
        indices = []
        for index in range(width):
            data = read(runs[width, index] / "partition/selection.json")
            assert data["full_inventory"] == full
            indices.extend(data["selected_occurrences"])
        assert sorted(indices) == list(range(len(full)))


def matrix(campaign, destination):
    """Synthetic cross-OS metadata over real Linux runs, not a Windows run."""
    root, env, _, runs = campaign
    destination.mkdir()
    for name, count in (("ubuntu-22.04", 1), ("windows-latest", 4)):
        for index in range(count):
            target = destination / f"task-swarm-shard-{name}-{index}-123-1"
            shutil.copytree(runs[count, index], target)
            if name == "windows-latest":
                path = target / "partition/selection.json"
                selected = read(path)
                selected["shard"]["os"] = name
                save(path, selected)
                event_path = target / "observation/events.jsonl"
                events = [json.loads(line) for line in event_path.read_bytes().splitlines()]
                events[0]["run"]["RUNNER_OS"] = "Windows"
                events[0]["environment"]["system"] = "Windows"
                raw = b"".join(encoded(e) for e in events)
                event_path.write_bytes(raw)
                final_path = target / "observation/final.json"
                final = read(final_path)
                final.update(events_sha256=hashlib.sha256(raw).hexdigest(), stream_bytes=len(raw))
                save(final_path, final)
                if index == 0:
                    reference = target / "reference/reference.json"
                    value = read(reference)
                    value["os"] = name
                    save(reference, value)
            rebind_completion(target)
    return root, env


def rebind_completion(target):
    path = target / "completion.json"
    value = read(path)
    value["shard"] = read(target / "partition/selection.json")["shard"]
    value["selection_sha256"] = hashlib.sha256((target / "partition/selection.json").read_bytes()).hexdigest()
    value["final_sha256"] = hashlib.sha256((target / "observation/final.json").read_bytes()).hexdigest()
    save(path, value)


def rewrite_session(target, mutate):
    path = target / "observation/events.jsonl"
    rows = [json.loads(line) for line in path.read_bytes().splitlines()]
    mutate(rows[0])
    raw = b"".join(encoded(row) for row in rows)
    path.write_bytes(raw)
    final_path = target / "observation/final.json"
    final = read(final_path)
    final.update(events_sha256=hashlib.sha256(raw).hexdigest(), stream_bytes=len(raw))
    save(final_path, final)


@pytest.mark.parametrize("change", ["none", "missing", "extra", "duplicate", "selected", "full", "reference",
    "source", "all_stale", "lock", "selector", "run", "attempt", "footer", "exit", "postcheck",
    "raw_source", "typed_version", "typed_index", "typed_count",
    "failure", "skipped", "cancelled", "absent_result"])
def test_matrix_requires_current_complete_independent_coverage(campaign, tmp_path, change):
    destination = tmp_path / "artifacts"
    root, env = matrix(campaign, destination)
    target = destination / "task-swarm-shard-windows-latest-0-123-1"
    selection = target / "partition/selection.json"
    doc = read(selection)
    if change == "missing":
        shutil.rmtree(target)
    elif change == "extra":
        (destination / "unknown").mkdir()
    elif change in ("duplicate", "selected", "full"):
        if change == "duplicate": doc["selected_occurrences"].append(doc["selected_occurrences"][0])
        elif change == "selected": doc["selected_occurrences"][0] += 1
        else:
            doc["full_inventory"].pop()
            doc["inventory_sha256"] = hashlib.sha256(encoded(doc["full_inventory"])).hexdigest()
        save(selection, doc)
        rebind_completion(target)
    elif change == "reference":
        path = target / "reference/reference.json"
        value = read(path)
        value["full_inventory"].reverse()
        value["inventory_sha256"] = hashlib.sha256(encoded(value["full_inventory"])).hexdigest()
        save(path, value)
    elif change in ("source", "lock", "selector", "run", "attempt", "all_stale"):
        documents = list(destination.glob("*/partition/selection.json")) if change == "all_stale" else [selection]
        for path in documents:
            value = read(path)
            if change in ("source", "all_stale", "lock", "selector"):
                key = {"source": "checkout_sha", "all_stale": "checkout_sha", "lock": "lock_sha256", "selector": "selector_sha256"}[change]
                value["context"]["source"][key] = "0" * (40 if "sha256" not in key else 64)
            else:
                value["context"]["run"]["GITHUB_RUN_ID" if change == "run" else "GITHUB_RUN_ATTEMPT"] = "99"
            save(path, value)
            if change == "all_stale":
                shard_root = path.parent.parent
                rewrite_session(shard_root, lambda row: row["source"].update(checkout_sha="0" * 40))
                for other in (shard_root / "reference/reference.json", shard_root / "completion.json"):
                    if other.exists():
                        old = read(other)
                        old["context"] = value["context"]
                        save(other, old)
            rebind_completion(path.parent.parent)
    elif change == "raw_source":
        rewrite_session(target, lambda row: row["source"].update(checkout_sha="0" * 40))
        rebind_completion(target)
    elif change.startswith("typed_"):
        if change == "typed_version": doc["version"] = True
        elif change == "typed_index": doc["shard"]["index"] = False
        else: doc["shard"]["count"] = 4.0
        save(selection, doc)
        rebind_completion(target)
    elif change == "footer":
        (target / "observation/final.json").unlink()
    elif change == "exit":
        path = target / "observation/final.json"
        value = read(path)
        value["pytest_exit_code"] = 1
        save(path, value)
        rebind_completion(target)
    elif change == "postcheck":
        path = target / "completion.json"
        value = read(path)
        value["demo"] = "skipped"
        save(path, value)
    elif change in ("failure", "skipped", "cancelled", "absent_result"):
        env = {**env, "MATRIX_RESULT": "" if change == "absent_result" else change}
    result = run(root, [sys.executable, "-B", "tools/pytest_ci_shards.py", "verify", str(destination)], env,
                 expected=0 if change == "none" else 3)
    if change == "none":
        assert json.loads(result.stdout) == {"complete": True, "shards": 5, "occurrences_per_os": 10}


@pytest.mark.parametrize("option", ["keyword", "invalid_index", "empty", "failed_subtest"])
def test_selector_refuses_filters_invalid_or_incomplete_execution(campaign, tmp_path, option):
    root, env, _, _ = campaign
    env = {**env, "KOTODAMA_CI_SHARD_OS": "ubuntu-22.04", "KOTODAMA_CI_SHARD_INDEX": "0",
           "KOTODAMA_CI_SHARD_COUNT": "1", "KOTODAMA_CI_SHARD_DIR": str(tmp_path / "partition"),
           "KOTODAMA_CI_OBSERVATION_DIR": str(tmp_path / "observation"),
           "PYTEST_PLUGINS": "tools.pytest_ci_observer,tools.pytest_ci_shards"}
    command = list(COMMAND)
    if option == "keyword": command.extend(["-k", "capture"])
    elif option == "invalid_index": env["KOTODAMA_CI_SHARD_INDEX"] = "1"
    elif option == "empty":
        env.update(KOTODAMA_CI_SHARD_COUNT="4", KOTODAMA_CI_SHARD_INDEX="3", FIXTURE_SMALL="yes")
    else: env["FIXTURE_FAIL"] = "yes"
    run(root, command, env, expected={"failed_subtest": 1, "empty": 3}.get(option, 4))
    if option == "failed_subtest":
        run(root, [sys.executable, "-B", "tools/pytest_ci_shards.py", "seal", str(tmp_path),
                   "--demo", "success", "--benchmark", "success"], env, expected=3)
