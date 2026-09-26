"""Create an unbound draft in a new directory; never overwrite or grant authority."""
import json
import re
from pathlib import Path
from knowledge_work_validator import MANIFEST, QuietParser


def create_package(target, package_id):
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", package_id):
        raise ValueError("invalid id")
    target.mkdir(parents=False, exist_ok=False)
    package = {"version": 1, "package_id": package_id, "work_ref": None, "state": "draft",
               "producer_ref": "ref/producer/unassigned", "sensitivity": "internal", "objective": "Define the question and bind an existing Work before use.",
               "sources": [], "claims": [], "assumptions": [], "questions": [], "contradictions": [], "criteria": [], "deliverables": [],
               "review": {"state": "not_run", "reviewer_ref": None, "subject_sha256": None}, "promotion": "blocked"}
    with (target / MANIFEST).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(package, ensure_ascii=False, indent=2) + "\n")
    return {"kind": "knowledge_work_creation", "status": "DRAFT_CREATED", "package_id": package_id,
            "work_bound": False, "execution_authorized": False, "promotion_created": False}


def main():
    parser = QuietParser(description=__doc__)
    parser.add_argument("target", type=Path)
    parser.add_argument("package_id")
    args = parser.parse_args()
    try:
        result = create_package(args.target, args.package_id)
    except (OSError, ValueError):
        print(json.dumps({"kind": "knowledge_work_creation", "status": "REFUSED", "errors": ["TARGET_OR_ID_REFUSED"]}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
