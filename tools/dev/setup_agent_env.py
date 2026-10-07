#!/usr/bin/env python3
"""Prepare hash-locked test dependencies without blocking an agent session."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
NODE_VERSION = "24.14.0"
NODE_HASHES = {
    "x86_64": ("x64", "41cd79bb7877c81605a9e68ec4c91547774f46a40c67a17e34d7179ef11729df"),
    "aarch64": ("arm64", "e7adfca03d9173276114a6f2219df1a7d25e1bfd6bbd771d3f839118a2053094"),
}
COREPACK_VERSION = "0.34.6"
COREPACK_SHA512 = base64.b64decode("gvylq9kzJB09mSsiOnKOnhg0YdCWNy2aGaeGbYF4HlyGd/v4moxEonQjJPYI45/K4zP7q1hW9qCVvaYYKK5nkA==").hex()
LOCKS = ("requirements-ci.txt", "requirements-task-swarm-ci.txt")
NODE_DEPENDENCY_PROBE = """
const fs = require('node:fs'), path = require('node:path');
const manifest = JSON.parse(fs.readFileSync('package.json', 'utf8'));
for (const [name, expected] of Object.entries(manifest.dependencies ?? {})) {
  const base = path.join('node_modules', name);
  const installed = JSON.parse(fs.readFileSync(path.join(base, 'package.json'), 'utf8'));
  if (installed.version !== expected) process.exit(1);
  for (const entry of [installed.main, installed.module].filter(Boolean)) {
    if (!fs.existsSync(path.join(base, entry))) process.exit(1);
  }
}
"""


class Unavailable(Exception):
    """A named preparation stage could not be completed."""


def owned_path(root: Path, path: Path) -> None:
    """Validate existing ancestors before creating or writing a task path."""
    if not path.resolve().is_relative_to(root.resolve()):
        raise Unavailable("workspace path")


def owned_tree(root: Path, path: Path, python_bin: Path) -> None:
    """Reject redirected children; a venv may link its exact base interpreter."""
    owned_path(root, path)
    if not path.exists():
        return
    for directory, folders, files in os.walk(path, followlinks=False):
        for name in (*folders, *files):
            child = Path(directory) / name
            if child.is_symlink() or child.is_junction():
                if child.parent == python_bin and name in ("python", "python3", "python3.12") and child.resolve() == Path(sys.executable).resolve():
                    continue
                owned_path(root, child)


def safe_environment(state: Path) -> dict[str, str]:
    """Only execution and proxy/CA settings cross into dependency tools."""
    names = ("PATH", "LANG", "LC_ALL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
             "http_proxy", "https_proxy", "all_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
             "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(HOME=str(state / "home"), XDG_CACHE_HOME=str(state / "cache"),
               COREPACK_HOME=str(state / "corepack-cache"), COREPACK_ENABLE_DOWNLOAD_PROMPT="0",
               COREPACK_DEFAULT_TO_LATEST="0", COREPACK_ENABLE_AUTO_PIN="0",
               npm_config_userconfig=str(state / "empty.npmrc"), npm_config_registry="https://registry.npmjs.org/",
               PIP_CONFIG_FILE=os.devnull, PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1",
               PIP_DEFAULT_TIMEOUT="15", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", CI="true")
    return env


def run(command: list[str], *, cwd: Path, env: dict[str, str], timeout: int = 180, output: bool = False) -> str:
    """Suppress tool diagnostics: package URLs and environment values stay private."""
    try:
        result = subprocess.run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE if output else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=True, text=True)
        return result.stdout.strip() if output else ""
    except (OSError, subprocess.SubprocessError):
        raise Unavailable("command") from None


def verified_archive(url: str, destination: Path, digest: str, algorithm: str) -> None:
    """Only extract a fixed archive after checking its committed digest."""
    archive = destination.with_suffix(".archive")
    try:
        if not archive.exists():
            with urllib.request.urlopen(url, timeout=20) as response:
                content = response.read(60 * 1024 * 1024 + 1)
            if len(content) > 60 * 1024 * 1024:
                raise Unavailable("archive size")
            archive.write_bytes(content)
        if hashlib.new(algorithm, archive.read_bytes()).hexdigest() != digest:
            raise Unavailable("archive digest")
        if destination.exists():
            return
        # extractall's data filter rejects traversal, unsafe links and devices.
        with tarfile.open(archive) as incoming:
            if sum(row.size for row in incoming.getmembers()) > 300 * 1024 * 1024:
                raise Unavailable("archive expanded size")
            staging = Path(tempfile.mkdtemp(prefix="extract-", dir=destination.parent))
            incoming.extractall(staging, filter="data")
            staging.rename(destination)
    except (OSError, ValueError, tarfile.TarError):
        raise Unavailable("archive download or extraction") from None


def fingerprint(root: Path, python_version: str, node_version: str, pnpm_version: str) -> str:
    digest = hashlib.sha256()
    for name in (*LOCKS, "runtime/discord-template/pnpm-lock.yaml", "runtime/discord-template/package.json", "tools/dev/setup_agent_env.py"):
        digest.update(name.encode())
        digest.update((root / name).read_bytes())
    digest.update(f"{python_version}/{node_version}/{pnpm_version}/{sys.platform}/{platform.machine()}".encode())
    return digest.hexdigest()


def prepare(root: Path, *, hook: bool = False) -> dict[str, object]:
    started = time.monotonic()
    if hook and os.environ.get("CLAUDE_CODE_REMOTE") != "true":
        return {"status": "SKIPPED_LOCAL_HOOK"}
    if sys.platform != "linux" or sys.version_info[:2] != (3, 12):
        return {"status": "INCOMPLETE", "stage": "Linux and Python 3.12 required; CI uses 3.12.10"}
    state = root / "work" / "agent-env"
    try:
        owned_tree(root, state, state / "venv/bin")
        owned_tree(root, root / "runtime/discord-template/node_modules", state / "venv/bin")
        state.mkdir(parents=True, exist_ok=True)
    except (Unavailable, OSError, RuntimeError):
        return {"status": "INCOMPLETE", "stage": "workspace path or write access; no installation started"}
    lock = state / "setup.lock"
    try:
        lock.mkdir()
    except FileExistsError:
        return {"status": "INCOMPLETE", "stage": "setup already owned; inspect its process before retrying"}
    except OSError:
        return {"status": "INCOMPLETE", "stage": "workspace lock write access; no installation started"}
    stage = "credential gate"
    try:
        env = safe_environment(state)
        for folder in (state / "home", state / "cache", state / "bin"):
            folder.mkdir(exist_ok=True)
        (state / "empty.npmrc").touch(exist_ok=True)
        run([sys.executable, "-S", "-B", "tools/check_tracked_secret_hygiene.py"], cwd=root, env=env)
        stage = "Node 24 (nodejs.org must be reachable)"
        node = shutil.which("node")
        try:
            node_version = run([node or "node", "--version"], cwd=root, env=env, timeout=10, output=True)
        except Unavailable:
            node_version = ""
        if not node_version.startswith("v24."):
            architecture, digest = NODE_HASHES.get(platform.machine(), (None, None))
            if architecture is None:
                raise Unavailable("unsupported Linux architecture")
            name = f"node-v{NODE_VERSION}-linux-{architecture}"
            unpacked = state / "node"
            verified_archive(f"https://nodejs.org/dist/v{NODE_VERSION}/{name}.tar.xz", unpacked, digest, "sha256")
            node = str(unpacked / name / "bin" / "node")
            node_version = run([node, "--version"], cwd=root, env=env, timeout=10, output=True)
            if node_version != f"v{NODE_VERSION}":
                raise Unavailable("Node version")
        assert node is not None
        env["PATH"] = os.pathsep.join([str(Path(node).parent), env.get("PATH", "/usr/bin:/bin")])
        stage = "Corepack and pinned pnpm (registry.npmjs.org must be reachable)"
        corepack_root = state / "corepack"
        verified_archive(f"https://registry.npmjs.org/corepack/-/corepack-{COREPACK_VERSION}.tgz", corepack_root, COREPACK_SHA512, "sha512")
        corepack = corepack_root / "package" / "dist" / "corepack.js"
        package = json.loads((root / "runtime/discord-template/package.json").read_text(encoding="utf-8"))
        manager = package["packageManager"]
        if manager != "pnpm@11.19.0":
            raise Unavailable("packageManager drift; review setup and package together")
        pnpm_version = run([node, str(corepack), manager, "--version"], cwd=root, env=env, output=True)
        if pnpm_version != "11.19.0":
            raise Unavailable("pnpm version")
        launcher = state / "bin" / "pnpm"
        launcher.write_text("#!/bin/sh\n" +
                            "\n".join(f"export {key}={shlex.quote(env[key])}" for key in ("COREPACK_HOME", "COREPACK_ENABLE_DOWNLOAD_PROMPT", "COREPACK_DEFAULT_TO_LATEST", "COREPACK_ENABLE_AUTO_PIN")) +
                            f"\nexec {shlex.quote(node)} {shlex.quote(str(corepack))} {shlex.quote(manager)} \"$@\"\n", encoding="utf-8")
        launcher.chmod(0o700)
        venv = state / "venv"
        python = venv / "bin" / "python"
        env["PATH"] = os.pathsep.join([str(venv / "bin"), str(launcher.parent), env["PATH"]])
        signature = fingerprint(root, platform.python_version(), node_version, pnpm_version)
        stamp = state / "ready.json"
        ready = False
        if stamp.exists() and python.exists() and (root / "runtime/discord-template/node_modules/.modules.yaml").is_file():
            ready = json.loads(stamp.read_text(encoding="utf-8")).get("fingerprint") == signature
        if ready:
            stage = "cached dependency consistency"
            try:
                run([str(python), "-m", "pip", "check"], cwd=root, env=env, timeout=30)
                run([str(python), "-m", "pip", "install", "--dry-run", "--no-index", "--require-hashes", *[arg for name in LOCKS for arg in ("-r", name)]], cwd=root, env=env, timeout=30)
                run([node, "-e", NODE_DEPENDENCY_PROBE], cwd=root / "runtime/discord-template", env=env, timeout=30)
            except Unavailable:
                ready = False
        if not ready:
            stage = "Python hash-locked dependencies (pypi.org / files.pythonhosted.org)"
            if not python.exists():
                run([sys.executable, "-m", "venv", str(venv)], cwd=root, env=env)
            run([str(python), "-m", "pip", "install", "--require-hashes", "--retries", "1", "--cache-dir", str(state / "cache/pip"), "--index-url", "https://pypi.org/simple", *[arg for name in LOCKS for arg in ("-r", name)]], cwd=root, env=env)
            stage = "Discord frozen dependencies (registry.npmjs.org)"
            run([str(launcher), "install", "--frozen-lockfile", "--ignore-scripts", "--store-dir", str(state / "pnpm-store")], cwd=root / "runtime/discord-template", env=env)
            run([str(python), "-m", "pip", "check"], cwd=root, env=env, timeout=30)
            run([node, "-e", NODE_DEPENDENCY_PROBE], cwd=root / "runtime/discord-template", env=env, timeout=30)
            stamp.write_text(json.dumps({"fingerprint": signature}) + "\n", encoding="utf-8")
        activate = state / "activate.sh"
        activate.write_text(f"export PATH={shlex.quote(str(venv/'bin')+os.pathsep+str(launcher.parent)+os.pathsep+str(Path(node).parent))}:\"$PATH\"\nexport KOTODAMA_TEST_SWARM_PYTHON={shlex.quote(str(python))}\n", encoding="utf-8")
        if hook and os.environ.get("CLAUDE_ENV_FILE"):
            with open(os.environ["CLAUDE_ENV_FILE"], "a", encoding="utf-8") as output:
                output.write(f". {shlex.quote(str(activate))}\n")
        missing = [name for name in ("git", "ffmpeg") if shutil.which(name, path=env["PATH"]) is None]
        return {"status": "READY" if not missing else "INCOMPLETE", "stage": "system tools: " + ", ".join(missing) if missing else "dependencies ready; tests not run",
                "python": platform.python_version(), "node": node_version, "pnpm": pnpm_version,
                "cached": ready, "seconds": round(time.monotonic() - started, 2),
                "activate": ". work/agent-env/activate.sh"}
    except (Unavailable, OSError, ValueError, KeyError):
        return {"status": "INCOMPLETE", "stage": stage, "retry": "Check this stage's network or tool availability, then rerun setup. Session can continue."}
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass  # Preserve another owner's state; never mask the stage result.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hook", action="store_true")
    args = parser.parse_args()
    print("[agent-env] " + json.dumps(prepare(ROOT, hook=args.hook), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
