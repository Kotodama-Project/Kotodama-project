#!/usr/bin/env python3
"""Read back the separate fixed-core security candidate, never apply or adopt it."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "runtime/cloudflare-os/security-2026-10-08"
COMMIT = "bf7f762d7fa73553284d731ab6a978d3ea17be24"
TREE = "023da57719fa9744a4ca909f9c3863c93cb614fa"
PATCH_PATHS = {"pnpm-workspace.yaml", "packages/mcp-shared/src/account.ts", "packages/mcp-shared/__tests__/account-endpoint.test.ts"}
ALL_PATHS = PATCH_PATHS | {"pnpm-lock.yaml"}
OVERRIDES = {"postcss@8.5.25>nanoid":"3.3.18", "@cloudflare/puppeteer@1.2.0>@puppeteer/browsers":"3.0.4", "@tanstack/router-core@1.171.15>seroval":"1.6.3", "postcss@8.5.25>source-map-js":"1.2.2", "@tailwindcss/node@4.3.3>source-map-js":"1.2.2", "@gadgets/mcp-shared@1.0.0>@modelcontextprotocol/client":"2.2.0"}


class CandidateViolation(ValueError):
    """The artifact or observed bytes do not support the fixed candidate."""


def require(condition, message):
    if not condition:
        raise CandidateViolation(message)


def regular_bytes(path: Path, limit: int) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), "regular input file required")
        value = bytearray()
        while len(value) <= limit:
            part = os.read(descriptor, min(65536, limit + 1 - len(value)))
            if not part:
                break
            value.extend(part)
        require(len(value) <= limit, "input byte limit exceeded")
        return bytes(value)
    finally:
        os.close(descriptor)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def load_candidate():
    return json.loads(regular_bytes(ARTIFACT / "candidate.json", 65536), object_pairs_hook=unique_object)


def verify_bytes(data, expected):
    require(type(expected["bytes"]) is int and len(data) == expected["bytes"], "file byte count mismatch")
    require(hashlib.sha256(data).hexdigest() == expected["sha256"], "file digest mismatch")
    require(b"\r" not in data, "canonical LF bytes required")


def validate_candidate(candidate, patch, license_bytes):
    require(candidate["kind"] == "kotodama/cloudflare-security-candidate/v1", "candidate kind mismatch")
    require(candidate["status"] == "LOCAL_COMPONENT_PASS_FULL_SUITE_BLOCKED_NOT_ADOPTED", "full-suite blocker must remain explicit")
    source = candidate["source"]
    require(source["repository"] == "https://github.com/cloudflare/cloudflare-os" and source["commit"] == COMMIT and source["tree"] == TREE, "source pin mismatch")
    require(set(source["files"]) == set(candidate["materialized_files"]) == ALL_PATHS, "source/output path set mismatch")
    require(candidate["overrides"] == OVERRIDES, "parent-scoped dependency policy mismatch")
    meta = candidate["patch"]
    require(meta["path"] == "candidate.patch" and meta["paths"] == sorted(PATCH_PATHS), "patch path set mismatch")
    require(meta["includes_generated_lock"] is False and meta["apply_requires_index_and_unidiff_zero"] is True, "package-manager lock generation required")
    verify_bytes(patch, meta)
    headers = re.findall(rb"^diff --git a/([^\n ]+) b/([^\n ]+)$", patch, re.MULTILINE)
    require(len(headers) == 3 and {a.decode() for a, b in headers if a == b} == PATCH_PATHS, "patch scope mismatch")
    for part in patch.split(b"diff --git ")[1:]:
        header = part.split(b"@@", 1)[0]
        path = header.split(b" ", 1)[0][2:].decode()
        require(header.count(f"--- a/{path}\n".encode()) == 1 and header.count(f"+++ b/{path}\n".encode()) == 1, "patch file headers mismatch")
        index = re.search(rb"(?m)^index ([0-9a-f]{40})\.\.([0-9a-f]{40}) 100644$", header)
        require(index is not None and index[1].decode() == source["files"][path]["blob"], "patch source index mismatch")
        require(not re.search(rb"(?m)^(?:rename |copy |new file |deleted file |old mode |new mode |GIT binary patch)", header), "patch may only edit the fixed regular files")
    require(candidate["license"]["spdx"] == "Apache-2.0" and candidate["license"]["path"] == "LICENSE", "upstream license must remain")
    require(hashlib.sha256(license_bytes).hexdigest() == candidate["license"]["sha256"], "license digest mismatch")
    require(candidate["adoption"] == {"upstream_pin_changed":False,"old_security_overlay_rebound":False,"provider_deployed":False,"trust_approved":False,"full_remediation_claimed":False,"public_beta":"NO_GO_UNPUBLISHED"}, "candidate cannot grant adoption")
    verification = candidate["observed_verification"]
    for field in ("production_audit_high", "production_audit_critical", "production_audit_other"):
        require(type(verification[field]) is int and verification[field] == 0, "recorded audit must be zero, not unknown")
    require(verification["full_upstream_suite_passed"] is False and candidate["review"]["owner_independence_accepted"] is False, "unverified acceptance cannot be promoted")
    require(candidate["remaining_failure"]["candidate_and_previous_overlay_both_fail"] is True, "baseline failure observation is required")


def git(core, *args):
    try:
        return subprocess.run(["git", "--no-lazy-fetch", "-c", "core.fsmonitor=false", "-C", str(core), *args], check=True, capture_output=True, timeout=30,
                              env={**os.environ, "GIT_NO_LAZY_FETCH":"1", "GIT_TERMINAL_PROMPT":"0"}).stdout
    except (OSError, subprocess.SubprocessError):
        raise CandidateViolation("fixed Git object read failed") from None


def changed_paths(core):
    # Compare raw bytes to Git blobs: never run a working-tree diff, clean filter,
    # textconv, or configured monitor merely to inspect a supplied checkout.
    entries = git(core, "ls-tree", "-rz", "HEAD").split(b"\0")
    changed = set()
    tracked = set()
    for entry in filter(None, entries):
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, blob = metadata.split()
        require(mode in (b"100644", b"100755", b"120000") and kind == b"blob", "tracked source blob required")
        path = raw_path.decode("utf-8")
        target = core / path
        require(target.resolve().is_relative_to(core.resolve()), "tracked source escaped core")
        # A Git symlink stores the link text, never its destination contents.
        # Windows checkouts with core.symlinks=false store that text as a file.
        data = os.fsencode(os.readlink(target)) if mode == b"120000" and target.is_symlink() else regular_bytes(target, 16 * 1024 * 1024)
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if actual != blob.decode():
            changed.add(path)
        tracked.add(raw_path)
    require(set(filter(None, git(core, "ls-files", "-z").split(b"\0"))) == tracked, "index path set mismatch")
    return changed


def verify_source(core, candidate, *, clean_working_tree=False):
    require(git(core, "rev-parse", "HEAD").decode().strip() == COMMIT and git(core, "rev-parse", "HEAD^{tree}").decode().strip() == TREE, "core checkout must use the exact source pin")
    for path, expected in candidate["source"]["files"].items():
        require(git(core, "rev-parse", f"{COMMIT}:{path}").decode().strip() == expected["blob"], "source blob mismatch")
        verify_bytes(git(core, "show", f"{COMMIT}:{path}"), expected)
        if clean_working_tree:
            target = core / path
            require(target.resolve().is_relative_to(core.resolve()), "source path escaped core")
            verify_bytes(regular_bytes(target, 1024 * 1024), expected)
    if clean_working_tree:
        require(not changed_paths(core), "source tracked tree must use canonical Git bytes")


def verify_materialized(core, candidate):
    verify_source(core, candidate)
    changed = changed_paths(core)
    require(changed == ALL_PATHS, "materialized tracked change set mismatch")
    for path, expected in candidate["materialized_files"].items():
        target = core / path
        require(target.resolve().is_relative_to(core.resolve()), "materialized path escaped core")
        verify_bytes(regular_bytes(target, 1024 * 1024), expected)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--source-core", type=Path)
    group.add_argument("--materialized-core", type=Path)
    args = parser.parse_args(argv)
    try:
        candidate = load_candidate()
        validate_candidate(candidate, regular_bytes(ARTIFACT/"candidate.patch", 65536), regular_bytes(ARTIFACT/"LICENSE", 32768))
        if args.materialized_core:
            verify_materialized(args.materialized_core, candidate)
        elif args.source_core:
            verify_source(args.source_core, candidate, clean_working_tree=True)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(json.dumps({"status":"REFUSED", "reason":str(exc) if isinstance(exc, CandidateViolation) else "candidate input unavailable"}))
        return 1
    print(json.dumps({"status":"CANDIDATE_BYTES_VALID_FULL_SUITE_BLOCKED", "source_verified":bool(args.source_core or args.materialized_core), "materialized_bytes_verified":bool(args.materialized_core), "audit_rerun":False, "tests_rerun":False, "full_remediation_verified":False, "owner_approval_verified":False, "provider_verified":False, "public_beta":"NO_GO_UNPUBLISHED"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
