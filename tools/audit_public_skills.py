"""Read-only audit for the public Kotodama Agent Skills pack.

The public repository intentionally has no private runtime dependency. This
small standard-library tool checks the portable manifests, required intent
sections, relative links, and a deny-list of private or executable deployment
patterns. It never rewrites a skill or a catalog.
"""

from __future__ import annotations

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


def audit() -> dict[str, object]:
    failures: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    if not SKILLS_ROOT.exists():
        failures.append({"path": str(SKILLS_ROOT), "finding": "missing skill root"})
    paths = sorted(SKILLS_ROOT.glob("*/SKILL.md")) if SKILLS_ROOT.exists() else []
    names: dict[str, Path] = {}
    for path in paths:
        text = path.read_text(encoding="utf-8")
        name, description, frontmatter_error = _frontmatter(text)
        findings: list[str] = []
        if frontmatter_error:
            findings.append(frontmatter_error)
        if name and name in names:
            findings.append(f"duplicate name: {name} ({names[name].as_posix()})")
        elif name:
            names[name] = path
        missing = [heading for heading in REQUIRED_HEADINGS if heading not in text]
        findings.extend(f"missing heading: {heading}" for heading in missing)
        findings.extend(_relative_link_failures(path, text))
        for finding_name, pattern in FORBIDDEN.items():
            if pattern.search(text):
                findings.append(f"forbidden pattern: {finding_name}")
        record = {
            "path": path.relative_to(ROOT).as_posix(),
            "name": name,
            "description_present": bool(description),
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "findings": sorted(set(findings)),
        }
        records.append(record)
        failures.extend({"path": record["path"], "finding": item} for item in record["findings"])
    return {
        "schema_version": "kotodama.public-skill-audit.v1",
        "status": "PASS" if not failures else "FAIL",
        "evidence_tier": "LOCAL",
        "changed": False,
        "observed_at_utc": datetime.now(timezone.utc).isoformat(),
        "skill_count": len(records),
        "skills": records,
        "failures": failures,
        "exit_code": 0 if not failures else 1,
    }


def main() -> int:
    result = audit()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
