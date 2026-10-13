"""Finite Windows process-creation diagnostic; no product code is imported.

Each cwd is generated under one owned temporary directory. This observes the
platform gate, not the private diagnostics of a failed learning invocation.
Only lengths, stages, return codes and numeric exception metadata are printed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

CASES = [(size, "plain") for size in (245, 252, 258, 259, 260, 266)] + [
    (259, "extended"), (266, "extended")]
CHILD = "import os; print(len(os.getcwd().encode('utf-16-le')) // 2)"


def units(value):
    return len(str(value).encode("utf-16-le")) // 2


def emit(value):
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), flush=True)


def exception_fields(error):
    return {"exception_class": type(error).__name__,
            "errno": getattr(error, "errno", None),
            "winerror": getattr(error, "winerror", None)}


def extended(path):
    value = str(path)
    if value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def padded_path(root, target_units):
    """Keep components small while obtaining the exact UTF-16 path length."""
    remaining = target_units - units(root)
    if remaining < 2:
        raise ValueError("temporary root cannot fit the requested length")
    path = root
    while remaining:
        size = min(60, remaining - 1)
        if remaining - size - 1 == 1:
            size -= 1
        if size < 1:
            raise ValueError("cannot construct the requested length")
        path /= "x" * size
        remaining -= size + 1
    if units(path) != target_units:
        raise ValueError("constructed length differs")
    return path


def observe(root, number, target_units, spelling):
    result = {"case": number, "spelling": spelling,
              "plain_cwd_utf16_units": target_units, "stage": "prepare"}
    try:
        path = padded_path(root / ("c" + str(number)), target_units)
        # Preparation accepts long names independently from CreateProcess cwd.
        Path(extended(path)).mkdir(parents=True, exist_ok=False)
        cwd = str(path) if spelling == "plain" else extended(path)
        result.update(stage="create_process", supplied_cwd_utf16_units=units(cwd))
        child = subprocess.run([sys.executable, "-I", "-B", "-c", CHILD],
            cwd=cwd, capture_output=True, timeout=15, check=False)
        result.update(stage="child_exit", exit_code=child.returncode)
        output = child.stdout.strip()
        if child.returncode == 0 and output.isdigit() and len(output) <= 10:
            result["child_cwd_utf16_units"] = int(output)
        else:
            # Do not print child stderr or exception text containing paths.
            result["stdout_bytes"] = len(child.stdout)
            result["stderr_bytes"] = len(child.stderr)
    except Exception as error:
        result.update(exception_fields(error))
    emit(result)
    return result


def main():
    if os.name != "nt":
        emit({"stage": "platform", "exception_class": "WindowsRequired", "exit_code": 2})
        return 2
    temporary = None
    exit_code = 0
    try:
        temporary = tempfile.TemporaryDirectory(prefix="kwp-", ignore_cleanup_errors=True)
        root = Path(temporary.name).resolve()
        for number, (length, spelling) in enumerate(CASES, 1):
            observed = observe(root, number, length, spelling)
            if observed["stage"] == "prepare" or observed.get("exception_class") == "TimeoutExpired":
                exit_code = 2
    except Exception as error:
        emit({"stage": "setup", **exception_fields(error)})
        exit_code = 2
    finally:
        if temporary is not None:
            try:
                # Delete only this invocation's root, including its long names.
                shutil.rmtree(extended(Path(temporary.name)))
                emit({"stage": "cleanup", "exit_code": 0})
            except Exception as error:
                emit({"stage": "cleanup", **exception_fields(error)})
                exit_code = 2
            finally:
                try:
                    temporary.cleanup()
                except Exception as error:
                    emit({"stage": "cleanup_finalizer", **exception_fields(error)})
                    exit_code = 2
    emit({"stage": "complete", "exit_code": exit_code})
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
