#!/usr/bin/env python3
"""Detect likely live credentials in the current Git-tracked tree."""

from __future__ import annotations

import argparse
import codecs
import re
import subprocess
import sys
from pathlib import Path


MAX_TEXT_BYTES = 8 * 1024 * 1024
ALLOWED_ENV = {
    ".dev.vars.example",
    ".env.example",
    ".env.sample",
    ".env.template",
}
SENSITIVE_EXACT = {".env", "credentials.json", "id_ed25519", "id_rsa"}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx", ".ppk"}
TEXT_FILENAMES = {".dev.vars", ".env", "dockerfile", "makefile"}
TEXT_SUFFIXES = {
    ".c", ".cfg", ".cmd", ".conf", ".cpp", ".cs", ".css", ".csv",
    ".env", ".go", ".gradle", ".graphql", ".h", ".hcl", ".html",
    ".ini", ".java", ".js", ".json", ".kt", ".kts", ".lock", ".md",
    ".php", ".properties", ".ps1", ".py", ".rb", ".rs", ".sh",
    ".sql", ".swift", ".tf", ".toml", ".ts", ".txt", ".xml", ".yaml",
    ".yml",
}

TOKEN_PATTERNS = (
    ("GitHub token", re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{36,255}(?![A-Za-z0-9_])")),
    ("GitHub fine-grained token", re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{60,255}(?![A-Za-z0-9_])")),
    ("AWS access key ID", re.compile(r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])")),
    ("Google API key", re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])")),
    ("Slack token", re.compile(r"(?<![A-Za-z0-9-])xox[baprs]-[A-Za-z0-9-]{20,255}")),
    ("Stripe live key", re.compile(r"(?<![A-Za-z0-9_])(?:sk|rk)_live_[A-Za-z0-9]{20,255}")),
    ("Anthropic API key", re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{40,255}")),
    ("OpenAI API key", re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{48,255}")),
)

ASSIGNMENT_NAMES = (
    "ANTHROPIC_API_KEY", "AWS_SECRET_ACCESS_KEY", "CF_API_KEY", "CF_API_TOKEN",
    "CLOUDFLARE_API_TOKEN", "DATABASE_URL", "DISCORD_TOKEN", "GEMINI_API_KEY",
    "GITHUB_TOKEN", "GH_TOKEN", "GOOGLE_API_KEY", "N8N_ENCRYPTION_KEY",
    "KOTODAMA_COMPANY_DB_PASSWORD", "KOTODAMA_EVIDENCE_DB_PASSWORD",
    "OPENAI_API_KEY", "POSTGRES_PASSWORD", "SLACK_BOT_TOKEN",
)
ASSIGNMENT = re.compile(
    r"^\s*(?:-\s*|ARG\s+|export\s+|\$env:|ENV\s+|setx?\s+)?[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s*(?::|=(?![=>~]))\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
SPACE_ASSIGNMENT = re.compile(
    r"^\s*(?:ENV\s+|setx?\s+)[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
BARE_SPACE_ASSIGNMENT = re.compile(
    r"^\s*[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s+(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
STRUCTURED_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_])[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s*:\s*(?P<value>"
    + r"\$\{\{[^{}\r\n]+\}\}|\$\{[^{}\r\n]+\}|"
    + r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\r\n]+>|"
    + r'"(?:\\.|[^"\\])*"'
    + r"|'(?:\\.|[^'\\])*'|[^,}\]]+)",
    re.IGNORECASE,
)
INLINE_ASSIGNMENT = re.compile(
    r"(?<![A-Za-z0-9_])[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s*=(?![=>~])\s*(?P<value>"
    + r"\$\{\{[^{}\r\n]+\}\}|\$\{[^{}\r\n]+\}|"
    + r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\r\n]+>|"
    + r'"(?:\\.|[^"\\])*"'
    + r"|'(?:\\.|[^'\\])*'|[^,;}\]]+)",
    re.IGNORECASE,
)
PRIVATE_BEGIN = re.compile(
    r"(?:-----BEGIN (?:(?:(?:ENCRYPTED|RSA|DSA|EC|OPENSSH) )?PRIVATE KEY|"
    r"PGP PRIVATE KEY BLOCK)-----|PuTTY-User-Key-File-[23]:)"
)


def index_blobs(root: Path) -> dict[Path, str]:
    output = subprocess.run(
        ["git", "ls-files", "-s", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    result: dict[Path, str] = {}
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        _mode, oid, stage = metadata.decode("ascii").split()
        if stage != "0":
            raise ValueError("unmerged index entry")
        result[Path(raw_path.decode("utf-8", errors="strict"))] = oid
    return result


def head_blobs(root: Path) -> dict[Path, str]:
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if head.returncode != 0:
        return {}
    output = subprocess.run(
        ["git", "ls-tree", "-r", "-z", "HEAD"],
        cwd=root,
        capture_output=True,
        check=True,
    ).stdout
    result: dict[Path, str] = {}
    for raw in output.split(b"\0"):
        if not raw:
            continue
        metadata, raw_path = raw.split(b"\t", 1)
        _mode, object_type, oid = metadata.decode("ascii").split()
        if object_type == "blob":
            result[Path(raw_path.decode("utf-8", errors="strict"))] = oid
    return result


def blob_sizes(root: Path, oids: set[str]) -> dict[str, int]:
    if not oids:
        return {}
    output = subprocess.run(
        [
            "git",
            "cat-file",
            "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        ],
        cwd=root,
        input=("\n".join(sorted(oids)) + "\n").encode("ascii"),
        capture_output=True,
        check=True,
    ).stdout
    result: dict[str, int] = {}
    for line in output.decode("ascii").splitlines():
        oid, object_type, size = line.split()
        if object_type != "blob":
            raise ValueError("tracked Git object is not a blob")
        result[oid] = int(size)
    return result


def read_blobs(root: Path, oids: set[str]) -> dict[str, bytes]:
    if not oids:
        return {}
    output = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=root,
        input=("\n".join(sorted(oids)) + "\n").encode("ascii"),
        capture_output=True,
        check=True,
    ).stdout
    result: dict[str, bytes] = {}
    offset = 0
    while offset < len(output):
        end = output.index(b"\n", offset)
        oid, object_type, raw_size = output[offset:end].decode("ascii").split()
        if object_type != "blob":
            raise ValueError("tracked Git object is not a blob")
        size = int(raw_size)
        start = end + 1
        result[oid] = output[start:start + size]
        offset = start + size + 1
    return result


def text_like_path(path: Path) -> bool:
    return path.name.lower() in TEXT_FILENAMES or path.suffix.lower() in TEXT_SUFFIXES


def looks_like_text(data: bytes) -> bool:
    sample = data[:8192]
    if not sample:
        return True
    control = sum(
        (byte < 32 and byte not in {8, 9, 10, 12, 13}) or byte == 127
        for byte in sample
    )
    return control / len(sample) <= 0.01


def decode_text_snapshot(path: Path, data: bytes) -> tuple[str | None, str | None]:
    encodings = (
        (codecs.BOM_UTF32_LE, "utf-32"),
        (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF16_LE, "utf-16"),
        (codecs.BOM_UTF16_BE, "utf-16"),
        (codecs.BOM_UTF8, "utf-8-sig"),
    )
    for marker, encoding in encodings:
        if data.startswith(marker):
            try:
                return data.decode(encoding), None
            except UnicodeDecodeError:
                return None, "tracked text BOM has invalid encoded content"
    if b"\0" in data[:8192]:
        if text_like_path(path):
            return None, "tracked text-like file contains unrecognized NUL encoding"
        return None, None
    try:
        return data.decode("utf-8"), None
    except UnicodeDecodeError:
        if text_like_path(path) or looks_like_text(data):
            return None, "tracked text-like file is not UTF-8 or BOM-backed Unicode"
        return None, None


def source_label(sources: set[str]) -> str:
    order = {"HEAD": 0, "index": 1, "working tree": 2}
    return "/".join(sorted(sources, key=lambda source: order[source]))


def sensitive_filename(path: Path) -> bool:
    name = path.name.lower()
    parts = tuple(part.lower() for part in path.parts)
    if (bool(parts) and parts[0] == "work") or any(
        part in {".terraform", ".wrangler"} for part in parts
    ):
        return True
    if name in ALLOWED_ENV or (
        name.startswith((".dev.vars.", ".env.")) and name.endswith(".example")
    ):
        return False
    return (
        name in SENSITIVE_EXACT
        or name == ".dev.vars"
        or name.startswith(".dev.vars.")
        or name.startswith(".env.")
        or name.endswith(".tfstate")
        or ".tfstate." in name
        or path.suffix.lower() in SENSITIVE_SUFFIXES
        or re.fullmatch(r"credentials(?:[-_.].+)?\.json", name) is not None
        or re.fullmatch(r"service[-_]account(?:[-_.].+)?\.json", name) is not None
    )


def assignment_value(raw: str) -> str:
    value = raw.strip().rstrip(",").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1].strip()
    return value


def placeholder(value: str) -> bool:
    stripped = value.strip()
    normalized = stripped.strip("'\"")
    lower = normalized.lower()
    if not lower or lower in {"none", "null", "nil", "undefined"}:
        return True
    if re.fullmatch(
        r"(?:\$\{\{\s*(?:env|secrets|vars)\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}|"
        r"\$\{[A-Za-z_][A-Za-z0-9_]*(?:(?::?\?)[^{}\r\n]*)?\}|"
        r"\{[A-Za-z_][A-Za-z0-9_]*\}|<[^<>\r\n]+>)",
        normalized,
    ):
        return True
    marker = re.fullmatch(
        r"(?:changeme|change-me|dummy|example|fake|not-a-real|placeholder|"
        r"redacted|replace-me|replaceme|sample|synthetic|test-only)"
        r"(?:[._-][a-z0-9._-]+)?",
        lower,
    )
    reference = re.fullmatch(
        r"(?:(?:env|secrets|vars)\.[a-z_][a-z0-9_]*|"
        r"process\.env\.[a-z_][a-z0-9_]*|"
        r"os\.environ(?:\[['\"][a-z_][a-z0-9_]*['\"]\]|"
        r"\.get\(['\"][a-z_][a-z0-9_]*['\"]\))|"
        r"your[-_][a-z0-9._-]+)",
        lower,
    )
    return (
        lower == "demo"
        or marker is not None
        or reference is not None
        or re.fullmatch(r"[*xX._-]{8,}", normalized) is not None
    )


def live_assignment(value: str) -> bool:
    return not placeholder(value)


def assignment_expression_continues(line: str, value_end: int) -> bool:
    remainder = line[value_end:]
    return re.match(r"\s*(?:\+|\.|\|\||&&|\?\?)", remainder) is not None


def shell_parameter_assignments(line: str) -> list[tuple[str, str]]:
    """Return sensitive shell default/assignment expansions, including nesting."""

    assignments: list[tuple[str, str]] = []
    stack: list[int] = []
    index = 0
    names = sorted(ASSIGNMENT_NAMES, key=len, reverse=True)
    while index < len(line):
        if line.startswith("${", index):
            stack.append(index)
            index += 2
            continue
        if line[index] == "}" and stack:
            start = stack.pop()
            body = line[start + 2:index]
            upper = body.upper()
            for name in names:
                if not upper.startswith(name):
                    continue
                remainder = body[len(name):]
                for operator in (":-", ":=", ":+", "-", "=", "+"):
                    if remainder.startswith(operator):
                        assignments.append((name, remainder[len(operator):]))
                        break
                break
        index += 1
    return assignments


def scan_text(path: Path, text: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        for detector, pattern in TOKEN_PATTERNS:
            if pattern.search(line):
                findings.append((path.as_posix(), number, detector))
        matches = []
        patterns = [ASSIGNMENT, SPACE_ASSIGNMENT]
        if path.suffix.lower() == ".properties":
            patterns.append(BARE_SPACE_ASSIGNMENT)
        for pattern in patterns:
            match = pattern.match(line)
            if match is not None:
                matches.append(match)
        name_spans = {candidate.span("name") for candidate in matches}
        for candidate in (
            *STRUCTURED_ASSIGNMENT.finditer(line),
            *INLINE_ASSIGNMENT.finditer(line),
        ):
            name_start = candidate.start("name")
            if name_start >= 2 and line[name_start - 2:name_start] == "${":
                continue
            if candidate.span("name") not in name_spans:
                matches.append(candidate)
                name_spans.add(candidate.span("name"))
        reported_assignments: set[str] = set()
        for match in matches:
            name = match.group("name").upper()
            value_is_live = live_assignment(assignment_value(match.group("value")))
            if (
                name not in reported_assignments
                and (
                    value_is_live
                    or assignment_expression_continues(line, match.end("value"))
                )
            ):
                findings.append((
                    path.as_posix(),
                    number,
                    f"live-looking value assigned to {name}",
                ))
                reported_assignments.add(name)
        for name, value in shell_parameter_assignments(line):
            name = name.upper()
            if name not in reported_assignments and live_assignment(value):
                findings.append((
                    path.as_posix(),
                    number,
                    f"live-looking value assigned to {name}",
                ))
                reported_assignments.add(name)
        if PRIVATE_BEGIN.search(line):
            findings.append((path.as_posix(), number, "private key block"))
    return findings


def scan_repository(root: Path) -> tuple[list[tuple[str, int, str]], int, int]:
    root = root.resolve()
    findings: list[tuple[str, int, str]] = []
    index = index_blobs(root)
    head = head_blobs(root)
    paths = set(index) | set(head)
    oids = set(index.values()) | set(head.values())
    sizes = blob_sizes(root, oids)
    readable_oids = {oid for oid, size in sizes.items() if size <= MAX_TEXT_BYTES}
    contents = read_blobs(root, readable_oids)
    text_files = 0

    for relative in sorted(paths, key=lambda path: path.as_posix()):
        if sensitive_filename(relative):
            findings.append((relative.as_posix(), 0, "sensitive tracked filename"))

        snapshots: dict[bytes, set[str]] = {}
        for source, oid in (("HEAD", head.get(relative)), ("index", index.get(relative))):
            if oid is None:
                continue
            if sizes[oid] > MAX_TEXT_BYTES:
                findings.append((
                    relative.as_posix(),
                    0,
                    f"tracked file exceeds scan size limit [{source}]",
                ))
                continue
            snapshots.setdefault(contents[oid], set()).add(source)

        path = root / relative
        try:
            if path.is_symlink():
                data = path.readlink().as_posix().encode()
            elif path.exists():
                size = path.stat().st_size
                if size > MAX_TEXT_BYTES:
                    findings.append((
                        relative.as_posix(),
                        0,
                        "tracked file exceeds scan size limit [working tree]",
                    ))
                    data = None
                else:
                    data = path.read_bytes()
            else:
                data = None
        except (OSError, ValueError) as error:
            findings.append((
                relative.as_posix(),
                0,
                f"working-tree inspection failed ({type(error).__name__})",
            ))
            continue
        if data is not None:
            snapshots.setdefault(data, set()).add("working tree")

        for snapshot, sources in snapshots.items():
            text, decode_error = decode_text_snapshot(relative, snapshot)
            label = source_label(sources)
            if decode_error is not None:
                findings.append((
                    relative.as_posix(), 0, f"{decode_error} [{label}]"
                ))
                continue
            if text is None:
                continue
            text_files += 1
            for reported_path, line, detector in scan_text(relative, text):
                findings.append((reported_path, line, f"{detector} [{label}]"))
    return sorted(set(findings)), len(paths), text_files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    try:
        findings, tracked, text_files = scan_repository(root)
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError) as error:
        print(f"Tracked credential hygiene: ERROR ({type(error).__name__})", file=sys.stderr)
        return 2
    if findings:
        print("Tracked credential hygiene: FAIL", file=sys.stderr)
        for path, line, detector in findings:
            location = f"{path}:{line}" if line else path
            print(f"  - {location}: {detector}", file=sys.stderr)
        print(
            f"Inspected {tracked} tracked paths ({text_files} decoded text snapshots "
            "across HEAD, index, and working tree). "
            "Secret values were not printed.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Tracked credential hygiene: PASS ({tracked} tracked paths; "
        f"{text_files} decoded text snapshots across HEAD, index, and working tree)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
