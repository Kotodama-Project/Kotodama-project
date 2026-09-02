"""Read-only audit for the public Kotodama Agent Skills pack.

The public repository intentionally has no private runtime dependency. This
small standard-library tool checks the portable manifests, required intent
sections, relative links, and a deny-list of private or executable deployment
patterns. It never rewrites a skill or a catalog.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".agents" / "skills"
FRONTMATTER = re.compile(
    r"\A---[ \t]*\r?\n(?P<body>.*?)\r?\n---[ \t]*(?:\r?\n|\Z)",
    re.DOTALL,
)
FIELD = re.compile(r"^([A-Za-z0-9_-]+):(?:[ \t]+(.*))?$")
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FENCE = re.compile(r"^[ \t]{0,3}(?P<marker>`{3,}|~{3,})")
H2 = re.compile(r"^[ \t]{0,3}##[ \t]+.+$")
FORBIDDEN = {
    "private_absolute_path": re.compile(r"(?:[A-Za-z]:\\Users\\|/home/|/Users/)", re.I),
    "private_host": re.compile(r"\b(?:pve|ct)\s*20\d\b|\bdiscord\.gg\b", re.I),
    "local_endpoint": re.compile(r"\b(?:localhost|127\.0\.0\.1)\b", re.I),
    "remote_shell_or_deploy": re.compile(
        r"\b(?:ssh|systemctl|curl|pip\s+install)\b", re.I
    ),
    "runtime_private_path": re.compile(r"\b(?:runtime\.app|platform\\runtime|BOT2)\b", re.I),
}
FIXED_MODEL_CLAIM = re.compile(
    r"\b(?:"
    r"gpt[-_ ]\d+(?:[._-]\d+)*[a-z0-9.-]*"
    r"|o[1-9](?:[-_ ](?:mini|pro|preview))?"
    r"|gemini(?:[-_ ]\d+(?:[._-]\d+)*(?:[-_ ](?:pro|flash|ultra|nano|preview))?)"
    r"|claude[-_ ]\d+(?:[._-]\d+)*(?:[-_ ][a-z0-9]+)*"
    r"|(?:sonnet|opus|haiku)(?:[-_ ]\d+(?:[._-]\d+)*)?"
    r"|(?:llama|mistral|mixtral|qwen|deepseek|phi|falcon|grok|command|gemma|yi)"
    r"[-_ ]\d+(?:[._-]\d+)*(?:[-_ ][a-z0-9]+)*"
    r")\b",
    re.I,
)
MODEL_ASSIGNMENT = re.compile(
    r"\b(?:model|engine|llm)(?:[ _-]+(?:id|name))?[ \t]*(?:is[ \t]+|[:=])[ \t]*"
    r"[`\"']?(?P<value>[a-z][a-z0-9._-]{2,})",
    re.I,
)
MODEL_PLACEHOLDERS = {
    "auto",
    "configured",
    "current",
    "default",
    "dynamic",
    "env",
    "environment",
    "input",
    "model-id",
    "model_name",
    "none",
    "null",
    "provided",
    "runtime",
    "selected",
    "unknown",
    "unset",
    "user",
    "value",
    "your-model",
}
DIRECT_REPOSITORY_COMMAND = re.compile(
    r"\b(?:git[ \t]+push\b|gh[ \t]+(?:release[ \t]+create|pr[ \t]+merge|"
    r"repo[ \t]+(?:archive|delete|edit)))",
    re.I,
)
REQUIRED_HEADINGS = ("## Intent", "## Triggers", "## Non-triggers", "## Completion")
REQUIRED_SECTIONS = (*REQUIRED_HEADINGS[:3], "## Procedure", REQUIRED_HEADINGS[3])
DESCRIPTION_SCOPE_PREFIX = "Use only for the Kotodama public repository "
MAX_SKILL_BYTES = 64 * 1024
MAX_SKILLS_PER_ROOT = 256


def _frontmatter(text: str) -> tuple[str | None, str | None, str | None]:
    match = FRONTMATTER.match(text)
    if not match:
        return None, None, "missing frontmatter"
    fields: dict[str, str] = {}
    for line_number, raw_line in enumerate(match.group("body").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        item = FIELD.fullmatch(line)
        if not item:
            return fields.get("name"), fields.get("description"), (
                f"invalid frontmatter line {line_number}: expected key: value"
            )
        key = item.group(1)
        if key in fields:
            return fields.get("name"), fields.get("description"), (
                f"invalid frontmatter: duplicate key {key}"
            )
        value = (item.group(2) or "").strip()
        if value[:1] in {"'", '"'}:
            quote = value[0]
            closing_index: int | None = None
            escaped = False
            for index, character in enumerate(value[1:], start=1):
                if quote == '"' and character == "\\" and not escaped:
                    escaped = True
                    continue
                if character == quote and not escaped:
                    closing_index = index
                    break
                escaped = False
            if closing_index is None:
                return fields.get("name"), fields.get("description"), (
                    f"invalid frontmatter: unterminated {quote}quoted value for {key}"
                )
            trailing = value[closing_index + 1 :].strip()
            if trailing and not trailing.startswith("#"):
                return fields.get("name"), fields.get("description"), (
                    f"invalid frontmatter: trailing content after {key}"
                )
            value = value[1:closing_index]
        elif value[-1:] in {"'", '"'} or value.count('"') % 2:
            return fields.get("name"), fields.get("description"), (
                f"invalid frontmatter: unbalanced quote for {key}"
            )
        fields[key] = value
    name = fields.get("name")
    description = fields.get("description")
    if not name or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        return name, description, "invalid name"
    if not description or len(description) > 1024:
        return name, description, "invalid description"
    return name, description, None


def _markdown_lines(
    text: str,
    *,
    include_fenced: bool = False,
    excluded_section: str | None = None,
):
    current_section: str | None = None
    fence: tuple[str, int] | None = None
    for line in text.replace("\r\n", "\n").splitlines():
        marker = FENCE.match(line)
        if fence:
            if (
                marker
                and marker.group("marker")[0] == fence[0]
                and len(marker.group("marker")) >= fence[1]
            ):
                fence = None
            elif include_fenced and current_section != excluded_section:
                yield line
            continue
        if marker:
            raw_marker = marker.group("marker")
            fence = (raw_marker[0], len(raw_marker))
            continue
        stripped = line.strip()
        if H2.fullmatch(line):
            current_section = stripped
        if current_section != excluded_section:
            yield line


def _unfenced_lines(text: str) -> list[str]:
    return list(_markdown_lines(text))


def _section_failures(text: str) -> list[str]:
    headings = [line.strip() for line in _unfenced_lines(text) if H2.fullmatch(line)]
    failures = [
        f"missing heading: {heading}"
        for heading in REQUIRED_SECTIONS
        if heading not in headings
    ]
    ordered = [heading for heading in headings if heading in REQUIRED_SECTIONS]
    if not failures and ordered != list(REQUIRED_SECTIONS):
        failures.append(f"required headings must appear once and in order: {ordered}")
    return failures


def _relative_link_failures(path: Path, text: str) -> list[str]:
    failures: list[str] = []
    for raw in LINK.findall(text):
        link = raw.strip().strip("<>")
        if not link or link.startswith("#") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", link):
            continue
        target = link.split("#", 1)[0].split("?", 1)[0]
        if not target:
            continue
        resolved = (path.parent / target).resolve()
        try:
            resolved.relative_to(ROOT.resolve())
        except ValueError:
            failures.append(f"link outside repository: {link}")
            continue
        if not resolved.exists():
            failures.append(f"broken link: {link}")
    return failures


def _procedure_failures(text: str) -> list[str]:
    lines = _unfenced_lines(text)
    start = next(
        (
            index + 1
            for index, line in enumerate(lines)
            if H2.fullmatch(line) and line.strip() == "## Procedure"
        ),
        None,
    )
    if start is None:
        return []
    end = next(
        (index for index in range(start, len(lines)) if H2.fullmatch(lines[index])),
        len(lines),
    )
    procedure = "\n".join(lines[start:end])
    matches = list(re.finditer(r"(?m)^[ \t]{0,3}(\d+)\. ", procedure))
    numbers = [int(match.group(1)) for match in matches]
    failures: list[str] = []
    if numbers != [1, 2, 3, 4]:
        failures.append(f"procedure steps must be exactly 1..4: {numbers}")
        return failures
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(procedure)
        if "Done when:" not in procedure[match.start():end]:
            failures.append(f"procedure step {numbers[index]} missing Done when")
    return failures


def _fixed_model_failures(text: str) -> list[str]:
    for line in _markdown_lines(include_fenced=True, excluded_section="## Non-triggers", text=text):
        if FIXED_MODEL_CLAIM.search(line):
            return ["forbidden pattern: fixed_model_claim"]
        assignment = MODEL_ASSIGNMENT.search(line)
        if assignment and assignment.group("value").lower() not in MODEL_PLACEHOLDERS:
            return ["forbidden pattern: fixed_model_claim"]
    return []


def _direct_repository_command_failures(text: str) -> list[str]:
    for line in _markdown_lines(include_fenced=True, excluded_section="## Non-triggers", text=text):
        if DIRECT_REPOSITORY_COMMAND.search(line):
            return ["forbidden pattern: direct_repository_mutation"]
    return []


def _bounded_skill_paths(root: Path) -> tuple[list[Path], str | None]:
    if not root.exists() or not root.is_dir():
        return [], "missing skill root"
    paths: list[Path] = []
    for path in root.glob("*/SKILL.md"):
        paths.append(path)
        if len(paths) > MAX_SKILLS_PER_ROOT:
            return [], f"skill count exceeds {MAX_SKILLS_PER_ROOT}"
    paths.sort()
    resolved_root = root.resolve()
    for path in paths:
        try:
            path.resolve().relative_to(resolved_root)
        except (OSError, ValueError):
            return [], "skill path escapes declared root"
    return paths, None


def _read_bounded(path: Path) -> tuple[str | None, str | None, str | None]:
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None, None, "skill is not a regular file"
        with path.open("rb") as handle:
            raw = handle.read(MAX_SKILL_BYTES + 1)
        if len(raw) > MAX_SKILL_BYTES:
            return None, None, f"skill exceeds {MAX_SKILL_BYTES} bytes"
        text = raw.decode("utf-8").replace("\r\n", "\n")
        return text, hashlib.sha256(raw).hexdigest(), None
    except (OSError, UnicodeError):
        return None, None, "skill is unreadable UTF-8"


def _digest(value: object) -> str:
    raw = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def audit(external_roots: tuple[Path, ...] = ()) -> dict[str, object]:
    failures: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    paths, root_error = _bounded_skill_paths(SKILLS_ROOT)
    if root_error:
        failures.append({"path": ".agents/skills", "finding": root_error})
    names: dict[str, Path] = {}
    descriptions: dict[str, Path] = {}
    for path in paths:
        text, raw_sha256, read_error = _read_bounded(path)
        if read_error or text is None:
            record_path = path.relative_to(ROOT).as_posix()
            failures.append({"path": record_path, "finding": read_error})
            continue
        name, description, frontmatter_error = _frontmatter(text)
        findings: list[str] = []
        if frontmatter_error:
            findings.append(frontmatter_error)
        if name and not frontmatter_error and not name.startswith("kotodama-"):
            findings.append("name must use kotodama- namespace")
        if name and not frontmatter_error and name in names:
            findings.append(
                f"duplicate name: {name} ({names[name].relative_to(ROOT).as_posix()})"
            )
        elif name and not frontmatter_error:
            names[name] = path
        if description and not description.startswith(DESCRIPTION_SCOPE_PREFIX):
            findings.append("description is not scoped to the Kotodama public repository")
        if description and not frontmatter_error and description in descriptions:
            findings.append(
                f"duplicate description: {descriptions[description].relative_to(ROOT).as_posix()}"
            )
        elif description and not frontmatter_error:
            descriptions[description] = path
        findings.extend(_section_failures(text))
        findings.extend(_procedure_failures(text))
        findings.extend(_relative_link_failures(path, text))
        findings.extend(_fixed_model_failures(text))
        findings.extend(_direct_repository_command_failures(text))
        for finding_name, pattern in FORBIDDEN.items():
            if pattern.search(text):
                findings.append(f"forbidden pattern: {finding_name}")
        record = {
            "path": path.relative_to(ROOT).as_posix(),
            "name": name,
            "description_present": bool(description),
            "sha256": raw_sha256,
            "findings": sorted(set(findings)),
        }
        records.append(record)
        failures.extend({"path": record["path"], "finding": item} for item in record["findings"])

    external_records: list[dict[str, object]] = []
    for root_index, external_root in enumerate(external_roots):
        external_paths, external_error = _bounded_skill_paths(external_root)
        root_label = f"external[{root_index}]"
        if external_error:
            failures.append({"path": root_label, "finding": external_error})
            continue
        for path in external_paths:
            label = f"{root_label}/{path.parent.name}/SKILL.md"
            text, raw_sha256, read_error = _read_bounded(path)
            if read_error or text is None:
                failures.append({"path": label, "finding": read_error})
                continue
            name, description, frontmatter_error = _frontmatter(text)
            findings: list[str] = []
            if frontmatter_error:
                findings.append(f"external {frontmatter_error}")
            if name and not frontmatter_error and name in names:
                findings.append(f"external duplicate name: {name}")
            elif name and not frontmatter_error:
                names[name] = path
            if description and not frontmatter_error and description in descriptions:
                findings.append("external duplicate description")
            elif description and not frontmatter_error:
                descriptions[description] = path
            external_record = {
                "path": label,
                "name": name,
                "description_present": bool(description),
                "sha256": raw_sha256,
                "findings": sorted(set(findings)),
            }
            external_records.append(external_record)
            failures.extend(
                {"path": label, "finding": item} for item in external_record["findings"]
            )
    audit_payload = {
        "schema_version": "kotodama.public-skill-audit.v2",
        "status": "PASS" if not failures else "FAIL",
        "skill_count": len(records),
        "skills": records,
        "declared_external_roots": len(external_roots),
        "external_catalog_count": len(external_records),
        "external_skills": external_records,
        "failures": failures,
    }
    identity_digest = _digest(audit_payload)
    digest = f"sha256:{identity_digest}"
    return {
        "schema_version": "kotodama.skill-receipt.v1",
        "skill": "kotodama-surface-audit",
        "status": "COMPLETED" if not failures else "FAILED",
        "mode": "plan",
        "changed": False,
        "no_op": True,
        "no_op_reason": "read-only audit; no files changed",
        "evidence_tier": "LOCAL",
        "target": {"identity_digest": digest},
        "source_revision": digest,
        "before_sha256": digest,
        "after_sha256": digest,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "exit_code": 0 if not failures else 1,
        "actor": "UNKNOWN",
        "model_verification": "NOT_APPLICABLE",
        "approval_ref": None,
        "rollback_ref": None,
        "evidence_refs": [],
        "effect_counts": {"files_changed": 0, "network_writes": 0, "external_sends": 0},
        "no_go_reasons": [f"{item['path']}: {item['finding']}" for item in failures],
        "audit": audit_payload,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-skill-root", action="append", default=[], type=Path)
    args = parser.parse_args()
    result = audit(tuple(args.external_skill_root))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
