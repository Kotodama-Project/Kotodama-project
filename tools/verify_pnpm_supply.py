#!/usr/bin/env python3
"""Verify fixed public pnpm bytes against a candidate registry/identity policy."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "runtime/cloudflare-os/pnpm-supply-policy.json"


class SupplyViolation(ValueError):
    """A fixed-byte, cryptographic or identity boundary was not satisfied."""


def require(condition, reason):
    if not condition:
        raise SupplyViolation(reason)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON field")
        value[key] = item
    return value


def document(raw):
    return json.loads(raw, object_pairs_hook=unique_object)


def read_regular(path, limit):
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    try:
        require(stat.S_ISREG(os.fstat(descriptor).st_mode), "input must be a regular file")
        value = bytearray()
        while len(value) <= limit:
            part = os.read(descriptor, min(64 * 1024, limit + 1 - len(value)))
            if not part:
                break
            value.extend(part)
        require(len(value) <= limit, "input byte limit exceeded")
        return bytes(value)
    finally:
        os.close(descriptor)


def archive_shape(raw, policy):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
        rows = archive.getmembers()
        require(len(rows) == policy["archive_entries"], "archive entry count mismatch")
        require(sum(row.size for row in rows) == policy["archive_unpacked_bytes"], "archive unpacked size mismatch")
        names = set()
        for row in rows:
            path = PurePosixPath(row.name)
            require(row.isfile() or row.isdir(), "archive special entry refused")
            require(not path.is_absolute() and path.parts[0] == "package" and ".." not in path.parts and "\\" not in row.name, "archive path refused")
            require(row.name not in names, "archive duplicate path refused")
            names.add(row.name)


def registry_message(metadata, keys, archive, policy, now):
    require(isinstance(metadata, dict) and isinstance(keys, dict), "registry document shape mismatch")
    require(metadata.get("name") == policy["package"] and metadata.get("version") == policy["version"], "package identity mismatch")
    dist = metadata["dist"]
    require(dist["tarball"] == policy["tarball"], "registry artifact origin mismatch")
    digest = hashlib.sha512(archive).hexdigest()
    require(digest == policy["archive_sha512"], "artifact digest mismatch")
    integrity = "sha512-" + base64.b64encode(bytes.fromhex(digest)).decode("ascii")
    require(dist["integrity"] == integrity, "registry integrity mismatch")
    entries = keys["keys"]
    require(len({row["keyid"] for row in entries}) == len(entries), "duplicate registry key identifier")
    selected = [row for row in entries if row["keyid"] == policy["registry_key_id"]]
    require(len(selected) == 1, "registry key missing")
    key = selected[0]
    require(key["keytype"] == key["scheme"] == "ecdsa-sha2-nistp256", "registry key algorithm refused")
    if key.get("expires") is not None:
        expires = dt.datetime.fromisoformat(key["expires"].replace("Z", "+00:00"))
        require(expires.tzinfo is not None and expires > now, "registry key expired")
    signatures = dist["signatures"]
    require(len(signatures) == 1 and signatures[0]["keyid"] == policy["registry_key_id"], "registry signature identity mismatch")
    archive_shape(archive, policy)
    return {"message": f'{policy["package"]}@{policy["version"]}:{integrity}', "key": key["key"], "signature": signatures[0]["sig"]}


def verify_statement(result, policy):
    require(isinstance(result, list) and len(result) == 1, "expected one verified provenance")
    verified = result[0]["verificationResult"]
    certificate = verified["signature"]["certificate"]
    require(isinstance(certificate, dict), "verified certificate missing")
    expected = {
        "subjectAlternativeName": policy["certificate_identity"], "issuer": policy["certificate_issuer"],
        "sourceRepositoryURI": "https://github.com/" + policy["source_repository"],
        "sourceRepositoryRef": policy["source_ref"], "sourceRepositoryDigest": policy["source_commit"],
        "buildSignerURI": policy["certificate_identity"], "runnerEnvironment": "github-hosted",
    }
    require(all(certificate.get(key) == value for key, value in expected.items()), "verified certificate identity mismatch")
    require(bool(verified["verifiedTimestamps"]), "verified timestamp missing")
    statement = verified["statement"]
    require(statement["predicateType"] == policy["predicate_type"], "provenance predicate mismatch")
    require(statement["subject"] == [{"name": f'pkg:npm/{policy["package"]}@{policy["version"]}', "digest": {"sha512": policy["archive_sha512"]}}], "verified provenance subject mismatch")


def child_environment(home):
    names = ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS")
    env = {name: os.environ[name] for name in names if name in os.environ}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(home/"AppData"), LOCALAPPDATA=str(home/"LocalAppData"), GH_CONFIG_DIR=str(home/"gh"), XDG_CACHE_HOME=str(home/"cache"), GH_PROMPT_DISABLED="1", GH_NO_UPDATE_NOTIFIER="1")
    return env


def verify(args):
    policy_bytes = read_regular(POLICY, 32768)
    policy = document(policy_bytes)
    require(policy["kind"] == "kotodama/pnpm-supply-policy/v1" and policy["status"] == "CANDIDATE_TRUST_ACCEPTANCE_PENDING", "policy status refused")
    require(all(policy[key] is False for key in ("trust_root_accepted", "independent_approval", "upstream_adopted")) and policy["public_beta"] == "NO_GO_UNPUBLISHED", "policy cannot grant adoption")
    require(policy["package"] == "pnpm" and policy["version"] == "11.9.0" and policy["registry"] == "https://registry.npmjs.org/", "fixed policy package mismatch")
    require(policy["certificate_identity"] == f'https://github.com/{policy["source_repository"]}/{policy["source_workflow"]}@{policy["source_ref"]}', "policy workflow identity is inconsistent")
    raw = {"metadata": read_regular(args.metadata, 256 * 1024), "keys": read_regular(args.keys, 32768), "archive": read_regular(args.archive, 32 * 1024 * 1024), "bundle": read_regular(args.bundle, 1024 * 1024)}
    require(hashlib.sha256(raw["keys"]).hexdigest() == policy["registry_key_document_sha256"], "registry key document digest mismatch")
    now = dt.datetime.now(dt.timezone.utc)
    message = registry_message(document(raw["metadata"]), document(raw["keys"]), raw["archive"], policy, now)
    document(raw["bundle"])
    os_label = "windows" if sys.platform == "win32" else "linux" if sys.platform == "linux" else "unsupported"
    architecture = "amd64" if platform.machine().lower() in ("amd64", "x86_64") else "unsupported"
    verifier_bytes = read_regular(args.gh_executable, 64 * 1024 * 1024)
    verifier_digest = hashlib.sha256(verifier_bytes).hexdigest()
    require(verifier_digest == policy["verifier"]["binary_sha256"].get(f"{os_label}-{architecture}"), "verifier executable digest or platform mismatch")
    work = ROOT / "work" / "pnpm-supply-verification"
    require(work.resolve() == ROOT.resolve()/"work/pnpm-supply-verification", "verification workspace redirected")
    work.mkdir(parents=True, exist_ok=True)
    helper_bytes = read_regular(ROOT/"tools/npm_registry_signature.mjs", 16384)
    with tempfile.TemporaryDirectory(prefix="verify-", dir=work) as temporary:
        home = Path(temporary)
        env = child_environment(home)
        node = subprocess.run([args.node_executable, "--version"], capture_output=True, env=env, timeout=10)
        node_version = node.stdout.decode("ascii", errors="strict").strip()
        require(node.returncode == 0 and re.fullmatch(r"v24\.\d+\.\d+", node_version), "Node 24 toolchain required")
        helper = home / "registry-signature.mjs"
        helper.write_bytes(helper_bytes)
        signature = subprocess.run([args.node_executable, str(helper)], input=json.dumps(message).encode(), capture_output=True, env=env, timeout=30)
        require(signature.returncode == 0 and document(signature.stdout).get("verified") is True, "registry cryptographic signature refused")
        binary = home / ("gh.exe" if os_label == "windows" else "gh")
        binary.write_bytes(verifier_bytes)
        binary.chmod(0o700)
        archive = home / "pnpm.tgz"
        bundle = home / "provenance.json"
        archive.write_bytes(raw["archive"])
        bundle.write_bytes(raw["bundle"])
        command = [str(binary), "attestation", "verify", str(archive), "--bundle", str(bundle), "--repo", policy["source_repository"],
                   "--cert-identity", policy["certificate_identity"], "--cert-oidc-issuer", policy["certificate_issuer"],
                   "--source-ref", policy["source_ref"], "--source-digest", policy["source_commit"], "--deny-self-hosted-runners",
                   "--digest-alg", "sha512", "--predicate-type", policy["predicate_type"], "--format", "json"]
        provenance = subprocess.run(command, capture_output=True, env=env, timeout=120)
        require(provenance.returncode == 0 and len(provenance.stdout) <= 4 * 1024 * 1024, "provenance cryptographic verification refused")
        verify_statement(document(provenance.stdout), policy)
    return {"status": "REGISTRY_AND_PROVENANCE_VERIFIED_CANDIDATE", "observed_at": now.isoformat(), "package": policy["package"], "version": policy["version"],
            "input_sha256": {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}, "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
            "verifier_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "registry_helper_sha256": hashlib.sha256(helper_bytes).hexdigest(),
            "verifier_sha256": verifier_digest, "node_version": node_version, "registry_signature_verified": True, "provenance_signature_verified": True, "source_identity_verified": True,
            "trust_root_accepted": False, "independent_approval": False, "upstream_adopted": False, "provider_credential_variables_inherited": False,
            "package_installed": False, "lifecycle_executed": False, "public_beta": "NO_GO_UNPUBLISHED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("metadata", "keys", "archive", "bundle", "gh-executable"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--node-executable", default="node")
    args = parser.parse_args(argv)
    try:
        result = verify(args)
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, tarfile.TarError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc) if isinstance(exc, SupplyViolation) else "verification input or tool unavailable"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
