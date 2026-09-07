from __future__ import annotations

from .foundation import *  # noqa: F401,F403
from .reserved import *  # noqa: F401,F403
from .load import *  # noqa: F401,F403
from .project import *  # noqa: F401,F403
from .retrieve import *  # noqa: F401,F403
from .audit import *  # noqa: F401,F403

def _print_issues(issues: Iterable[Issue]) -> None:
    for issue in issues:
        print(f"{issue.level.upper()} {issue.code} {issue.path}: {issue.message}")


def _add_common_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (default: inferred from tools/knowledge_base.py)",
    )
    parser.add_argument(
        "--as-of",
        help="ISO 8601 audit instant; defaults to current UTC time",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate OKF and Kotodama profile invariants")
    _add_common_root(validate_parser)
    validate_parser.add_argument("--warnings-as-errors", action="store_true")

    build_parser = subparsers.add_parser("build", help="build deterministic catalog and graph projections")
    _add_common_root(build_parser)
    build_parser.add_argument("--check", action="store_true", help="refuse when generated files differ instead of writing them")

    audit_parser = subparsers.add_parser("audit", help="report knowledge-quality measurements and findings")
    _add_common_root(audit_parser)
    audit_parser.add_argument("--format", choices=("json", "markdown"), default="json")
    audit_parser.add_argument("--fail-on-errors", action="store_true")
    audit_parser.add_argument("--fail-on-critical-stale", action="store_true")

    query_parser = subparsers.add_parser("query", help="run transparent lexical retrieval over current concepts")
    _add_common_root(query_parser)
    query_parser.add_argument("query")
    query_parser.add_argument("--limit", type=int, default=10)
    query_parser.add_argument("--type")
    query_parser.add_argument("--tag")
    query_parser.add_argument("--include-stale", action="store_true")
    query_parser.add_argument("--json", action="store_true")

    context_parser = subparsers.add_parser("context", help="assemble bounded goal/KGI/initiative context")
    _add_common_root(context_parser)
    context_parser.add_argument("--goal", action="append", default=[])
    context_parser.add_argument("--kgi", action="append", default=[])
    context_parser.add_argument("--initiative", action="append", default=[])
    context_parser.add_argument("--tag", action="append", default=[])
    context_parser.add_argument("--max-concepts", type=int)
    context_parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        as_of = _parse_as_of(args.as_of)
        bundle = load_bundle(args.root, as_of=as_of)
    except KnowledgeBaseError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    errors = [issue for issue in bundle.issues if issue.level == "error"]
    warnings = [issue for issue in bundle.issues if issue.level == "warning"]

    if args.command == "validate":
        _print_issues(bundle.issues)
        print(f"Validated {len(bundle.concepts)} concepts: {len(errors)} errors, {len(warnings)} warnings")
        if errors or (args.warnings_as_errors and warnings):
            return 1
        return 0

    if args.command == "build":
        if errors:
            _print_issues(errors)
            print("Refusing to build projections from an invalid bundle", file=sys.stderr)
            return 1
        changed = build(bundle, check=args.check)
        if args.check and changed:
            print("Generated knowledge projections are stale:")
            for path in changed:
                print(f"- {path}")
            return 1
        action = "Would update" if args.check else "Updated"
        if changed:
            print(f"{action} {len(changed)} projection(s):")
            for path in changed:
                print(f"- {path}")
        else:
            print("Generated knowledge projections are current")
        return 0

    if args.command == "audit":
        report = audit_report(bundle, as_of=as_of)
        if args.format == "markdown":
            print(audit_markdown(report), end="")
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.fail_on_errors and errors:
            return 1
        if args.fail_on_critical_stale:
            critical_tags = set(bundle.profile["quality"].get("critical_tags", []))
            if any(concept.is_stale and set(concept.metadata.get("tags", [])) & critical_tags for concept in bundle.concepts):
                return 1
        return 0

    if args.command == "query":
        if args.limit < 1 or args.limit > 100:
            print("ERROR: --limit must be between 1 and 100", file=sys.stderr)
            return 2
        results = query_bundle(
            bundle,
            args.query,
            limit=args.limit,
            type_filter=args.type,
            tag_filter=args.tag,
            include_stale=args.include_stale,
        )
        if args.json:
            rows = [
                {
                    "id": result.concept.concept_id,
                    "path": result.concept.document.path.relative_to(bundle.root).as_posix(),
                    "title": result.concept.metadata.get("title"),
                    "description": result.concept.metadata.get("description"),
                    "score": round(result.score, 4),
                    "reasons": list(result.reasons),
                    "trust_tier": result.concept.trust_tier,
                    "knowledge_state": result.concept.extension.get("knowledge_state"),
                    "stale": result.concept.is_stale,
                    "source_resources": list(result.concept.source_resources),
                }
                for result in results
            ]
            print(json.dumps({"query": args.query, "results": rows}, ensure_ascii=False, indent=2))
        else:
            for index, result in enumerate(results, start=1):
                concept = result.concept
                print(f"{index}. {concept.metadata.get('title')} [{concept.concept_id}] score={result.score:.2f}")
                print(f"   {concept.metadata.get('description')}")
                print(f"   state={concept.extension.get('knowledge_state')} trust={concept.trust_tier} stale={concept.is_stale}")
                print(f"   path={concept.document.path.relative_to(bundle.root).as_posix()}")
                print(f"   sources={', '.join(concept.source_resources)}")
        return 0

    if args.command == "context":
        selection = select_context(
            bundle,
            goals=args.goal,
            kgis=args.kgi,
            initiatives=args.initiative,
            tags=args.tag,
            max_concepts=args.max_concepts,
        )
        context = context_as_dict(selection, bundle=bundle)
        if args.json:
            print(json.dumps(context, ensure_ascii=False, indent=2))
        else:
            print(context_markdown(context), end="")
        return 0 if context["state"] == "ready_candidate" else 3

    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

__all__ = [name for name in globals() if not name.startswith("__")]
