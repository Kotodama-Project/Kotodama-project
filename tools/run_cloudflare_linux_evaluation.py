#!/usr/bin/env python3
"""Run one fixed Cloudflare OS local check in an isolated Linux checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import stat
import subprocess
import sys
import time

if __package__:
    from .validate_cloudflare_security_patch import ARTIFACT, CandidateViolation, load_candidate, regular_bytes, require, validate_candidate, verify_materialized
else:
    from validate_cloudflare_security_patch import ARTIFACT, CandidateViolation, load_candidate, regular_bytes, require, validate_candidate, verify_materialized

COMMANDS = {
    "build": ("run", "build"),
    "test": ("run", "test"),
    "types": ("run", "types:check"),
    "scheduler": ("--filter", "@gadgets/gatekeeper-scheduler", "exec", "vitest", "run", "__tests__/scheduler-scope.test.ts"),
}


def command_arguments(name):
    require(name in COMMANDS, "command is outside the local evaluation allowlist")
    return list(COMMANDS[name])


def clean_environment(home, binary_dir):
    # No inherited PATH, Node options, package-manager config or provider keys.
    return {
        "PATH": f"{binary_dir}:/usr/bin:/bin", "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"), "XDG_CACHE_HOME": str(home / "cache"),
        "TMPDIR": str(home / "tmp"), "CI": "true", "LANG": "C.UTF-8",
        "npm_config_userconfig": str(home / "npmrc"), "npm_config_offline": "true",
        "npm_config_ignore_scripts": "true", "npm_config_manage_package_manager_versions": "false",
        "WRANGLER_SEND_METRICS": "false", "WRANGLER_LOG_SANITIZE": "true",
    }


def preflight(core, node, pnpm, candidate):
    require(sys.platform == "linux", "Linux process required; run inside WSL on Windows")
    require(core.is_absolute() and node.is_absolute() and pnpm.is_absolute(), "absolute paths required")
    require(node.is_file() and pnpm.is_file(), "explicit Node and pnpm files required")
    with node.open("rb") as stream:
        require(stream.read(4) == b"\x7fELF", "native Linux Node required")
    validate_candidate(candidate, regular_bytes(ARTIFACT / "candidate.patch", 65536), regular_bytes(ARTIFACT / "LICENSE", 32768))
    verify_materialized(core, candidate)
    # Never run this against a user's runtime copy or local provider configuration.
    for root, dirs, files in os.walk(core, followlinks=False):
        dirs[:] = [name for name in dirs if name not in (".git", "node_modules", "dist", ".wrangler")]
        require(not any(name == ".npmrc" or name.startswith((".env", ".dev.vars")) for name in files), "local configuration must be absent from evaluation source")


def owned_run(argv, core, environment, log, timeout, *, stop_requested=None):
    """Track exact child identities; stop only this invocation's descendants."""
    import psutil  # Installed from requirements-task-swarm-ci.txt in the evaluator.

    stop_requested = stop_requested or (lambda: False)
    known = {}
    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=core, env=environment, stdin=subprocess.DEVNULL,
                               stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    leader = psutil.Process(process.pid)
    known[leader.pid] = leader.create_time()

    def capture():
        session_owned = False
        for pid, created in list(known.items()):
            try:
                parent = psutil.Process(pid)
                if parent.create_time() == created:
                    session_owned |= os.getsid(pid) == process.pid
                    for child in parent.children(recursive=True):
                        known[child.pid] = child.create_time()
            except (ProcessLookupError, psutil.NoSuchProcess):
                pass
        # Capture surviving members of our still-owned session after leader exit.
        if not session_owned:
            return
        for item in psutil.process_iter(["pid", "create_time"]):
            try:
                if os.getsid(item.pid) == process.pid:
                    known[item.pid] = item.create_time()
            except (ProcessLookupError, PermissionError, psutil.NoSuchProcess):
                pass

    def alive():
        found = []
        for pid, created in known.items():
            try:
                item = psutil.Process(pid)
                if item.create_time() == created and item.status() != psutil.STATUS_ZOMBIE:
                    found.append(item)
            except psutil.NoSuchProcess:
                pass
        return found

    reason = "completed"
    try:
        while process.poll() is None:
            capture()
            if stop_requested() or time.monotonic() - started >= timeout:
                reason = "cancelled" if stop_requested() else "timeout"
                break
            time.sleep(0.1)
    finally:
        capture()
        for method in ("terminate", "kill"):
            for item in reversed(alive()):
                try:
                    # psutil verifies PID reuse again when signalling.
                    getattr(item, method)()
                except psutil.NoSuchProcess:
                    pass
            psutil.wait_procs(alive(), timeout=3)
        process.wait(timeout=3)
    return {"exit_code": process.returncode, "reason": reason,
            "tracked_processes": len(known), "owned_processes_remaining": len(alive()),
            "elapsed_seconds": round(time.monotonic() - started, 3)}


def evaluate(args):
    candidate = load_candidate()
    command = command_arguments(args.command)
    core, node, pnpm = (path.absolute() for path in (args.core, args.node, args.pnpm))
    preflight(core, node, pnpm, candidate)
    run_dir = args.output.absolute()
    require(not run_dir.exists() and not run_dir.is_relative_to(core), "new output directory outside core required")
    run_dir.mkdir(parents=True, mode=0o700)
    home, binary_dir = run_dir / "home", run_dir / "bin"
    for folder in (home, home / "tmp", home / "config", home / "cache", binary_dir):
        folder.mkdir(mode=0o700)
    (home / "npmrc").write_text("", encoding="utf-8")
    (binary_dir / "node").symlink_to(node)
    launcher = binary_dir / "pnpm"
    launcher.write_text(f"#!/bin/sh\nexec {shlex.quote(str(node))} {shlex.quote(str(pnpm))} \"$@\"\n", encoding="utf-8", newline="\n")
    launcher.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    environment = clean_environment(home, binary_dir)
    for argv, expected in (([str(node), "-p", "process.platform + ':' + process.version"], "linux:v24.19.0"), ([str(node), str(pnpm), "--version"], "11.9.0")):
        result = subprocess.run(argv, env=environment, cwd=core, check=True, capture_output=True, text=True, timeout=20)
        require(result.stdout.strip() == expected, "toolchain version/platform mismatch")
    stopped = False
    def stop(signum, frame):
        nonlocal stopped
        stopped = True
    old_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
    receipt = {"kind": "kotodama/cloudflare-linux-evaluation/v1", "status": "RUNNING",
               "command": args.command, "source_commit": candidate["source"]["commit"],
               "files": candidate["materialized_files"], "node": "24.19.0", "pnpm": "11.9.0",
               "provider_credentials_inherited": False, "provider_verified": False,
               "public_beta": "NO_GO_UNPUBLISHED"}
    receipt_path = run_dir / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    try:
        with (run_dir / "command.log").open("xb") as log:
            receipt.update(owned_run([str(node), str(pnpm), *command], core, environment, log, args.timeout, stop_requested=lambda: stopped))
        verify_materialized(core, candidate)
        receipt["source_bytes_unchanged"] = True
        receipt["status"] = "PASS_LOCAL_COMMAND" if receipt["exit_code"] == 0 and receipt["reason"] == "completed" and receipt["owned_processes_remaining"] == 0 else "FAILED"
    except Exception:
        receipt["status"] = "FAILED_UNCONFIRMED"
        raise
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        receipt["log_sha256"] = hashlib.sha256((run_dir / "command.log").read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    for name in ("core", "node", "pnpm", "output"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--timeout", type=int, choices=range(1, 1801), default=1200)
    args = parser.parse_args(argv)
    try:
        receipt = evaluate(args)
    except (CandidateViolation, OSError, ValueError, subprocess.SubprocessError, ImportError):
        print(json.dumps({"status": "REFUSED_OR_FAILED", "public_beta": "NO_GO_UNPUBLISHED"}))
        return 1
    print(json.dumps(receipt))
    return 0 if receipt["status"] == "PASS_LOCAL_COMMAND" else 1


if __name__ == "__main__":
    raise SystemExit(main())
