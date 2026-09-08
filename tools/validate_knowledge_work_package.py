"""Validate a package's exact local evidence, with no authority-producing path."""
from pathlib import Path
from knowledge_work_validator import QuietParser, emit, evaluation_time, validate_package


def main():
    parser = QuietParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--as-of")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    args = parser.parse_args()
    try:
        report, _ = validate_package(args.workspace, evaluation_time(args.as_of))
    except (ValueError, TypeError):
        parser.error("invalid clock")
    emit(report, args.format)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
