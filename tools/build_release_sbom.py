"""Emit deterministic CycloneDX 1.6 lock inventories; never inspect an environment.

All conditional/platform packages are included. Hashes describe distribution
candidates, not installed bytes. Dependency graphs and license claims are omitted.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote

import yaml

LOCKS = {
    "python-ci": "requirements-ci.txt",
    "python-task-swarm": "requirements-task-swarm-ci.txt",
    "discord": "runtime/discord-template/pnpm-lock.yaml",
}


class UniqueLoader(yaml.SafeLoader):
    """Refuse silent loss of duplicate lock entries."""


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError("DUPLICATE_YAML_KEY")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def validate_marker(marker: str) -> None:
    variables = r"(?:python_version|python_full_version|os_name|sys_platform|platform_release|platform_system|platform_version|platform_machine|platform_python_implementation|implementation_name|implementation_version|extra)"
    value = rf'''(?:{variables}|"[^"\\]*"|'[^'\\]*')'''
    comparison = rf"{value}\s*(?:===|==|!=|<=|>=|~=|<|>|not\s+in|in)\s*{value}"
    token = re.compile(rf"\s*({comparison}|and\b|or\b|\(|\))")
    tokens = []
    pos = 0
    while pos < len(marker):
        match = token.match(marker, pos)
        if not match:
            raise ValueError("INVALID_PYTHON_MARKER")
        tokens.append(match.group(1))
        pos = match.end()
    # Alternating operand/operator grammar, with bounded balanced groups.
    need_operand, depth = True, 0
    for item in tokens:
        if need_operand:
            if item == '(':
                depth += 1
                if depth > 32:
                    raise ValueError("INVALID_PYTHON_MARKER")
            elif re.fullmatch(comparison, item):
                need_operand = False
            else:
                raise ValueError("INVALID_PYTHON_MARKER")
        elif item == ')' and depth:
            depth -= 1
        elif item in {'and', 'or'}:
            need_operand = True
        else:
            raise ValueError("INVALID_PYTHON_MARKER")
    if need_operand or depth:
        raise ValueError("INVALID_PYTHON_MARKER")


def component(ecosystem: str, name: str, version: str, hashes: list[dict]) -> dict:
    purl = f"pkg:{ecosystem}/{quote(name, safe='/')}@{quote(version, safe='')}"
    return {"type": "library", "bom-ref": purl, "name": name,
            "version": version, "purl": purl, "hashes": hashes}


def python_components(text: str) -> list[dict]:
    records = []
    # Remove comments before joining pip's continuation lines.
    lines = [line.split("#", 1)[0].strip() for line in text.splitlines()]
    logical = "\n".join(lines)
    logical = re.sub(r"\\\s*\n\s*", " ", logical)
    for line in logical.splitlines():
        if not line.strip():
            continue
        head, sep, encoded = line.strip().partition('--hash=')
        if not sep:
            raise ValueError("UNSUPPORTED_OR_UNHASHED_PYTHON_REQUIREMENT")
        encoded = sep + encoded
        requirement, marker_sep, marker = head.strip().partition(';')
        if marker_sep:
            validate_marker(marker.strip())
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[A-Za-z0-9,._-]+\])?==([^\s;]+)"
            , requirement.strip(),
        )
        if not match or not re.fullmatch(r"(?:--hash=sha256:[a-f0-9]{64}\s*)+", encoded):
            raise ValueError("UNSUPPORTED_OR_UNHASHED_PYTHON_REQUIREMENT")
        name, version = match.groups()
        name = re.sub(r"[-_.]+", "-", name).lower()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.!+_-]*", version):
            raise ValueError("INVALID_PYTHON_VERSION")
        hashes = [{"alg": "SHA-256", "content": h} for h in
                  sorted(set(re.findall(r"sha256:([a-f0-9]{64})", encoded)))]
        records.append(component("pypi", name, version, hashes))
    return records


def npm_components(text: str) -> list[dict]:
    lock = yaml.load(text, Loader=UniqueLoader)
    if not isinstance(lock, dict) or str(lock.get("lockfileVersion")) != "9.0":
        raise ValueError("UNSUPPORTED_PNPM_LOCK_VERSION")
    packages = lock.get("packages")
    if not isinstance(packages, dict) or not packages:
        raise ValueError("PNPM_PACKAGES_REQUIRED")
    records = []
    for identity, metadata in packages.items():
        if not isinstance(identity, str) or not isinstance(metadata, dict):
            raise ValueError("INVALID_PNPM_PACKAGE")
        name, sep, version = identity.rpartition("@")
        if not sep or not re.fullmatch(r"(?:@[a-z0-9._-]+/)?[a-z0-9._-]+", name):
            raise ValueError("UNSUPPORTED_PNPM_IDENTITY")
        if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version):
            raise ValueError("UNSUPPORTED_PNPM_VERSION")
        resolution = metadata.get("resolution", {})
        if not isinstance(resolution, dict) or set(resolution) != {"integrity"}:
            raise ValueError("UNSUPPORTED_PNPM_RESOLUTION")
        integrity = resolution["integrity"]
        if not isinstance(integrity, str):
            raise ValueError("INVALID_PNPM_INTEGRITY")
        hashes = []
        for token in integrity.split():
            alg, sep, encoded = token.partition("-")
            if not sep or alg not in {"sha256", "sha384", "sha512"}:
                raise ValueError("UNSUPPORTED_PNPM_HASH")
            try:
                digest = base64.b64decode(encoded, validate=True)
            except ValueError:
                raise ValueError("INVALID_PNPM_HASH") from None
            if len(digest) != {"sha256": 32, "sha384": 48, "sha512": 64}[alg]:
                raise ValueError("INVALID_PNPM_HASH_LENGTH")
            hashes.append({"alg": f"SHA-{alg[3:]}", "content": digest.hex()})
        if not hashes:
            raise ValueError("PNPM_HASH_REQUIRED")
        records.append(component("npm", name, version, sorted(hashes, key=lambda h: (h['alg'], h['content']))))
    return records


def build_bom(raw: bytes, lock_name: str, relative_path: str, release: str) -> dict:
    text = raw.decode("utf-8")
    records = npm_components(text) if lock_name == "discord" else python_components(text)
    if not records:
        raise ValueError("EMPTY_LOCK")
    refs = [r["bom-ref"] for r in records]
    if len(set(refs)) != len(refs):
        raise ValueError("DUPLICATE_COMPONENT")
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
        "metadata": {
            "component": {"type": "application", "name": f"kotodama-{lock_name}", "version": release},
            "properties": [
                {"name": "kotodama:lock:path", "value": relative_path},
                {"name": "kotodama:lock:sha256", "value": hashlib.sha256(raw).hexdigest()},
                {"name": "kotodama:scope", "value": "all locked distribution candidates; not an installed inventory"},
            ],
        },
        "components": sorted(records, key=lambda r: r["bom-ref"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"v[0-9][A-Za-z0-9._-]{0,100}", args.release):
        parser.error("release must be a bounded v-prefixed version")
    # Parse every input before creating output; exclusive creation protects saved artifacts.
    artifacts = []
    for name, relative in LOCKS.items():
        bom = build_bom((args.root / relative).read_bytes(), name, relative, args.release)
        artifacts.append((f"sbom-{name}-{args.release}.cdx.json", json.dumps(bom, ensure_ascii=False, sort_keys=True, indent=2) + "\n"))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if any((args.output_dir / name).exists() for name, _ in artifacts):
        raise ValueError("SBOM_OUTPUT_EXISTS")
    for name, content in artifacts:
        with (args.output_dir / name).open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
    print(json.dumps({"status": "PASS_LOCAL_LOCK_INVENTORY", "files": [name for name, _ in artifacts]}))


if __name__ == "__main__":
    main()
