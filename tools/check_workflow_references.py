#!/usr/bin/env python3
"""Require immutable references for external actions and Docker images."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


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


def mapping_values(node: Node, key: str) -> list[tuple[int, Node]]:
    if not isinstance(node, MappingNode):
        return []
    return [
        (key_node.start_mark.line + 1, value_node)
        for key_node, value_node in node.value
        if isinstance(key_node, ScalarNode) and key_node.value == key
    ]


def scalar_value(node: Node) -> str | None:
    return node.value.strip() if isinstance(node, ScalarNode) else None


def workflow_references(text: str) -> list[tuple[int, str | None, str]]:
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if root is None:
        return []

    references: list[tuple[int, str | None, str]] = []
    for _jobs_line, jobs in mapping_values(root, "jobs"):
        if not isinstance(jobs, MappingNode):
            continue
        for _job_name, job in jobs.value:
            if not isinstance(job, MappingNode):
                continue
            for line, reference in mapping_values(job, "uses"):
                references.append((
                    line,
                    scalar_value(reference),
                    "job",
                ))
            for _steps_line, steps in mapping_values(job, "steps"):
                if not isinstance(steps, SequenceNode):
                    continue
                for step in steps.value:
                    for line, reference in mapping_values(step, "uses"):
                        references.append((
                            line,
                            scalar_value(reference),
                            "step",
                        ))
    return references


def action_references(text: str) -> list[tuple[int, str | None, str]]:
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if root is None:
        return []

    references: list[tuple[int, str | None, str]] = []
    for _runs_line, runs in mapping_values(root, "runs"):
        if not isinstance(runs, MappingNode):
            continue
        using = [
            scalar_value(value) for _line, value in mapping_values(runs, "using")
        ]
        if any(value and value.lower() == "composite" for value in using):
            for _steps_line, steps in mapping_values(runs, "steps"):
                if not isinstance(steps, SequenceNode):
                    continue
                for step in steps.value:
                    for line, reference in mapping_values(step, "uses"):
                        references.append((line, scalar_value(reference), "step"))
        for line, image in mapping_values(runs, "image"):
            reference = scalar_value(image)
            if reference is not None and reference.lower().startswith("docker://"):
                references.append((line, reference, "image"))
    return references


def local_action_metadata(
    root: Path, reference: str
) -> tuple[Path | None, str | None]:
    candidate = (root / reference[2:]).resolve()
    if not candidate.is_relative_to(root):
        return None, "local action path escapes the repository root"
    matches: list[Path] = []
    for path in (candidate / "action.yml", candidate / "action.yaml"):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if not resolved.is_relative_to(root):
            return None, "local action metadata escapes the repository root"
        matches.append(resolved)
    if len(matches) != 1:
        return None, "local action must contain exactly one action.yml or action.yaml"
    return matches[0], None


def scan_workflows(root: Path) -> list[tuple[str, int, str]]:
    root = root.resolve()
    violations: list[tuple[str, int, str]] = []
    pending_actions: list[Path] = []

    def inspect_references(
        path: Path, references: list[tuple[int, str | None, str]]
    ) -> None:
        relative_path = path.relative_to(root).as_posix()
        for line_number, reference, kind in references:
            if reference is None:
                violations.append((
                    relative_path,
                    line_number,
                    "workflow uses reference must be a scalar literal",
                ))
                continue
            violation = reference_violation(reference)
            if violation is not None:
                violations.append((relative_path, line_number, violation))
                continue
            if kind == "step" and reference.startswith("./"):
                metadata, local_error = local_action_metadata(root, reference)
                if local_error is not None:
                    violations.append((relative_path, line_number, local_error))
                elif metadata is not None:
                    pending_actions.append(metadata)

    for path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        try:
            references = workflow_references(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            mark = getattr(error, "problem_mark", None)
            line = mark.line + 1 if mark is not None else 0
            violations.append((
                path.relative_to(root).as_posix(),
                line,
                f"workflow inspection failed ({type(error).__name__})",
            ))
            continue
        inspect_references(path, references)

    inspected_actions: set[Path] = set()
    while pending_actions:
        path = pending_actions.pop()
        if path in inspected_actions:
            continue
        inspected_actions.add(path)
        try:
            references = action_references(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            mark = getattr(error, "problem_mark", None)
            line = mark.line + 1 if mark is not None else 0
            violations.append((
                path.relative_to(root).as_posix(),
                line,
                f"action metadata inspection failed ({type(error).__name__})",
            ))
            continue
        inspect_references(path, references)

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
