#!/usr/bin/env python3
"""Verify downloaded Wrangler bytes against the repository-pinned metadata."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
from typing import Any


MAX_ARTIFACT_BYTES = 134_217_728
REQUIRED_FIELDS = {
    "kind",
    "package",
    "version",
    "npm_tarball",
    "npm_integrity",
    "npm_shasum",
    "slsa_subject",
    "slsa_subject_sha512",
    "slsa_predicate_type",
    "observed_utc",
}
EXPECTED_IDENTITY = {
    "kind": "npm_supply_chain_binding",
    "package": "wrangler",
    "version": "4.120.0",
    "npm_tarball": "https://registry.npmjs.org/wrangler/-/wrangler-4.120.0.tgz",
    "slsa_subject": "pkg:npm/wrangler@4.120.0",
    "slsa_predicate_type": "https://slsa.dev/provenance/v1",
    "observed_utc": "2026-08-07",
}


class WranglerIntegrityViolation(ValueError):
    """The downloaded artifact did not match the trusted binding."""


def load_metadata(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WranglerIntegrityViolation(f"cannot load Wrangler metadata: {exc}") from exc
    if not isinstance(value, dict) or set(value) != REQUIRED_FIELDS:
        raise WranglerIntegrityViolation("Wrangler metadata shape is not exact")
    return value


def validate_identity(metadata: dict[str, Any]) -> None:
    if set(metadata) != REQUIRED_FIELDS:
        raise WranglerIntegrityViolation("Wrangler metadata shape is not exact")
    for field, expected in EXPECTED_IDENTITY.items():
        if metadata.get(field) != expected:
            raise WranglerIntegrityViolation(f"Wrangler metadata identity mismatch: {field}")


def verify_artifact(metadata: dict[str, Any], artifact_path: pathlib.Path) -> dict[str, Any]:
    validate_identity(metadata)
    try:
        size = artifact_path.stat().st_size
    except OSError as exc:
        raise WranglerIntegrityViolation(f"cannot inspect Wrangler artifact: {exc}") from exc
    if size <= 0 or size > MAX_ARTIFACT_BYTES:
        raise WranglerIntegrityViolation("Wrangler artifact size is outside the trusted bound")

    sha1 = hashlib.sha1(usedforsecurity=False)
    sha512 = hashlib.sha512()
    try:
        with artifact_path.open("rb") as artifact:
            while chunk := artifact.read(1_048_576):
                sha1.update(chunk)
                sha512.update(chunk)
    except OSError as exc:
        raise WranglerIntegrityViolation(f"cannot read Wrangler artifact: {exc}") from exc

    sha512_bytes = sha512.digest()
    sha512_hex = sha512.hexdigest()
    npm_integrity = "sha512-" + base64.b64encode(sha512_bytes).decode("ascii")
    if metadata.get("npm_integrity") != npm_integrity:
        raise WranglerIntegrityViolation("Wrangler npm integrity mismatch")
    if metadata.get("npm_shasum") != sha1.hexdigest():
        raise WranglerIntegrityViolation("Wrangler npm shasum mismatch")
    if metadata.get("slsa_subject_sha512") != sha512_hex:
        raise WranglerIntegrityViolation("Wrangler SLSA subject digest mismatch")
    return {
        "kind": "wrangler_artifact_integrity",
        "status": "PASS",
        "package": EXPECTED_IDENTITY["package"],
        "version": EXPECTED_IDENTITY["version"],
        "artifact_bytes": size,
        "artifact_sha512": sha512_hex,
        "npm_integrity_verified": True,
        "npm_shasum_verified": True,
        "slsa_subject_digest_verified": True,
        "slsa_attestation_signature_verified": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=pathlib.Path, required=True)
    parser.add_argument("--artifact", type=pathlib.Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        report = verify_artifact(load_metadata(args.metadata), args.artifact)
    except WranglerIntegrityViolation as exc:
        report = {
            "kind": "wrangler_artifact_integrity",
            "status": "REFUSED",
            "error": str(exc),
        }
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
