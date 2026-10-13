"""Finite diagnostic sampling around an otherwise unchanged isolated CLI script.

No frame locals, argument values, source contents or absolute paths are emitted.
Sampling is not a function-call counter, benchmark or proof of child cleanup.
"""
from __future__ import annotations

import builtins
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import sysconfig
import threading
import time
import types

MAX_BYTES = 2 * 1024 * 1024
MAX_SAMPLES, MAX_THREADS, MAX_FRAMES, MAX_STACKS = 220, 32, 48, 128
WINDOW, INTERVAL = 55.0, 0.25


class Sampler:
    def __init__(self, directory, root):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.roots = [(os.path.normcase(str(root)) + os.sep, "repo/"),
                      (os.path.normcase(sysconfig.get_path("stdlib")) + os.sep, "stdlib/")]
        self.started = time.perf_counter()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="diagnostic-sampler", daemon=True)
        self.slots, self.stacks, self.identities, self.recent = {}, {}, {}, {}
        self.resources = []
        self.samples = self.dropped_threads = self.dropped_stacks = 0
        self.sample_cpu = self.sample_wall = self.flush_wall = 0.0
        self.writes = self.written_bytes = self.write_failures = 0
        self.identity_overflow = False
        self.complete = False
        self.stop_reason = None
        self.target_returned = False

    def frame(self, frame):
        filename = os.path.normcase(frame.f_code.co_filename)
        relative = "<external>"
        for prefix, label in self.roots:
            if filename.startswith(prefix):
                relative = label + filename[len(prefix):].replace(os.sep, "/")
                break
        if filename.startswith("<frozen ") and filename.endswith(">"):
            relative = filename
        return (relative[:180], frame.f_code.co_name[:96], frame.f_lineno)

    def sample(self):
        names = {thread.ident: thread.name for thread in threading.enumerate()}
        for ident, frame in sys._current_frames().items():
            if ident == threading.get_ident():
                continue
            if ident not in self.slots:
                if len(self.slots) >= MAX_THREADS:
                    self.dropped_threads += 1
                    continue
                self.slots[ident] = len(self.slots)
            name = names.get(ident, "")
            role = ("main" if ident == threading.main_thread().ident else
                    "monitor" if name == "loop-owner-watch" else
                    "worker" if name.startswith("ThreadPoolExecutor-") else
                    "stdin" if "feed_prompt" in name else "other")
            frames = []
            while frame is not None and len(frames) < MAX_FRAMES:
                frames.append(self.frame(frame))
                frame = frame.f_back
            key = (self.slots[ident], role, tuple(frames))
            # Keep a small time-series breadcrumb even if the unique-stack
            # table is already full later in the controller's lifetime.
            relevant = [row for row in frames if row[0].startswith("repo/")]
            self.recent[key[0]] = {"thread": key[0], "role": role,
                                  "frames": frames[:2] + relevant[:2]}
            if key not in self.stacks and len(self.stacks) >= MAX_STACKS:
                self.dropped_stacks += 1
                continue
            row = self.stacks.setdefault(key, {"thread": key[0], "role": role, "frames": frames,
                                              "samples": 0, "truncated_stack": frame is not None})
            row["samples"] += 1
        self.samples += 1

    def resources_and_identities(self):
        import psutil
        row = {"elapsed_seconds": time.perf_counter() - self.started,
               "process_cpu_seconds": time.process_time(), "io": None,
               "active_threads": sorted(self.recent.values(),
                   key=lambda item: (item["role"] != "main", item["thread"]))[:8]}
        self.recent.clear()
        try:
            process = psutil.Process(os.getpid())
            counters = process.io_counters()
            row["io"] = {key: getattr(counters, key, None)
                         for key in ("read_count", "write_count", "read_bytes", "write_bytes")}
            for child in [process, *process.children(recursive=True)]:
                try:
                    identity = (child.pid, child.create_time())
                    if identity not in self.identities and len(self.identities) >= 32:
                        self.identity_overflow = True
                        continue
                    self.identities[identity] = {"pid": identity[0], "created_at": identity[1],
                        "role": "controller" if child.pid == process.pid else "observed_descendant"}
                except (psutil.Error, OSError):
                    row["identity_observation_incomplete"] = True
        except (psutil.Error, OSError):
            row["resource_observation_incomplete"] = True
        self.resources.append(row)

    def flush(self):
        started = time.perf_counter()
        value = {"version": 1, "scope": "One target controller; approximate sampled stacks, not call counts.",
                 "performance_qualification": "NOT_EVALUATED", "elapsed_seconds": started - self.started,
                 "sampling_stopped": self.complete, "sampling_stop_reason": self.stop_reason,
                 "target_python_finally_reached": self.target_returned,
                 "limits": {"bytes": MAX_BYTES, "samples": MAX_SAMPLES, "threads": MAX_THREADS,
                            "frames_per_stack": MAX_FRAMES, "unique_stacks": MAX_STACKS,
                            "window_seconds": WINDOW, "interval_seconds": INTERVAL, "owned_identities": 32},
                 "samples": self.samples, "dropped_thread_samples": self.dropped_threads,
                 "dropped_new_stack_samples": self.dropped_stacks, "owned_identity_overflow": self.identity_overflow,
                 "stacks": list(self.stacks.values()), "resources": self.resources,
                 "owned_identities": list(self.identities.values()),
                 "overhead": {"sampler_thread_cpu_seconds": self.sample_cpu,
                              "sampling_and_flush_wall_seconds": self.sample_wall,
                              "previous_flush_wall_seconds": self.flush_wall,
                              "previous_writes": self.writes, "previous_written_bytes": self.written_bytes,
                              "previous_write_failures": self.write_failures}}
        data = (json.dumps(value, ensure_ascii=True, separators=(",", ":")) + "\n").encode()
        if len(data) > MAX_BYTES:
            value["stacks"] = []
            value["stack_byte_cap_exceeded"] = True
            data = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        if len(data) > MAX_BYTES:
            value["resources"] = []
            value["resource_byte_cap_exceeded"] = True
            data = (json.dumps(value, separators=(",", ":")) + "\n").encode()
        if len(data) > MAX_BYTES:
            self.write_failures += 1
            self.flush_wall += time.perf_counter() - started
            return  # Never replace the last snapshot with an oversized record.
        try:
            staged = self.directory / "samples.partial.json"
            with staged.open("wb") as stream:
                stream.write(data)
                stream.flush()
            staged.replace(self.directory / "samples.json")
            self.writes += 1
            self.written_bytes += len(data)
        except OSError:
            self.write_failures += 1
        self.flush_wall += time.perf_counter() - started

    def run(self):
        started_cpu = time.thread_time()
        next_resource = next_flush = 0.0
        while self.samples < MAX_SAMPLES and time.perf_counter() - self.started < WINDOW:
            begin = time.perf_counter()
            self.sample()
            elapsed = begin - self.started
            if elapsed >= next_resource:
                self.resources_and_identities()
                next_resource = elapsed + 1.0
            self.sample_cpu = time.thread_time() - started_cpu
            if elapsed >= next_flush:
                self.flush()
                next_flush = elapsed + 5.0
            self.sample_wall += time.perf_counter() - begin
            if self.stop.wait(INTERVAL):
                break
        self.complete = True
        self.stop_reason = ("target_python_finally" if self.stop.is_set() else
                            "sample_limit" if self.samples >= MAX_SAMPLES else "time_limit")
        self.sample_cpu = time.thread_time() - started_cpu
        self.flush()

    def finish(self):
        self.target_returned = True
        self.stop.set()
        self.thread.join(timeout=0.5)
        if not self.thread.is_alive():
            self.flush()


def launch(script, arguments):
    """Use the direct-script namespace, including its actual __main__ module."""
    namespace = types.ModuleType("__main__")
    namespace.__dict__.update(__file__=script, __package__=None, __spec__=None,
        __cached__=None, __annotations__={}, __builtins__=builtins,
        __loader__=importlib.machinery.SourceFileLoader("__main__", script))
    code = compile(Path(script).read_bytes(), script, "exec", dont_inherit=True)
    sys.argv = [script, *arguments]
    sys.modules["__main__"] = namespace
    exec(code, namespace.__dict__)


def main():
    directory, script, *arguments = sys.argv[1:]
    sampler = Sampler(Path(directory), Path(__file__).resolve().parents[2])
    sampler.thread.start()
    try:
        launch(script, arguments)
    finally:
        sampler.finish()


if __name__ == "__main__":
    main()
