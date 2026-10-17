"""Explicit CI occurrence partition and complete-matrix verification.

The ordinary observer and product schedulers are unchanged. No shard is a
complete suite: only the independent reference plus every shard can establish
coverage. Reference collection does not load this module as a pytest plugin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 2 * 1024 * 1024
MAX_ITEMS = 5000
OS_NAMES = {"ubuntu-22.04": "Linux", "windows-latest": "Windows"}
MATRIX = (*(("ubuntu-22.04", i, 2) for i in range(2)), *(('windows-latest', i, 4) for i in range(4)))
COLLECTION_ARGS = ["-q", "-p", "no:cacheprovider", "-o", "python_files=test_task_swarm_*.py", "tests"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def encoded(value):
    return (json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def read(path):
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_BYTES + 1)
    require(len(raw) <= MAX_BYTES, "shard evidence exceeds capacity")
    return json.loads(raw)


def write(path, value):
    raw = encoded(value)
    require(len(raw) <= MAX_BYTES, "shard evidence exceeds capacity")
    with Path(path).open("xb") as stream:
        stream.write(raw)


def context():
    def revision(ref):
        return subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, timeout=5, text=True).strip()
    run = {key: os.environ.get(key) for key in (
        "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_SHA", "KOTODAMA_CI_HEAD_SHA")}
    require(all(isinstance(x, str) and x for x in run.values()), "current CI identity is required")
    head = revision("HEAD")
    require(head == run["GITHUB_SHA"], "checkout differs from the current workflow source")
    return {"source": {"checkout_sha": head, "checkout_tree": revision("HEAD^{tree}"),
        "lock_sha256": sha((ROOT / "requirements-task-swarm-ci.txt").read_bytes()),
        "observer_sha256": sha((ROOT / "tools/pytest_ci_observer.py").read_bytes()),
        "selector_sha256": sha(Path(__file__).read_bytes())},
        "run": run, "python": platform.python_version()}


def lane():
    name = os.environ.get("KOTODAMA_CI_SHARD_OS")
    index, count = (os.environ.get(key, "") for key in ("KOTODAMA_CI_SHARD_INDEX", "KOTODAMA_CI_SHARD_COUNT"))
    require(name in OS_NAMES and index in ("0", "1", "2", "3") and count in ("1", "2", "4"),
            "invalid shard settings")
    require(int(index) < int(count), "invalid shard index")
    return {"os": name, "index": int(index), "count": int(count)}


def inventory(items):
    nodes = [item.nodeid for item in items]
    require(0 < len(nodes) <= MAX_ITEMS and all(isinstance(n, str) and 0 < len(n) <= 4096 for n in nodes),
            "invalid full inventory")
    return nodes


def full_selection(config):
    require(Path(config.rootpath).resolve() == ROOT and config.args == ["tests"]
            and config.getini("python_files") == ["test_task_swarm_*.py"], "full Task swarm collection is required")
    for option in ("keyword", "markexpr", "deselect", "ignore", "ignore_glob", "lf", "failedfirst"):
        require(not getattr(config.option, option, None), "additional test selection is refused")


class Selector:
    def __init__(self, config):
        full_selection(config)
        require(not config.option.collectonly, "selector is execution-only")
        self.config, self.identity, self.shard = config, context(), lane()
        self.directory = Path(os.environ["KOTODAMA_CI_SHARD_DIR"])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.nodes = self.indices = None

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_modifyitems(self, session, config, items):
        original = list(items)
        result = yield
        require(items == original, "another plugin changed the full collection")
        self.nodes = inventory(items)
        self.indices = list(range(self.shard["index"], len(items), self.shard["count"]))
        require(self.indices, "empty shard is refused")
        items[:] = [original[index] for index in self.indices]
        return result

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_collection_finish(self, session):
        result = yield
        require(self.indices is not None and [i.nodeid for i in session.items]
                == [self.nodes[i] for i in self.indices], "selected execution order changed")
        write(self.directory / "selection.json", {"version": 1, "kind": "task_swarm_shard",
            "context": self.identity, "shard": self.shard, "full_inventory": self.nodes,
            "inventory_sha256": sha(encoded(self.nodes)), "selected_occurrences": self.indices})
        return result


def pytest_configure(config):
    try:
        config.pluginmanager.register(Selector(config), "kotodama-ci-selector")
    except (OSError, ValueError, KeyError) as exc:
        raise pytest.UsageError(str(exc)) from exc


def reference(directory):
    """Separate ordinary collect-only invocation; no selector or observer."""
    require(not os.environ.get("PYTEST_PLUGINS") and not os.environ.get("PYTEST_ADDOPTS"),
            "reference collection cannot inherit plugins or options")
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=False)
    identity, shard = context(), lane()
    require(shard["index"] == 0, "reference belongs to shard zero")
    records = []

    class Reference:
        def pytest_collection_finish(self, session):
            full_selection(session.config)
            records.append(inventory(session.items))

    previous = Path.cwd()
    try:
        os.chdir(ROOT)
        status = pytest.main(["--collect-only", *COLLECTION_ARGS], plugins=[Reference()])
    finally:
        os.chdir(previous)
    require(status == 0 and len(records) == 1 and identity == context(), "reference collection failed or changed")
    write(destination / "reference.json", {"version": 1, "kind": "task_swarm_reference",
        "context": identity, "os": shard["os"], "full_inventory": records[0],
        "inventory_sha256": sha(encoded(records[0]))})


def observation(directory, expected, shard):
    if __package__:
        from .pytest_ci_observer import verify
    else:
        from pytest_ci_observer import verify
    final = verify(directory)
    require(final["pytest_exit_code"] == 0, "a failed observation cannot satisfy the gate")
    nodes = []
    with (Path(directory) / "events.jsonl").open("rb") as stream:
        first = json.loads(next(stream))
        for raw in stream:
            event = json.loads(raw)
            if event["kind"] == "collected":
                nodes.append(event["nodeid"])
    source = {k: v for k, v in expected["source"].items() if k != "selector_sha256"}
    require(first["source"] == source and all(first["run"].get(k) == v for k, v in expected["run"].items())
            and first["run"].get("RUNNER_OS") == OS_NAMES[shard["os"]]
            and first["environment"]["system"] == OS_NAMES[shard["os"]]
            and first["environment"]["python"] == expected["python"]
            and first["selection"] == {"python_files": ["test_task_swarm_*.py"], "collect_only": False},
            "observation does not belong to the current source, run or OS")
    return nodes, final


def selected(directory, expected, shard):
    document = read(Path(directory) / "partition/selection.json")
    require(type(document["version"]) is int and document["version"] == 1
            and document["kind"] == "task_swarm_shard" and document["context"] == expected
            and encoded(document["shard"]) == encoded(shard), "shard identity changed")
    full = document["full_inventory"]
    require(isinstance(full, list) and 0 < len(full) <= MAX_ITEMS
            and all(isinstance(n, str) and 0 < len(n) <= 4096 for n in full)
            and document["inventory_sha256"] == sha(encoded(full)), "invalid full inventory")
    indices = list(range(shard["index"], len(full), shard["count"]))
    require(indices and document["selected_occurrences"] == indices
            and all(type(i) is int for i in document["selected_occurrences"]), "partition is not the exact occurrence slice")
    actual, final = observation(Path(directory) / "observation", expected, shard)
    require(actual == [full[i] for i in indices], "observed execution differs from assigned occurrences")
    return document, final


def seal(directory, demo, benchmark):
    directory = Path(directory)
    expected, shard = context(), lane()
    selected(directory, expected, shard)
    outcome = "success" if shard["index"] == 0 else "skipped"
    require(demo == benchmark == outcome, "required shard-zero demo or benchmark did not succeed")
    write(directory / "completion.json", {"version": 1, "context": expected, "shard": shard,
        "selection_sha256": sha((directory / "partition/selection.json").read_bytes()),
        "final_sha256": sha((directory / "observation/final.json").read_bytes()),
        "demo": demo, "benchmark": benchmark})


def verify_matrix(directory, matrix_result):
    require(matrix_result == "success", "every current matrix job must succeed")
    directory, expected = Path(directory), context()
    suffix = expected["run"]["GITHUB_RUN_ID"] + "-" + expected["run"]["GITHUB_RUN_ATTEMPT"]
    names = {f"task-swarm-shard-{name}-{index}-{suffix}": {"os": name, "index": index, "count": count}
             for name, index, count in MATRIX}
    require({p.name for p in directory.iterdir()} == set(names), "matrix artifacts are missing, extra or stale")
    references, seen = {}, {name: [] for name in OS_NAMES}
    full_by_os = {}
    for name, shard in names.items():
        root = directory / name
        allowed = {"partition", "observation", "completion.json"}
        if shard["index"] == 0:
            allowed.add("reference")
        require({p.name for p in root.iterdir()} == allowed, "unrecognized shard evidence")
        document, _ = selected(root, expected, shard)
        full = document["full_inventory"]
        prior = full_by_os.setdefault(shard["os"], full)
        require(prior == full, "full collection differs between shards")
        seen[shard["os"]].extend(document["selected_occurrences"])
        completion = read(root / "completion.json")
        outcome = "success" if shard["index"] == 0 else "skipped"
        require(encoded(completion) == encoded({"version": 1, "context": expected, "shard": shard,
            "selection_sha256": sha((root / "partition/selection.json").read_bytes()),
            "final_sha256": sha((root / "observation/final.json").read_bytes()),
            "demo": outcome, "benchmark": outcome}), "shard completion or required post-checks changed")
        if shard["index"] == 0:
            reference_doc = read(root / "reference/reference.json")
            require(encoded(reference_doc) == encoded({"version": 1, "kind": "task_swarm_reference", "context": expected,
                "os": shard["os"], "full_inventory": full, "inventory_sha256": sha(encoded(full))}),
                "independent reference differs from the full shard inventory")
            references[shard["os"]] = full
    require(len(references) == 2 and references["ubuntu-22.04"] == references["windows-latest"],
            "full ordered inventory differs between OS")
    for name, full in references.items():
        require(sorted(seen[name]) == list(range(len(full))), "occurrences are missing or repeated")
    return {"complete": True, "shards": len(names), "occurrences_per_os": len(references["ubuntu-22.04"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("reference").add_argument("directory")
    complete = commands.add_parser("seal")
    complete.add_argument("directory")
    complete.add_argument("--demo", required=True)
    complete.add_argument("--benchmark", required=True)
    commands.add_parser("verify").add_argument("directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "reference":
            reference(args.directory)
        elif args.command == "seal":
            seal(args.directory, args.demo, args.benchmark)
        else:
            print(json.dumps(verify_matrix(args.directory, os.environ.get("MATRIX_RESULT"))))
        return 0
    except (OSError, ValueError, KeyError, IndexError, TypeError, StopIteration, subprocess.SubprocessError):
        print('{"complete":false,"reason":"missing_or_invalid_shard_evidence"}')
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
