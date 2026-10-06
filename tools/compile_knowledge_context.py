"""Compile Knowledge Work into the same bounded envelope as the existing KB."""
from __future__ import annotations

import hashlib
from pathlib import Path

from knowledge_context import canonical_bytes, context_json, make_context
from knowledge_work_validator import QuietParser, SENSITIVITY, evaluation_time, validate_package


def source_digest(validation):
    return hashlib.sha256(canonical_bytes({key: validation[key] for key in
        ("package_sha256", "subject_sha256", "bindings")})).hexdigest()


def refused(as_of, errors):
    # A refusal carries no package identity, body, acceptance or deliverables.
    return make_context(bundle_id="kotodama-knowledge-work", source_digest=None,
                        as_of=as_of, errors=errors)


def assert_current(workspace, context, *, ceiling, now, source_root):
    if context["state"] != "ready_candidate":
        return context
    latest, _ = validate_package(workspace, now, source_root=source_root, ceiling=ceiling)
    if latest["status"] != "PASS" or source_digest(latest) != context["source_digest"]:
        return refused(context["as_of"], ["SOURCE_DRIFT"])
    return context


def compile_context(workspace, *, ceiling="public", max_claims=8, max_bytes=16384, now=None, source_root=None):
    if ceiling not in SENSITIVITY or type(max_claims) is not int or not 1 <= max_claims <= 64 or type(max_bytes) is not int or not 256 <= max_bytes <= 65536:
        raise ValueError("invalid context limits")
    now = now or evaluation_time()
    validation, package = validate_package(workspace, now, source_root=source_root, ceiling=ceiling)
    instant = validation["as_of"]
    if validation["status"] != "PASS":
        return refused(instant, ["SENSITIVITY_CEILING"] if "SENSITIVITY_CEILING" in validation["errors"] else ["PACKAGE_INVALID"])
    if package["state"] != "candidate":
        return refused(instant, ["CANDIDATE_REQUIRED"])

    required = {claim["id"] for claim in package["claims"] if claim["material"]}
    required.update(ref for item in package["assumptions"] + package["contradictions"] for ref in item["claim_refs"])
    if len(required) > max_claims:
        return refused(instant, ["REQUIRED_CONTEXT_BUDGET"])
    ordered = sorted(package["claims"], key=lambda claim: (claim["id"] not in required, not claim["material"], claim["id"]))
    selected = ordered[:max_claims]
    source_ids = {ref for claim in selected for ref in claim["source_refs"]}
    work = {"package_sha256": validation["package_sha256"], "subject_sha256": validation["subject_sha256"],
        "sensitivity_ceiling": ceiling, "work_ref": package["work_ref"], "objective": package["objective"],
        "selected_claims": selected,
        "sources": [{key: source[key] for key in ("id", "sha256", "kind", "sensitivity", "expires_at")}
                    for source in package["sources"] if source["id"] in source_ids],
        "assumptions": package["assumptions"], "questions": package["questions"], "contradictions": package["contradictions"],
        "acceptance_criteria": [{"id": item["id"], "description": item["description"], "reported_state": item["state"],
                                 "deliverable_refs": item["deliverable_refs"]} for item in package["criteria"]],
        "deliverable_bindings": [{key: item[key] for key in ("id", "sha256", "criterion_refs")} for item in package["deliverables"]]}
    context = make_context(bundle_id="kotodama-knowledge-work", source_digest=source_digest(validation),
        as_of=instant, work=work, omitted_ids=[claim["id"] for claim in ordered[max_claims:]])
    if len(canonical_bytes(context)) + 1 > max_bytes:
        return refused(instant, ["CONTEXT_BYTE_BUDGET"])
    return assert_current(workspace, context, ceiling=ceiling, now=now, source_root=source_root)


def main():
    parser = QuietParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--ceiling", choices=list(SENSITIVITY), default="public")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--max-claims", type=int, default=8)
    parser.add_argument("--max-bytes", type=int, default=16384)
    parser.add_argument("--as-of")
    args = parser.parse_args()
    try:
        now = evaluation_time(args.as_of)
        value = compile_context(args.workspace, ceiling=args.ceiling, source_root=args.source_root,
            max_claims=args.max_claims, max_bytes=args.max_bytes, now=now)
        rendered = context_json(value)
        latest = assert_current(args.workspace, value, ceiling=args.ceiling, now=now, source_root=args.source_root)
        if latest != value:
            value, rendered = latest, context_json(latest)
    except (ValueError, TypeError):
        parser.error("invalid context inputs")
    print(rendered)
    return 0 if value["state"] == "ready_candidate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
