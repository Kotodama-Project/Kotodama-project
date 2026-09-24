"""Rule-based lint for the public documentation surface.

Standard library only. Prints one line of JSON and exits 0 on PASS, 1 on FAIL,
2 on usage error. The rules keep the entry documents short and current instead
of pinning their prose in tests:

1. README.md stays within 150 lines and docs/FIVE-MINUTE-TOUR.md within 120.
2. Every relative Markdown link in tracked ``*.md`` files resolves to an
   existing file, and every ``#anchor`` resolves to a heading or an explicit
   ``<a id="...">`` in the target document.
3. The entry documents do not leak internal revision numbers (``R123``) or
   governance-internal wording that a first visitor cannot act on, and README
   states the NO_GO_UNPUBLISHED boundary at most twice instead of after every
   section.
4. STATUS.md and ROADMAP.md do not narrate a historical revision as current.

Run ``python -S -B tools/lint_docs.py`` from the repository root.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINE_BUDGETS = {"README.md": 150, "docs/FIVE-MINUTE-TOUR.md": 120}
ENTRY_DOCUMENTS = ("README.md", "README.en.md", "docs/FIVE-MINUTE-TOUR.md")
BANNED_IN_ENTRY = (
    ("internal revision number", re.compile(r"\bR\d{2,3}\b")),
    (
        "governance-internal wording",
        re.compile(r"Promotion Candidate|attestation nonce|checkpoint segment"),
    ),
)
MAX_NO_GO_MENTIONS_IN_README = 2
HISTORICAL_AS_CURRENT = re.compile(r"\bR\d{2,3} (?:is|remains) the (?:current|latest)\b")
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
EXPLICIT_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")
FENCE = re.compile(r"^(```|~~~).*?^\1\s*$", re.MULTILINE | re.DOTALL)
SKIP_PARTS = {".git", "node_modules", ".venv", "work"}


def tracked_markdown(root: Path) -> list[Path]:
    names: list[str] = []
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--", "*.md", "**/*.md"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
        if completed.returncode == 0:
            names = [line for line in completed.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        names = []
    files = [root / name for name in names] if names else sorted(root.rglob("*.md"))
    return [
        f
        for f in files
        if f.is_file() and not (set(f.relative_to(root).parts) & SKIP_PARTS)
    ]


def github_anchor(heading: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", heading)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    body = FENCE.sub("", text)
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for match in HEADING.finditer(body):
        base = github_anchor(match.group(2))
        count = seen.get(base, 0)
        anchors.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    anchors.update(EXPLICIT_ANCHOR.findall(body))
    return anchors


def check_links(root: Path, files: list[Path]) -> list[str]:
    errors: list[str] = []
    cache: dict[Path, set[str]] = {}
    for file in files:
        text = file.read_text(encoding="utf-8")
        relative = file.relative_to(root).as_posix()
        for match in LINK.finditer(FENCE.sub("", text)):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path_part, _, fragment = target.partition("#")
            if path_part:
                resolved = (file.parent / path_part).resolve()
                if not resolved.exists():
                    errors.append(f"{relative}: broken link {target}")
                    continue
            else:
                resolved = file.resolve()
            if fragment and resolved.suffix == ".md":
                if resolved not in cache:
                    cache[resolved] = anchors_of(resolved.read_text(encoding="utf-8"))
                if fragment not in cache[resolved]:
                    errors.append(f"{relative}: unresolved anchor {target}")
    return errors


def check_entry_documents(root: Path) -> list[str]:
    errors: list[str] = []
    for name, budget in LINE_BUDGETS.items():
        path = root / name
        if not path.is_file():
            errors.append(f"{name}: missing")
            continue
        lines = path.read_text(encoding="utf-8").count("\n")
        if lines > budget:
            errors.append(f"{name}: {lines} lines exceeds the {budget}-line budget")
    for name in ENTRY_DOCUMENTS:
        path = root / name
        if not path.is_file():
            continue
        text = FENCE.sub("", path.read_text(encoding="utf-8"))
        for label, pattern in BANNED_IN_ENTRY:
            found = pattern.search(text)
            if found:
                errors.append(
                    f"{name}: {label} '{found.group(0)}' belongs in docs/, not in an entry document"
                )
    readme = root / "README.md"
    if readme.is_file():
        count = readme.read_text(encoding="utf-8").count("NO_GO_UNPUBLISHED")
        if count > MAX_NO_GO_MENTIONS_IN_README:
            errors.append(
                f"README.md: NO_GO_UNPUBLISHED appears {count} times; "
                "state the boundary once or twice and link STATUS.md"
            )
    return errors


def check_orientation_documents(root: Path) -> list[str]:
    errors: list[str] = []
    for name in ("STATUS.md", "ROADMAP.md"):
        path = root / name
        if not path.is_file():
            errors.append(f"{name}: missing")
            continue
        found = HISTORICAL_AS_CURRENT.search(path.read_text(encoding="utf-8"))
        if found:
            errors.append(
                f"{name}: '{found.group(0)}' narrates a historical revision as current; "
                "move it to docs/HISTORY.md"
            )
    return errors


def lint(root: Path) -> dict:
    files = tracked_markdown(root)
    errors = (
        check_entry_documents(root)
        + check_links(root, files)
        + check_orientation_documents(root)
    )
    return {
        "tool": "lint_docs",
        "version": "1.0",
        "status": "PASS" if not errors else "FAIL",
        "checked_files": len(files),
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] in ("-h", "--help"):
        sys.stdout.write((__doc__ or "").strip() + "\n")
        return 0
    if len(args) > 1 or (args and args[0].startswith("-")):
        sys.stdout.write(
            json.dumps({"tool": "lint_docs", "status": "REFUSED", "reason_codes": ["USAGE"]}) + "\n"
        )
        return 2
    root = Path(args[0]).resolve() if args else ROOT
    report = lint(root)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
