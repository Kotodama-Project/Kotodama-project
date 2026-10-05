"""Small, test-only contracts for the repository's existing Markdown dialect.

Link and anchor semantics come from tools/lint_docs.py. These helpers inspect
selected documents, not the complete tracked tree, and do not execute runbooks.
"""
from __future__ import annotations

import importlib.util
from functools import lru_cache
import subprocess
import sys
import tempfile
from typing import NamedTuple
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("document_contract_lint", ROOT / "tools/lint_docs.py")
assert _spec is not None and _spec.loader is not None
LINT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LINT)
BLOCK = re.compile(r"^(```|~~~)([^\n]*)\n(.*?)^\1\s*$", re.MULTILINE | re.DOTALL)
SHELLS = {"bash", "sh", "shell", "powershell", "pwsh"}


def headings(text: str) -> list[tuple[int, str, int]]:
    """Return (level, GitHub anchor, offset), excluding fenced examples."""
    body = LINT.FENCE.sub(lambda match: " " * len(match.group()), text)
    result = []
    seen: dict[str, int] = {}
    for match in LINT.HEADING.finditer(body):
        base = LINT.github_anchor(match.group(2))
        count = seen.get(base, 0)
        result.append((len(match.group(1)), base if count == 0 else f"{base}-{count}", match.start()))
        seen[base] = count + 1
    return result


def section(text: str, anchor: str) -> str:
    """Find an actual heading and stop at the next heading of equal/higher rank."""
    matches = headings(text)
    found = [(index, item) for index, item in enumerate(matches) if item[1] == anchor]
    if len(found) != 1:
        raise AssertionError(f"expected one document section: {anchor}")
    index, (level, _anchor, start) = found[0]
    end = next((offset for rank, _name, offset in matches[index + 1:] if rank <= level), len(text))
    return text[start:end]


def link_targets(text: str) -> list[str]:
    return LINT.LINK.findall(LINT.FENCE.sub("", text))


def assert_links(case, document: Path, text: str, required=()) -> None:
    """Verify selected links including their real target anchors, without a scan."""
    targets = link_targets(text)
    for target in required:
        case.assertIn(target, targets, f"missing navigation target: {target}")
    for target in targets:
        if target.startswith(("https://", "http://", "mailto:")):
            continue
        relative, _, fragment = target.partition("#")
        resolved = (document.parent / relative).resolve() if relative else document.resolve()
        case.assertTrue(resolved.is_file(), f"missing linked document: {target}")
        if fragment:
            case.assertEqual(resolved.suffix, ".md", "heading links must target Markdown")
            case.assertIn(fragment, LINT.anchors_of(resolved.read_text(encoding="utf-8")),
                          f"missing target anchor: {target}")


def fenced_blocks(text: str, language: str | None = None) -> list[str]:
    return [match.group(3) for match in BLOCK.finditer(text)
            if language is None or match.group(2).strip().lower() == language]


def canonical_command(command: str) -> str:
    # The repository documents both tools\\name.py and tools/name.py.
    return " ".join(command.strip().replace("tools\\", "tools/").split())


def shell_commands(text: str, language: str | None = None) -> list[str]:
    commands = []
    for match in BLOCK.finditer(text):
        kind = match.group(2).strip().lower()
        if kind not in SHELLS or (language is not None and kind != language):
            continue
        for line in match.group(3).splitlines():
            value = canonical_command(line)
            if value and not value.startswith("#"):
                commands.append(value)
    return commands


def assert_command_order(case, text: str, expected, language: str | None = None) -> None:
    commands = shell_commands(text, language)
    positions = []
    for command in expected:
        canonical = canonical_command(command)
        case.assertIn(canonical, commands, f"missing executable command: {canonical}")
        positions.append(commands.index(canonical))
    case.assertEqual(positions, sorted(positions), "documented command order changed")
    case.assertEqual(len(positions), len(set(positions)), "expected commands must be distinct")


def table_rows(text: str) -> list[list[str]]:
    """Parse the simple pipe tables used by the owned repository documents."""
    rows = []
    for line in LINT.FENCE.sub("", text).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-+:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def assert_preview_boundary(case, text: str, denied=()) -> None:
    """Require candidate markers and an explicit denial in each claim paragraph.

    This checks an authored statement, not human intent or runtime truth. The
    machine report/schema contract should be checked separately where present.
    """
    case.assertIn("NO_GO_UNPUBLISHED", text)
    case.assertRegex(text, r"read-only\s*/\s*candidate-only|read-only.*candidate-only")
    paragraphs = [" ".join(part.split()) for part in text.split("\n\n")]
    denial = re.compile(r"作られません|作らない|作らず|作り\s*ません|意味しません|証明しません|証明ではありません|"
                        r"未提供|未完了|not\s+(?:prove|establish|create)|"
                        r"does\s+not\s+(?:prove|establish|create)|"
                        r"do\s+not\s+(?:prove|establish|create)", re.IGNORECASE)
    for claim in denied:
        case.assertTrue(any(claim in paragraph and denial.search(paragraph) for paragraph in paragraphs),
                        f"missing explicit non-authorizing statement: {claim}")
    case.assertNotRegex(text, r"Public Beta GO\s*:\s*true|Human approval\s+is\s+verified")


class SmokeReceipt(NamedTuple):
    returncode: int
    stdout: str
    stderr: str
    before_entries: tuple[str, ...]
    after_entries: tuple[str, ...]


@lru_cache(maxsize=1)
def owned_smoke_receipt() -> SmokeReceipt:
    """Reuse one real foreign-cwd integration; cache no mutable report objects."""
    with tempfile.TemporaryDirectory() as temporary:
        caller = Path(temporary)
        before = tuple(sorted(path.name for path in caller.iterdir()))
        result = subprocess.run(
            [sys.executable, "-S", "-B", str(ROOT / "tools/smoke_company_pack_review_chain.py")],
            cwd=caller, capture_output=True, text=True, encoding="utf-8", errors="strict",
            timeout=90, check=False,
        )
        after = tuple(sorted(path.name for path in caller.iterdir()))
    return SmokeReceipt(result.returncode, result.stdout, result.stderr, before, after)
