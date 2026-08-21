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
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = ROOT / ".agents" / "skills"
FRONTMATTER = re.compile(r"\A---\r?\n(?P<body>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL)
FIELD = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
FORBIDDEN = {
    "private_absolute_path": re.compile(r"(?:[A-Za-z]:\\Users\\|/home/|/Users/)", re.I),
    "private_host": re.compile(r"\b(?:pve|ct)\s*20\d\b|\bdiscord\.gg\b", re.I),
    "local_endpoint": re.compile(r"\b(?:localhost|127\.0\.0\.1)\b", re.I),
    "remote_shell_or_deploy": re.compile(
        r"\b(?:ssh|systemctl|curl|pip\s+install)\b", re.I
    ),
    "runtime_private_path": re.compile(r"\b(?:runtime\.app|platform\\runtime|BOT2)\b", re.I),
    "fixed_model_claim": re.compile(
        r"\b(?:gpt-5\.\d+|o4-mini|sonnet|opus|haiku)\b", re.I
    ),
}
REQUIRED_HEADINGS = ("## Intent", "## Triggers", "## Non-triggers", "## Completion")
DESCRIPTION_SCOPE_PREFIX = "Use only for the Kotodama public repository "
MAX_SKILL_BYTES = 64 * 1024
MAX_SKILLS_PER_ROOT = 256


def _frontmatter(text: str) -> tuple[str | None, str | None, str | None]:
    match = FRONTMATTER.match(text)
    if not match:
        return None, None, "missing frontmatter"
    fields: dict[str, str] = {}
    for raw_line in match.group("body").splitlines():
        item = FIELD.match(raw_line.strip())
        if item:
            fields[item.group(1)] = item.group(2).strip().strip("'\"")
    name = fields.get("name")
    description = fields.get("description")
    if not name or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name):
        return name, description, "invalid name"
    if not description or len(description) > 1024:
        return name, description, "invalid description"
    return name, description, None


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
    if "## Procedure\n" not in text:
        return ["missing heading: ## Procedure"]
    procedure = text.split("## Procedure\n", 1)[1].split("\n## ", 1)[0]
    matches = list(re.finditer(r"(?m)^(\d+)\. ", procedure))
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


def _bounded_skill_paths(root: Path) -> tuple[list[Path], str | None]:
    if not root.exists() or not root.is_dir():
        return [], "missing skill root"
    paths = sorted(root.glob("*/SKILL.md"))
    if len(paths) > MAX_SKILLS_PER_ROOT:
        return [], f"skill count exceeds {MAX_SKILLS_PER_ROOT}"
    resolved_root = root.resolve()
    for path in paths:
        try:
            path.resolve().relative_to(resolved_root)
        except (OSError, ValueError):
            return [], "skill path escapes declared root"
    return paths, None


def _read_bounded(path: Path) -> tuple[str | None, str | None, str | None]:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_SKILL_BYTES + 1)
        if len(raw) > MAX_SKILL_BYTES:
            return None, None, f"skill exceeds {MAX_SKILL_BYTES} bytes"
        text = raw.decode("utf-8").replace("\r\n", "\n")
        return text, hashlib.sha256(raw).hexdigest(), None
    except (OSError, UnicodeError):
        return None, None, "skill is unreadable UTF-8"


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
        if name and name in names:
            findings.append(
                f"duplicate name: {name} ({names[name].relative_to(ROOT).as_posix()})"
            )
        elif name:
            names[name] = path
        if description and not description.startswith(DESCRIPTION_SCOPE_PREFIX):
            findings.append("description is not scoped to the Kotodama public repository")
        if description and description in descriptions:
            findings.append(
                f"duplicate description: {descriptions[description].relative_to(ROOT).as_posix()}"
            )
        elif description:
            descriptions[description] = path
        missing = [heading for heading in REQUIRED_HEADINGS if heading not in text]
        findings.extend(f"missing heading: {heading}" for heading in missing)
        findings.extend(_procedure_failures(text))
        findings.extend(_relative_link_failures(path, text))
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
            if name and name in names:
                findings.append(f"external duplicate name: {name}")
            elif name:
                names[name] = path
            if description and description in descriptions:
                findings.append("external duplicate description")
            elif description:
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
    return {
        "schema_version": "kotodama.public-skill-audit.v2",
        "status": "PASS" if not failures else "FAIL",
        "evidence_tier": "LOCAL",
        "changed": False,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "skill_count": len(records),
        "skills": records,
        "declared_external_roots": len(external_roots),
        "external_catalog_count": len(external_records),
        "external_skills": external_records,
        "failures": failures,
        "exit_code": 0 if not failures else 1,
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
