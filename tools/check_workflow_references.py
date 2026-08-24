#!/usr/bin/env python3
"""Require immutable references for external actions and Docker images."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


USES_PATTERN = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s#]+)")
ACTION_SHA_PATTERN = re.compile(r"^[^@\s]+@[0-9a-fA-F]{40}$")
DOCKER_DIGEST_PATTERN = re.compile(
    r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$"
)


def reference_violation(reference: str) -> str | None:
    """Return a bounded violation label, or None for an immutable reference."""

    if reference.startswith("./"):
        return None
    if reference.startswith("docker://"):
        if DOCKER_DIGEST_PATTERN.fullmatch(reference):
            return None
        return "Docker action image is not pinned to a sha256 digest"
    if ACTION_SHA_PATTERN.fullmatch(reference):
        return None
    return "external GitHub Action is not pinned to a full commit SHA"


def scan_workflows(root: Path) -> list[tuple[str, int, str]]:
    violations: list[tuple[str, int, str]] = []
    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = USES_PATTERN.match(line)
            if not match:
                continue
            reference = match.group(1).strip("'\"")
            violation = reference_violation(reference)
            if violation is not None:
                violations.append(
                    (path.relative_to(root).as_posix(), line_number, violation)
                )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    root = parser.parse_args().root.resolve()
    violations = scan_workflows(root)
    if violations:
        print("Workflow reference hygiene: FAIL")
        for path, line, violation in violations:
            print(f"  - {path}:{line}: {violation}")
        return 1
    print("Workflow reference hygiene: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
