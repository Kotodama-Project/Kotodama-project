"""Diagnostic-only launcher for one unchanged native learning pytest case."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
NODE = "tests/test_task_swarm_executor_cli.py::test_learning_cli_uses_current_decision_and_keeps_the_typed_transport[13-False]"


def write(path, value):
    try:
        path.write_text(json.dumps(value, separators=(",", ":")) + "\n", encoding="utf-8")
    except OSError:
        pass  # Missing diagnostics remain unknown; preserve pytest's outcome.


def postmortem(directory):
    """Inspect only identities recorded as this controller or its descendants."""
    import psutil
    path = directory / "target" / "samples.json"
    if not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        return {"status": "unknown", "reason": "bounded_sample_missing"}
    try:
        sample = json.loads(path.read_bytes())
    except (ValueError, OSError):
        return {"status": "unknown", "reason": "sample_unreadable"}
    rows = []
    for identity in sample.get("owned_identities", [])[:32]:
        row = dict(identity)
        try:
            process = psutil.Process(identity["pid"])
            same = abs(process.create_time() - identity["created_at"]) <= 0.001
            row["postmortem"] = ("same_identity_alive" if process.is_running() else "exited") if same else "identity_changed"
        except psutil.NoSuchProcess:
            row["postmortem"] = "not_present"
        except (psutil.Error, OSError, ValueError):
            row["postmortem"] = "unknown"
        rows.append(row)
    return {"status": "observed_subset", "owned_identities": rows,
            "all_child_cleanup": "unknown", "termination_requested_by_diagnostic": False,
            "scope": "One read after subprocess.run returns or raises; short-lived or unsampled descendants may be absent."}


def main():
    if len(sys.argv) < 5 or sys.argv[2] != "--" or sys.argv[-1] != NODE:
        raise SystemExit("expected output-directory -- pytest-options exact-native-node")
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=False)
    original_run = subprocess.run
    matched = 0
    intercepted = 0

    def observed_run(*popenargs, **kwargs):
        nonlocal matched, intercepted
        command = popenargs[0] if popenargs else kwargs.get("args")
        eligible = (isinstance(command, (list, tuple)) and len(command) > 6
                    and list(command[:4]) == [sys.executable, "-I", "-B", str(ROOT / "tools/knowledge_base.py")]
                    and list(command[4:6]) == ["task-input", "execute"]
                    and "--learning-decision-digest" in command
                    and not any(str(arg).startswith("--receipt-sha256") for arg in command))
        if not eligible:
            return original_run(*popenargs, **kwargs)
        matched += 1
        if matched != 1 or kwargs.get("timeout") != 60:
            return original_run(*popenargs, **kwargs)
        intercepted += 1
        wrapped = [*command[:3], str(Path(__file__).with_name("windows_target_sampler.py")),
                   str(directory / "target"), *command[3:]]
        if popenargs:
            popenargs = (wrapped, *popenargs[1:])
        else:
            kwargs = {**kwargs, "args": wrapped}
        started = time.perf_counter()
        outcome = "exception"
        try:
            result = original_run(*popenargs, **kwargs)
            outcome = "returned"
            return result
        finally:
            error = sys.exception()
            try:
                observed = postmortem(directory)
            except Exception as exc:
                observed = {"status": "unknown", "error_type": type(exc).__name__}
            write(directory / "target-call.json", {
                "scope": "First admitted target execute only; original kwargs and 60-second timeout retained.",
                "outcome": outcome, "exception_type": type(error).__name__ if error else None,
                "elapsed_seconds": time.perf_counter() - started,
                "postmortem": observed,
            })

    # Match python -m pytest's repository import root, without changing child
    # environment, cwd, stdin, Python isolation flags or any product source.
    sys.path[0] = str(ROOT)
    subprocess.run = observed_run
    try:
        import pytest
        status = int(pytest.main(sys.argv[3:]))
    finally:
        subprocess.run = original_run
        write(directory / "selection.json", {"version": 1, "eligible_calls": matched,
              "intercepted_calls": intercepted, "required_intercepted_calls": 1,
              "nodeid": NODE, "performance_qualification": "NOT_EVALUATED"})
    return status if status or intercepted == 1 else 3


if __name__ == "__main__":
    raise SystemExit(main())
