#!/usr/bin/env python3
"""Require immutable references for external actions and Docker images."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode


ACTION_SHA_PATTERN = re.compile(r"^[^@\s]+@[0-9a-fA-F]{40}$")
DOCKER_DIGEST_PATTERN = re.compile(
    r"^docker://[^@\s]+@sha256:[0-9a-f]{64}$"
)
CONTAINER_DIGEST_PATTERN = re.compile(
    r"^[^@\s]+@sha256:[0-9a-f]{64}$"
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


def container_image_violation(reference: str) -> str | None:
    if CONTAINER_DIGEST_PATTERN.fullmatch(reference):
        return None
    return "workflow container image is not pinned to a sha256 digest"


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

    def append_container_image(line: int, node: Node, kind: str) -> None:
        if kind == "service" and not isinstance(node, MappingNode):
            references.append((line, None, kind))
            return
        if isinstance(node, ScalarNode):
            references.append((line, scalar_value(node), kind))
            return
        images = mapping_values(node, "image")
        if not images:
            references.append((line, None, kind))
            return
        for image_line, image in images:
            references.append((image_line, scalar_value(image), kind))

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
            for line, container in mapping_values(job, "container"):
                append_container_image(line, container, "container")
            for _services_line, services in mapping_values(job, "services"):
                if not isinstance(services, MappingNode):
                    references.append((_services_line, None, "service"))
                    continue
                for service_name, service in services.value:
                    line = service_name.start_mark.line + 1
                    append_container_image(line, service, "service")
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


def is_git_repository(root: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def git_paths(root: Path, source: str) -> set[PurePosixPath]:
    if source == "HEAD":
        head = subprocess.run(
            ["git", "rev-parse", "--verify", "HEAD"],
            cwd=root,
            capture_output=True,
            check=False,
        )
        if head.returncode != 0:
            return set()
        command = [
            "git", "ls-tree", "-r", "--name-only", "-z", "HEAD", "--",
            ".github/workflows",
        ]
    elif source == "index":
        command = ["git", "ls-files", "-z", "--", ".github/workflows"]
    else:
        raise ValueError(f"unsupported Git source: {source}")
    output = subprocess.run(
        command, cwd=root, capture_output=True, check=True
    ).stdout
    result: set[PurePosixPath] = set()
    for raw in output.split(b"\0"):
        if not raw:
            continue
        path = PurePosixPath(raw.decode("utf-8", errors="strict"))
        if path.suffix.lower() in {".yml", ".yaml"}:
            result.add(path)
    return result


def safe_relative(reference: str) -> PurePosixPath | None:
    path = PurePosixPath(reference)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        return None
    return path


def read_snapshot(root: Path, path: PurePosixPath, source: str) -> bytes | None:
    relative = path.as_posix()
    if source == "HEAD":
        command = ["git", "show", f"HEAD:{relative}"]
    elif source == "index":
        command = ["git", "show", f":{relative}"]
    elif source == "working tree":
        candidate = (root / Path(*path.parts)).resolve()
        if not candidate.is_relative_to(root) or not candidate.is_file():
            return None
        return candidate.read_bytes()
    else:
        raise ValueError(f"unsupported snapshot source: {source}")
    result = subprocess.run(command, cwd=root, capture_output=True, check=False)
    return result.stdout if result.returncode == 0 else None


def workflow_snapshots(root: Path) -> list[tuple[str, PurePosixPath, bytes]]:
    if not is_git_repository(root):
        return [
            (
                "working tree",
                PurePosixPath(path.relative_to(root).as_posix()),
                path.read_bytes(),
            )
            for path in sorted((root / ".github" / "workflows").glob("*.y*ml"))
        ]

    by_source = {
        "HEAD": git_paths(root, "HEAD"),
        "index": git_paths(root, "index"),
    }
    by_source["working tree"] = by_source["HEAD"] | by_source["index"]
    snapshots: list[tuple[str, PurePosixPath, bytes]] = []
    for source, paths in by_source.items():
        for path in sorted(paths, key=lambda value: value.as_posix()):
            data = read_snapshot(root, path, source)
            if data is not None:
                snapshots.append((source, path, data))
    return snapshots


def local_action_metadata(
    root: Path, reference: str, source: str
) -> tuple[PurePosixPath | None, bytes | None, str | None]:
    candidate = safe_relative(reference[2:])
    if candidate is None:
        return None, None, "local action path escapes the repository root"
    metadata = [candidate / "action.yml", candidate / "action.yaml"]
    matches = [
        (path, data)
        for path in metadata
        if (data := read_snapshot(root, path, source)) is not None
    ]
    if len(matches) != 1:
        return (
            None,
            None,
            "local action must contain exactly one action.yml or action.yaml",
        )
    path, data = matches[0]
    if source == "working tree":
        resolved = (root / Path(*path.parts)).resolve()
        if not resolved.is_relative_to(root):
            return None, None, "local action metadata escapes the repository root"
    return path, data, None


def local_workflow_metadata(
    root: Path, reference: str, source: str
) -> tuple[PurePosixPath | None, bytes | None, str | None]:
    candidate = safe_relative(reference[2:])
    if candidate is None:
        return None, None, "local reusable workflow path escapes the repository root"
    if (
        candidate.parent != PurePosixPath(".github/workflows")
        or candidate.suffix.lower() not in {".yml", ".yaml"}
    ):
        return (
            None,
            None,
            "local reusable workflow must be a .yml or .yaml file directly under "
            ".github/workflows",
        )
    if source == "working tree":
        resolved = (root / Path(*candidate.parts)).resolve()
        if not resolved.is_relative_to(root):
            return (
                None,
                None,
                "local reusable workflow path escapes the repository root",
            )
    data = read_snapshot(root, candidate, source)
    if data is None:
        return None, None, "local reusable workflow does not exist in the snapshot"
    return candidate, data, None


def scan_workflows(root: Path) -> list[tuple[str, int, str]]:
    root = root.resolve()
    violations: list[tuple[str, int, str]] = []
    pending_workflows = workflow_snapshots(root)
    pending_actions: list[tuple[str, PurePosixPath, bytes]] = []

    def inspect_references(
        source: str,
        path: PurePosixPath,
        references: list[tuple[int, str | None, str]],
    ) -> None:
        relative_path = path.as_posix()
        for line_number, reference, kind in references:
            if reference is None:
                noun = (
                    "container image"
                    if kind in {"container", "service"}
                    else "uses reference"
                )
                violations.append((
                    relative_path,
                    line_number,
                    f"workflow {noun} must be a scalar literal [{source}]",
                ))
                continue
            violation = (
                container_image_violation(reference)
                if kind in {"container", "service"}
                else reference_violation(reference)
            )
            if violation is not None:
                violations.append((
                    relative_path, line_number, f"{violation} [{source}]"
                ))
                continue
            if kind == "job" and reference.startswith("./"):
                metadata, data, local_error = local_workflow_metadata(
                    root, reference, source
                )
                if local_error is not None:
                    violations.append((
                        relative_path, line_number, f"{local_error} [{source}]"
                    ))
                elif metadata is not None and data is not None:
                    pending_workflows.append((source, metadata, data))
            elif kind == "step" and reference.startswith("./"):
                metadata, data, local_error = local_action_metadata(
                    root, reference, source
                )
                if local_error is not None:
                    violations.append((
                        relative_path, line_number, f"{local_error} [{source}]"
                    ))
                elif metadata is not None and data is not None:
                    pending_actions.append((source, metadata, data))

    inspected_workflows: set[tuple[str, PurePosixPath]] = set()
    while pending_workflows:
        source, path, data = pending_workflows.pop()
        identity = (source, path)
        if identity in inspected_workflows:
            continue
        inspected_workflows.add(identity)
        try:
            references = workflow_references(data.decode("utf-8"))
        except (UnicodeError, yaml.YAMLError) as error:
            mark = getattr(error, "problem_mark", None)
            line = mark.line + 1 if mark is not None else 0
            violations.append((
                path.as_posix(),
                line,
                f"workflow inspection failed ({type(error).__name__}) [{source}]",
            ))
            continue
        inspect_references(source, path, references)

    inspected_actions: set[tuple[str, PurePosixPath]] = set()
    while pending_actions:
        source, path, data = pending_actions.pop()
        identity = (source, path)
        if identity in inspected_actions:
            continue
        inspected_actions.add(identity)
        try:
            references = action_references(data.decode("utf-8"))
        except (UnicodeError, yaml.YAMLError) as error:
            mark = getattr(error, "problem_mark", None)
            line = mark.line + 1 if mark is not None else 0
            violations.append((
                path.as_posix(),
                line,
                f"action metadata inspection failed ({type(error).__name__}) "
                f"[{source}]",
            ))
            continue
        inspect_references(source, path, references)

    return sorted(set(violations))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    root = parser.parse_args().root.resolve()
    try:
        violations = scan_workflows(root)
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as error:
        print(
            f"Workflow reference hygiene: ERROR ({type(error).__name__})",
            file=sys.stderr,
        )
        return 2
    if violations:
        print("Workflow reference hygiene: FAIL")
        for path, line, violation in violations:
            print(f"  - {path}:{line}: {violation}")
        return 1
    print("Workflow reference hygiene: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
