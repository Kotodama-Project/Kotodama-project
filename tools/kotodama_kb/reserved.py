from __future__ import annotations

from .foundation import *  # noqa: F401,F403

def _validate_reserved_files(bundle_root: Path) -> list[Issue]:
    issues: list[Issue] = []
    root_index = bundle_root / RESERVED_INDEX
    if not root_index.is_file():
        issues.append(Issue("error", "MISSING_ROOT_INDEX", "knowledge/index.md", "root index is required by the Kotodama profile"))
    else:
        try:
            metadata = _frontmatter_from_root_index(root_index)
            if metadata.get("okf_version") != "0.2":
                issues.append(Issue("error", "OKF_VERSION", "knowledge/index.md", "root index must declare okf_version: '0.2'"))
            unknown = set(metadata) - {"okf_version"}
            if unknown:
                issues.append(Issue("error", "ROOT_INDEX_FRONTMATTER", "knowledge/index.md", f"root index frontmatter has unsupported keys: {sorted(unknown)}"))
        except KnowledgeBaseError as exc:
            issues.append(Issue("error", "ROOT_INDEX_FRONTMATTER", "knowledge/index.md", str(exc)))

    for index_path in bundle_root.rglob(RESERVED_INDEX):
        if index_path == root_index:
            continue
        raw = index_path.read_text(encoding="utf-8")
        if raw.startswith("---"):
            issues.append(Issue("error", "NESTED_INDEX_FRONTMATTER", index_path.relative_to(bundle_root.parent).as_posix(), "only the bundle-root index.md may contain frontmatter"))

    for log_path in bundle_root.rglob(RESERVED_LOG):
        raw = log_path.read_text(encoding="utf-8")
        if raw.startswith("---"):
            issues.append(Issue("error", "LOG_FRONTMATTER", log_path.relative_to(bundle_root.parent).as_posix(), "log.md must not contain frontmatter"))
        headings = re.findall(r"^##\s+(.+?)\s*$", raw, flags=re.MULTILINE)
        for heading in headings:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", heading):
                issues.append(Issue("error", "LOG_DATE", log_path.relative_to(bundle_root.parent).as_posix(), f"log date heading is not YYYY-MM-DD: {heading}"))
        if headings != sorted(headings, reverse=True):
            issues.append(Issue("error", "LOG_ORDER", log_path.relative_to(bundle_root.parent).as_posix(), "log dates must be newest first"))
    return issues



__all__ = [name for name in globals() if not name.startswith("__")]
