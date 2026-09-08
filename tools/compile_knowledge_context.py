"""Compile bounded derived context only after exact package validation."""
import hashlib
import json
from pathlib import Path
from knowledge_work_validator import FALSE_CLAIMS, QuietParser, SENSITIVITY, emit, evaluation_time, validate_package


def compile_context(workspace, *, ceiling="public", max_claims=8, max_bytes=16384, now=None, source_root=None):
    if ceiling not in SENSITIVITY or type(max_claims) is not int or not 1 <= max_claims <= 64 or type(max_bytes) is not int or not 256 <= max_bytes <= 65536:
        raise ValueError("invalid context limits")
    validation, package = validate_package(workspace, now, source_root=source_root, ceiling=ceiling)
    required_ids = set()
    if validation["status"] == "PASS":
        required_ids = {c["id"] for c in package["claims"] if c["material"]}
        required_ids.update(c for a in package["assumptions"] + package["contradictions"] for c in a["claim_refs"])
    result = {"kind": "knowledge_context_bundle", "version": 1, "status": "REFUSED", "errors": [],
              "package_sha256": validation["package_sha256"], "subject_sha256": validation["subject_sha256"],
              "as_of": validation["as_of"], "sensitivity_ceiling": ceiling, "work_ref": None,
              "objective": None, "selected_claims": [], "sources": [], "assumptions": [], "questions": [],
              "contradictions": [], "omitted_ids": [], "context_sha256": None, "claims": dict(FALSE_CLAIMS)}
    if validation["status"] != "PASS":
        result["errors"] = ["SENSITIVITY_CEILING"] if "SENSITIVITY_CEILING" in validation["errors"] else ["PACKAGE_INVALID"]
    elif package["state"] != "candidate":
        result["errors"] = ["CANDIDATE_REQUIRED"]
    elif SENSITIVITY[package["sensitivity"]] > SENSITIVITY[ceiling]:
        result["errors"] = ["SENSITIVITY_CEILING"]
    elif len(required_ids) > max_claims:
        result["errors"] = ["REQUIRED_CONTEXT_BUDGET"]
    else:
        ordered = sorted(package["claims"], key=lambda c: (c["id"] not in required_ids, not c["material"], c["id"]))
        selected = ordered[:max_claims]
        source_ids = {s for c in selected for s in c["source_refs"]}
        result.update(status="READY_CANDIDATE", work_ref=package["work_ref"], objective=package["objective"],
                      selected_claims=selected, sources=[{k: s[k] for k in ["id", "sha256", "kind", "sensitivity", "expires_at"]}
                                                        for s in package["sources"] if s["id"] in source_ids],
                      assumptions=package["assumptions"], questions=package["questions"], contradictions=package["contradictions"],
                      omitted_ids=[c["id"] for c in ordered[max_claims:]])
        raw = json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
        # Reserve room for the 64-byte digest that replaces null before emission.
        if len(raw) + 64 > max_bytes:
            result.update(status="REFUSED", errors=["CONTEXT_BYTE_BUDGET"])
        else:
            result["context_sha256"] = hashlib.sha256(raw).hexdigest()
    if result["status"] == "REFUSED":
        result.update(package_sha256=None, subject_sha256=None, work_ref=None, objective=None, context_sha256=None,
                      selected_claims=[], sources=[], assumptions=[], questions=[], contradictions=[], omitted_ids=[])
    return result


def main():
    parser = QuietParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--ceiling", choices=list(SENSITIVITY), default="public")
    parser.add_argument("--source-root", type=Path, help="Operator-selected evidence root; defaults to workspace")
    parser.add_argument("--max-claims", type=int, default=8)
    parser.add_argument("--max-bytes", type=int, default=16384)
    parser.add_argument("--as-of")
    args = parser.parse_args()
    try:
        result = compile_context(args.workspace, ceiling=args.ceiling, max_claims=args.max_claims, max_bytes=args.max_bytes, now=evaluation_time(args.as_of), source_root=args.source_root)
    except (ValueError, TypeError):
        parser.error("invalid limits")
    emit(result)
    return 0 if result["status"] == "READY_CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
