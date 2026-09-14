"""Read-only design-contract checks; no Cloudflare, OS, or worker API calls."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import stat
from typing import Any

try:
    from jsonschema import Draft202012Validator, FormatChecker
except ImportError:
    Draft202012Validator = FormatChecker = None

ROOT = Path(__file__).resolve().parents[1]
CONFIG = "governance/cloudflare-os-integration.json"
SCHEMA = "schemas/cloudflare-os-integration.schema.json"
OPENMAUS = "governance/openmaus-integration.json"
MAX_BYTES = 262144
MAX_DEPTH = 32
SERVICE_STAGES = {
    "workers": "core", "durable_objects": "core",
    "dynamic_workers_and_facets": "core", "access": "hybrid_phase",
    "tunnel": "hybrid_phase", "r2": "artifact_phase",
    "workflows": "deferred", "queues": "deferred", "d1": "deferred",
    "ai_gateway": "deferred",
}
REPORT_CLAIMS = {"runtime_verified": False, "deployment_authorized": False}


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-finite number")


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite number")
    return number


def load_json(path: Path) -> dict[str, Any]:
    """Bound reads and refuse special files, symlinks, duplicate keys and deep JSON."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("not a regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_BYTES:
            raise ValueError("invalid file")
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("input too large")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_constant=_reject_constant, parse_float=_finite_float)
    if not isinstance(value, dict):
        raise ValueError("object required")
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise ValueError("input too deep")
        children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else ()
        stack.extend((child, depth + 1) for child in children)
    return value


def _no_external_refs(schema: Any) -> bool:
    stack = [schema]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for key in ("$ref", "$dynamicRef", "$recursiveRef"):
                if key in node and (not isinstance(node[key], str) or not node[key].startswith("#")):
                    return False
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return True


def _get(value: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _report(codes: list[str]) -> dict[str, Any]:
    return {"status": "FAIL" if codes else "PASS", "scope": "design_contract_only",
            "findings": [{"code": code} for code in sorted(set(codes))],
            "claims": dict(REPORT_CLAIMS)}


def validate(root: Path) -> dict[str, Any]:
    if Draft202012Validator is None:
        return _report(["VALIDATOR_UNAVAILABLE"])
    try:
        config, schema, base = (load_json(root / path) for path in (CONFIG, SCHEMA, OPENMAUS))
    except (OSError, ValueError, RecursionError):
        return _report(["INPUT_INVALID"])
    if not _no_external_refs(schema):
        return _report(["EXTERNAL_SCHEMA_REF_FORBIDDEN"])
    try:
        Draft202012Validator.check_schema(schema)
        if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(config):
            return _report(["SCHEMA_INVALID"])
    except Exception:
        return _report(["VALIDATOR_UNAVAILABLE"])
    codes: list[str] = []
    services = config["cloudflare_services"]
    observed = {entry["id"]: entry["stage"] for entry in services}
    if len(services) != len(observed) or observed != SERVICE_STAGES:
        codes.append("SERVICE_STAGE_DRIFT")
    if (_get(base, "management_model", "primary_human_surface") != config["composition"]["surface_ref"]
            or _get(base, "management_model", "no_parallel_authority") is not True
            or _get(base, "management_model", "principle") != "one_management_plane_multiple_execution_boundaries"):
        codes.append("PARALLEL_MANAGEMENT_PLANE")
    if (_get(base, "work_contract", "shared_work_identity_required") is not True
            or _get(base, "work_contract", "idempotency_required_for_dispatch") is not True
            or _get(base, "work_contract", "stop_request_requires_stop_observation") is not True):
        codes.append("SHARED_WORK_CONTRACT_DRIFT")
    if _get(base, "adapters", "proxmox", "direct_agent_access_to_proxmox_management") is not False:
        codes.append("PROXMOX_BOUNDARY_DRIFT")
    return _report(codes)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    report = validate(args.root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
