#!/usr/bin/env python3
"""Detect likely live credentials in the current Git-tracked tree."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


MAX_TEXT_BYTES = 8 * 1024 * 1024
ALLOWED_ENV = {".env.example", ".env.sample", ".env.template"}
SENSITIVE_EXACT = {".env", "credentials.json", "id_ed25519", "id_rsa"}
SENSITIVE_SUFFIXES = {".key", ".p12", ".pem", ".pfx"}

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
    "OPENAI_API_KEY", "SLACK_BOT_TOKEN",
)
ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?[\"']?(?P<name>"
    + "|".join(map(re.escape, ASSIGNMENT_NAMES))
    + r")[\"']?\s*[:=]\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)
PRIVATE_BEGIN = re.compile(r"-----BEGIN (?:(?:RSA|DSA|EC|OPENSSH) )?PRIVATE KEY-----")
PRIVATE_END = re.compile(r"-----END (?:(?:RSA|DSA|EC|OPENSSH) )?PRIVATE KEY-----")


def tracked_paths(root: Path) -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True
    ).stdout
    return [
        Path(raw.decode("utf-8", errors="strict"))
        for raw in output.split(b"\0")
        if raw
    ]


def sensitive_filename(path: Path) -> bool:
    name = path.name.lower()
    if name in ALLOWED_ENV:
        return False
    return (
        name in SENSITIVE_EXACT
        or name.startswith(".env.")
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
    lower = value.strip().lower()
    if not lower or lower in {"none", "null", "nil", "undefined"}:
        return True
    if value.lstrip().startswith(("${", "${{", "$(", "<")):
        return True
    markers = (
        "changeme", "change-me", "demo", "dummy", "example", "fake",
        "not-a-real", "placeholder", "redacted", "replace-me", "replaceme",
        "sample", "secrets.", "test-only", "vars.", "your-", "your_",
    )
    return (
        any(marker in lower for marker in markers)
        or lower.startswith(("env.", "os.environ", "process.env"))
        or re.fullmatch(r"[*xX._-]{8,}", value.strip()) is not None
    )


def live_assignment(value: str) -> bool:
    if placeholder(value) or len(value) < 16 or any(c.isspace() for c in value):
        return False
    classes = (
        any(c.islower() for c in value),
        any(c.isupper() for c in value),
        any(c.isdigit() for c in value),
        any(not c.isalnum() for c in value),
    )
    return sum(classes) >= 2


def scan_text(path: Path, text: str) -> list[tuple[str, int, str]]:
    findings: list[tuple[str, int, str]] = []
    lines = text.splitlines()
    for number, line in enumerate(lines, 1):
        for detector, pattern in TOKEN_PATTERNS:
            if pattern.search(line):
                findings.append((path.as_posix(), number, detector))
        match = ASSIGNMENT.match(line)
        if match and live_assignment(assignment_value(match.group("value"))):
            findings.append((
                path.as_posix(),
                number,
                f"live-looking value assigned to {match.group('name').upper()}",
            ))

    begin = None
    body = 0
    for number, line in enumerate(lines, 1):
        if begin is None:
            if PRIVATE_BEGIN.search(line):
                begin, body = number, 0
        elif PRIVATE_END.search(line):
            if body >= 80:
                findings.append((path.as_posix(), begin, "private key block"))
            begin, body = None, 0
        else:
            body += len(re.sub(r"[^A-Za-z0-9+/=]", "", line))
    return findings


def scan_repository(root: Path) -> tuple[list[tuple[str, int, str]], int, int]:
    root = root.resolve()
    findings: list[tuple[str, int, str]] = []
    tracked = text_files = 0
    for relative in tracked_paths(root):
        tracked += 1
        if sensitive_filename(relative):
            findings.append((relative.as_posix(), 0, "sensitive tracked filename"))
        path = root / relative
        try:
            if path.is_symlink():
                data = path.readlink().as_posix().encode()
            else:
                size = path.stat().st_size
                with path.open("rb") as stream:
                    prefix = stream.read(8192)
                if b"\0" in prefix:
                    continue
                if size > MAX_TEXT_BYTES:
                    findings.append((relative.as_posix(), 0, "tracked text file exceeds scan size limit"))
                    continue
                data = path.read_bytes()
        except (OSError, ValueError) as error:
            findings.append((relative.as_posix(), 0, f"inspection failed ({type(error).__name__})"))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        text_files += 1
        findings.extend(scan_text(relative, text))
    return sorted(set(findings)), tracked, text_files


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root
    try:
        findings, tracked, text_files = scan_repository(root)
    except (OSError, subprocess.CalledProcessError, UnicodeError) as error:
        print(f"Tracked credential hygiene: ERROR ({type(error).__name__})", file=sys.stderr)
        return 2
    if findings:
        print("Tracked credential hygiene: FAIL", file=sys.stderr)
        for path, line, detector in findings:
            location = f"{path}:{line}" if line else path
            print(f"  - {location}: {detector}", file=sys.stderr)
        print(
            f"Inspected {tracked} tracked paths ({text_files} UTF-8 text files). "
            "Secret values were not printed.",
            file=sys.stderr,
        )
        return 1
    print(f"Tracked credential hygiene: PASS ({tracked} tracked paths; {text_files} UTF-8 text files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
