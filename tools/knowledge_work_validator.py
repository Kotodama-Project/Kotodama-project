"""Bounded, read-only structural evidence for one existing Work's knowledge package.

No model invocation, remote retrieval, approval, Task write or Promotion. The
workspace must be operator-selected; this is not a hostile-writer OS sandbox.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from validate_resolved_compose_candidate import load_strict_json_bytes

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "knowledge-work.json"
MAX_PACKAGE_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
SENSITIVITY = {"public": 0, "internal": 1, "restricted": 2}
FALSE_CLAIMS = {"human_approval_verified": False, "reviewer_identity_verified": False,
                "semantic_entailment_verified": False, "execution_authorized": False,
                "promotion_created": False, "current_truth_changed": False}


class Refusal(ValueError):
    pass


class QuietParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "invalid arguments\n")


def evaluation_time(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    if len(value) == 10:
        value += "T00:00:00+00:00"
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise Refusal("CLOCK_INVALID")
    return result.astimezone(timezone.utc)


def selected_root(value: Path):
    """Validate an operator-selected local directory without resolving links away."""
    path = Path(value)
    spelling = str(path)
    if spelling.startswith(("\\\\", "//")) or ".." in path.parts or (path.drive and not path.is_absolute()):
        raise Refusal("ROOT_REFUSED")
    path = Path(os.path.abspath(path))
    current = Path(path.anchor)
    for part in [None, *path.parts[1:]]:
        if part is not None:
            current /= part
        details = current.lstat()
        if (not stat.S_ISDIR(details.st_mode) or stat.S_ISLNK(details.st_mode)
                or getattr(details, "st_file_attributes", 0) & 0x400):
            raise Refusal("ROOT_REFUSED")
    return path


def _plain_path(root: Path, relative: str):
    root = selected_root(root)
    if not isinstance(relative, str) or not relative or len(relative) > 512 or any(c in relative for c in "\\:\x00"):
        raise Refusal("PATH_REFUSED")
    parts = relative.split("/")
    if any(not p or p in {".", ".."} or p.lower() == ".git" for p in parts):
        raise Refusal("PATH_REFUSED")
    target = root
    for part in [None, *parts]:
        if part is not None:
            target /= part
        details = target.lstat()
        if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise Refusal("PATH_REFUSED")
    target.resolve().relative_to(root.resolve())
    return target


def read_bound(root: Path, relative: str, limit: int):
    path = _plain_path(root, relative)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > limit or before.st_nlink != 1:
        raise Refusal("FILE_REFUSED")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise Refusal("SOURCE_DRIFT")
        chunks, size = [], 0
        while size <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    final = _plain_path(root, relative).lstat()
    fields = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if size > limit or fields(before) != fields(after) or fields(after) != fields(final):
        raise Refusal("SOURCE_DRIFT")
    return b"".join(chunks)


def subject_digest(package):
    subject = {k: v for k, v in package.items() if k != "review"}
    return hashlib.sha256(json.dumps(subject, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def validate_package(root: Path, now=None, *, source_root: Path | None = None, ceiling="public"):
    now = now or evaluation_time()
    errors, warnings = [], []
    report = {"kind": "knowledge_work_validation", "version": 1, "status": "FAIL", "package_id": None,
              "package_sha256": None, "subject_sha256": None, "as_of": now.isoformat(),
              "errors": errors, "warnings": warnings, "bindings": [], "claims": dict(FALSE_CLAIMS)}
    package = None
    try:
        if ceiling not in SENSITIVITY:
            raise Refusal("SENSITIVITY_CEILING_INVALID")
        root = selected_root(root)
        evidence_root = selected_root(source_root) if source_root is not None else root
        raw = read_bound(root, MANIFEST, MAX_PACKAGE_BYTES)
        package = load_strict_json_bytes(raw)
        schema = load_strict_json_bytes((ROOT / "schemas/knowledge-work-package.schema.json").read_bytes())
        if not Draft202012Validator(schema, format_checker=FormatChecker()).is_valid(package):
            raise Refusal("SCHEMA_INVALID")
        declared = [package["sensitivity"], *[item["sensitivity"] for key in ["sources", "claims"] for item in package[key]]]
        if any(SENSITIVITY[value] > SENSITIVITY[package["sensitivity"]] for value in declared):
            errors.append("SENSITIVITY_DOWNGRADE")
        # Refuse before reading bound evidence or reporting private identifiers.
        if any(SENSITIVITY[value] > SENSITIVITY[ceiling] for value in declared):
            raise Refusal("SENSITIVITY_CEILING")
        report.update(package_id=package["package_id"], package_sha256=hashlib.sha256(raw).hexdigest(), subject_sha256=subject_digest(package))
        names = [item["id"] for key in ["sources", "claims", "assumptions", "questions", "contradictions", "criteria", "deliverables"] for item in package[key]]
        if len(names) != len(set(names)):
            raise Refusal("DUPLICATE_ID")
        sources = {s["id"]: s for s in package["sources"]}
        claims = {c["id"]: c for c in package["claims"]}
        criteria = {c["id"]: c for c in package["criteria"]}
        deliverables = {d["id"]: d for d in package["deliverables"]}
        if any(SENSITIVITY[item["sensitivity"]] > SENSITIVITY[package["sensitivity"]] for item in [*sources.values(), *claims.values()]):
            errors.append("SENSITIVITY_DOWNGRADE")
        total = len(raw)
        for category in ["sources", "deliverables"]:
            for item in package[category]:
                content = read_bound(evidence_root, item["path"], MAX_ARTIFACT_BYTES)
                total += len(content)
                if total > MAX_TOTAL_BYTES:
                    raise Refusal("AGGREGATE_LIMIT")
                actual = hashlib.sha256(content).hexdigest()
                if actual != item["sha256"]:
                    errors.append("SOURCE_DIGEST_MISMATCH" if category == "sources" else "DELIVERABLE_DIGEST_MISMATCH")
                report["bindings"].append({"id": item["id"], "sha256": actual, "bytes": len(content)})
        for source in sources.values():
            expiry = source["expires_at"]
            if source["kind"] == "local_snapshot" and expiry is None:
                errors.append("FRESHNESS_REQUIRED")
            if expiry is not None and evaluation_time(expiry) <= now:
                errors.append("SOURCE_EXPIRED")
        assumption_claims = set()
        for item in package["assumptions"]:
            if not set(item["claim_refs"]) <= claims.keys():
                errors.append("CLAIM_REF_UNKNOWN")
            assumption_claims.update(item["claim_refs"])
        for claim in claims.values():
            if not set(claim["source_refs"]) <= sources.keys():
                errors.append("SOURCE_REF_UNKNOWN")
                continue
            if claim["material"] and claim["kind"] != "assumption" and not claim["source_refs"]:
                errors.append("MATERIAL_CLAIM_UNSUPPORTED")
            if claim["kind"] == "assumption" and claim["id"] not in assumption_claims:
                errors.append("ASSUMPTION_UNTRACKED")
            if any(SENSITIVITY[sources[s]["sensitivity"]] > SENSITIVITY[claim["sensitivity"]] for s in claim["source_refs"]):
                errors.append("SENSITIVITY_DOWNGRADE")
        for item in package["contradictions"]:
            if not set(item["claim_refs"]) <= claims.keys():
                errors.append("CLAIM_REF_UNKNOWN")
            if item["state"] == "open":
                (errors if item["severity"] == 1 and package["state"] == "candidate" else warnings).append("CONTRADICTION_OPEN")
        if any(q["blocking"] and q["state"] == "open" for q in package["questions"]):
            (errors if package["state"] == "candidate" else warnings).append("BLOCKING_QUESTION_OPEN")
        for criterion in criteria.values():
            refs = criterion["deliverable_refs"]
            if not set(refs) <= deliverables.keys():
                errors.append("DELIVERABLE_REF_UNKNOWN")
            elif any(criterion["id"] not in deliverables[d]["criterion_refs"] for d in refs):
                errors.append("CRITERION_MAPPING_MISMATCH")
            if package["state"] == "candidate" and (criterion["state"] != "met" or not refs):
                errors.append("ACCEPTANCE_PENDING")
        for deliverable in deliverables.values():
            refs = deliverable["criterion_refs"]
            if not refs or not set(refs) <= criteria.keys():
                errors.append("CRITERION_REF_UNKNOWN")
            elif any(deliverable["id"] not in criteria[c]["deliverable_refs"] for c in refs):
                errors.append("CRITERION_MAPPING_MISMATCH")
        if package["state"] == "candidate" and (package["work_ref"] is None or not claims or not criteria or not deliverables):
            errors.append("CANDIDATE_INCOMPLETE")
        review = package["review"]
        if review["state"] == "performed":
            if review["reviewer_ref"] is None or review["reviewer_ref"] == package["producer_ref"]:
                errors.append("REVIEWER_NOT_INDEPENDENT")
            if review["subject_sha256"] != report["subject_sha256"]:
                errors.append("REVIEW_BINDING_MISMATCH")
            warnings.append("REVIEW_IDENTITY_UNVERIFIED")
        elif review["reviewer_ref"] is not None or review["subject_sha256"] is not None:
            errors.append("REVIEW_STATE_MISMATCH")
        else:
            warnings.append("SEMANTIC_REVIEW_NOT_RUN")
        if read_bound(root, MANIFEST, MAX_PACKAGE_BYTES) != raw:
            errors.append("PACKAGE_DRIFT")
        # Re-read the exact dependent bytes at the end; a stable manifest alone
        # cannot prove that a source did not change during the rest of the audit.
        for category in ["sources", "deliverables"]:
            for item in package[category]:
                if hashlib.sha256(read_bound(evidence_root, item["path"], MAX_ARTIFACT_BYTES)).hexdigest() != item["sha256"]:
                    errors.append("SOURCE_DRIFT")
        report["status"] = "PASS" if not errors else "FAIL"
    except (OSError, ValueError, TypeError, RecursionError) as error:
        # Never reflect source bodies, paths, schema values or filesystem errors.
        errors.append(str(error) if isinstance(error, Refusal) else "INPUT_INVALID")
    report["errors"] = sorted(set(errors))
    report["warnings"] = sorted(set(warnings))
    return report, package


def emit(value, format="json"):
    if format == "markdown":
        print(f"# Knowledge Work: {value['status']}")
        for item in value.get("packages", [value]):
            print(f"- {item.get('package_id') or 'unresolved'}: {item['status']}; errors={','.join(item.get('errors', [])) or 'none'}")
        print("\nStructural evidence only; no approval, execution, semantic truth or Promotion.")
    else:
        print(json.dumps(value, ensure_ascii=False, sort_keys=True))
