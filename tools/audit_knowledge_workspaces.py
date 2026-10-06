"""Audit bounded local knowledge-work packages using their exact evidence checks."""
import os
import stat
from pathlib import Path

from knowledge_work_validator import (
    FALSE_CLAIMS, MANIFEST, QuietParser, ROOT, SENSITIVITY, _plain_path,
    emit, evaluation_time, selected_root, validate_package,
)

MAX_ENTRIES = 4096
MAX_PACKAGES = 64


def discover_packages(root, workspaces):
    """Stream local entries without following links or silently skipping errors."""
    manifests = []
    examined = 0

    def add(path):
        manifests.append(path)
        if len(manifests) > MAX_PACKAGES:
            raise ValueError("package limit")

    for folder in ("examples/knowledge-work", "knowledge-work"):
        try:
            directory = _plain_path(root, folder)
        except FileNotFoundError:
            continue
        pending = [directory]
        while pending:
            current = pending.pop()
            _plain_path(root, current.relative_to(root).as_posix())
            with os.scandir(current) as entries:
                for entry in entries:
                    examined += 1
                    if examined > MAX_ENTRIES:
                        raise ValueError("entry limit")
                    details = entry.stat(follow_symlinks=False)
                    if (stat.S_ISLNK(details.st_mode)
                            or getattr(details, "st_file_attributes", 0) & 0x400):
                        raise ValueError("linked entry")
                    path = Path(entry.path)
                    if entry.name == MANIFEST:
                        if not stat.S_ISREG(details.st_mode):
                            raise ValueError("invalid manifest")
                        add(path)
                    elif stat.S_ISDIR(details.st_mode):
                        pending.append(path)
                    elif not stat.S_ISREG(details.st_mode):
                        raise ValueError("special entry")
    for workspace in workspaces:
        directory = _plain_path(root, workspace)
        if not directory.is_dir():
            raise ValueError("invalid workspace")
        add(_plain_path(root, workspace + "/" + MANIFEST))
    if len({os.path.normcase(str(path)) for path in manifests}) != len(manifests):
        raise ValueError("duplicate workspace")
    return sorted(manifests)


def main():
    parser = QuietParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--workspace", action="append", default=[], help="Additional root-relative package directory")
    parser.add_argument("--source-root", type=Path, help="Evidence root for all packages; defaults to each workspace")
    parser.add_argument("--ceiling", choices=list(SENSITIVITY), default="public")
    parser.add_argument("--as-of")
    parser.add_argument("--format", choices=["json", "markdown"], default="json")
    parser.add_argument("--fail-on", choices=["warning", "error"], default="error")
    parser.add_argument("--require-package", action="store_true")
    args = parser.parse_args()
    try:
        now = evaluation_time(args.as_of)
        root = selected_root(args.root)
        source_root = selected_root(args.source_root) if args.source_root is not None else None
        manifests = discover_packages(root, args.workspace)
        packages = [validate_package(path.parent, now, source_root=source_root, ceiling=args.ceiling)[0]
                    for path in manifests]
        errors = ["PACKAGE_REQUIRED"] if args.require_package and not packages else []
        failed = bool(errors) or any(p["errors"] or (args.fail_on == "warning" and p["warnings"]) for p in packages)
        report = {"kind": "knowledge_work_audit", "version": 1, "status": "FAIL" if failed else "PASS",
                  "packages": packages, "package_count": len(packages), "errors": errors,
                  "as_of": now.isoformat(), "claims": dict(FALSE_CLAIMS)}
    except (OSError, ValueError, TypeError, RecursionError):
        report = {"kind": "knowledge_work_audit", "version": 1, "status": "FAIL", "packages": [],
                  "package_count": 0, "errors": ["INPUT_INVALID"], "claims": dict(FALSE_CLAIMS)}
    emit(report, args.format)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
