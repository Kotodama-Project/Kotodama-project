"""Prepare the existing native addon in a new, pinned Cloudflare OS checkout.

Uses Git and the standard library only. Does not install packages, execute the
OS, apply optional patches, copy working-tree state, or change an adoption pin.
The destination must be outside both source repositories. On failure, a newly
created destination is retained for inspection, never reported as prepared.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "https://github.com/cloudflare/cloudflare-os.git"
EXTENSION = "runtime/cloudflare-os-kotodama"
MANIFEST = "governance/cloudflare-os-integration.json"
MOUNTS = {
    "gatekeeper-kotodama-brief": "packages/gatekeeper-kotodama-brief",
    "blueprints/kotodama-requirements":
        "packages/workshop-backend/format-blueprints/kotodama-requirements",
}
REQUIRED = {
    "gatekeeper-kotodama-brief/package.json",
    "gatekeeper-kotodama-brief/src/kotodama.ts",
    "blueprints/kotodama-requirements/blueprint.json",
    "blueprints/kotodama-requirements/files/client.js",
    "blueprints/kotodama-requirements/files/server.js",
}


class PreparationError(ValueError):
    """A bounded diagnostic code, without private paths or command output."""


def git(repo: Path, *args: str) -> bytes:
    # In particular, do not forward GIT_DIR, GIT_INDEX_FILE, ASKPASS, auth headers,
    # user templates, credential helpers or checkout filters to the new clone.
    env = {key: value for key, value in os.environ.items() if key in {
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
    }}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_TERMINAL_PROMPT="0", LC_ALL="C")
    try:
        result = subprocess.run(
            ["git", "-c", "core.autocrlf=false", "-c", "credential.helper=",
             "-c", "core.hooksPath=" + os.devnull, "-c", "init.templateDir=",
             "-C", str(repo), *args], env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise PreparationError("git_unavailable_or_timed_out") from error
    if result.returncode:
        raise PreparationError("git_operation_failed")
    return result.stdout


def snapshot(repo: Path, ref: str) -> tuple[str, str, list[tuple[str, str, bytes, int]]]:
    """Resolve once; copy only committed regular files in the two native mounts."""
    commit = git(repo, "rev-parse", "--verify", "--end-of-options",
                 ref + "^{commit}").decode().strip()
    config = json.loads(git(repo, "show", f"{commit}:{MANIFEST}"))
    if not isinstance(config, dict) or not isinstance(config.get("upstream"), dict):
        raise PreparationError("invalid_native_source_pin")
    upstream = config["upstream"]
    pin = upstream.get("compatibility_commit", "")
    if (upstream.get("repository") != "cloudflare/cloudflare-os"
            or upstream.get("extension_path") != EXTENSION
            or not isinstance(pin, str) or not re.fullmatch(r"[0-9a-f]{40}", pin)):
        raise PreparationError("invalid_native_source_pin")
    entries = git(repo, "ls-tree", "-r", "-z", "-l", commit, "--",
                  *(f"{EXTENSION}/{source}" for source in MOUNTS)).split(b"\0")
    files = []
    seen = set()
    total = 0
    for entry in filter(None, entries):
        fields, raw_path = entry.split(b"\t", 1)
        mode, kind, oid, size = fields.split()
        path = raw_path.decode("utf-8")
        relative = path.removeprefix(EXTENSION + "/")
        parts = PurePosixPath(relative).parts
        if (mode not in (b"100644", b"100755") or kind != b"blob"
                or not parts or any(p.casefold() in (".", "..", ".git") for p in parts)
                or "\\" in relative or ":" in relative):
            raise PreparationError("unsupported_addon_entry")
        if any(p in (".env", ".dev.vars", "node_modules", ".wrangler")
               or p.startswith(".dev.vars.")
               or (p.startswith(".env.") and p != ".env.example") for p in parts):
            raise PreparationError("runtime_state_in_addon")
        total += int(size)
        if int(size) > 2 * 1024 * 1024 or total > 8 * 1024 * 1024 or len(files) >= 256:
            raise PreparationError("addon_size_limit")
        for source, target in MOUNTS.items():
            prefix = source + "/"
            if relative.startswith(prefix):
                destination = target + "/" + relative[len(prefix):]
                data = git(repo, "cat-file", "blob", oid.decode("ascii"))
                files.append((relative, destination, data, int(mode, 8) & 0o777))
                seen.add(relative)
                break
        else:
            raise PreparationError("unexpected_addon_path")
    if not REQUIRED <= seen:
        raise PreparationError("incomplete_native_addon")
    return commit, pin, files


def prepare(repo: Path, destination: Path, *, ref: str = "HEAD",
            source_core: Path | None = None) -> dict:
    repo = repo.resolve(strict=True)
    destination = destination.absolute()
    # Resolve only the parent: resolving a dangling destination symlink would
    # turn it into an apparently new name and defeat exclusive creation.
    destination = destination.parent.resolve(strict=True) / destination.name
    core = source_core.resolve(strict=True) if source_core is not None else None
    if destination.exists() or destination.is_symlink():
        raise PreparationError("destination_exists")
    if destination.is_relative_to(repo) or (core and destination.is_relative_to(core)):
        raise PreparationError("destination_inside_source")
    commit, pin, files = snapshot(repo, ref)
    if core is not None:
        observed = git(core, "rev-parse", "--verify", pin + "^{commit}").decode().strip()
        if observed != pin:
            raise PreparationError("core_commit_mismatch")
    # mkdir is exclusive even if a second preparer wins after the preflight.
    # Never reset, clean, reuse, or delete a destination that already exists.
    destination.mkdir()
    git(destination, "init", "--quiet")
    git(destination, "remote", "add", "origin", UPSTREAM)
    git(destination, "fetch", "--depth=1", "--no-tags", "--no-recurse-submodules",
        str(core) if core is not None else UPSTREAM, pin)
    observed = git(destination, "rev-parse", "FETCH_HEAD^{commit}").decode().strip()
    if observed != pin:
        raise PreparationError("core_commit_mismatch")
    git(destination, "checkout", "--quiet", "--detach", pin)
    for parent in ("packages", "packages/workshop-backend/format-blueprints"):
        if git(destination, "cat-file", "-t", f"{pin}:{parent}").strip() != b"tree":
            raise PreparationError("incompatible_core_layout")
    package = json.loads(git(destination, "show", f"{pin}:package.json"))
    manager = package.get("packageManager", "")
    if not isinstance(manager, str) or not re.fullmatch(
            r"pnpm@\d+\.\d+\.\d+\+sha512\.[0-9a-f]{128}", manager):
        raise PreparationError("unbound_package_manager")
    for target in MOUNTS.values():
        path = destination / target
        # Refuse core collisions and any symlink in the path we would write.
        for candidate in (path, *path.parents):
            if candidate == destination:
                break
            if candidate.is_symlink():
                raise PreparationError("unsafe_mount_path")
        if path.exists():
            raise PreparationError("addon_mount_exists")
    for _source, target, data, mode in files:
        path = destination / target
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(data)
        path.chmod(mode)
        if path.read_bytes() != data:
            raise PreparationError("addon_readback_mismatch")
    git(destination, "diff", "--quiet", "HEAD", "--")
    return {
        "status": "PREPARED_NOT_INSTALLED",
        "core_repository": "cloudflare/cloudflare-os", "core_commit": pin,
        "kotodama_commit": commit, "copied_files": len(files),
        "package_manager": manager, "runtime_started": False,
    }


def validate_native_lock(before: str, after: str) -> int:
    """Allow one addon importer and added advisories, never changed resolutions.

    pnpm refreshes registry deprecation strings even with exact dependency pins.
    Compare the emitted lock text; do not rewrite it or remove existing warnings.
    """
    def sections(text):
        prefix, rest = text.split("\nimporters:\n", 1)
        importers, rest = rest.split("\npackages:\n", 1)
        packages, snapshots = rest.split("\nsnapshots:\n", 1)
        return prefix, re.split(r"(?m)(?=^  \S)", importers), packages, snapshots

    old, new = sections(before), sections(after)
    marker = "  packages/gatekeeper-kotodama-brief:\n"
    added = [block for block in new[1] if block.startswith(marker)]
    if (old[0] != new[0] or old[3] != new[3] or len(added) != 1
            or [block for block in new[1] if not block.startswith(marker)] != old[1]):
        raise PreparationError("native_lock_settings_importers_or_snapshots_changed")
    old_lines, new_lines = old[2].splitlines(keepends=True), new[2].splitlines(keepends=True)
    count = 0
    for kind, _a, _b, start, end in SequenceMatcher(
            None, old_lines, new_lines, autojunk=False).get_opcodes():
        if kind == "equal":
            continue
        lines = new_lines[start:end]
        if kind != "insert" or not all(re.fullmatch(r"    deprecated: [^\r\n]+\n", line)
                                        for line in lines):
            raise PreparationError("native_lock_package_graph_changed")
        count += len(lines)
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path,
                        help="new directory outside both source repositories")
    parser.add_argument("--source-core", type=Path,
                        help="optional local official Git clone containing the pinned commit")
    parser.add_argument("--ref", default="HEAD", help="committed Kotodama ref (default: HEAD)")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare(ROOT, args.destination, ref=args.ref,
                                 source_core=args.source_core), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError) as error:
        code = str(error) if isinstance(error, PreparationError) else "invalid_input_or_io"
        print(json.dumps({"status": "NOT_PREPARED", "error": code}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
