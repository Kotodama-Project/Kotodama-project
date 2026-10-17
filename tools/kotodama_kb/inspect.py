"""Bounded Concept/ATX section retrieval from the existing admitted snapshot."""
from __future__ import annotations

from .foundation import *  # noqa: F401,F403


def _headings(lines: Sequence[str]) -> list[tuple[int, int, str]]:
    headings = []
    fence: tuple[str, int] | None = None
    for index, line in enumerate(lines):
        text = line.rstrip("\r\n")
        if fence:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) +
                            "{" + str(fence[1]) + r",}[ \t]*", text):
                fence = None
            continue
        opening = re.match(r" {0,3}(`{3,}|~{3,})(.*)$", text)
        if opening and not (opening[1][0] == "`" and "`" in opening[2]):
            fence = (opening[1][0], len(opening[1]))
            continue
        heading = re.fullmatch(r" {0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)", text)
        if heading:
            title = (heading[2] or "").rstrip(" \t")
            tail = len(title)
            while tail and title[tail - 1] == "#":
                tail -= 1
            if tail < len(title) and (tail == 0 or title[tail - 1] in " \t"):
                title = title[:tail].rstrip(" \t")
            title = title.strip()
            headings.append((index, len(heading[1]), title))
    return headings


def _has_container_fence(lines: Sequence[str]) -> bool:
    # Container indentation needs a full block parser. Refuse section selection
    # rather than misidentify code as a heading or hide subsequent headings.
    pattern = re.compile(r"^[ \t]*+(?:>[ \t]*+|(?:[-+*]|\d{1,9}[.)])[ \t]++)+"
                         r"[ \t]*+(`{3,}|~{3,})(.*)$")
    for line in lines:
        match = pattern.match(line.rstrip("\r\n"))
        if match and not (match[1][0] == "`" and "`" in match[2]):
            return True
    return False


def inspect_concept(
    bundle: Bundle, concept_id: str, *, section: str | None = None,
    max_chars: int = 4000, offset: int = 0, expected_digest: str | None = None,
) -> dict[str, Any]:
    _require_valid_bundle(bundle)
    if type(max_chars) is not int or not 1 <= max_chars <= 65536:
        raise KnowledgeBaseError("SHOW_CHARACTER_BUDGET_INVALID")
    if type(offset) is not int or offset < 0:
        raise KnowledgeBaseError("SHOW_OFFSET_INVALID")
    if offset and expected_digest is None:
        raise KnowledgeBaseError("SHOW_RESUME_DIGEST_REQUIRED")
    if expected_digest is not None and expected_digest != bundle.source_digest:
        raise KnowledgeBaseError("SOURCE_CHANGED_RELOAD_REQUIRED")
    concept = bundle.by_id.get(concept_id)
    if concept is None:
        raise KnowledgeBaseError("SHOW_CONCEPT_UNAVAILABLE")
    extension = concept.extension
    if (not extension.get("agent_use", {}).get("discoverable", False)
            or concept.metadata.get("status") == "deprecated"
            or extension.get("knowledge_state") not in {"candidate", "confirmed"}
            or concept.is_stale):
        raise KnowledgeBaseError("SHOW_CONCEPT_UNAVAILABLE")

    lines = concept.document.body.splitlines(keepends=True)
    sections_supported = not _has_container_fence(lines)
    if section is not None and not sections_supported:
        raise KnowledgeBaseError("SHOW_SECTION_STRUCTURE_UNSUPPORTED")
    headings = _headings(lines) if sections_supported else []
    start, end = 0, len(lines)
    if section is not None:
        matches = [row for row in headings if row[2] == section]
        if not matches:
            raise KnowledgeBaseError("SHOW_SECTION_UNAVAILABLE")
        if len(matches) != 1:
            raise KnowledgeBaseError("SHOW_SECTION_AMBIGUOUS")
        start, level, _ = matches[0]
        end = next((index for index, depth, _ in headings
                    if index > start and depth <= level), len(lines))
    text = "".join(lines[start:end])
    if offset > len(text):
        raise KnowledgeBaseError("SHOW_OFFSET_INVALID")
    content = text[offset:offset + max_chars]
    next_offset = offset + len(content)
    # The parser preserves the raw frontmatter/body boundary and line endings.
    prefix = concept.document.raw[:len(concept.document.raw) - len(concept.document.body)]
    body_line = len(prefix.splitlines()) + 1
    report = {
        "id": concept.concept_id,
        "path": concept.document.path.relative_to(bundle.root).as_posix(),
        "title": concept.metadata.get("title"),
        "authority": extension.get("authority"),
        "knowledge_state": extension.get("knowledge_state"),
        "trust_tier": concept.trust_tier,
        "stale": concept.is_stale,
        "content_sha256": concept.content_sha256,
        "source_digest": bundle.source_digest,
        "as_of": bundle.as_of.isoformat().replace("+00:00", "Z"),
        "source_resources": list(concept.source_resources),
        "section": section,
        "sections_supported": sections_supported,
        "sections": [{"title": title, "level": level, "line": body_line + index}
                     for index, level, title in headings[:32]],
        "sections_total": len(headings),
        "sections_truncated": len(headings) > 32,
        "line_start": body_line + start,
        "line_end": body_line + end - 1,
        "offset": offset,
        "total_chars": len(text),
        "returned_chars": len(content),
        "truncated": next_offset < len(text),
        "next_offset": next_offset if next_offset < len(text) else None,
        "content": content,
    }
    resume = ["show", concept_id, "--root", str(bundle.root), "--json",
              "--offset", str(next_offset),
              "--expected-digest", bundle.source_digest, "--max-chars", str(max_chars),
              "--as-of", report["as_of"]]
    if section is not None:
        resume.extend(["--section", section])
    report["resume_args"] = resume if report["truncated"] else None
    _assert_current(bundle)
    return report


def inspection_markdown(report: Mapping[str, Any]) -> str:
    lines = [f"# {report['title']} [{report['id']}]",
             f"Source: {report['path']}:{report['line_start']}-{report['line_end']}",
             f"State: {report['knowledge_state']} / {report['trust_tier']} / {report['authority']}",
             f"As of: {report['as_of']}",
             f"Concept SHA-256: {report['content_sha256']}",
             f"Bundle source digest: {report['source_digest']}",
             "Sources: " + ", ".join(report["source_resources"]),
             f"Characters: {report['offset']} + {report['returned_chars']} / {report['total_chars']}"]
    if not report["sections_supported"]:
        lines.append("Sections: unsupported container fence structure; read the whole Concept")
    if report["truncated"]:
        lines.append(f"PARTIAL: repeat the same selection with --offset {report['next_offset']} "
                     f"--expected-digest {report['source_digest']} --as-of {report['as_of']}")
    return "\n".join(lines) + "\n\n" + report["content"]


__all__ = ["inspect_concept", "inspection_markdown"]
