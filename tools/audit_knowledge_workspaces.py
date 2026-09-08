"""Audit declared knowledge-work packages; do not replace their checks with inventory."""
import os
from pathlib import Path
from knowledge_work_validator import FALSE_CLAIMS, MANIFEST, QuietParser, ROOT, SENSITIVITY, _plain_path, emit, evaluation_time, selected_root, validate_package


def main():
    parser = QuietParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--workspace", action="append", default=[], help="Additional --root-relative package directory")
    parser.add_argument("--source-root", type=Path, help="Evidence root for every package in this audit; defaults to each workspace")
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
        manifests = []
        examined = 0
        for folder in ["examples/knowledge-work", "knowledge-work"]:
            directory = root / folder
            if directory.is_symlink():
                raise ValueError("symlink root")
            if directory.exists():
                _plain_path(root, folder)
                for path in directory.rglob("*"):
                    examined += 1
                    if examined > 4096 or path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                        raise ValueError("unsafe discovery")
                    if path.name == MANIFEST:
                        _plain_path(root, path.relative_to(root).as_posix())
                        manifests.append(path)
                        if len(manifests) > 64:
                            raise ValueError("too many packages")
        for workspace in args.workspace:
            directory = _plain_path(root, workspace)
            if not directory.is_dir():
                raise ValueError("invalid workspace")
            manifests.append(_plain_path(root, workspace + "/" + MANIFEST))
            if len(manifests) > 64:
                raise ValueError("too many packages")
        if len({os.path.normcase(str(path)) for path in manifests}) != len(manifests):
            raise ValueError("duplicate workspace")
        packages = [validate_package(path.parent, now, source_root=source_root, ceiling=args.ceiling)[0] for path in sorted(manifests)]
        errors = ["PACKAGE_REQUIRED"] if args.require_package and not packages else []
        failed = bool(errors) or any(p["errors"] or (args.fail_on == "warning" and p["warnings"]) for p in packages)
        report = {"kind": "knowledge_work_audit", "version": 1, "status": "FAIL" if failed else "PASS",
                  "packages": packages, "package_count": len(packages), "errors": errors, "as_of": now.isoformat(),
                  "claims": dict(FALSE_CLAIMS)}
    except (OSError, ValueError, TypeError):
        report = {"kind": "knowledge_work_audit", "version": 1, "status": "FAIL", "packages": [],
                  "package_count": 0, "errors": ["INPUT_INVALID"], "claims": dict(FALSE_CLAIMS)}
    emit(report, args.format)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
