#!/usr/bin/env python3
"""Opt-in, unqualified Linux unittest runner; the mandatory CI command is unchanged."""
from __future__ import annotations

import argparse
from collections import Counter, deque
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
try:
    import resource
except ImportError:  # Optional runner refuses unsupported platforms explicitly.
    resource = None
import signal
import subprocess
import sys
import threading
import time
import traceback
import unittest

SCRIPT = Path(__file__).resolve()
MAX_TIMEOUT = 1200
JSON_BYTES_LIMIT = 16 * 1024 * 1024
EVENT_LINE_LIMIT = 1024 * 1024
EVENT_STREAM_LIMIT = 64 * 1024 * 1024


class RunnerError(RuntimeError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(detail)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def save(path, value):
    temporary = path.with_name(path.name + ".pending")
    temporary.write_text(encoded(value) + "\n", encoding="utf-8")
    temporary.replace(path)


def finite_number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key')
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs)


def read_json(path):
    with path.open('rb') as stream:
        data = stream.read(JSON_BYTES_LIMIT + 1)
    if len(data) > JSON_BYTES_LIMIT:
        raise RunnerError('JSON_LIMIT', 'saved JSON exceeds 16 MiB')
    return strict_json(data.decode('utf-8'))


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE,
                                   timeout=15).decode("utf-8").strip()


def source(root):
    if git(root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise RunnerError("SOURCE_DIRTY", "commit the source; put results outside its checkout")
    return {"head": git(root, "rev-parse", "HEAD"), "tree": git(root, "rev-parse", "HEAD^{tree}")}


def environment():
    # No plaintext environment values/credentials are emitted. Dependency code
    # bytes are not independently attested by this name/version inventory.
    return {"python": sys.version, "executable": str(Path(sys.executable).resolve()),
            "invoked_executable": sys.executable, "prefix": sys.prefix,
            "distributions": sorted([d.metadata.get("Name", ""), d.version]
                                    for d in importlib.metadata.distributions()),
            "environment_sha256": hashlib.sha256(encoded(dict(os.environ)).encode()).hexdigest()}


def discover(root):
    os.chdir(root)
    sys.path.insert(0, str(root))
    loader = unittest.TestLoader()
    suite = loader.discover(str(root / "tests"), pattern="test*.py")
    cases, unsupported = [], []

    def visit(node):
        if isinstance(node, unittest.TestSuite):
            if type(node) is not unittest.TestSuite:
                unsupported.append("custom suite: " + type(node).__qualname__)
            for item in node:
                visit(item)
        elif isinstance(node, unittest.TestCase):
            cases.append(node)
        else:
            raise RunnerError("DISCOVERY_UNSUPPORTED", "discovered object is not a unittest case/suite")
    visit(suite)
    for error in loader.errors:
        print(error, file=sys.stderr)
    for name, module in list(sys.modules.items()):
        if hasattr(module, "load_tests") and getattr(module, "__file__", None):
            try:
                Path(module.__file__).resolve().relative_to(root / "tests")
            except ValueError:
                continue
            unsupported.append("load_tests: " + name)
    counts, rows, blocks = Counter(), [], []
    for case in cases:
        identifier = case.id()
        counts[identifier] += 1
        module = case.__class__.__module__
        if not blocks or blocks[-1]["module"] != module:
            blocks.append({"number": len(blocks), "module": module, "indices": []})
        index = len(rows)
        blocks[-1]["indices"].append(index)
        rows.append({"index": index, "id": identifier, "ordinal": counts[identifier],
                     "module": module, "class": module + "." + case.__class__.__qualname__,
                     "block": blocks[-1]["number"]})
    if not rows:
        raise RunnerError("EMPTY_DISCOVERY", "no tests were discovered")
    return suite, cases, {"occurrences": rows, "blocks": blocks,
                          "parallel_unsupported": sorted(set(unsupported)),
                          "discovery_error_count": len(loader.errors)}


def partitions(plan, workers):
    weights = Counter(row["module"] for row in plan["occurrences"])
    loads, assigned = [0] * workers, {}
    for name in sorted(weights, key=lambda name: (-weights[name], name)):
        target = min(range(workers), key=lambda i: (loads[i], i))
        assigned[name] = target
        loads[target] += weights[name]
    return [[b["number"] for b in plan["blocks"] if assigned[b["module"]] == i]
            for i in range(workers) if loads[i]]


class RecordedResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity, *, event_stream, rows, dynamic_order=False):
        super().__init__(stream, descriptions, verbosity)
        self.event_stream, self.pending = event_stream, deque(rows)
        self.active, self.block = None, rows[0]["block"]
        self.sequences = Counter()
        self.dynamic_order, self.setup_refusals = dynamic_order, {}

    def emit(self, kind, test=None, **extra):
        self.sequences[self.block] += 1
        row = {"kind": kind, "id": test.id() if test is not None else None,
               "sequence": self.sequences[self.block],
               "ordinal": self.active["ordinal"] if self.active else None,
               "index": self.active["index"] if self.active else None,
               "block": self.block, "monotonic": time.monotonic(), **extra}
        self.event_stream.write(encoded(row) + "\n")
        self.event_stream.flush()

    def startTest(self, test):
        row = next((r for r in self.pending if r['id'] == test.id()), None) if self.dynamic_order else (self.pending[0] if self.pending else None)
        if row is None or row['id'] != test.id():
            raise RunnerError("RESULT_ID_MISMATCH", "test start differs from discovered occurrences")
        if self.dynamic_order:
            self.setup_refusals = {cause: fact for cause, fact in self.setup_refusals.items() if row[fact[0]] != fact[1]}
        self.pending.remove(row)
        self.active = row
        self.block = self.active["block"]
        super().startTest(test)
        self.emit("start", test, ordinal=self.active["ordinal"])

    def stopTest(self, test):
        self.emit("stop", test)
        super().stopTest(test)
        self.active = None

    def fixture_block(self, test):
        if self.active is None and self.pending:
            first = next((row for row in self.pending if test.id() in {"setUpModule (" + row["module"] + ")", "setUpClass (" + row["class"] + ")"}), self.pending[0]) if self.dynamic_order else self.pending[0]
            if test.id() in {"setUpModule (" + first["module"] + ")", "setUpClass (" + first["class"] + ")"}:
                self.block = first["block"]

    def fixture_refusal(self, test):
        # Only actual setup errors/skips explain omitted planned cases. Restrict
        # to the first contiguous class/module block: A/B/A must reenter A.
        if self.active is not None or not self.pending:
            return
        first = next((row for row in self.pending if test.id() in {"setUpModule (" + row["module"] + ")", "setUpClass (" + row["class"] + ")"}), self.pending[0]) if self.dynamic_order else self.pending[0]
        target = test.id()
        if target == "setUpModule (" + first["module"] + ")":
            key = "module"
        elif target == "setUpClass (" + first["class"] + ")":
            key = "class"
        else:
            return
        self.block = first["block"]
        if self.dynamic_order:
            self.setup_refusals[target] = (key, first[key], tuple(row['index'] for row in self.pending if row[key] == first[key]))
            return
        while self.pending and self.pending[0]["block"] == first["block"] and self.pending[0][key] == first[key]:
            row = self.pending.popleft()
            self.emit("blocked", cause=target, planned_index=row["index"],
                      planned_id=row["id"], ordinal=row["ordinal"])

    def finish_pending(self):
        # A custom suite's run order need not match its iteration order. Keep
        # that original run intact; only real scoped setup refusal can account
        # for a discovered occurrence that never received startTest.
        if self.dynamic_order:
            for row in list(self.pending):
                refused = next(((cause, key) for cause, (key, value, candidates) in self.setup_refusals.items() if row[key] == value and candidates == (row['index'],)), None)
                if refused is None:
                    raise RunnerError('RESULT_INCOMPLETE', 'custom unstarted occurrence has no unambiguous current setup refusal')
                cause, _ = refused
                self.pending.remove(row)
                self.block = row['block']
                self.emit('blocked', cause=cause, planned_index=row['index'],
                          planned_id=row['id'], ordinal=row['ordinal'])

    def addSuccess(self, test):
        super().addSuccess(test)
        self.emit("success", test)

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.fixture_block(test)
        self.emit("skip", test, reason=reason,
                  parent=test.test_case.id() if isinstance(test, unittest.case._SubTest) else None)
        self.fixture_refusal(test)

    def error(self, kind, test, err):
        self.emit(kind, test, exception=err[0].__name__, message=str(err[1]),
                  traceback=self._exc_info_to_string(err, test))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.error("failure", test, err)

    def addError(self, test, err):
        super().addError(test, err)
        self.fixture_block(test)
        self.error("error", test, err)
        self.fixture_refusal(test)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self.error("expected_failure", test, err)

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self.emit("unexpected_success", test)

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        self.emit("subtest", subtest, parent=test.id(),
                  outcome="success" if err is None else "failure" if issubclass(err[0], test.failureException) else "error",
                  traceback=None if err is None else self._exc_info_to_string(err, test))


def collect_worker(root, output):
    """Discovery imports run in an owned process under the parent's deadline."""
    try:
        pinned = source(root)
        _, _, plan = discover(root)
        if source(root) != pinned:
            raise RunnerError('SOURCE_CHANGED', 'discovery changed source')
        save(output / 'collected.json', {'source': pinned, 'discovery': plan})
        return 0
    except BaseException as exc:
        traceback.print_exc()
        save(output / 'collection-error.json', {'code': getattr(exc, 'code', 'DISCOVERY_ERROR'), 'detail': str(exc)})
        return 2


def worker(root, output, plan_path, assignment, sequential):
    started = time.monotonic()
    report = {"completed": False}
    try:
        manifest = read_json(plan_path)
        if source(root) != manifest["source"] or hashlib.sha256(SCRIPT.read_bytes()).hexdigest() != manifest["runner_sha256"]:
            raise RunnerError("SOURCE_CHANGED", "worker source/runner differs from parent pin")
        observed_environment = environment()
        expected_environment = {**manifest["environment"], "environment_sha256": manifest["worker_environment_sha256"][str(output.name)]}
        if observed_environment != expected_environment:
            raise RunnerError("ENVIRONMENT_CHANGED", "worker interpreter/environment differs from parent pin")
        suite, cases, plan = discover(root)
        if plan != manifest["discovery"]:
            raise RunnerError("DISCOVERY_CHANGED", "worker discovery differs from parent occurrences")
        selected = [b for b in plan["blocks"] if b["number"] in assignment]
        if [b["number"] for b in selected] != assignment:
            raise RunnerError("ASSIGNMENT_INVALID", "unknown/duplicate/unordered blocks")
        rows = [plan["occurrences"][i] for b in selected for i in b["indices"]]
        with (output / "events.jsonl").open("w", encoding="utf-8") as events:
            runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=2,
                resultclass=lambda s, d, v: RecordedResult(s, d, v, event_stream=events, rows=rows, dynamic_order=sequential and bool(plan['parallel_unsupported'])))
            if sequential:
                if assignment != [b["number"] for b in plan["blocks"]]:
                    raise RunnerError("ASSIGNMENT_INVALID", "sequential suite must retain all occurrences")
                result = runner.run(suite)  # original loader object, unfiltered
            else:
                # A top-level suite per contiguous defining-module block forces
                # real teardown/reentry even when intervening modules are in the
                # other shard. Test instances and their execution order are kept.
                class Blocks(unittest.TestSuite):
                    def run(self, result, debug=False):
                        for b in selected:
                            result._previousTestClass = None
                            result.block = b["number"]
                            unittest.TestSuite(cases[i] for i in b["indices"]).run(result)
                        return result
                result = runner.run(Blocks())
            result.finish_pending()
            if result.pending:
                raise RunnerError("RESULT_INCOMPLETE", "case omitted without actual setup refusal")
        if source(root) != manifest["source"]:
            raise RunnerError("SOURCE_CHANGED", "test changed tracked source")
        report.update(completed=True, successful=result.wasSuccessful(), tests_run=result.testsRun,
                      failures=len(result.failures), errors=len(result.errors), skips=len(result.skipped),
                      expected_failures=len(result.expectedFailures), unexpected_successes=len(result.unexpectedSuccesses))
    except BaseException as exc:
        report.update(code=getattr(exc, "code", "WORKER_EXCEPTION"), exception=type(exc).__name__,
                      detail=str(exc), traceback=traceback.format_exc())
        traceback.print_exc()
    report.update(wall_seconds=time.monotonic() - started,
                  cpu_self_seconds=resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime,
                  cpu_reaped_children_seconds=resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime)
    save(output / "result.json", report)
    return 0 if report.get("completed") and report.get("successful") else 1


def stat(pid):
    try:
        tail = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return {"state": tail[0], "ppid": int(tail[1]), "pgrp": int(tail[2]),
                "start": tail[19], "rss": int(tail[21]) * os.sysconf("SC_PAGE_SIZE")}
    except (OSError, ValueError, IndexError):
        return None


class Observer:
    """Observed aggregate peak, not an upper bound; wait follows full scan."""
    def __init__(self, path):
        self.path, self.stop = path, threading.Event()
        self.known, self.seen_workers, self.peak = {}, set(), 0
        self.error = None
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.sample, daemon=True)

    def rows(self):
        rows = {}
        with os.scandir('/proc') as entries:
            for entry in entries:
                if entry.name.isdecimal():
                    value = stat(int(entry.name))
                    if value is not None:
                        rows[int(entry.name)] = value
        with self.lock:
            owned = {pid for pid, start in self.known.items() if pid in rows and rows[pid]['start'] == start}
        owned.add(os.getpid())
        while True:
            added = {pid for pid, value in rows.items() if value['ppid'] in owned} - owned
            if not added:
                break
            owned.update(added)
        result = {pid: rows[pid] for pid in owned if pid in rows}
        with self.lock:
            self.known.update({pid: value['start'] for pid, value in result.items()})
        return result

    def register(self, process):
        value = stat(process.pid)
        if value is not None:
            with self.lock:
                self.known[process.pid] = value['start']
                self.seen_workers.add(process.pid)
        return value

    def sample(self):
        try:
            with self.path.open('w', encoding='utf-8') as stream:
                while not self.stop.is_set():
                    started = time.monotonic()
                    rows = self.rows()
                    if os.getpid() not in rows:
                        raise RunnerError('RSS_UNAVAILABLE', 'cannot observe orchestrator')
                    total = sum(row['rss'] for row in rows.values())
                    self.peak = max(self.peak, total)
                    stream.write(encoded({'monotonic': time.monotonic(), 'rss_bytes': total,
                                          'scan_seconds': time.monotonic() - started,
                                          'owned_processes': [{'pid': pid, 'start': row['start'], 'state': row['state'], 'rss_bytes': row['rss']} for pid, row in sorted(rows.items())]}) + '\n')
                    stream.flush()
                    self.stop.wait(.02)
        except BaseException as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            self.error = 'observer did not converge'


def subreaper():
    library = ctypes.CDLL(None, use_errno=True)
    if library.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER, own process only
        raise RunnerError('OWNERSHIP_UNAVAILABLE', 'cannot establish child reaping')


def cleanup(jobs, observer):
    errors = []
    for sig in (signal.SIGTERM, signal.SIGKILL):
        rows = observer.rows()
        for process, start in jobs:
            current = stat(process.pid)
            # poll(None) means this unreaped Popen child still belongs to us;
            # its PID cannot be reused while it is alive/unreaped. Missing stat
            # remains a measurement failure, never a fabricated RSS value.
            if process.poll() is None and (current is None or start is None or current['start'] == start):
                try:
                    os.killpg(process.pid, sig)
                except ProcessLookupError:
                    pass
        for pid, row in rows.items():
            current = stat(pid)
            if pid != os.getpid() and row['state'] != 'Z' and current is not None and current['start'] == row['start']:
                try:
                    os.kill(pid, sig)
                except ProcessLookupError:
                    pass
        until = time.monotonic() + 1
        while time.monotonic() < until:
            if not any(row['state'] != 'Z' for pid, row in observer.rows().items() if pid != os.getpid()):
                break
            time.sleep(.02)
    for process, _ in jobs:
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            errors.append('worker not reaped: ' + str(process.pid))
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
        except ChildProcessError:
            break
    remaining = observer.rows()
    if any(pid != os.getpid() for pid in remaining):
        errors.append('owned descendants remain: ' + encoded(remaining))
    return errors


def read_events(path):
    events, error = [], None
    if path.exists():
        with path.open('rb') as stream:
            total = 0
            while True:
                line = stream.readline(EVENT_LINE_LIMIT + 1)
                if not line:
                    break
                total += len(line)
                try:
                    if total > EVENT_STREAM_LIMIT or len(line) > EVENT_LINE_LIMIT or not line.endswith(b'\n'):
                        raise ValueError('invalid/incomplete event line')
                    event = strict_json(line.decode('utf-8'))
                    if not isinstance(event, dict) or not isinstance(event.get('kind'), str):
                        raise ValueError('event is not an object with a kind')
                    events.append(event)
                except (UnicodeError, ValueError) as exc:
                    error = str(exc)
                    break
    return events, error


def validate_events(events, expected, report, *, dynamic_order=False):
    # Callback order, per-block sequence and the canonical occurrence queue are
    # independent of shard boundaries. A missing success is never an inference.
    pending, active = deque(expected), None
    counts, sequences, terminal = Counter(), Counter(), Counter()
    negative_subtest = False
    refusal = None
    dynamic_refusals = {}
    fixture_ids = {block: {prefix + " (" + row[key] + ")"
                          for row in expected.values() if row['block'] == block
                          for prefix, key in (("setUpModule", "module"), ("tearDownModule", "module"),
                                              ("setUpClass", "class"), ("tearDownClass", "class"))}
                   for block in {r['block'] for r in expected.values()}}
    def invalid(detail):
        raise RunnerError('RESULT_INVALID', detail)
    def identity(event, index, *, subtest=False):
        row = expected[index]
        if type(event.get('ordinal')) is not int or event['ordinal'] != row['ordinal'] or event['block'] != row['block']:
            raise RunnerError('RESULT_ID_MISMATCH', 'outcome differs from planned occurrence')
        if subtest:
            if event.get('parent') != row['id'] or not isinstance(event.get('id'), str) or not event['id'].startswith(row['id'] + ' '):
                invalid('invalid subtest identity/parent')
        elif event.get('id') != row['id']:
            raise RunnerError('RESULT_ID_MISMATCH', 'unknown outcome identity')
    for event in events:
        kind, index, block = event['kind'], event.get('index'), event.get('block')
        if (not isinstance(event.get('id'), (str, type(None))) or
                type(event.get('index')) not in (int, type(None)) or
                type(event.get('ordinal')) not in (int, type(None)) or
                not finite_number(event.get('monotonic'))):
            invalid('invalid common event fields')
        if type(block) is not int or block not in fixture_ids or type(event.get('sequence')) is not int or event['sequence'] != sequences[block] + 1:
            invalid('missing/duplicate/unordered event sequence')
        sequences[block] += 1
        if kind == 'start':
            if active is not None or type(index) is not int or index not in pending or (not dynamic_order and index != pending[0]):
                invalid('nested/unknown/out-of-order test start')
            identity(event, index)
            if dynamic_order:
                row = expected[index]
                dynamic_refusals = {cause: fact for cause, fact in dynamic_refusals.items() if row[fact[2]] != fact[3]}
            pending.remove(index)
            active, terminal, negative_subtest, refusal = index, Counter(), False, None
            counts['tests_run'] += 1
        elif kind == 'stop':
            if type(index) is not int or active != index:
                invalid('unmatched test stop')
            identity(event, index)
            if not terminal and not negative_subtest:
                raise RunnerError('RESULT_INCOMPLETE', 'case has no actual terminal outcome')
            active = None
        elif kind == 'blocked':
            index = event.get('planned_index')
            if active is not None or type(index) is not int or index not in pending or (not dynamic_order and index != pending[0]):
                invalid('unknown/duplicate/out-of-order blocked case')
            row = expected[index]
            current_refusal = dynamic_refusals.get(event.get('cause')) if dynamic_order and isinstance(event.get('cause'), str) else refusal
            if current_refusal is None:
                invalid('blocked case lacks actual setup error/skip')
            cause, refused_block, key, value = current_refusal[:4]
            if dynamic_order and current_refusal[4] != (index,):
                invalid('custom blocked range is not unambiguously attributable')
            if event.get('index') is not None or event.get('id') is not None or event.get('cause') != cause or (not dynamic_order and block != refused_block) or row[key] != value or event.get('planned_id') != row['id'] or type(event.get('ordinal')) is not int or event['ordinal'] != row['ordinal'] or block != row['block']:
                raise RunnerError('RESULT_ID_MISMATCH', 'blocked case differs from actual refused scope')
            pending.remove(index)
        elif index is None:
            if active is not None or event.get('ordinal') is not None or event.get('id') not in fixture_ids[block] or kind not in ('error', 'skip'):
                invalid('unknown/out-of-order fixture outcome')
            cause = event['id']
            refusal = None
            if pending:
                row = next((expected[i] for i in pending if cause in {'setUpModule (' + expected[i]['module'] + ')', 'setUpClass (' + expected[i]['class'] + ')'}), expected[pending[0]]) if dynamic_order else expected[pending[0]]
                for prefix, key in (('setUpModule', 'module'), ('setUpClass', 'class')):
                    if block == row['block'] and cause == prefix + ' (' + row[key] + ')':
                        refusal = (cause, block, key, row[key])
                        if dynamic_order:
                            dynamic_refusals[cause] = (*refusal, tuple(i for i in pending if expected[i][key] == row[key]))
            counts['errors' if kind == 'error' else 'skips'] += 1
        else:
            if type(index) is not int or index != active:
                invalid('outcome without current test')
            is_subtest = kind == 'subtest' or (kind == 'skip' and event.get('parent') is not None)
            identity(event, index, subtest=is_subtest)
            exclusive = terminal['success'] or terminal['expected_failure'] or terminal['unexpected_success']
            if exclusive:
                invalid('duplicate/conflicting outcome after terminal success/expectation')
            if kind == 'subtest':
                if terminal or event.get('outcome') not in ('success', 'failure', 'error'):
                    invalid('invalid/out-of-order subtest outcome')
                if event['outcome'] != 'success':
                    negative_subtest = True
                    counts['failures' if event['outcome'] == 'failure' else 'errors'] += 1
            elif kind == 'skip' and is_subtest:
                if terminal:
                    invalid('subtest skip after parent terminal outcome')
                negative_subtest = True
                counts['skips'] += 1
            elif kind in ('success', 'expected_failure', 'unexpected_success'):
                if terminal or negative_subtest:
                    invalid('terminal success/expectation conflicts with prior failure/skip')
                terminal[kind] += 1
                if kind != 'success':
                    counts['expected_failures' if kind == 'expected_failure' else 'unexpected_successes'] += 1
            elif kind in ('failure', 'error', 'skip'):
                # Multiple genuine teardown/cleanup errors remain legitimate.
                terminal[kind] += 1
                counts[{'failure': 'failures', 'error': 'errors', 'skip': 'skips'}[kind]] += 1
            else:
                invalid('unknown outcome kind')
    if active is not None or pending:
        raise RunnerError('RESULT_INCOMPLETE', 'missing occurrence or incomplete test')
    keys = ('tests_run', 'failures', 'errors', 'skips', 'expected_failures', 'unexpected_successes')
    if any(type(report.get(key)) is not int or report[key] != counts[key] for key in keys):
        invalid('saved counts differ from actual raw outcomes')
    successful = not (counts['failures'] or counts['errors'] or counts['unexpected_successes'])
    if report.get('successful') is not successful:
        invalid('saved success disagrees with raw outcomes')


def run(root, output, workers, timeout):
    if sys.platform != 'linux' or resource is None:
        raise RunnerError('PLATFORM_UNSUPPORTED', 'initial opt-in runner requires Linux /proc; use standard unittest on other platforms')
    if type(workers) is not int or workers not in (1, 2):
        raise RunnerError('WORKERS_INVALID', 'only one or two workers are allowed')
    if not finite_number(timeout) or not 0 < timeout <= MAX_TIMEOUT:
        raise RunnerError('TIMEOUT_INVALID', 'timeout must be finite, positive, at most 1200 seconds')
    if output == root or root in output.parents:
        raise RunnerError('OUTPUT_IN_SOURCE', 'keep immutable raw evidence outside tracked checkout')
    started = time.monotonic()
    def remaining():
        value = timeout - (time.monotonic() - started)
        if value <= 0:
            raise RunnerError('TIMEOUT', 'declared deadline expired before operation')
        return value
    cpu_self_start = resource.getrusage(resource.RUSAGE_SELF)
    cpu_children_start = resource.getrusage(resource.RUSAGE_CHILDREN)
    initial_source, initial_environment = source(root), environment()
    base_env = dict(os.environ)
    subreaper()
    output.mkdir(parents=True, exist_ok=False)
    interrupted = threading.Event()
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    for sig in previous:
        signal.signal(sig, lambda *_: interrupted.set())
    jobs, logs, failures, events, reports, collector_jobs = [], [], [], [], [], []
    observer = Observer(output / 'memory.jsonl')
    try:
        observer.thread.start()
        collection = output / 'collection'; collection.mkdir()
        collection_checkout = output / 'collection-checkout'
        subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(root), str(collection_checkout)],
                       check=True, capture_output=True, timeout=min(30, remaining()))
        subprocess.run(['git', '-C', str(collection_checkout), 'checkout', '--quiet', '--detach', initial_source['head']],
                       check=True, capture_output=True, timeout=min(15, remaining()))
        remaining()
        if interrupted.is_set():
            raise RunnerError('CANCELLED', 'stopped before collector launch')
        collection_log = (output / 'discovery.log').open('wb'); logs.append(collection_log)
        remaining()
        if interrupted.is_set():
            raise RunnerError('CANCELLED', 'stopped immediately before collector launch')
        collector = subprocess.Popen([sys.executable, '-B', str(SCRIPT), '_collect', '--root', str(collection_checkout),
                                      '--output', str(collection)], env=base_env, cwd=collection_checkout,
                                     stdout=collection_log, stderr=subprocess.STDOUT, start_new_session=True)
        observed = observer.register(collector)
        collector_jobs.append((collector, observed['start'] if observed else None))
        while collector.poll() is None:
            if interrupted.is_set() or time.monotonic() - started >= timeout:
                raise RunnerError('CANCELLED' if interrupted.is_set() else 'TIMEOUT', 'stopped during discovery imports')
            time.sleep(.02)
        if collector.returncode != 0:
            raise RunnerError('DISCOVERY_INCOMPLETE', 'owned collector did not finish; see discovery.log')
        collected_path = collection / 'collected.json'
        if collected_path.stat().st_size > 16 * 1024 * 1024:
            raise RunnerError('PLAN_LIMIT', 'discovery manifest exceeds 16 MiB')
        collected = read_json(collected_path)
        if not isinstance(collected, dict):
            raise RunnerError('PLAN_INVALID', 'collection is not an object')
        if collected['source'] != initial_source or source(root) != initial_source:
            raise RunnerError('SOURCE_CHANGED', 'discovery source differs from pinned input')
        plan = collected['discovery']
        if workers == 2 and plan['parallel_unsupported']:
            raise RunnerError('PARALLEL_UNSUPPORTED', '; '.join(plan['parallel_unsupported']))
        assignments = partitions(plan, workers)
        if workers == 1:
            assignments = [[b['number'] for b in plan['blocks']]]
        expected_worker_env = {}
        for i in range(len(assignments)):
            temp_path = str(output / ('tmp-' + str(i)))
            value = {**base_env, 'TMPDIR': temp_path, 'TMP': temp_path, 'TEMP': temp_path, 'PYTHONDONTWRITEBYTECODE': '1'}
            expected_worker_env['worker-' + str(i)] = hashlib.sha256(encoded(value).encode()).hexdigest()
        manifest = {'kind': 'repository-tests-plan/v1', 'source': initial_source,
                    'runner_sha256': hashlib.sha256(SCRIPT.read_bytes()).hexdigest(),
                    'environment': initial_environment, 'worker_environment_sha256': expected_worker_env, 'workers_requested': workers,
                    'discovery': plan, 'assignments': assignments,
                    'execution_order': 'original-custom-run' if workers == 1 and plan['parallel_unsupported'] else 'canonical-discovery',
                    'timeout_seconds': timeout, 'qualification': 'NOT_EVALUATED'}
        save(output / 'plan.json', manifest)
        for index, blocks in enumerate(assignments):
            if interrupted.is_set() or time.monotonic() - started >= timeout:
                raise RunnerError('CANCELLED' if interrupted.is_set() else 'TIMEOUT', 'stopped before worker launch')
            checkout = output / ('checkout-' + str(index))
            subprocess.run(['git', 'clone', '--quiet', '--no-hardlinks', str(root), str(checkout)],
                           check=True, capture_output=True, timeout=min(30, remaining()))
            subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', initial_source['head']],
                           check=True, capture_output=True, timeout=min(15, remaining()))
            remaining()
            if interrupted.is_set():
                raise RunnerError('CANCELLED', 'stopped before worker launch')
            child_output = output / ('worker-' + str(index)); child_output.mkdir()
            temp = output / ('tmp-' + str(index)); temp.mkdir()
            child_env = {**base_env, 'TMPDIR': str(temp), 'TMP': str(temp), 'TEMP': str(temp), 'PYTHONDONTWRITEBYTECODE': '1'}
            log = (child_output / 'raw.log').open('wb'); logs.append(log)
            command = [sys.executable, '-B', str(SCRIPT), '_worker', '--root', str(checkout), '--output', str(child_output),
                       '--plan', str(output / 'plan.json'), '--assignment', encoded(blocks)]
            if workers == 1:
                command.append('--sequential')
            save(child_output / 'command.json', {'argv': command, 'temp': str(temp)})
            remaining()
            if interrupted.is_set():
                raise RunnerError('CANCELLED', 'stopped immediately before worker launch')
            process = subprocess.Popen(command, cwd=checkout, env=child_env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            observed = observer.register(process)
            jobs.append((process, observed['start'] if observed else None))
            if interrupted.is_set():
                process.send_signal(signal.SIGINT)
        while any(p.poll() is None for p, _ in jobs):
            if interrupted.is_set() or time.monotonic() - started >= timeout:
                raise RunnerError('CANCELLED' if interrupted.is_set() else 'TIMEOUT', 'stopped while workers were active')
            time.sleep(.02)
    except BaseException as exc:
        failures.append({'code': 'TIMEOUT' if isinstance(exc, subprocess.TimeoutExpired) else getattr(exc, 'code', 'ORCHESTRATOR_ERROR'), 'detail': str(exc)})
    finally:
        if observer.thread.ident is not None:
            failures.extend({'code': 'CLEANUP_INCOMPLETE', 'detail': x} for x in cleanup(collector_jobs + jobs, observer))
            observer.close()
        for log in logs:
            log.close()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    for index, (process, _) in enumerate(jobs):
        directory = output / ('worker-' + str(index))
        rows, error = read_events(directory / 'events.jsonl')
        events.extend(rows)  # retain valid partial prefix even if result is missing
        if error:
            failures.append({'code': 'EVENTS_INVALID', 'detail': error})
        path = directory / 'result.json'
        try:
            report = read_json(path)
            if not isinstance(report, dict) or type(report.get('completed')) is not bool:
                raise RunnerError('RESULT_INVALID', 'saved worker completed must be a boolean in an object')
            reports.append(report)
            if not report['completed']:
                raise RunnerError('WORKER_INCOMPLETE', report.get('detail', 'worker did not complete'))
            blocks = manifest['assignments'][index]
            expected = {r['index']: r for r in plan['occurrences'] if r['block'] in blocks}
            validate_events(rows, expected, report, dynamic_order=workers == 1 and bool(plan['parallel_unsupported']))
            if process.returncode != (0 if report['successful'] else 1):
                raise RunnerError('WORKER_EXIT_INVALID', 'exit code disagrees with saved result')
        except (OSError, ValueError, KeyError, TypeError, RunnerError) as exc:
            failures.append({'code': getattr(exc, 'code', 'RESULT_MISSING_OR_INVALID'), 'detail': str(exc)})
    try:
        if source(root) != initial_source or environment() != initial_environment or (jobs and hashlib.sha256(SCRIPT.read_bytes()).hexdigest() != manifest['runner_sha256']):
            raise RunnerError('SOURCE_OR_ENV_CHANGED', 'parent source/environment changed during run')
    except (OSError, subprocess.SubprocessError, RunnerError) as exc:
        failures.append({'code': getattr(exc, 'code', 'SOURCE_OR_ENV_UNAVAILABLE'), 'detail': str(exc)})
    if observer.error or observer.peak <= 0 or any(p.pid not in observer.seen_workers for p, _ in collector_jobs + jobs):
        failures.append({'code': 'RSS_UNAVAILABLE', 'detail': observer.error or 'parent or worker observation missing'})
    if time.monotonic() - started >= timeout and not any(f['code'] == 'TIMEOUT' for f in failures):
        failures.append({'code': 'TIMEOUT', 'detail': 'run did not finish within the declared deadline'})
    success = not failures and reports and all(r.get('successful') for r in reports)
    status = 'PASS' if success else 'INCOMPLETE' if failures else 'FAILED'
    summary = {'kind': 'repository-tests-result/v1', 'status': status, 'infrastructure_failures': failures,
               'workers': reports, 'worker_returncodes': [p.returncode for p, _ in jobs], 'collector_returncodes': [p.returncode for p, _ in collector_jobs],
               'events': events if workers == 1 else sorted(events, key=lambda e: e.get('block', -1)),
               'started_occurrences': sum(e.get('kind') == 'start' for e in events),
               'stopped_occurrences': sum(e.get('kind') == 'stop' for e in events),
               'wall_seconds': time.monotonic() - started,
               'sampled_aggregate_peak_rss_bytes': observer.peak if observer.peak > 0 else None,
               'rss_target_wait_seconds': .02, 'rss_hard_bound': False,
               'rss_observed_phase': 'after source/environment preflight through collector/worker cleanup; excludes result aggregation and summary save',
               'rss_whole_invocation': False,
               'cpu_parent_self_seconds': resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime - cpu_self_start.ru_utime - cpu_self_start.ru_stime,
               'cpu_parent_reaped_children_seconds': resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime - cpu_children_start.ru_utime - cpu_children_start.ru_stime,
               'cpu_child_scope': 'OS-accounted reaped children; never add worker counters again',
               'qualification': 'NOT_EVALUATED', 'exit_code': 0 if success else 2 if failures else 1}
    save(output / 'summary.json', summary)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, choices=(1, 2), default=1)
    parser.add_argument('--timeout', type=float, default=1200)
    # The worker mode is internal, always bound to the saved parent plan.
    args_list = sys.argv[1:] if argv is None else argv
    worker_mode = bool(args_list and args_list[0] == '_worker')
    collection_mode = bool(args_list and args_list[0] == '_collect')
    if worker_mode:
        parser.add_argument('--plan', type=Path, required=True)
        parser.add_argument('--assignment', required=True)
        parser.add_argument('--sequential', action='store_true')
        args_list = args_list[1:]
    if collection_mode:
        args_list = args_list[1:]
    args = parser.parse_args(args_list)
    try:
        if collection_mode:
            return collect_worker(args.root.resolve(), args.output.resolve())
        if worker_mode:
            return worker(args.root.resolve(), args.output.resolve(), args.plan, json.loads(args.assignment), args.sequential)
        summary = run(args.root.resolve(), args.output.resolve(), args.workers, args.timeout)
        print(encoded({'status': summary['status'], 'exit_code': summary['exit_code'],
                       'summary': str(args.output.resolve() / 'summary.json'), 'qualification': 'NOT_EVALUATED'}))
        return summary['exit_code']
    except (RunnerError, OSError, subprocess.SubprocessError) as exc:
        print(encoded({'status': 'REFUSED', 'code': getattr(exc, 'code', 'IO_ERROR'), 'detail': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
